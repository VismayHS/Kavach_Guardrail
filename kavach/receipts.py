"""Tamper-evident decision receipts.

Every decision is written as a structured receipt and chained: each receipt
stores the SHA-256 of the previous one and an HMAC over its own canonical JSON.
Editing a receipt, or deleting any but the newest, breaks the chain from that point on.

A chain can't tell that it was cut short, so after every receipt a signed checkpoint
(count + head hash) is kept apart from the log (U10): in memory, and with a Store in
a separate anchor file. verify() checks the log still reaches that checkpoint.
Anyone holding the signing key can rewrite everything, so persistent deployments must
set KAVACH_RECEIPT_KEY (production: a KMS-held key, checkpoints on WORM storage).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time

DEFAULT_KEY = "demo-receipt-key"


class TamperedLog(RuntimeError):
    """The stored receipt log fails verification; a server must not serve on top of it."""


def _canon(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode()


class ReceiptLog:
    def __init__(self, key: bytes | None = None, store=None):
        self.key = key or os.environ.get("KAVACH_RECEIPT_KEY", DEFAULT_KEY).encode()
        self.store = store
        self.items: list[dict] = store.receipts() if store else []
        self.anchor: dict | None = store.read_anchor() if store else None
        self.lock = threading.Lock()
        if store:
            if self.items and self.anchor is None:
                raise TamperedLog(f"{len(self.items)} stored receipts but no anchor checkpoint: the anchor file "
                                  f"{store.anchor_path} was removed")
            v = self.verify()
            if not v["valid"]:
                raise TamperedLog(f"receipt log fails verification ({v['reason']}); refusing to start on it")

    def _sign(self, msg: str) -> str:
        return hmac.new(self.key, msg.encode(), hashlib.sha256).hexdigest()

    def append(self, body: dict) -> dict:
        with self.lock:
            prev = self.items[-1]["hash"] if self.items else "0" * 64
            core = {"seq": len(self.items) + 1, "ts": round(time.time(), 3), "prev_hash": prev, "body": body}
            h = hashlib.sha256(_canon(core)).hexdigest()
            rec = {**core, "id": f"rcpt-{core['seq']:05d}", "hash": h, "sig": self._sign(h)}
            if self.store:
                self.store.add_receipt(rec)
            self.items.append(rec)
            self.anchor = {"count": rec["seq"], "head": h, "sig": self._sign(f"{rec['seq']}:{h}")}
            if self.store:
                self.store.write_anchor(self.anchor)
            return rec

    def get(self, rid: str) -> dict | None:
        return next((r for r in self.items if r["id"] == rid), None)

    def verify(self) -> dict:
        prev = "0" * 64
        for r in self.items:
            core = {k: r[k] for k in ("seq", "ts", "prev_hash", "body")}
            h = hashlib.sha256(_canon(core)).hexdigest()
            ok_sig = hmac.compare_digest(r["sig"], self._sign(h))
            if r["prev_hash"] != prev or h != r["hash"] or not ok_sig:
                return {"valid": False, "broken_at": r["id"], "checked": r["seq"],
                        "reason": "chain: a receipt was edited or removed"}
            prev = h
        a = self.anchor
        if a is not None:
            if not hmac.compare_digest(str(a.get("sig", "")), self._sign(f"{a.get('count')}:{a.get('head')}")):
                return {"valid": False, "broken_at": None, "checked": len(self.items),
                        "reason": "anchor: the checkpoint's signature is wrong"}
            n = int(a["count"])
            if len(self.items) < n or (n and self.items[n - 1]["hash"] != a["head"]):
                return {"valid": False, "broken_at": f"rcpt-{min(len(self.items), n) + 1:05d}", "checked": len(self.items),
                        "reason": f"anchor: the last signed checkpoint covers {n} receipts, the log has {len(self.items)}"}
        return {"valid": True, "count": len(self.items), "head": prev[:16]}
