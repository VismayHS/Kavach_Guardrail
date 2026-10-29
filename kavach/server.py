"""HTTP API + dashboard.

    uvicorn kavach.server:app --port 8000      then open http://localhost:8000

Endpoints
  POST /api/v1/check            raw action input -> decision + receipt   (the PS's "agent action input")
  POST /api/v1/plan             validate a whole plan before step one
  POST /mcp                     MCP-style JSON-RPC (tools/list, tools/call) so an MCP client can sit behind KAVACH
  POST /api/demo/{scenario}     replay a scripted scenario through the gateway
  GET  /api/hitl                pending approvals;  POST /api/hitl/{id}  approve / deny
  POST /api/undo/{receipt_id}   restore the snapshot taken before a safeguarded action
  GET  /api/receipts            receipt chain;      GET /api/receipts/verify
  GET  /api/metrics             latest benchmark results
"""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from .environment import Environment
from .gateway import Kavach
from .models import ToolCall
from .scenarios import SCENARIOS, materialize

ROOT = Path(__file__).resolve().parent
env = Environment(tempfile.mkdtemp(prefix="kavach-"))
gw = Kavach(env)
app = FastAPI(title="KAVACH guardrail", version="0.1")
_mcp_task: dict[str, str] = {}


class CheckIn(BaseModel):
    user_request: str
    tool: str
    args: dict
    user_id: str = "demo-user"
    role: str = "support"
    env: str = "prod"
    context: list[dict] = []        # earlier tool outputs: [{"tool": "...", "output": ...}] for provenance
    execute: bool = False
    tool_def_hash: str | None = None


class PlanIn(BaseModel):
    user_request: str
    plan: list[dict]
    user_id: str = "demo-user"
    role: str = "support"


class HitlIn(BaseModel):
    approve: bool
    approver: str = "reviewer-1"
    mode: str = "execute"


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.post("/api/v1/check")
def check(body: CheckIn):
    tid, _ = gw.start_task(body.user_id, body.role, body.user_request, body.env)
    for c in body.context:
        spec = gw.registry.get(c.get("tool", ""))
        if spec:
            gw.tasks[tid].prov.register_output(c["tool"], c.get("output"), spec.output_trust, spec.output_conf)
    d = gw.check(tid, ToolCall(body.tool, body.args, tool_def_hash=body.tool_def_hash))
    if body.execute:
        gw.execute(tid, d)
    return {"task_id": tid, **d.to_dict(), "explanation": d.explanation}


@app.post("/api/v1/plan")
def plan(body: PlanIn):
    _, report = gw.start_task(body.user_id, body.role, body.user_request, plan=body.plan)
    return report


@app.get("/api/scenarios")
def scenarios():
    return [{"id": k, "title": v["title"], "request": v["request"], "user": v["user"]} for k, v in SCENARIOS.items()]


@app.post("/api/demo/{name}")
def demo(name: str, reset: bool = True):
    sc = SCENARIOS.get(name)
    if sc is None:
        raise HTTPException(404, "unknown scenario")
    if reset:
        env.reset()
    tid, plan_report = gw.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
    steps, last = [], None
    for call in sc["steps"]:
        call = materialize(call, last)
        d = gw.run(tid, call)
        steps.append({**d.to_dict(), "explanation": d.explanation})
        last = d.result
        if d.verdict.value in ("DENY", "ESCALATE"):
            break        # a blocked agent receives the replan hint instead of continuing blindly
    return {"task_id": tid, "scenario": name, "title": sc["title"], "request": sc["request"],
            "principal": {"user": sc["user"][0], "role": sc["user"][1]}, "plan": plan_report, "steps": steps,
            "state": {"tables": env.table_counts(), "outbox": len(env.outbox), "ledger": len(env.ledger)}}


@app.get("/api/hitl")
def hitl_pending():
    return gw.hitl.pending()


@app.post("/api/hitl/{hid}")
def hitl_resolve(hid: str, body: HitlIn):
    try:
        return gw.resolve_hitl(hid, body.approver, body.approve, body.mode)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(409, str(e))


@app.post("/api/undo/{rid}")
def undo(rid: str):
    return gw.undo_action(rid)


@app.get("/api/receipts")
def receipts(limit: int = 50):
    return gw.receipts.items[-limit:]


@app.get("/api/receipts/verify")
def verify():
    return gw.receipts.verify()


@app.get("/api/state")
def state():
    return {"tables": env.table_counts(), "outbox": env.outbox[-5:], "ledger": env.ledger[-5:],
            "risk_model": gw.risk.source, "c_block": gw.cfg.c_block, "policy": gw.policy.version,
            "qualcomm_llm": gw.judge.llm.enabled, "judge_model": gw.judge.llm.model}


@app.get("/api/metrics")
def metrics():
    p = ROOT.parent / "bench" / "results" / "results.json"
    if not p.exists():
        return JSONResponse({"error": "run python -m bench.run first"}, 404)
    d = json.loads(p.read_text())
    d.pop("full_rows", None)
    return d


@app.get("/bench/{name}")
def bench_file(name: str):
    p = ROOT.parent / "bench" / "results" / Path(name).name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p)


# ---------------------------------------------------------------- MCP-style JSON-RPC front door
@app.post("/mcp")
def mcp(rpc: dict):
    """Minimal MCP JSON-RPC: initialize, tools/list, tools/call. Every tools/call goes through the gateway.
    The user's request is passed once via params._meta['kavach/userRequest'] (session-scoped)."""
    mid, method, params = rpc.get("id"), rpc.get("method"), rpc.get("params", {}) or {}
    meta = params.get("_meta", {}) or {}
    session = meta.get("kavach/session", "default")
    if method == "initialize":
        tid, _ = gw.start_task(meta.get("kavach/user", "mcp-user"), meta.get("kavach/role", "support"),
                               meta.get("kavach/userRequest", ""), meta.get("kavach/env", "prod"))
        _mcp_task[session] = tid
        return {"jsonrpc": "2.0", "id": mid, "result": {"protocolVersion": "2025-06-18",
                "serverInfo": {"name": "kavach-gateway", "version": "0.1"}, "capabilities": {"tools": {}}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": mid, "result": {"tools": gw.registry.mcp_tools_list()}}
    if method == "tools/call":
        tid = _mcp_task.get(session)
        if tid is None:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32002, "message": "call initialize first"}}
        call = ToolCall(params.get("name", ""), params.get("arguments", {}) or {},
                        tool_def_hash=meta.get("kavach/definitionHash"))
        d = gw.run(tid, call)
        allowed = d.verdict.value.startswith("ALLOW")
        text = json.dumps(d.result, default=str)[:4000] if allowed else (
            f"KAVACH {d.verdict.value}: {d.reason}" + (f" Suggested: {d.replan_hint}" if d.replan_hint else ""))
        return {"jsonrpc": "2.0", "id": mid, "result": {
            "content": [{"type": "text", "text": text}], "isError": not allowed,
            "_meta": {"kavach/verdict": d.verdict.value, "kavach/receipt": d.receipt_id, "kavach/hitl": d.hitl_id}}}
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
