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

from .environment import INTERNAL_DOMAIN, Environment
from .manifest import ToolSpec
from .models import Effect, Label, Reversibility, TaskContext, ToolCall

WHERE = re.compile(r"\bWHERE\b", re.I)
TABLE = re.compile(r"\b(?:FROM|UPDATE|INTO|TABLE)\s+([A-Za-z_]+)", re.I)


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
        else:  # ingress: mail.read_inbox, web.fetch
            eff = Effect("static", rev, {"ingress": True}, 0.0,
                         "Read-only fetch; output will be labelled UNTRUSTED for the rest of the task.")
        eff.staged_ms = round((time.perf_counter() - t0) * 1000, 2)
        return eff

    # ---------------------------------------------------------------- staging
    def _stage_sql(self, sql: str, prod: float) -> Effect:
        clone = self.env.db_copy()
        before = self.env.table_counts(clone)
        ddl = bool(re.match(r"^\s*(DROP|TRUNCATE|ALTER)", sql, re.I))
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
        tables = sorted({m.group(1).lower() for m in TABLE.finditer(sql)})
        pii_rows = rows_total if "customers" in tables else 0
        deleted = sum(max(0, before[t] - after.get(t, 0)) for t in before)
        raw = (rows_total * 0.02 + pii_rows * 0.01 + (20.0 if ddl else 0.0)) * prod
        no_where = bool(re.match(r"^\s*(UPDATE|DELETE)", sql, re.I)) and not WHERE.search(sql)
        clone.close()
        summary = (f"Sandbox run: {rows_total} rows changed in {', '.join(tables) or '?'}"
                   + (f" (tables dropped: {', '.join(dropped)})" if dropped else "")
                   + (", no WHERE clause" if no_where else "") + "." if err is None else f"SQL error in sandbox: {err}")
        return Effect("sandbox", Reversibility.REVERSIBLE,
                      {"rows_affected": rows_total, "rows_deleted": deleted, "tables": tables, "no_where": no_where,
                       "ddl": ddl, "pii_rows": pii_rows, "error": err, "before": before, "after": after},
                      harm_from(raw), summary, safeguard="snapshot+undo")

    def _stage_select(self, sql: str) -> Effect:
        clone = self.env.db_copy()
        try:
            n = len(clone.execute(sql).fetchmany(10000))
            err = None
        except Exception as e:
            n, err = 0, str(e)
        clone.close()
        pii = n if re.search(r"\bcustomers\b", sql, re.I) else 0
        return Effect("sandbox", Reversibility.IDEMPOTENT, {"rows_returned": n, "pii_rows_read": pii, "error": err},
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
