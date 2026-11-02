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
  GET  /api/policy              the rulebook: rules, roles, limits, tools
  POST /api/agent/run           plain-English request -> a real LLM agent runs it twice, without and with KAVACH
  GET  /api/agent/run/{id}      steps so far for both runs (poll until both are done)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
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
# F6: OpenTelemetry spans (standard OTEL_EXPORTER_OTLP_ENDPOINT) and SIEM forwarding (KAVACH_SIEM_KIND/URL/TOKEN)
try:
    from .telemetry import SiemForwarder, setup_tracing
    _tracing = setup_tracing()
    if _tracing is not None:
        gw.receipts.listeners.append(_tracing)
    if os.environ.get("KAVACH_SIEM_URL"):
        gw.receipts.listeners.append(SiemForwarder(os.environ.get("KAVACH_SIEM_KIND", "webhook"),
                                                   os.environ["KAVACH_SIEM_URL"], os.environ.get("KAVACH_SIEM_TOKEN")))
except ImportError:
    pass
if os.environ.get("KAVACH_SLACK_WEBHOOK") or os.environ.get("KAVACH_TEAMS_WEBHOOK"):   # F8: approval cards
    from .notify import ApprovalNotifier
    gw.receipts.listeners.append(ApprovalNotifier(gw, os.environ.get("KAVACH_SLACK_WEBHOOK"),
                                                  os.environ.get("KAVACH_TEAMS_WEBHOOK"),
                                                  os.environ.get("KAVACH_CONSOLE_URL", "")))
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


def _tenant_of(who: dict | None) -> str:
    return (who or {}).get("tenant", "default")


def _sees(who: dict | None, tenant: str | None) -> bool:
    """F10 tenant isolation: with auth on, a caller sees only its own tenant (admin sees all); dev mode sees all."""
    return who is None or who.get("role") == "admin" or (tenant or "default") == _tenant_of(who)


def _task_tenant(task_id: str | None) -> str | None:
    t = gw.tasks.get(task_id) if task_id else None
    return t.ctx.principal.tenant if t else None


def _rec_tenant(rec: dict) -> str | None:
    b = rec["body"]
    return b.get("tenant") or _task_tenant(b.get("task_id"))


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
    task_id: str | None = None      # F2: an existing task (e.g. a delegated agent's) to check this call in
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
    approver_role: str | None = None    # dev mode only; with auth on, the role comes from the token
    mode: str = "execute"


class _Static(StaticFiles):
    async def get_response(self, path, scope):
        r = await super().get_response(path, scope)
        r.headers["Cache-Control"] = "no-cache"        # a pulled update shows on the next reload
        return r


app.mount("/static", _Static(directory=ROOT / "static"))


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html", headers={"Cache-Control": "no-cache"})


@app.post("/api/v1/check")
def check(body: CheckIn, who: dict | None = Depends(caller)):
    user, role, authed = _identity(who, body.user_id, body.role)
    key = (user, body.session_id) if body.session_id else None
    if body.task_id:
        if body.task_id not in gw.tasks or not _sees(who, _task_tenant(body.task_id)):
            raise HTTPException(404, f"no task {body.task_id}")
        tid, seen = body.task_id, set()
    elif key in _sessions:
        tid, seen = _sessions[key]
        gw.add_request(tid, body.user_request)
    else:
        tid, _ = gw.start_task(user, role, body.user_request, body.env, authenticated=authed, tenant=_tenant_of(who))
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
    _, report = gw.start_task(user, role, body.user_request, plan=body.plan, authenticated=authed,
                              tenant=_tenant_of(who))
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


class ReplayIn(BaseModel):
    policy_yaml: str
    task_ids: list[str] | None = None


@app.post("/api/policy/replay")
def policy_replay(body: ReplayIn, who: dict | None = Depends(caller)):
    """F9: re-run past tasks under a draft policy and list every decision that would change."""
    if who is not None and who["role"] not in ("admin", "policy_author"):
        raise HTTPException(403, "only an admin or a policy author can replay policies")
    from .policy import PolicyEngine
    from .replay import replay
    try:
        draft = PolicyEngine.from_text(body.policy_yaml)
    except Exception as e:
        raise HTTPException(422, f"draft policy doesn't load: {e}")
    return replay(gw, draft, body.task_ids)


