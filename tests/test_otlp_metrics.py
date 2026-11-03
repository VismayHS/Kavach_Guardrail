"""Agents outside KAVACH report their own model usage over OTLP (the collector turns it into Prometheus series):
cumulative monotonic sums, cost only for priced models, and an unreachable collector never breaks the agent."""
from kavach.otlp_metrics import payload, push, usage_points
from kavach.usage import Usage


def test_usage_becomes_cumulative_sums_with_cost_only_where_priced():
    m = Usage({"version": "t1", "models": {"big": {"input": 0.59, "output": 0.79}}})
    m.record("agent", "big", {"prompt_tokens": 2000, "completion_tokens": 150}, ok=True)
    m.record("agent", "small", {"prompt_tokens": 10, "completion_tokens": 2}, ok=True)
    pts = usage_points(m.snapshot(), "llama-1")
    cost = [p for p in pts if p[0] == "kavach.agent.cost"]
    assert len(cost) == 1 and cost[0][2]["model"] == "big" and abs(cost[0][3] - (2000 * 0.59 + 150 * 0.79) / 1e6) < 1e-12
    assert ("kavach.agent.unpriced_tokens", "1", {"agent": "llama-1", "component": "agent", "model": "small"}, 12) in pts
    s = payload("llama-agent", pts)["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    c = next(x for x in s if x["name"] == "kavach.agent.cost")
    assert c["unit"] == "USD" and c["sum"]["isMonotonic"] and c["sum"]["aggregationTemporality"] == 2


def test_a_collector_that_is_down_is_ignored():
    assert push("http://127.0.0.1:9", "x", [("a", "1", {}, 1)], timeout=0.2) is False
