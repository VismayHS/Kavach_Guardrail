#!/usr/bin/env python3
"""KAVACH as a Topaz AgentOS hook (Infosys Agentic Foundry, Topaz_AgentOS/).

AgentOS runs hook scripts before and after every tool call and passes the call in
environment variables (IAF_QUERY, IAF_TOOL_NAME, IAF_TOOL_INPUT, IAF_TOOL_OUTPUT,
IAF_SESSION_ID, IAF_USER_ID). A non-zero exit blocks the call; the hook's `on_block`
decides whether that block is a hard deny or a human approval in the #approvals tab.

    python3 agentos_hook.py record   # PostToolUse: remember the tool output for provenance
    python3 agentos_hook.py deny     # PreToolUse, on_block: deny -> exit 1 only on KAVACH DENY
    python3 agentos_hook.py hitl     # PreToolUse, on_block: hitl -> exit 1 only on KAVACH ESCALATE

config.yaml (agent):

    hooks:
      PostToolUse:
        - {matcher: "*", command: "python3 /shared/hooks/agentos_hook.py record", mode: observe}
      PreToolUse:
        - {matcher: "*", command: "python3 /shared/hooks/agentos_hook.py deny", mode: blocking, priority: 10,
           on_block: deny, block_on_nonzero: true, fail_policy: closed, timeout_seconds: 5}
        - {matcher: "*", command: "python3 /shared/hooks/agentos_hook.py hitl", mode: blocking, priority: 20,
           on_block: hitl, block_on_nonzero: true, fail_policy: closed, timeout_seconds: 5}

fail_policy must be set to closed: AgentOS defaults hooks to open.

KAVACH_URL defaults to http://localhost:8000. Stdlib only, so it runs in AgentOS's hook sandbox.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import urllib.request
from pathlib import Path

KAVACH_URL = os.environ.get("KAVACH_URL", "http://localhost:8000")
STATE = Path(os.environ.get("KAVACH_HOOK_STATE", Path(tempfile.gettempdir()) / "kavach-agentos"))
SQL_WRITE = re.compile(r"^\s*(UPDATE|DELETE|INSERT|DROP|ALTER|TRUNCATE|CREATE)\b", re.I)


def to_kavach(tool: str, args: dict) -> tuple[str, dict]:
    """AgentOS tool shapes -> KAVACH manifest tools. Unknown tools pass through and fail closed (R6)."""
    if tool in ("run_sql", "run_sql_query", "execute_sql", "sql"):
        sql = args.get("query") or args.get("sql") or args.get("statement") or ""
        return ("crm.execute" if SQL_WRITE.match(sql) else "crm.query"), {"sql": sql}
    if tool == "write_file":
        return "files.write", {"path": str(args.get("path", "")).replace("/workspace/", ""),
                               "content": args.get("content", "")}
    if tool == "shell":
        cmd = args.get("command", "")
        m = re.match(r"^\s*(cat|rm)\s+(?:-\w+\s+)*(\S+)\s*$", cmd)
        if m:
            path = m.group(2).replace("/workspace/", "")
            return ("files.read" if m.group(1) == "cat" else "files.delete"), {"path": path}
    return tool, args


def _session_file() -> Path:
    sid = os.environ.get("IAF_SESSION_ID") or "default"
    return STATE / (hashlib.sha256(sid.encode()).hexdigest()[:16] + ".jsonl")


def _env_json(name: str) -> dict:
    try:
        v = json.loads(os.environ.get(name) or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


def record() -> int:
    tool, args = to_kavach(os.environ.get("IAF_TOOL_NAME", ""), _env_json("IAF_TOOL_INPUT"))
    raw = os.environ.get("IAF_TOOL_OUTPUT", "")
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = raw
    STATE.mkdir(parents=True, exist_ok=True)
    with _session_file().open("a") as f:
        f.write(json.dumps({"tool": tool, "output": out}) + "\n")
    return 0


def check() -> dict:
    tool, args = to_kavach(os.environ.get("IAF_TOOL_NAME", ""), _env_json("IAF_TOOL_INPUT"))
    sf = _session_file()
    context = [json.loads(line) for line in sf.read_text().splitlines()] if sf.exists() else []
    body = {"user_request": os.environ.get("IAF_QUERY", ""), "tool": tool, "args": args,
            "user_id": os.environ.get("IAF_USER_ID") or "agentos-user",
            "role": os.environ.get("KAVACH_ROLE", "support"), "env": os.environ.get("KAVACH_ENV", "prod"),
            "context": context}
    req = urllib.request.Request(f"{KAVACH_URL}/api/v1/check", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=4) as r:
        return json.loads(r.read())


def main(mode: str) -> int:
    if mode == "record":
        return record()
    d = check()                                 # any exception -> non-zero exit -> fail_policy: closed
    verdict = d.get("verdict", "DENY")
    blocks = verdict == "DENY" if mode == "deny" else verdict == "ESCALATE"
    if blocks:
        print(json.dumps({"blocked": True, "reason": f"KAVACH {verdict}: {d.get('explanation') or d.get('reason')}",
                          "receipt": d.get("receipt_id")}))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "deny"))
