"""local_execution=False: KAVACH decides, something else executes (the MCP proxy, the AgentOS hook)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402


def gateway():
    return Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False, local_execution=False))


def test_no_undo_claim_for_what_kavach_does_not_run():
    k = gateway()
    tid, _ = k.start_task("asha", "support", "Please update customer 17 to the gold tier.")
    d = k.check(tid, ToolCall("crm.execute", {"sql": "UPDATE customers SET tier = 'gold' WHERE id = 17"}))
    assert d.verdict == Verdict.ALLOW and "undo armed" not in d.reason


def test_approval_does_not_run_the_call_in_kavachs_world():
    k = gateway()
    tid, _ = k.start_task("asha", "support", "Refund 12000 on invoice 1042, the customer was double charged.")
    d = k.check(tid, ToolCall("payments.refund", {"invoice_id": 1042, "amount": 12000}))
    out = k.resolve_hitl(d.hitl_id, "lead-7", approve=True)
    assert out["approved"] and out["external"] and not out["executed"] and k.env.ledger == []
    assert k.receipts.items[-1]["body"]["type"] == "human-approved" and k.receipts.verify()["valid"]


def test_approving_a_draft_keeps_the_pin_the_human_saw():
    k = gateway()
    seen = []
    k.registry.on_approve.append(lambda name, pin: seen.append((name, pin)))
    k.registry.add_draft("acme.delete_all", "Deletes everything.", {"properties": {}}, {"destructiveHint": True})
    k.registry.pins["acme.delete_all"] = "upstream-hash-123"
    assert k.registry.approve("acme.delete_all") and seen == [("acme.delete_all", "upstream-hash-123")]
