"""The HTTP API as a separate UI uses it: CORS, and the endpoints a front end builds on."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def client(monkeypatch):
    from fastapi.testclient import TestClient
    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", None)
    return TestClient(server.app)


def test_cors_allows_a_local_ui_in_dev(monkeypatch):
    c = client(monkeypatch)
    pre = c.options("/api/v1/check", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                                              "Access-Control-Request-Headers": "authorization,content-type"})
    assert pre.status_code == 200 and pre.headers["access-control-allow-origin"] == "http://localhost:5173"
    assert "authorization" in pre.headers["access-control-allow-headers"].lower()
    other = c.get("/api/scenarios", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in other.headers


def test_receipts_can_be_polled_after_a_seq(monkeypatch):
    c = client(monkeypatch)
    start = len(c.get("/api/receipts?limit=100000").json())
    c.post("/api/demo/benign_lookup")
    new = c.get(f"/api/receipts?after={start}").json()
    assert new and new[0]["seq"] == start + 1 and all(r["seq"] > start for r in new)


def test_event_stream_replays_receipts(monkeypatch):
    c = client(monkeypatch)
    c.post("/api/demo/email_injection")
    total = len(c.get("/api/receipts?limit=100000").json())
    with c.stream("GET", "/api/events?after=0&max_s=0") as r:
        assert r.headers["content-type"].startswith("text/event-stream")
        text = "".join(r.iter_text())
    ids = [int(line[4:]) for line in text.splitlines() if line.startswith("id: ")]
    assert ids == list(range(1, total + 1)) and "event: decision" in text
