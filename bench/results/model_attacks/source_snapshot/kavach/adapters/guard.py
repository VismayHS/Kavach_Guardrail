"""KavachGuard: the one object every framework adapter uses (E2).

    guard = KavachGuard(manifests=["my_tools.yaml"])            # in-process: its own KAVACH gateway
    guard = KavachGuard(url="http://localhost:8000", token=...)  # remote: a KAVACH server decides

    guard.start("Email bob@partner.example that the meeting moved.")   # the user's request (trusted)
    d = guard.check("send_email", {"to": "bob@partner.example", ...})   # before the tool runs
    if d.allowed: out = run_tool(...); guard.record("send_email", args, out)   # after: label what it returned
    else: tell_the_model(d.message)

KAVACH only decides here; the framework runs the tool (local_execution=False: no undo is claimed for what KAVACH
doesn't run). A tool KAVACH has no manifest for is onboarded as a cautious draft (calls escalate) unless
onboard_unknown=False, in which case it is refused (R6).
"""
from __future__ import annotations

import json
import tempfile
import time
import urllib.request
import uuid
from dataclasses import dataclass, field

from ..environment import Environment
from ..gateway import GatewayConfig, Kavach
from ..manifest import ToolRegistry, load_manifest, spec_from_dict
from ..models import ToolCall
from ..risk import RiskModel


@dataclass
class GuardDecision:
    verdict: str                     # ALLOW | ALLOW_WITH_SAFEGUARD | ESCALATE | DENY
    reason: str
    hint: str | None = None
    receipt: str | None = None
    hitl: str | None = None
    raw: dict = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.verdict.startswith("ALLOW")

    @property
    def message(self) -> str:
        """What the model should be told instead of a tool result."""
        if self.allowed:
            return ""
        what = "needs a person's approval first" if self.verdict == "ESCALATE" else "was blocked"
        return (f"KAVACH: this call {what}. {self.reason}" + (f" Suggested instead: {self.hint}" if self.hint else "")
                + (f" (approval request {self.hitl})" if self.hitl else ""))

    def as_dict(self) -> dict:
        return {"verdict": self.verdict, "reason": self.reason, "hint": self.hint, "receipt": self.receipt,
                "hitl": self.hitl}


class KavachGuard:
    def __init__(self, manifests=(), tools: dict[str, dict] | None = None, *, url: str | None = None,
                 token: str | None = None, user: str = "agent-user", role: str = "agent", env: str = "prod",
                 onboard_unknown: bool = True, approval_wait_s: float = 0.0, gateway: Kavach | None = None,
                 timeout: float = 10.0):
        self.url, self.token, self.user, self.role, self.env = url, token, user, role, env
        self.onboard_unknown, self.approval_wait_s, self.timeout = onboard_unknown, approval_wait_s, timeout
        self.request, self.task, self.session = "", None, uuid.uuid4().hex[:12]
        self.context: list[dict] = []                 # remote mode: what the agent read, sent with each check
        self.gw = None
        if url is None:
            self.gw = gateway or Kavach(Environment(tempfile.mkdtemp(prefix="kavach-guard-")), GatewayConfig(
                use_llm_judge=False, use_windows=False, local_execution=False,
                c_block=RiskModel().meta.get("operating_point", {}).get("c_block", 0.02)), registry=ToolRegistry({}))
            for m in manifests:
                for name, spec in load_manifest(m).items():
                    self._add(name, spec)
            for name, d in (tools or {}).items():
                self._add(name, spec_from_dict(name, d))

    # ---------------------------------------------------------------- tools
    def _add(self, name: str, spec) -> None:
        self.gw.registry.specs[name] = spec
        self.gw.registry.pins[name] = spec.definition_hash()
        self.gw.policy.cfg["roles"].setdefault(self.role, [])
        if name not in self.gw.policy.cfg["roles"][self.role]:
            self.gw.policy.cfg["roles"][self.role].append(name)

    def describe(self, name: str, **manifest) -> None:
        """Tell KAVACH what a tool does (same keys as a manifest file: effect, sink, effect_model, control_args...)."""
        self._add(name, spec_from_dict(name, manifest))

    # ---------------------------------------------------------------- sessions
    def start(self, request: str) -> None:
        """A new user request: a new KAVACH task (provenance, budget and denials start over)."""
        self.request, self.context, self.session = request, [], uuid.uuid4().hex[:12]
        self.task = self.gw.start_task(self.user, self.role, request, self.env)[0] if self.gw else None

    def _ensure_task(self) -> None:
        if self.gw is not None and self.task is None:
            self.task = self.gw.start_task(self.user, self.role, self.request, self.env)[0]

    # ---------------------------------------------------------------- decisions
    def check(self, tool: str, args: dict) -> GuardDecision:
        args = dict(args or {})
        if self.gw is None:
            return self._remote_check(tool, args)
        self._ensure_task()
        if self.gw.registry.get(tool) is None and self.onboard_unknown:
            self.gw.registry.add_draft(tool, "", None, {}, list(args))     # cautious draft: a person decides
            self._add(tool, self.gw.registry.specs[tool])
            self.gw.registry.drafts.add(tool)
        d = self.gw.check(self.task, ToolCall(tool, args))
        verdict = d.verdict.value
        if verdict == "ESCALATE" and self.approval_wait_s > 0:
            verdict = self._wait(d.hitl_id) or verdict
        return GuardDecision(verdict, d.reason, d.replan_hint, d.receipt_id, d.hitl_id, d.to_dict())

    def _wait(self, hid) -> str | None:
        deadline = time.time() + self.approval_wait_s
        while hid and time.time() < deadline:
            st = self.gw.hitl.items[hid]["status"]
            if st == "approved":
                return "ALLOW"
            if st != "pending":
                return "DENY"
            time.sleep(0.2)
        return None

    def record(self, tool: str, args: dict, output) -> None:
        """Label what a tool returned, so later arguments can be traced back to it."""
        output = _plain(output)
        if self.gw is None:
            self.context.append({"tool": tool, "args": dict(args or {}), "output": output})
            return
        self._ensure_task()
        if self.gw.registry.get(tool) is not None:
            self.gw.register_output(self.task, ToolCall(tool, dict(args or {})), output)

    def _remote_check(self, tool: str, args: dict) -> GuardDecision:
        body = {"user_request": self.request, "tool": tool, "args": args, "user_id": self.user, "role": self.role,
                "env": self.env, "session_id": self.session, "context": self.context}
        if self.onboard_unknown:
            body["tool_annotations"] = {}
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(f"{self.url.rstrip('/')}/api/v1/check", data=json.dumps(body, default=str).encode(),
                                     headers=headers)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:   # any failure raises: callers fail closed
            d = json.loads(r.read())
        return GuardDecision(d["verdict"], d.get("reason", ""), d.get("replan_hint"), d.get("receipt_id"),
                             d.get("hitl_id"), d)


def _plain(x):
    if hasattr(x, "model_dump"):
        return x.model_dump(mode="json")
    if isinstance(x, (list, tuple)):
        return [_plain(v) for v in x]
    if isinstance(x, dict):
        return {k: _plain(v) for k, v in x.items()}
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)
