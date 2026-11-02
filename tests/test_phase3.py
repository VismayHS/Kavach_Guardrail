"""Phase 3: actions KAVACH lets through can still be taken back (payment hold, email recall window, SAP park),
and what goes out is checked against what was approved."""
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import MAIL_RECALL_S, PAYMENT_HOLD_S, Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.scenarios import SCENARIOS, materialize, prepare  # noqa: E402


@pytest.fixture()
def gw():
    return Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))


def replay(gw, name):
    sc = SCENARIOS[name]
    prepare(gw.env, sc)
    tid, _ = gw.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
    steps, last = [], None
    for c in sc["steps"]:
        d = gw.run(tid, materialize(c, last))
        steps.append(d)
        last = d.result
        if d.verdict in (Verdict.DENY, Verdict.ESCALATE):
            break
    return tid, steps


def status(gw, inv):
    f = gw.env.ap_invoice_facts(inv)
    return f["status"], f["proposal_id"]


def later(s):
    return time.time() + s + 1


# ---------------------------------------------------------------- the three windows
def test_held_payment_can_be_cancelled_and_released_again(gw):
    tid, steps = replay(gw, "ap_clean_release")
    d = steps[-1]
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD and "held 60 min" in d.reason
    assert status(gw, "INV-3001") == ("held", None)         # the proposal is used up while the payment waits
    assert gw.undo_action(d.receipt_id) == {"undone": True, "cancelled": d.result["held"]}
    assert gw.env.settle_due(later(PAYMENT_HOLD_S)) == [] and gw.env.ledger == []     # the money never left
    assert status(gw, "INV-3001") == ("approved", "P-3001")
    assert not gw.undo_action(d.receipt_id)["undone"]                                   # only once
    again = gw.run(tid, ToolCall("payment.release", {"invoice_id": "INV-3001"}))
    assert again.verdict == Verdict.ALLOW_WITH_SAFEGUARD


def test_undo_from_before_a_reset_does_not_touch_the_new_world(gw):
    _, old = replay(gw, "ap_clean_release")                  # hold-1
    _, new = replay(gw, "ap_clean_release")                  # the demo resets the world: hold-1 again, a new one
    assert not gw.undo_action(old[-1].receipt_id)["undone"]
    assert gw.env.holds[0]["status"] == "held"                # the new payment is untouched
    assert gw.undo_action(new[-1].receipt_id)["undone"]


def test_a_held_invoice_is_not_released_twice(gw):
    tid, steps = replay(gw, "ap_clean_release")
    second = gw.run(tid, ToolCall("payment.release", {"invoice_id": "INV-3001"}))
    assert not second.verdict.value.startswith("ALLOW") and "R19" in second.reason   # no open proposal left
    assert len(gw.env.holds) == 1


def test_queued_email_can_be_recalled_and_otherwise_goes_out(gw):
    _, steps = replay(gw, "benign_external_email")
    d = steps[-1]
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD and d.result["queued"] and gw.env.outbox == []
    assert gw.env.settle_due(time.time() + 1) == []                      # still inside the recall window
    assert gw.env.settle_due(later(MAIL_RECALL_S)) == [d.result["queued"]] and len(gw.env.outbox) == 1
    assert not gw.undo_action(d.receipt_id)["undone"]                    # too late: it went out

    gw2 = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    _, steps = replay(gw2, "benign_external_email")
    assert gw2.undo_action(steps[-1].receipt_id)["undone"]
    assert gw2.env.settle_due(later(MAIL_RECALL_S)) == [] and gw2.env.outbox == []


def test_parked_sap_document_is_discarded_by_undo(gw):
    _, steps = replay(gw, "ap_sap_correction")
    d = steps[-1]
    assert d.verdict == Verdict.ALLOW_WITH_SAFEGUARD and d.result == {"parked": "SAP-1"}
    assert gw.undo_action(d.receipt_id)["cancelled"] == "SAP-1"
    row = gw.env.db.execute("SELECT status FROM sap_documents WHERE id = 1").fetchone()
    assert row[0] == "discarded"                                          # kept for audit, never posted


def test_direct_calls_skip_the_windows(gw):
    gw.env.dispatch("mail.send", {"to": "x@client9.com", "subject": "s", "body": "b"})
    gw.env.dispatch("payment.release", {"invoice_id": "INV-3001"})
    assert len(gw.env.outbox) == 1 and len(gw.env.ledger) == 1 and gw.env.holds == []


def test_without_windows_the_same_payment_goes_out_at_once():
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False, use_windows=False))
    _, steps = replay(k, "ap_clean_release")
    assert steps[-1].verdict == Verdict.ALLOW and len(k.env.ledger) == 1 and k.env.holds == []


