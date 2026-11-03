"""The with/without comparison: the "without KAVACH" paths really bypass KAVACH (and say so), and they exist only
where they should: the Live demo's direct send is dev-profile only and still leaves a receipt."""
import dataclasses
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from kavach import server
from kavach.connectors import SmtpMailer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeSMTP:
    sent = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send_message(self, m, from_addr=None, to_addrs=None):
        FakeSMTP.sent.append((m, to_addrs))
        return {}


def test_direct_send_bypasses_kavach_only_in_dev_and_leaves_a_receipt(monkeypatch):
    import smtplib
    FakeSMTP.sent = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(server.env, "mailer", SmtpMailer("127.0.0.1", 1025))
    c = TestClient(server.app)
    r = c.post("/api/stage/direct-send", json={"to": "demo-recipient@example.test", "subject": "hi", "body": "x"})
    assert r.status_code == 200 and FakeSMTP.sent[-1][1] == ["demo-recipient@example.test"]
    assert FakeSMTP.sent[-1][0]["X-Sent-By"] == "no-KAVACH"                     # marked as sent without KAVACH
    assert server.gw.receipts.items[-1]["body"]["type"] == "demo-unguarded-send"
    leak = c.post("/api/stage/direct-send", json={"leak": True}).json()
    assert leak["to"] == ["billing@acme-invoices.co"] and leak["lines"] > 100          # the synthetic customer list
    monkeypatch.setattr(server, "PROFILE", dataclasses.replace(server.PROFILE, fast_forward=False))    # prod-like
    assert c.post("/api/stage/direct-send", json={"to": "a@b.test", "subject": "s", "body": "b"}).status_code == 403


def test_the_plain_mail_server_sends_at_once_and_says_it_had_no_kavach(monkeypatch):
    import smtplib
    FakeSMTP.sent = []
    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    from scripts import plain_mail_mcp
    assert plain_mail_mcp.send("demo-recipient@example.test", "s", "b") == "Sent to demo-recipient@example.test."
    (m, rcpts), = FakeSMTP.sent
    assert rcpts == ["demo-recipient@example.test"] and m["X-Sent-By"] == "no-KAVACH"
    assert any(x["id"] == "msg-6103" for x in plain_mail_mcp.read_inbox())     # the same demo company KAVACH guards
