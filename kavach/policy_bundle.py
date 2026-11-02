"""Sign and verify policy files (F9). With KAVACH_POLICY_PUBKEY set, KAVACH loads a policy only if its signature
(<file>.sig, next to it) verifies: a policy change has to come from whoever holds the signing key.

    python -m kavach.policy_bundle sign kavach/policies/default.yaml --key keys/kavach_signing.pem
    python -m kavach.policy_bundle verify kavach/policies/default.yaml --pubkey keys/kavach_signing.pub.pem
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sign(policy: Path, key_path: Path) -> Path:
    from cryptography.hazmat.primitives import serialization

    from .signing import Signer
    signer = Signer(serialization.load_pem_private_key(key_path.read_bytes(), password=None))
    digest = hashlib.sha256(policy.read_bytes()).hexdigest()
    out = policy.with_name(policy.name + ".sig")
    out.write_text(json.dumps({"file": policy.name, "sha256": digest, "kid": signer.key_id,
                               "sig": signer.sign(digest.encode())}, indent=1))
    return out


def verify(policy: Path, pub_path: Path) -> bool:
    from .signing import key_id, load_public
    from .signing import verify as ok
    s = json.loads(policy.with_name(policy.name + ".sig").read_text())
    key = load_public(pub_path.read_text())
    digest = hashlib.sha256(policy.read_bytes()).hexdigest()
    return s["sha256"] == digest and s["kid"] == key_id(key) and ok(key, digest.encode(), s["sig"])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m kavach.policy_bundle")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sign")
    s.add_argument("policy")
    s.add_argument("--key", required=True)
    v = sub.add_parser("verify")
    v.add_argument("policy")
    v.add_argument("--pubkey", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "sign":
        print(sign(Path(a.policy), Path(a.key)))
        return 0
    good = verify(Path(a.policy), Path(a.pubkey))
    print("valid" if good else "INVALID")
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
