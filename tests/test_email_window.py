"""Demo 1, "stop the email before it leaves": a queued email is either cancelled or handed to the mail server once,
and the receipts say which, also when the server is down, the connection drops mid-send, KAVACH dies mid-send, or
two workers share one database. (The same flow against a real Mailpit inbox: tests/test_mailpit_e2e.py.)"""
import os
import socket
import tempfile
import time

from kavach.connectors import SmtpMailer
from kavach.consequence import wait_text
from kavach.environment import MAIL_RECALL_S, Environment
from kavach.gateway import GatewayConfig, Kavach
from kavach.models import ToolCall, Verdict
from kavach.store import Store, attach

REQ = "Send this test summary to demo-recipient@example.test."
SEND = ToolCall("mail.send", {"to": "demo-recipient@example.test", "subject": "Test summary", "body": "All good."})


class Smtp:
    """Mail server stand-in. mode: ok | down (refuses the connection) | drop (takes the message, then the connection
    breaks before it answers) | crash (takes the message, then KAVACH is killed). `during` runs mid-send."""
    got, mode, during = [], "ok", None

    def __init__(self, host, port, timeout=None):
        if Smtp.mode == "down":
            raise ConnectionRefusedError("mail server down")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def send_message(self, m, from_addr=None, to_addrs=None):
        if Smtp.during:
            Smtp.during()
        Smtp.got.append(m["X-Kavach-Outbox"])
        if Smtp.mode == "drop":
            raise socket.timeout("timed out")
        if Smtp.mode == "crash":
            raise SystemExit("KAVACH killed mid-send")
        return {}


def setup_function():
    Smtp.got, Smtp.mode, Smtp.during = [], "ok", None


def later():
    return time.time() + MAIL_RECALL_S + 1


def db():
    return "sqlite:///" + os.path.join(tempfile.mkdtemp(), "kavach.db")


def kavach(url=None):
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    gw.env.mailer = SmtpMailer("mailpit", 1025, smtp=Smtp)
    if url:
        attach(gw, Store(url))
    return gw


def queue(gw):
    tid, _ = gw.start_task("ravi", "analyst", REQ)
    d = gw.run(tid, SEND)
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD and "queued" in d.result      # the agent hears "queued"
    return d


def closed(gw):
    """What the window-closed receipts say happened, by hold id."""
    return {r["body"]["hold"]: r["body"]["outcome"] for r in gw.receipts.items if r["body"]["type"] == "window-closed"}


def test_it_leaves_only_after_the_window_and_the_receipt_says_sent():
    gw = kavach()
    hold = queue(gw).result["queued"]
    assert gw.settle() == [] and Smtp.got == []
    gw.settle(later())
    assert Smtp.got == [hold] and closed(gw) == {hold: "sent"} and gw.env.holds[-1]["status"] == "sent"


def test_cancel_and_send_cannot_both_win():
    gw = kavach()
    d = queue(gw)
    answers = []
    Smtp.during = lambda: answers.append(gw.undo_action(d.receipt_id))       # Cancel pressed while it is going out
    gw.settle(later())
    assert answers[0]["undone"] is False and Smtp.got == [d.result["queued"]]
    assert closed(gw) == {d.result["queued"]: "sent"}


def test_a_mail_server_that_is_down_is_failed_not_sent():
    gw = kavach()
    hold = queue(gw).result["queued"]
    Smtp.mode = "down"
    gw.settle(later())
    assert Smtp.got == [] and closed(gw) == {hold: "failed"} and "ConnectionRefused" in gw.env.outbox[-1]["delivery_error"]


def test_a_connection_that_breaks_mid_send_is_unknown():
    gw = kavach()
    hold = queue(gw).result["queued"]
    Smtp.mode = "drop"
    gw.settle(later())
    assert Smtp.got == [hold] and closed(gw) == {hold: "unknown"}          # it may have arrived: never "sent"


def test_killed_mid_send_it_is_never_sent_again():
    url = db()
    gw = kavach(url)
    hold = queue(gw).result["queued"]
    Smtp.mode = "crash"
    try:
        gw.settle(later())
    except SystemExit:
        pass
    Smtp.mode = "ok"
    gw2 = kavach(url)                                                        # restart
    gw2.settle(later())
    assert Smtp.got == [hold]                                                # once, not twice
    assert closed(gw2)[hold] == "unknown" and gw2.env.holds[-1]["status"] == "unknown"


def test_cancelled_stays_cancelled_through_a_restart():
    url = db()
    gw = kavach(url)
    d = queue(gw)
    assert gw.undo_action(d.receipt_id)["undone"] and not gw.undo_action(d.receipt_id)["undone"]   # twice: harmless
    kavach(url).settle(later())
    assert Smtp.got == []


def test_two_workers_on_one_database_send_once():
    url = db()
    a = kavach(url)
    hold = queue(a).result["queued"]
    b = kavach(url)                                                          # a second worker sees the same hold
    b.settle(later())
    a.settle(later())
    assert Smtp.got == [hold]
    assert a.env.cancel(hold) is False and b.env.cancel(hold) is False       # gone out: neither can cancel it now


def test_mcp_answers_notifications_and_offers_only_the_listed_tools(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    c = TestClient(server.app)
    assert c.post("/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}).status_code == 202
    monkeypatch.setattr(server, "MCP_TOOLS", {"mail.send"})
    rpc = lambda i, method, params=None: c.post("/mcp", json={"jsonrpc": "2.0", "id": i, "method": method,
                                                               "params": params or {}}).json()
    assert [t["name"] for t in rpc(1, "tools/list")["result"]["tools"]] == ["mail.send"]
    rpc(2, "initialize", {"_meta": {"kavach/session": "only-listed", "kavach/userRequest": "Pay INV-3001."}})
    r = rpc(3, "tools/call", {"name": "payment.release", "arguments": {"invoice_id": "INV-3001"},
                              "_meta": {"kavach/session": "only-listed"}})
    assert "not offered" in r["error"]["message"]


def test_an_address_typed_earlier_in_the_same_conversation_still_counts():
    from fastapi.testclient import TestClient

    from kavach import server
    c = TestClient(server.app)
    rpc = lambda i, method, params: c.post("/mcp", json={"jsonrpc": "2.0", "id": i, "method": method,
                                                          "params": params}).json()
    def say(conv, text):        # what the hook sends for each prompt you type
        rpc(1, "initialize", {"_meta": {"kavach/session": "turns", "kavach/conversation": conv,
                                        "kavach/userRequest": text, "kavach/user": "ravi", "kavach/role": "analyst"}})
    def send():
        return rpc(2, "tools/call", {"name": "mail.send", "arguments": {"to": "demo-recipient@example.test",
               "subject": "Test summary", "body": "All good."}, "_meta": {"kavach/session": "turns"}})
    say("conv-1", "Send this test summary to demo-recipient@example.test: all good.")
    say("conv-1", "just send it please")                                   # a later turn: the address still counts
    assert send()["result"]["_meta"]["kavach/verdict"] == "ALLOW_WITH_SAFEGUARD"
    say("conv-2", "just send it please")                                   # a new conversation starts over
    assert send()["result"]["_meta"]["kavach/verdict"] == "ESCALATE"


def test_the_wait_is_said_in_seconds_when_short():
    assert (wait_text(30), wait_text(300), wait_text(3600)) == ("30 s", "5 min", "60 min")
