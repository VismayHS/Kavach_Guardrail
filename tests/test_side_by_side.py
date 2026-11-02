"""The demo's opening: one request, one inbox; the action the user asked for goes through, the injected one is stopped."""
from fastapi.testclient import TestClient

from kavach import server


def test_legit_goes_through_and_injected_is_stopped_in_the_same_task():
    r = TestClient(server.app).post("/api/demo/side-by-side").json()
    assert r["read"]["verdict"] == "ALLOW"
    assert r["legit"]["verdict"] == "ALLOW_WITH_SAFEGUARD" and r["legit"]["executed"]
    assert r["injected"]["verdict"] == "DENY" and r["injected"]["reason"].startswith("[R1]")
    assert "msg-4471" in r["injected"]["reason"] and r["hidden_instruction"]["id"] == "msg-4471"
    assert r["state"] == {"outbox": 0, "waiting": 1}           # John's email waits in its recall window; nothing else
    assert r["legit"]["receipt_id"] != r["injected"]["receipt_id"]
