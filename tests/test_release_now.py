"""Send now: a person lets a queued email (or held payment) go out before its window ends, the opposite of Cancel.
Only while it is still waiting; the release is receipted (who, which hold) before it goes out, and it leaves by the
same path a closing window uses, so it is sent at most once and its outcome is receipted the same way."""
import tempfile

from kavach.connectors import SmtpMailer
from kavach.environment import Environment
from kavach.gateway import GatewayConfig, Kavach
from kavach.models import ToolCall, Verdict
from tests.test_email_window import REQ, SEND, Smtp, setup_function  # noqa: F401  (the mail server stand-in)


def kavach():
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    gw.env.mailer = SmtpMailer("mailpit", 1025, smtp=Smtp)
    return gw


def queued(gw):
    tid, _ = gw.start_task("ravi", "analyst", REQ)
    d = gw.run(tid, SEND)
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD and not Smtp.got
    return d.receipt_id


def types(gw):
    return [r["body"]["type"] for r in gw.receipts.items]


def test_send_now_lets_it_out_at_once_and_only_once():
    gw = kavach()
    rid = queued(gw)
    out = gw.release_now(rid, by="meera")
    assert out["released"] and out["outcome"] == "sent" and len(Smtp.got) == 1
    rel = next(r["body"] for r in gw.receipts.items if r["body"]["type"] == "released-early")
    assert rel["by"] == "meera" and rel["receipt"] == rid
    assert types(gw).index("released-early") < types(gw).index("window-closed")
    assert not gw.release_now(rid)["released"] and len(Smtp.got) == 1       # a second press sends nothing
    assert gw.settle() == [] and len(Smtp.got) == 1                         # nor does the window closing later


def test_a_cancelled_email_cannot_be_sent_now():
    gw = kavach()
    rid = queued(gw)
    assert gw.undo_action(rid)["undone"]
    out = gw.release_now(rid)
    assert not out["released"] and Smtp.got == []


def test_send_now_after_a_reset_touches_nothing():
    gw = kavach()
    rid = queued(gw)
    gw.env.reset()
    assert not gw.release_now(rid)["released"] and Smtp.got == []


def test_a_held_payment_can_be_released_now():
    gw = kavach()
    tid, _ = gw.start_task("ravi", "finance", "Pay Northwind Supplies 4000 for invoice INV-88 (ACC-11-2001).")
    d = gw.run(tid, ToolCall("payments.transfer", {"to_account": "ACC-11-2001", "amount": 4000, "memo": "INV-88"}))
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD, d.reason
    before = len(gw.env.ledger)
    out = gw.release_now(d.receipt_id, by="meera")
    assert out["released"] and len(gw.env.ledger) == before + 1


def test_the_console_endpoint_sends_it_now():
    from fastapi.testclient import TestClient

    from kavach import server
    tid, _ = server.gw.start_task("ravi", "analyst", REQ)
    d = server.gw.run(tid, SEND)
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD
    sent_before = len(server.env.outbox)
    r = TestClient(server.app).post(f"/api/release/{d.receipt_id}").json()
    assert r["released"] and len(server.env.outbox) == sent_before + 1
    assert TestClient(server.app).post(f"/api/release/{d.receipt_id}").json()["released"] is False
