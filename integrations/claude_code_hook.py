#!/usr/bin/env python3
"""KAVACH as a Claude Code hook (stdlib only). One script for three hook events:

    UserPromptSubmit  remember the user's prompt (the trusted request for provenance and intent)
    PostToolUse       remember what each tool returned (labelled for provenance)
    PreToolUse        ask KAVACH: DENY -> "deny" (the reason goes back to Claude), ESCALATE -> "ask" (you decide,
                      with KAVACH's reason shown), ALLOW -> no opinion (your own permission settings still apply)

Start a KAVACH server that knows Claude Code's tools:
    KAVACH_MANIFESTS=kavach/manifests/claude_code.yaml python -m uvicorn kavach.server:app --port 8000

.claude/settings.json (project) or ~/.claude/settings.json (user):
    {"hooks": {
      "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 /path/to/integrations/claude_code_hook.py"}]}],
      "PreToolUse":  [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 /path/to/integrations/claude_code_hook.py"}]}],
      "PostToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": "python3 /path/to/integrations/claude_code_hook.py"}]}]}}

Options (arguments or environment): --url / KAVACH_URL (default http://localhost:8000), --role / KAVACH_ROLE
(default claude_code), KAVACH_TOKEN (bearer token when KAVACH runs with auth), --on-error ask|deny (default ask:
if KAVACH can't be reached you are asked, never silently allowed).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import os
import sys
import tempfile
import urllib.request
from pathlib import Path

STATE = Path(os.environ.get("KAVACH_HOOK_STATE", Path(tempfile.gettempdir()) / "kavach-claude-code"))
MAX_OUTPUT = 20000           # characters of each tool output kept for provenance


def _state(session: str) -> Path:
    return STATE / f"{hashlib.sha256(session.encode()).hexdigest()[:16]}.json"


def load(session: str) -> dict:
    p = _state(session)
    return json.loads(p.read_text()) if p.exists() else {"prompt": "", "context": []}


def save(session: str, st: dict) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    _state(session).write_text(json.dumps(st))


def decide(event: dict, opts) -> dict:
    st = load(event.get("session_id", "default"))
    body = {"user_request": st["prompt"], "tool": event["tool_name"], "args": event.get("tool_input") or {},
            "user_id": os.environ.get("USER", "claude-code-user"), "role": opts.role, "env": "prod",
            "session_id": event.get("session_id"), "context": st["context"], "tool_annotations": {}}
    headers = {"Content-Type": "application/json"}
    if os.environ.get("KAVACH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["KAVACH_TOKEN"]
    req = urllib.request.Request(f"{opts.url.rstrip('/')}/api/v1/check", data=json.dumps(body, default=str).encode(),
                                 headers=headers)
    with urllib.request.urlopen(req, timeout=opts.timeout) as r:
        return json.loads(r.read())


def state_request(prompt: str, conversation: str, opts) -> None:
    """--mcp: Claude uses KAVACH's own tools at <url>/mcp, which can't see what you typed. This hook, on your side
    and not the model's, hands each prompt to KAVACH (the session Claude's calls use). Prompts from the same Claude
    Code conversation add up, so an address you typed two messages ago still counts as yours."""
    headers = {"Content-Type": "application/json"}
    if os.environ.get("KAVACH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["KAVACH_TOKEN"]
    meta = {"kavach/userRequest": prompt, "kavach/user": os.environ.get("KAVACH_USER", os.environ.get("USER", "")),
            "kavach/role": opts.role, "kavach/conversation": conversation}
    body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"_meta": meta}}
    req = urllib.request.Request(f"{opts.url.rstrip('/')}/mcp", data=json.dumps(body).encode(), headers=headers)
    urllib.request.urlopen(req, timeout=opts.timeout).read()   # if it fails, Claude's calls run with no request:
                                                                # KAVACH then asks a person (R40), never allows more


def handle(event: dict, opts) -> dict:
    name = event.get("hook_event_name")
    session = event.get("session_id", "default")
    if name == "UserPromptSubmit":
        st = load(session)
        # Claude Code wraps pasted text in <pasted_content id="..."> tags: what was pasted is what the user said
        st["prompt"] = re.sub(r"</?pasted_content[^>]*>", "", event.get("prompt", "")).strip()
        save(session, st)
        if opts.mcp:
            state_request(st["prompt"], session, opts)
        return {}
    if name == "PostToolUse":
        st = load(session)
        out = event.get("tool_response")
        out = out if isinstance(out, (dict, list)) else str(out)[:MAX_OUTPUT]
        st["context"].append({"tool": event.get("tool_name"), "args": event.get("tool_input") or {}, "output": out})
        save(session, st)
        return {}
    if name == "PreToolUse":
        try:
            d = decide(event, opts)
        except Exception as e:  # fail safe: never a silent allow
            return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": opts.on_error,
                                           "permissionDecisionReason": f"KAVACH unreachable ({type(e).__name__}); "
                                                                       "a person decides."}}
        verdict = d.get("verdict", "DENY")
        if verdict.startswith("ALLOW"):
            return {}
        reason = d.get("reason", "") + (f" Suggested instead: {d['replan_hint']}" if d.get("replan_hint") else "")
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "permissionDecision": "deny" if verdict == "DENY" else "ask",
                                       "permissionDecisionReason": f"KAVACH {verdict}: {reason} "
                                                                   f"(receipt {d.get('receipt_id')})"}}
    return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="KAVACH hook for Claude Code")
    ap.add_argument("--url", default=os.environ.get("KAVACH_URL", "http://localhost:8000"))
    ap.add_argument("--role", default=os.environ.get("KAVACH_ROLE", "claude_code"))
    ap.add_argument("--on-error", choices=("ask", "deny"), default=os.environ.get("KAVACH_ON_ERROR", "ask"))
    ap.add_argument("--timeout", type=float, default=8.0)
    ap.add_argument("--mcp", action="store_true", help="also state each prompt to KAVACH's /mcp (Claude uses "
                                                       "KAVACH's own tools there; see integrations/claude_demo/)")
    opts = ap.parse_args(argv)
    out = handle(json.loads(sys.stdin.read() or "{}"), opts)
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
