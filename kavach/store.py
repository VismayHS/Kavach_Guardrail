"""Persistent state (E5) for what KAVACH itself must not forget across a restart.

    KAVACH_DB_URL=sqlite:////data/kavach.db                       # one file (the compose stack and Helm use this)
    KAVACH_DB_URL=postgresql+psycopg://kavach:pw@db/kavach         # a shared database (pip install psycopg)

What is kept:
  * the receipt chain, append-only, written before the decision returns. It is verified when loaded, so a row
    edited in the database makes /readyz fail instead of being trusted. Its signed checkpoint (count + head) goes to
    a separate file, so deleting the newest rows is caught too: `<db>.checkpoint.json` beside a SQLite file, or
    KAVACH_CHECKPOINT_FILE (needed for Postgres; in production, write-once storage apart from the database).
  * kill-switch pauses: a restart never silently un-pauses an agent.
  * undo windows (E6): held payments and queued emails, with what they will send and when they go, and which
    receipt can take each back, so Undo still works after a restart and nothing goes out early or twice.
  * tool pins: the definition hash a human approved, so a rug-pull is still caught after a restart.
  * human feedback (approve / refuse, with the action's features) and any risk model the learning loop promoted
    (E11), so a restart keeps the retrained model instead of falling back to the shipped one.

Approvals that were still waiting when the process stopped are closed as expired, with a receipt. The agent's
context (where each value came from) lived in memory, and approving a call without it would be approving blind; the
agent asks again. The demo company (CRM, files, inbox) is a simulator and is seeded fresh at each start.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

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
models = Table("kavach_risk_models", md, Column("id", Integer, primary_key=True, autoincrement=True),
               Column("data", Text, nullable=False))
labels = Table("kavach_feedback", md, Column("id", Integer, primary_key=True, autoincrement=True),
               Column("data", Text, nullable=False))
meta = Table("kavach_meta", md, Column("key", String(64), primary_key=True), Column("value", Text, nullable=False))

FINAL_APPROVAL = {"human-approved", "human-denied", "human-approved-draft", "human-approved-execution",
                  "approval-expired", "approval-closed-restart"}


def _dump(x) -> str:
    return json.dumps(x, default=str, sort_keys=True)


class Store:
    def __init__(self, url: str, checkpoint: str | os.PathLike | None = None):
        kw = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {"pool_pre_ping": True}
        self.engine = create_engine(url, **kw)
        md.create_all(self.engine)
        self.lock = threading.Lock()
        self.url = url
        db_file = self.engine.url.database if url.startswith("sqlite") else None
        where = checkpoint or os.environ.get("KAVACH_CHECKPOINT_FILE") or (
            f"{db_file}.checkpoint.json" if db_file and db_file != ":memory:" else None)
        self.checkpoint_path = Path(where) if where else None

    # ---------------------------------------------------------------- the receipt chain's signed checkpoint
    def read_checkpoint(self) -> dict | None:
        if self.checkpoint_path is None:
            return None
        try:
            return json.loads(self.checkpoint_path.read_text())
        except FileNotFoundError:
            return None

    def write_checkpoint(self, cp: dict) -> None:
        """Atomic, and only forward: a slower thread never moves the checkpoint back."""
        if self.checkpoint_path is None:
            return
        with self.lock:
            old = self.read_checkpoint()
            if old is not None and int(old.get("count", 0)) >= cp["count"]:
                return
            tmp = self.checkpoint_path.with_name(self.checkpoint_path.name + ".tmp")
            tmp.write_text(json.dumps(cp))
            os.replace(tmp, self.checkpoint_path)

    # ---------------------------------------------------------------- facts about the store itself
    def get_meta(self, key: str) -> str | None:
        with self.engine.connect() as c:
            r = c.execute(select(meta.c.value).where(meta.c.key == key)).first()
            return r.value if r else None

    def set_meta(self, key: str, value: str) -> None:
        with self.lock, self.engine.begin() as c:
            if c.execute(select(meta.c.key).where(meta.c.key == key)).first():
                c.execute(update(meta).where(meta.c.key == key).values(value=value))
            else:
                c.execute(insert(meta).values(key=key, value=value))

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

    def move_hold(self, h: dict, frm: tuple, to: str) -> str | None:
        """Move a hold to `to` only if the database still has it in one of `frm`, so of two workers (or a Cancel and
        a sweep) exactly one wins. Returns the status the database has now; None if it has never seen this hold."""
        with self.lock, self.engine.begin() as c:
            moved = c.execute(update(holds).where(holds.c.id == h["id"], holds.c.status.in_(frm))
                              .values(status=to, data=_dump({**h, "status": to}))).rowcount
            if moved:
                return to
            row = c.execute(select(holds.c.status).where(holds.c.id == h["id"])).first()
            return row.status if row else None

    def link_hold(self, hold_id: str, receipt: str) -> None:
        with self.lock, self.engine.begin() as c:
            c.execute(update(holds).where(holds.c.id == hold_id).values(receipt=receipt))

    def load_holds(self) -> list[tuple[dict, str | None]]:
        with self.engine.connect() as c:
            return [({**json.loads(r.data), "status": r.status}, r.receipt)
                    for r in c.execute(select(holds.c.data, holds.c.status, holds.c.receipt))]

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

    def save_model(self, model: dict) -> None:
        with self.lock, self.engine.begin() as c:
            c.execute(insert(models).values(data=_dump(model)))

    def latest_model(self) -> dict | None:
        with self.engine.connect() as c:
            r = c.execute(select(models.c.data).order_by(models.c.id.desc()).limit(1)).first()
            return json.loads(r.data) if r else None

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
    legacy = False
    if store.checkpoint_path is not None:
        gw.receipts.checkpoint = store.read_checkpoint()
        # a store that has ever had a checkpoint says so in its own table: then a missing file was removed. One
        # written before checkpoints existed has receipts and no such mark: it is adopted (receipted below), not
        # reported as tampered with, which was a false CHAIN BROKEN on every older demo database.
        had = store.get_meta("checkpointed") is not None
        legacy = bool(items) and gw.receipts.checkpoint is None and not had
        gw.receipts.checkpoint_missing = bool(items) and gw.receipts.checkpoint is None and had
    chain = gw.receipts.verify()
    restored = {"receipts": len(items), "chain_valid": chain["valid"]}
    for k in store.active_kills():
        gw.kills[k["id"]] = k
    learned = store.latest_model()
    if learned is not None:                       # E11: the last model the learning loop promoted
        from .risk import RiskModel
        gw.risk = RiskModel(model=learned)
    restored["risk_model"] = gw.risk.sha
    restored["kills"] = len(gw.kills)
    for name, h in store.load_pins().items():
        if name in gw.registry.specs:
            gw.registry.pins[name] = h
    by_id = {h["id"]: h for h in env.holds}
    n_held, cut_off = 0, []
    for h, receipt in store.load_holds():
        if h["id"] in by_id:
            continue
        env.holds.append(h)
        if h["status"] == "held":
            n_held += 1
            if receipt:
                gw.recall[receipt] = (env.epoch, h["id"])
        elif h["status"] == "dispatching":          # the last process died while handing it over
            cut_off.append((h, receipt))
    restored["holds_waiting"] = n_held
    env.claim = store.move_hold
    marked = [store.checkpoint_path is not None and store.get_meta("checkpointed") is not None]

    def on_receipt(rec: dict) -> None:
        store.append_receipt(rec)
        store.write_checkpoint(gw.receipts.checkpoint_for(rec))     # after the receipt itself is durable
        if store.checkpoint_path is not None and not marked[0]:
            store.set_meta("checkpointed", str(rec["seq"]))           # from here on, a missing file means removed
            marked[0] = True
        b = rec["body"]
        if b.get("type") == "kill":
            store.save_kill(gw.kills.get(b["id"]) or {k: b[k] for k in ("id", "scope", "target", "by", "reason", "at")},
                            True)
        elif b.get("type") == "resume":
            store.save_kill({"id": b["kill"]}, False)
    # a receipt is durable before any exporter sees it and before the decision returns; if the database refuses a
    # decision or approval receipt, that call fails and does not run (receipts.FAIL_CLOSED)
    gw.receipts.durable.append(on_receipt)
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
    if legacy and chain["valid"]:
        gw.receipts.append({"type": "checkpoint-started", "covers_from": len(items) + 1,
                            "reason": f"This store's {len(items)} receipts were written before signed checkpoints "
                                      "existed. The hash chain still covers them (edits break it); from here on, a "
                                      "checkpoint also catches receipts cut off the end."})
        restored["checkpoint_started"] = True
    for h, receipt in cut_off:                       # it may or may not have arrived: say so, never send it again
        if env._move(h, "dispatching", "unknown"):
            where = "the mail server" if h.get("kind") == "mail" else "the bank"
            gw.receipts.append({"type": "window-closed", "hold": h["id"], "kind": h.get("kind"), "outcome": "unknown",
                                "receipt": receipt, "task_id": gw._task_of(receipt),
                                "reason": f"KAVACH stopped while handing this to {where}, so whether it arrived is "
                                          f"unknown. It is not sent again; look for {h['id']} at {where}."})
    if cut_off:
        restored["holds_cut_off"] = len(cut_off)
    return restored
