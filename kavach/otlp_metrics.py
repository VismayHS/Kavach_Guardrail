"""Push cumulative counters to an OpenTelemetry collector over OTLP/HTTP JSON, with the standard library only.

Used by agents that run outside KAVACH's process (scripts/llama_agent.py) to report their own model usage and cost,
the way Claude Code reports its own (CLAUDE_CODE_ENABLE_TELEMETRY): the collector turns them into Prometheus series
(deploy/otel-collector.yaml, :8889) and Grafana shows them next to KAVACH's own overhead.

    push("http://127.0.0.1:4318", "llama-agent", [("kavach.agent.cost", "USD", {"model": "Llama-3.3-70B"}, 0.0012)])

Never raises: an agent must not fail because the dashboard is down.
"""
from __future__ import annotations

import json
import time
import urllib.request

START_NS = time.time_ns()


def _attrs(d: dict) -> list[dict]:
    return [{"key": k, "value": {"stringValue": str(v)}} for k, v in d.items()]


def payload(service: str, points: list[tuple[str, str, dict, float]], start_ns: int = START_NS) -> dict:
    """points: (metric name, unit, attributes, cumulative value since start_ns). Monotonic cumulative sums."""
    now, by_name = time.time_ns(), {}
    for name, unit, attrs, value in points:
        m = by_name.setdefault(name, {"name": name, "unit": unit, "sum": {
            "aggregationTemporality": 2, "isMonotonic": True, "dataPoints": []}})
        m["sum"]["dataPoints"].append({"attributes": _attrs(attrs), "startTimeUnixNano": str(start_ns),
                                       "timeUnixNano": str(now), "asDouble": float(value)})
    return {"resourceMetrics": [{"resource": {"attributes": _attrs({"service.name": service})},
                                 "scopeMetrics": [{"scope": {"name": "kavach"}, "metrics": list(by_name.values())}]}]}


def push(endpoint: str, service: str, points: list, timeout: float = 2.0, start_ns: int = START_NS) -> bool:
    if not endpoint or not points:
        return False
    req = urllib.request.Request(endpoint.rstrip("/") + "/v1/metrics",
                                 data=json.dumps(payload(service, points, start_ns)).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status < 300
    except Exception:
        return False


def usage_points(snapshot: dict, agent: str) -> list:
    """A usage.METER snapshot as points: tokens by model and kind, and cost for priced models."""
    out = []
    for r in snapshot.get("rows", []):
        base = {"agent": agent, "component": r["component"], "model": r["model"]}
        out.append(("kavach.agent.tokens", "1", {**base, "kind": "prompt"}, r["prompt_tokens"]))
        out.append(("kavach.agent.tokens", "1", {**base, "kind": "completion"}, r["completion_tokens"]))
        out.append(("kavach.agent.calls", "1", {**base, "outcome": "error"}, r["errors"]))
        out.append(("kavach.agent.calls", "1", {**base, "outcome": "ok"}, r["calls"] - r["errors"]))
        if r.get("priced"):
            out.append(("kavach.agent.cost", "USD", {**base, "prices": snapshot.get("price_table", "")}, r["cost_usd"]))
        else:
            out.append(("kavach.agent.unpriced_tokens", "1", base, r["prompt_tokens"] + r["completion_tokens"]))
    return out
