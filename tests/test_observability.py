"""What /metrics and /api/usage say: real effects and their outcomes (sent, failed, unknown, cancelled by a person or the
kill switch), approvals by outcome, overdue holds, the sweeper's heartbeat, whether the chain verifies, store write
failures, end-to-end latency of agent requests, and model calls, retries, tokens (as the API reported them) and an
estimated cost from the versioned price table. No label carries an id, an address or an argument."""
import re

from tests.test_email_window import REQ, SEND, Smtp, kavach, later, queue, setup_function  # noqa: F401


def metric(text, name, **labels):
    want = ",".join(f'{k}="{v}"' for k, v in labels.items())
    m = re.search(rf"^{name}{{{re.escape(want)}}} ([\d.]+)$" if labels else rf"^{name} ([\d.]+)$", text, re.M)
    return float(m.group(1)) if m else None


def test_effects_cancellations_and_approvals_are_counted():
    from kavach.telemetry import metrics_text
    gw = kavach()
    queue(gw)
    gw.settle(later())
    d = queue(gw)
    gw.undo_action(d.receipt_id)
    queue(gw)
    gw.kill("global", None, "ops")
    tid, _ = gw.start_task("ravi", "analyst", "Send the test summary, please.")
    text = metrics_text(gw)
    assert metric(text, "kavach_effects_total", kind="mail", outcome="sent") == 1
    assert metric(text, "kavach_cancellations_total", by="person") == 1
    assert metric(text, "kavach_cancellations_total", by="kill switch") == 1
    assert metric(text, "kavach_receipt_chain_valid") == 1 and metric(text, "kavach_holds_overdue") == 0
    Smtp.mode = "down"
    gw2 = kavach()
    queue(gw2)
    gw2.settle(later())
    assert metric(metrics_text(gw2), "kavach_effects_total", kind="mail", outcome="failed") == 1


def test_no_label_carries_an_id_or_an_address():
    from kavach.telemetry import metrics_text
    gw = kavach()
    queue(gw)
    gw.settle(later())
    text = metrics_text(gw)
    labels = " ".join(re.findall(r"\{([^}]*)\}", text))
    assert "@" not in labels and not re.search(r"rcpt-|hold-|task-|call-|hitl-", labels)


def test_the_server_reports_request_latency_heartbeat_dependencies_and_usage():
    from fastapi.testclient import TestClient

    from kavach import server
    c = TestClient(server.app)
    rpc = lambda method, params: c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method,  # noqa: E731
                                                      "params": params}).json()
    rpc("initialize", {"_meta": {"kavach/session": "obs", "kavach/userRequest": REQ, "kavach/role": "analyst"}})
    rpc("tools/call", {"name": "mail.read_inbox", "arguments": {}, "_meta": {"kavach/session": "obs"}})
    text = c.get("/metrics").text
    assert metric(text, "kavach_request_latency_ms_count", route="mcp") >= 2
    assert 'kavach_dependency_up{dep="model_endpoint_configured"}' in text
    u = c.get("/api/usage").json()
    assert u["price_table"] and u["decisions"] >= 1 and "rows" in u


def test_counters_start_at_zero_so_the_first_event_fires_its_alert():
    """increase() ignores a counter's first appearance: a first canary trip or failed delivery published straight
    at 1 never fired KavachCanaryTripped or KavachDeliveryFailedOrUnknown (found in the alert drill)."""
    from kavach.telemetry import metrics_text
    text = metrics_text(kavach())
    for name, labels in [("kavach_rule_hits_total", {"rule": "R28", "outcome": "DENY"}),
                         ("kavach_effects_total", {"kind": "mail", "outcome": "failed"}),
                         ("kavach_effects_total", {"kind": "payment", "outcome": "unknown"}),
                         ("kavach_approvals_total", {"outcome": "expired"}),
                         ("kavach_cancellations_total", {"by": "kill switch"})]:
        assert metric(text, name, **labels) == 0, (name, labels)

