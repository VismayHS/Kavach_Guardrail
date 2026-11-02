"""HTTP API + dashboard.

    uvicorn kavach.server:app --port 8000      then open http://localhost:8000

Endpoints
  POST /api/v1/check            raw action input -> decision + receipt   (the PS's "agent action input")
  POST /api/v1/plan             validate a whole plan before step one
  POST /mcp                     MCP-style JSON-RPC (tools/list, tools/call) so an MCP client can sit behind KAVACH
  POST /api/demo/{scenario}     replay a scripted scenario through the gateway
  GET  /api/hitl                pending approvals;  POST /api/hitl/{id}  approve / deny
  POST /api/undo/{receipt_id}   take back a safeguarded action: restore its snapshot, or cancel its hold / recall / park
  POST /api/settle              let held payments and queued emails go out (advance_s fast-forwards the clock)
  GET  /api/receipts            receipt chain;      GET /api/receipts/verify
  GET  /api/metrics             latest benchmark results
  GET  /api/autonomy            changes that ran without a human this session, priced at AgentOS's $35-75 per exception
  POST /api/agent/run           plain-English request -> a real LLM agent runs it twice, without and with KAVACH
  GET  /api/agent/run/{id}      steps so far for both runs (poll until both are done)
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import auth
from .environment import Environment
from .gateway import Kavach
from .models import ToolCall
from .scenarios import SCENARIOS, materialize, prepare

ROOT = Path(__file__).resolve().parent
env = Environment(tempfile.mkdtemp(prefix="kavach-"))
gw = Kavach(env)
app = FastAPI(title="KAVACH guardrail", version="0.1")
_mcp_task: dict[tuple[str, str], str] = {}
_sessions: dict[tuple[str, str], tuple[str, set[str]]] = {}     # (user, session id) -> (task id, context seen)
AUTH_SECRET = os.environ.get(auth.SECRET_ENV)     # unset = dev mode (role from the request, receipts say so)


def caller(authorization: str | None = Header(None)) -> dict | None:
    """Verified {sub, role} when auth is on; None in dev mode."""
    if not AUTH_SECRET:
        return None
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "missing bearer token")
    try:
        return auth.verify(authorization[len("Bearer "):], AUTH_SECRET)
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid token: {e}")


def _identity(who: dict | None, user: str, role: str) -> tuple[str, str, bool]:
    return (who["sub"], who["role"], True) if who else (user, role, False)


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
    session_id: str | None = None   # same id across calls = one task: provenance, harm budget and denials add up
    tool_description: str = ""      # for a tool KAVACH doesn't know: its MCP description, schema and annotations
    tool_schema: dict | None = None
    tool_annotations: dict | None = None


class AgentRunIn(BaseModel):
    request: str
    role: str = "analyst"


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
def check(body: CheckIn, who: dict | None = Depends(caller)):
    user, role, authed = _identity(who, body.user_id, body.role)
    key = (user, body.session_id) if body.session_id else None
    if key in _sessions:
        tid, seen = _sessions[key]
        gw.add_request(tid, body.user_request)
    else:
        tid, _ = gw.start_task(user, role, body.user_request, body.env, authenticated=authed)
        seen: set[str] = set()
        if key:
            _sessions[key] = (tid, seen)
    for c in body.context:
        h = hashlib.sha256(json.dumps(c, sort_keys=True, default=str).encode()).hexdigest()
        spec = gw.registry.get(c.get("tool", ""))
        if spec and h not in seen:                   # a session resends its history; count each output once
            seen.add(h)
            gw.tasks[tid].prov.register_output(c["tool"], c.get("output"), spec.output_trust, spec.output_conf)
    if gw.registry.get(body.tool) is None and body.tool_annotations is not None:
        gw.registry.add_draft(body.tool, body.tool_description, body.tool_schema, body.tool_annotations, body.args)
    d = gw.check(tid, ToolCall(body.tool, body.args, tool_def_hash=body.tool_def_hash))
    if body.execute:
        gw.execute(tid, d)
    return {"task_id": tid, **d.to_dict(), "explanation": d.explanation}


@app.post("/api/v1/plan")
def plan(body: PlanIn, who: dict | None = Depends(caller)):
    user, role, authed = _identity(who, body.user_id, body.role)
    _, report = gw.start_task(user, role, body.user_request, plan=body.plan, authenticated=authed)
    return report


@app.get("/api/scenarios")
def scenarios():
    return [{"id": k, "title": v["title"], "request": v["request"], "user": v["user"]} for k, v in SCENARIOS.items()]


@app.post("/api/demo/{name}", dependencies=[Depends(caller)])
def demo(name: str, reset: bool = True):
    sc = SCENARIOS.get(name)
    if sc is None:
        raise HTTPException(404, "unknown scenario")
    if reset:
        prepare(env, sc)
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
            "state": {"tables": env.table_counts(), "outbox": len(env.outbox), "ledger": len(env.ledger),
                      "waiting": sum(h["status"] == "held" for h in env.holds)}}


@app.get("/api/hitl", dependencies=[Depends(caller)])
def hitl_pending():
    return gw.hitl.pending()


@app.post("/api/hitl/{hid}")
def hitl_resolve(hid: str, body: HitlIn, who: dict | None = Depends(caller)):
    approver = who["sub"] if who else body.approver     # four-eyes needs a verified approver identity
    try:
        return gw.resolve_hitl(hid, approver, body.approve, body.mode)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(409, str(e))


@app.post("/api/undo/{rid}", dependencies=[Depends(caller)])
def undo(rid: str):
    return gw.undo_action(rid)


@app.post("/api/settle", dependencies=[Depends(caller)])
def settle(advance_s: float = 0.0):
    """Held payments and queued emails whose window has passed go out; advance_s fast-forwards for the demo."""
    return {"settled": env.settle_due(time.time() + max(0.0, advance_s))}


@app.get("/api/receipts", dependencies=[Depends(caller)])
def receipts(limit: int = 50):
    return gw.receipts.items[-limit:]


@app.get("/api/receipts/verify")
def verify():
    return gw.receipts.verify()


@app.get("/api/tools/drafts", dependencies=[Depends(caller)])
def tool_drafts():
    """Tools onboarded from their MCP annotations that a human hasn't approved yet (calls to them escalate)."""
    return [{"name": n, "description": gw.registry.specs[n].description,
             "annotations": gw.registry.specs[n].mcp_annotations()} for n in sorted(gw.registry.drafts)]


