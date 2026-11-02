"""KAVACH as an MCP proxy (E1): any MCP client  <->  KAVACH  <->  real upstream MCP servers.

    python -m kavach.mcp_proxy --config kavach_mcp.yaml               # stdio (Claude Desktop, IDEs)
    python -m kavach.mcp_proxy --config kavach_mcp.yaml --http 8100   # Streamable HTTP
    python -m kavach.mcp_proxy --config kavach_mcp.yaml --console 8000  # plus the approvals console/API

At start the proxy connects to each upstream server, reads its tools, and:
  * scans every definition (kavach.mcp_proxy.scan): poisoned or shadowing tools are quarantined, never listed;
  * pins each definition's hash (a JSON pins file). A tool whose definition changed since it was pinned (a rug
    pull, or an upgrade nobody reviewed) is hidden, and calls to it are denied (R6) until a person re-approves it.
    New tools are pinned on first use (trust_on_first_use) or wait for approval as drafts;
  * builds a KAVACH manifest entry: from the config's manifests when given (effect model, argument roles,
    reversibility...), otherwise from the tool's MCP annotations with MCP's cautious defaults.
Every tools/call then goes through the KAVACH gateway: provenance of each argument, consequence, rules, risk.
Allowed calls are forwarded upstream and their output is labelled for provenance; denied calls return KAVACH's
reason and replan hint as a tool error; escalated calls wait for a person (approvals console, /api/hitl) up to
approval_wait_s, then go upstream or fail. KAVACH only decides here (local_execution=False): it can't hold or
snapshot what an upstream server runs, so it never claims an undo it doesn't have.

The user's request (for provenance and intent) comes from the call's _meta["kavach/userRequest"] when the client
sends it, otherwise from the config's `request`.
"""
from __future__ import annotations

import asyncio
import json
import os
import tempfile
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import mcp_types as types
import yaml
from mcp import Client, StdioServerParameters
from mcp.server.lowlevel.server import Server

from ..environment import Environment
from ..gateway import GatewayConfig, Kavach
from ..manifest import MCP_TYPES, ToolRegistry, ToolSpec, load_manifest, spec_from_dict, spec_to_dict
from ..models import Reversibility, ToolCall, Verdict
from ..risk import RiskModel
from .scan import as_dicts, definition_hash, scan_tools

ROLE = "mcp_agent"


@dataclass
class ProxyConfig:
    upstreams: dict[str, Any]                     # name -> URL | StdioServerParameters | in-process server
    overrides: dict[str, dict] = field(default_factory=dict)   # manifest entries by exposed or upstream tool name
    pins_path: str | None = None
    trust_on_first_use: bool = True
    request: str = ""
    user: str = "mcp-user"
    approval_wait_s: float = 60.0
    namespace: bool = True                        # expose tools as <server>__<tool>
    judge: bool = False                           # Qualcomm judge (escalations-only) when a key is configured

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ProxyConfig":
        path = Path(path)
        d = yaml.safe_load(path.read_text()) or {}
        ups: dict[str, Any] = {}
        for name, u in (d.get("upstreams") or {}).items():
            if "url" in u:
                ups[name] = u["url"]
            else:
                env = {**os.environ, **{k: str(v) for k, v in (u.get("env") or {}).items()}}
                ups[name] = StdioServerParameters(command=u["command"], args=list(u.get("args") or []), env=env)
        overrides: dict[str, dict] = {}
        for m in d.get("manifests") or []:
            mp = (path.parent / m) if not Path(m).is_absolute() else Path(m)
            overrides.update({n: spec_to_dict(s) for n, s in load_manifest(mp).items()})
        overrides.update(d.get("tools") or {})
        pins = d.get("pins")
        return cls(upstreams=ups, overrides=overrides,
                   pins_path=str((path.parent / pins) if pins and not Path(pins).is_absolute() else pins) if pins else None,
                   trust_on_first_use=bool(d.get("trust_on_first_use", True)), request=d.get("request", ""),
                   user=d.get("user", "mcp-user"), approval_wait_s=float(d.get("approval_wait_s", 60)),
                   namespace=bool(d.get("namespace", True)), judge=bool(d.get("judge", False)))


@dataclass
class ExposedTool:
    name: str                    # what the client sees
    upstream: str
    raw: str                     # the upstream's own name
    definition: dict             # name, description, inputSchema, annotations (as the model would read them)
    hash: str
    status: str                  # approved | draft | changed | quarantined
    findings: list[dict] = field(default_factory=list)


def _tool_dict(t: types.Tool) -> dict:
    ann = t.annotations.model_dump(by_alias=True, exclude_none=True) if t.annotations else {}
    return {"name": t.name, "description": t.description or "", "inputSchema": t.input_schema or {}, "annotations": ann}


