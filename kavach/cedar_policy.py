"""KAVACH's rules in Cedar (E4): facts from KAVACH's engines, decisions in a standard, analysable policy language.

KAVACH computes the facts (provenance of every argument, what the action does, staged rows, lookalike domains,
canaries...) into a Cedar request context; kavach/policies/cedar/kavach.cedar decides, with two questions per call:
Action::"execute" (forbid = DENY) and Action::"auto_execute" (forbid = a person must approve).

    python -m kavach.policy_verify      # proofs (partial evaluation) and parity with the Python engine

Proofs: Cedar's partial evaluator (cedarpy.is_authorized_partial) decides a request where only the facts a property
is about are fixed and every other fact is *unknown*. A definite Deny then holds for every value of the unknowns.
This is not Cedar's SMT analyzer (the Rust cedar-symcc tool, not reachable from Python); it proves properties of the
Cedar policies, and the parity check ties those policies to what the Python engine decides. Partial evaluation is
an experimental upstream Cedar feature.
"""
from __future__ import annotations

import json
from pathlib import Path

from .addresses import domain_of, parse_recipients
from .manifest import arg, argname, model_of
from .models import Conf, Trust
from .provenance import URL, web_parts

POLICY_FILE = Path(__file__).parent / "policies" / "cedar" / "kavach.cedar"
# (rule, outcome) pairs the Cedar policies decide; the rest stay in Python (they need data Cedar can't see cheaply)
COVERED = {("KILL", "DENY"), ("R6", "DENY"), ("R7", "DENY"), ("R8", "DENY"), ("R1", "DENY"), ("R11", "DENY"),
           ("R3", "DENY"), ("R4", "DENY"), ("R5", "DENY"), ("R9", "DENY"), ("R12", "DENY"), ("R13", "DENY"),
           ("R19", "DENY"), ("R20", "DENY"), ("R21", "DENY"), ("R22", "DENY"), ("R28", "DENY"),
           ("R1", "REQUIRE_APPROVAL"), ("R2", "REQUIRE_APPROVAL"), ("R5", "REQUIRE_APPROVAL"),
           ("R6", "REQUIRE_APPROVAL"), ("R10", "REQUIRE_APPROVAL"), ("R11", "REQUIRE_APPROVAL"),
           ("R14", "REQUIRE_APPROVAL"),
           ("R18", "REQUIRE_APPROVAL"), ("R25", "REQUIRE_APPROVAL")}
BOOL_FACTS = ("killed", "known_tool", "pin_mismatch", "schema_error", "read_tool_writes", "stage_error", "role_allowed",
              "external", "ingress", "untrusted_control", "refused_control", "delegated_control", "state_changing",
              "copied_control", "delegated_copy", "prod", "freeze",
              "writes_data", "sql_write", "ddl", "over_hard_cap", "over_auto_limit", "file_read", "sensitive_path",
              "outside_workspace", "web_fetch", "unknown_host", "url_carries_private", "ap_release", "self_proposed",
              "sanctioned", "bank_change", "iban_untrusted", "deletes_retained", "outbound", "carries_canary",
              "external_send", "all_internal", "draft_tool", "private_seen", "untrusted_seen", "destination_trusted",
              "internal_destination", "lookalike")
INT_FACTS = ("pii_out", "pii_external_max", "rows_changed", "bulk_rows_approval", "amount", "role_release_limit")


class CedarPolicy:
    def __init__(self, path: Path = POLICY_FILE):
        import cedarpy
        self.cedarpy = cedarpy
        self.text = Path(path).read_text()
        parsed = json.loads(cedarpy.policies_to_json_str(self.text))
        self.meta: dict[str, tuple[str, str]] = {}       # policyN -> (rule id, DENY | REQUIRE_APPROVAL)
        for pid, p in (parsed.get("staticPolicies") or {}).items():
            rule = (p.get("annotations") or {}).get("id")
            if rule:
                only_auto = (p.get("action") or {}).get("op") == "=="
                self.meta[pid] = (rule, "REQUIRE_APPROVAL" if only_auto else "DENY")

    def _ask(self, action: str, context: dict):
        req = {"principal": 'User::"agent"', "action": f'Action::"{action}"', "resource": 'Tool::"call"',
               "context": context}
        return self.cedarpy.is_authorized(req, self.text, [])

    def decide(self, facts: dict) -> dict:
        """{'verdict_floor': DENY | REQUIRE_APPROVAL | PASS, 'rules': [(rule, outcome)...]}"""
        ex, auto = self._ask("execute", facts), self._ask("auto_execute", facts)
        deny = {self.meta[p] for p in ex.diagnostics.reasons if p in self.meta}
        floor = {self.meta[p] for p in auto.diagnostics.reasons if p in self.meta and
                 self.meta[p][1] == "REQUIRE_APPROVAL"}
        rules = sorted(deny | floor)
        return {"verdict_floor": "DENY" if not ex.allowed else ("REQUIRE_APPROVAL" if not auto.allowed else "PASS"),
                "rules": rules}

    def prove(self, fixed: dict, action: str = "execute") -> dict:
        """Partial evaluation with only `fixed` known: {'decision', 'proved': definite Deny for all unknowns}."""
        ctx = {k: fixed.get(k, {"__extn": {"fn": "unknown", "arg": k}}) for k in (*BOOL_FACTS, *INT_FACTS)}
        req = {"principal": 'User::"agent"', "action": f'Action::"{action}"', "resource": 'Tool::"call"', "context": ctx}
        r = self.cedarpy.is_authorized_partial(req, self.text, [])
        return {"decision": str(r.decision).split(".")[-1], "proved": str(r.decision).endswith("Deny")}