class DelegateIn(BaseModel):
    parent_task_id: str
    agent: str
    instruction: str
    tools: list[str] | None = None


@app.post("/api/v1/delegate")
def delegate(body: DelegateIn, who: dict | None = Depends(caller)):
    """F2: agent A hands work to agent B. Returns B's task id; send B's calls with task_id to /api/v1/check."""
    if body.parent_task_id not in gw.tasks or not _sees(who, _task_tenant(body.parent_task_id)):
        raise HTTPException(404, f"no task {body.parent_task_id}")
    child = gw.delegate(body.parent_task_id, body.agent, body.instruction, body.tools)
    return {"task_id": child, "tools": gw.tasks[child].allowed_tools}


@app.get("/.well-known/jwks.json")
def jwks():
    """KAVACH's Ed25519 public key, for tools that verify delegated agent tokens (F1)."""
    from .identity import jwks as _jwks
    if gw.receipts.signer is None:
        raise HTTPException(503, "no signing key")
    return _jwks(gw.receipts.signer)


@app.post("/oauth/token")
async def token_exchange(request: Request):
    """RFC 8693 token exchange: a user's token in, a short-lived, task-scoped delegated token for an agent out."""
    from .identity import JWT_TYPE, TOKEN_EXCHANGE, exchange
    form = dict(await request.form()) if "form" in request.headers.get("content-type", "") else await request.json()
    if form.get("grant_type") != TOKEN_EXCHANGE:
        raise HTTPException(400, "unsupported_grant_type")
    if form.get("subject_token_type", JWT_TYPE) != JWT_TYPE or not form.get("subject_token"):
        raise HTTPException(400, "invalid_request: subject_token (a KAVACH JWT) is required")
    if not AUTH_SECRET:
        raise HTTPException(400, "token exchange needs sign-in on (KAVACH_AUTH_SECRET)")
    try:
        claims = auth.verify(form["subject_token"], AUTH_SECRET)
    except jwt.PyJWTError as e:
        raise HTTPException(401, f"invalid_grant: {e}")
    try:
        return exchange(claims, gw.policy.cfg["roles"].get(claims["role"], []), form.get("scope", ""),
                        form.get("audience", ""), form.get("resource", ""), form.get("actor", "agent"),
                        min(int(form.get("expires_in", 300) or 300), 3600), gw.receipts.signer)
    except PermissionError as e:
        raise HTTPException(403, f"invalid_scope: {e}")


@app.get("/api/tasks")
def tasks(limit: int = 50, who: dict | None = Depends(caller)):
    """Recent sessions (newest first) with their Rule-of-Two legs, for a session list in a UI."""
    ids = [t for t in gw.tasks if _sees(who, _task_tenant(t))][-max(1, limit):][::-1]
    return [{k: v for k, v in gw.task_summary(t).items() if k != "receipts"} for t in ids]


@app.get("/api/tasks/{task_id}")
def task(task_id: str, who: dict | None = Depends(caller)):
    """One session: request, principal, Rule-of-Two meter, harm budget, denials, hostile sources, every receipt."""
    if task_id not in gw.tasks or not _sees(who, _task_tenant(task_id)):
        raise HTTPException(404, f"no task {task_id}")
    return gw.task_summary(task_id)


@app.get("/api/demo/fatigue")
def fatigue_game(seed: int = 7):
    """D3: fifteen approval prompts (one disguised exfiltration) and, for the reveal, KAVACH's view of each."""
    if not PROFILE.demo_endpoints:
        raise HTTPException(404, "demo endpoints are off in this profile")
    from .fatigue_demo import game
    return game(seed)


@app.get("/api/hitl")
def hitl_pending(who: dict | None = Depends(caller)):
    return [i for i in gw.hitl.pending() if _sees(who, _task_tenant(i["task_id"]))]


@app.get("/api/hitl/stats", dependencies=[Depends(caller)])
def hitl_stats():
    """Approval fatigue: per approver, decisions, approvals, median time to decide, fast approvals, approve streaks."""
    return gw.hitl.stats()


@app.post("/api/hitl/{hid}")
def hitl_resolve(hid: str, body: HitlIn, who: dict | None = Depends(caller)):
    item = gw.hitl.items.get(hid)
    if item is not None and not _sees(who, _task_tenant(item["task_id"])):
        raise HTTPException(403, "this approval belongs to another tenant")
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


