"""HTTP API + dashboard.

    uvicorn kavach.server:app --port 8000      then open http://localhost:8000

Endpoints
  POST /api/v1/check            raw action input -> decision + receipt   (the PS's "agent action input")
  POST /api/v1/session          the orchestrator opens a session: the user's request and tool outputs (agent tokens can't)
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
from .models import Conf, ToolCall
from .scenarios import SCENARIOS, materialize, prepare
from .store import Store

ROOT = Path(__file__).resolve().parent


def make_gateway() -> tuple[Kavach, Environment]:
    """In memory by default. KAVACH_STATE=<file> keeps receipts and approvals across restarts (kavach.store); then a
    real KAVACH_RECEIPT_KEY is required, since with the public default key anyone could rewrite the stored log.
    A stored log that fails verification raises TamperedLog here, so the server doesn't start on top of it."""
    environment = Environment(tempfile.mkdtemp(prefix="kavach-"))
    path = os.environ.get("KAVACH_STATE")
    if not path:
        return Kavach(environment), environment
    key = os.environ.get("KAVACH_RECEIPT_KEY", "")
    if len(key) < 32:
        raise SystemExit("KAVACH_STATE needs KAVACH_RECEIPT_KEY (32+ characters): with the default key anyone could "
                         "rewrite the stored receipt log")
    return Kavach(environment, store=Store(path), receipt_key=key.encode()), environment


gw, env = make_gateway()
app = FastAPI(title="KAVACH guardrail", version="0.1")
_mcp_task: dict[tuple[str, str], str] = {}
_sessions: dict[tuple[str, str], tuple[str, set[str]]] = {}     # (user, session id) -> (task id, context seen)
AUTH_SECRET = os.environ.get(auth.SECRET_ENV)     # unset = dev mode (role from the request, receipts say so)
# Which environment this server guards is deployment config. A caller saying "dev" would switch off the production
# rules while still acting on the same database, so the env field of a request is ignored.
SERVER_ENV = os.environ.get("KAVACH_ENV", "prod")


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
    user_request: str = ""          # an agent token leaves this out: its session holds the request
    tool: str
    args: dict
    user_id: str = "demo-user"
    role: str = "support"
    env: str = "prod"               # ignored (see SERVER_ENV); kept so existing callers don't break
    context: list[dict] = []        # earlier tool outputs: [{"tool": "...", "output": ...}] for provenance
    execute: bool = False
    tool_def_hash: str | None = None
    session_id: str | None = None   # same id across calls = one task: provenance, harm budget and denials add up
    tool_description: str = ""      # for a tool KAVACH doesn't know: its MCP description, schema and annotations
    tool_schema: dict | None = None
    tool_annotations: dict | None = None


class SessionIn(BaseModel):
    session_id: str
    user_request: str
    context: list[dict] = []
    user_id: str = "demo-user"
    role: str = "support"


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


def _session(user: str, role: str, authed: bool, session_id: str | None, request: str) -> tuple[str, set[str]]:
    key = (user, session_id) if session_id else None
    if key in _sessions:
        tid, seen = _sessions[key]
        gw.add_request(tid, request)
        return tid, seen
    tid, _ = gw.start_task(user, role, request, SERVER_ENV, authenticated=authed)
    seen: set[str] = set()
    if key:
        _sessions[key] = (tid, seen)
    return tid, seen


def _add_context(tid: str, seen: set[str], context: list[dict]) -> None:
    for c in context:
        h = hashlib.sha256(json.dumps(c, sort_keys=True, default=str).encode()).hexdigest()
        spec = gw.registry.get(c.get("tool", ""))
        if h not in seen:                            # a session resends its history; count each output once
            seen.add(h)
            # the output of a tool KAVACH has no manifest for could be anything: untrusted and private until shown not
            trust, conf = (spec.output_trust, spec.output_conf) if spec else ("untrusted", Conf.CONFIDENTIAL)
            gw.tasks[tid].prov.register_output(c.get("tool", "unknown"), c.get("output"), trust, conf)


@app.post("/api/v1/session")
def open_session(body: SessionIn, who: dict | None = Depends(caller)):
    """The orchestrator states the user's request and hands over the tool outputs so far; agent tokens can't."""
    if auth.kind_of(who) != "orchestrator":
        raise HTTPException(403, "only the orchestrator may state the user's request or supply tool outputs")
    user, role, authed = _identity(who, body.user_id, body.role)
    tid, seen = _session(user, role, authed, body.session_id, body.user_request)
    _add_context(tid, seen, body.context)
    return {"task_id": tid, "session_id": body.session_id, "outputs_seen": gw.tasks[tid].prov.n_outputs}


@app.post("/api/v1/check")
def check(body: CheckIn, who: dict | None = Depends(caller)):
    user, role, authed = _identity(who, body.user_id, body.role)
    if auth.kind_of(who) == "agent":
        # an agent checks its own calls inside a session the orchestrator opened; it can't restate the task
        if body.context or not body.session_id or (user, body.session_id) not in _sessions:
            raise HTTPException(403, "agent tokens act inside a session the orchestrator opened (POST "
                                     "/api/v1/session) and can't supply the request or tool outputs")
        tid, seen = _sessions[(user, body.session_id)]
    else:
        tid, seen = _session(user, role, authed, body.session_id, body.user_request)
        _add_context(tid, seen, body.context)
    if gw.registry.get(body.tool) is None and body.tool_annotations is not None:
        gw.registry.add_draft(body.tool, body.tool_description, body.tool_schema, body.tool_annotations, body.args)
    d = gw.check(tid, ToolCall(body.tool, body.args, tool_def_hash=body.tool_def_hash))
    if body.execute:
        gw.execute(tid, d)
    # A hold, recall window or snapshot exists only if KAVACH ran the call. outputs_seen = 0 means provenance had
    # nothing to trace: no context was sent, so "not from an email" only means no email was shown.
    return {"task_id": tid, **d.to_dict(), "explanation": d.explanation,
            "safeguard_armed": d.receipt_id in gw.undo or d.receipt_id in gw.recall,
            "outputs_seen": gw.tasks[tid].prov.n_outputs}


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
        if auth.kind_of(who) != "orchestrator":
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32001, "message":
                    "only the orchestrator may initialize a session (it states the user's request)"}}
        user, role, authed = _identity(who, meta.get("kavach/user", "mcp-user"), meta.get("kavach/role", "support"))
        tid, _ = gw.start_task(user, role, meta.get("kavach/userRequest", ""), SERVER_ENV, authenticated=authed)
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
