"""The server with KAVACH_DB_URL: a pause and the receipts survive a real process restart."""
import json
import subprocess
import sys
import tempfile

import pytest

pytest.importorskip("sqlalchemy")

SCRIPT = r"""
import json, os, sys
os.environ["KAVACH_DB_URL"] = sys.argv[1]
from fastapi.testclient import TestClient
from kavach import server
c = TestClient(server.app)
if sys.argv[2] == "first":
    c.post("/api/kill", json={"scope": "user", "target": "mallory", "reason": "drill"})
    c.post("/api/v1/check", json={"user_request": "count customers", "tool": "crm.query",
                                  "args": {"sql": "SELECT COUNT(*) FROM customers"}, "role": "analyst"})
print(json.dumps({"ready": c.get("/readyz").json(), "kills": c.get("/api/kill").json(),
                  "verify": c.get("/api/receipts/verify").json()}))
"""


def run(url, phase):
    out = subprocess.run([sys.executable, "-c", SCRIPT, url, phase], capture_output=True, text=True, timeout=120,
                         env={"PATH": "/usr/bin:/bin", "KAVACH_SWEEP_S": "0", "KAVACH_CANARIES": "0"})
    assert out.returncode == 0, out.stderr[-2000:]
    return json.loads(out.stdout.strip().splitlines()[-1])


def test_server_restores_state_from_the_database():
    url = f"sqlite:///{tempfile.mkdtemp()}/kavach.db"
    first = run(url, "first")
    assert first["ready"]["store"]["backend"] == "sqlite" and first["ready"]["store"]["restored"]["receipts"] == 0
    n = first["verify"]["count"]
    second = run(url, "second")
    restored = dict(second["ready"]["store"]["restored"])
    assert second["ready"]["ready"] and restored.pop("risk_model") and restored == {
        "receipts": n, "chain_valid": True, "kills": 1, "holds_waiting": 0, "approvals_closed": 0}
    assert [k["target"] for k in second["kills"]] == ["mallory"]
    assert second["verify"]["valid"] and len(second["verify"]["key_ids"]) == 2
