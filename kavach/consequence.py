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
import re
import time

from . import changelog
from .addresses import domain_of, parse_recipients
from .environment import INTERNAL_DOMAIN, MAIL_RECALL_S, PAYMENT_HOLD_S, Environment
from .manifest import ToolSpec, arg, model_of
from .models import Effect, Label, Reversibility, TaskContext, ToolCall
from .sql import READ_STATEMENTS, WRITE_STATEMENTS, classify, guard, statement_kind

STAGE_BUDGET_S = 0.25          # a statement that can't be staged in this time is too expensive to run (A8)
TOO_EXPENSIVE = f"too expensive to stage (over {STAGE_BUDGET_S * 1000:.0f} ms)"


def _budget(conn, seconds: float = STAGE_BUDGET_S) -> None:
    deadline = time.perf_counter() + seconds
    conn.set_progress_handler(lambda: 1 if time.perf_counter() > deadline else 0, 2000)


def is_internal(addr: str) -> bool:
    d = domain_of(addr)
    return d == INTERNAL_DOMAIN or d.endswith("." + INTERNAL_DOMAIN)

# Safeguards that run an action through a window the gateway can still cancel: the effect is reversible until it
# closes (Phase 3). The text says what happens to the action.
def wait_text(s: float) -> str:
    return f"{s:.0f} s" if s < 60 else f"{s / 60:.0f} min"


WINDOW_TEXT = {"hold": f"held {wait_text(PAYMENT_HOLD_S)} before it reaches the bank; cancel until then",
               "recall-window": f"queued {wait_text(MAIL_RECALL_S)} before it leaves; recall until then",
               "park": "parked in SAP; nothing is booked until a person posts it"}
