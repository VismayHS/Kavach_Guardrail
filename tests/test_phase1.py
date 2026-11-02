"""Phase 1: rules that don't depend on training (R15-R17), Indian identifiers, sessions, and unknown tools."""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import Conf, ToolCall, Verdict  # noqa: E402
from kavach.provenance import ProvenanceTracker, entities, is_pii  # noqa: E402


@pytest.fixture()
def gw():
    return Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))


def rules(d, outcome):
    return {g.rule_id for g in d.gates if g.outcome == outcome}


def read_customers(gw, tid, sql):
    rows = gw.env.crm_query(sql)
    spec = gw.registry.get("crm.query")
    gw.tasks[tid].prov.register_output("crm.query", rows, spec.output_trust, spec.output_conf)
    return rows


# ---------------------------------------------------------------- R15 values the agent made up
def test_r15_invented_amount_needs_a_human(gw):
    tid, _ = gw.start_task("meera", "finance", "Pay Northwind Supplies for invoice INV-88 to account ACC-11-2001.")
    d = gw.check(tid, ToolCall("payments.transfer", {"to_account": "ACC-11-2001", "amount": 6400, "memo": "INV-88"}))
    assert "R15" in rules(d, "REQUIRE_APPROVAL") and d.verdict == Verdict.ESCALATE
    tid, _ = gw.start_task("meera", "finance", "Pay Northwind Supplies 4200 for invoice INV-88 to account ACC-11-2001.")
    d = gw.check(tid, ToolCall("payments.transfer", {"to_account": "ACC-11-2001", "amount": 4200, "memo": "INV-88"}))
    assert "R15" not in rules(d, "REQUIRE_APPROVAL")


# ---------------------------------------------------------------- R16 scope
def test_r16_action_that_ignores_the_named_record_needs_a_human(gw):
    tid, _ = gw.start_task("asha", "support", "Remove the duplicate record for customer 17.")
    broad = gw.check(tid, ToolCall("crm.execute", {"sql": "DELETE FROM customers WHERE city = 'Pune' AND tier = 'gold'"}))
    assert "R16" in rules(broad, "REQUIRE_APPROVAL") and broad.verdict == Verdict.ESCALATE
    exact = gw.check(tid, ToolCall("crm.execute", {"sql": "DELETE FROM customers WHERE id = 17"}))
    assert "R16" not in rules(exact, "REQUIRE_APPROVAL")


def test_r16_one_digit_ids_count(gw):
    tid, _ = gw.start_task("asha", "support", "Remove the duplicate record for customer 3.")
    broad = gw.check(tid, ToolCall("crm.execute", {"sql": "DELETE FROM customers WHERE city = 'Pune' AND tier = 'gold'"}))
    assert "R16" in rules(broad, "REQUIRE_APPROVAL")
    assert "R16" not in rules(gw.check(tid, ToolCall("crm.execute", {"sql": "DELETE FROM customers WHERE id = 3"})),
                              "REQUIRE_APPROVAL")
    tid, _ = gw.start_task("asha", "support", "Refund 900 on invoice 3; the customer was double charged.")
    d = gw.check(tid, ToolCall("payments.refund", {"invoice_id": 3, "amount": 900}))
    assert "R16" not in rules(d, "REQUIRE_APPROVAL")                  # a bare 3 in a structured arg is the id


def test_r16_paying_a_different_invoice_needs_a_human(gw):
    tid, _ = gw.start_task("meera", "ap_supervisor", "Release the approved payment for invoice INV-3001.")
    d = gw.check(tid, ToolCall("payment.release", {"invoice_id": "INV-3022"}))
    assert "R16" in rules(d, "REQUIRE_APPROVAL") and d.verdict == Verdict.ESCALATE


# ---------------------------------------------------------------- R17 someone else's personal data
def test_r17_one_customers_phone_to_another_customer_needs_a_human(gw):
    tid, _ = gw.start_task("ravi", "analyst", "Email the status of invoice 1042.")
    a, b = read_customers(gw, tid, "SELECT id, name, email, phone FROM customers WHERE id IN (1, 2)")
    gw.add_request(tid, f"Email {b['email']} the status of invoice 1042.")
    other = gw.check(tid, ToolCall("mail.send", {"to": b["email"], "subject": "Invoice 1042",
                                                 "body": f"Invoice 1042 is due. Contact {a['name']} at {a['phone']}."}))
    assert "R17" in rules(other, "REQUIRE_APPROVAL") and other.verdict == Verdict.ESCALATE
    gw.add_request(tid, f"Email {a['email']} the status of invoice 1042.")
    own = gw.check(tid, ToolCall("mail.send", {"to": a["email"], "subject": "Invoice 1042",
                                               "body": f"Invoice 1042 is due. We have your number as {a['phone']}."}))
    assert "R17" not in rules(own, "REQUIRE_APPROVAL")         # their own details are fine


