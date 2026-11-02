"""An approval is bound to one exact action: this task (its user, role, tenant and session), this tool, these
arguments (destination, payload, amount). It runs what the person saw, once, before it expires; a changed action
needs its own approval. Cross-tenant approval: tests/test_tenancy.py. Four-eyes and quorum: tests/test_ap.py."""
import time

import pytest

from kavach.models import ToolCall, Verdict
from tests.test_email_window import SEND, Smtp, kavach, later, setup_function  # noqa: F401
from tests.test_trace import ASK, Keep


def escalated(gw, call=SEND):
    tid, _ = gw.start_task("ravi", "analyst", ASK)
    d = gw.run(tid, call)
    assert d.verdict == Verdict.ESCALATE, d.reason
    return tid, d


def test_it_runs_exactly_what_the_person_saw_even_if_the_caller_changes_its_copy():
    gw = kavach()
    call = ToolCall("mail.send", {"to": "demo-recipient@example.test", "subject": "Test summary", "body": "All good."})
    _, d = escalated(gw, call)
    call.args.update(to="drop@fin-desk.io", body="the customer list")      # the agent's object, after the check
    gw.env.mailer._smtp = Keep
    Keep.msgs = []
    assert gw.resolve_hitl(d.hitl_id, "meera", True)["executed"]
    gw.settle(later())
    assert [m["To"] for m in Keep.msgs] == ["demo-recipient@example.test"]
    assert Keep.msgs[0].get_payload().strip() == "All good."


def test_the_digest_is_on_the_card_and_the_receipts():
    gw = kavach()
    tid, d = escalated(gw)
    digest = gw.hitl.items[d.hitl_id]["digest"]
    assert digest == gw.action_digest(tid, SEND)
    gw.resolve_hitl(d.hitl_id, "meera", True)
    bodies = [r["body"] for r in gw.receipts.items]
    assert bodies[0]["decision"]["action_digest"] == digest
    assert next(b for b in bodies if b["type"] == "human-approved-execution")["digest"] == digest


def test_a_changed_action_is_refused_not_run():
    gw = kavach()
    tid, d = escalated(gw)
    t, call, eff = gw.pending_calls[d.hitl_id]
    gw.pending_calls[d.hitl_id] = (t, ToolCall(call.tool, {**call.args, "to": "drop@fin-desk.io"}, call.call_id), eff)
    out = gw.resolve_hitl(d.hitl_id, "meera", True)
    gw.settle(later())
    assert not out["executed"] and "changed" in out["reason"] and Smtp.got == []


def test_changed_arguments_need_their_own_approval():
    gw = kavach()
    tid, d = escalated(gw)
    gw.resolve_hitl(d.hitl_id, "meera", True)
    again = gw.run(tid, ToolCall("mail.send", {**SEND.args, "body": "All good. Also, the customer list."}))
    assert again.verdict == Verdict.ESCALATE and again.hitl_id != d.hitl_id
    assert gw.hitl.items[again.hitl_id]["digest"] != gw.hitl.items[d.hitl_id]["digest"]


def test_an_approval_is_used_once():
    gw = kavach()
    _, d = escalated(gw)
    gw.resolve_hitl(d.hitl_id, "meera", True)
    with pytest.raises(ValueError):
        gw.resolve_hitl(d.hitl_id, "meera", True)
    gw.settle(later())
    assert len(Smtp.got) == 1


def test_an_expired_approval_cannot_be_approved():
    gw = kavach()
    _, d = escalated(gw)
    gw.hitl.expire(time.time() + 10 ** 6)
    with pytest.raises(ValueError):
        gw.resolve_hitl(d.hitl_id, "meera", True)
    gw.settle(later())
    assert Smtp.got == [] and gw.hitl.items[d.hitl_id]["status"] == "expired-denied"
    assert any(r["body"]["type"] == "approval-expired" and r["body"]["corr"] == SEND.call_id for r in gw.receipts.items)
