"""Part 4: receipts and approvals survive a restart (U9), a cut-short receipt log is detected (U10)."""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.models import ToolCall, Verdict  # noqa: E402
from kavach.receipts import ReceiptLog, TamperedLog  # noqa: E402
from kavach.store import Store  # noqa: E402

KEY = b"state-test-receipt-key-32-bytes-long"


def gateway(path: Path) -> Kavach:
    store = Store(path, anchor=path.with_suffix(".anchor.json"))
    return Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False), store=store, receipt_key=KEY)


def test_a_restart_keeps_receipts_and_pending_approvals(tmp_path):
    db = tmp_path / "kavach.db"
    gw = gateway(db)
    tid, _ = gw.start_task("asha", "support", "Refund 12000 on invoice 1042; the customer was double charged.")
    esc = gw.check(tid, ToolCall("payments.refund", {"invoice_id": 1042, "amount": 12000}))
    ok = gw.check(tid, ToolCall("crm.query", {"sql": "SELECT status FROM invoices WHERE id = 1042"}))
    assert esc.verdict == Verdict.ESCALATE and ok.verdict == Verdict.ALLOW
    before = gw.receipts.verify()

    again = gateway(db)                                   # the server restarts
    assert again.receipts.verify() == before and len(again.receipts.items) == 2
    assert [i["id"] for i in again.hitl.pending()] == [esc.hitl_id]
    out = again.resolve_hitl(esc.hitl_id, "meera", True)  # approving after the restart still runs the call
    assert out["executed"] and again.env.ledger[-1]["amount"] == -12000.0
    assert gateway(db).hitl.pending() == [] and len(gateway(db).receipts.items) == 3


def test_a_tampered_store_stops_startup(tmp_path):
    db = tmp_path / "kavach.db"
    gw = gateway(db)
    tid, _ = gw.start_task("ravi", "analyst", "Read deploy.env")
    gw.check(tid, ToolCall("files.read", {"path": "deploy.env"}))
    con = sqlite3.connect(db)
    row = json.loads(con.execute("SELECT body FROM receipts WHERE seq = 1").fetchone()[0])
    row["body"]["decision"]["verdict"] = "ALLOW"                  # rewrite history
    con.execute("UPDATE receipts SET body = ? WHERE seq = 1", (json.dumps(row),))
    con.commit()
    with pytest.raises(TamperedLog):
        gateway(db)


def test_deleting_the_newest_receipt_is_detected_in_memory():
    log = ReceiptLog(KEY)
    for i in range(3):
        log.append({"n": i})
    assert log.verify()["valid"]
    log.items.pop()                                              # cut the log short
    v = log.verify()
    assert not v["valid"] and "anchor" in v["reason"]


def test_deleting_the_newest_receipt_stops_startup(tmp_path):
    db = tmp_path / "kavach.db"
    gw = gateway(db)
    tid, _ = gw.start_task("asha", "support", "What is the status of invoice 1042?")
    for _ in range(3):
        gw.check(tid, ToolCall("crm.query", {"sql": "SELECT status FROM invoices WHERE id = 1042"}))
    con = sqlite3.connect(db)
    con.execute("DELETE FROM receipts WHERE seq = 3")
    con.commit()
    with pytest.raises(TamperedLog, match="anchor"):
        gateway(db)


def test_a_forged_anchor_is_refused(tmp_path):
    db = tmp_path / "kavach.db"
    gw = gateway(db)
    tid, _ = gw.start_task("asha", "support", "What is the status of invoice 1042?")
    gw.check(tid, ToolCall("crm.query", {"sql": "SELECT status FROM invoices WHERE id = 1042"}))
    anchor = db.with_suffix(".anchor.json")
    a = json.loads(anchor.read_text())
    anchor.write_text(json.dumps({**a, "count": 0, "sig": "0" * 64}))
    with pytest.raises(TamperedLog, match="anchor"):
        gateway(db)


def test_persistent_state_needs_a_real_receipt_key(monkeypatch, tmp_path):
    import kavach.server as server
    monkeypatch.setenv("KAVACH_STATE", str(tmp_path / "kavach.db"))
    monkeypatch.delenv("KAVACH_RECEIPT_KEY", raising=False)
    with pytest.raises(SystemExit, match="KAVACH_RECEIPT_KEY"):
        server.make_gateway()
    monkeypatch.setenv("KAVACH_RECEIPT_KEY", "k" * 40)
    gw, _ = server.make_gateway()
    assert gw.receipts.store is not None
