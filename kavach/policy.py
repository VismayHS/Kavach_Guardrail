"""Deterministic hard gates (stage 4). No ML, no LLM.

Each rule returns PASS, REQUIRE_APPROVAL (a floor: the action can never be
auto-allowed) or DENY (final). The rule id travels into the receipt.
"""
from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from urllib.parse import urlparse

import yaml

from .addresses import domain_of, parse_recipients
from .intent import BREADTH
from .lookalike import Lookalike, registered
from .manifest import ToolRegistry, ToolSpec, arg, argname, model_of
from .models import Conf, GateResult, Label, TaskContext, ToolCall, Trust
from .provenance import URL, arg_targets, named_records, named_targets

RANGE = re.compile(r"\b\d+\s*(?:to|-|–|through|till|until)\s*\d+\b", re.I)
# "invoice 1042", "customer #17", "vendor V002", "invoice INV-3040": the record kind and its id
NAMED_KIND = re.compile(r"\b(invoice|customer|client|vendor)s?\s*(?:no\.?|number)?\s*[#:=]?\s*([A-Z]{1,5}-?\d{2,}|\d+)\b",
                        re.I)
KIND_TABLES = {"invoice": ("invoices", "ap_invoices"), "customer": ("customers",), "client": ("customers",),
               "vendor": ("vendors",)}

# Rules read a tool's effect model (E3), not its name, so any tool declared as "email" or "sql_write" gets them.
# Actions aimed at specific records (R16): if the user named records, the action must touch one of them, and the
# argument role that picks the record (None for SQL, whose numbers are mostly values) must be one the user named
TARGETED = {"sql_write": None, "ap_release": "invoice_id", "ap_propose": "invoice_id", "refund": "invoice_id",
            "bank_change": "vendor_id", "ledger_post": "gl_account"}
# the argument role that picks where an outbound action goes
DESTINATION = {"email": "to", "transfer": "to_account", "refund": "invoice_id", "ap_release": "invoice_id"}


