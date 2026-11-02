"""Secrets broker (F1): the agent names a credential, the broker supplies it at execution time, and the agent and
the receipts never see the value. OWASP's agentic guidance: "keys must never be directly available to agents".

    args: {"url": "https://api.vendor.example/v1/pay", "token": "{{secret:VENDOR_API_KEY}}"}

The gateway decides on the placeholder (so a receipt shows `{{secret:VENDOR_API_KEY}}`, never the key); the
broker resolves it in the connector, immediately before the call, and only for tools that secret is granted to.
Secrets come from environment variables KAVACH_SECRET_<NAME> (stand-in for Vault / a KMS-backed store).

Rule R32 (in kavach/policy.py) blocks the other direction: an argument that carries a raw credential (an AWS key,
a Stripe or OpenAI secret key, a GitHub or Slack token, a private key) means a key passed through the agent.
"""
from __future__ import annotations

import os
import re

PLACEHOLDER = re.compile(r"\{\{secret:([A-Z0-9_]{2,64})\}\}")
RAW_CREDENTIAL = [
    ("AWS access key", re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("secret API key", re.compile(r"\b(sk|rk)_(live|test)_[0-9A-Za-z]{16,}\b|\bsk-(proj-|live-)?[A-Za-z0-9_-]{20,}\b")),
    ("GitHub token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
]


def raw_credentials(args: dict) -> list[str]:
    """Kinds of raw credential found in a call's arguments (placeholders are fine)."""
    blob = " ".join(str(v) for v in args.values())
    return [kind for kind, rx in RAW_CREDENTIAL if rx.search(blob)]


class SecretsBroker:
    def __init__(self, grants: dict[str, list[str]] | None = None, environ=None):
        """grants: secret name -> tools allowed to receive it (None = any tool)."""
        self.grants = grants
        self.env = os.environ if environ is None else environ
        self.used: list[tuple[str, str]] = []          # (tool, secret name): what was injected, never the value

    def resolve(self, tool: str, args: dict) -> dict:
        """Replace placeholders with secret values for this tool. Raises PermissionError for an ungranted or missing
        secret (fail closed: the call doesn't go out with a broken credential)."""
        def sub(m):
            name = m.group(1)
            if self.grants is not None and tool not in self.grants.get(name, []):
                raise PermissionError(f"secret {name} is not granted to {tool}")
            value = self.env.get(f"KAVACH_SECRET_{name}")
            if value is None:
                raise PermissionError(f"secret {name} is not configured")
            self.used.append((tool, name))
            return value
        return {k: PLACEHOLDER.sub(sub, v) if isinstance(v, str) else v for k, v in args.items()}
