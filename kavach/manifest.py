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
    safeguard: str | None = None                 # safe transform the gateway can apply
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
                 safeguard="save-as-draft"),
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
                 control_args=["to_account", "amount"], data_args=["memo"], safeguard="hold-for-24h"),
        ToolSpec("payments.refund", "Refund an invoice.", {"invoice_id": "int", "amount": "float"},
                 ["invoice_id", "amount"], effect="payment", sink="external", reversibility=R.COMPENSABLE,
                 control_args=["invoice_id", "amount"]),
        ToolSpec("web.fetch", "Fetch a web page.", {"url": "str"}, ["url"], effect="ingress", sink="none",
                 reversibility=R.IDEMPOTENT, control_args=["url"], output_trust="untrusted",
                 output_conf=Conf.PUBLIC),
    ]
    return {s.name: s for s in specs}


class ToolRegistry:
    def __init__(self, specs: dict[str, ToolSpec] | None = None):
        self.specs = specs or default_manifest()
        self.pins = {n: s.definition_hash() for n, s in self.specs.items()}

    def get(self, name: str) -> ToolSpec | None:
        return self.specs.get(name)

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
                                "properties": {k: {"type": {"str": "string", "int": "integer", "float": "number",
                                                            "bool": "boolean"}[v]} for k, v in s.params.items()}},
                "annotations": s.mcp_annotations(),
                "_meta": {"kavach/definitionHash": self.pins[s.name]},
            })
        return out
