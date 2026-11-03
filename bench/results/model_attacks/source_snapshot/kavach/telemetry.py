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
             "kavach.latency_ms": float(d.get("latency_ms") or 0.0), "kavach.authenticated": bool(rec["body"].get("authenticated")),
             "kavach.correlation_id": rec["body"].get("corr") or d["call"].get("call_id", "")}
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


REQUEST_BUCKETS_MS = (5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000)


class Requests:
    """End-to-end latency and errors of the routes an agent calls (/mcp, /api/v1/check), measured around the whole
    request: what the agent waits, not only the decision."""

    def __init__(self):
        self.lock = threading.Lock()
        self.lat: dict[str, list[int]] = {}       # route -> bucket counts (+Inf last)
        self.sum: dict[str, float] = {}
        self.errors: dict[tuple[str, int], int] = {}

    def observe(self, route: str, ms: float, status: int) -> None:
        with self.lock:
            b = self.lat.setdefault(route, [0] * (len(REQUEST_BUCKETS_MS) + 1))
            for i, edge in enumerate(REQUEST_BUCKETS_MS):
                if ms <= edge:
                    b[i] += 1
            b[-1] += 1
            self.sum[route] = self.sum.get(route, 0.0) + ms
            if status >= 500:
                self.errors[(route, status)] = self.errors.get((route, status), 0) + 1

    def lines(self) -> list[str]:
        with self.lock:
            out = ["# HELP kavach_request_latency_ms End-to-end time of an agent's request (route = /mcp or check).",
                   "# TYPE kavach_request_latency_ms histogram"]
            for route, b in sorted(self.lat.items()):
                out += [f'kavach_request_latency_ms_bucket{{route="{route}",le="{e}"}} {b[i]}'
                        for i, e in enumerate(REQUEST_BUCKETS_MS)]
                out += [f'kavach_request_latency_ms_bucket{{route="{route}",le="+Inf"}} {b[-1]}',
                        f'kavach_request_latency_ms_sum{{route="{route}"}} {self.sum[route]:.3f}',
                        f'kavach_request_latency_ms_count{{route="{route}"}} {b[-1]}']
            out += ["# HELP kavach_request_errors_total Requests that ended in a server error (5xx).",
                    "# TYPE kavach_request_errors_total counter"]
            out += [f'kavach_request_errors_total{{route="{r}",code="{c}"}} {n}' for (r, c), n in sorted(self.errors.items())]
        return out


REQUESTS = Requests()
_deps_cache: dict = {"at": 0.0, "lines": []}
_chain_cache: dict = {"n": -1, "at": 0.0, "valid": True}


def dependency_lines(env, every_s: float = 15.0) -> list[str]:
    """Is each dependency reachable: the mail server (SMTP connect), the bank (GET /transfers), the model endpoint
    (configured: a key and an endpoint; no tokens are spent to check). Cached for every_s seconds."""
    now = time.time()
    if now - _deps_cache["at"] < every_s and _deps_cache["lines"]:
        return _deps_cache["lines"]
    import socket
    import urllib.request
    deps = {}
    m = getattr(env, "mailer", None)
    if m is not None:
        try:
            socket.create_connection((m.host, m.port), timeout=0.5).close()
            deps["mail_server"] = 1
        except OSError:
            deps["mail_server"] = 0
    b = getattr(env, "bank", None)
    if b is not None:
        try:
            urllib.request.urlopen(b.url + "/transfers", timeout=1).close()
            deps["bank"] = 1
        except Exception:
            deps["bank"] = 0
    from .qualcomm import QualcommCloudAI
    deps["model_endpoint_configured"] = int(QualcommCloudAI().enabled)
    lines = ["# HELP kavach_dependency_up 1 if the dependency answered (model: configured), else 0.",
             "# TYPE kavach_dependency_up gauge"] + [f'kavach_dependency_up{{dep="{k}"}} {v}' for k, v in deps.items()]
    _deps_cache.update(at=now, lines=lines)
    return lines


