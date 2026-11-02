"""Ed25519 signing for receipts and policy bundles (F5, F9).

An HMAC proves nothing to an auditor: whoever can check it can also forge it. An Ed25519 signature is checked with a
public key that cannot sign. KAVACH signs each receipt's chain hash; an exported chain carries the public key and its
id, and `python -m kavach.receipts verify` checks it with nothing secret.

    python -m kavach.receipts keygen keys/          # writes kavach_signing.pem (private) and kavach_signing.pub.pem
    export KAVACH_SIGNING_KEY=keys/kavach_signing.pem

Production: keep the private key in a KMS or Vault (sign through it; this class is the seam); without
KAVACH_SIGNING_KEY a key is generated per process, which is fine for a demo and useless for an audit.
"""
from __future__ import annotations

import base64
import hashlib
import os
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey


class Signer:
    def __init__(self, private_key: Ed25519PrivateKey, ephemeral: bool = False):
        self._key = private_key
        self.ephemeral = ephemeral
        raw = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        self.key_id = hashlib.sha256(raw).hexdigest()[:16]

    @classmethod
    def from_env(cls) -> "Signer":
        path = os.environ.get("KAVACH_SIGNING_KEY")
        if path:
            key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError(f"{path} is not an Ed25519 private key")
            return cls(key)
        return cls(Ed25519PrivateKey.generate(), ephemeral=True)

    @classmethod
    def generate(cls) -> "Signer":
        return cls(Ed25519PrivateKey.generate())

    def sign(self, data: bytes) -> str:
        return base64.b64encode(self._key.sign(data)).decode()

    @property
    def public_pem(self) -> str:
        return self._key.public_key().public_bytes(serialization.Encoding.PEM,
                                                   serialization.PublicFormat.SubjectPublicKeyInfo).decode()

    def private_pem(self) -> bytes:
        return self._key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption())


def load_public(pem: str) -> Ed25519PublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("not an Ed25519 public key")
    return key


def key_id(pub: Ed25519PublicKey) -> str:
    raw = pub.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return hashlib.sha256(raw).hexdigest()[:16]


def verify(pub: Ed25519PublicKey, data: bytes, sig_b64: str) -> bool:
    try:
        pub.verify(base64.b64decode(sig_b64), data)
        return True
    except (InvalidSignature, ValueError):
        return False
