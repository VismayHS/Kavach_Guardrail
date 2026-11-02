"""Deterministic hard gates (stage 4). No ML, no LLM.

Each rule returns PASS, REQUIRE_APPROVAL (a floor: the action can never be
auto-allowed) or DENY (final). The rule id travels into the receipt.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import yaml

from .manifest import ToolRegistry, ToolSpec
from .models import Conf, GateResult, Label, TaskContext, ToolCall, Trust
from .provenance import URL, arg_targets, named_targets

# actions aimed at specific records: if the user named records, the action should touch one of them (R16)
TARGETED = {"crm.execute", "payment.release", "payment.propose", "payments.refund", "vendor.update_bank", "sap.post"}
# the argument that picks where an outbound action goes
DESTINATION = {"mail.send": "to", "payments.transfer": "to_account", "payments.refund": "invoice_id",
               "payment.release": "invoice_id"}


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
        if call.tool_def_hash is None and self.cfg.get("require_tool_hash"):
            add("R6", "DENY", "No tool definition hash presented; this deployment requires pinned definitions.")
            return out
        if call.tool in registry.drafts:
            add("R6", "REQUIRE_APPROVAL", f"'{call.tool}' was onboarded from its MCP annotations and hasn't been "
                "approved yet; a human decides this call.")
        else:
            add("R6", "PASS", "Tool is in the approved manifest and its definition hash matches." if call.tool_def_hash
                else "Tool is in the approved manifest (no definition hash presented, so the pin was not checked).")

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

        # R18-R23 the accounts-payable rulebook, enforced on facts read from the records
        st = staged or {}
        self._finance_rules(ctx, call, labels, st, add)

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
            internal = self._all_internal(to)    # every recipient, not just the end of the string
            if pii > self.cfg["limits"]["pii_external_max"] and not internal:
                add("R2", "REQUIRE_APPROVAL", f"{pii} PII values would be sent to external address {to}.",
                    pii=pii, recipient=to)
            else:
                add("R2", "PASS", f"PII leaving: {pii} (limit {self.cfg['limits']['pii_external_max']}), "
                    f"recipient {'internal' if internal else 'external'}.")
            # R17 someone else's personal data, even a single value, going outside the company
            if st.get("third_party_pii") and not internal:
                add("R17", "REQUIRE_APPROVAL", f"The email carries {st['third_party_pii']} personal value(s) that "
                    "belong to someone other than the recipient.", count=st["third_party_pii"])
            # R24 the email is about an invoice the user named, but goes to someone who isn't that invoice's customer
            if st.get("stray_recipients"):
                inv = ", ".join(st.get("effect", {}).get("named_invoices", []))
                add("R24", "REQUIRE_APPROVAL", f"The user named invoice {inv}, but {', '.join(st['stray_recipients'])}"
                    " is not that invoice's customer in the CRM.", recipients=st["stray_recipients"])

        # R15 values the agent made up: they appear nowhere in the request or in any tool output
        if call.tool in ("payments.transfer", "payments.refund"):
            for a in spec.control_args:
                lab, v = labels.get(a), call.args.get(a)
                grounded = lab is not None and (lab.trust == Trust.TRUSTED or lab.sources != ["agent"])
                if not grounded and str(v) not in ctx.user_request:
                    add("R15", "REQUIRE_APPROVAL", f"'{a}' = {v!r} appears nowhere in the request or any tool "
                        "output; the agent made it up.", arg=a)

        # R16 the user named specific records, and this action touches none of them
        if call.tool in TARGETED:
            named = named_targets(ctx.user_request)
            if named and not named & arg_targets(call.args):
                add("R16", "REQUIRE_APPROVAL", f"The user named {', '.join(sorted(named))}, but this action touches "
                    "none of them.", named=sorted(named))

        # R13 data leaving through a URL / R14 lethal trifecta at runtime
        if call.tool == "web.fetch":
            self._url_rule(ctx, call, labels, st, add)
        if spec.sink == "external" and st.get("private_seen") and st.get("untrusted_seen"):
            dest = DESTINATION.get(call.tool)
            lab = labels.get(dest) if dest else None
            if not (lab and lab.trust == Trust.TRUSTED) and not self._internal_destination(call, st):
                add("R14", "REQUIRE_APPROVAL", "This task has read private data and untrusted content, and "
                    f"'{dest}' = {call.args.get(dest)!r} was not given by the user.", arg=dest)

        # R3 change freeze / R4 DDL / R10 bulk (SQL facts come from SQLite's compiler, see sql.py)
        sql_info = st.get("sql") or {}
        if call.tool == "crm.execute":
            sql = str(call.args.get("sql", ""))
            if ctx.env == "prod" and (self.cfg.get("change_freeze") or (staged or {}).get("freeze")):
                add("R3", "DENY", "Change freeze is active: production writes are blocked.")
            if ctx.env == "prod" and sql_info.get("ddl"):
                add("R4", "DENY", "Schema-destructive SQL in production.", sql=sql[:120], ops=sql_info.get("sql_ops"))
            rows = (staged or {}).get("rows_affected", 0)
            if ctx.env == "prod" and rows > self.cfg["limits"]["bulk_rows_approval"]:
                add("R10", "REQUIRE_APPROVAL", f"Statement would change {rows} rows "
                    f"(limit {self.cfg['limits']['bulk_rows_approval']}).", rows=rows)
        if call.tool == "crm.query" and (sql_info.get("writes") or sql_info.get("ddl")):
            add("R7", "DENY", f"crm.query is read-only but the statement would {', '.join(sql_info['sql_ops'])}.",
                ops=sql_info.get("sql_ops"))
        if call.tool.startswith("files.") and spec.effect == "write" and ctx.env == "prod" \
                and (self.cfg.get("change_freeze") or (staged or {}).get("freeze")):
            add("R3", "DENY", "Change freeze is active.")

        # R5 payments (amount given in the call; payment.release is covered by R18 on the invoice record)
        if call.tool in ("payments.transfer", "payments.refund"):
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

    def _finance_rules(self, ctx: TaskContext, call: ToolCall, labels: dict[str, Label], staged: dict, add) -> None:
        """R18-R23: rules from the accounts-payable rulebook (Infosys AgentOS sample tenant, fa_judgment.md).
        Amounts, payees and proposers are read from the records by the consequence engine, not parsed from text."""
        fin, e = self.cfg["finance"], staged.get("effect") or {}
        if call.tool == "payment.release" and "amount" in e:
            inv, amt, cur = e["invoice_id"], e["amount"], e["currency"]
            if e["sanctioned"]:
                add("R21", "DENY", f"{e['vendor_name']} is on the sanctions watch list; payments are blocked.",
                    vendor=e["vendor_id"])
            elif not e["bank_verified"]:
                add("R21", "REQUIRE_APPROVAL", f"{e['vendor_name']}'s bank account has not been independently verified.",
                    vendor=e["vendor_id"])
            if e["proposal_id"] is None:
                add("R19", "REQUIRE_APPROVAL", f"No payment proposal exists for {inv}; releasing it would skip the "
                    "proposer/releaser split.")
            elif e["proposed_by"] == ctx.principal.user_id or e["proposal_task"] == ctx.task_id:
                add("R19", "DENY", f"Separation of duties: {e['proposed_by']} proposed this payment in this task, "
                    "and the proposer may not also release it.", proposed_by=e["proposed_by"])
            if not e["matched"]:
                add("R23", "REQUIRE_APPROVAL", f"{inv} fails the 3-way match: invoice {amt:,.2f}, purchase order "
                    f"{e['po_amount']}, goods receipt {e['gr_amount']}.")
            limit = fin["role_release_limit"].get(ctx.principal.role, 0)
            if amt > limit:
                tier = next(t for t in fin["release_tiers"] if t["max"] is None or amt <= t["max"])
                add("R18", "REQUIRE_APPROVAL", f"Releasing {cur} {amt:,.0f} for {inv} needs {tier['approvers']}; "
                    f"role '{ctx.principal.role}' may release up to {cur} {limit:,.0f}.",
                    amount=amt, approvers=tier["approvers"])
            else:
                add("R18", "PASS", f"{cur} {amt:,.0f} is within role '{ctx.principal.role}'s release limit "
                    f"({cur} {limit:,.0f}).")
        if call.tool == "vendor.update_bank":
            lab = labels.get("iban")
            if lab and lab.trust == Trust.UNTRUSTED:
                add("R20", "DENY", f"The new bank account {call.args.get('iban')!r} came from {', '.join(lab.sources)}; "
                    "bank details are never changed based on an email or document alone.", arg="iban",
                    sources=lab.sources)
            else:
                add("R20", "REQUIRE_APPROVAL", "Bank detail changes need independent verification (a call to the "
                    "vendor's registered number) and AP Manager sign-off.")
        if call.tool == "crm.execute":
            kept = set(e.get("tables_written") or []) & set(fin["retained_tables"])
            if kept and {"delete", "drop"} & set(e.get("sql_ops") or []):
                add("R22", "DENY", f"Records in {', '.join(sorted(kept))} must be kept for "
                    f"{fin['retention_years']} years; deleting them is blocked.", tables=sorted(kept))

    def _internal_host(self, host: str) -> bool:
        return any(host == d or host.endswith("." + d) for d in self.cfg["internal_domains"])

    def _all_internal(self, to: str) -> bool:
        recipients = [r.strip().lower() for r in to.split(",") if r.strip()]
        return bool(recipients) and all(self._internal_host(r.rsplit("@", 1)[-1]) for r in recipients)

    def _internal_destination(self, call: ToolCall, staged: dict) -> bool:
        if call.tool == "mail.send":
            return self._all_internal(str(call.args.get("to", "")))
        if call.tool == "payments.transfer":
            return call.args.get("to_account") in staged.get("payees", {})
        return False

    def _url_rule(self, ctx: TaskContext, call: ToolCall, labels: dict[str, Label], staged: dict, add) -> None:
        """R13: a URL is an outbound channel. Unknown hosts may not receive private values or bulk data."""
        parts = urlparse(str(call.args.get("url", "")))
        host = (parts.hostname or "").lower()
        user_hosts = {(urlparse(u).hostname or "").lower() for u in URL.findall(ctx.user_request)}
        if host in user_hosts or self._internal_host(host):
            return
        lab = labels.get("url")
        private = bool(lab and (lab.pii_entities or lab.conf.rank >= Conf.CONFIDENTIAL.rank))
        payload = len(parts.query) + len(parts.fragment)
        if private or payload > self.cfg["limits"]["url_payload_max"]:
            what = "private values" if private else f"a {payload}-character payload"
            add("R13", "DENY", f"URL to {host!r}, a host the user never named, carries {what}.", host=host)
        elif staged.get("private_seen"):
            add("R13", "REQUIRE_APPROVAL", f"Fetching {host!r}, a host the user never named, after this task "
                "read private data.", host=host)


def floor_of(gates: list[GateResult]) -> str:
    if any(g.outcome == "DENY" for g in gates):
        return "DENY"
    if any(g.outcome == "REQUIRE_APPROVAL" for g in gates):
        return "REQUIRE_APPROVAL"
    return "PASS"
