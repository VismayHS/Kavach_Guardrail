"""Telemetry and SIEM export (F6). Everything here listens to the receipt chain, so it sees exactly what was decided
and can never change or block a decision.

OpenTelemetry: one span per decision, named `execute_tool {tool}` with the GenAI semantic conventions
(gen_ai.operation.name, gen_ai.tool.name, gen_ai.tool.call.id) plus kavach.* attributes (verdict, rules, p_harm,
receipt). Tool arguments and results are *not* exported (they may carry personal data), as the conventions advise.
Export with the standard OTEL_EXPORTER_OTLP_ENDPOINT to any OpenTelemetry collector (Grafana, Datadog, Honeycomb...).

Prometheus: `metrics_text(gw)` serves counters and a latency histogram at GET /metrics.

SIEM: `SiemForwarder` posts each receipt (decisions, approvals, kills, undos, anchors) to Splunk HTTP Event Collector,
Microsoft Sentinel (Logs Ingestion API) or any JSON webhook, from a background queue.
"""
from __future__ import annotations

import queue
import threading
import time

LATENCY_BUCKETS_MS = (1, 2, 5, 10, 25, 50, 100, 250, 1000, 5000)


def decision_attributes(rec: dict) -> dict:
    d = rec["body"]["decision"]
    rules = [g["rule_id"] for g in d.get("gates", []) if g.get("outcome") != "PASS"]
    attrs = {"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": d["call"]["tool"],
             "gen_ai.tool.call.id": d["call"].get("call_id", ""), "gen_ai.conversation.id": rec["body"].get("task_id", ""),
             "kavach.verdict": d["verdict"], "kavach.rule_ids": rules, "kavach.receipt_id": rec["id"],
             "kavach.latency_ms": float(d.get("latency_ms") or 0.0), "kavach.authenticated": bool(rec["body"].get("authenticated"))}
    if d.get("risk"):
        attrs["kavach.p_harm"] = float(d["risk"]["p_harm"])
        attrs["kavach.tau"] = float(d["risk"]["tau"])
    if d.get("hitl_id"):
        attrs["kavach.hitl_id"] = d["hitl_id"]
    return attrs


class Tracing:
    """Receipt listener that emits one OpenTelemetry span per decision."""

    def __init__(self, tracer_provider=None):
        from opentelemetry import trace
        self.tracer = (tracer_provider or trace.get_tracer_provider()).get_tracer("kavach", "0.2")

    def __call__(self, rec: dict) -> None:
        if rec["body"].get("type") != "decision":
            return
        from opentelemetry.trace import Status, StatusCode
        a = decision_attributes(rec)
        end = int(rec["ts"] * 1e9)
        span = self.tracer.start_span(f"execute_tool {a['gen_ai.tool.name']}",
                                      start_time=end - int(a["kavach.latency_ms"] * 1e6), attributes=a)
        if a["kavach.verdict"] == "DENY":
            span.set_status(Status(StatusCode.ERROR, "blocked by KAVACH"))
        span.end(end_time=end)


