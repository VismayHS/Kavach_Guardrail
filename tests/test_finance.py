"""F7: IBAN validity (R30), sanctions screening (R21), Confirmation of Payee (R31)."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.finance import SanctionsList, iban_check, ifsc_valid  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall  # noqa: E402


def rules(d, outcome):
    return {g.rule_id for g in d.gates if g.outcome == outcome}


def test_iban_and_ifsc():
    for good in ("DE89370400440532013000", "GB33 BUKB 2020 1555 5555 55", "NL91ABNA0417164300"):
        assert iban_check(good)[0], good
    assert not iban_check("GB34BUKB20201555555555")[0] and "check digits" in iban_check("GB34BUKB20201555555555")[1]
    assert not iban_check("DE8937040044053201300")[0]
    assert ifsc_valid("HDFC0001234") and not ifsc_valid("HDFC1001234")


def test_sanctions_screening_is_fuzzy_on_names():
    s = SanctionsList.load()
    for n in ("Fabrikam Trading LLC", "FABRIKAM FZE", "Fabrikam Trading L.L.C."):
        assert s.screen(n), n
    for n in ("Northwind Supplies GmbH", "Contoso Logistics BV"):
        assert s.screen(n) is None, n


def test_sanctions_csv(tmp_path):
    f = tmp_path / "targets.simple.csv"
    f.write_text("id,schema,name,aliases\nNK-1,Organization,Acme Shadow Trading Co,ASTC\nQ1,Person,Jane Roe,\n")
    s = SanctionsList.load(str(f))
    assert s.screen("ACME SHADOW TRADING COMPANY")["id"] == "NK-1"


def gw():
    return Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))


def test_invalid_iban_on_a_bank_change_is_denied():
    k = gw()
    tid, _ = k.start_task("meera", "ap_supervisor", "Update vendor V001's bank details to GB34BUKB20201555555555.")
    d = k.check(tid, ToolCall("vendor.update_bank", {"vendor_id": "V001", "iban": "GB34BUKB20201555555555"}))
    assert d.verdict.value == "DENY" and "R30" in rules(d, "DENY")


def test_confirmation_of_payee_mismatch_needs_approval():
    k = gw()
    k.env.iban_holders["GB33BUKB20201555555555"] = "Quick Cash Holdings Ltd"
    tid, _ = k.start_task("meera", "ap_supervisor", "Update vendor V001's bank details to GB33BUKB20201555555555.")
    d = k.check(tid, ToolCall("vendor.update_bank", {"vendor_id": "V001", "iban": "GB33BUKB20201555555555"}))
    assert "R31" in rules(d, "REQUIRE_APPROVAL") and "Quick Cash" in d.explanation + str([g.message for g in d.gates])
    k.env.iban_holders["GB33BUKB20201555555555"] = "Northwind Supplies GmbH"
    ok = k.check(tid, ToolCall("vendor.update_bank", {"vendor_id": "V001", "iban": "GB33BUKB20201555555555"}))
    assert "R31" not in rules(ok, "REQUIRE_APPROVAL")


def test_screening_blocks_a_renamed_sanctioned_vendor():
    k = gw()
    k.env.db.execute("UPDATE vendors SET sanctioned = 0, name = 'FABRIKAM FZE' WHERE id = 'V012'")  # flag missing
    tid, _ = k.start_task("meera", "ap_supervisor", "Release the approved payment for invoice INV-3070.")
    d = k.check(tid, ToolCall("payment.release", {"invoice_id": "INV-3070"}))
    assert d.verdict.value == "DENY" and "R21" in rules(d, "DENY") and "sanctions list" in d.reason