def metrics_text(gw, sweeper=None, deps: bool = False) -> str:
    """Prometheus exposition format, computed from the receipt chain and the live queues. No label carries an id,
    an address or an argument: tools, verdicts, rules, kinds and outcomes only."""
    # Every known series starts at 0: Prometheus's increase() doesn't count a counter's first appearance, so a first
    # canary trip (R28) or a first failed delivery appearing at 1 would never fire its alert.
    from .gateway import AUTH_RULES, SAFETY_RULES
    verdicts, lat = {}, []
    rules = {(r, o): 0 for r in AUTH_RULES | SAFETY_RULES for o in ("DENY", "REQUIRE_APPROVAL")}
    effects = {(k, o): 0 for k, outs in (("mail", ("sent", "failed", "unknown")),
                                         ("payment", ("settled", "failed", "unknown"))) for o in outs}
    approvals = {o: 0 for o in ("approved", "denied", "expired", "closed", "draft")}
    cancels = {"person": 0, "kill switch": 0}
    early = mismatch = 0
    FINAL = {"human-approved-execution": "approved", "human-approved": "approved", "human-approved-draft": "draft",
             "human-denied": "denied", "approval-expired": "expired", "approval-closed-restart": "closed"}
    for r in gw.receipts.items:
        t = r["body"].get("type")
        if t == "window-closed":
            k = (r["body"].get("kind") or "?", r["body"].get("outcome") or "?")
            effects[k] = effects.get(k, 0) + 1
        elif t in FINAL:
            approvals[FINAL[t]] = approvals.get(FINAL[t], 0) + 1
        elif t == "undo" and r["body"].get("cancelled") and r["body"].get("ok"):
            who = "kill switch" if r["body"].get("by") == "kill switch" else "person"
            cancels[who] = cancels.get(who, 0) + 1
        elif t == "kill" and r["body"].get("cancelled"):        # what the pause itself took back
            cancels["kill switch"] = cancels.get("kill switch", 0) + len(r["body"]["cancelled"])
        elif t == "released-early":
            early += 1
        elif t == "outcome-mismatch":
            mismatch += 1
        if t != "decision":
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
    now = time.time()
    holds = list(getattr(gw.env, "holds", []))
    overdue = [now - h["settles_at"] for h in holds if h["status"] == "held" and h["settles_at"] < now - 15]
    out += ["# HELP kavach_effects_total What happened when an undo window closed: kind (mail, payment) and outcome "
            "(sent, settled, failed, unknown).", "# TYPE kavach_effects_total counter"]
    out += [f'kavach_effects_total{{kind="{k}",outcome="{o}"}} {n}' for (k, o), n in sorted(effects.items())]
    out += ["# HELP kavach_cancellations_total Waiting actions cancelled before they went out, by whom.",
            "# TYPE kavach_cancellations_total counter"]
    out += [f'kavach_cancellations_total{{by="{w}"}} {n}' for w, n in sorted(cancels.items())]
    out += ["# HELP kavach_released_early_total Waiting actions a person let out before their window ended.",
            "# TYPE kavach_released_early_total counter", f"kavach_released_early_total {early}",
            "# HELP kavach_outcome_mismatch_total Cancelled at execution: the action no longer matched its check.",
            "# TYPE kavach_outcome_mismatch_total counter", f"kavach_outcome_mismatch_total {mismatch}",
            "# HELP kavach_approvals_total Approvals closed, by outcome.", "# TYPE kavach_approvals_total counter"]
    out += [f'kavach_approvals_total{{outcome="{o}"}} {n}' for o, n in sorted(approvals.items())]
    out += ["# HELP kavach_holds_overdue Waiting actions more than 15 s past their time (is the sweeper running?).",
            "# TYPE kavach_holds_overdue gauge", f"kavach_holds_overdue {len(overdue)}",
            "# HELP kavach_holds_dispatching Actions being handed to the mail server or bank right now.",
            "# TYPE kavach_holds_dispatching gauge",
            f"kavach_holds_dispatching {sum(h['status'] == 'dispatching' for h in holds)}"]
    if sweeper is not None:
        out += ["# HELP kavach_sweeper_seconds_since_tick Seconds since the windows sweeper last ran (heartbeat).",
                "# TYPE kavach_sweeper_seconds_since_tick gauge",
                f"kavach_sweeper_seconds_since_tick {now - (sweeper.last_tick or sweeper.started):.1f}",
                "# HELP kavach_sweeper_ticks_total Sweeper runs.", "# TYPE kavach_sweeper_ticks_total counter",
                f"kavach_sweeper_ticks_total {sweeper.ticks}"]
    n = len(gw.receipts.items)
    if n != _chain_cache["n"] or now - _chain_cache["at"] > 60:      # re-verify when the chain grows, or each minute
        _chain_cache.update(n=n, at=now, valid=bool(gw.receipts.verify()["valid"]))
    out += ["# HELP kavach_receipt_chain_valid 1 if the whole receipt chain (and its checkpoint) verifies.",
            "# TYPE kavach_receipt_chain_valid gauge", f"kavach_receipt_chain_valid {int(_chain_cache['valid'])}",
            "# HELP kavach_receipt_write_failures_total Receipts the durable store refused (decisions then fail closed).",
            "# TYPE kavach_receipt_write_failures_total counter",
            f"kavach_receipt_write_failures_total {getattr(gw.receipts, 'write_failures', 0)}"]
    out += REQUESTS.lines()
    from .usage import METER
    out += METER.metrics()
    if deps:
        out += dependency_lines(gw.env)
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
