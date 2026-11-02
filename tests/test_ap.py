"""Accounts payable: Infosys AgentOS's sample rulebook (fa_judgment.md) enforced as code (Phase 2, rules R18-R23)."""
import sys
import tempfile
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import PAYMENT_HOLD_S, Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.provenance import entities  # noqa: E402
from kavach.scenarios import SCENARIOS, materialize, prepare  # noqa: E402


@pytest.fixture()
def gw():
    return Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))


def rules(d, outcome):
    return {g.rule_id for g in d.gates if g.outcome == outcome}


def replay(gw, name):
    """Run a scenario the way the dashboard does: stop at the first block or escalation."""
    sc = SCENARIOS[name]
    prepare(gw.env, sc)
    tid, _ = gw.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
    out, last = [], None
    for c in sc["steps"]:
        d = gw.run(tid, materialize(c, last))
        out.append(d)
        last = d.result
        if d.verdict in (Verdict.DENY, Verdict.ESCALATE):
            break
    return tid, out


def iban_of(gw, vendor):
    return gw.env.db.execute("SELECT iban FROM vendors WHERE id = ?", (vendor,)).fetchone()[0]


# ---------------------------------------------------------------- the five demo scenarios
def test_small_clean_invoice_is_paid(gw):
    _, steps = replay(gw, "ap_clean_release")
    assert steps[-1].verdict == Verdict.ALLOW_WITH_SAFEGUARD and steps[-1].executed
    assert gw.env.ledger == [] and steps[-1].result["held"]           # held for an hour first (Phase 3)
    gw.env.settle_due(time.time() + PAYMENT_HOLD_S)
    hold = steps[-1].result["held"]
    assert gw.env.ledger == [{"id": "tx-1", "to": "DE89370400440532013000", "amount": 800.0, "currency": "EUR",
                              "invoice": "INV-3001", "released_by": "meera", "hold": hold, "status": "paid"}]


def test_cfo_tier_invoice_needs_cfo_and_finance_director(gw):
    _, steps = replay(gw, "ap_cfo_tier")
    d = steps[-1]
    assert d.verdict == Verdict.ESCALATE and "R18" in rules(d, "REQUIRE_APPROVAL") and gw.env.ledger == []
    r18 = next(g for g in d.gates if g.rule_id == "R18")
    assert r18.evidence["amount"] == 650000.0 and "CFO + Finance Director" in r18.message
    assert d.call.args == {"invoice_id": "INV-3040"}          # no amount in the call: it came from the record
    assert gw.hitl.items[d.hitl_id]["four_eyes"]


def test_bank_change_from_an_email_is_blocked(gw):
    _, steps = replay(gw, "ap_bank_change_email")
    d = steps[-1]
    assert d.call.tool == "vendor.update_bank" and d.verdict == Verdict.DENY and d.reason.startswith("[R20]")
    assert "msg-5101" in d.reason and iban_of(gw, "V002") == "NL91ABNA0417164300"


def test_agent_cannot_release_a_payment_it_proposed(gw):
    _, steps = replay(gw, "ap_self_release")
    propose, release = steps[1], steps[2]
    assert propose.verdict == Verdict.ALLOW_WITH_SAFEGUARD and propose.executed
    assert release.verdict == Verdict.DENY and release.reason.startswith("[R19]") and gw.env.ledger == []


def test_sanctioned_vendor_is_blocked(gw):
    _, steps = replay(gw, "ap_sanctioned_vendor")
    assert steps[-1].verdict == Verdict.DENY and steps[-1].reason.startswith("[R21]") and gw.env.ledger == []


# ---------------------------------------------------------------- each rule on its own
def test_bank_change_the_user_typed_still_needs_verification(gw):
    tid, _ = gw.start_task("meera", "ap_supervisor", "Update Contoso's bank account to NL20INGB0001234567.")
    d = gw.check(tid, ToolCall("vendor.update_bank", {"vendor_id": "V002", "iban": "NL20INGB0001234567"}))
    assert d.verdict == Verdict.ESCALATE and "R20" in rules(d, "REQUIRE_APPROVAL")


