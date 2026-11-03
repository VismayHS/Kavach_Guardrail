"""A conversation's turns add up: a clarification doesn't erase an earlier ask, and a later refusal withdraws it.

Found on real Gmail, 3 Nov 2026: "Read the email with subject 'DEMO-04 | ...'. Reply to its sender: ..." found nothing
(Gmail's search), the user then typed "Draft Quote 2041 | Figures Awaiting Confirmati", and the reply waited for a
person as "the user did not ask for a state-changing action": intent saw only the last turn, provenance saw them all."""
from kavach.models import ToolCall, Verdict
from tests.test_first_contact import gmail, restore_policy  # noqa: F401
from tests.test_email_window import setup_function  # noqa: F401
from tests.test_gmail import FakeImap, mail

QUOTE = "Draft Quote 2041 | Figures Awaiting Confirmation"
REPLY = "We received draft quote 2041. The figures remain under review; this is not acceptance."


def two_turns(second):
    gw = gmail()
    FakeImap.box = [mail(23, "Dhanush S <dhanred0309@gmail.com>", QUOTE, "Please confirm the figures.")]
    tid, _ = gw.start_task("claude", "ap_agent", f'Read the email with subject "DEMO-04 | {QUOTE}". '
                                                  f'Reply to its sender: "{REPLY}"')
    assert gw.run(tid, ToolCall("mail.read_inbox", {"query": f'subject:"{QUOTE}"'})).verdict == Verdict.ALLOW
    gw.add_request(tid, second)
    return gw, tid, gw.run(tid, ToolCall("mail.send", {"to": "dhanred0309@gmail.com", "subject": f"Re: {QUOTE}",
                                                       "body": REPLY}))


def test_a_clarifying_turn_keeps_the_reply_the_user_asked_for():
    gw, tid, d = two_turns("Draft Quote 2041 | Figures Awaiting Confirmati")
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD, d.reason
    assert gw.tasks[tid].ctx.turns[-1].startswith("Draft Quote") and "Reply to its sender" in gw.tasks[tid].ctx.user_request


def test_a_later_turn_that_refuses_withdraws_the_ask():
    _, _, d = two_turns("Actually, don't reply to anyone. Do not send any emails.")
    assert d.verdict != Verdict.ALLOW_WITH_SAFEGUARD and d.verdict != Verdict.ALLOW