INVOICE_REF = re.compile(r"\binvoice\s*(?:no\.?|number)?\s*#?\s*(\d+)\b", re.I)    # "invoice 2339", "invoice #12"


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
        rev = Reversibility.REVERSIBLE if spec.safeguard in WINDOW_TEXT else spec.reversibility
        after = WINDOW_TEXT.get(spec.safeguard)

        m = model_of(spec)                       # dispatch on what the tool does, not on its name (E3)
        A = lambda role, default=None: arg(spec, a, role, default)  # noqa: E731
        if m == "sql_write":
            eff = self._stage_sql(str(A("sql", "")), prod)
        elif m == "sql_read":
            eff = self._stage_select(str(A("sql", "")))
        elif m in ("file_write", "file_delete"):
            eff = self._stage_file(m == "file_delete", str(A("path", "")), A("content"), prod)
        elif m == "email":
            to = parse_recipients(A("to", ""), A("cc", ""), A("bcc", ""))
            ext = [x for x in to if not is_internal(x)]
            pii = sum(labels[k].pii_entities for k in spec.data_args if k in labels)
            conf = max((labels[k].conf.rank for k in spec.data_args if k in labels), default=0)
            raw = len(ext) * 1.0 + pii * 0.5 + (2.0 if conf >= 2 and ext else 0.0)
            named, stray = self._invoice_recipients(ctx.user_request, ext)
            eff = Effect("predicted", rev,
                         {"recipients": len(to), "external_recipients": len(ext), "pii_records": pii,
                          "body_chars": len(str(A("body", ""))), "domains": sorted({x.split("@")[-1] for x in to}),
                          "named_invoices": named, "not_invoice_customer": stray},
                         harm_from(raw),
                         f"1 email to {', '.join(to) or '?'} ({len(ext)} external) carrying {pii} PII values; "
                         + (after or "cannot be recalled once sent") + ".", safeguard=spec.safeguard)
        elif m == "transfer":
            amt = float(A("amount", 0))
            known = A("to_account") in self.env.payees
            raw = amt / 2000.0 + (3.0 if not known else 0.0)
            eff = Effect("predicted", rev, {"amount": amt, "payee_known": known,
                                            "payee": self.env.payees.get(A("to_account"), "UNKNOWN")},
                         harm_from(raw), f"Transfer INR {amt:,.0f} to {A('to_account')} "
                         f"({'known payee' if known else 'UNKNOWN payee'}); "
                         + (after or "settled transfers cannot be reversed") + ".",
                         safeguard=spec.safeguard)
        elif m == "refund":
            amt = float(A("amount", 0))
            eff = Effect("predicted", rev, {"amount": amt, "invoice_id": A("invoice_id")},
                         harm_from(amt / 2000.0), f"Refund INR {amt:,.0f} on invoice {A('invoice_id')}; "
                         "compensable (can be re-invoiced) but not undoable.")
        elif m == "file_read":
            secret = any(s in str(A("path", "")) for s in ("env", "secret", "id_rsa"))
            eff = Effect("static", rev, {"path": A("path"), "secret": secret}, harm_from(10.0 if secret else 0.0),
                         f"Read {A('path')} into the agent context" + (" (CREDENTIALS)" if secret else "") + ".")
        elif m in ("ap_propose", "ap_release"):
            eff = self._stage_payment(m == "ap_propose", str(A("invoice_id", "")), rev, spec.safeguard)
        elif m == "bank_change":
            eff = self._stage_bank_change(str(A("vendor_id", "")), str(A("iban", "")), spec.safeguard)
        elif m == "invoice_read":
            eff = Effect("static", rev, {"invoice_id": A("invoice_id")}, 0.0,
                         f"Read invoice {A('invoice_id')} into the agent context.")
        elif m == "vendor_read":
            eff = Effect("static", rev, {"vendor_id": A("vendor_id")}, 0.0,
                         f"Read vendor {A('vendor_id')}'s record into the agent context.")
        elif m == "ledger_post":
            amt = float(A("amount", 0) or 0)
            eff = Effect("predicted", rev, {"amount": amt, "gl_account": A("gl_account"), "doc_type": A("doc_type")},
                         harm_from(amt / 2000.0), f"Post a {A('doc_type')} document of EUR {amt:,.0f} to GL account "
                         f"{A('gl_account')}; " + (after or "undoing a posted document needs a reversal entry") + ".",
                         safeguard=spec.safeguard)
        elif m == "shell":
            eff = self._stage_shell(str(A("command", "")), prod, spec)
        elif spec.amount_arg:  # money a manifest describes (e.g. a bank's send_money): harm grows with the amount
            try:
                amt = abs(float(a.get(spec.amount_arg, 0) or 0))
            except (TypeError, ValueError):
                amt = 0.0
            dest = next((str(a[k]) for k in spec.control_args if k != spec.amount_arg and k in a), "?")
            eff = Effect("predicted", rev, {"amount": amt, "destination": dest}, harm_from(amt / 2000.0),
                         f"{tool}: {amt:,.2f} to {dest}; " + (after or ("settled payments cannot be reversed"
                         if rev == Reversibility.IRREVERSIBLE else f"{rev.value}")) + ".", safeguard=spec.safeguard)
        elif spec.effect == "ingress":  # mail.read_inbox, web.fetch
            eff = Effect("static", rev, {"ingress": True}, 0.0,
                         "Read-only fetch; output will be labelled UNTRUSTED for the rest of the task.")
        else:  # a tool KAVACH has no model for (e.g. a draft onboarded from its MCP annotations): assume the worst
            outside = spec.sink == "external"
            eff = Effect("predicted", rev, {"unknown_effect": True},
                         harm_from(0.0 if spec.effect == "read" else 6.0 if outside else 3.0),
                         f"No model of what {tool} does; treated as {spec.effect}, {rev.value}"
                         + (", reaching outside the company." if outside else "."))
        eff.staged_ms = round((time.perf_counter() - t0) * 1000, 2)
        return eff

    # ---------------------------------------------------------------- staging
    def _invoice_recipients(self, request: str, recipients: list[str]) -> tuple[list[str], list[str]]:
        """R24 facts: CRM invoices the user named, and the recipients who aren't the customer on any of them.
        Owners' addresses stay out of the effect: the agent may never have read them, so receipts couldn't mask them."""
        ids = sorted({int(i) for i in INVOICE_REF.findall(request)})
        if not ids or not recipients:
            return [], []
        rows = self.env.db.execute("SELECT i.id, lower(c.email) FROM invoices i JOIN customers c ON c.id = "
                                   f"i.customer_id WHERE i.id IN ({','.join('?' * len(ids))})", ids).fetchall()
        owners = {e for _, e in rows}
        return [str(i) for i, _ in rows], [r for r in recipients if rows and r.lower() not in owners]

    def _stage_payment(self, propose: bool, invoice_id: str, rev: Reversibility, safeguard: str | None) -> Effect:
        """Amount, payee, proposal and 3-way match come from the records, never from the call's text."""
        f = self.env.ap_invoice_facts(invoice_id)
        if f is None:
            return Effect("static", rev, {"error": f"no invoice {invoice_id}"}, 0.0, f"No invoice {invoice_id}.")
        amt, po, gr = f["amount"], f["po_amount"], f["gr_amount"]
        tolerance = min(0.02 * amt, 100.0)          # fa_judgment.md: "≤ 2% or ≤ €100, whichever is lower"
        matched = po is not None and gr is not None and abs(amt - po) <= tolerance and abs(amt - gr) <= tolerance
        facts = {**f, "matched": matched}
        if propose:
            return Effect("static", rev, facts, harm_from(amt / 20000.0),
                          f"Propose paying {f['currency']} {amt:,.0f} for {invoice_id} to {f['vendor_name']}.",
                          safeguard=safeguard)
        bank = "verified" if f["bank_verified"] else "NOT verified"
        return Effect("static", rev, facts, harm_from(amt / 2000.0 + (0.0 if f["bank_verified"] else 3.0)),
                      f"Release {f['currency']} {amt:,.0f} for {invoice_id} to {f['vendor_name']} ({f['iban']}, bank "
                      f"{bank}); " + (WINDOW_TEXT.get(safeguard) or "a settled payment cannot be reversed") + ".",
                      safeguard=safeguard)

    def _stage_bank_change(self, vendor_id: str, iban: str, safeguard: str | None) -> Effect:
        with self.env.lock:
            row = self.env.db.execute("SELECT name, iban FROM vendors WHERE id = ?", (vendor_id,)).fetchone()
        if row is None:
            return Effect("static", Reversibility.REVERSIBLE, {"error": f"no vendor {vendor_id}"}, 0.0,
                          f"No vendor {vendor_id}.")
        holder = getattr(self.env, "iban_holders", {}).get(iban.replace(" ", "").upper())
        return Effect("static", Reversibility.REVERSIBLE,
                      {"vendor_id": vendor_id, "vendor_name": row["name"], "old_iban": row["iban"], "new_iban": iban,
                       "holder_name": holder},
                      harm_from(8.0), f"Change {row['name']}'s bank account from {row['iban']} to {iban}; every later "
                      "payment to this vendor goes to the new account.", safeguard=safeguard)

    def _stage_sql(self, sql: str, prod: float) -> Effect:
        clone = self.env.db_copy()
        before = self.env.table_counts(clone)
        sq = classify(clone, sql)
        ddl = sq["ddl"]
        changes: list[dict] = []
        try:
            if not ddl and sq["tables_written"]:      # row-level diff: which rows and columns really change (A5)
                changelog.install(clone, sq["tables_written"])   # before guard(): it refuses to create triggers
            guard(clone)
            if statement_kind(sql) not in WRITE_STATEMENTS:
                raise ValueError(f"{statement_kind(sql).upper() or 'this'} statements are not allowed on this tool")
            _budget(clone)
            cur = clone.execute(sql)
            clone.set_progress_handler(None, 0)
            rows = max(cur.rowcount, 0)
            after = self.env.table_counts(clone)
            changes = changelog.collect(clone) if not ddl and sq["tables_written"] else []
            err = None
        except Exception as e:  # invalid SQL never reaches production
            clone.set_progress_handler(None, 0)
            rows, after = 0, before
            err = TOO_EXPENSIVE if "interrupt" in str(e).lower() else str(e)
        rows_changed, columns_changed = changelog.summarize(changes)
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
                       "rows_changed": rows_changed, "columns_changed": columns_changed,
                       "before": before, "after": after},
                      harm_from(raw), summary, safeguard="snapshot+undo")

    def _stage_select(self, sql: str) -> Effect:
        clone = self.env.db_copy()
        sq = classify(clone, sql)
        clone.execute("PRAGMA query_only = ON")      # a "read" that writes fails here, not in production
        guard(clone)
        try:
            if statement_kind(sql) not in READ_STATEMENTS:
                raise ValueError(f"{statement_kind(sql).upper() or 'this'} statements are not allowed on this tool")
            _budget(clone)
            n = len(clone.execute(sql).fetchmany(10000))
            err = None
        except Exception as e:
            n, err = 0, (TOO_EXPENSIVE if "interrupt" in str(e).lower() else str(e))
        clone.set_progress_handler(None, 0)
        clone.close()
        pii = n if "customers" in sq["tables"] else 0
        return Effect("sandbox", Reversibility.IDEMPOTENT,
                      {"rows_returned": n, "pii_rows_read": pii, "error": err,
                       "writes": sq["writes"], "ddl": sq["ddl"], "sql_ops": sq["ops"]},
                      harm_from(pii * 0.005), f"Read-only query returns {n} rows"
                      + (f" ({pii} customer records enter the agent context)" if pii else "") + ".")

    def _stage_shell(self, command: str, prod: float, spec: ToolSpec) -> Effect:
        """E10: read the command, then (for commands KAVACH runs itself) dry-run it in the sandbox on the workspace
        and measure what it changes. A command the reading already refuses is not run at all, not even dry."""
        from .shell import analyze
        a = analyze(command)
        refused = a["decode_and_run"] or a["privilege"] or a["persistence"] or a["outside_writes"] or \
            (a["secrets"] and a["network"])
        sandbox = getattr(self.env, "shell", None)
        dry = None
        if spec.staging == "sandbox" and sandbox is not None and not refused and sandbox.available():
            dry = sandbox.stage(command, self.env.workspace)
        files = (dry or {}).get("files") or {}
        raw = (len(files.get("deleted", [])) * 1.0 + len(files.get("changed", [])) * 0.3
               + len(files.get("created", [])) * 0.1 + (8.0 if a["network"] else 0) + (10.0 if a["secrets"] else 0)
               + (15.0 if refused else 0) + (2.0 if a["destructive"] and dry is None else 0)) * prod
        contained = dry is not None and not a["network"] and not refused
        what = (f"dry run in the sandbox: exit {dry['exit']}, {len(files.get('created', []))} created, "
                f"{len(files.get('changed', []))} changed, {len(files.get('deleted', []))} deleted"
                + (" (TIMED OUT)" if dry["timed_out"] else "") + (" (tried the network)" if dry["network_attempted"]
                                                                   else "")) if dry else (
            "not dry-run (" + ("refused on reading" if refused else "no sandbox here" if spec.staging == "sandbox"
                              else "the agent runs it itself") + ")")
        reach = ", ".join(x for x in (("network: " + ", ".join(a["network"][:2])) if a["network"] else "",
                                      ("secrets: " + ", ".join(a["secrets"][:2])) if a["secrets"] else "") if x)
        changes = any(files.values())
        return Effect("sandbox" if dry else "static",
                      (Reversibility.REVERSIBLE if changes else Reversibility.IDEMPOTENT) if contained
                      else Reversibility.IRREVERSIBLE,
                      {**a, "command": command[:500], "dry_run": dry}, harm_from(raw),
                      f"Shell: {', '.join(a['programs'][:5]) or '?'}; {what}" + (f"; reaches {reach}" if reach else "")
                      + ("; workspace files snapshotted first." if contained else "."),
                      # nothing changed in the dry run: nothing to snapshot (the real run still applies only its diff)
                      safeguard=spec.safeguard if contained and changes else None)

    def _stage_file(self, delete: bool, path: str, content, prod: float) -> Effect:
        try:
            p = self.env._safe(path)
            inside = True
        except PermissionError:
            p, inside = None, False
        exists = bool(p and p.exists())
        size = p.stat().st_size if exists else 0
        raw = ((size / 200.0) if delete else (size / 400.0 if exists else 0.1)) * prod
        if not inside:
            raw += 15
        return Effect("sandbox", Reversibility.REVERSIBLE if inside else Reversibility.IRREVERSIBLE,
                      {"path": path, "inside_workspace": inside, "exists": exists, "bytes_before": size,
                       "bytes_after": 0 if delete else len(str(content or ""))},
                      harm_from(raw), f"{'Delete' if delete else 'Overwrite' if exists else 'Create'} "
                      f"{path} ({size} bytes before){'' if inside else ' OUTSIDE workspace'}; snapshot taken first.",
                      safeguard="snapshot+undo")
