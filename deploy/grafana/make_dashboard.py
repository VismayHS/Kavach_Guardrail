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


def stat(title, expr, x, y, w=4, h=4, color="#2a78d6", desc="", unit="none", alarm=None):
    steps = [{"color": color, "value": None}] if alarm is None else [{"color": "#6b6b6b", "value": None},
                                                                      {"color": alarm, "value": 1}]
    return {"id": next(NID), "type": "stat", "title": title, "description": desc, "datasource": DS,
            "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "targets": [{"refId": "A", "datasource": DS, "expr": expr, "instant": True, "legendFormat": title}],
            "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "thresholds"},
                                         "thresholds": {"mode": "absolute", "steps": steps}},
                            "overrides": []},
            "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
                        "colorMode": "value", "graphMode": "none", "textMode": "value",
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
P.append(stat("Approvals waiting", "kavach_approvals_pending", 12, y, alarm=STATUS["ESCALATE"]))
P.append(stat("In undo window", "kavach_holds_waiting", 16, y, alarm=STATUS["ALLOW_WITH_SAFEGUARD"],
              desc="Held payments and queued emails that can still be taken back."))
P.append(stat("Agents paused", "kavach_kills_active", 20, y, alarm=STATUS["DENY"], desc="Active kill-switch pauses."))
y += 4
P.append(ts("Decisions per minute, by verdict",
            [('sum by (verdict) (rate(kavach_decisions_total[1m])) * 60', "{{verdict}}")], 0, y,
            unit="none", overrides=verdict_overrides(), desc="Status colours: green allow, yellow allow with a "
            "safeguard, orange to a person, red blocked. Names are in the legend."))
P.append(ts("Decision latency (ms)",
            [("histogram_quantile(0.5, sum by (le) (rate(kavach_check_latency_ms_bucket[5m])))", "p50"),
             ("histogram_quantile(0.95, sum by (le) (rate(kavach_check_latency_ms_bucket[5m])))", "p95"),
             ("histogram_quantile(0.99, sum by (le) (rate(kavach_check_latency_ms_bucket[5m])))", "p99")],
            12, y, unit="ms", desc="Time to decide one tool call (rules, staging, risk; the judge when inline)."))
y += 8
P.append(bars("Rules that fired (deny or approval)", "sort_desc(sum by (rule) (kavach_rule_hits_total))", "{{rule}}", 0, y,
              desc="Which rules are doing the work. R28 = canary tripped (a breach in progress)."))
P.append(table("Decisions by tool and verdict", "sum by (tool, verdict) (kavach_decisions_total)", 12, y))
y += 9
P.append(ts("Approvals waiting and undo windows open",
            [("kavach_approvals_pending", "approvals waiting"), ("kavach_holds_waiting", "in undo window")],
            0, y, w=12))
P.append(stat("Receipts in the chain", "kavach_receipts_total", 12, y, w=12, h=8,
              desc="Hash-chained, signed receipts (verify with GET /api/receipts/verify)."))

dash = {"uid": "kavach-overview", "title": "KAVACH: agent action firewall", "tags": ["kavach", "security"],
        "timezone": "browser", "schemaVersion": 39, "version": 1, "refresh": "5s",
        "time": {"from": "now-30m", "to": "now"}, "editable": True, "graphTooltip": 1,
        "panels": P, "templating": {"list": []}, "annotations": {"list": []},
        "links": [{"title": "KAVACH console", "type": "link", "url": "http://localhost:8000", "targetBlank": True},
                  {"title": "Traces (Jaeger)", "type": "link", "url": "http://localhost:16686", "targetBlank": True}]}
out = sys.argv[1] if len(sys.argv) > 1 else str(__import__("pathlib").Path(__file__).parent / "dashboards" / "kavach.json")
json.dump(dash, open(out, "w"), indent=1)
print(len(P), "panels")
