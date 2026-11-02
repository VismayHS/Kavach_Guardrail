"""F6: OpenTelemetry spans per decision, Prometheus metrics, SIEM forwarding (against stand-in endpoints)."""
import json
import sys
import tempfile
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall  # noqa: E402
from kavach.telemetry import SiemForwarder, Tracing, metrics_text  # noqa: E402


def run_two(k):
    tid, _ = k.start_task("ravi", "analyst", "Summarise my unread emails.")
    k.run(tid, ToolCall("mail.read_inbox", {"unread_only": True}))
    k.check(tid, ToolCall("mail.send", {"to": "billing@acme-invoices.co", "subject": "recon", "body": "list"}))


def test_one_genai_span_per_decision_without_arguments():
    pytest.importorskip("opentelemetry.sdk")
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    exp = InMemorySpanExporter()
    tp = TracerProvider()
    tp.add_span_processor(SimpleSpanProcessor(exp))
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    k.receipts.listeners.append(Tracing(tp))
    run_two(k)
    spans = exp.get_finished_spans()
    assert [s.name for s in spans] == ["execute_tool mail.read_inbox", "execute_tool mail.send"]
    send = spans[1].attributes
    assert send["gen_ai.operation.name"] == "execute_tool" and send["kavach.verdict"] == "DENY"
    assert "R1" in send["kavach.rule_ids"] and spans[1].status.status_code.name == "ERROR"
    assert not any("billing@" in str(v) for v in send.values())               # no arguments exported


def test_prometheus_metrics():
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    run_two(k)
    text = metrics_text(k)
    assert 'kavach_decisions_total{tool="mail.send",verdict="DENY"} 1' in text
    assert 'kavach_rule_hits_total{rule="R1",outcome="DENY"} 1' in text and "kavach_check_latency_ms_count 2" in text


@pytest.mark.parametrize("kind", ["splunk", "sentinel", "webhook"])
def test_siem_forwarding(kind):
    got = []

    def siem(request):
        got.append((request.headers.get("authorization"), request.content))
        return httpx.Response(200, json={"text": "Success"})
    fwd = SiemForwarder(kind, "https://siem.example/ingest", token="T0K", transport=httpx.MockTransport(siem))
    k = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    k.receipts.listeners.append(fwd)
    run_two(k)
    fwd.flush()
    assert fwd.sent == len(k.receipts.items) == 3 and fwd.failed == 0      # decisions and the execution receipt
    events = []
    for _, content in got:                     # each format wraps the same event differently
        if kind == "splunk":
            lines = [json.loads(x) for x in content.decode().splitlines()]
            assert all(x["sourcetype"] == "kavach:receipt" for x in lines)
            events += [x["event"] for x in lines]
        elif kind == "sentinel":
            events += json.loads(content)
        else:
            events.append(json.loads(content))
    send = [e for e in events if e.get("tool") == "mail.send"]
    assert send and send[0]["verdict"] == "DENY" and send[0]["rules"] == ["R1"]
    auth = got[0][0]
    assert auth == {"splunk": "Splunk T0K", "sentinel": "Bearer T0K", "webhook": "Bearer T0K"}[kind]
    if kind == "sentinel":
        assert isinstance(json.loads(got[0][1]), list) and "TimeGenerated" in json.loads(got[0][1])[0]


def test_metrics_endpoint(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    monkeypatch.setattr(server, "AUTH_SECRET", None)
    c = TestClient(server.app)
    c.post("/api/demo/drop_table")
    r = c.get("/metrics")
    assert r.status_code == 200 and "kavach_rule_hits_total" in r.text and r.headers["content-type"].startswith("text/plain")
