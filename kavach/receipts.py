"""Tamper-evident decision receipts.

Every decision is written as a structured receipt and chained: each receipt
stores the SHA-256 of the previous one and an HMAC over its own canonical JSON.
Editing or deleting any past receipt breaks verification from that point on.
(Production: anchor the chain head in WORM storage / sign with a KMS-held key.)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time


def _canon(d: dict) -> bytes:
    return json.dumps(d, sort_keys=True, separators=(",", ":"), default=str).encode()


class ReceiptLog:
    def __init__(self, key: bytes | None = None):
        self.key = key or os.environ.get("KAVACH_RECEIPT_KEY", "demo-receipt-key").encode()
        self.items: list[dict] = []
        self.lock = threading.Lock()

    def append(self, body: dict) -> dict:
        with self.lock:
            prev = self.items[-1]["hash"] if self.items else "0" * 64
            core = {"seq": len(self.items) + 1, "ts": round(time.time(), 3), "prev_hash": prev, "body": body}
            h = hashlib.sha256(_canon(core)).hexdigest()
            sig = hmac.new(self.key, h.encode(), hashlib.sha256).hexdigest()
            rec = {**core, "id": f"rcpt-{core['seq']:05d}", "hash": h, "sig": sig}
            self.items.append(rec)
            return rec

    def get(self, rid: str) -> dict | None:
        return next((r for r in self.items if r["id"] == rid), None)

    def verify(self) -> dict:
        prev = "0" * 64
        for r in self.items:
            core = {k: r[k] for k in ("seq", "ts", "prev_hash", "body")}
            h = hashlib.sha256(_canon(core)).hexdigest()
            ok_sig = hmac.compare_digest(r["sig"], hmac.new(self.key, h.encode(), hashlib.sha256).hexdigest())
            if r["prev_hash"] != prev or h != r["hash"] or not ok_sig:
                return {"valid": False, "broken_at": r["id"], "checked": r["seq"]}
            prev = h
        return {"valid": True, "count": len(self.items), "head": prev[:16]}
