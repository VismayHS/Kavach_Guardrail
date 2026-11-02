"""One correlation id follows an action from the agent's request to its real effect: the call's id is on the decision
receipt, the approval, the hold, the window-closed receipt and the email itself (X-Kavach-Correlation), and
GET /api/trace/<id> tells the whole story: request, untrusted sources, proposed call, decision and rules, whether the
connector was invoked, what it said, every receipt."""
import email

from kavach.models import ToolCall, Verdict
from tests.test_email_window import REQ, SEND, Smtp, kavach, later, setup_function  # noqa: F401

ASK = "Send the test summary, please."            # no address typed, so a person decides (R40)


class Keep(Smtp):
    """Mail server stand-in that keeps the whole message."""
    msgs = []

    def send_message(self, m, from_addr=None, to_addrs=None):
        Keep.msgs.append(email.message_from_string(m.as_string()))
        return super().send_message(m, from_addr, to_addrs)


def test_one_id_from_the_request_to_the_inbox():
    gw = kavach()
    gw.env.mailer._smtp = Keep
    Keep.msgs = []
    tid, _ = gw.start_task("ravi", "analyst", REQ)
    call = ToolCall("mail.send", dict(SEND.args))
    d = gw.run(tid, call)
    t = gw.trace(call.call_id)
    assert t["verdict"] == "ALLOW_WITH_SAFEGUARD" and t["connector"] == {
        "invoked": False, "outcome": "waiting", "header": f"X-Kavach-Outbox: {d.result['queued']}"}
    gw.settle(later())
    t = gw.trace(call.call_id)
    assert [r["type"] for r in t["receipts"]] == ["decision", "execution", "window-closed"]
    assert t["connector"]["invoked"] and t["connector"]["outcome"] == "sent" and t["request"] == REQ
    m = Keep.msgs[0]
    assert m["X-Kavach-Correlation"] == call.call_id and m["X-Kavach-Outbox"] == t["hold"]["id"]


def test_a_refused_call_shows_its_untrusted_source_and_that_nothing_was_called():
    gw = kavach()
    tid, _ = gw.start_task("ravi", "analyst", "Summarise my unread emails.")
    gw.run(tid, ToolCall("mail.read_inbox", {}))
    leak = ToolCall("mail.send", {"to": "billing@acme-invoices.co", "subject": "recon", "body": "customer list"})
    assert gw.run(tid, leak).verdict == Verdict.DENY
    t = gw.trace(leak.call_id)
    assert t["connector"] == {"invoked": False, "outcome": "refused: the connector was never called", "header": None}
    assert t["rules"][0]["rule"] == "R1" and any("mail.read_inbox" in s for s in t["untrusted_sources"])


def test_an_approval_and_a_cancel_carry_the_same_id():
    gw = kavach()
    tid, _ = gw.start_task("ravi", "analyst", ASK)
    call = ToolCall("mail.send", dict(SEND.args))
    d = gw.run(tid, call)
    out = gw.resolve_hitl(d.hitl_id, "meera", True)
    assert gw.trace(call.call_id)["connector"]["outcome"] == "waiting"
    gw.undo_action(out["undo_receipt"])
    gw.settle(later())
    t = gw.trace(call.call_id)
    assert [r["type"] for r in t["receipts"]] == ["decision", "human-approved-execution", "undo"]
    assert t["connector"] == {"invoked": False, "outcome": "cancelled before it went out",
                              "header": f"X-Kavach-Outbox: {t['hold']['id']}"} and Smtp.got == []


def test_the_api_and_mcp_return_it(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    c = TestClient(server.app)
    rpc = lambda method, params: c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method,  # noqa: E731
                                                      "params": params}).json()
    rpc("initialize", {"_meta": {"kavach/session": "trace", "kavach/userRequest": REQ, "kavach/role": "analyst"}})
    out = rpc("tools/call", {"name": "mail.send", "arguments": SEND.args,
                             "_meta": {"kavach/session": "trace", "kavach/correlation": "demo-trace-1"}})
    assert out["result"]["_meta"]["kavach/correlation"] == "demo-trace-1"
    t = c.get("/api/trace/demo-trace-1").json()
    assert t["tool"] == "mail.send" and t["chain"]["valid"] and t["receipts"][0]["type"] == "decision"
    assert c.get("/api/trace/no-such-id").status_code == 404