# ---------------------------------------------------------------- R24 the wrong customer
def test_r24_email_about_an_invoice_goes_to_that_invoices_customer(gw):
    tid, _ = gw.start_task("ravi", "analyst", "Email the customer on invoice 1042 that it is overdue.")
    owner = read_customers(gw, tid, "SELECT c.email FROM customers c JOIN invoices i ON i.customer_id = c.id "
                                    "WHERE i.id = 1042")[0]["email"]
    other = read_customers(gw, tid, "SELECT email FROM customers WHERE id NOT IN "
                                    "(SELECT customer_id FROM invoices WHERE id = 1042) LIMIT 1")[0]["email"]
    mail = lambda to: ToolCall("mail.send", {"to": to, "subject": "Invoice 1042", "body": "Invoice 1042 is overdue."})  # noqa: E731
    wrong = gw.check(tid, mail(other))
    assert "R24" in rules(wrong, "REQUIRE_APPROVAL") and wrong.verdict == Verdict.ESCALATE
    assert owner not in str(wrong.to_dict())               # the right customer's address isn't revealed
    assert "R24" not in rules(gw.check(tid, mail(owner)), "REQUIRE_APPROVAL")
    gw.add_request(tid, f"Email {other} that invoice 1042 is overdue.")       # the user chose this address
    assert "R24" not in rules(gw.check(tid, mail(other)), "REQUIRE_APPROVAL")


# ---------------------------------------------------------------- Indian identifiers
def test_indian_identifiers_are_detected_validated_and_masked():
    text = "UPI ravi.k@okhdfcbank, PAN ABCDE1234F, Aadhaar 2345 6789 0124, card 4111 1111 1111 1111"
    ents = entities(text)
    found = {"ravi.k@okhdfcbank", "pan:ABCDE1234F", "aadhaar:234567890124", "card:4111111111111111"}
    assert found <= ents and all(is_pii(e) for e in found)
    assert "card:4111111111111112" not in entities("bad card 4111 1111 1111 1112")         # fails Luhn
    assert not any(e.startswith("aadhaar:") for e in entities("ref 1234 5678 9012"))    # starts with 1 / bad check
    assert entities("billing@acme-invoices.co") == {"billing@acme-invoices.co"}   # an email, not a UPI id
    p = ProvenanceTracker()
    p.register_output("crm.query", [{"id": 9, "kyc": text}], "derived", Conf.PII)
    masked = p.mask(text)
    assert all(s not in masked for s in ("okhdfcbank", "ABCDE1234F", "2345 6789 0124", "4111 1111")), masked


# ---------------------------------------------------------------- sessions and unknown tools (HTTP API)
@pytest.fixture()
def api(monkeypatch):
    from fastapi.testclient import TestClient
    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", None)
    return TestClient(server.app)


INBOX = {"tool": "mail.read_inbox", "output": [{"id": "msg-1", "from": "x@ext.example", "body": "Hello", "unread": True}]}
CRM = {"tool": "crm.query", "output": [{"id": 5, "name": "A", "email": "a5@client5.com", "phone": "+91-9123456789"}]}
SEND = {"tool": "mail.send", "args": {"to": "partner@example.org", "subject": "Summary", "body": "All fine."},
        "user_request": "Summarise my unread emails.", "role": "analyst"}


def test_session_adds_up_what_the_agent_read_across_calls(api):
    first = api.post("/api/v1/check", json={**SEND, "context": [INBOX], "session_id": "s-phase1"}).json()
    second = api.post("/api/v1/check", json={**SEND, "context": [INBOX, CRM], "session_id": "s-phase1"}).json()
    assert second["task_id"] == first["task_id"]                 # one task for the whole session
    assert any(g["rule_id"] == "R14" for g in second["gates"])  # private data + untrusted content, across calls
    alone = api.post("/api/v1/check", json={**SEND, "context": [CRM]}).json()
    assert not any(g["rule_id"] == "R14" for g in alone["gates"])


def test_unknown_tool_with_annotations_escalates_until_an_admin_approves_it(api):
    call = {"user_request": "File a ticket for the outage.", "tool": "jira.create_issue_p1",
            "args": {"summary": "Outage"}, "role": "admin", "tool_description": "Create a Jira issue",
            "tool_annotations": {"readOnlyHint": False, "openWorldHint": False}}
    r = api.post("/api/v1/check", json=call).json()
    assert r["verdict"] == "ESCALATE" and any(g["rule_id"] == "R6" and g["outcome"] == "REQUIRE_APPROVAL"
                                              for g in r["gates"])
    assert "jira.create_issue_p1" in [t["name"] for t in api.get("/api/tools/drafts").json()]
    tools = api.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()["result"]["tools"]
    assert any(t["name"] == "jira.create_issue_p1" for t in tools)       # drafts don't break the MCP list
    assert api.post("/api/tools/jira.create_issue_p1/approve").json()["approved"] == "jira.create_issue_p1"
    after = api.post("/api/v1/check", json=call).json()
    assert not any(g["rule_id"] == "R6" and g["outcome"] != "PASS" for g in after["gates"])


def test_unknown_tool_without_a_description_is_still_denied(api):
    r = api.post("/api/v1/check", json={"user_request": "do it", "tool": "shell.run_p1", "args": {"cmd": "ls"},
                                        "role": "admin"}).json()
    assert r["verdict"] == "DENY" and r["reason"].startswith("[R6]")


def test_only_an_admin_can_approve_a_tool(monkeypatch, api):
    from kavach import auth, server
    secret = "kavach-test-secret-at-least-32-bytes-long"
    monkeypatch.setattr(server, "AUTH_SECRET", secret)
    analyst = {"Authorization": "Bearer " + auth.mint("ravi", "analyst", secret=secret)}
    assert api.post("/api/tools/anything/approve", headers=analyst).status_code == 403