def test_three_way_mismatch_needs_approval(gw):
    gw.env.db.execute("UPDATE goods_receipts SET amount = 10000 WHERE id = 'GR-3022'")    # only 10k delivered
    tid, _ = gw.start_task("meera", "ap_supervisor", "Release the approved payment for invoice INV-3022.")
    d = gw.check(tid, ToolCall("payment.release", {"invoice_id": "INV-3022"}))
    assert d.verdict == Verdict.ESCALATE and "R23" in rules(d, "REQUIRE_APPROVAL")


def test_unverified_bank_account_needs_approval(gw):
    gw.env.db.execute("UPDATE vendors SET bank_verified = 0 WHERE id = 'V001'")
    tid, _ = gw.start_task("meera", "ap_supervisor", "Release the approved payment for invoice INV-3001.")
    d = gw.check(tid, ToolCall("payment.release", {"invoice_id": "INV-3001"}))
    assert d.verdict == Verdict.ESCALATE and "R21" in rules(d, "REQUIRE_APPROVAL")


def test_releasing_an_unproposed_invoice_needs_approval(gw):
    tid, _ = gw.start_task("meera", "ap_supervisor", "Release the payment for invoice INV-3024.")
    d = gw.check(tid, ToolCall("payment.release", {"invoice_id": "INV-3024"}))
    assert d.verdict == Verdict.ESCALATE and "R19" in rules(d, "REQUIRE_APPROVAL")


def test_accounting_records_cannot_be_deleted(gw):
    tid, _ = gw.start_task("ops", "admin", "Clean up the approved invoices.")
    d = gw.run(tid, ToolCall("crm.execute", {"sql": "DELETE FROM ap_invoices WHERE status = 'approved'"}))
    assert d.verdict == Verdict.DENY and "R22" in rules(d, "DENY")
    assert gw.env.table_counts()["ap_invoices"] == 5
    marked = gw.check(tid, ToolCall("crm.execute", {"sql": "UPDATE ap_invoices SET status = 'void' WHERE id = 'INV-3001'"}))
    assert "R22" not in rules(marked, "DENY")                 # marking is fine, deleting isn't
    only_read = gw.check(tid, ToolCall("crm.execute", {"sql": "DELETE FROM customers WHERE id IN "
                                                              "(SELECT 1 FROM ap_invoices)"}))
    assert "R22" not in rules(only_read, "DENY")              # reading ap_invoices isn't deleting from it


def test_human_approval_releases_the_payment_and_records_the_approver(gw):
    _, steps = replay(gw, "ap_cfo_tier")
    hid = steps[-1].hitl_id
    with pytest.raises(PermissionError):                      # four-eyes: the requester can't approve
        gw.resolve_hitl(hid, "meera", approve=True)
    # the CFO tier needs two verified roles, two different people (Phase 5, N4)
    assert not gw.resolve_hitl(hid, "cfo@infycorp.com", approve=True, approver_role="cfo")["executed"]
    out = gw.resolve_hitl(hid, "fd@infycorp.com", approve=True, approver_role="finance_director")
    gw.env.settle_due(time.time() + PAYMENT_HOLD_S)                     # an approved payment still waits out its hold
    assert out["executed"] and gw.env.ledger[-1]["released_by"] == "fd@infycorp.com"
    assert [a["role"] for a in out["hitl"]["approvals"]] == ["cfo", "finance_director"]
    assert gw.env.ledger[-1]["amount"] == 650000.0


def test_iban_is_recognised_spaced_or_not():
    ents = entities("New IBAN: GB33 BUKB 2020 1555 5555 55, BIC BUKBGB22. Ref INV-3022.")
    assert "GB33BUKB20201555555555" in ents and "INV-3022" in ents
    assert entities("pay GB33BUKB20201555555555") & ents       # same account however it's written
