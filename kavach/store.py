"""Persistent state (E5) for what KAVACH itself must not forget across a restart.

    KAVACH_DB_URL=sqlite:////data/kavach.db                       # one file (the compose stack and Helm use this)
    KAVACH_DB_URL=postgresql+psycopg://kavach:pw@db/kavach         # a shared database (pip install psycopg)

What is kept:
  * the receipt chain, append-only, written before the decision returns. It is verified when loaded, so a row
    edited in the database makes /readyz fail instead of being trusted.
  * kill-switch pauses: a restart never silently un-pauses an agent.
  * undo windows (E6): held payments and queued emails, with what they will send and when they go, and which
    receipt can take each back, so Undo still works after a restart and nothing goes out early or twice.
  * tool pins: the definition hash a human approved, so a rug-pull is still caught after a restart.

Approvals that were still waiting when the process stopped are closed as expired, with a receipt. The agent's
context (where each value came from) lived in memory, and approving a call without it would be approving blind; the
agent asks again. The demo company (CRM, files, inbox) is a simulator and is seeded fresh at each start.
"""
from __future__ import annotations

import json
import threading

from sqlalchemy import (Boolean, Column, Float, Integer, MetaData, String, Table, Text, create_engine, insert, select,
                        update)

md = MetaData()
receipts = Table("kavach_receipts", md, Column("seq", Integer, primary_key=True, autoincrement=False),
                 Column("rid", String(32), nullable=False, unique=True), Column("data", Text, nullable=False))
kills = Table("kavach_kills", md, Column("id", String(32), primary_key=True), Column("data", Text, nullable=False),
              Column("active", Boolean, nullable=False))
holds = Table("kavach_holds", md, Column("id", String(40), primary_key=True), Column("status", String(16)),
              Column("settles_at", Float), Column("receipt", String(32)), Column("data", Text, nullable=False))
pins = Table("kavach_tool_pins", md, Column("name", String(128), primary_key=True),
             Column("hash", String(80), nullable=False))
keys = Table("kavach_signing_keys", md, Column("kid", String(64), primary_key=True),
             Column("public_pem", Text, nullable=False))
labels = Table("kavach_feedback", md, Column("id", Integer, primary_key=True, autoincrement=True),
               Column("data", Text, nullable=False))

FINAL_APPROVAL = {"human-approved", "human-denied", "human-approved-draft", "human-approved-execution",
                  "approval-expired", "approval-closed-restart"}


def _dump(x) -> str:
    return json.dumps(x, default=str, sort_keys=True)


class Store:
    def __init__(self, url: str):
        kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        self.engine = create_engine(url, **kw)
        md.create_all(self.engine)
        self.lock = threading.Lock()
        self.url = url

    # ---------------------------------------------------------------- receipts
    def append_receipt(self, rec: dict) -> None:
        with self.lock, self.engine.begin() as c:
            c.execute(insert(receipts).values(seq=rec["seq"], rid=rec["id"], data=_dump(rec)))

    def load_receipts(self) -> list[dict]:
        with self.engine.connect() as c:
            return [json.loads(r.data) for r in c.execute(select(receipts.c.data).order_by(receipts.c.seq))]

    def save_key(self, kid: str, pem: str) -> None:
        with self.lock, self.engine.begin() as c:
            if not c.execute(select(keys.c.kid).where(keys.c.kid == kid)).first():
                c.execute(insert(keys).values(kid=kid, public_pem=pem))

    def load_keys(self) -> dict[str, str]:
        with self.engine.connect() as c:
            return {r.kid: r.public_pem for r in c.execute(select(keys.c.kid, keys.c.public_pem))}

    # ---------------------------------------------------------------- kill switch
    def save_kill(self, k: dict, active: bool) -> None:
        with self.lock, self.engine.begin() as c:
            if c.execute(select(kills.c.id).where(kills.c.id == k["id"])).first():
                c.execute(update(kills).where(kills.c.id == k["id"]).values(active=active))
            else:
                c.execute(insert(kills).values(id=k["id"], data=_dump(k), active=active))

    def active_kills(self) -> list[dict]:
        with self.engine.connect() as c:
            return [json.loads(r.data) for r in c.execute(select(kills.c.data).where(kills.c.active.is_(True)))]

    # ---------------------------------------------------------------- undo windows
    def save_hold(self, h: dict, receipt: str | None = None) -> None:
        with self.lock, self.engine.begin() as c:
            row = c.execute(select(holds.c.receipt).where(holds.c.id == h["id"])).first()
            vals = {"status": h["status"], "settles_at": h.get("settles_at"), "data": _dump(h)}
            if row:
                if receipt:
                    vals["receipt"] = receipt
                c.execute(update(holds).where(holds.c.id == h["id"]).values(**vals))
            else:
                c.execute(insert(holds).values(id=h["id"], receipt=receipt, **vals))

    def link_hold(self, hold_id: str, receipt: str) -> None:
        with self.lock, self.engine.begin() as c:
            c.execute(update(holds).where(holds.c.id == hold_id).values(receipt=receipt))

    def load_holds(self) -> list[tuple[dict, str | None]]:
        with self.engine.connect() as c:
            return [(json.loads(r.data), r.receipt) for r in c.execute(select(holds.c.data, holds.c.receipt))]

    # ---------------------------------------------------------------- tool pins
    def save_pin(self, name: str, h: str) -> None:
        with self.lock, self.engine.begin() as c:
            c.execute(pins.delete().where(pins.c.name == name))
            c.execute(insert(pins).values(name=name, hash=h))

    def load_pins(self) -> dict[str, str]:
        with self.engine.connect() as c:
            return {r.name: r.hash for r in c.execute(select(pins.c.name, pins.c.hash))}

    # ---------------------------------------------------------------- human feedback (E11 learning loop)
    def add_label(self, lab: dict) -> None:
        with self.lock, self.engine.begin() as c:
            c.execute(insert(labels).values(data=_dump(lab)))

    def load_labels(self) -> list[dict]:
        with self.engine.connect() as c:
            return [json.loads(r.data) for r in c.execute(select(labels.c.data).order_by(labels.c.id))]


