"""E8: Presidio PII detection with Indian recognisers (skipped where presidio or the spaCy model isn't installed)."""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach import pii  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall  # noqa: E402
from kavach.provenance import _aadhaar_ok  # noqa: E402

pytestmark = pytest.mark.skipif(not pii.available(), reason="presidio-analyzer and en_core_web_sm not installed")


def aadhaar() -> str:
    """A number with a valid Verhoeff check digit (synthetic, as every value in this repo)."""
    base = "23456789012"
    d = next(base + str(c) for c in range(10) if _aadhaar_ok(base + str(c)))
    return f"{d[:4]} {d[4:8]} {d[8:]}"


@pytest.fixture(scope="module")
def detector():
    return pii.PIIDetector()


def test_indian_identifiers_are_found(detector):
    a = aadhaar()
    found = {f["type"] for f in detector.find(f"PAN ABCDE1234F, Aadhaar {a}, UPI ravi.k@okhdfcbank, call +91 98450 12345")}
    assert {"IN_PAN", "IN_AADHAAR", "IN_UPI"} <= found and ({"IN_PHONE", "PHONE_NUMBER"} & found)
    bad = a[:-1] + str((int(a[-1]) + 1) % 10)                                   # wrong check digit
    assert "IN_AADHAAR" not in {f["type"] for f in detector.find(f"Aadhaar {bad}")}


def test_pii_typed_from_memory_still_counts_for_r2():
    def decide(use):
        k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False, use_presidio=use))
        tid, _ = k.start_task("ravi", "analyst", "Send the KYC details to onboarding@partner.example.")
        d = k.check(tid, ToolCall("mail.send", {"to": "onboarding@partner.example", "subject": "KYC",
                                                "body": f"Asha Rao, Aadhaar {aadhaar()}, mobile +91 98450 12345"}))
        return {g.rule_id: g.outcome for g in d.gates}["R2"]
    assert decide(False) == "PASS"                     # KAVACH never saw these values come in
    assert decide(True) == "REQUIRE_APPROVAL"          # Presidio sees personal data leaving


def test_personal_data_in_a_page_makes_the_task_private():
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False, use_presidio=True))
    page = "https://intranet.infycorp.com/hr/directory"
    k.env.web[page] = "Directory: Asha Rao, asha.rao@infycorp.com, mobile +91 98450 12345, PAN ABCDE1234F."
    tid, _ = k.start_task("ravi", "analyst", f"Open {page}.")
    k.run(tid, ToolCall("web.fetch", {"url": page}))
    assert k.tasks[tid].prov.private_seen and "pan:ABCDE1234F" in k.tasks[tid].prov.pii_values
