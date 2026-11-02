"""Demo 2 against the real sandbox bank: with it running (scripts/demo_up.sh starts it on :8030), a payment KAVACH
blocks never arrives, the approved one arrives once with the record's account and amount, and a retry of the same
transfer is booked once. Skipped when no bank is listening."""
import json
import os
import tempfile
import time
import urllib.request

import pytest

from kavach.connectors import SandboxBank
from kavach.environment import PAYMENT_HOLD_S, Environment
from kavach.gateway import GatewayConfig, Kavach
from kavach.models import ToolCall, Verdict

BANK = os.environ.get("KAVACH_TEST_BANK", "http://127.0.0.1:8030")


def bank_up() -> bool:
    try:
        urllib.request.urlopen(BANK + "/transfers", timeout=3)
        return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(not bank_up(), reason=f"no sandbox bank at {BANK} (scripts/demo_up.sh starts one)")


def booked(ref: str) -> list[dict]:
    return [t for t in json.load(urllib.request.urlopen(BANK + "/transfers", timeout=3)) if t["id"] == ref]


def test_the_bank_shows_what_the_receipts_say():
    gw = Kavach(Environment(tempfile.mkdtemp(), invoice_demo=True), GatewayConfig(use_llm_judge=False))
    gw.env.bank = SandboxBank(BANK)
    tid, _ = gw.start_task("ravi", "ap_agent", "Review invoice INV-101 and prepare its payment using the approved "
                                              "vendor details.")
    gw.run(tid, ToolCall("mail.read_inbox", {}))
    pay = lambda acct: gw.run(tid, ToolCall("payment.release", {"invoice_id": "INV-101", "to_account": acct,
                                                                 "amount": 8000}))
    assert pay("TEST-ACCT-999").verdict == Verdict.DENY
    d = pay("TEST-ACCT-001")
    hold = gw.resolve_hitl(d.hitl_id, "meera", True, approver_role="ap_supervisor")
    ref = gw.env.holds[-1]["id"]
    assert hold["executed"] and booked(ref) == []                           # approved, still in its hold
    gw.settle(time.time() + PAYMENT_HOLD_S + 1)
    (t,) = booked(ref)
    assert (t["to_account"], t["amount"], t["currency"], t["memo"]) == ("TEST-ACCT-001", 8000.0, "INR", "INV-101")
    SandboxBank(BANK).pay({"id": "x", "hold": ref, "to": "TEST-ACCT-001", "amount": 8000.0})   # a retry
    assert len(booked(ref)) == 1                                             # booked once
    req = urllib.request.Request(BANK + f"/transfers/{ref}", method="DELETE")
    urllib.request.urlopen(req, timeout=3)                                   # leave a demo bank as it was
