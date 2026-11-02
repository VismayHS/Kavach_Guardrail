"""The evaluation scripts run offline and keep their promises about what they write."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench import semantic_eval  # noqa: E402


def test_semantic_cases_are_balanced_and_left_to_meaning():
    labels = [c["label"] for c in semantic_eval.CASES]
    assert labels.count(0) == labels.count(1) == 12
    out = semantic_eval.main(offline=True)
    assert out["rule_decided"] == []          # every case reaches the judge; a rule that decides one is reported
    assert "on" not in out["cases"][0]        # offline never pretends to have asked a model


def test_live_logs_from_the_stand_in_never_land_next_to_real_ones(tmp_path, monkeypatch):
    from agent import llm_agent
    monkeypatch.setattr(llm_agent, "LIVE", tmp_path / "results" / "live")
    out = {"guarded": True, "endpoint_host": "localhost", "messages": [], "trace": []}
    assert "rehearsal" in llm_agent.save_log(out, "20261102T000000Z").parts
    real = llm_agent.save_log({**out, "endpoint_host": "aisuite.cirrascale.com"}, "20261102T000000Z")
    assert real.parent == tmp_path / "results" / "live" and real.name.endswith("-guarded.json")


def test_model_score_ablation_zeroes_the_model_but_keeps_rules():
    import tempfile
    from kavach.environment import Environment
    from kavach.gateway import GatewayConfig, Kavach
    from kavach.models import ToolCall
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False, model_scores=False))
    tid, _ = gw.start_task("asha", "support", "Drop the customers table.")
    d = gw.check(tid, ToolCall("crm.execute", {"sql": "DROP TABLE customers"}))
    assert d.risk.p_hi == 0.0 and d.verdict.value == "DENY"
