"""F8: approval cards (Slack, Teams), Hindi explanations, approval-fatigue stats, SLA escalation chain."""
import json
import sys
import tempfile
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.explain import template  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.hitl import ApprovalQueue  # noqa: E402
from kavach.models import ToolCall  # noqa: E402
from kavach.notify import ApprovalNotifier, slack_blocks, teams_card  # noqa: E402
from kavach.scenarios import SCENARIOS, materialize, prepare  # noqa: E402


def escalated():
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    sc = SCENARIOS["ap_cfo_tier"]
    prepare(k.env, sc)
    tid, _ = k.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
    last = d = None
    for c in sc["steps"]:
        d = k.run(tid, materialize(c, last))
        last = d.result
    return k, d


def test_cards_carry_what_an_approver_needs():
    k, d = escalated()
    item = k.hitl.items[d.hitl_id]
    s = json.dumps(slack_blocks(item, "https://kavach.example.com"))
    assert "payment.release" in s and "R18" in s and "1x cfo + 1x finance director" in s
    assert "https://kavach.example.com/?hitl=" in s
    t = teams_card(item)
    assert t["attachments"][0]["contentType"] == "application/vnd.microsoft.card.adaptive"
    assert slack_blocks(item)["blocks"][-1]["type"] == "context"            # no button without a console URL


def test_notifier_posts_one_card_per_channel():
    posted = []
    k, _ = escalated()
    n = ApprovalNotifier(k, "https://hooks.slack.example/x", "https://teams.example/y",
                         transport=httpx.MockTransport(lambda r: posted.append(str(r.url)) or httpx.Response(200)))
    k.receipts.listeners.append(n)
    tid, _ = k.start_task("asha", "support", "Refund 12000 on invoice 1042, the customer was double charged.")
    k.check(tid, ToolCall("payments.refund", {"invoice_id": 1042, "amount": 12000}))
    n.flush()
    assert sorted(posted) == ["https://hooks.slack.example/x", "https://teams.example/y"] and n.failed == 0


def test_hindi_explanation_frame():
    k, d = escalated()
    hi = template(k.receipts.get(d.receipt_id)["body"]["decision"], "hi")
    assert hi.startswith("किसी व्यक्ति की स्वीकृति चाहिए") and "कारण" in hi and "[R18]" in hi


def test_sla_escalates_up_the_chain_then_expires():
    q = ApprovalQueue(timeout_s=10, chain=["team_lead", "ops_manager"])
    events = []
    q.on_event.append(events.append)
    hid = q.submit("t1", "agent", {"call": {"tool": "x"}}, four_eyes=False)
    now = time.time()
    q.expire(now + 11)
    assert q.items[hid]["status"] == "pending" and q.items[hid]["routed_to"] == "team_lead"
    q.expire(now + 21)
    assert q.items[hid]["routed_to"] == "ops_manager"
    q.expire(now + 31)
    assert q.items[hid]["status"] == "expired-denied"
    assert [e["type"] for e in events] == ["approval-escalated", "approval-escalated", "approval-expired"]


def test_fatigue_stats_flag_rubber_stamping():
    q = ApprovalQueue()
    for i in range(12):
        hid = q.submit(f"t{i}", "agent", {"call": {"tool": "mail.send"}, "risk": None}, four_eyes=False)
        q.resolve(hid, "lead-7", approve=True)                     # instant, every time
    s = q.stats()
    assert s["approvers"]["lead-7"]["fast_approvals"] == 12 and s["approvers"]["lead-7"]["longest_approve_streak"] == 12
    assert len(s["warnings"]) == 2


def test_api_stats_and_hindi(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", None)
    c = TestClient(server.app)
    run = c.post("/api/demo/drop_table").json()
    rid = run["steps"][-1]["receipt_id"]
    assert "रोका गया" in c.get(f"/api/receipts/{rid}/explain?lang=hi").json()["explanation"]
    assert "approvers" in c.get("/api/hitl/stats").json()
