"""Generates deploy/grafana/dashboards/kavach.json (Grafana 11 schema):  python deploy/grafana/make_dashboard.py

Verdict colours are the reserved status palette (green allow, yellow safeguard, orange to a person, red blocked);
every series is also named in its legend, so colour never carries meaning alone."""
import json
import sys

DS = {"type": "prometheus", "uid": "kavach-prom"}
STATUS = {"ALLOW": "#0ca30c", "ALLOW_WITH_SAFEGUARD": "#fab219", "ESCALATE": "#ec835a", "DENY": "#d03b3b"}
NID = iter(range(1, 100))


def verdict_overrides():
    return [{"matcher": {"id": "byName", "options": v},
             "properties": [{"id": "color", "value": {"mode": "fixed", "fixedColor": c}}]} for v, c in STATUS.items()]


def stat(title, expr, x, y, w=4, h=4, color="#2a78d6", desc="", unit="none", alarm=None, steps=None, legend=None,
         names=False):
    steps = steps or ([{"color": color, "value": None}] if alarm is None else [{"color": "#6b6b6b", "value": None},
                                                                               {"color": alarm, "value": 1}])
    return {"id": next(NID), "type": "stat", "title": title, "description": desc, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [{"refId": "A", "datasource": DS, "expr": expr, "instant": True, "legendFormat": legend or title}],
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "thresholds"},
                                         "thresholds": {"mode": "absolute", "steps": steps}},
                            "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "value", "graphMode": "none", "textMode": "value_and_name" if names else "value",
                        "justifyMode": "auto", "orientation": "auto"}}