class KavachMCPProxy:
    def __init__(self, config: ProxyConfig, gateway: Kavach | None = None):
        self.cfg = config
        self.gw = gateway or Kavach(Environment(tempfile.mkdtemp(prefix="kavach-mcp-")), GatewayConfig(
            use_llm_judge=config.judge, judge_mode="escalations-only", use_windows=False, local_execution=False,
            c_block=RiskModel().meta.get("operating_point", {}).get("c_block", 0.02)), registry=ToolRegistry({}))
        self.gw.registry.on_approve.append(self._approved)
        self.clients: dict[str, Client] = {}
        self.tools: dict[str, ExposedTool] = {}
        # KAVACH task per session. MCP's 2026 protocol is stateless per request, so the session is what the client
        # names in _meta["kavach/session"]; without one, the whole proxy process is one session (the stdio case:
        # one client, one proxy). Run one proxy per user, or have clients send kavach/session, for shared HTTP use.
        self.sessions: dict[str, str] = {}
        self.pins: dict[str, dict] = self._load_pins()

    # ---------------------------------------------------------------- pins
    def _load_pins(self) -> dict[str, dict]:
        p = self.cfg.pins_path
        return json.loads(Path(p).read_text()) if p and Path(p).exists() else {}

    def _save_pins(self) -> None:
        if self.cfg.pins_path:
            Path(self.cfg.pins_path).parent.mkdir(parents=True, exist_ok=True)
            Path(self.cfg.pins_path).write_text(json.dumps(self.pins, indent=1, sort_keys=True))

    def _pin(self, t: ExposedTool, by: str) -> None:
        self.pins[t.name] = {"hash": t.hash, "upstream": t.upstream, "tool": t.raw, "by": by, "at": round(time.time())}
        self._save_pins()

    def _approved(self, name: str, _pin: str) -> None:
        """A person approved a draft (or re-approved a changed tool): pin what they saw, show it again."""
        t = self.tools.get(name)
        if t is None:
            return
        self.gw.registry.pins[name] = t.hash
        t.status = "approved"
        self._pin(t, "human")

    # ---------------------------------------------------------------- upstreams
    async def connect(self, stack: AsyncExitStack) -> None:
        """Connect to every upstream, then scan, pin and register its tools."""
        listed: dict[str, list[tuple[str, dict]]] = {}
        for name, target in self.cfg.upstreams.items():
            client = await stack.enter_async_context(Client(target))
            self.clients[name] = client
            res = await client.list_tools()
            listed[name] = [(self._exposed(name, t.name), _tool_dict(t)) for t in res.tools]
        names = {up: [n for n, _ in tools] for up, tools in listed.items()}
        for up, tools in listed.items():
            others = {u: n for u, n in names.items() if u != up}
            for exposed, d in tools:
                findings = as_dicts(scan_tools([d], others))
                self._register(ExposedTool(exposed, up, d["name"], d, definition_hash(d), "draft", findings))
        self.gw.policy.cfg["roles"][ROLE] = sorted(self.tools)

    def _exposed(self, upstream: str, raw: str) -> str:
        return f"{upstream}__{raw}" if self.cfg.namespace else raw

    def _register(self, t: ExposedTool) -> None:
        self.tools[t.name] = t
        if any(f["severity"] == "block" for f in t.findings):
            t.status = "quarantined"           # never listed; calls refused
            self.gw.receipts.append({"type": "mcp-tool-quarantined", "tool": t.name, "findings": t.findings})
            return
        reg = self.gw.registry
        reg.specs[t.name] = self._spec(t)
        pinned = self.pins.get(t.name)
        if pinned and pinned["hash"] == t.hash:
            t.status = "approved"
            reg.pins[t.name] = t.hash
        elif pinned:                            # rug pull, or an upgrade nobody reviewed
            t.status = "changed"
            reg.pins[t.name] = pinned["hash"]   # calls present the new hash: R6 denies until re-approved
            reg.drafts.add(t.name)
            self.gw.receipts.append({"type": "mcp-tool-changed", "tool": t.name, "pinned": pinned["hash"],
                                     "now": t.hash})
        elif self.cfg.trust_on_first_use:
            t.status = "approved"
            reg.pins[t.name] = t.hash
            self._pin(t, "first-use")
        else:
            t.status = "draft"                  # every call escalates (R6) until a person approves the tool
            reg.pins[t.name] = t.hash
            reg.drafts.add(t.name)

    def _spec(self, t: ExposedTool) -> ToolSpec:
        """The tool's KAVACH manifest entry: from the config when given, else from its MCP annotations."""
        d = t.definition
        schema = d.get("inputSchema") or {}
        params = {k: MCP_TYPES.get((v or {}).get("type"), "any") for k, v in (schema.get("properties") or {}).items()}
        required = list(schema.get("required") or [])
        over = self.cfg.overrides.get(t.name) or self.cfg.overrides.get(t.raw)
        if over:
            spec = spec_from_dict(t.name, {"description": d.get("description", ""), "params": params,
                                           "required": required, **over})
        else:
            ann = d.get("annotations") or {}
            read = bool(ann.get("readOnlyHint", False))
            open_world = bool(ann.get("openWorldHint", True))
            rev = Reversibility.IDEMPOTENT if read else (
                Reversibility.IRREVERSIBLE if ann.get("destructiveHint", True) else Reversibility.COMPENSABLE)
            spec = ToolSpec(t.name, d.get("description", ""), params, required, effect="read" if read else "write",
                            sink="external" if open_world else "internal", reversibility=rev,
                            control_args=[] if read else list(params),
                            output_trust="untrusted" if open_world else "derived")
        spec.safeguard = None                   # KAVACH can't hold or snapshot what an upstream server runs
        return spec

    # ---------------------------------------------------------------- MCP server side
    def listed(self) -> list[types.Tool]:
        out = []
        for t in self.tools.values():
            if t.status not in ("approved", "draft"):
                continue
            d = t.definition
            out.append(types.Tool(name=t.name, description=d.get("description") or None,
                                  input_schema=d.get("inputSchema") or {"type": "object"},
                                  annotations=types.ToolAnnotations(**{
                                      k: v for k, v in self.gw.registry.specs[t.name].mcp_annotations().items()}),
                                  meta={"kavach/upstream": t.upstream, "kavach/definitionHash": t.hash,
                                        "kavach/status": t.status}))
        return out

    def _task(self, session_key: str, request: str | None) -> str:
        tid = self.sessions.get(session_key)
        if tid is None:
            tid, _ = self.gw.start_task(self.cfg.user, ROLE, request or self.cfg.request, env="prod")
            self.sessions[session_key] = tid
        elif request:
            self.gw.add_request(tid, request)
        return tid

    async def call(self, name: str, arguments: dict, meta: dict | None = None) -> types.CallToolResult:
        meta = meta or {}
        tid = self._task(str(meta.get("kavach/session") or "default"), meta.get("kavach/userRequest"))
        t = self.tools.get(name)
        if t is not None and t.status == "quarantined":
            self.gw.receipts.append({"type": "mcp-quarantined-call", "task_id": tid, "tool": name})
            return _error(f"KAVACH DENY: '{name}' is quarantined: its definition carries injected instructions "
                          f"({', '.join(sorted({f['kind'] for f in t.findings}))}).", "DENY", None)
        call = ToolCall(name, dict(arguments or {}), tool_def_hash=t.hash if t else None)
        d = self.gw.check(tid, call)
        if d.verdict == Verdict.ESCALATE:
            status = await self._await_human(d.hitl_id)
            if status != "approved":
                return _error(f"KAVACH ESCALATE: a person had to approve this call and it was {status} "
                              f"({d.reason}).", "ESCALATE", d.receipt_id, d.hitl_id)
        elif d.verdict == Verdict.DENY:
            return _error(f"KAVACH DENY: {d.reason}" + (f" Suggested: {d.replan_hint}" if d.replan_hint else ""),
                          "DENY", d.receipt_id)
        res = await self.clients[t.upstream].call_tool(t.raw, call.args)
        self.gw.register_output(tid, call, _output(res))
        self.gw.receipts.append({"type": "mcp-forwarded", "task_id": tid, "decision_receipt": d.receipt_id,
                                 "tool": name, "upstream_error": bool(res.is_error)})
        res.meta = {**(res.meta or {}), "kavach/verdict": d.verdict.value, "kavach/receipt": d.receipt_id}
        return res

    async def _await_human(self, hid: str | None) -> str:
        deadline = time.time() + self.cfg.approval_wait_s
        while hid and time.time() < deadline:
            st = self.gw.hitl.items[hid]["status"]
            if st != "pending":
                return st
            await asyncio.sleep(0.2)
        return "not answered in time"

    def server(self) -> Server:
        async def on_list_tools(ctx, params):
            return types.ListToolsResult(tools=self.listed())

        async def on_call_tool(ctx, params: types.CallToolRequestParams):
            return await self.call(params.name, params.arguments or {},
                                   params.meta if isinstance(params.meta, dict) else {})

        return Server("kavach-mcp-proxy", version="0.2", instructions=(
            "Tools from other MCP servers, guarded by KAVACH. A refused call returns KAVACH's reason and a "
            "suggested alternative; don't retry it unchanged."), on_list_tools=on_list_tools,
            on_call_tool=on_call_tool)


def _output(res: types.CallToolResult):
    if res.structured_content:
        return res.structured_content
    texts = [getattr(c, "text", None) for c in res.content or []]
    return "\n".join(x for x in texts if x)


def _error(text: str, verdict: str, receipt: str | None, hitl: str | None = None) -> types.CallToolResult:
    return types.CallToolResult(content=[types.TextContent(type="text", text=text)], is_error=True,
                                meta={"kavach/verdict": verdict, "kavach/receipt": receipt, "kavach/hitl": hitl})