class PolicyEngine:
    def __init__(self, path: str | Path | None = None):
        path = path or Path(__file__).parent / "policies" / "default.yaml"
        self.cfg = yaml.safe_load(Path(path).read_text())
        self.version = self.cfg["version"]
        self.rules = self.cfg["rules"]
        self.lookalike = Lookalike(list(self.cfg.get("internal_domains", [])) + list(self.cfg.get("known_domains", [])))

    def file_conf(self, path: str) -> Conf | None:
        """Sensitivity of a workspace file by name (N2); None = the tool's default."""
        name = Path(str(path)).name.lower()
        for item in self.cfg.get("file_sensitivity", []):
            if fnmatch.fnmatch(name, item["pattern"].lower()):
                return Conf(item["conf"])
        return None

    def release_quorum(self, amount: float) -> dict[str, int]:
        tiers = self.cfg["finance"]["release_tiers"]
        tier = next(t for t in tiers if t["max"] is None or amount <= t["max"])
        return dict(tier.get("quorum") or {})

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

        m = model_of(spec)

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
        self._finance_rules(ctx, call, spec, labels, st, add)

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
            pii = max(pii, st.get("detected_pii") or 0)     # E8: Presidio also counts PII typed from memory
            to = ", ".join(str(arg(spec, call.args, r)) for r in ("to", "cc", "bcc") if arg(spec, call.args, r))
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
            # R25 a recipient whose domain imitates ours or a vendor's, unless the user typed that address
            given = st.get("given") or (lambda _v: False)
            fakes = [(r, self.lookalike.check(domain_of(r))) for r in parse_recipients(to)]
            fakes = [(r, p) for r, p in fakes if p and not given(r)]
            if fakes:
                add("R25", "REQUIRE_APPROVAL", "Lookalike domain: " + "; ".join(f"{r} imitates {p}" for r, p in fakes)
                    + ".", recipients=[r for r, _ in fakes])

        # R15 values the agent made up: they appear nowhere in the request or in any tool output
        if m in ("transfer", "refund"):
            for a in spec.control_args:
                lab, v = labels.get(a), call.args.get(a)
                grounded = lab is not None and (lab.trust == Trust.TRUSTED or lab.sources != ["agent"])
                if not grounded and str(v) not in ctx.user_request:
                    add("R15", "REQUIRE_APPROVAL", f"'{a}' = {v!r} appears nowhere in the request or any tool "
                        "output; the agent made it up.", arg=a)

        # R16 the user named specific records, and this action touches none of them or picks another one
        if m in TARGETED:
            named = named_targets(ctx.user_request)
            key = argname(spec, TARGETED[m]) if TARGETED[m] else None
            pick = arg_targets({key: call.args[key]}) if key in call.args else set()
            other = bool(pick) and not pick & (named_records(ctx.user_request) or named)
            if named and (not named & arg_targets(call.args) or other):
                what = f"picks {', '.join(sorted(pick))}" if other else "touches none of them"
                add("R16", "REQUIRE_APPROVAL", f"The user named {', '.join(sorted(named))}, but this action {what}.",
                    named=sorted(named))
            elif m == "sql_write":
                self._rows_rule(ctx, st.get("effect") or {}, add)
        if m == "sql_write":
            self._columns_rule(ctx, st.get("effect") or {}, add)

        # R13 data leaving through a URL / R14 lethal trifecta at runtime
        if m == "web_fetch":
            self._url_rule(ctx, call, spec, labels, st, add)
        if spec.sink == "external" and st.get("private_seen") and st.get("untrusted_seen"):
            dest = argname(spec, DESTINATION[m]) if m in DESTINATION else None
            lab = labels.get(dest) if dest else None
            if not (lab and lab.trust == Trust.TRUSTED) and not self._internal_destination(call, spec, st):
                add("R14", "REQUIRE_APPROVAL", "This task has read private data and untrusted content, and "
                    f"'{dest}' = {call.args.get(dest)!r} was not given by the user.", arg=dest)

        # R29 a classifier flagged injected instructions in what this task read (C3): state changes go to a human
        # unless every destination/target was typed by the user. A model signal: it escalates, it never blocks.
        if st.get("hostile") and spec.effect in ("write", "payment", "external_send"):
            ctrl = [labels[a] for a in spec.control_args if a in labels]
            if not ctrl or not all(l.trust == Trust.TRUSTED for l in ctrl):
                add("R29", "REQUIRE_APPROVAL", f"A classifier flagged injected instructions in {', '.join(st['hostile'][:3])}"
                    "; this action's target wasn't typed by the user.", sources=st["hostile"][:10])

        # R3 change freeze / R4 DDL / R10 bulk (SQL facts come from SQLite's compiler, see sql.py)
        sql_info = st.get("sql") or {}
        if m == "sql_write":
            sql = str(arg(spec, call.args, "sql", ""))
            if ctx.env == "prod" and (self.cfg.get("change_freeze") or (staged or {}).get("freeze")):
                add("R3", "DENY", "Change freeze is active: production writes are blocked.")
            if ctx.env == "prod" and sql_info.get("ddl"):
                add("R4", "DENY", "Schema-destructive SQL in production.", sql=sql[:120], ops=sql_info.get("sql_ops"))
            rows = (staged or {}).get("rows_affected", 0)
            if ctx.env == "prod" and rows > self.cfg["limits"]["bulk_rows_approval"]:
                add("R10", "REQUIRE_APPROVAL", f"Statement would change {rows} rows "
                    f"(limit {self.cfg['limits']['bulk_rows_approval']}).", rows=rows)
        if m == "sql_read" and (sql_info.get("writes") or sql_info.get("ddl")):
            add("R7", "DENY", f"{call.tool} is read-only but the statement would {', '.join(sql_info['sql_ops'])}.",
                ops=sql_info.get("sql_ops"))
        if m in ("file_write", "file_delete") and spec.effect == "write" and ctx.env == "prod" \
                and (self.cfg.get("change_freeze") or (staged or {}).get("freeze")):
            add("R3", "DENY", "Change freeze is active.")

        # R5 payments (amount given in the call; payment.release is covered by R18 on the invoice record)
        if m in ("transfer", "refund"):
            lim = self.cfg["limits"]
            amt = float(arg(spec, call.args, "amount", 0))
            if m == "refund":
                if amt > lim["refund_hard_max"]:
                    add("R5", "DENY", f"Refund {amt:,.0f} exceeds hard cap {lim['refund_hard_max']:,}.")
                elif amt > lim["refund_auto_max"]:
                    add("R5", "REQUIRE_APPROVAL", f"Refund {amt:,.0f} exceeds auto limit {lim['refund_auto_max']:,}.")
                else:
                    add("R5", "PASS", f"Refund {amt:,.0f} within auto limit.")
            else:
                payee_known = arg(spec, call.args, "to_account") in (staged or {}).get("payees", {})
                if amt > lim["transfer_hard_max"]:
                    add("R5", "DENY", f"Transfer {amt:,.0f} exceeds hard cap.")
                elif not payee_known or amt > lim["transfer_auto_max"]:
                    add("R5", "REQUIRE_APPROVAL",
                        f"Transfer of {amt:,.0f} to {'unknown' if not payee_known else 'known'} payee needs approval.")

        # R9 secrets
        if m == "file_read":
            p = str(arg(spec, call.args, "path", ""))
            if any(s in p for s in self.cfg["sensitive_paths"]):
                add("R9", "DENY", f"'{p}' is a credential file; reading it into an agent context is blocked.")

        # R28 canary records (last, so a provenance rule stays the stated reason and the canary is extra evidence)
        self._canary_rule(call, spec, add)
        return out

    def _finance_rules(self, ctx: TaskContext, call: ToolCall, spec: ToolSpec, labels: dict[str, Label], staged: dict,
                       add) -> None:
        """R18-R23: rules from the accounts-payable rulebook (Infosys AgentOS sample tenant, fa_judgment.md).
        Amounts, payees and proposers are read from the records by the consequence engine, not parsed from text."""
        fin, e = self.cfg["finance"], staged.get("effect") or {}
        m = model_of(spec)
        if m == "ap_release" and "amount" in e:
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
                    amount=amt, approvers=tier["approvers"], quorum=dict(tier.get("quorum") or {}))
            else:
                add("R18", "PASS", f"{cur} {amt:,.0f} is within role '{ctx.principal.role}'s release limit "
                    f"({cur} {limit:,.0f}).")
        if m == "bank_change":
            lab = labels.get(argname(spec, "iban"))
            if lab and lab.trust == Trust.UNTRUSTED:
                add("R20", "DENY", f"The new bank account {arg(spec, call.args, 'iban')!r} came from {', '.join(lab.sources)}; "
                    "bank details are never changed based on an email or document alone.", arg="iban",
                    sources=lab.sources)
            else:
                add("R20", "REQUIRE_APPROVAL", "Bank detail changes need independent verification (a call to the "
                    "vendor's registered number) and AP Manager sign-off.")
        if m == "sql_write":
            kept = set(e.get("tables_written") or []) & set(fin["retained_tables"])
            if kept and {"delete", "drop"} & set(e.get("sql_ops") or []):
                add("R22", "DENY", f"Records in {', '.join(sorted(kept))} must be kept for "
                    f"{fin['retention_years']} years; deleting them is blocked.", tables=sorted(kept))

    def _canary_rule(self, call: ToolCall, spec: ToolSpec, add) -> None:
        values = [str(v).lower() for v in (self.cfg.get("canaries") or {}).get("values", [])]
        if not values:
            return
        blob = " ".join(str(v) for v in call.args.values()).lower()
        hits = [v for v in values if v in blob]
        if not hits:
            return
        outbound = spec.sink == "external" or model_of(spec) == "web_fetch"
        if outbound:
            add("R28", "DENY", f"Canary tripped: {', '.join(hits)} is a planted record no legitimate task needs, and "
                "this action would send it outside the company.", canaries=hits)
        else:
            add("R28", "PASS", f"Canary data moved internally ({', '.join(hits)}); recorded.", canaries=hits)

    def _rows_rule(self, ctx: TaskContext, e: dict, add) -> None:
        """R16 on measured rows (N5): the user named records ("invoice 1042") and asked for nothing broad, so every
        row of THAT kind the sandbox saw the statement update or delete must be one of them. A named customer says
        nothing about which invoice rows may change ("delete the invoices for customer 23" is fine)."""
        req = ctx.user_request
        if not e.get("rows_changed") or BREADTH.search(req) or RANGE.search(req):
            return
        named: dict[str, set[str]] = {}
        for kind, rid in NAMED_KIND.findall(req):
            for table in KIND_TABLES.get(kind.lower(), ()):
                named.setdefault(table, set()).update({rid, rid.rsplit("-", 1)[-1]})
        extra = {t: [i for i in v if str(i) not in named[t]] for t, v in e["rows_changed"].items() if t in named}
        extra = {t: v for t, v in extra.items() if v}
        if extra:
            ids = sorted({i for s in named.values() for i in s})
            what = "; ".join(f"{t} {', '.join(map(str, v[:5]))}{' ...' if len(v) > 5 else ''}" for t, v in extra.items())
            add("R16", "REQUIRE_APPROVAL", f"The user named {', '.join(ids)}, but the statement also changes {what}.",
                named=ids, extra={t: v[:20] for t, v in extra.items()})

    def _columns_rule(self, ctx: TaskContext, e: dict, add) -> None:
        """R26 (N6): a sensitive column changed that the request never asks for."""
        req = ctx.user_request.lower()
        sens = self.cfg.get("sensitive_columns", {})
        hits = [f"{t}.{c}" for t, cols in (e.get("columns_changed") or {}).items() for c in cols
                if c in sens and not any(w in req for w in sens[c])]
        if hits:
            add("R26", "REQUIRE_APPROVAL", f"The statement also changes {', '.join(hits)}, which the request doesn't "
                "ask for.", columns=hits)

    def _internal_host(self, host: str) -> bool:
        return any(host == d or host.endswith("." + d) for d in self.cfg["internal_domains"])

    def _all_internal(self, to: str) -> bool:
        recipients = parse_recipients(to)
        return bool(recipients) and all(self._internal_host(domain_of(r)) for r in recipients)

    def _internal_destination(self, call: ToolCall, spec: ToolSpec, staged: dict) -> bool:
        m = model_of(spec)
        if m == "email":
            return self._all_internal(str(arg(spec, call.args, "to", "")))
        if m == "transfer":
            return arg(spec, call.args, "to_account") in staged.get("payees", {})
        return False

    def _url_rule(self, ctx: TaskContext, call: ToolCall, spec: ToolSpec, labels: dict[str, Label], staged: dict,
                  add) -> None:
        """R13: a URL is an outbound channel. Unknown hosts may not receive private values or bulk data."""
        parts = urlparse(str(arg(spec, call.args, "url", "")))
        host = (parts.hostname or "").lower()
        user_hosts = {(urlparse(u).hostname or "").lower() for u in URL.findall(ctx.user_request)}
        if host in user_hosts or self._internal_host(host):
            return
        imitates = self.lookalike.check(host)
        if imitates:
            add("R25", "REQUIRE_APPROVAL", f"Lookalike domain: {host!r} imitates {imitates}.", host=host)
        lab = labels.get(argname(spec, "url"))
        private = bool(lab and (lab.pii_entities or lab.conf.rank >= Conf.CONFIDENTIAL.rank))
        # everything the URL can carry (N2): query, fragment, path, and labels in front of the registered domain
        name, tld = registered(host)
        sub = host[: -len(f"{name}.{tld}")].rstrip(".") if tld and host.endswith(f"{name}.{tld}") else ""
        payload = len(parts.query) + len(parts.fragment) + len(parts.path.strip("/")) + len(sub)
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