@app.post("/api/tools/{name}/approve")
def approve_tool(name: str, who: dict | None = Depends(caller)):
    if who and who["role"] != "admin":
        raise HTTPException(403, "only an admin can approve a tool")
    if not gw.registry.approve(name):
        raise HTTPException(404, f"no draft tool '{name}'")
    return {"approved": name, "definitionHash": gw.registry.pins[name]}


@app.get("/api/state", dependencies=[Depends(caller)])
def state():
    parked = [dict(r) for r in env.db.execute("SELECT * FROM sap_documents WHERE status = 'parked'")]
    return {"tables": env.table_counts(), "outbox": env.outbox[-5:], "ledger": env.ledger[-5:],
            "waiting": [h for h in env.holds if h["status"] == "held"], "parked": parked, "drafts": env.drafts[-5:],
            "risk_model": gw.risk.source, "c_block": gw.cfg.c_block, "policy": gw.policy.version,
            "qualcomm_llm": gw.judge.llm.enabled, "judge_models": list(gw.judge.llm.picked or [gw.judge.llm.model])}


# ---------------------------------------------------------------- type a request: a real agent, without and with KAVACH
_agent_runs: dict[str, dict] = {}
_agent_slots = threading.Semaphore(2)        # one request = two runs side by side; a second request waits its turn
AGENT_ROLES = ("analyst", "support", "finance", "ap_supervisor")


def _agent_worker(slot: dict, request: str, guard: bool, role: str) -> None:
    from agent import llm_agent
    with _agent_slots:
        try:
            out = llm_agent.run(request, guard=guard, role=role, trace=slot["trace"])
            slot["outcome"] = {"emails_out": [{"to": m["to"], "subject": m["subject"], "chars": len(m["body"])}
                                              for m in out["external_emails_sent"]],
                               "payments": out["payments"], "waiting": len(out["waiting_held_or_queued"]),
                               "model": out["model"]}
        except (Exception, SystemExit) as e:          # SystemExit: run() exits when the model isn't configured
            slot["error"] = f"{type(e).__name__}: {e}"
        finally:
            slot["done"] = True


