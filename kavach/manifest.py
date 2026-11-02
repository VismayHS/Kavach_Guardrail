"""Tool manifest registry: the typed *effect signature* of every tool.

The agent never decides what a tool is allowed to do; the manifest does. Each
definition is hash-pinned at registration so a server that silently changes a
tool's description or schema after approval (an MCP "rug pull") is refused.
Unknown tools fail closed: treated as irreversible, external, untrusted.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field

from .models import Conf, Reversibility


@dataclass
class ToolSpec:
    name: str
    description: str
    params: dict[str, str]                       # arg -> type ("str" | "int" | "float" | "bool")
    required: list[str]
    effect: str                                  # read | write | external_send | payment | ingress
    sink: str                                    # none | internal | external
    reversibility: Reversibility
    control_args: list[str] = field(default_factory=list)   # args that pick the target/destination
    data_args: list[str] = field(default_factory=list)      # args that carry payload data
    output_trust: str = "derived"                # trust label of the tool's output (ingress => untrusted)
    output_conf: Conf = Conf.INTERNAL
    staging: str = "none"                        # sqlite | fs | sandbox (E10: shell dry run) | none
    safeguard: str | None = None                 # safe transform the gateway applies (hold/recall-window/park:
                                                 # a window it can still cancel; reversibility is the tool's own)
    # What KAVACH knows how to stage and which rules apply (E3): one of EFFECT_MODELS. Any tool can declare one, and
    # arg_map maps the model's argument roles to the tool's own names (a Gmail MCP send_email: {"to": "recipients"}).
    effect_model: str | None = None
    arg_map: dict[str, str] = field(default_factory=dict)
    amount_arg: str | None = None                # for tools KAVACH has no custom model of: the argument that is money
    # Field-level labels: output fields that are free text written by someone else (a transaction's subject, an
    # email body). Only those are untrusted; the rest of each record keeps output_trust. Empty = whole output.
    untrusted_fields: list[str] = field(default_factory=list)
    intent_verbs: list[str] = field(default_factory=list)   # words in a request that ask for this kind of action
    user_args: list[str] = field(default_factory=list)      # arguments only the user may choose (a new password): R41
    # MCP-style hints (readOnlyHint/destructiveHint/openWorldHint) are derived, never trusted from servers
    def mcp_annotations(self) -> dict:
        return {"readOnlyHint": self.effect in ("read", "ingress"),
                "destructiveHint": self.reversibility in (Reversibility.IRREVERSIBLE, Reversibility.COMPENSABLE),
                "openWorldHint": self.sink == "external"}

    def definition_hash(self) -> str:
        blob = json.dumps({"n": self.name, "d": self.description, "p": self.params, "r": self.required},
                          sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


# Effect models (E3): how KAVACH stages a kind of action and which rules read it, with the argument roles each uses.
EFFECT_MODELS = {
    "sql_write": ("sql",), "sql_read": ("sql",),
    "file_write": ("path", "content"), "file_delete": ("path",), "file_read": ("path",),
    "email": ("to", "cc", "bcc", "subject", "body"),
    "message": ("to", "body"),          # a chat message, DM or SMS to people: R39 reads it as it reads email
    "transfer": ("to_account", "amount", "memo"), "refund": ("invoice_id", "amount"),
    "web_fetch": ("url",),
    "ap_propose": ("invoice_id",), "ap_release": ("invoice_id",), "invoice_read": ("invoice_id",),
    "bank_change": ("vendor_id", "iban"),
    "ledger_post": ("doc_type", "amount", "gl_account", "text"),
    "shell": ("command",),
}
# KAVACH's own tools (and anything registered under these names) keep their model without declaring it
LEGACY_MODELS = {"crm.execute": "sql_write", "crm.query": "sql_read", "files.write": "file_write",
                 "files.delete": "file_delete", "files.read": "file_read", "mail.send": "email",
                 "payments.transfer": "transfer", "payments.refund": "refund", "web.fetch": "web_fetch",
                 "payment.propose": "ap_propose", "payment.release": "ap_release", "invoice.read": "invoice_read",
                 "vendor.update_bank": "bank_change", "sap.post": "ledger_post"}


def model_of(spec: ToolSpec | None) -> str | None:
    if spec is None:
        return None
    return spec.effect_model or LEGACY_MODELS.get(spec.name)


def argname(spec: ToolSpec | None, role: str) -> str:
    """The tool's own name for one of its effect model's argument roles."""
    return spec.arg_map.get(role, role) if spec is not None else role


def arg(spec: ToolSpec | None, args: dict, role: str, default=None):
    return args.get(argname(spec, role), default)


def default_manifest() -> dict[str, ToolSpec]:
    R = Reversibility
    specs = [
        ToolSpec("crm.query", "Run a read-only SQL SELECT on the CRM database.", {"sql": "str"}, ["sql"],
                 effect="read", sink="none", reversibility=R.IDEMPOTENT, output_trust="derived",
                 output_conf=Conf.PII, staging="sqlite"),
        ToolSpec("crm.execute", "Run a SQL statement that modifies the CRM database.", {"sql": "str"}, ["sql"],
                 effect="write", sink="internal", reversibility=R.REVERSIBLE, control_args=["sql"],
                 staging="sqlite", safeguard="snapshot+undo"),
        ToolSpec("mail.read_inbox", "Read emails from the shared inbox.", {"unread_only": "bool"}, [],
                 effect="ingress", sink="none", reversibility=R.IDEMPOTENT, output_trust="untrusted",
                 output_conf=Conf.INTERNAL),
        ToolSpec("mail.send", "Send an email.", {"to": "str", "subject": "str", "body": "str"},
                 ["to", "subject", "body"], effect="external_send", sink="external",
                 reversibility=R.IRREVERSIBLE, control_args=["to"], data_args=["subject", "body"],
                 safeguard="recall-window"),
        ToolSpec("files.read", "Read a file from the workspace.", {"path": "str"}, ["path"],
                 effect="read", sink="none", reversibility=R.IDEMPOTENT, output_trust="derived",
                 output_conf=Conf.INTERNAL, staging="fs"),
        ToolSpec("files.write", "Write a file in the workspace.", {"path": "str", "content": "str"},
                 ["path", "content"], effect="write", sink="internal", reversibility=R.REVERSIBLE,
                 control_args=["path"], data_args=["content"], staging="fs", safeguard="snapshot+undo"),
        ToolSpec("files.delete", "Delete a file in the workspace.", {"path": "str"}, ["path"],
                 effect="write", sink="internal", reversibility=R.REVERSIBLE, control_args=["path"],
                 staging="fs", safeguard="move-to-trash"),
        ToolSpec("payments.transfer", "Transfer money to a bank account.",
                 {"to_account": "str", "amount": "float", "memo": "str"}, ["to_account", "amount"],
                 effect="payment", sink="external", reversibility=R.IRREVERSIBLE,
                 control_args=["to_account", "amount"], data_args=["memo"], safeguard="hold"),
        ToolSpec("payments.refund", "Refund an invoice.", {"invoice_id": "int", "amount": "float"},
                 ["invoice_id", "amount"], effect="payment", sink="external", reversibility=R.COMPENSABLE,
                 control_args=["invoice_id", "amount"]),
        ToolSpec("web.fetch", "Fetch a web page.", {"url": "str"}, ["url"], effect="ingress", sink="none",
                 reversibility=R.IDEMPOTENT, control_args=["url"], output_trust="untrusted",
                 output_conf=Conf.PUBLIC),
        # accounts payable (the amount and payee of a payment come from the records, not from the call)
        ToolSpec("invoice.read", "Read an accounts-payable invoice.", {"invoice_id": "str"}, ["invoice_id"],
                 effect="read", sink="none", reversibility=R.IDEMPOTENT, output_trust="derived",
                 output_conf=Conf.CONFIDENTIAL, staging="sqlite"),
        ToolSpec("payment.propose", "Propose payment of an approved invoice.", {"invoice_id": "str"}, ["invoice_id"],
                 effect="write", sink="internal", reversibility=R.REVERSIBLE, control_args=["invoice_id"],
                 staging="sqlite", safeguard="snapshot+undo"),
        ToolSpec("payment.release", "Release the proposed payment for an invoice to the vendor's bank account.",
                 {"invoice_id": "str"}, ["invoice_id"], effect="payment", sink="external",
                 reversibility=R.IRREVERSIBLE, control_args=["invoice_id"], safeguard="hold"),
        ToolSpec("vendor.update_bank", "Change a vendor's bank account (IBAN).", {"vendor_id": "str", "iban": "str"},
                 ["vendor_id", "iban"], effect="write", sink="internal", reversibility=R.REVERSIBLE,
                 control_args=["vendor_id", "iban"], staging="sqlite", safeguard="snapshot+undo"),
        ToolSpec("sap.post", "Post an accounting document to SAP.",
                 {"doc_type": "str", "amount": "float", "gl_account": "str", "text": "str"},
                 ["doc_type", "amount", "gl_account"], effect="write", sink="internal",
                 reversibility=R.COMPENSABLE, control_args=["gl_account", "amount"], data_args=["text"],
                 safeguard="park"),
    ]
    return {s.name: s for s in specs}


def spec_to_dict(s: ToolSpec) -> dict:
    """A ToolSpec as plain YAML-able data (the format of kavach/manifests/*.yaml)."""
    d = {"description": s.description, "params": dict(s.params), "required": list(s.required), "effect": s.effect,
         "sink": s.sink, "reversibility": s.reversibility.value, "control_args": list(s.control_args),
         "data_args": list(s.data_args), "output_trust": s.output_trust, "output_conf": s.output_conf.value,
         "staging": s.staging, "safeguard": s.safeguard, "effect_model": s.effect_model or LEGACY_MODELS.get(s.name),
         "arg_map": dict(s.arg_map), "amount_arg": s.amount_arg, "intent_verbs": list(s.intent_verbs),
         "untrusted_fields": list(s.untrusted_fields), "user_args": list(s.user_args)}
    return {k: v for k, v in d.items() if v not in (None, [], {})}


def spec_from_dict(name: str, d: dict) -> ToolSpec:
    known = {"description", "params", "required", "effect", "sink", "reversibility", "control_args", "data_args",
             "output_trust", "output_conf", "staging", "safeguard", "effect_model", "arg_map", "amount_arg",
             "intent_verbs", "untrusted_fields", "user_args"}
    unknown = set(d) - known
    if unknown:
        raise ValueError(f"tool {name!r}: unknown manifest keys {sorted(unknown)}")
    model = d.get("effect_model")
    if model and model not in EFFECT_MODELS:
        raise ValueError(f"tool {name!r}: effect_model must be one of {sorted(EFFECT_MODELS)}")
    return ToolSpec(name, d.get("description", ""), dict(d.get("params") or {}), list(d.get("required") or []),
                    effect=d.get("effect", "write"), sink=d.get("sink", "external"),
                    reversibility=Reversibility(d.get("reversibility", "irreversible")),
                    control_args=list(d.get("control_args") or []), data_args=list(d.get("data_args") or []),
                    output_trust=d.get("output_trust", "derived"), output_conf=Conf(d.get("output_conf", "internal")),
                    staging=d.get("staging", "none"), safeguard=d.get("safeguard"), effect_model=model,
                    arg_map=dict(d.get("arg_map") or {}), amount_arg=d.get("amount_arg"),
                    intent_verbs=list(d.get("intent_verbs") or []), untrusted_fields=list(d.get("untrusted_fields") or []),
                    user_args=list(d.get("user_args") or []))


def load_manifest(path) -> dict[str, ToolSpec]:
    """Tool specs from a YAML file: {tools: {name: {...}}}. Missing keys take cautious defaults (a write, external,
    irreversible): a tool is only as trusted as its manifest says."""
    import yaml
    from pathlib import Path
    data = yaml.safe_load(Path(path).read_text()) or {}
    return {name: spec_from_dict(name, d or {}) for name, d in (data.get("tools") or {}).items()}


def load_manifest_roles(path) -> dict[str, list[str]]:
    """The optional `roles:` section of a manifest file: which roles may use its tools."""
    import yaml
    from pathlib import Path
    data = yaml.safe_load(Path(path).read_text()) or {}
    return {r: list(t or []) for r, t in (data.get("roles") or {}).items()}


def register_manifests(registry: "ToolRegistry", roles: dict[str, list[str]], paths) -> list[str]:
    """Add the tools (pinned) and roles of each manifest file to a registry and a policy's role table."""
    added = []
    for p in paths:
        for name, spec in load_manifest(p).items():
            registry.specs[name], registry.pins[name] = spec, spec.definition_hash()
            added.append(name)
        for role, tools in load_manifest_roles(p).items():
            roles.setdefault(role, [])
            roles[role] += [t for t in tools if t not in roles[role]]
    return added


def dump_manifest(specs: dict[str, ToolSpec]) -> str:
    import yaml
    return yaml.safe_dump({"tools": {n: spec_to_dict(s) for n, s in specs.items()}}, sort_keys=False, width=120)


MCP_TYPES = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}
JSON_TYPES = {v: k for k, v in MCP_TYPES.items()}


class ToolRegistry:
    def __init__(self, specs: dict[str, ToolSpec] | None = None):
        # None means KAVACH's own tools; an empty dict means no tools (never silently the default set)
        self.specs = default_manifest() if specs is None else specs
        self.pins = {n: s.definition_hash() for n, s in self.specs.items()}
        self.drafts: set[str] = set()        # onboarded from MCP annotations, not yet approved by a human
        self.on_approve: list = []           # callbacks(name, pin) when a human approves a draft (e.g. persist pins)

    def get(self, name: str) -> ToolSpec | None:
        return self.specs.get(name)

    def add_draft(self, name: str, description: str = "", input_schema: dict | None = None,
                  annotations: dict | None = None, arg_names=()) -> ToolSpec:
        """Onboard an unknown tool from its MCP description. Until a human approves it, calls escalate (R6).
        Missing hints take MCP's own cautious defaults: not read-only, destructive, open world."""
        ann = annotations or {}
        props = (input_schema or {}).get("properties") or {k: {} for k in arg_names}
        params = {k: MCP_TYPES.get(v.get("type"), "any") for k, v in props.items()}
        read = bool(ann.get("readOnlyHint", False))
        rev = Reversibility.IDEMPOTENT if read else (
            Reversibility.IRREVERSIBLE if ann.get("destructiveHint", True) else Reversibility.COMPENSABLE)
        spec = ToolSpec(name, description, params, list((input_schema or {}).get("required", [])),
                        effect="read" if read else "write",
                        sink="external" if ann.get("openWorldHint", True) else "internal",
                        reversibility=rev, control_args=[] if read else list(params),
                        output_trust="untrusted", output_conf=Conf.CONFIDENTIAL)   # unknown output: assume the worst
        self.specs[name], self.pins[name] = spec, spec.definition_hash()
        self.drafts.add(name)
        return spec

    def approve(self, name: str) -> bool:
        """A human approved the draft: its definition is now pinned like any other tool."""
        if name not in self.drafts:
            return False
        self.drafts.discard(name)
        # keep the pin of the definition the human looked at (an MCP proxy pins the upstream's own definition)
        self.pins[name] = self.pins.get(name) or self.specs[name].definition_hash()
        for cb in self.on_approve:
            cb(name, self.pins[name])
        return True

    def verify_pin(self, name: str, presented_hash: str | None) -> bool:
        """True if the definition the agent saw matches the approved, pinned one."""
        if presented_hash is None:
            return True
        return self.pins.get(name) == presented_hash

    def validate_args(self, spec: ToolSpec, args: dict) -> list[str]:
        errors = []
        for r in spec.required:
            if r not in args:
                errors.append(f"missing required arg '{r}'")
        for k, v in args.items():
            t = spec.params.get(k)
            if t == "any":
                continue
            if t is None:
                errors.append(f"unexpected arg '{k}'")
            elif t == "str" and not isinstance(v, str):
                errors.append(f"arg '{k}' must be str")
            elif t in ("int", "float") and not isinstance(v, (int, float)):
                errors.append(f"arg '{k}' must be numeric")
        return errors

    def mcp_tools_list(self) -> list[dict]:
        out = []
        for s in self.specs.values():
            out.append({
                "name": s.name, "description": s.description,
                "inputSchema": {"type": "object", "required": s.required,
                                "properties": {k: ({"type": JSON_TYPES[v]} if v in JSON_TYPES else {})
                                               for k, v in s.params.items()}},
                "annotations": s.mcp_annotations(),
                "_meta": {"kavach/definitionHash": self.pins[s.name]},
            })
        return out
