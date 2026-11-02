"""Anchor the receipt chain's head outside KAVACH (F5): proof of *when* it existed and that it wasn't rewritten later.

    python -m kavach.anchor tsa https://freetsa.org/tsr       # RFC 3161 timestamp of the current head
    python -m kavach.anchor rekor https://rekor.sigstore.dev   # Sigstore Rekor transparency-log entry

Both send the head hash (and, for Rekor, the public key and a signature) to an outside service, so both are opt-in:
nothing is sent unless one of these is called. The response is stored as an "anchor" receipt, so the chain records
its own anchoring. An auditor checks a timestamp with `openssl ts -verify` and a Rekor entry with `rekor-cli`.
"""
from __future__ import annotations

import base64
import hashlib
import json
import sys

SHA256_OID = bytes.fromhex("0609608648016503040201")      # DER: OID 2.16.840.1.101.3.4.2.1


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, body: bytes) -> bytes:
    return bytes([tag]) + _der_len(len(body)) + body


def timestamp_request(digest_hex: str, nonce: int | None = None) -> bytes:
    """DER TimeStampReq (RFC 3161 section 2.4.1) for a SHA-256 digest, asking for the TSA's certificate."""
    digest = bytes.fromhex(digest_hex)
    if len(digest) != 32:
        raise ValueError("expected a SHA-256 digest")
    algorithm = _tlv(0x30, SHA256_OID + b"\x05\x00")                           # AlgorithmIdentifier, NULL params
    imprint = _tlv(0x30, algorithm + _tlv(0x04, digest))                        # MessageImprint
    parts = [_tlv(0x02, b"\x01"), imprint]                                      # version 1
    if nonce is not None:
        nb = nonce.to_bytes(max(1, (nonce.bit_length() + 8) // 8), "big")
        parts.append(_tlv(0x02, nb))
    parts.append(_tlv(0x01, b"\xff"))                                           # certReq TRUE
    return _tlv(0x30, b"".join(parts))


def anchor_tsa(receipts, tsa_url: str, transport=None) -> dict:
    """Timestamp the chain head with an RFC 3161 authority; record the token as an 'anchor' receipt."""
    import httpx
    head = receipts.items[-1]["hash"] if receipts.items else "0" * 64
    req = timestamp_request(head)
    with httpx.Client(transport=transport, timeout=20) as c:
        r = c.post(tsa_url, content=req, headers={"Content-Type": "application/timestamp-query"})
    r.raise_for_status()
    if r.headers.get("content-type", "").split(";")[0] != "application/timestamp-reply":
        raise ValueError(f"not a timestamp reply: {r.headers.get('content-type')}")
    rec = receipts.append({"type": "anchor", "method": "rfc3161", "service": tsa_url, "head": head,
                           "token_b64": base64.b64encode(r.content).decode()})
    return {"anchored": head, "receipt": rec["id"], "bytes": len(r.content)}


def rekor_entry(head: str, signer) -> dict:
    """A hashedrekord entry: the head hash, KAVACH's signature over it, and the public key."""
    return {"apiVersion": "0.0.1", "kind": "hashedrekord", "spec": {
        "data": {"hash": {"algorithm": "sha256", "value": hashlib.sha256(head.encode()).hexdigest()}},
        "signature": {"content": signer.sign(head.encode()),
                      "publicKey": {"content": base64.b64encode(signer.public_pem.encode()).decode()}}}}


def anchor_rekor(receipts, rekor_url: str, transport=None) -> dict:
    import httpx
    if receipts.signer is None:
        raise ValueError("Rekor anchoring needs a signing key (KAVACH_SIGNING_KEY)")
    head = receipts.items[-1]["hash"] if receipts.items else "0" * 64
    with httpx.Client(transport=transport, timeout=20) as c:
        r = c.post(f"{rekor_url.rstrip('/')}/api/v1/log/entries", json=rekor_entry(head, receipts.signer))
    r.raise_for_status()
    uuid, entry = next(iter(r.json().items()))
    rec = receipts.append({"type": "anchor", "method": "rekor", "service": rekor_url, "head": head, "uuid": uuid,
                           "log_index": entry.get("logIndex"), "integrated_time": entry.get("integratedTime")})
    return {"anchored": head, "receipt": rec["id"], "uuid": uuid, "log_index": entry.get("logIndex")}


def _cli(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m kavach.anchor")
    ap.add_argument("method", choices=("tsa", "rekor"))
    ap.add_argument("url")
    ap.add_argument("--server", default="http://localhost:8000", help="the KAVACH server whose chain to anchor")
    a = ap.parse_args(argv)
    import httpx
    out = httpx.post(f"{a.server}/api/receipts/anchor", params={"method": a.method, "url": a.url}, timeout=60).json()
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(_cli())
