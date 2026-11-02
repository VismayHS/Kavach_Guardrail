"""C2: where the Qualcomm judge sits. A stub stands in for the model, so these run offline."""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402

BENIGN = ("ravi", "analyst", "Email john.menon@client4.com that invoice 1042 is being processed.",
          ToolCall("mail.send", {"to": "john.menon@client4.com", "subject": "Invoice 1042",
                                 "body": "Hi John, invoice 1042 is being processed."}))
ESCALATED = ("asha", "support", "Refund 12000 on invoice 1042, the customer was double charged.",
             ToolCall("payments.refund", {"invoice_id": 1042, "amount": 12000}))


class StubJudgeLLM:
    """Flags everything and scores it 0.1: the strictest possible judge, so any effect it has shows."""
    enabled, model, picked, last_latency_ms = True, "stub", ("stub-8B", "stub-70B"), 5.0

    def __init__(self):
        self.calls = 0

    def pick_models(self):
        return self.picked

    def chat_text(self, messages, max_tokens=5, model=None, **kw):
        self.calls += 1
        return "FLAG" if max_tokens <= 5 else "ALIGNMENT: 0.1\nREASON: the user did not ask for this."


def gateway(mode):
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=True, judge_mode=mode, c_block=0.002))
    k.judge.llm = StubJudgeLLM()
    return k


def check(k, case):
    user, role, request, call = case
    tid, _ = k.start_task(user, role, request)
    return k.check(tid, ToolCall(call.tool, dict(call.args)))


def test_inline_judge_sits_in_every_state_changing_call():
    k = gateway("inline")
    d = check(k, BENIGN)
    assert k.judge.llm.calls == 2 and d.verdict == Verdict.ESCALATE        # it can turn an allow into a human check


def test_escalations_only_never_touches_an_auto_allowed_call():
    k = gateway("escalations-only")
    d = check(k, BENIGN)
    assert k.judge.llm.calls == 0 and d.verdict in (Verdict.ALLOW, Verdict.ALLOW_WITH_SAFEGUARD)
    e = check(k, ESCALATED)
    assert e.verdict == Verdict.ESCALATE and k.judge.llm.calls == 2
    assert e.risk.intent["review"]["llm_alignment"] == 0.1                  # the note is on the decision...
    assert k.hitl.items[e.hitl_id]["decision"]["risk"]["intent"]["review"]["llm_reason"]   # ...and the approval card


def test_async_judge_writes_its_note_later():
    k = gateway("async")
    e = check(k, ESCALATED)
    assert e.verdict == Verdict.ESCALATE
    for _ in range(100):
        if any(r["body"].get("type") == "judge-note" for r in k.receipts.items):
            break
        time.sleep(0.02)
    note = next(r for r in k.receipts.items if r["body"].get("type") == "judge-note")
    assert note["body"]["decision_receipt"] == e.receipt_id and note["body"]["note"]["llm_alignment"] == 0.1
    assert k.hitl.items[e.hitl_id]["decision"]["risk"]["intent"]["review"]["llm_alignment"] == 0.1
    assert k.receipts.verify()["valid"]
