"""Consequence engine (stage 3): what will this action actually do?

Uses the strongest mechanism each tool supports, and says which one it used:
  sandbox   - run the action on a copy of the state and diff it (SQL, files)
  static    - compute the effect from arguments + manifest (reads, fetches)
  predicted - effect of an external, non-forkable action inferred from arguments
              and provenance (email recipients, PII count, money, payee)
The result is a measured/predicted blast radius and a harm magnitude H in [0,1].
"""
from __future__ import annotations

import math
import time

from .environment import INTERNAL_DOMAIN, Environment
from .manifest import ToolSpec
from .models import Effect, Label, Reversibility, TaskContext, ToolCall
from .sql import classify


def harm_from(raw: float) -> float:
    """Squash a raw severity score into H in [0,1]. Scale chosen so 1 external PII email ~0.26."""
    return round(1 - math.exp(-max(raw, 0.0) / 5.0), 4)


class ConsequenceEngine:
    def __init__(self, env: Environment):
        self.env = env

    def analyze(self, ctx: TaskContext, call: ToolCall, spec: ToolSpec, labels: dict[str, Label]) -> Effect:
        t0 = time.perf_counter()
        prod = 1.5 if ctx.env == "prod" else 1.0
        tool, a = call.tool, call.args
        rev = spec.reversibility

        if tool == "crm.execute":
            eff = self._stage_sql(str(a.get("sql", "")), prod)
        elif tool == "crm.query":
            eff = self._stage_select(str(a.get("sql", "")))
        elif tool in ("files.write", "files.delete"):
            eff = self._stage_file(tool, str(a.get("path", "")), a.get("content"), prod)
        elif tool == "mail.send":
            to = [x.strip() for x in str(a.get("to", "")).split(",") if x.strip()]
            ext = [x for x in to if not x.lower().endswith("@" + INTERNAL_DOMAIN)]
            pii = sum(labels[k].pii_entities for k in spec.data_args if k in labels)
            conf = max((labels[k].conf.rank for k in spec.data_args if k in labels), default=0)
            raw = len(ext) * 1.0 + pii * 0.5 + (2.0 if conf >= 2 and ext else 0.0)
            eff = Effect("predicted", rev,
                         {"recipients": len(to), "external_recipients": len(ext), "pii_records": pii,
                          "body_chars": len(str(a.get("body", ""))), "domains": sorted({x.split("@")[-1] for x in to})},
                         harm_from(raw),
                         f"1 email to {', '.join(to) or '?'} ({len(ext)} external) carrying {pii} PII values; "
                         "cannot be recalled once sent.", safeguard=spec.safeguard)
        elif tool == "payments.transfer":
            amt = float(a.get("amount", 0))
            known = a.get("to_account") in self.env.payees
            raw = amt / 2000.0 + (3.0 if not known else 0.0)
            eff = Effect("predicted", rev, {"amount": amt, "payee_known": known,
                                            "payee": self.env.payees.get(a.get("to_account"), "UNKNOWN")},
                         harm_from(raw), f"Transfer INR {amt:,.0f} to {a.get('to_account')} "
                         f"({'known payee' if known else 'UNKNOWN payee'}); settled transfers cannot be reversed.",
                         safeguard=spec.safeguard)
        elif tool == "payments.refund":
            amt = float(a.get("amount", 0))
            eff = Effect("predicted", rev, {"amount": amt, "invoice_id": a.get("invoice_id")},
                         harm_from(amt / 2000.0), f"Refund INR {amt:,.0f} on invoice {a.get('invoice_id')}; "
                         "compensable (can be re-invoiced) but not undoable.")
        elif tool == "files.read":
            secret = any(s in str(a.get("path", "")) for s in ("env", "secret", "id_rsa"))
            eff = Effect("static", rev, {"path": a.get("path"), "secret": secret}, harm_from(10.0 if secret else 0.0),
                         f"Read {a.get('path')} into the agent context" + (" (CREDENTIALS)" if secret else "") + ".")
        elif tool in ("payment.propose", "payment.release"):
            eff = self._stage_payment(tool, str(a.get("invoice_id", "")), rev, spec.safeguard)
        elif tool == "vendor.update_bank":
            eff = self._stage_bank_change(str(a.get("vendor_id", "")), str(a.get("iban", "")), spec.safeguard)
        elif tool == "invoice.read":
            eff = Effect("static", rev, {"invoice_id": a.get("invoice_id")}, 0.0,
                         f"Read invoice {a.get('invoice_id')} into the agent context.")
        elif tool == "sap.post":
            amt = float(a.get("amount", 0) or 0)
            eff = Effect("predicted", rev, {"amount": amt, "gl_account": a.get("gl_account"), "doc_type": a.get("doc_type")},
                         harm_from(amt / 2000.0), f"Post a {a.get('doc_type')} document of EUR {amt:,.0f} to GL account "
                         f"{a.get('gl_account')}; undoing a posted document needs a reversal entry.")
        else:  # ingress: mail.read_inbox, web.fetch
            eff = Effect("static", rev, {"ingress": True}, 0.0,
                         "Read-only fetch; output will be labelled UNTRUSTED for the rest of the task.")
        eff.staged_ms = round((time.perf_counter() - t0) * 1000, 2)
        return eff

    # ---------------------------------------------------------------- staging
    def _stage_payment(self, tool: str, invoice_id: str, rev: Reversibility, safeguard: str | None) -> Effect:
        """Amount, payee, proposal and 3-way match come from the records, never from the call's text."""
        f = self.env.ap_invoice_facts(invoice_id)
        if f is None:
            return Effect("static", rev, {"error": f"no invoice {invoice_id}"}, 0.0, f"No invoice {invoice_id}.")
        amt, po, gr = f["amount"], f["po_amount"], f["gr_amount"]
        tolerance = min(0.02 * amt, 100.0)          # fa_judgment.md: "≤ 2% or ≤ €100, whichever is lower"
        matched = po is not None and gr is not None and abs(amt - po) <= tolerance and abs(amt - gr) <= tolerance
        facts = {**f, "matched": matched}
        if tool == "payment.propose":
            return Effect("static", rev, facts, harm_from(amt / 20000.0),
                          f"Propose paying {f['currency']} {amt:,.0f} for {invoice_id} to {f['vendor_name']}.",
                          safeguard=safeguard)
        bank = "verified" if f["bank_verified"] else "NOT verified"
        return Effect("static", rev, facts, harm_from(amt / 2000.0 + (0.0 if f["bank_verified"] else 3.0)),
                      f"Release {f['currency']} {amt:,.0f} for {invoice_id} to {f['vendor_name']} ({f['iban']}, bank "
                      f"{bank}); a settled payment cannot be reversed.")

    def _stage_bank_change(self, vendor_id: str, iban: str, safeguard: str | None) -> Effect:
        with self.env.lock:
            row = self.env.db.execute("SELECT name, iban FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if row is None:
            return Effect("static", Reversibility.REVERSIBLE, {"error": f"no vendor {vendor_id}"}, 0.0,
                          f"No vendor {vendor_id}.")
        return Effect("static", Reversibility.REVERSIBLE,
                      {"vendor_id": vendor_id, "vendor_name": row["name"], "old_iban": row["iban"], "new_iban": iban},
                      harm_from(8.0), f"Change {row['name']}'s bank account from {row['iban']} to {iban}; every later "
                      "payment to this vendor goes to the new account.", safeguard=safeguard)

    def _stage_sql(self, sql: str, prod: float) -> Effect:
        clone = self.env.db_copy()
        before = self.env.table_counts(clone)
        sq = classify(clone, sql)
        ddl = sq["ddl"]
        try:
            cur = clone.execute(sql)
            rows = max(cur.rowcount, 0)
            after = self.env.table_counts(clone)
            err = None
        except Exception as e:  # invalid SQL never reaches production
            rows, after, err = 0, before, str(e)
        dropped = [t for t in before if t not in after]
        lost = sum(before[t] for t in dropped)
        rows_total = rows + lost
        tables = sq["tables"]
        pii_rows = rows_total if "customers" in tables else 0
        deleted = sum(max(0, before[t] - after.get(t, 0)) for t in before)
        raw = (rows_total * 0.02 + pii_rows * 0.01 + (20.0 if ddl else 0.0)) * prod
        no_where = sq["no_where"]
        clone.close()
        summary = (f"Sandbox run: {rows_total} rows changed in {', '.join(tables) or '?'}"
                   + (f" (tables dropped: {', '.join(dropped)})" if dropped else "")
                   + (", no WHERE clause" if no_where else "") + "." if err is None else f"SQL error in sandbox: {err}")
        return Effect("sandbox", Reversibility.REVERSIBLE,
                      {"rows_affected": rows_total, "rows_deleted": deleted, "tables": tables, "no_where": no_where,
                       "ddl": ddl, "writes": sq["writes"], "sql_ops": sq["ops"], "tables_written": sq["tables_written"],
                       "pii_rows": pii_rows, "error": err,
                       "before": before, "after": after},
                      harm_from(raw), summary, safeguard="snapshot+undo")

    def _stage_select(self, sql: str) -> Effect:
        clone = self.env.db_copy()
        sq = classify(clone, sql)
        clone.execute("PRAGMA query_only = ON")      # a "read" that writes fails here, not in production
        try:
            n = len(clone.execute(sql).fetchmany(10000))
            err = None
        except Exception as e:
            n, err = 0, str(e)
        clone.close()
        pii = n if "customers" in sq["tables"] else 0
        return Effect("sandbox", Reversibility.IDEMPOTENT,
                      {"rows_returned": n, "pii_rows_read": pii, "error": err,
                       "writes": sq["writes"], "ddl": sq["ddl"], "sql_ops": sq["ops"]},
                      harm_from(pii * 0.005), f"Read-only query returns {n} rows"
                      + (f" ({pii} customer records enter the agent context)" if pii else "") + ".")

    def _stage_file(self, tool: str, path: str, content, prod: float) -> Effect:
        try:
            p = self.env._safe(path)
            inside = True
        except PermissionError:
            p, inside = None, False
        exists = bool(p and p.exists())
        size = p.stat().st_size if exists else 0
        raw = ((size / 200.0) if tool == "files.delete" else (size / 400.0 if exists else 0.1)) * prod
        if not inside:
            raw += 15
        return Effect("sandbox", Reversibility.REVERSIBLE if inside else Reversibility.IRREVERSIBLE,
                      {"path": path, "inside_workspace": inside, "exists": exists, "bytes_before": size,
                       "bytes_after": 0 if tool == "files.delete" else len(str(content or ""))},
                      harm_from(raw), f"{'Delete' if tool == 'files.delete' else 'Overwrite' if exists else 'Create'} "
                      f"{path} ({size} bytes before){'' if inside else ' OUTSIDE workspace'}; snapshot taken first.",
                      safeguard="snapshot+undo")
