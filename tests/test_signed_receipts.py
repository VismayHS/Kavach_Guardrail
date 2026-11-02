"""F5: Ed25519-signed receipts an auditor verifies with the public key alone."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from kavach.receipts import ReceiptLog, verify_chain  # noqa: E402
from kavach.signing import Signer  # noqa: E402


def chain(n=4):
    log = ReceiptLog(key=b"operator-hmac-key", signer=Signer.generate())
    for i in range(n):
        log.append({"type": "decision", "i": i})
    return log


def test_receipts_carry_an_ed25519_signature_that_verifies_with_the_public_key():
    log = chain()
    out = verify_chain(log.items, public_pem=log.signer.public_pem)          # no HMAC key: the auditor's view
    assert out["valid"] and out["ed25519_verified"] == 4 and out["key_id"] == log.signer.key_id
    assert log.verify()["valid"]


def test_tampering_or_another_key_fails():
    log = chain()
    forged = [dict(r) for r in log.items]
    forged[1] = {**forged[1], "body": {"type": "decision", "i": 99}}
    assert not verify_chain(forged, public_pem=log.signer.public_pem)["valid"]
    other = Signer.generate()
    assert not verify_chain(log.items, public_pem=other.public_pem)["valid"]   # signed by someone else's key


def test_export_and_cli_verify(tmp_path):
    log = chain()
    f = tmp_path / "export.jsonl"
    f.write_text("".join(log.export_lines()))
    (tmp_path / "pub.pem").write_text(log.signer.public_pem)
    r = subprocess.run([sys.executable, "-m", "kavach.receipts", "verify", str(f), "--pubkey", str(tmp_path / "pub.pem")],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and json.loads(r.stdout)["ed25519_verified"] == 4
    lines = f.read_text().splitlines()
    lines[2] = lines[2].replace('"i": 1', '"i": 7')
    f.write_text("\n".join(lines) + "\n")
    bad = subprocess.run([sys.executable, "-m", "kavach.receipts", "verify", str(f)], capture_output=True, text=True,
                         cwd=ROOT)
    assert bad.returncode == 1


def test_keygen(tmp_path):
    r = subprocess.run([sys.executable, "-m", "kavach.receipts", "keygen", str(tmp_path)], capture_output=True,
                       text=True, cwd=ROOT)
    assert r.returncode == 0 and (tmp_path / "kavach_signing.pem").stat().st_mode & 0o777 == 0o600


def test_api_exports_the_chain_with_its_public_key(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", None)
    c = TestClient(server.app)
    c.post("/api/demo/benign_lookup")
    text = c.get("/api/receipts/export").text.splitlines()
    header, items = json.loads(text[0]), [json.loads(x) for x in text[1:]]
    assert header["public_key"] == c.get("/api/receipts/public-key").json()["public_key"]
    assert verify_chain(items, public_pem=header["public_key"])["valid"]


def test_rotated_keys_each_verify_their_own_receipts():
    a, b = Signer.generate(), Signer.generate()
    log = ReceiptLog(key=b"k" * 32, signer=a)
    log.append({"type": "decision", "n": 1})
    log.signer = b                                   # a new key (rotation, or a restart without a key file)
    log.append({"type": "decision", "n": 2})
    assert verify_chain(log.items, public_pems=[b.public_pem])["valid"] is False     # the old receipt needs its key
    out = verify_chain(log.items, public_pems=[a.public_pem, b.public_pem])
    assert out["valid"] and out["ed25519_verified"] == 2 and sorted(out["key_ids"]) == sorted([a.key_id, b.key_id])
    log.known_keys[a.key_id] = a.public_pem
    assert log.verify()["valid"]
    header = json.loads(next(log.export_lines()))
    assert header["public_key"] == b.public_pem and set(header["public_keys"]) == {a.public_pem, b.public_pem}
