"""F3: the kill switch. Pause now; nothing in scope runs; what was waiting is taken back; resume is receipted."""
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import PAYMENT_HOLD_S, Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.scenarios import SCENARIOS, materialize, prepare  # noqa: E402

SECRET = "kavach-test-secret-at-least-32-bytes-long"


@pytest.fixture()
def gw():
    return Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))


def replay(gw, name):
    sc = SCENARIOS[name]
    prepare(gw.env, sc)
    tid, _ = gw.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
    last, steps = None, []
    for c in sc["steps"]:
        d = gw.run(tid, materialize(c, last))
        steps.append(d)
        last = d.result
    return tid, steps


def test_a_paused_task_runs_nothing_and_its_held_payment_is_cancelled(gw):
    tid, steps = replay(gw, "ap_clean_release")
    assert steps[-1].verdict == Verdict.ALLOW_WITH_SAFEGUARD and gw.env.holds[-1]["status"] == "held"
    out = gw.kill("task", tid, "ops", "investigating")
    assert out["cancelled"] == [steps[-1].result["held"]]
    gw.env.settle_due(time.time() + PAYMENT_HOLD_S)
    assert gw.env.ledger == []                                         # the money never left
    d = gw.check(tid, ToolCall("invoice.read", {"invoice_id": "INV-3001"}))
    assert d.verdict == Verdict.DENY and d.reason.startswith("[KILL] Paused by ops")
    other, _ = gw.start_task("asha", "support", "What is the status of invoice 1042?")
    assert gw.check(other, ToolCall("crm.query", {"sql": "SELECT status FROM invoices WHERE id = 1042"})).verdict \
        == Verdict.ALLOW                                               # other tasks keep working


def test_global_kill_closes_pending_approvals_and_resume_is_receipted(gw):
    tid, steps = replay(gw, "ap_cfo_tier")
    hid = steps[-1].hitl_id
    k = gw.kill("global", None, "ops", "incident")
    assert hid in k["approvals_closed"] and gw.hitl.items[hid]["status"] == "killed"
    with pytest.raises(ValueError):
        gw.resolve_hitl(hid, "cfo@infycorp.com", True, approver_role="cfo")   # nothing to approve any more
    new, _ = gw.start_task("asha", "support", "What is the status of invoice 1042?")
    assert gw.check(new, ToolCall("crm.query", {"sql": "SELECT 1"})).verdict == Verdict.DENY
    gw.resume(k["id"], "ops")
    assert gw.check(new, ToolCall("crm.query", {"sql": "SELECT 1"})).verdict == Verdict.ALLOW
    kinds = [r["body"]["type"] for r in gw.receipts.items]
    assert "kill" in kinds and "resume" in kinds and gw.receipts.verify()["valid"]


def test_role_and_user_scopes(gw):
    a, _ = gw.start_task("asha", "support", "Status of invoice 1042?")
    b, _ = gw.start_task("ravi", "analyst", "Status of invoice 1042?")
    gw.kill("role", "support", "ops")
    q = ToolCall("crm.query", {"sql": "SELECT 1"})
    assert gw.check(a, q).verdict == Verdict.DENY and gw.check(b, q).verdict == Verdict.ALLOW
    with pytest.raises(ValueError):
        gw.kill("user", None, "ops")                                   # a user kill needs a target


def test_only_an_admin_can_pause_or_resume(monkeypatch):
    from fastapi.testclient import TestClient
    from kavach import auth, server
    monkeypatch.setattr(server, "AUTH_SECRET", SECRET)
    c = TestClient(server.app)
    hdr = lambda u, r: {"Authorization": "Bearer " + auth.mint(u, r, secret=SECRET)}  # noqa: E731
    assert c.post("/api/kill", headers=hdr("ravi", "analyst"), json={"scope": "global"}).status_code == 403
    k = c.post("/api/kill", headers=hdr("ops", "admin"), json={"scope": "user", "target": "mallory"}).json()
    assert k["by"] == "ops" and [x["id"] for x in c.get("/api/kill", headers=hdr("ops", "admin")).json()] == [k["id"]]
    assert c.delete(f"/api/kill/{k['id']}", headers=hdr("ravi", "analyst")).status_code == 403
    assert c.delete(f"/api/kill/{k['id']}", headers=hdr("ops", "admin")).json()["resumed"] == k["id"]
