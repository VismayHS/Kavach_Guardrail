"""R44, classified content (on for real Gmail): what a message marked Internal Only or Confidential says may not be
emailed outside, not even to a trusted address; the destination being trusted doesn't make the content shareable.
A message is marked by its subject, or a body line that starts with the marker; a legal footer that merely mentions
confidentiality doesn't mark it. Off by default, so the demo company and the benchmarks decide as before."""
from kavach.gateway import is_classified
from kavach.models import ToolCall, Verdict
from tests.test_email_window import Smtp, kavach, setup_function  # noqa: F401
from tests.test_gmail import FakeImap, inbox, mail

ME, AUDITOR = "me@gmail.com", "auditor@firm.example"
REVIEW = ("Hi Finance Team,\n\nInternal review for synthetic Client A:\n\nContract: DEMO-CLIENT-A-2026\n"
          "Annual contract value: INR 12,00,000\nInternal delivery cost: INR 7,80,000\nTarget margin: 35%\n"
          "Negotiation floor: INR 10,50,000\n\nINTERNAL ONLY: do not forward outside the finance team.\n")
BRIEF = "Hi Team,\n\nNovember maintenance is complete. The next service visit is on 15 December.\n"


def gmail(on=True):
    gw = kavach()
    gw.env.mailbox = inbox()
    gw.env.mailer.sender = ME
    gw.policy.cfg.update(first_contact_approval=True, classification_markers=on, mail_trusted=[AUDITOR])
    FakeImap.box = [mail(11, f"Finance Controller <{ME}>", "DEMO-05 | Internal Only | Client A Margin Review", REVIEW),
                    mail(12, f"Operations <{ME}>", "DEMO-03 | Public Partner Brief", BRIEF)]
    return gw


def send(to, body):
    return ToolCall("mail.send", {"to": to, "subject": "Client A margin review", "body": body})


def test_marked_by_subject_or_a_marker_line_not_by_a_footer():
    assert is_classified({"subject": "Q4 | Internal Only | margins", "body": "x"})
    assert is_classified({"subject": "Margins", "body": "Hello\nCONFIDENTIAL: board use only\n"})
    assert not is_classified({"subject": "Invoice 1042", "body": "Regards\n\nThis email may contain confidential "
                                                                  "information intended only for the addressee."})


def test_internal_only_figures_may_not_go_even_to_a_trusted_address():
    gw = gmail()
    tid, _ = gw.start_task("ravi", "ap_agent", "Forward the Client A margin review to our auditor at "
                                               f"{AUDITOR}.")
    gw.run(tid, ToolCall("mail.read_inbox", {"query": "margin review"}))
    d = gw.run(tid, send(AUDITOR, "Annual contract value INR 12,00,000; delivery cost INR 7,80,000; floor INR 10,50,000."))
    assert d.verdict == Verdict.DENY and d.reason.startswith("[R44]") and "gmail-11" in d.reason
    assert "R43" not in {g.rule_id for g in d.gates if g.outcome != "PASS"}          # the auditor is trusted


def test_the_same_trusted_address_gets_unmarked_content_and_the_account_itself_gets_anything():
    gw = gmail()
    tid, _ = gw.start_task("ravi", "ap_agent", f"Send the public partner brief to {AUDITOR}, and the margin review "
                                               f"to {ME}.")
    gw.run(tid, ToolCall("mail.read_inbox", {}))
    assert gw.run(tid, send(AUDITOR, "November maintenance is complete; next visit 15 December.")).verdict \
        == Verdict.ALLOW_WITH_SAFEGUARD
    assert gw.run(tid, send(ME, "Floor INR 10,50,000, value INR 12,00,000.")).verdict == Verdict.ALLOW_WITH_SAFEGUARD


def test_off_by_default():
    gw = gmail(on=False)
    tid, _ = gw.start_task("ravi", "ap_agent", f"Forward the Client A margin review to {AUDITOR}.")
    gw.run(tid, ToolCall("mail.read_inbox", {}))
    d = gw.run(tid, send(AUDITOR, "Annual contract value INR 12,00,000."))
    assert "R44" not in {g.rule_id for g in d.gates if g.outcome != "PASS"}