def ts(title, targets, x, y, w=12, h=8, unit="none", desc="", overrides=None, stack=False):
    return {"id": next(NID), "type": "timeseries", "title": title, "description": desc, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [{"refId": chr(65 + i), "datasource": DS, "expr": e, "legendFormat": lf}
                        for i, (e, lf) in enumerate(targets)],
            "fieldConfig": {"defaults": {"unit": unit, "custom": {
                "lineWidth": 2, "fillOpacity": 0 if not stack else 60, "pointSize": 8, "showPoints": "never",
                "stacking": {"mode": "normal" if stack else "none", "group": "A"}, "drawStyle": "line",
                "axisSoftMin": 0, "gradientMode": "none"},
                "color": {"mode": "palette-classic"}}, "overrides": overrides or []},
            "options": {"tooltip": {"mode": "multi", "sort": "desc"},
                        "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True}}}


def bars(title, expr, legend, x, y, w=12, h=9, desc=""):
    return {"id": next(NID), "type": "bargauge", "title": title, "description": desc, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [{"refId": "A", "datasource": DS, "expr": expr, "legendFormat": legend, "instant": True}],
            "fieldConfig": {"defaults": {"unit": "none", "min": 0, "color": {"mode": "fixed", "fixedColor": "#2a78d6"},
                                         "thresholds": {"mode": "absolute", "steps": [{"color": "#2a78d6", "value": None}]}},
                            "overrides": []},
            "options": {"orientation": "horizontal", "displayMode": "basic", "showUnfilled": True, "valueMode": "text",
                        "namePlacement": "left", "sizing": "auto",
                        "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False}}}


def table(title, expr, x, y, w=12, h=9, desc=""):
    return {"id": next(NID), "type": "table", "title": title, "description": desc, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [{"refId": "A", "datasource": DS, "expr": expr, "instant": True, "format": "table"}],
            "transformations": [{"id": "organize", "options": {"excludeByName": {"Time": True},
                                                                "indexByName": {"tool": 0, "verdict": 1, "Value": 2},
                                                                "renameByName": {"Value": "decisions"}}},
                                {"id": "sortBy", "options": {"sort": [{"field": "decisions", "desc": True}]}}],
            "fieldConfig": {"defaults": {"custom": {"align": "auto"}}, "overrides": []},
            "options": {"showHeader": True, "cellHeight": "sm"}}


P = []
y = 0
P.append(stat("Decisions", "sum(kavach_decisions_total)", 0, y, desc="Every tool call KAVACH decided."))
P.append(stat("Blocked", 'sum(kavach_decisions_total{verdict="DENY"}) or vector(0)', 4, y, color=STATUS["DENY"],
              desc="DENY: a deterministic rule refused the action."))
P.append(stat("Sent to a person", 'sum(kavach_decisions_total{verdict="ESCALATE"}) or vector(0)', 8, y,
              color=STATUS["ESCALATE"], desc="ESCALATE: a human approves or refuses."))
P.append(stat("Approvals waiting", "sum(kavach_approvals_pending)", 12, y, alarm=STATUS["ESCALATE"]))
P.append(stat("In undo window", "sum(kavach_holds_waiting)", 16, y, alarm=STATUS["ALLOW_WITH_SAFEGUARD"],
              desc="Held payments and queued emails that can still be taken back."))
P.append(stat("Agents paused", "sum(kavach_kills_active)", 20, y, alarm=STATUS["DENY"], desc="Active kill-switch pauses."))
y += 4
P.append(ts("Decisions per minute, by verdict",
            [('sum by (verdict) (rate(kavach_decisions_total[1m])) * 60', "{{verdict}}")], 0, y,
            unit="none", overrides=verdict_overrides(), desc="Status colours: green allow, yellow allow with a "
            "safeguard, orange to a person, red blocked. Names are in the legend."))
P.append(ts("Decision latency (ms)",
            [("histogram_quantile(0.5, sum by (le) (rate(kavach_check_latency_ms_bucket[5m])))", "p50"),
             ("histogram_quantile(0.95, sum by (le) (rate(kavach_check_latency_ms_bucket[5m])))", "p95"),
             ("histogram_quantile(0.99, sum by (le) (rate(kavach_check_latency_ms_bucket[5m])))", "p99")],
            12, y, unit="ms", desc="Time to decide one tool call (rules, staging, risk). Escalated calls also include the Qualcomm judge's note (escalations-only): seconds, on calls that already wait for a person; allowed calls never wait for it."))
y += 8
P.append(bars("Rules that fired (deny or approval)", "sort_desc(sum by (rule) (kavach_rule_hits_total) > 0)", "{{rule}}", 0, y,
              desc="Which rules are doing the work. R28 = canary tripped (a breach in progress)."))
P.append(table("Decisions by tool and verdict", "sum by (tool, verdict) (kavach_decisions_total)", 12, y))
y += 9
P.append(ts("Approvals waiting and undo windows open",
            [("sum(kavach_approvals_pending)", "approvals waiting"), ("sum(kavach_holds_waiting)", "in undo window")],
            0, y, w=12))
P.append(stat("Receipts in the chain", "max(kavach_receipts_total)", 12, y, w=12, h=8,
              desc="Hash-chained, signed receipts (verify with GET /api/receipts/verify)."))
y += 8

# ---- what really happened outside KAVACH: the mail server and the bank
GOOD, BAD = [{"color": "#d03b3b", "value": None}, {"color": "#0ca30c", "value": 1}], None
P.append(stat("Delivered", 'sum(kavach_effects_total{outcome=~"sent|settled"}) or vector(0)', 0, y,
              color=STATUS["ALLOW"], desc="Emails the mail server took and payments the bank booked, after their window."))
P.append(stat("Failed or not sure", 'sum(kavach_effects_total{outcome=~"failed|unknown"}) or vector(0)', 4, y,
              alarm=STATUS["DENY"], desc="failed: refused, nothing sent. unknown: the line broke mid-send; never re-sent."))
P.append(stat("Cancelled before it went out", "sum(kavach_cancellations_total) or vector(0)", 8, y,
              desc="By a person (Cancel) or by the kill switch."))
P.append(stat("Sent now (manual override)", "sum(kavach_released_early_total)", 12, y,
              desc="A person let a waiting action out before its window ended."))
P.append(stat("Overdue in a window", "sum(kavach_holds_overdue)", 16, y, alarm=STATUS["ESCALATE"],
              desc="Past their time by more than 15 s and still waiting: is the sweeper running?"))
P.append(stat("Sweeper: seconds since last run", "max(kavach_sweeper_seconds_since_tick)", 20, y, unit="s",
              steps=[{"color": "#0ca30c", "value": None}, {"color": STATUS["ESCALATE"], "value": 10},
                     {"color": STATUS["DENY"], "value": 30}], desc="Heartbeat of the worker that closes windows."))
y += 4
P.append(ts("When windows closed: kind and outcome (per 5 min)",
            [("sum by (kind, outcome) (increase(kavach_effects_total[5m]))", "{{kind}} {{outcome}}"),
             ('sum by (by) (increase(kavach_cancellations_total[5m]))', "cancelled by {{by}}")], 0, y,
            desc="mail sent / payment settled: it really went out. failed / unknown: see the alert text."))
P.append(ts("Approvals closed, by outcome (per 5 min)",
            [("sum by (outcome) (increase(kavach_approvals_total[5m]))", "{{outcome}}")], 12, y,
            desc="approved, denied, expired (nobody answered: no), closed (a restart), draft."))
y += 8

# ---- health
P.append(stat("Receipt chain verifies", "min(kavach_receipt_chain_valid)", 0, y, steps=GOOD,
              desc="1 = every receipt and the signed checkpoint verify. 0 = edited, removed or checkpoint missing."))
P.append(stat("Receipt store failures", "sum(kavach_receipt_write_failures_total) or vector(0)", 4, y,
              alarm=STATUS["DENY"], desc="Receipts the database refused; those decisions failed closed (nothing ran)."))
P.append(stat("Dependencies up", "max by (dep) (kavach_dependency_up)", 8, y, w=8, steps=GOOD, legend="{{dep}}", names=True,
              desc="mail_server (SMTP connect), bank (GET /transfers), model endpoint configured (no tokens spent)."))
P.append(stat("Agent request errors (5xx)", "sum(kavach_request_errors_total) or vector(0)", 16, y, w=4,
              alarm=STATUS["DENY"]))
P.append(stat("KAVACH up", 'sum(up{job="kavach"})', 20, y, w=4, steps=GOOD,
              desc="Instances answering /metrics (the compose one or the host one; the other is expected down)."))
y += 4
P.append(ts("End-to-end time of an agent's request (ms)",
            [(f'histogram_quantile({q}, sum by (le) (rate(kavach_request_latency_ms_bucket{{route="mcp"}}[5m])))', f"p{int(q * 100)}")
             for q in (0.5, 0.95, 0.99)], 0, y, unit="ms",
            desc="/mcp tools/call, from request in to answer out: what the agent waits. Spikes of seconds are escalated calls carrying the live Qualcomm judge's note."))
P.append(ts("Model calls per minute, by component",
            [('sum by (component, outcome) (rate(kavach_model_calls_total[5m])) * 60', "{{component}} {{outcome}}"),
             ("sum by (component) (rate(kavach_model_retries_total[5m])) * 60", "{{component}} retries")], 12, y,
            desc="judge, explainer, planner, agent: each Qualcomm call, and retries (rate limits, 5xx, timeouts)."))
y += 8

# ---- model usage and cost (usage is measured; currency is an estimate)
P.append(ts("Tokens per 5 min, by component (as the API reported them)",
            [("sum by (component, kind) (increase(kavach_model_tokens_total[5m]))", "{{component}} {{kind}}")], 0, y,
            desc="From each reply's usage field. Calls without one are counted apart (Usage unknown)."))
P.append(stat("Estimated model cost", "sum(kavach_model_cost_usd_total) or vector(0)", 12, y, unit="currencyUSD",
              desc="Tokens x the versioned price table (kavach/model_prices.json). Qualcomm publishes no per-token "
                   "price; the 70B row is a reference rate from other hosts, not Qualcomm's."))
P.append(stat("Est. cost per decision", "(sum(kavach_model_cost_usd_total) or vector(0)) / sum(kavach_decisions_total)",
              16, y, unit="currencyUSD", desc="Estimated model cost divided by decisions KAVACH made."))
P.append(stat("Unpriced tokens", "sum(kavach_model_unpriced_tokens_total) or vector(0)", 20, y,
              desc="Tokens of models with no price in the table: their cost is unknown, not zero."))
P.append(stat("Usage unknown (calls)", "sum(kavach_model_usage_unknown_total) or vector(0)", 12, y + 4,
              desc="Successful calls whose reply had no usage field."))
P.append(stat("Model call errors", 'sum(kavach_model_calls_total{outcome="error"}) or vector(0)', 16, y + 4,
              alarm=STATUS["ESCALATE"], desc="The judge and explainer fall back to deterministic text; decisions never loosen."))
P.append(stat("Model calls", "sum(kavach_model_calls_total) or vector(0)", 20, y + 4))

dash = {"uid": "kavach-overview", "title": "KAVACH: agent action firewall", "tags": ["kavach", "security"],
        "timezone": "browser", "schemaVersion": 39, "version": 1, "refresh": "5s",
        "time": {"from": "now-30m", "to": "now"}, "editable": True, "graphTooltip": 1,
        "panels": P, "templating": {"list": []}, "annotations": {"list": []},
        "links": [{"title": "KAVACH console", "type": "link", "url": "http://localhost:8000", "targetBlank": True},
                  {"title": "Traces (Jaeger)", "type": "link", "url": "http://localhost:16686", "targetBlank": True}]}
out = sys.argv[1] if len(sys.argv) > 1 else str(__import__("pathlib").Path(__file__).parent / "dashboards" / "kavach.json")
json.dump(dash, open(out, "w"), indent=1)
print(len(P), "panels")