# ---------------------------------------------------------------- outcome check and human approval
def test_payment_is_cancelled_if_the_bank_account_changed_while_a_human_approved_it(gw):
    _, steps = replay(gw, "ap_cfo_tier")
    d = steps[-1]
    assert d.verdict == Verdict.ESCALATE
    gw.env.db.execute("UPDATE vendors SET iban = 'GB33BUKB20201555555555' WHERE id = 'V002'")  # not via the agent
    gw.resolve_hitl(d.hitl_id, "cfo@infycorp.com", approve=True, approver_role="cfo")
    out = gw.resolve_hitl(d.hitl_id, "fd@infycorp.com", approve=True, approver_role="finance_director")
    assert "cancelled" in out["result"] and "GB33BUKB20201555555555" in out["result"]
    gw.env.settle_due(later(PAYMENT_HOLD_S))
    assert gw.env.ledger == [] and status(gw, "INV-3040") == ("approved", "P-3040")
    assert any(r["body"].get("type") == "outcome-mismatch" for r in gw.receipts.items) and gw.receipts.verify()["valid"]


def test_approve_as_draft_saves_a_real_draft(gw):
    tid, _ = gw.start_task("ravi", "analyst", "Email the customer on invoice 1042 that it is overdue.")
    rows = gw.env.crm_query("SELECT email FROM customers WHERE id NOT IN "
                            "(SELECT customer_id FROM invoices WHERE id = 1042) LIMIT 1")
    gw.tasks[tid].prov.register_output("crm.query", rows, "derived", gw.registry.get("crm.query").output_conf)
    d = gw.run(tid, ToolCall("mail.send", {"to": rows[0]["email"], "subject": "Invoice 1042", "body": "Overdue."}))
    assert d.verdict == Verdict.ESCALATE                                  # R24: not that invoice's customer
    out = gw.resolve_hitl(d.hitl_id, "lead-7", approve=True, mode="safeguard")
    assert out["result"] == {"draft_saved": "draft-1"} and gw.env.drafts[0]["to"] == rows[0]["email"]
    assert gw.env.outbox == [] and gw.env.holds == []


# ---------------------------------------------------------------- R16: the record argument must be one the user named
def test_r16_a_different_record_with_the_right_amount_needs_a_human(gw):
    def r16(user, role, request, tool, args):
        tid, _ = gw.start_task(user, role, request)
        return any(g.rule_id == "R16" and g.outcome == "REQUIRE_APPROVAL" for g in gw.check(tid, ToolCall(tool, args)).gates)
    refund = "Refund 1500 on invoice 1042; the customer was overcharged."
    assert r16("asha", "support", refund, "payments.refund", {"invoice_id": 1043, "amount": 1500})
    assert not r16("asha", "support", refund, "payments.refund", {"invoice_id": 1042, "amount": 1500})
    swap = "Refund 2000 on invoice 1042; the customer was double charged."
    assert r16("asha", "support", swap, "payments.refund", {"invoice_id": 2000, "amount": 1042})   # swapped
    assert r16("asha", "support", "Refund 1500 on invoice 1499.", "payments.refund", {"invoice_id": 1500, "amount": 1500})
    assert not r16("meera", "ap_supervisor", "Release the approved payments for invoices INV-5300 and INV-5400.",
                   "payment.release", {"invoice_id": "INV-5400"})        # a list: both are named
    post = "Post a correction of EUR 1200 to GL account 400100 for the freight accrual."
    sap = {"doc_type": "correction", "amount": 1200, "text": "freight accrual"}
    assert r16("meera", "ap_supervisor", post, "sap.post", {**sap, "gl_account": "600200"})
    assert not r16("meera", "ap_supervisor", post, "sap.post", {**sap, "gl_account": "400100"})
    assert not r16("meera", "ap_supervisor", "Release the approved payment for invoice 3001.", "payment.release",
                   {"invoice_id": "INV-3001"})                            # "invoice 3001" is INV-3001


# ---------------------------------------------------------------- HTTP API
def test_settle_endpoint_lets_waiting_payments_go_out(monkeypatch):
    from fastapi.testclient import TestClient
    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", None)
    api = TestClient(server.app)
    run = api.post("/api/demo/ap_clean_release").json()
    assert run["state"]["waiting"] == 1 and run["state"]["ledger"] == 0
    assert [h["kind"] for h in api.get("/api/state").json()["waiting"]] == ["payment"]
    assert api.post("/api/settle").json()["settled"] == []                # the hour hasn't passed
    assert len(api.post("/api/settle?advance_s=3600").json()["settled"]) == 1
    assert api.get("/api/state").json()["waiting"] == []
