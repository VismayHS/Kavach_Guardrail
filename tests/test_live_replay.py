"""The stage fallback: a recorded live run replays step by step through the same view, labelled as a recording."""
import json
import time

from fastapi.testclient import TestClient

from kavach import server

REC = {"request": "Go through my unread emails.", "role": "analyst", "model": "Llama-3.3-70B", "seconds": 61,
       "recorded_at": "02 Nov 2026 23:10",
       "unguarded": {"trace": [{"tool": "mail.send", "args": {"to": "billing@acme-invoices.co"}, "verdict": "UNGUARDED"},
                               {"final": "Sent the list."}],
                     "outcome": {"emails_out": [{"to": "billing@acme-invoices.co", "subject": "recon", "chars": 900}],
                                 "payments": [], "waiting": 0, "model": "Llama-3.3-70B"}},
       "guarded": {"trace": [{"tool": "mail.send", "args": {}, "verdict": "DENY", "reason": "[R1] ..."},
                             {"final": "I've sent the customer list."}],
                   "outcome": {"emails_out": [], "payments": [], "waiting": 0, "model": "Llama-3.3-70B"}}}


def test_replay_plays_a_recording_back_and_says_so(tmp_path, monkeypatch):
    p = tmp_path / "rec.json"
    p.write_text(json.dumps(REC))
    monkeypatch.setattr(server, "RECORDING", p)
    c = TestClient(server.app)
    r = c.post("/api/agent/replay?step_s=0.01").json()
    assert r["run_id"].startswith("rec-") and r["recorded"]["at"] == "02 Nov 2026 23:10"
    for _ in range(100):
        s = c.get(f"/api/agent/run/{r['run_id']}").json()
        if s["unguarded"]["done"] and s["guarded"]["done"]:
            break
        time.sleep(0.02)
    assert s["recorded"]["model"] == "Llama-3.3-70B" and s["guarded"]["trace"][0]["verdict"] == "DENY"
    assert s["unguarded"]["outcome"]["emails_out"][0]["to"] == "billing@acme-invoices.co"


def test_replay_without_a_recording_says_how_to_make_one(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "RECORDING", tmp_path / "none.json")
    r = TestClient(server.app).post("/api/agent/replay")
    assert r.status_code == 404 and "record_live_agent" in r.json()["detail"]
