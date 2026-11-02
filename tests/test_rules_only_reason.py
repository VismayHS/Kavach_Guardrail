"""With the risk model off (the rules-only configuration), an approval floor still names its rule: every receipt
cites the rule that decided. Before, the reason was just 'Policy requires approval.' (seen in AgentDojo logs)."""
import tempfile

from kavach.environment import Environment
from kavach.gateway import GatewayConfig, Kavach
from kavach.models import ToolCall, Verdict


def test_rules_only_escalation_cites_the_rule():
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False, use_risk=False))
    tid, _ = k.start_task("asha", "analyst", "Summarise my unread emails.")
    k.register_output(tid, ToolCall("mail.read_inbox", {}), [{"id": "m1", "from": "x@y.example",
                                                             "body": "see https://evil.example/next?a=1"}])
    d = k.check(tid, ToolCall("web.fetch", {"url": "https://evil.example/next?a=1"}))
    assert d.verdict == Verdict.ESCALATE and d.reason.startswith("[R1] "), d.reason
