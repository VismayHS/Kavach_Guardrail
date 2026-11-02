"""The kill switch stops what is already waiting, not only new calls: an email or payment queued before the pause never
goes out, also when KAVACH restarted in between (its tasks were in memory and are gone; the receipts say whose action
each one is), when the action started waiting while the pause was coming in, and when someone presses Send now."""
from kavach.models import Verdict
from tests.test_email_window import REQ, SEND, Smtp, db, kavach, later, queue, setup_function  # noqa: F401


def cancelled_by_kill(gw):
    return [r["body"] for r in gw.receipts.items if r["body"]["type"] == "undo" and r["body"].get("by") == "kill switch"]


def test_a_global_pause_after_a_restart_stops_the_email_left_waiting():
    url = db()
    hold = queue(kavach(url)).result["queued"]
    gw = kavach(url)                                        # restart: the task is gone, the hold is not
    out = gw.kill("global", None, "ops", "incident")
    gw.settle(later())
    assert out["cancelled"] == [hold] and Smtp.got == []
    assert next(h for h in gw.env.holds if h["id"] == hold)["status"] == "cancelled"


def test_user_and_role_pauses_after_a_restart_know_whose_email_it_is():
    url = db()
    mine = queue(kavach(url)).result["queued"]               # ravi, an analyst
    gw = kavach(url)
    gw.kill("user", "someone-else", "ops")
    gw.settle(later() - 2)                                   # not due yet: nothing happens
    assert next(h for h in gw.env.holds if h["id"] == mine)["status"] == "held"
    gw.kill("role", "analyst", "ops")
    gw.settle(later())
    assert Smtp.got == [] and next(h for h in gw.env.holds if h["id"] == mine)["status"] == "cancelled"


def test_an_email_that_starts_waiting_while_the_pause_comes_in_never_leaves():
    gw = kavach()
    tid, _ = gw.start_task("ravi", "analyst", REQ)
    d = gw.check(tid, SEND)                                  # checked before the pause...
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD
    gw.kill("task", tid, "ops")
    gw.execute(tid, d)                                       # ...queued after it
    gw.settle(later())
    assert Smtp.got == [] and cancelled_by_kill(gw)[0]["cancelled"] == d.result["queued"]


def test_send_now_cannot_let_a_paused_agents_email_out():
    gw = kavach()
    tid, _ = gw.start_task("ravi", "analyst", REQ)
    d = gw.check(tid, SEND)
    gw.kill("task", tid, "ops")
    gw.execute(tid, d)
    out = gw.release_now(d.receipt_id, by="meera")
    assert not out["released"] and "kill switch" in out["reason"] and Smtp.got == []
    assert gw.settle(later()) == [] and Smtp.got == []


def test_after_resume_new_work_flows_and_the_cancelled_email_stays_cancelled():
    gw = kavach()
    d = queue(gw)
    k = gw.kill("global", None, "ops")
    gw.resume(k["id"], "ops")
    gw.settle(later())
    assert Smtp.got == [] and gw.release_now(d.receipt_id)["released"] is False
    d2 = queue(gw)
    gw.settle(later())
    assert Smtp.got == [d2.result["queued"]]