@app.get("/api/receipts")
def receipts(limit: int = 50, after: int | None = None, who: dict | None = Depends(caller)):
    """The last `limit` receipts, or (for polling UIs) every receipt with seq > `after`, oldest first. With auth on, a
    caller sees its own tenant's receipts (verify the whole chain with /api/receipts/export as admin)."""
    items = gw.receipts.items[max(0, after):] if after is not None else gw.receipts.items
    mine = [r for r in items if _sees(who, _rec_tenant(r))]
    return mine[:max(1, limit)] if after is not None else mine[-limit:]


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


@app.get("/api/receipts/export")
def receipts_export(who: dict | None = Depends(caller)):
    """The whole chain as JSONL (a header with the public key, then every receipt), for an auditor:
    python -m kavach.receipts verify export.jsonl --pubkey kavach_signing.pub.pem"""
    if who is not None and who["role"] != "admin":     # the chain only verifies whole: no per-tenant exports
        raise HTTPException(403, "the export is the whole chain; ask an admin")
    return StreamingResponse(gw.receipts.export_lines(), media_type="application/x-ndjson",
                             headers={"Content-Disposition": "attachment; filename=kavach-receipts.jsonl"})


@app.get("/api/receipts/{rid}/explain", dependencies=[Depends(caller)])
def receipt_explain(rid: str, lang: str = "en"):
    """The decision on a receipt, explained for an approver (lang=en or hi)."""
    rec = gw.receipts.get(rid)
    if rec is None or rec["body"].get("type") != "decision":
        raise HTTPException(404, f"no decision receipt {rid}")
    text, source = gw.explainer.explain(rec["body"]["decision"], lang)
    return {"receipt": rid, "lang": lang, "explanation": text, "source": source}


@app.post("/api/receipts/anchor")
def receipts_anchor(method: str, url: str, who: dict | None = Depends(caller)):
    """Opt-in: anchor the chain head with an RFC 3161 timestamp authority or Sigstore Rekor (sends the head hash
    outside). Admin only when auth is on."""
    if who is not None and who["role"] != "admin":
        raise HTTPException(403, "only an admin can anchor the receipt chain")
    from .anchor import anchor_rekor, anchor_tsa
    try:
        return anchor_tsa(gw.receipts, url) if method == "tsa" else anchor_rekor(gw.receipts, url)
    except Exception as e:
        raise HTTPException(502, f"anchoring failed: {e}")


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


@app.get("/api/policy")
def policy():
    """The rulebook as the console shows it: rules, who may use which tool, limits, and the tools."""
    cfg, p = gw.policy.cfg, gw.policy
    return {"version": p.version, "rules": p.rules, "roles": cfg["roles"], "limits": cfg["limits"],
            "finance": cfg["finance"],
            "tools": [{"name": n, "description": t.description} for n, t in gw.registry.specs.items()],
            # Phase 5: which exact policy decides, whether it is signed, shadow mode and any canary candidate
            "sha256": p.sha256, "signed_by": getattr(p, "signed_by", None), "enforce": gw.cfg.enforce,
            "candidate": None if gw.candidate is None else {"version": gw.candidate.version,
                                                            "sha256": gw.candidate.sha256,
                                                            "percent": gw.cfg.candidate_percent}}


@app.get("/api/state", dependencies=[Depends(caller)])
def state():
    receipt_of = {ref: rid for rid, (epoch, ref) in gw.recall.items() if epoch == env.epoch}    # what Undo needs
    parked = [{**r, "receipt": receipt_of.get(f"SAP-{r['id']}")} for r in map(dict, env.db.execute(
        "SELECT * FROM sap_documents WHERE status = 'parked'"))]
    return {"tables": env.table_counts(), "outbox": env.outbox[-5:], "ledger": env.ledger[-5:],
            "waiting": [{**h, "receipt": receipt_of.get(h["id"])} for h in env.holds if h["status"] == "held"],
            "parked": parked, "drafts": env.drafts[-5:],
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


@app.get("/metrics")
def prometheus():
    """Prometheus metrics: decisions by tool and verdict, rule hits, check latency, approvals, holds, kills."""
    from fastapi.responses import PlainTextResponse

    from .telemetry import metrics_text
    return PlainTextResponse(metrics_text(gw), media_type="text/plain; version=0.0.4")


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
