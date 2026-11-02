"""Deterministic hard gates (stage 4). No ML, no LLM.

Each rule returns PASS, REQUIRE_APPROVAL (a floor: the action can never be
auto-allowed) or DENY (final). The rule id travels into the receipt.
"""
from __future__ import annotations

import fnmatch
import hashlib
import re
from pathlib import Path

import yaml

from .addresses import domain_of, parse_recipients
from .finance import iban_check, name_similarity
from .intent import BREADTH
from .lookalike import Lookalike, registered
from .manifest import ToolRegistry, ToolSpec, arg, argname, model_of
from .models import Conf, GateResult, Label, TaskContext, ToolCall, Trust
from .provenance import URL, arg_targets, named_records, named_targets, web_parts

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
        raw = Path(path).read_bytes()
        self.sha256 = hashlib.sha256(raw).hexdigest()
        self._check_signature(Path(path))
        self.cfg = yaml.safe_load(raw)
        self.version = self.cfg["version"]
        self.rules = self.cfg["rules"]
        self.lookalike = Lookalike(list(self.cfg.get("internal_domains", [])) + list(self.cfg.get("known_domains", [])))
        import os

        from .finance import SanctionsList
        self.sanctions = SanctionsList.load(os.environ.get("KAVACH_SANCTIONS_CSV") or self.cfg.get("sanctions_list"))

    @classmethod
    def from_text(cls, text: str) -> "PolicyEngine":
        """A draft policy from YAML text (for replay): never loaded from disk, so no signature applies."""
        import tempfile
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
            f.write(text)
        import os
        saved = os.environ.pop("KAVACH_POLICY_PUBKEY", None)
        try:
            return cls(f.name)
        finally:
            if saved is not None:
                os.environ["KAVACH_POLICY_PUBKEY"] = saved
            os.unlink(f.name)

    def _check_signature(self, path: Path) -> None:
        """F9: with KAVACH_POLICY_PUBKEY set, a policy loads only with a valid Ed25519 signature (<file>.sig)."""
        import json
        import os
        pub = os.environ.get("KAVACH_POLICY_PUBKEY")
        if not pub:
            self.signed_by = None
            return
        from .signing import key_id, load_public, verify
        sig = path.with_name(path.name + ".sig")
        key = load_public(Path(pub).read_text())
        if not sig.exists():
            raise PermissionError(f"{path} has no signature ({sig.name}); refusing to load an unsigned policy")
        s = json.loads(sig.read_text())
        if s.get("sha256") != self.sha256 or s.get("kid") != key_id(key) or \
                not verify(key, self.sha256.encode(), s.get("sig", "")):
            raise PermissionError(f"{path}: signature does not match the file or the trusted key; refusing to load")
        self.signed_by = s["kid"]

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
                if lab and lab.trust == Trust.UNTRUSTED and spec.effect != "ingress" and lab.delegated \
                        and self._asked_for(ctx, call.tool, spec):
                    add("R1", "REQUIRE_APPROVAL", f"'{a}' = {call.args.get(a)!r} came from "
                        f"{', '.join(lab.sources)}, which the user pointed at and asked to act on. A document can "
                        "still be tampered with, so a person confirms the value before it is used.", arg=a,
                        sources=lab.sources, delegated=True)
                elif lab and lab.trust == Trust.UNTRUSTED and spec.effect != "ingress":
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
            # R37 bulk or encoded data needs no recognisable PII to be a leak (base64, reformatted phone numbers...)
            lim = self.cfg["limits"]
            text = f"{arg(spec, call.args, 'subject', '')} {arg(spec, call.args, 'body', '')}"
            longest = max((len(w) for w in text.split()), default=0)
            if not internal and (len(text) > lim["outbound_chars_max"] or longest >= lim["encoded_token_min"]):
                add("R37", "REQUIRE_APPROVAL", f"This email to {to} carries {len(text):,} characters"
                    + (f", including an unbroken run of {longest:,}" if longest >= lim["encoded_token_min"] else "")
                    + "; a person should see what is leaving.", chars=len(text), longest=longest)

        # R40 nothing was shown, so lineage has nothing to trace: an outside destination must then be the user's
        if m in ("email", "transfer") and st.get("outputs_seen") == 0 \
                and not st.get("destination_given") and not self._internal_destination(call, spec, st):
            dest = argname(spec, DESTINATION[m])
            add("R40", "REQUIRE_APPROVAL", f"No tool output was shown for this task, so where {call.args.get(dest)!r} "
                "came from can't be checked, and the user didn't give it.", arg=dest)

        # R39 bank details or links from untrusted content, passed on by email (inside the company too)
        if m == "email" and st.get("untrusted_details"):
            add("R39", "REQUIRE_APPROVAL", f"The email repeats {', '.join(st['untrusted_details'])} from untrusted "
                "content; payment details and links from outside need a person to check them before staff act on them.",
                values=st["untrusted_details"])

        # R36 one task's characters to outside addresses: a list split into short emails adds up
        if m == "email" and st.get("task_outbound_chars", 0) > self.cfg["limits"]["task_outbound_chars_max"]:
            add("R36", "REQUIRE_APPROVAL", f"This task would have emailed {st['task_outbound_chars']:,} characters to "
                f"outside addresses in total (limit {self.cfg['limits']['task_outbound_chars_max']:,}); data may be "
                "leaving in parts.", chars=st["task_outbound_chars"])

        # R38 instructions in untrusted content can name a destination in a form value matching can't trace
        # ("payouts [at] fin-desk [dot] io"): after untrusted content, an outside destination must come from the user
        if m in ("email", "transfer") and st.get("untrusted_seen") \
                and not st.get("destination_given") and not self._internal_destination(call, spec, st) \
                and not any(g.rule_id == "R1" and g.outcome == "DENY" for g in out):   # R1 already traced it
            dest = argname(spec, DESTINATION[m])
            add("R38", "REQUIRE_APPROVAL", f"This task read untrusted content, and '{dest}' = {call.args.get(dest)!r} "
                "was not given by the user.", arg=dest)

        # R15 values the agent made up: they appear nowhere in the request or in any tool output
        if m in ("transfer", "refund", "ledger_post"):
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
            dest = self.destination_arg(spec)
            lab = labels.get(dest) if dest else None
            if dest is None:        # fail closed: nothing says where this tool sends, so nothing can be checked
                add("R14", "REQUIRE_APPROVAL", "This task has read private data and untrusted content, and "
                    f"{call.tool} sends outside the company without a declared destination argument to check.",
                    arg=None)
            elif dest in call.args and not (lab and lab.trust == Trust.TRUSTED) \
                    and not self._internal_destination(call, spec, st):
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
            # R35 the finance rules trust these records, so changing them with SQL would switch the rules off
            e = st.get("effect") or {}
            guarded = sorted(set(e.get("tables_written") or []) & set(self.cfg["finance"]["protected_tables"]))
            if guarded:
                add("R35", "DENY", f"Raw SQL may not change {', '.join(guarded)}: the finance rules rely on these "
                    "records. Use the finance tools, which go through approval.", tables=guarded)
            if ctx.env == "prod" and st.get("task_rows", 0) > self.cfg["limits"]["task_rows_approval"]:
                add("R36", "REQUIRE_APPROVAL", f"This task would have changed {st['task_rows']} rows in total "
                    f"(limit {self.cfg['limits']['task_rows_approval']}); a big change may be split into small ones.",
                    rows=st["task_rows"])
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
                acct = str(arg(spec, call.args, "to_account", ""))
                if re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9 ]{8,34}", acct.upper()) and not iban_check(acct)[0]:
                    add("R30", "DENY", f"{acct!r} is not a valid IBAN: {iban_check(acct)[1]}.", iban=acct)
                if amt > lim["transfer_hard_max"]:
                    add("R5", "DENY", f"Transfer {amt:,.0f} exceeds hard cap.")
                elif not payee_known or amt > lim["transfer_auto_max"]:
                    add("R5", "REQUIRE_APPROVAL",
                        f"Transfer of {amt:,.0f} to {'unknown' if not payee_known else 'known'} payee needs approval.")

        # R36 one task's totals: repeats of an outbound action, and money across several small payments
        if spec.effect in ("payment", "external_send") and st.get("repeat"):
            add("R36", "REQUIRE_APPROVAL", f"This task already ran the same {call.tool} call; a repeat needs a person.")
        task_money = st.get("task_money") or {}
        if task_money.get("INR", 0) > self.cfg["limits"]["task_money_approval"]:
            add("R36", "REQUIRE_APPROVAL", f"This task would have moved INR {task_money['INR']:,.0f} in total "
                f"(limit {self.cfg['limits']['task_money_approval']:,}).", total=task_money["INR"])
        release_limit = self.cfg["finance"]["role_release_limit"].get(ctx.principal.role, 0)
        if m == "ap_release" and task_money.get("EUR", 0) > release_limit:
            add("R36", "REQUIRE_APPROVAL", f"This task would have released EUR {task_money['EUR']:,.0f} in total; role "
                f"'{ctx.principal.role}' may release up to EUR {release_limit:,.0f}.", total=task_money["EUR"])

        # R9 secrets: not into the agent's context, and not overwritten or deleted either
        if m in ("file_read", "file_write", "file_delete"):
            p = str(arg(spec, call.args, "path", ""))
            if any(s in p.lower() for s in self.cfg["sensitive_paths"]):
                what = "reading it into an agent context" if m == "file_read" else "changing it"
                add("R9", "DENY", f"'{p}' is a credential file; {what} is blocked.")

        # R34 shell commands (E10): read and dry-run in a sandbox by the consequence engine
        if m == "shell":
            self._shell_rule(st.get("effect") or {}, add)

        # R32 raw credentials in the arguments: a key passed through the agent (use {{secret:NAME}} instead)
        from .secret_broker import raw_credentials
        creds = raw_credentials(call.args)
        if creds:
            add("R32", "DENY", f"The arguments carry a raw credential ({', '.join(creds)}). Keys must never pass "
                "through an agent: reference it as {{secret:NAME}} and the secrets broker supplies it at execution.",
                kinds=creds)

        # R28 canary records (last, so a provenance rule stays the stated reason and the canary is extra evidence)
        self._canary_rule(call, spec, add)
        return out

    @staticmethod
    def _asked_for(ctx: TaskContext, tool: str, spec: ToolSpec) -> bool:
        """The user's request asks for this kind of action (its intent verbs), e.g. "pay" for a transfer."""
        from .intent import TOOL_VERBS
        req = ctx.user_request.lower()
        return any(re.search(rf"\b{re.escape(v)}", req) for v in (spec.intent_verbs or TOOL_VERBS.get(tool, [])))

    def _shell_rule(self, e: dict, add) -> None:
        """R34: a shell command is refused for what it reaches, and goes to a person for what it might do."""
        deny = []
        if e.get("decode_and_run"):
            deny.append(f"runs code it downloads or decodes ({', '.join(e['decode_and_run'][:2])})")
        if e.get("privilege"):
            deny.append(f"asks for more privileges ({', '.join(e['privilege'][:2])})")
        if e.get("persistence"):
            deny.append(f"installs something that outlives the task ({', '.join(e['persistence'][:2])})")
        if e.get("secrets") and e.get("network"):
            deny.append("reads secrets and reaches the network in the same command")
        if e.get("outside_writes"):
            deny.append(f"writes or deletes outside the workspace ({', '.join(e['outside_writes'][:2])})")
        ev = {k: e.get(k) for k in ("programs", "network", "hosts", "secrets", "outside_writes", "decode_and_run")}
        if deny:
            add("R34", "DENY", "The command " + "; ".join(deny) + ".", **ev)
            return
        ask, dry = [], e.get("dry_run") or {}
        files = dry.get("files") or {}
        if e.get("network"):
            ask.append(f"reaches the network ({', '.join(e['network'][:2])}"
                       + (f" to {', '.join(e['hosts'][:3])}" if e.get("hosts") else "") + ")")
        if e.get("secrets"):
            ask.append(f"reads secrets ({', '.join(e['secrets'][:2])})")
        n_del = len(files.get("deleted", []))
        if n_del > self.cfg["limits"].get("shell_delete_max", 5):
            ask.append(f"deleted {n_del} files in the dry run")
        if dry.get("timed_out"):
            ask.append("did not finish within the dry run's time limit")
        if dry.get("network_attempted") and not e.get("network"):
            ask.append("tried to reach the network in the dry run, though nothing in the command says so")
        if e.get("parse_error"):
            ask.append(f"could not be read ({e['parse_error']})")
        if e.get("destructive") and not dry:
            ask.append("deletes or rewrites files and was not dry-run")
        if ask:
            add("R34", "REQUIRE_APPROVAL", "The command " + "; ".join(ask) + ".", **ev)
        else:
            add("R34", "PASS", "Read the command: no network, secrets, privileges or writes outside the workspace"
                + (f"; the dry run changed {sum(len(v) for v in files.values())} file(s) in the workspace." if files
                   else "."))

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
        if m == "ap_release" and "amount" in e:
            hit = self.sanctions.screen(e.get("vendor_name", ""))          # F7: the list, not only a database flag
            if hit and not e["sanctioned"]:
                add("R21", "DENY", f"{e['vendor_name']} matches sanctions list entry '{hit['match']}' "
                    f"(similarity {hit['score']}); payments are blocked.", vendor=e["vendor_id"], screening=hit)
            ok, why = iban_check(e.get("iban", ""))
            if not ok:
                add("R30", "DENY", f"The vendor's bank account on record is not a valid IBAN ({why}); fix the vendor "
                    "master before paying.", iban=e.get("iban"))
        if m == "bank_change":
            lab = labels.get(argname(spec, "iban"))
            if lab and lab.trust == Trust.UNTRUSTED:
                add("R20", "DENY", f"The new bank account {arg(spec, call.args, 'iban')!r} came from {', '.join(lab.sources)}; "
                    "bank details are never changed based on an email or document alone.", arg="iban",
                    sources=lab.sources)
            else:
                add("R20", "REQUIRE_APPROVAL", "Bank detail changes need independent verification (a call to the "
                    "vendor's registered number) and AP Manager sign-off.")
            # after R20, so provenance stays the stated reason when both apply
            new = str(arg(spec, call.args, "iban", ""))
            ok, why = iban_check(new)
            if not ok:
                add("R30", "DENY", f"{new!r} is not a valid IBAN: {why}.", iban=new)
            holder = e.get("holder_name")
            if holder and name_similarity(holder, e.get("vendor_name", "")) < 0.85:
                add("R31", "REQUIRE_APPROVAL", f"Confirmation of Payee: the account is registered to {holder!r}, not "
                    f"{e.get('vendor_name')!r}.", holder=holder)
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

    @staticmethod
    def destination_arg(spec: ToolSpec) -> str | None:
        """The argument that says where an outbound action goes: its effect model's, or for a tool KAVACH has no
        model of, the one its manifest maps to the 'to' role (send_money: {"to": "recipient"})."""
        m = model_of(spec)
        if m in DESTINATION:
            return argname(spec, DESTINATION[m])
        return spec.arg_map.get("to")

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
        parts = web_parts(str(arg(spec, call.args, "url", "")))
        host = (parts.hostname or "").lower()
        user_hosts = {(web_parts(u).hostname or "").lower() for u in URL.findall(ctx.user_request)}
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
