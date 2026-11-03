"""Tamper-evident decision receipts.

Every decision is written as a structured receipt and chained: each receipt stores the SHA-256 of the previous one,
an HMAC over its own hash (the operator's integrity check) and, when a signer is configured, an Ed25519 signature
(the auditor's check: verifiable with the public key alone, see kavach/signing.py). Editing or deleting any past
receipt breaks verification from that point on.

A chain can't tell that it was cut short (deleting the newest receipts leaves a valid chain), so each receipt also
moves a signed checkpoint (count + head hash). The store keeps it in a file apart from the database
(kavach/store.py); verify() checks that the log still reaches it.

    python -m kavach.receipts keygen keys/                         # an Ed25519 signing key pair
    python -m kavach.receipts verify receipts.jsonl [--pubkey k.pem]   # check an exported chain, nothing secret needed
Export: GET /api/receipts/export (JSONL: a header with the public key, then every receipt).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from pathlib import Path


def _canon(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode()


# Receipts that come before an effect: a decision (the call runs after it), a person's approval (the approved call runs
# after it) and Send now. If the durable store can't take one of these, it is not kept and the caller gets
# ReceiptWriteError, so nothing runs without its record. Receipts written after an effect (a window closing, an undo,
# a kill) are about something that already happened: they stay in memory, and the log is marked degraded.
FAIL_CLOSED = {"decision", "human-approved-execution", "released-early"}


class ReceiptWriteError(RuntimeError):
    """The durable store refused a receipt that must exist before its action runs; the action did not run."""


class ReceiptLog:
    def __init__(self, key: bytes | None = None, signer=None):
        self.key = key or os.environ.get("KAVACH_RECEIPT_KEY", "demo-receipt-key").encode()
        self.signer = signer
        self.items: list[dict] = []
        self.lock = threading.Lock()
        self.listeners: list = []          # callables(receipt) after each append (telemetry, SIEM): best effort
        self.durable: list = []            # callables(receipt) that make it durable (the store): run in order, and a
                                           # failure is not swallowed (see FAIL_CLOSED)
        self.write_failures = 0            # receipts the durable store refused
        self.degraded: str | None = None   # the last such failure, for /readyz and the metrics
        self.known_keys: dict[str, str] = {}   # kid -> public PEM of keys that signed earlier receipts (rotation,
                                               # or a restart with a new key): old receipts verify with their own key
        self.checkpoint: dict | None = None    # {count, head, sig} of the newest receipt
        self.checkpoint_missing = False        # receipts were restored but their checkpoint is gone (store sets it)

    def append(self, body: dict) -> dict:
        with self.lock:
            prev = self.items[-1]["hash"] if self.items else "0" * 64
            core = {"seq": len(self.items) + 1, "ts": round(time.time(), 3), "prev_hash": prev, "body": body}
            h = hashlib.sha256(_canon(core)).hexdigest()
            sig = hmac.new(self.key, h.encode(), hashlib.sha256).hexdigest()
            rec = {**core, "id": f"rcpt-{core['seq']:05d}", "hash": h, "sig": sig}
            if self.signer is not None:
                rec["ed25519"] = {"kid": self.signer.key_id, "sig": self.signer.sign(h.encode())}
            before = self.checkpoint
            self.items.append(rec)
            self.checkpoint = self.checkpoint_for(rec)
            for fn in list(self.durable):          # inside the lock: the store sees receipts in chain order
                try:
                    fn(rec)
                except Exception as e:
                    self.write_failures += 1
                    self.degraded = f"{type(e).__name__}: {e}"[:300]
                    if body.get("type") in FAIL_CLOSED:
                        self.items.pop()           # not kept: the chain stays as the store has it
                        self.checkpoint = before
                        raise ReceiptWriteError(f"the receipt store refused the {body.get('type')} receipt "
                                                f"({type(e).__name__}); nothing ran") from e
        for fn in list(self.listeners):
            try:
                fn(rec)
            except Exception:  # an exporter failing must never break the decision path
                pass
        return rec

    def get(self, rid: str) -> dict | None:
        return next((r for r in self.items if r["id"] == rid), None)

    def public_keys(self) -> list[str]:
        cur = [self.signer.public_pem] if self.signer is not None else []
        return cur + [p for p in self.known_keys.values() if p not in cur]

    def checkpoint_for(self, rec: dict) -> dict:
        return {"count": rec["seq"], "head": rec["hash"],
                "sig": hmac.new(self.key, f"{rec['seq']}:{rec['hash']}".encode(), hashlib.sha256).hexdigest()}

    def verify(self) -> dict:
        out = verify_chain(self.items, hmac_key=self.key, public_pems=self.public_keys() or None)
        if not out["valid"]:
            return {**out, "reason": "chain: a receipt was edited or removed"}
        n = len(self.items)
        if self.checkpoint_missing:
            return {"valid": False, "broken_at": None, "checked": n,
                    "reason": "checkpoint: missing, though receipts were stored (the checkpoint file was removed)"}
        cp = self.checkpoint
        if cp is not None:
            want = hmac.new(self.key, f"{cp.get('count')}:{cp.get('head')}".encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(str(cp.get("sig", "")), want):
                return {"valid": False, "broken_at": None, "checked": n,
                        "reason": "checkpoint: its signature is wrong"}
            k = int(cp["count"])
            if n < k or (k and self.items[k - 1]["hash"] != cp["head"]):
                return {"valid": False, "broken_at": f"rcpt-{min(n, k) + 1:05d}", "checked": n,
                        "reason": f"checkpoint: the last signed checkpoint covers {k} receipts, the log has {n}"}
        return out

    def export_lines(self):
        """JSONL: a header (public key, key id, head), then every receipt in order."""
        head = self.items[-1]["hash"] if self.items else "0" * 64
        yield json.dumps({"type": "kavach-receipts", "version": 1, "count": len(self.items), "head": head,
                          "public_key": self.signer.public_pem if self.signer is not None else None,
                          "public_keys": self.public_keys(),
                          "kid": self.signer.key_id if self.signer is not None else None,
                          "ephemeral_key": bool(self.signer is not None and self.signer.ephemeral)}) + "\n"
        for r in list(self.items):
            yield json.dumps(r, default=str) + "\n"


def verify_chain(items: list[dict], hmac_key: bytes | None = None, public_pem: str | None = None,
                 public_pems: list[str] | None = None) -> dict:
    """Recompute every hash and link; check the HMAC if the key is given and the Ed25519 signature if public keys
    are given (or carried in an export). Each receipt must verify with the key it names (kid), and that key must be
    one of the trusted ones."""
    from .signing import key_id, load_public, verify
    pems = [p for p in ([public_pem] if public_pem else []) + list(public_pems or []) if p]
    keys = {key_id(k): k for k in (load_public(p) for p in pems)}
    kid = next(iter(keys), None)
    prev, signed = "0" * 64, 0
    for r in items:
        core = {k: r[k] for k in ("seq", "ts", "prev_hash", "body")}
        h = hashlib.sha256(_canon(core)).hexdigest()
        ok = r["prev_hash"] == prev and h == r["hash"]
        if ok and hmac_key is not None:
            ok = hmac.compare_digest(r["sig"], hmac.new(hmac_key, h.encode(), hashlib.sha256).hexdigest())
        if ok and keys:
            ed = r.get("ed25519") or {}
            pub = keys.get(ed.get("kid"))
            ok = pub is not None and verify(pub, h.encode(), ed.get("sig", ""))
            signed += ok
        if not ok:
            return {"valid": False, "broken_at": r["id"], "checked": r["seq"]}
        prev = h
    return {"valid": True, "count": len(items), "head": prev[:16], "ed25519_verified": signed,
            "key_id": kid, "key_ids": sorted(keys)}


def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kavach.receipts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen", help="write an Ed25519 key pair")
    k.add_argument("dir")
    v = sub.add_parser("verify", help="verify an exported receipt chain (JSONL)")
    v.add_argument("file")
    v.add_argument("--pubkey", action="append", help="trusted public key PEM, repeatable (default: the keys in the "
                                                     "export's header)")
    a = ap.parse_args(argv)
    if a.cmd == "keygen":
        from .signing import Signer
        s, d = Signer.generate(), Path(a.dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "kavach_signing.pem").write_bytes(s.private_pem())
        os.chmod(d / "kavach_signing.pem", 0o600)
        (d / "kavach_signing.pub.pem").write_text(s.public_pem)
        print(f"key id {s.key_id}: {d / 'kavach_signing.pem'} (keep secret), {d / 'kavach_signing.pub.pem'}")
        return 0
    lines = [json.loads(x) for x in Path(a.file).read_text().splitlines() if x.strip()]
    header, items = (lines[0], lines[1:]) if lines and lines[0].get("type") == "kavach-receipts" else ({}, lines)
    pems = [Path(p).read_text() for p in a.pubkey] if a.pubkey else (header.get("public_keys") or
                                                                     [header.get("public_key")])
    out = verify_chain(items, public_pems=[p for p in pems if p])
    if a.pubkey is None and any(pems):
        out["note"] = "checked against the key in the export's own header; pass --pubkey for a key you trust"
    print(json.dumps(out, indent=1))
    return 0 if out["valid"] else 1


if __name__ == "__main__":
    sys.exit(_cli())
