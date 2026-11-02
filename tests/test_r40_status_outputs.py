"""R40 asks a person about a destination the user didn't give while no tool output has been shown (lineage has
nothing to trace it from). KAVACH's own reply to the agent's state change ("queued", "held", a row count) shows the
agent nothing, so it must not switch R40 off: before, one approved email let every later email in the task go to any
address the agent made up, with no person asked."""
from kavach.models import ToolCall, Verdict
from tests.test_email_window import SEND, Smtp, kavach, setup_function  # noqa: F401


def mail(to, body="All good."):
    return ToolCall("mail.send", {"to": to, "subject": "Test summary", "body": body})


def test_after_one_approved_email_the_next_ones_still_need_a_person():
    gw = kavach()
    tid, _ = gw.start_task("ravi", "analyst", "Send the test summary, please.")
    d = gw.run(tid, SEND)
    assert d.verdict == Verdict.ESCALATE and d.reason.startswith("[R40]")
    assert gw.resolve_hitl(d.hitl_id, "meera", True)["executed"]
    for call in (mail("demo-recipient@example.test", "something else"), mail("drop@made-up.example")):
        again = gw.run(tid, call)
        assert again.verdict == Verdict.ESCALATE and again.reason.startswith("[R40]"), (call.args, again.reason)


def test_a_read_still_counts_as_shown():
    gw = kavach()
    tid, _ = gw.start_task("ravi", "analyst", "Look up invoice 1042, then send the test summary.")
    gw.run(tid, ToolCall("crm.query", {"sql": "SELECT status FROM invoices WHERE id = 1042"}))
    assert not gw.run(tid, mail("demo-recipient@example.test")).reason.startswith("[R40]")