def facts(gw, task_id: str, call, spec, labels: dict, staged: dict, effect) -> dict:
    """The Cedar request context for one call, computed by KAVACH's engines (same helpers the Python rules use)."""
    task = gw.tasks[task_id]
    ctx, cfg, reg = task.ctx, gw.policy.cfg, gw.registry
    m = model_of(spec)
    e = (effect.magnitude if effect else {}) or {}
    sql = staged.get("sql") or {}
    ctrl = {a: labels[a] for a in (spec.control_args if spec else []) if a in labels}
    external = bool(spec and spec.sink == "external")
    ingress = bool(spec and spec.effect == "ingress")
    state = bool(spec and spec.effect in ("write", "payment", "external_send"))
    untrusted = {a for a, lab in ctrl.items() if lab.trust == Trust.UNTRUSTED}
    # R1: a value read whole from a source the user pointed at, for an action the user asked for, goes to a person
    asked = bool(spec) and gw.policy._asked_for(ctx, call.tool, spec)
    # (a fetch only needs the pointing: a link in a message, channel or file the user named, not inside a web page)
    delegated = {a for a in untrusted if gw.policy.followable(ctrl[a], reg)} if ingress else \
        {a for a in untrusted if ctrl[a].delegated and asked}
    copied = {a for a in untrusted if any(s.startswith("tool:") for s in ctrl[a].sources)}
    lim, fin = cfg["limits"], cfg["finance"]
    amt = float(arg(spec, call.args, "amount", 0) or 0) if m in ("transfer", "refund") else 0.0
    hard = (m == "refund" and amt > lim["refund_hard_max"]) or (m == "transfer" and amt > lim["transfer_hard_max"])
    payee_known = arg(spec, call.args, "to_account") in staged.get("payees", {})
    auto_over = not hard and ((m == "refund" and amt > lim["refund_auto_max"]) or
                              (m == "transfer" and (not payee_known or amt > lim["transfer_auto_max"])))
    host, unknown_host, url_private, look = "", False, False, False
    if m == "web_fetch":
        parts = web_parts(str(arg(spec, call.args, "url", "")))
        host = (parts.hostname or "").lower()
        user_hosts = {(web_parts(u).hostname or "").lower() for u in URL.findall(ctx.user_request)}
        unknown_host = host not in user_hosts and not gw.policy._internal_host(host)
        lab = labels.get(argname(spec, "url"))
        from .lookalike import registered
        name, tld = registered(host)
        sub = host[: -len(f"{name}.{tld}")].rstrip(".") if tld and host.endswith(f"{name}.{tld}") else ""
        payload = len(parts.query) + len(parts.fragment) + len(parts.path.strip("/")) + len(sub)
        url_private = bool(lab and (lab.pii_entities or lab.conf.rank >= Conf.CONFIDENTIAL.rank)) or \
            payload > lim["url_payload_max"]
        look = unknown_host and bool(gw.policy.lookalike.check(host))
    to = ", ".join(str(arg(spec, call.args, r)) for r in ("to", "cc", "bcc") if arg(spec, call.args, r)) \
        if spec else ""
    external_send = external and spec.effect == "external_send"
    if external_send:
        given = staged.get("given") or (lambda _v: False)
        look = look or any(gw.policy.lookalike.check(domain_of(r)) and not given(r) for r in parse_recipients(to))
    dest = gw.policy.destination_arg(spec) if spec else None
    dest_lab = labels.get(dest) if dest else None
    # no new destination in this call (an update that keeps the payee) counts as trusted; no declared one never does
    dest_trusted = dest is not None and (dest not in call.args or bool(dest_lab and dest_lab.trust == Trust.TRUSTED))
    canaries = [str(v).lower() for v in (cfg.get("canaries") or {}).get("values", [])]
    blob = " ".join(str(v) for v in call.args.values()).lower()
    allowed = cfg["roles"].get(ctx.principal.role, [])
    f = {
        "killed": gw.killed(task_id) is not None,
        "known_tool": spec is not None,
        "pin_mismatch": bool(spec) and (not reg.verify_pin(call.tool, call.tool_def_hash) or
                                        (call.tool_def_hash is None and bool(cfg.get("require_tool_hash")))),
        "schema_error": bool(spec) and bool(reg.validate_args(spec, call.args)),
        "read_tool_writes": m == "sql_read" and bool(sql.get("writes") or sql.get("ddl")),
        "stage_error": bool(e.get("error")),
        "role_allowed": "*" in allowed or call.tool in allowed,
        "external": external, "ingress": ingress, "untrusted_control": bool(untrusted),
        "refused_control": bool(untrusted - delegated), "delegated_control": bool(delegated),
        "state_changing": state,
        "copied_control": bool(copied - delegated - (untrusted if external and not ingress else set())),
        "delegated_copy": bool((copied & delegated) - (untrusted if external and not ingress else set())),
        "prod": ctx.env == "prod", "freeze": bool(cfg.get("change_freeze") or staged.get("freeze")),
        "writes_data": m == "sql_write" or (m in ("file_write", "file_delete") and bool(spec) and spec.effect == "write"),
        "sql_write": m == "sql_write", "ddl": bool(sql.get("ddl")),
        "over_hard_cap": hard, "over_auto_limit": auto_over,
        "file_read": m == "file_read",
        "sensitive_path": m == "file_read" and any(s in str(arg(spec, call.args, "path", "")) for s in cfg["sensitive_paths"]),
        "outside_workspace": e.get("inside_workspace") is False,
        "web_fetch": m == "web_fetch", "unknown_host": unknown_host, "url_carries_private": url_private,
        "ap_release": m == "ap_release" and "amount" in e,
        "self_proposed": m == "ap_release" and "amount" in e and e.get("proposal_id") is not None and
                         (e.get("proposed_by") == ctx.principal.user_id or e.get("proposal_task") == ctx.task_id),
        "sanctioned": bool(e.get("sanctioned")) and m == "ap_release",
        "bank_change": m == "bank_change",
        "iban_untrusted": m == "bank_change" and bool(labels.get(argname(spec, "iban"))) and
                          labels[argname(spec, "iban")].trust == Trust.UNTRUSTED,
        "deletes_retained": m == "sql_write" and bool(set(e.get("tables_written") or []) & set(fin["retained_tables"]))
                            and bool({"delete", "drop"} & set(e.get("sql_ops") or [])),
        "outbound": external or m == "web_fetch", "carries_canary": any(v in blob for v in canaries),
        "external_send": external_send, "all_internal": bool(to) and gw.policy._all_internal(to),
        "draft_tool": call.tool in reg.drafts,
        "private_seen": bool(staged.get("private_seen")), "untrusted_seen": bool(staged.get("untrusted_seen")),
        "destination_trusted": dest_trusted,
        "internal_destination": bool(spec) and gw.policy._internal_destination(call, spec, staged),
        "lookalike": look,
        "pii_out": max(sum(l.pii_entities for k, l in labels.items() if spec and k in spec.data_args),
                       staged.get("detected_pii") or 0),
        "pii_external_max": int(lim["pii_external_max"]),
        "rows_changed": int(staged.get("rows_affected", 0) or 0),
        "bulk_rows_approval": int(lim["bulk_rows_approval"]),
        # money in cents: Cedar has integers only, and rounding to whole euros could flip R18 at the limit
        "amount": int(round(float(e.get("amount", 0) or 0) * 100)) if m == "ap_release" else 0,
        "role_release_limit": int(round(float(fin["role_release_limit"].get(ctx.principal.role, 0)) * 100)),
    }
    return f


def python_outcomes(gates) -> list[tuple[str, str]]:
    """The covered (rule, outcome) pairs the Python engine produced, for parity."""
    return sorted({(g.rule_id, g.outcome) for g in gates if (g.rule_id, g.outcome) in COVERED})


def agrees(gates, cedar: dict) -> bool:
    """Parity on the covered rules. The Python engine stops at the first fatal rule (an unknown tool gets only R6)
    while Cedar evaluates every policy, so: same floor; if nothing is denied, the same approval rules; if something
    is, the Python engine's deciding rule is one of Cedar's denials."""
    py = python_outcomes(gates)
    py_deny = [r for r, o in py if o == "DENY"]
    py_floor = "DENY" if py_deny else ("REQUIRE_APPROVAL" if py else "PASS")
    if py_floor != cedar["verdict_floor"]:
        return False
    if py_floor == "DENY":
        first = next(g.rule_id for g in gates if g.outcome == "DENY" and (g.rule_id, "DENY") in COVERED)
        return (first, "DENY") in cedar["rules"]
    return set(py) == set(cedar["rules"])
