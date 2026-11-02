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
    staging: str = "none"                        # sqlite | fs | none
    safeguard: str | None = None                 # safe transform the gateway applies (hold/recall-window/park:
                                                 # a window it can still cancel; reversibility is the tool's own)
    amount_arg: str | None = None                # for tools KAVACH has no custom model of: the argument that is money
    intent_verbs: list[str] = field(default_factory=list)   # words in a request that ask for this kind of action
    # MCP-style hints (readOnlyHint/destructiveHint/openWorldHint) are derived, never trusted from servers
    def mcp_annotations(self) -> dict:
        return {"readOnlyHint": self.effect in ("read", "ingress"),
                "destructiveHint": self.reversibility in (Reversibility.IRREVERSIBLE, Reversibility.COMPENSABLE),
                "openWorldHint": self.sink == "external"}

    def definition_hash(self) -> str:
        blob = json.dumps({"n": self.name, "d": self.description, "p": self.params, "r": self.required},
                          sort_keys=True).encode()
        return hashlib.sha256(blob).hexdigest()[:16]


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


MCP_TYPES = {"string": "str", "integer": "int", "number": "float", "boolean": "bool"}
JSON_TYPES = {v: k for k, v in MCP_TYPES.items()}


class ToolRegistry:
    def __init__(self, specs: dict[str, ToolSpec] | None = None):
        self.specs = specs or default_manifest()
        self.pins = {n: s.definition_hash() for n, s in self.specs.items()}
        self.drafts: set[str] = set()        # onboarded from MCP annotations, not yet approved by a human

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
                        reversibility=rev, control_args=[] if read else list(params))
        self.specs[name], self.pins[name] = spec, spec.definition_hash()
        self.drafts.add(name)
        return spec

    def approve(self, name: str) -> bool:
        """A human approved the draft: its definition is now pinned like any other tool."""
        if name not in self.drafts:
            return False
        self.drafts.discard(name)
        self.pins[name] = self.specs[name].definition_hash()
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
