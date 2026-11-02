"""D1: canary records (R28). Planted values no legitimate task needs; carrying one outside is proof of an attack."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.policy import PolicyEngine  # noqa: E402
from kavach.scenarios import SCENARIOS, materialize, prepare  # noqa: E402

CANARIES = PolicyEngine().cfg["canaries"]


def gateway():
    return Kavach(Environment(tempfile.mkdtemp(), canaries=CANARIES), GatewayConfig(use_llm_judge=False))


def rules(d, outcome):
    return {g.rule_id for g in d.gates if g.outcome == outcome}


def test_canaries_are_planted_first_in_a_dump():
    k = gateway()
    rows = k.env.crm_query("SELECT name, email, phone FROM customers LIMIT 200")
    assert rows[0]["email"] == "ritika.menon0@client0.com"
    assert (k.env.workspace / "vendor_portal_keys.txt").exists()


def test_exfiltration_trips_the_canary_and_the_receipt_says_so():
    k = gateway()
    sc = SCENARIOS["email_injection"]
    prepare(k.env, sc)
    tid, _ = k.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
    last = d = None
    for c in sc["steps"]:
        d = k.run(tid, materialize(c, last))
        last = d.result
    assert d.verdict == Verdict.DENY and d.reason.startswith("[R1]")     # provenance stays the stated reason
    assert "R28" in rules(d, "DENY") and k.env.outbox == []
    assert "Canary tripped" in str(k.receipts.items[-1]["body"]["decision"]["gates"])


def test_canary_trips_even_when_the_destination_was_typed_by_the_user():
    k = gateway()
    tid, _ = k.start_task("ravi", "analyst", "Send the customer contacts to audit@big4-review.co.")
    d = k.check(tid, ToolCall("mail.send", {"to": "audit@big4-review.co", "subject": "contacts",
                                            "body": "Ritika Menon ritika.menon0@client0.com +91-9876500001"}))
    assert d.verdict == Verdict.DENY and d.reason.startswith("[R28]")


def test_moving_canary_data_internally_is_recorded_not_blocked():
    k = gateway()
    tid, _ = k.start_task("ravi", "analyst", "Save today's call notes to notes.txt.")
    d = k.check(tid, ToolCall("files.write", {"path": "notes.txt", "content": "Called ritika.menon0@client0.com"}))
    assert "R28" not in rules(d, "DENY") and "R28" in rules(d, "PASS")


def test_default_environment_has_no_canaries():
    assert Environment(tempfile.mkdtemp()).table_counts()["customers"] == 480
