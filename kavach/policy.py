"""Deterministic hard gates (stage 4). No ML, no LLM.

Each rule returns PASS, REQUIRE_APPROVAL (a floor: the action can never be
auto-allowed) or DENY (final). The rule id travels into the receipt.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from .manifest import ToolRegistry, ToolSpec
from .models import GateResult, Label, TaskContext, ToolCall, Trust

DDL = re.compile(r"^\s*(DROP|TRUNCATE|ALTER)\b", re.I)
WRITE_SQL = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE|DROP|TRUNCATE|ALTER|CREATE)\b", re.I)


class PolicyEngine:
    def __init__(self, path: str | Path | None = None):
        path = path or Path(__file__).parent / "policies" / "default.yaml"
        self.cfg = yaml.safe_load(Path(path).read_text())
        self.version = self.cfg["version"]
        self.rules = self.cfg["rules"]

    def evaluate(self, ctx: TaskContext, call: ToolCall, spec: ToolSpec | None, registry: ToolRegistry,
                 labels: dict[str, Label], staged: dict | None = None) -> list[GateResult]:
        out: list[GateResult] = []
        add = lambda rid, outcome, msg, **ev: out.append(GateResult(rid, outcome, msg, ev))  # noqa: E731

        # R6 fail-closed on unknown tools / rug pulls
        if spec is None:
            add("R6", "DENY", f"Unknown tool '{call.tool}' (not in approved manifest).")
            return out
        if not registry.verify_pin(call.tool, call.tool_def_hash):
            add("R6", "DENY", "Tool definition changed after approval (hash mismatch: possible rug pull).",
                presented=call.tool_def_hash, pinned=registry.pins[call.tool])
            return out
        add("R6", "PASS", "Tool is in the approved manifest and its definition hash matches.")

        # R7 schema
        errs = registry.validate_args(spec, call.args)
        if errs:
            add("R7", "DENY", "Arguments do not match schema: " + "; ".join(errs))
            return out
        add("R7", "PASS", "Arguments match schema.")

        # R8 RBAC
        allowed = self.cfg["roles"].get(ctx.principal.role, [])
        if "*" not in allowed and call.tool not in allowed:
            add("R8", "DENY", f"Role '{ctx.principal.role}' may not use {call.tool}.")
        else:
            add("R8", "PASS", f"Role '{ctx.principal.role}' may use {call.tool}.")

        # R1 untrusted destination for external actions
        if spec.sink == "external" or spec.effect == "ingress":
            for a in spec.control_args:
                lab = labels.get(a)
                if lab and lab.trust == Trust.UNTRUSTED and spec.effect != "ingress":
                    add("R1", "DENY", f"'{a}' = {call.args.get(a)!r} came from untrusted content "
                        f"({', '.join(lab.sources)}), not from the user.", arg=a, sources=lab.sources)
                elif lab and lab.trust == Trust.UNTRUSTED and spec.effect == "ingress":
                    add("R1", "REQUIRE_APPROVAL", f"URL {call.args.get(a)!r} was supplied by untrusted content.",
                        arg=a, sources=lab.sources)

        # R11 verbatim untrusted instructions driving writes
        if spec.effect in ("write", "payment", "external_send"):
            for a in spec.control_args:
                lab = labels.get(a)
                if lab and lab.trust == Trust.UNTRUSTED and any(s.startswith("tool:") for s in lab.sources) \
                        and not any(g.rule_id == "R1" and g.evidence.get("arg") == a for g in out):
                    add("R11", "DENY", f"'{a}' was copied from untrusted content ({', '.join(lab.sources)}).",
                        arg=a, sources=lab.sources)

        # R2 PII leaving the company
        if spec.sink == "external" and spec.effect == "external_send":
            pii = sum(l.pii_entities for k, l in labels.items() if k in spec.data_args)
            to = str(call.args.get("to", ""))
            internal = any(to.lower().endswith("@" + d) for d in self.cfg["internal_domains"])
            if pii > self.cfg["limits"]["pii_external_max"] and not internal:
                add("R2", "REQUIRE_APPROVAL", f"{pii} PII values would be sent to external address {to}.",
                    pii=pii, recipient=to)
            else:
                add("R2", "PASS", f"PII leaving: {pii} (limit {self.cfg['limits']['pii_external_max']}), "
                    f"recipient {'internal' if internal else 'external'}.")

        # R3 change freeze / R4 DDL / R10 bulk
        if call.tool == "crm.execute":
            sql = str(call.args.get("sql", ""))
            if ctx.env == "prod" and (self.cfg.get("change_freeze") or (staged or {}).get("freeze")):
                add("R3", "DENY", "Change freeze is active: production writes are blocked.")
            if ctx.env == "prod" and DDL.match(sql):
                add("R4", "DENY", "Schema-destructive SQL in production.", sql=sql[:120])
            rows = (staged or {}).get("rows_affected", 0)
            if ctx.env == "prod" and rows > self.cfg["limits"]["bulk_rows_approval"]:
                add("R10", "REQUIRE_APPROVAL", f"Statement would change {rows} rows "
                    f"(limit {self.cfg['limits']['bulk_rows_approval']}).", rows=rows)
        if call.tool == "crm.query" and WRITE_SQL.match(str(call.args.get("sql", ""))):
            add("R7", "DENY", "crm.query is read-only but a write statement was supplied.")
        if call.tool.startswith("files.") and spec.effect == "write" and ctx.env == "prod" \
                and (self.cfg.get("change_freeze") or (staged or {}).get("freeze")):
            add("R3", "DENY", "Change freeze is active.")

        # R5 payments
        if spec.effect == "payment":
            lim = self.cfg["limits"]
            amt = float(call.args.get("amount", 0))
            if call.tool == "payments.refund":
                if amt > lim["refund_hard_max"]:
                    add("R5", "DENY", f"Refund {amt:,.0f} exceeds hard cap {lim['refund_hard_max']:,}.")
                elif amt > lim["refund_auto_max"]:
                    add("R5", "REQUIRE_APPROVAL", f"Refund {amt:,.0f} exceeds auto limit {lim['refund_auto_max']:,}.")
                else:
                    add("R5", "PASS", f"Refund {amt:,.0f} within auto limit.")
            else:
                payee_known = call.args.get("to_account") in (staged or {}).get("payees", {})
                if amt > lim["transfer_hard_max"]:
                    add("R5", "DENY", f"Transfer {amt:,.0f} exceeds hard cap.")
                elif not payee_known or amt > lim["transfer_auto_max"]:
                    add("R5", "REQUIRE_APPROVAL",
                        f"Transfer of {amt:,.0f} to {'unknown' if not payee_known else 'known'} payee needs approval.")

        # R9 secrets
        if call.tool == "files.read":
            p = str(call.args.get("path", ""))
            if any(s in p for s in self.cfg["sensitive_paths"]):
                add("R9", "DENY", f"'{p}' is a credential file; reading it into an agent context is blocked.")
        return out


def floor_of(gates: list[GateResult]) -> str:
    if any(g.outcome == "DENY" for g in gates):
        return "DENY"
    if any(g.outcome == "REQUIRE_APPROVAL" for g in gates):
        return "REQUIRE_APPROVAL"
    return "PASS"
