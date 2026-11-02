"""F4: a session's evidence pack ties each control to the receipt that proves it."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.evidence import markdown, pack  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.scenarios import SCENARIOS, materialize, prepare  # noqa: E402


def test_injection_session_evidences_goal_hijack_and_logging():
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    sc = SCENARIOS["email_injection"]
    prepare(k.env, sc)
    tid, _ = k.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
    last = d = None
    for c in sc["steps"]:
        d = k.run(tid, materialize(c, last))
        last = d.result
    p = pack(k, tid)
    assert d.receipt_id in p["controls"]["ASI01"]                     # the R1 denial is the goal-hijack evidence
    assert d.receipt_id in p["controls"]["Art. 12"] and p["chain"]["valid"]
    md = markdown(p)
    assert "OWASP ASI01: Agent Goal Hijack" in md and "not a legal opinion" in md and d.receipt_id in md


def test_api_serves_md_html_and_json(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", None)
    c = TestClient(server.app)
    run = c.post("/api/demo/ap_sanctioned_vendor").json()
    tid = run["task_id"]
    md = c.get(f"/api/evidence/{tid}").text
    assert "RBI DPSC" in md and "R21" in md
    assert c.get(f"/api/evidence/{tid}?format=html").text.startswith("<!doctype html>")
    assert c.get(f"/api/evidence/{tid}?format=json").json()["task"]["task_id"] == tid
    assert c.get("/api/evidence/task-nope").status_code == 404
