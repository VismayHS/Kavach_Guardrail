"""A local sandbox bank for the live demo. KAVACH's payments land here, so the proof of a payment is a separate
service with its own page, the way Mailpit is for email. Test accounts only: no real money, no credentials.

    python -m uvicorn scripts.sandbox_bank:create --factory --port 8030    # page http://127.0.0.1:8030
    KAVACH_BANK_DB=.kavach/bank.db (default)

POST /transfers {id, to_account, amount, currency, memo} books a transfer, once: the id is the caller's idempotency
key (KAVACH sends the hold id), so a retry gets the booked transfer back and is never paid twice.
GET /transfers lists them, newest first. DELETE /transfers empties the bank (scripts/demo_reset.sh).
"""
from __future__ import annotations

import html
import os
import sqlite3
import threading
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

# the two accounts in Demo 2's story, shown even before any money arrives (so "received nothing" is visible)
ACCOUNTS = [("TEST-ACCT-001", "Northwind Supplies, vendor V001: the account on record"),
            ("TEST-ACCT-999", "Unknown: the account the “bank details have changed” email asked for")]


class Transfer(BaseModel):
    id: str
    to_account: str
    amount: float
    currency: str = "INR"
    memo: str = ""


def money(amount: float, currency: str) -> str:
    return f"₹{amount:,.2f}" if currency == "INR" else f"{currency} {amount:,.2f}"


def make_app(path: str) -> FastAPI:
    db = sqlite3.connect(path, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("CREATE TABLE IF NOT EXISTS transfers(id TEXT PRIMARY KEY, to_account TEXT, amount REAL, currency TEXT,"
               " memo TEXT, at REAL)")
    lock = threading.Lock()
    app = FastAPI(title="Sandbox Bank")
    # the live demo page reads it straight from the browser (KAVACH is not in between); local test bank only
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "DELETE"])

    def rows() -> list[dict]:
        with lock:
            return [dict(r) for r in db.execute("SELECT * FROM transfers ORDER BY at DESC")]

    @app.post("/transfers")
    def book(t: Transfer):
        with lock:
            new = db.execute("INSERT OR IGNORE INTO transfers VALUES(?,?,?,?,?,?)",
                             (t.id, t.to_account, t.amount, t.currency, t.memo, time.time())).rowcount
            db.commit()
            row = dict(db.execute("SELECT * FROM transfers WHERE id = ?", (t.id,)).fetchone())
        return JSONResponse({**row, "status": "booked"}, 201) if new else {**row, "status": "booked", "duplicate": True}

    @app.get("/transfers")
    def transfers():
        return rows()

    @app.delete("/transfers")
    def empty():
        with lock:
            db.execute("DELETE FROM transfers")
            db.commit()
        return {"emptied": True}

    @app.delete("/transfers/{tid}")
    def forget(tid: str):                     # tests clean up after themselves on a demo bank
        with lock:
            n = db.execute("DELETE FROM transfers WHERE id = ?", (tid,)).rowcount
            db.commit()
        return {"deleted": n}

    @app.get("/", response_class=HTMLResponse)
    def page():
        ts = rows()
        names = dict(ACCOUNTS)
        accounts = list(names) + sorted({t["to_account"] for t in ts} - set(names))
        cards = []
        for a in accounts:
            mine = [t for t in ts if t["to_account"] == a]
            total = sum(t["amount"] for t in mine)
            cur = mine[0]["currency"] if mine else "INR"
            cards.append(f'<div class="acct{" got" if mine else ""}"><div class="num">{html.escape(a)}</div>'
                         f'<div class="who">{html.escape(names.get(a, "Another account"))}</div>'
                         f'<div class="sum">{money(total, cur)}</div><div class="n">received in {len(mine)} '
                         f'transfer{"" if len(mine) == 1 else "s"}</div></div>')
        body = "".join(f"<tr><td>{time.strftime('%H:%M:%S', time.localtime(t['at']))}</td>"
                       f"<td class='mono'>{html.escape(t['to_account'])}</td><td class='amt'>{money(t['amount'], t['currency'])}</td>"
                       f"<td>{html.escape(t['memo'])}</td><td class='mono ref'>{html.escape(t['id'])}</td></tr>" for t in ts)
        table = (f"<table><thead><tr><th>Time</th><th>To account</th><th>Amount</th><th>For</th><th>Reference</th></tr>"
                 f"</thead><tbody>{body}</tbody></table>" if ts else '<p class="empty">No money has arrived yet.</p>')
        return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport"
content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="2"><title>Sandbox Bank</title><style>
:root{{--ink:#14213d;--muted:#5c6577;--line:#dfe3ea;--bg:#f6f7f9;--card:#fff;--ok:#0f7b45}}
body{{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}}
header{{background:#0b2545;color:#fff;padding:18px 24px}} header b{{font-size:20px;letter-spacing:.02em}}
header span{{display:block;color:#c8d3e6;font-size:14px}} main{{max-width:960px;margin:0 auto;padding:24px 16px}}
h2{{font-size:15px;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:28px 0 12px}}
.accts{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}}
.acct{{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:16px}}
.num{{font:600 17px ui-monospace,Menlo,monospace}} .who{{color:var(--muted);font-size:14px;margin:2px 0 10px}}
.sum{{font-size:28px;font-weight:700;color:var(--muted)}} .got .sum{{color:var(--ok)}} .n{{color:var(--muted);font-size:13px}}
.wrap{{overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:8px}}
table{{border-collapse:collapse;width:100%;min-width:560px}} th,td{{text-align:left;padding:10px 14px;border-top:1px solid var(--line)}}
th{{border-top:0;font-size:13px;color:var(--muted);font-weight:600}} .mono{{font-family:ui-monospace,Menlo,monospace}}
.amt{{font-weight:600}} .ref{{color:var(--muted);font-size:13px}} .empty{{color:var(--muted);margin:0;padding:16px}}
</style></head><body><header><b>Sandbox Bank</b><span>Test accounts only, no real money. This page belongs to
the bank, not to KAVACH: it shows only what actually arrived.</span></header><main><h2>Accounts</h2>
<div class="accts">{"".join(cards)}</div><h2>Incoming transfers</h2><div class="wrap">{table}</div></main></body></html>"""

    return app


def create() -> FastAPI:
    path = os.environ.get("KAVACH_BANK_DB") or ".kavach/bank.db"
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    return make_app(path)
