"""Tamper-evident decision receipts.

Every decision is written as a structured receipt and chained: each receipt stores the SHA-256 of the previous one,
an HMAC over its own hash (the operator's integrity check) and, when a signer is configured, an Ed25519 signature
(the auditor's check: verifiable with the public key alone, see kavach/signing.py). Editing or deleting any past
receipt breaks verification from that point on.

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


class ReceiptLog:
    def __init__(self, key: bytes | None = None, signer=None):
        self.key = key or os.environ.get("KAVACH_RECEIPT_KEY", "demo-receipt-key").encode()
        self.signer = signer
        self.items: list[dict] = []
        self.lock = threading.Lock()
        self.listeners: list = []          # callables(receipt) after each append (telemetry, SIEM, persistence)

    def append(self, body: dict) -> dict:
        with self.lock:
            prev = self.items[-1]["hash"] if self.items else "0" * 64
            core = {"seq": len(self.items) + 1, "ts": round(time.time(), 3), "prev_hash": prev, "body": body}
            h = hashlib.sha256(_canon(core)).hexdigest()
            sig = hmac.new(self.key, h.encode(), hashlib.sha256).hexdigest()
            rec = {**core, "id": f"rcpt-{core['seq']:05d}", "hash": h, "sig": sig}
            if self.signer is not None:
                rec["ed25519"] = {"kid": self.signer.key_id, "sig": self.signer.sign(h.encode())}
            self.items.append(rec)
        for fn in list(self.listeners):
            try:
                fn(rec)
            except Exception:  # an exporter failing must never break the decision path
                pass
        return rec

    def get(self, rid: str) -> dict | None:
        return next((r for r in self.items if r["id"] == rid), None)

    def verify(self) -> dict:
        out = verify_chain(self.items, hmac_key=self.key,
                           public_pem=self.signer.public_pem if self.signer is not None else None)
        return out

    def export_lines(self):
        """JSONL: a header (public key, key id, head), then every receipt in order."""
        head = self.items[-1]["hash"] if self.items else "0" * 64
        yield json.dumps({"type": "kavach-receipts", "version": 1, "count": len(self.items), "head": head,
                          "public_key": self.signer.public_pem if self.signer is not None else None,
                          "kid": self.signer.key_id if self.signer is not None else None,
                          "ephemeral_key": bool(self.signer is not None and self.signer.ephemeral)}) + "\n"
        for r in list(self.items):
            yield json.dumps(r, default=str) + "\n"


def verify_chain(items: list[dict], hmac_key: bytes | None = None, public_pem: str | None = None) -> dict:
    """Recompute every hash and link; check the HMAC if the key is given and the Ed25519 signature if a public
    key is given (or carried in an export)."""
    from .signing import key_id, load_public, verify
    pub = load_public(public_pem) if public_pem else None
    kid = key_id(pub) if pub is not None else None
    prev, signed = "0" * 64, 0
    for r in items:
        core = {k: r[k] for k in ("seq", "ts", "prev_hash", "body")}
        h = hashlib.sha256(_canon(core)).hexdigest()
        ok = r["prev_hash"] == prev and h == r["hash"]
        if ok and hmac_key is not None:
            ok = hmac.compare_digest(r["sig"], hmac.new(hmac_key, h.encode(), hashlib.sha256).hexdigest())
        if ok and pub is not None:
            ed = r.get("ed25519") or {}
            ok = ed.get("kid") == kid and verify(pub, h.encode(), ed.get("sig", ""))
            signed += ok
        if not ok:
            return {"valid": False, "broken_at": r["id"], "checked": r["seq"]}
        prev = h
    return {"valid": True, "count": len(items), "head": prev[:16], "ed25519_verified": signed,
            "key_id": kid}


def _cli(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kavach.receipts")
    sub = ap.add_subparsers(dest="cmd", required=True)
    k = sub.add_parser("keygen", help="write an Ed25519 key pair")
    k.add_argument("dir")
    v = sub.add_parser("verify", help="verify an exported receipt chain (JSONL)")
    v.add_argument("file")
    v.add_argument("--pubkey", help="trusted public key PEM (default: the one in the export's header)")
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
    pem = Path(a.pubkey).read_text() if a.pubkey else header.get("public_key")
    out = verify_chain(items, public_pem=pem)
    if a.pubkey is None and pem:
        out["note"] = "checked against the key in the export's own header; pass --pubkey for a key you trust"
    print(json.dumps(out, indent=1))
    return 0 if out["valid"] else 1


if __name__ == "__main__":
    sys.exit(_cli())
