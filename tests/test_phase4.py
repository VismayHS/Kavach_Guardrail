"""Phase 4: the two-stage Qualcomm judge (fast triage, strong model only on flagged calls, cached), model choice from
GET /models, and the autonomy meter. No network: a scripted stand-in plays the Qualcomm API."""
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.intent import IntentJudge, heuristic_alignment  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.qualcomm import QualcommCloudAI  # noqa: E402


class ScriptedLLM:
    """Answers the triage prompt with `triage` and the reviewer prompt with `judge`; records which model was asked."""
    enabled, model, last_latency_ms = True, "configured", 2.0

    def __init__(self, triage, judge=None, fail=False):
        self.triage, self.judge, self.fail, self.calls = triage, judge, fail, []

    def pick_models(self):
        return "small-8B", "big-70B"

    def chat_json(self, messages, model=None, **kw):
        self.calls.append(model)
        if self.fail:
            raise TimeoutError("network down")
        return self.triage if "triage" in messages[0]["content"] else self.judge


ASK = ("Update customer 17 to the gold tier.", "crm.execute",
       {"sql": "UPDATE customers SET tier = 'gold' WHERE id = 17"}, {})


def test_a_call_the_fast_model_clears_never_reaches_the_strong_model():
    llm = ScriptedLLM({"flag": False})
    out = IntentJudge(llm).score(*ASK, ambiguous=True)
    assert llm.calls == ["small-8B"] and out["alignment"] == heuristic_alignment(ASK[0], ASK[1], {})["alignment"]
    assert out["source"].startswith("qualcomm-triage")


@pytest.mark.parametrize("triage", [{"flag": True}, {"flag": "false"}, {}, {"verdict": "fine"}])
def test_anything_but_an_explicit_false_goes_to_the_strong_model(triage):
    llm = ScriptedLLM(triage, {"alignment": 0.1, "reason": "the user asked about one customer"})
    out = IntentJudge(llm).score(*ASK, ambiguous=True)
    assert llm.calls == ["small-8B", "big-70B"] and out["alignment"] == 0.1


def test_the_strong_model_can_only_lower_alignment():
    base = heuristic_alignment(ASK[0], ASK[1], {})["alignment"]
    out = IntentJudge(ScriptedLLM({"flag": True}, {"alignment": 0.99})).score(*ASK, ambiguous=True)
    assert out["alignment"] == base < 0.99


def test_verdicts_are_cached_and_failures_are_not():
    llm = ScriptedLLM({"flag": True}, {"alignment": 0.4})
    judge = IntentJudge(llm)
    judge.score(*ASK, ambiguous=True)
    judge.score(*ASK, ambiguous=True)
    assert len(llm.calls) == 2                                   # second time from the cache
    judge.score(ASK[0], ASK[1], {"sql": "UPDATE customers SET tier = 'gold' WHERE id = 18"}, {}, ambiguous=True)
    assert len(llm.calls) == 4                                   # a different call is asked again
    down = ScriptedLLM(None, fail=True)
    judge = IntentJudge(down)
    first = judge.score(*ASK, ambiguous=True)
    assert first["source"] == "heuristic (llm unavailable)" and first["llm_error"] == "TimeoutError"
    judge.score(*ASK, ambiguous=True)
    assert len(down.calls) == 2                                  # retried, not served a cached failure


def test_judge_models_come_from_the_live_model_list(monkeypatch):
    monkeypatch.delenv("KAVACH_JUDGE_MODEL", raising=False)
    monkeypatch.delenv("KAVACH_JUDGE_STRONG_MODEL", raising=False)
    q = QualcommCloudAI(endpoint="http://x", api_key="k", model="Llama-3.1-8B")
    monkeypatch.setattr(q, "models", lambda: {"llm": ["Llama-3.3-70B", "Mistral-7B-Instruct", "Llama-3.1-8B"],
                                              "embedding": ["BAAI/bge-large-en-v1.5"]})
    assert q.pick_models() == ("Mistral-7B-Instruct", "Llama-3.3-70B")
    q2 = QualcommCloudAI(endpoint="http://x", api_key="k", model="Llama-3.1-8B")
    monkeypatch.setattr(q2, "models", lambda: {"data": [{"id": "llama-3.1-8b-instruct"}, {"id": "llama-3.3-70b"}]})
    assert q2.pick_models() == ("llama-3.1-8b-instruct", "llama-3.3-70b")   # OpenAI-style list, lower case
    q3 = QualcommCloudAI(endpoint="http://x", api_key="k", model="Llama-3.1-8B")

    def down():
        raise ConnectionError("no network")
    monkeypatch.setattr(q3, "models", down)
    assert q3.pick_models() == ("Llama-3.1-8B", "Llama-3.1-8B") and q3.picked is None   # asked again next time


# ---------------------------------------------------------------- in the gateway: stricter, never looser
def gateway(llm):
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=True))
    k.judge = IntentJudge(llm)
    return k


def test_the_judge_can_send_a_rule_passing_action_to_a_human():
    k = gateway(ScriptedLLM({"flag": True}, {"alignment": 0.1, "reason": "not what was asked"}))
    tid, _ = k.start_task("asha", "support", ASK[0])
    d = k.check(tid, ToolCall(ASK[1], ASK[2]))
    assert d.verdict == Verdict.ESCALATE and d.reason.startswith("Intent mismatch")


def test_the_judge_cannot_lift_a_deny():
    k = gateway(ScriptedLLM({"flag": False}, {"alignment": 1.0}))
    tid, _ = k.start_task("asha", "support", "Tidy up the CRM a bit.")
    assert k.check(tid, ToolCall("crm.execute", {"sql": "DROP TABLE invoices"})).verdict == Verdict.DENY


# ---------------------------------------------------------------- autonomy meter
def test_autonomy_meter_counts_changes_that_ran_without_a_human(monkeypatch):
    from fastapi.testclient import TestClient
    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", None)
    api = TestClient(server.app)
    before = api.get("/api/autonomy").json()
    for name in ("ap_clean_release", "drop_table", "big_refund"):     # paid alone (held), blocked, sent to a human
        api.post(f"/api/demo/{name}")
    after = api.get("/api/autonomy").json()
    delta = {k: after[k] - before[k] for k in ("changes", "without_a_human", "to_a_human", "blocked")}
    assert delta == {"changes": 3, "without_a_human": 1, "to_a_human": 1, "blocked": 1}     # reads don't count
    assert after["reviews_avoided_usd"] == [35 * after["without_a_human"], 75 * after["without_a_human"]]
