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
