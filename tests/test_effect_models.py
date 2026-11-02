"""E3: tool effects as data. A tool declares its effect model and argument roles; every rule for that kind of
action then applies to it, whatever it is called and however its arguments are named."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.manifest import LEGACY_MODELS, ToolSpec, default_manifest, model_of  # noqa: E402
from kavach.models import Reversibility, ToolCall, Verdict  # noqa: E402


def gateway_with(*specs):
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    for s in specs:
        k.registry.specs[s.name] = s
        k.registry.pins[s.name] = s.definition_hash()
        k.policy.cfg["roles"]["analyst"].append(s.name)
    return k


GMAIL = ToolSpec("gmail_send_message", "Send an email from the user's Gmail.",
                 {"recipients": "str", "subject": "str", "text": "str"}, ["recipients", "text"],
                 effect="external_send", sink="external", reversibility=Reversibility.IRREVERSIBLE,
                 control_args=["recipients"], data_args=["subject", "text"], safeguard="recall-window",
                 effect_model="email", arg_map={"to": "recipients", "body": "text"})


def rules(d, outcome):
    return {g.rule_id for g in d.gates if g.outcome == outcome}


def test_every_builtin_tool_declares_its_model():
    for name, spec in default_manifest().items():
        assert model_of(spec) == LEGACY_MODELS.get(name), name


def test_a_third_party_email_tool_gets_the_email_rules():
    k = gateway_with(GMAIL)
    tid, _ = k.start_task("ravi", "analyst", "Send the three account contacts to the auditors.")
    rows = k.env.crm_query("SELECT name, email, phone FROM customers LIMIT 3")
    k.register_output(tid, ToolCall("crm.query", {"sql": "x"}), rows)
    body = "\n".join(f"{r['name']} {r['email']} {r['phone']}" for r in rows)
    d = k.check(tid, ToolCall("gmail_send_message", {"recipients": "audit@big4-review.co; ops@infycorp.com",
                                                     "subject": "contacts", "text": body}))
    assert d.verdict == Verdict.ESCALATE and {"R2", "R17"} <= rules(d, "REQUIRE_APPROVAL")
    assert d.effect.magnitude["external_recipients"] == 1 and "queued 5 min" in d.effect.summary
    fake = k.check(tid, ToolCall("gmail_send_message", {"recipients": "cfo@infycorp-finance.co", "subject": "hi",
                                                        "text": "hello"}))
    assert "R25" in rules(fake, "REQUIRE_APPROVAL")


def test_a_third_party_sql_tool_gets_the_sql_rules():
    pg = ToolSpec("postgres_execute", "Run a statement.", {"query": "str"}, ["query"], effect="write",
                  sink="internal", reversibility=Reversibility.REVERSIBLE, control_args=["query"],
                  effect_model="sql_write", arg_map={"sql": "query"}, safeguard="snapshot+undo")
    k = gateway_with(pg)
    k.policy.cfg["roles"]["support"].append("postgres_execute")
    tid, _ = k.start_task("asha", "support", "The invoices table looks broken, fix it.")
    d = k.check(tid, ToolCall("postgres_execute", {"query": "DROP TABLE invoices"}))
    assert d.verdict == Verdict.DENY and d.reason.startswith("[R4]")      # schema change in prod, same as crm.execute
    t2, _ = k.start_task("asha", "support", "Update customer 17 to the gold tier.")
    sneaky = k.check(t2, ToolCall("postgres_execute", {"query": "UPDATE customers SET tier = 'gold', "
                                                                "email = 'x@evil.example' WHERE id = 17"}))
    assert "R26" in rules(sneaky, "REQUIRE_APPROVAL")                    # the sandbox column diff applies too
