"""Repeating a request doesn't repeat its effect. The same email asked for twice in one task goes to a person
(R36) instead of out twice; a payment carries its hold id to the bank as the idempotency key
(tests/test_bank_e2e.py); and a send cut off mid-way is `unknown`, never sent again (tests/test_email_window.py)."""
from kavach.models import ToolCall, Verdict
from tests.test_email_window import REQ, SEND, Smtp, kavach, later, setup_function  # noqa: F401


def test_the_same_email_twice_goes_to_a_person_and_leaves_once():
    gw = kavach()
    tid, _ = gw.start_task("ravi", "analyst", REQ)
    first = gw.run(tid, ToolCall("mail.send", dict(SEND.args)))
    again = gw.run(tid, ToolCall("mail.send", dict(SEND.args)))      # an agent retrying, or a replayed request
    assert first.verdict == Verdict.ALLOW_WITH_SAFEGUARD
    assert again.verdict == Verdict.ESCALATE and again.reason.startswith("[R36]")
    gw.settle(later())
    assert len(Smtp.got) == 1


def test_once_cancelled_the_same_email_can_be_asked_for_again():
    gw = kavach()
    tid, _ = gw.start_task("ravi", "analyst", REQ)
    first = gw.run(tid, ToolCall("mail.send", dict(SEND.args)))
    gw.undo_action(first.receipt_id)                                   # taken back: it no longer counts
    assert gw.run(tid, ToolCall("mail.send", dict(SEND.args))).verdict == Verdict.ALLOW_WITH_SAFEGUARD
    gw.settle(later())
    assert len(Smtp.got) == 1
