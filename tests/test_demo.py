"""The dashboard demo, step by step, with the shipped model and operating point.

Retraining the risk model can silently change a demo flow (it did once: a harmless COUNT(*) read started
escalating and cut the undo demo short). These tests pin every scenario's sequence of verdicts and rules.
"""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall  # noqa: E402
from kavach.risk import RiskModel  # noqa: E402
from kavach.scenarios import EXPECTED_FLOWS, SCENARIOS, materialize, prepare  # noqa: E402

EXPECTED = EXPECTED_FLOWS


def shipped_gateway() -> Kavach:
    """Like the server (shipped operating point), but without calling a live LLM."""
    cfg = GatewayConfig(use_llm_judge=False, c_block=RiskModel().meta["operating_point"]["c_block"])
    return Kavach(Environment(tempfile.mkdtemp()), cfg)


def test_every_scenario_has_a_pinned_flow():
    assert set(EXPECTED) == set(SCENARIOS)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_dashboard_flow(name):
    k, sc = shipped_gateway(), SCENARIOS[name]
    prepare(k.env, sc)
    tid, _ = k.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
    flow, last = [], None
    for c in sc["steps"]:
        d = k.run(tid, materialize(c, last))
        last = d.result
        rule = d.reason[1:d.reason.index("]")] if d.reason.startswith("[") else None
        flow.append((d.call.tool, d.verdict.value, rule))
        if d.verdict.value in ("DENY", "ESCALATE"):
            break
    assert flow == EXPECTED[name]


@pytest.mark.parametrize("amount", [800, 9000, 24000])
def test_clean_payments_within_the_release_limit_run_without_a_human(amount):
    """Issue #21: the model used to escalate clean payments from about EUR 9,000; the rulebook allows 25,000."""
    k = shipped_gateway()
    for table, row in (("ap_invoices", "INV-3001"), ("purchase_orders", "PO-3001"), ("goods_receipts", "GR-3001")):
        k.env.db.execute(f"UPDATE {table} SET amount = ? WHERE id = ?", (amount, row))
    tid, _ = k.start_task("meera", "ap_supervisor", "Release the approved payment for invoice INV-3001.")
    assert k.check(tid, ToolCall("payment.release", {"invoice_id": "INV-3001"})).verdict.value == "ALLOW_WITH_SAFEGUARD"
