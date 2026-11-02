"""A10: everything except the Qualcomm calls runs offline (the demo must survive a dead network).

With no Qualcomm variables set, the judge and the explainer fall back to the heuristic and the template, the
server answers every dashboard endpoint, and the attacks are still stopped by the rules.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

QUALCOMM_VARS = ("IMAGINE_API_KEY", "INFERENCE_CLOUD_API_KEY", "IMAGINE_API_ENDPOINT", "IMAGINE_ENDPOINT_URL",
                 "INFERENCE_CLOUD_ENDPOINT")


@pytest.fixture()
def offline(monkeypatch):
    for k in QUALCOMM_VARS:
        monkeypatch.delenv(k, raising=False)


def test_qualcomm_client_is_disabled_without_a_key(offline):
    from kavach.qualcomm import QualcommCloudAI
    assert not QualcommCloudAI().enabled


def test_judge_and_explainer_fall_back(offline, tmp_path):
    from kavach.environment import Environment
    from kavach.explain import Explainer
    from kavach.gateway import GatewayConfig, Kavach
    from kavach.models import ToolCall
    from kavach.qualcomm import QualcommCloudAI
    k = Kavach(Environment(str(tmp_path)), GatewayConfig(use_llm_judge=True, use_llm_explainer=True))
    k.judge.llm, k.explainer = QualcommCloudAI(), Explainer(QualcommCloudAI(), use_llm=True)
    tid, _ = k.start_task("asha", "support", "Mark invoice 1042 as paid.")
    d = k.check(tid, ToolCall("crm.execute", {"sql": "UPDATE invoices SET status = 'paid' WHERE id = 1042"}))
    assert d.risk.intent["source"] == "heuristic" and d.explanation.startswith("ALLOW")


def test_dashboard_endpoints_answer_offline(offline, monkeypatch):
    from fastapi.testclient import TestClient
    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", None)
    c = TestClient(server.app)
    assert c.get("/").status_code == 200
    for path in ("/api/scenarios", "/api/state", "/api/hitl", "/api/receipts", "/api/receipts/verify", "/api/autonomy"):
        assert c.get(path).status_code == 200, path
    run = c.post("/api/demo/email_injection").json()
    assert run["steps"][-1]["verdict"] == "DENY" and run["state"]["outbox"] == 0
    assert c.get("/api/receipts/verify").json()["valid"]


def test_parallel_tool_calls_are_sent_as_sequential_pairs():
    from kavach.qualcomm import sequential_tool_calls
    call = lambda i: {"id": i, "type": "function", "function": {"name": "f", "arguments": "{}"}}  # noqa: E731
    msgs = [{"role": "user", "content": "hi"},
            {"role": "assistant", "content": "doing both", "tool_calls": [call("a"), call("b")]},
            {"role": "tool", "tool_call_id": "a", "content": "A"}, {"role": "tool", "tool_call_id": "b", "content": "B"},
            {"role": "assistant", "content": "done"}]
    out = sequential_tool_calls(msgs)
    assert [m["role"] for m in out] == ["user", "assistant", "tool", "assistant", "tool", "assistant"]
    assert [m.get("tool_call_id") or [c["id"] for c in m.get("tool_calls", [])] for m in out[1:5]] == [["a"], "a", ["b"], "b"]
    assert out[1]["content"] == "doing both" and out[3]["content"] == ""
    single = [{"role": "assistant", "content": "", "tool_calls": [call("x")]}, {"role": "tool", "tool_call_id": "x", "content": "X"}]
    assert sequential_tool_calls(single) == single
