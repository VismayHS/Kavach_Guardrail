import json
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.explain import Explainer  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.hitl import ApprovalQueue  # noqa: E402
from kavach.intent import IntentJudge  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.scenarios import SCENARIOS, materialize  # noqa: E402


@pytest.fixture()
def gw():
    return Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))


def replay(gw, name):
    sc = SCENARIOS[name]
    gw.env.reset()
    tid, plan = gw.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
    out, last = [], None
    for c in sc["steps"]:
        d = gw.run(tid, materialize(c, last))
        out.append(d)
        last = d.result
    return tid, plan, out


def test_injection_exfiltration_is_denied_by_provenance(gw):
    _, plan, steps = replay(gw, "email_injection")
    assert plan["verdict"] == "CAUTION" and plan["findings"][0]["code"] == "P1"
    send = steps[-1]
    assert send.verdict == Verdict.DENY and send.reason.startswith("[R1]")
    assert gw.env.outbox == []                       # nothing left the company


def test_injected_payment_is_denied(gw):
    _, _, steps = replay(gw, "payment_injection")
    assert steps[-1].verdict == Verdict.DENY and gw.env.ledger == []


def test_reversible_update_is_safeguarded_and_undoable(gw):
    _, _, steps = replay(gw, "reversible_update")
    d = steps[-1]
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD and d.executed
    dormant = gw.env.db.execute("SELECT COUNT(*) FROM customers WHERE status='dormant'").fetchone()[0]
    assert dormant > 0
    assert gw.undo_action(d.receipt_id)["undone"]
    assert gw.env.db.execute("SELECT COUNT(*) FROM customers WHERE status='dormant'").fetchone()[0] == 0


def test_destructive_actions(gw):
    assert replay(gw, "drop_table")[2][-1].verdict == Verdict.DENY
    d = replay(gw, "overeager_delete")[2][-1]
    assert d.verdict in (Verdict.DENY, Verdict.ESCALATE) and d.effect.magnitude["rows_affected"] == 480
    assert gw.env.table_counts()["customers"] == 480     # sandbox only; production untouched


def test_rug_pull_and_secret_read_fail_closed(gw):
    assert replay(gw, "rug_pull")[2][-1].reason.startswith("[R6]")
    assert replay(gw, "secret_read")[2][-1].reason.startswith("[R9]")


def test_unknown_tool_fail_closed(gw):
    tid, _ = gw.start_task("u", "admin", "do it")
    assert gw.check(tid, ToolCall("shell.run", {"cmd": "rm -rf /"})).verdict == Verdict.DENY


def test_receipt_chain_detects_tampering(gw):
    replay(gw, "email_injection")
    assert gw.receipts.verify()["valid"]
    denied = next(r for r in gw.receipts.items if r["body"].get("decision", {}).get("verdict") == "DENY")
    denied["body"]["decision"]["verdict"] = "ALLOW"          # an insider rewrites history
    v = gw.receipts.verify()
    assert not v["valid"] and v["broken_at"] == denied["id"]


def test_policy_floor_escalates_and_four_eyes(gw):
    tid, _, steps = replay(gw, "big_refund")
    d = steps[-1]
    assert d.verdict == Verdict.ESCALATE and d.hitl_id
    out = gw.resolve_hitl(d.hitl_id, "lead-7", approve=True)
    assert out["executed"] and gw.env.ledger[-1]["amount"] == -12000


def test_hitl_timeout_is_default_deny():
    q = ApprovalQueue(timeout_s=0.01)
    hid = q.submit("t", "asha", {"call": {"tool": "x"}, "risk": None}, four_eyes=True)
    time.sleep(0.02)
    assert q.pending() == [] and q.items[hid]["status"] == "expired-denied"
    q2 = ApprovalQueue()
    hid = q2.submit("t", "asha", {"call": {"tool": "x"}, "risk": None}, four_eyes=True)
    with pytest.raises(PermissionError):
        q2.resolve(hid, "asha", approve=True)


class FakeLLM:
    enabled, model, last_latency_ms = True, "fake", 1.0

    def __init__(self, reply):
        self.reply = reply

    def chat_json(self, *a, **k):
        return json.loads(self.reply)

    def chat_text(self, *a, **k):
        return self.reply


def test_llm_judge_can_only_raise_scrutiny():
    hi = IntentJudge(FakeLLM('{"alignment": 0.99, "reason": "fine"}'))
    lo = IntentJudge(FakeLLM('{"alignment": 0.05, "reason": "not asked"}'))
    base = hi.score("Summarise my unread emails.", "mail.send", {}, {}, ambiguous=True)
    assert base["alignment"] <= 0.85                     # the LLM saying "0.99" cannot raise it
    assert lo.score("Summarise my unread emails.", "mail.send", {}, {}, ambiguous=True)["alignment"] == 0.05


def test_explainer_rejects_unfaithful_numbers():
    d = {"verdict": "DENY", "call": {"tool": "mail.send", "args": {"to": "a@b.co"}}, "gates": [], "effect": None,
         "risk": None, "replan_hint": None}
    bad = Explainer(FakeLLM("This would have leaked 9999 records."), use_llm=True)
    good = Explainer(FakeLLM("The email was blocked."), use_llm=True)
    assert bad.explain(d)[1].startswith("template")
    assert good.explain(d)[1].startswith("qualcomm-llm")


def test_mcp_front_door():
    from fastapi.testclient import TestClient
    from kavach.server import app
    c = TestClient(app)
    c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                         "params": {"_meta": {"kavach/userRequest": "status of invoice 1042?", "kavach/session": "t"}}})
    tools = c.post("/mcp", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"}).json()["result"]["tools"]
    assert any(t["name"] == "crm.execute" and t["annotations"]["destructiveHint"] is False for t in tools)
    r = c.post("/mcp", json={"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                             "params": {"name": "crm.execute", "arguments": {"sql": "DROP TABLE invoices"},
                                        "_meta": {"kavach/session": "t"}}}).json()["result"]
    assert r["isError"] and r["_meta"]["kavach/verdict"] == "DENY"
