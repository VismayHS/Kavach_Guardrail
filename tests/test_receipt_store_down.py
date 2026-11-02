"""No record, no action. With a database, a decision's receipt is written before the call runs; if the database
refuses it (disk full, locked, connection gone), the call does not run and the caller is told so. Before this, the
store's error was swallowed like a slow exporter's and the email went out with no durable receipt."""
import pytest

from kavach.models import Verdict
from kavach.receipts import ReceiptWriteError
from kavach.store import Store
from tests.test_email_window import REQ, SEND, Smtp, db, kavach, later, setup_function  # noqa: F401


def broken(gw, monkeypatch):
    def down(rec):
        raise OSError("database is locked")
    monkeypatch.setattr(gw.store, "append_receipt", down)


def test_a_decision_the_store_cannot_record_does_not_run(monkeypatch):
    url = db()
    gw = kavach(url)
    tid, _ = gw.start_task("ravi", "analyst", REQ)
    n = len(gw.receipts.items)
    broken(gw, monkeypatch)
    with pytest.raises(ReceiptWriteError):
        gw.run(tid, SEND)
    gw.settle(later())
    assert Smtp.got == [] and gw.env.holds == [] and len(gw.receipts.items) == n
    assert gw.receipts.write_failures == 1 and "locked" in gw.receipts.degraded
    monkeypatch.undo()                                       # the database is back: the same call now works
    assert gw.run(tid, SEND).verdict == Verdict.ALLOW_WITH_SAFEGUARD
    assert gw.receipts.verify()["valid"] and len(Store(url).load_receipts()) == len(gw.receipts.items)


def test_an_approval_the_store_cannot_record_does_not_run(monkeypatch):
    gw = kavach(db())
    tid, _ = gw.start_task("ravi", "analyst", "Send the test summary, please.")     # no address typed: a person decides
    d = gw.run(tid, SEND)
    assert d.verdict == Verdict.ESCALATE, d.reason
    broken(gw, monkeypatch)
    with pytest.raises(ReceiptWriteError):
        gw.resolve_hitl(d.hitl_id, "meera", True)
    gw.settle(later())
    assert Smtp.got == [] and gw.env.holds == []


def test_an_escalation_the_store_cannot_record_leaves_nothing_to_approve(monkeypatch):
    gw = kavach(db())
    tid, _ = gw.start_task("ravi", "analyst", "Send the test summary, please.")
    broken(gw, monkeypatch)
    with pytest.raises(ReceiptWriteError):
        gw.run(tid, SEND)
    assert gw.hitl.pending() == [] and gw.pending_calls == {}


def test_mcp_tells_the_agent_nothing_ran(monkeypatch):
    from fastapi.testclient import TestClient

    from kavach import server
    c = TestClient(server.app)
    rpc = lambda method, params: c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": method,  # noqa: E731
                                                      "params": params}).json()
    rpc("initialize", {"_meta": {"kavach/session": "store-down", "kavach/userRequest": REQ, "kavach/role": "analyst"}})

    def down(rec):
        raise OSError("disk full")
    monkeypatch.setattr(server.gw.receipts, "durable", [down])
    out = rpc("tools/call", {"name": "mail.send", "arguments": SEND.args, "_meta": {"kavach/session": "store-down"}})
    assert out["result"]["isError"] and out["result"]["_meta"]["kavach/verdict"] == "ERROR"
    assert "did not run" in out["result"]["content"][0]["text"]
    assert c.get("/readyz").status_code == 503
    monkeypatch.setattr(server.gw.receipts, "degraded", None)