def open_approvals(items: list[dict]) -> list[tuple[str, str | None]]:
    """(hitl id, task id) of approvals the receipt chain shows as opened and never closed."""
    opened, closed = {}, set()
    for r in items:
        b = r["body"]
        d = b.get("decision") or {}
        if b.get("type") == "decision" and d.get("verdict") == "ESCALATE" and d.get("hitl_id"):
            opened[d["hitl_id"]] = b.get("task_id")
        if b.get("type") in FINAL_APPROVAL and b.get("hitl"):
            closed.add(b["hitl"])
        if b.get("type") == "kill":
            closed.update(b.get("approvals_closed") or [])
    return [(h, t) for h, t in opened.items() if h not in closed]


def attach(gw, store: Store) -> dict:
    """Load what the last process left, then keep it current. Call before the first decision."""
    env = gw.env
    signer = gw.receipts.signer
    if signer is not None:            # every key that ever signed stays known: old receipts verify with their own key
        store.save_key(signer.key_id, signer.public_pem)
    gw.receipts.known_keys.update(store.load_keys())
    items = store.load_receipts()
    gw.receipts.items[:] = items
    chain = gw.receipts.verify()
    restored = {"receipts": len(items), "chain_valid": chain["valid"]}
    for k in store.active_kills():
        gw.kills[k["id"]] = k
    restored["kills"] = len(gw.kills)
    for name, h in store.load_pins().items():
        if name in gw.registry.specs:
            gw.registry.pins[name] = h
    by_id = {h["id"]: h for h in env.holds}
    n_held = 0
    for h, receipt in store.load_holds():
        if h["id"] in by_id:
            continue
        env.holds.append(h)
        if h["status"] == "held":
            n_held += 1
            if receipt:
                gw.recall[receipt] = (env.epoch, h["id"])
    restored["holds_waiting"] = n_held
    def on_receipt(rec: dict) -> None:
        store.append_receipt(rec)
        b = rec["body"]
        if b.get("type") == "kill":
            store.save_kill(gw.kills.get(b["id"]) or {k: b[k] for k in ("id", "scope", "target", "by", "reason", "at")},
                            True)
        elif b.get("type") == "resume":
            store.save_kill({"id": b["kill"]}, False)
    # the store first: a receipt is durable before any exporter sees it, and before the decision returns
    gw.receipts.listeners.insert(0, on_receipt)
    env.on_hold.append(lambda h: store.save_hold(h))
    gw.on_recall.append(lambda receipt, ref: store.link_hold(ref, receipt) if str(ref).startswith("hold-") else None)
    gw.registry.on_approve.append(store.save_pin)
    gw.hitl.on_label.append(store.add_label)
    gw.store = store
    stale = open_approvals(items) if chain["valid"] else []
    for hid, task_id in stale:
        gw.receipts.append({"type": "approval-closed-restart", "hitl": hid, "task_id": task_id,
                            "reason": "KAVACH restarted while this approval was waiting; the agent's context was not "
                                      "kept, so the approval is closed (denied). The agent can ask again."})
    restored["approvals_closed"] = len(stale)
    return restored
