"""Real and scripted never mix. With KAVACH on a real Gmail (KAVACH_MAIL=gmail, scripts/gmail_up.sh), the scripted
scenarios that play on the made-up demo company are refused: run on the real mailbox they would read real mail, and
the 'without KAVACH' button would send the demo customer list to an outside address through the real account."""
import pytest


@pytest.fixture()
def real(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    monkeypatch.setattr(server, "MAIL_MODE", "gmail")
    return TestClient(server.app)


@pytest.mark.parametrize("path, body", [("/api/demo/side-by-side", None), ("/api/demo/email_injection", None),
                                        ("/api/stage/direct-send", {"leak": True}), ("/api/stage/reset", None)])
def test_scripted_scenarios_are_refused_on_real_mail(real, path, body):
    r = real.post(path, json=body) if body else real.post(path)
    assert r.status_code == 409 and "real Gmail" in r.json()["detail"]


def test_real_agents_still_work_and_the_mode_is_shown(real):
    rpc = lambda method, params: real.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method,  # noqa: E731
                                                         "params": params}).json()
    assert rpc("tools/list", {})["result"]["tools"]
    assert real.get("/api/state").json()["mail"]["mode"] == "gmail"