@app.post("/api/agent/run")
def agent_run(body: AgentRunIn, who: dict | None = Depends(caller)):
    """A real LLM agent (Qualcomm Cloud AI) works on any plain-English request, once without KAVACH and once with it,
    each on its own fresh copy of the demo company. Needs the Qualcomm key in the server's environment."""
    from agent import llm_agent
    if not llm_agent.QualcommCloudAI().enabled:
        raise HTTPException(503, "No Qualcomm key: start the server with --env-file pointing at a file with "
                                 "INFERENCE_CLOUD_API_KEY and INFERENCE_CLOUD_ENDPOINT.")
    request = body.request.strip()[:2000]
    if not request:
        raise HTTPException(400, "Type a request first.")
    _, role, _ = _identity(who, "web-user", body.role if body.role in AGENT_ROLES else "analyst")
    rid = uuid.uuid4().hex[:10]
    runs = {"request": request, "role": role, "started": time.time(),
            "unguarded": {"trace": [], "done": False}, "guarded": {"trace": [], "done": False}}
    while len(_agent_runs) >= 20:                     # keep the last 20 requests
        _agent_runs.pop(next(iter(_agent_runs)))
    _agent_runs[rid] = runs
    for guard in (False, True):
        threading.Thread(target=_agent_worker, args=(runs["guarded" if guard else "unguarded"], request, guard, role),
                         daemon=True).start()
    return {"run_id": rid, "role": role}


@app.get("/api/agent/run/{rid}", dependencies=[Depends(caller)])
def agent_run_status(rid: str):
    runs = _agent_runs.get(rid)
    if runs is None:
        raise HTTPException(404, "unknown run")
    view = lambda r: {**{k: v for k, v in r.items() if k != "trace"}, "trace": list(r["trace"])}  # noqa: E731
    return {"request": runs["request"], "role": runs["role"], "seconds": round(time.time() - runs["started"]),
            "unguarded": view(runs["unguarded"]), "guarded": view(runs["guarded"])}


@app.get("/api/autonomy", dependencies=[Depends(caller)])
def autonomy():
    """Changes that ran without a human click in this session, priced the way AgentOS prices a human exception."""
    reads = {n for n, t in gw.registry.specs.items() if t.effect in ("read", "ingress")}
    ds = [r["body"]["decision"] for r in gw.receipts.items if r["body"].get("type") == "decision"]
    changes = [d for d in ds if d["call"]["tool"] not in reads]
    alone = sum(d["verdict"].startswith("ALLOW") for d in changes)
    return {"changes": len(changes), "without_a_human": alone,
            "to_a_human": sum(d["verdict"] == "ESCALATE" for d in changes),
            "blocked": sum(d["verdict"] == "DENY" for d in changes),
            "reviews_avoided_usd": [35 * alone, 75 * alone],
            "basis": "compared with a person approving every change; AgentOS prices a human exception at $35-75 "
                     "(cost_per_exception)"}


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
def mcp(rpc: dict, who: dict | None = Depends(caller)):
    """Minimal MCP JSON-RPC: initialize, tools/list, tools/call. Every tools/call goes through the gateway.
    The user's request is passed once via params._meta['kavach/userRequest'] (session-scoped)."""
    mid, method, params = rpc.get("id"), rpc.get("method"), rpc.get("params", {}) or {}
    meta = params.get("_meta", {}) or {}
    session = (who["sub"] if who else "", meta.get("kavach/session", "default"))   # a caller can't reuse another's session
    if method == "initialize":
        user, role, authed = _identity(who, meta.get("kavach/user", "mcp-user"), meta.get("kavach/role", "support"))
        tid, _ = gw.start_task(user, role, meta.get("kavach/userRequest", ""), meta.get("kavach/env", "prod"),
                               authenticated=authed)
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
