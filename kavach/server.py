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
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import time
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import auth
from .environment import Environment
from .gateway import Kavach
from .models import ToolCall
from .policy import PolicyEngine
from .profile import check_profile
from .scenarios import SCENARIOS, materialize, prepare

ROOT = Path(__file__).resolve().parent
PROFILE = check_profile()           # KAVACH_PROFILE=prod refuses to start without real secrets (A9)
# canary records (R28) are planted in the server's world unless KAVACH_CANARIES=0
_canaries = None if os.environ.get("KAVACH_CANARIES") == "0" else PolicyEngine().cfg.get("canaries")
env = Environment(tempfile.mkdtemp(prefix="kavach-"), canaries=_canaries)
gw = Kavach(env)
if PROFILE.require_tool_hash:
    gw.policy.cfg["require_tool_hash"] = True
if os.environ.get("KAVACH_MANIFESTS"):             # E3: more tools, e.g. kavach/manifests/claude_code.yaml
    from .manifest import register_manifests
    register_manifests(gw.registry, gw.policy.cfg["roles"],
                       [p.strip() for p in os.environ["KAVACH_MANIFESTS"].split(",") if p.strip()])
if os.environ.get("KAVACH_PROBE") == "1":          # C3: scan untrusted content with the CPU classifier
    from .injection_probe import InjectionProbe
    _probe = InjectionProbe()
    gw.probe = _probe if _probe.enabled else None
app = FastAPI(title="KAVACH guardrail", version="0.1")
# A separate UI (another port or host) may call the API. Dev profile: any localhost port. Prod: only the origins in
# KAVACH_CORS_ORIGINS (comma-separated). Tokens travel in the Authorization header, so no cookies are allowed.
_origins = [o.strip() for o in os.environ.get("KAVACH_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_origins,
                   allow_origin_regex=None if PROFILE.prod else r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
                   allow_methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Authorization", "Content-Type"],
                   allow_credentials=False)
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


class PlanIn(BaseModel):
    user_request: str
    plan: list[dict]
    user_id: str = "demo-user"
    role: str = "support"


class HitlIn(BaseModel):
    approve: bool
    approver: str = "reviewer-1"
    approver_role: str | None = None    # dev mode only; with auth on, the role comes from the token
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
            gw.register_output(tid, ToolCall(c["tool"], c.get("args") or {}), c.get("output"))
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
    if sc is None or not PROFILE.demo_endpoints:
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


class KillIn(BaseModel):
    scope: str = "global"            # global | user | role | task
    target: str | None = None
    reason: str = ""


def _operator(who: dict | None) -> str:
    """Pausing and resuming agents is for admins (when auth is on)."""
    if who is not None and who["role"] != "admin":
        raise HTTPException(403, "only an admin can pause or resume agents")
    return who["sub"] if who else "operator"


@app.post("/api/kill")
def kill(body: KillIn, who: dict | None = Depends(caller)):
    """Kill switch: pause everything, one user, one role or one task, now."""
    try:
        return gw.kill(body.scope, body.target, _operator(who), body.reason)
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.get("/api/kill", dependencies=[Depends(caller)])
def kills():
    return list(gw.kills.values())


@app.delete("/api/kill/{kill_id}")
def resume(kill_id: str, who: dict | None = Depends(caller)):
    try:
        return gw.resume(kill_id, _operator(who))
    except KeyError as e:
        raise HTTPException(404, str(e))


@app.get("/api/tasks", dependencies=[Depends(caller)])
def tasks(limit: int = 50):
    """Recent sessions (newest first) with their Rule-of-Two legs, for a session list in a UI."""
    ids = list(gw.tasks)[-max(1, limit):][::-1]
    return [{k: v for k, v in gw.task_summary(t).items() if k != "receipts"} for t in ids]


@app.get("/api/tasks/{task_id}", dependencies=[Depends(caller)])
def task(task_id: str):
    """One session: request, principal, Rule-of-Two meter, harm budget, denials, hostile sources, every receipt."""
    if task_id not in gw.tasks:
        raise HTTPException(404, f"no task {task_id}")
    return gw.task_summary(task_id)


@app.get("/api/hitl", dependencies=[Depends(caller)])
def hitl_pending():
    return gw.hitl.pending()


@app.post("/api/hitl/{hid}")
def hitl_resolve(hid: str, body: HitlIn, who: dict | None = Depends(caller)):
    approver = who["sub"] if who else body.approver     # four-eyes needs a verified approver identity
    role = who["role"] if who else body.approver_role   # and quorum a verified role (N4)
    try:
        return gw.resolve_hitl(hid, approver, body.approve, body.mode, approver_role=role)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except (ValueError, KeyError) as e:
        raise HTTPException(409, str(e))


@app.post("/api/undo/{rid}", dependencies=[Depends(caller)])
def undo(rid: str):
    return gw.undo_action(rid)


@app.post("/api/settle")
def settle(advance_s: float = 0.0, who: dict | None = Depends(caller)):
    """Held payments and queued emails whose window has passed go out. advance_s fast-forwards the clock for the
    demo: dev profile only, and only for an admin when auth is on (N8); otherwise the hold can't be skipped."""
    if advance_s > 0 and (not PROFILE.fast_forward or (who is not None and who["role"] != "admin")):
        raise HTTPException(403, "only an admin, in the dev profile, can fast-forward holds")
    return {"settled": env.settle_due(time.time() + max(0.0, advance_s))}


@app.get("/api/receipts", dependencies=[Depends(caller)])
def receipts(limit: int = 50, after: int | None = None):
    """The last `limit` receipts, or (for polling UIs) every receipt with seq > `after`, oldest first."""
    if after is not None:
        return gw.receipts.items[max(0, after):][:max(1, limit)]
    return gw.receipts.items[-limit:]


@app.get("/api/events", dependencies=[Depends(caller)])
async def events(after: int = 0, max_s: float = 300.0):
    """Server-Sent Events: every receipt as it is written (decisions, executions, approvals, undos, kills).
    `id` is the receipt seq, so a reconnecting client resumes with ?after=<last id>. Browsers' EventSource can't
    send an Authorization header: with auth on, read the stream with fetch() (e.g. @microsoft/fetch-event-source)."""
    async def stream():
        seq, until = max(0, after), time.time() + max(0.0, min(max_s, 3600.0))
        yield "retry: 2000\n\n"
        while True:
            for r in gw.receipts.items[seq:]:
                seq = r["seq"]
                yield f"id: {seq}\nevent: {r['body'].get('type', 'receipt')}\ndata: {json.dumps(r, default=str)}\n\n"
            if time.time() >= until:
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/receipts/verify")
def verify():
    return gw.receipts.verify()


@app.get("/api/receipts/export", dependencies=[Depends(caller)])
def receipts_export():
    """The whole chain as JSONL (a header with the public key, then every receipt), for an auditor:
    python -m kavach.receipts verify export.jsonl --pubkey kavach_signing.pub.pem"""
    return StreamingResponse(gw.receipts.export_lines(), media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=kavach-receipts.jsonl"})


@app.get("/api/receipts/public-key")
def receipts_public_key():
    s = gw.receipts.signer
    return {"kid": s.key_id if s else None, "public_key": s.public_pem if s else None,
            "ephemeral": bool(s and s.ephemeral)}


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
