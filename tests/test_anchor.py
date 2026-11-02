"""F5: anchoring the chain head (RFC 3161, Rekor), against stand-in services (nothing leaves the machine)."""
import base64
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.anchor import anchor_rekor, anchor_tsa, rekor_entry, timestamp_request  # noqa: E402
from kavach.receipts import ReceiptLog  # noqa: E402
from kavach.signing import Signer, load_public, verify  # noqa: E402


def log():
    lg = ReceiptLog(signer=Signer.generate())
    lg.append({"type": "decision"})
    return lg


@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl not installed")
def test_timestamp_request_is_valid_der(tmp_path):
    digest = hashlib.sha256(b"head").hexdigest()
    (tmp_path / "q.tsq").write_bytes(timestamp_request(digest))
    r = subprocess.run(["openssl", "ts", "-query", "-in", str(tmp_path / "q.tsq"), "-text"], capture_output=True, text=True)
    if r.returncode != 0 and "ts" in r.stderr and "invalid command" in r.stderr.lower():
        pytest.skip("this openssl has no 'ts' command")
    assert r.returncode == 0 and "sha256" in r.stdout.lower() and "Certificate required: yes" in r.stdout


def test_tsa_reply_is_recorded_as_an_anchor_receipt():
    seen = {}

    def tsa(request):
        seen["body"], seen["type"] = request.content, request.headers["content-type"]
        return httpx.Response(200, content=b"\x30\x03\x02\x01\x00", headers={"content-type": "application/timestamp-reply"})
    lg = log()
    out = anchor_tsa(lg, "https://tsa.example/tsr", transport=httpx.MockTransport(tsa))
    assert seen["type"] == "application/timestamp-query" and seen["body"] == timestamp_request(lg.items[0]["hash"])
    assert lg.items[-1]["body"]["type"] == "anchor" and out["receipt"] == lg.items[-1]["id"] and lg.verify()["valid"]


def test_rekor_entry_carries_a_verifiable_signature():
    lg = log()
    head = lg.items[-1]["hash"]
    e = rekor_entry(head, lg.signer)
    pub = load_public(base64.b64decode(e["spec"]["signature"]["publicKey"]["content"]).decode())
    assert verify(pub, head.encode(), e["spec"]["signature"]["content"])

    def rekor(request):
        assert json.loads(request.content)["kind"] == "hashedrekord"
        return httpx.Response(201, json={"24296fb24b8ad77a": {"logIndex": 42, "integratedTime": 1793600000}})
    out = anchor_rekor(lg, "https://rekor.example", transport=httpx.MockTransport(rekor))
    assert out["log_index"] == 42 and lg.items[-1]["body"]["uuid"] == "24296fb24b8ad77a"
