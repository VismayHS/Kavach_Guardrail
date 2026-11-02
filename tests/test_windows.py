"""E6 durable undo windows: they close on time by themselves, with a receipt, and survive a restart."""
import tempfile
import time

import pytest

pytest.importorskip("sqlalchemy")

from kavach.environment import MAIL_RECALL_S, PAYMENT_HOLD_S, Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.store import Store, attach  # noqa: E402
from kavach.windows import Sweeper  # noqa: E402


def boot(url):
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    return gw, attach(gw, Store(url))


def db():
    return f"sqlite:///{tempfile.mkdtemp()}/kavach.db"


def held_payment(gw):
    tid, _ = gw.start_task("ravi", "finance", "Pay ACC-11-2001 4000 for the Northwind invoice.")
    d = gw.run(tid, ToolCall("payments.transfer", {"to_account": "ACC-11-2001", "amount": 4000, "memo": "INV-88"}))
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD and "held" in d.result, d.reason
    return tid, d


def test_the_sweeper_closes_windows_on_time_with_a_receipt():
    url = db()
    gw, _ = boot(url)
    _, d = held_payment(gw)
    tid, _ = gw.start_task("ravi", "analyst", "Email john.menon@client4.com that invoice 1042 is being processed.")
    m = gw.run(tid, ToolCall("mail.send", {"to": "john.menon@client4.com", "subject": "Invoice 1042",
                                           "body": "Hi John, invoice 1042 is being processed. Regards, Ravi"}))
    assert "queued" in m.result, m.reason
    sw = Sweeper(gw, every_s=0)
    assert sw.tick() == []                                                # nothing is due yet
    gw2, _ = boot(url)                                                    # restart while both wait
    sw2 = Sweeper(gw2, every_s=0)
    assert sorted(sw2.tick(time.time() + max(PAYMENT_HOLD_S, MAIL_RECALL_S) + 1)) == sorted(
        [d.result["held"], m.result["queued"]])
    closed = [r["body"] for r in gw2.receipts.items if r["body"]["type"] == "window-closed"]
    assert {c["kind"] for c in closed} == {"payment", "mail"} and {c["receipt"] for c in closed} == {d.receipt_id,
                                                                                                      m.receipt_id}
    assert len(gw2.env.ledger) == 1 and len(gw2.env.outbox) == 1
    assert gw2.undo_action(d.receipt_id)["undone"] is False               # gone out: too late to take back
    assert boot(url)[1]["holds_waiting"] == 0                             # and it is not sent twice


def test_sweeper_thread_runs_and_api_settle_receipts_too():
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    _, d = held_payment(gw)
    sw = Sweeper(gw, every_s=0.05).start()
    time.sleep(0.3)
    sw.stop.set()
    assert sw.ticks >= 2 and sw.settled == 0                              # alive, and nothing went out early
    assert gw.settle(time.time() + PAYMENT_HOLD_S + 1) == [d.result["held"]]
    assert gw.receipts.items[-1]["body"]["type"] == "window-closed"