def setup_tracing():
    """An OTLP/HTTP exporter when OTEL_EXPORTER_OTLP_ENDPOINT is set (the standard variable); else None."""
    import os
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return None
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    provider = TracerProvider(resource=Resource.create({"service.name": os.environ.get("OTEL_SERVICE_NAME", "kavach")}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    return Tracing(provider)


def metrics_text(gw) -> str:
    """Prometheus exposition format, computed from the receipt chain and the live queues."""
    verdicts, rules, lat = {}, {}, []
    for r in gw.receipts.items:
        if r["body"].get("type") != "decision":
            continue
        d = r["body"]["decision"]
        verdicts[(d["call"]["tool"], d["verdict"])] = verdicts.get((d["call"]["tool"], d["verdict"]), 0) + 1
        for g in d.get("gates", []):
            if g.get("outcome") != "PASS":
                rules[(g["rule_id"], g["outcome"])] = rules.get((g["rule_id"], g["outcome"]), 0) + 1
        lat.append(float(d.get("latency_ms") or 0))
    out = ["# HELP kavach_decisions_total Decisions by tool and verdict.", "# TYPE kavach_decisions_total counter"]
    out += [f'kavach_decisions_total{{tool="{t}",verdict="{v}"}} {n}' for (t, v), n in sorted(verdicts.items())]
    out += ["# HELP kavach_rule_hits_total Rules that denied or required approval.", "# TYPE kavach_rule_hits_total counter"]
    out += [f'kavach_rule_hits_total{{rule="{r}",outcome="{o}"}} {n}' for (r, o), n in sorted(rules.items())]
    out += ["# HELP kavach_check_latency_ms Time to decide one tool call.", "# TYPE kavach_check_latency_ms histogram"]
    for b in LATENCY_BUCKETS_MS:
        out.append(f'kavach_check_latency_ms_bucket{{le="{b}"}} {sum(x <= b for x in lat)}')
    out += [f'kavach_check_latency_ms_bucket{{le="+Inf"}} {len(lat)}', f"kavach_check_latency_ms_sum {sum(lat):.3f}",
            f"kavach_check_latency_ms_count {len(lat)}"]
    pending = len(gw.hitl.pending())
    held = sum(h["status"] == "held" for h in getattr(gw.env, "holds", []))
    out += ["# HELP kavach_approvals_pending Calls waiting for a person.", "# TYPE kavach_approvals_pending gauge",
            f"kavach_approvals_pending {pending}",
            "# HELP kavach_holds_waiting Payments and emails inside their undo window.", "# TYPE kavach_holds_waiting gauge",
            f"kavach_holds_waiting {held}",
            "# HELP kavach_kills_active Active pauses (kill switch).", "# TYPE kavach_kills_active gauge",
            f"kavach_kills_active {len(gw.kills)}",
            "# HELP kavach_receipts_total Receipts in the chain.", "# TYPE kavach_receipts_total counter",
            f"kavach_receipts_total {len(gw.receipts.items)}"]
    return "\n".join(out) + "\n"


class SiemForwarder:
    """Posts receipts to a SIEM from a background thread (a slow SIEM never slows a decision).

    kind="splunk":   Splunk HTTP Event Collector; url .../services/collector/event, token = HEC token
    kind="sentinel": Azure Monitor Logs Ingestion API; url https://<dce>/dataCollectionRules/<dcr-id>/streams/<stream>
                     ?api-version=2023-01-01, token = an Entra ID bearer token for the DCR
    kind="webhook":  any endpoint taking a JSON object per receipt
    """

    def __init__(self, kind: str, url: str, token: str | None = None, transport=None, batch: int = 50):
        import httpx
        if kind not in ("splunk", "sentinel", "webhook"):
            raise ValueError("kind must be splunk, sentinel or webhook")
        self.kind, self.url, self.token, self.batch = kind, url, token, batch
        self.client = httpx.Client(transport=transport, timeout=10)
        self.q: queue.Queue = queue.Queue(maxsize=10000)
        self.sent, self.failed = 0, 0
        threading.Thread(target=self._run, daemon=True, name="kavach-siem").start()

    def __call__(self, rec: dict) -> None:
        try:
            self.q.put_nowait(rec)
        except queue.Full:
            self.failed += 1

    @staticmethod
    def event(rec: dict) -> dict:
        b = rec["body"]
        e = {"receipt": rec["id"], "seq": rec["seq"], "hash": rec["hash"], "type": b.get("type"),
             "task_id": b.get("task_id"), "principal": b.get("principal")}
        if b.get("type") == "decision":
            d = b["decision"]
            e.update(tool=d["call"]["tool"], verdict=d["verdict"], reason=d.get("reason"),
                     rules=[g["rule_id"] for g in d.get("gates", []) if g.get("outcome") != "PASS"],
                     p_harm=(d.get("risk") or {}).get("p_harm"), hitl=d.get("hitl_id"))
        else:
            e["detail"] = {k: v for k, v in b.items() if k not in ("type", "decision")}
        return e

    def _payload(self, recs: list[dict]):
        if self.kind == "splunk":
            return "\n".join(__import__("json").dumps({"time": r["ts"], "sourcetype": "kavach:receipt", "source": "kavach",
                                                       "event": self.event(r)}) for r in recs), \
                {"Authorization": f"Splunk {self.token}", "Content-Type": "application/json"}
        if self.kind == "sentinel":
            return __import__("json").dumps([{"TimeGenerated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(r["ts"])),
                                              **self.event(r)} for r in recs]), \
                {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        return None, None

    def _run(self) -> None:
        while True:
            recs = [self.q.get()]
            while len(recs) < self.batch:
                try:
                    recs.append(self.q.get_nowait())
                except queue.Empty:
                    break
            try:
                if self.kind == "webhook":
                    for r in recs:
                        self.client.post(self.url, json=self.event(r),
                                         headers={"Authorization": f"Bearer {self.token}"} if self.token else {})
                else:
                    body, headers = self._payload(recs)
                    self.client.post(self.url, content=body, headers=headers).raise_for_status()
                self.sent += len(recs)
            except Exception:
                self.failed += len(recs)

    def flush(self, timeout: float = 5.0) -> None:
        end = time.time() + timeout
        while not self.q.empty() and time.time() < end:
            time.sleep(0.02)
        time.sleep(0.05)
