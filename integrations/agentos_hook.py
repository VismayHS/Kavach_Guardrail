#!/usr/bin/env python3
"""KAVACH as a Topaz AgentOS hook (Infosys Agentic Foundry, Topaz_AgentOS/).

AgentOS runs hook scripts before and after every tool call, as argv without a shell, and passes the call in
environment variables (IAF_QUERY, IAF_TOOL_NAME, IAF_TOOL_INPUT, IAF_TOOL_OUTPUT, IAF_SESSION_ID, IAF_USER_ID).
It passes ONLY those and a few system variables (PATH, HOME, ...), so KAVACH's own settings come as arguments.
A non-zero exit blocks the call; the hook's `on_block` decides whether that is a deny or a human approval.

    agentos_hook.py record                       # PostToolUse: remember the tool output for provenance
    agentos_hook.py deny [--role R] [--url U]    # PreToolUse, on_block: deny -> exit 1 only on KAVACH DENY
    agentos_hook.py hitl [--role R] [--url U]    # PreToolUse, on_block: hitl -> exit 1 only on KAVACH ESCALATE

AgentOS only runs hook scripts that sit inside the agent's tenant tree, so copy this file to
enterprise_root/tenants/<tenant>/shared/hooks/kavach_hook.py. config.yaml (agent):

    hooks:
      PostToolUse:
        - {hook_id: kavach.record, matcher: ".*", mode: observe,
           command: "python3 $IAF_AGENT_ROOT/../../shared/hooks/kavach_hook.py record"}
      PreToolUse:
        - {hook_id: kavach.deny, matcher: ".*", mode: blocking, priority: 10, on_block: deny,
           block_on_nonzero: true, fail_policy: closed, timeout_seconds: 15,
           command: "python3 $IAF_AGENT_ROOT/../../shared/hooks/kavach_hook.py deny --role ap_supervisor"}
        - {hook_id: kavach.hitl, matcher: ".*", mode: blocking, priority: 20, on_block: hitl,
           block_on_nonzero: true, fail_policy: closed, timeout_seconds: 15,
           command: "python3 $IAF_AGENT_ROOT/../../shared/hooks/kavach_hook.py hitl --role ap_supervisor"}

fail_policy must be closed (AgentOS defaults hooks to open). The two PreToolUse hooks share one KAVACH decision:
the first stores it, the second reuses it, so each tool call is checked once. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

STATE = Path(os.environ.get("KAVACH_HOOK_STATE", Path(tempfile.gettempdir()) / "kavach-agentos"))
SQL_WRITE = re.compile(r"^\s*(UPDATE|DELETE|INSERT|DROP|ALTER|TRUNCATE|CREATE)\b", re.I)
RELEASE = re.compile(r"/payments/release\b")
BANK = re.compile(r"/vendors/([A-Za-z0-9_-]+)/bank_details\b")
INVOICE_URL = re.compile(r"/invoices/(INV-\d+)\b")
INVOICE_ID = re.compile(r"\bINV-\d+\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b")
WRITES = re.compile(r"\s-X\s*(POST|PUT|PATCH)\b|\s(-d|--data\S*)\s", re.I)
REUSE_S = 120          # how long the deny hook's decision is valid for the hitl hook


def to_kavach(tool: str, args: dict) -> tuple[str, dict]:
    """AgentOS tool shapes -> KAVACH manifest tools. Unknown tools pass through (KAVACH escalates them as drafts)."""
    if tool in ("run_sql", "run_sql_query", "execute_sql", "sql"):
        sql = args.get("query") or args.get("sql") or args.get("statement") or ""
        return ("crm.execute" if SQL_WRITE.match(sql) else "crm.query"), {"sql": sql}
    if tool == "write_file":
        return "files.write", {"path": str(args.get("path", "")).replace("/workspace/", ""),
                               "content": args.get("content", "")}
    if tool == "shell":
        cmd = str(args.get("command", ""))
        # their finance API (docs/SECURITY_TESTING_GUIDE.md): the amount and payee come from KAVACH's invoice record
        if RELEASE.search(cmd) and (m := INVOICE_ID.search(cmd)):
            return "payment.release", {"invoice_id": m.group(0)}
        if (b := BANK.search(cmd)) and WRITES.search(cmd) and (i := IBAN.search(cmd.split(b.group(0), 1)[1])):
            return "vendor.update_bank", {"vendor_id": b.group(1), "iban": i.group(0).replace(" ", "")}
        if (v := INVOICE_URL.search(cmd)) and not WRITES.search(cmd):
            return "invoice.read", {"invoice_id": v.group(1)}
        m = re.match(r"^\s*(cat|rm)\s+(?:-\w+\s+)*(\S+)\s*$", cmd)
        if m:
            path = m.group(2).replace("/workspace/", "")
            return ("files.read" if m.group(1) == "cat" else "files.delete"), {"path": path}
    return tool, args


def _session() -> str:
    return hashlib.sha256((os.environ.get("IAF_SESSION_ID") or "default").encode()).hexdigest()[:16]


def _env_json(name: str) -> dict:
    try:
        v = json.loads(os.environ.get(name) or "{}")
        return v if isinstance(v, dict) else {}
    except json.JSONDecodeError:
        return {}


def record() -> int:
    tool, _ = to_kavach(os.environ.get("IAF_TOOL_NAME", ""), _env_json("IAF_TOOL_INPUT"))
    raw = os.environ.get("IAF_TOOL_OUTPUT", "")
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = raw
    STATE.mkdir(parents=True, exist_ok=True)
    with (STATE / f"{_session()}.jsonl").open("a") as f:
        f.write(json.dumps({"tool": tool, "output": out}) + "\n")
    return 0


def check(opts: argparse.Namespace) -> dict:
    tool, args = to_kavach(os.environ.get("IAF_TOOL_NAME", ""), _env_json("IAF_TOOL_INPUT"))
    query = os.environ.get("IAF_QUERY", "")
    key = hashlib.sha256(json.dumps([_session(), tool, args, query], sort_keys=True, default=str).encode()).hexdigest()
    cached = STATE / f"decision-{key[:24]}.json"
    if cached.exists() and time.time() - cached.stat().st_mtime < REUSE_S:
        return json.loads(cached.read_text())          # the other PreToolUse hook already asked KAVACH
    sf = STATE / f"{_session()}.jsonl"
    context = [json.loads(line) for line in sf.read_text().splitlines()] if sf.exists() else []
    body = {"user_request": query, "tool": tool, "args": args,
            "user_id": os.environ.get("IAF_USER_ID") or "agentos-user", "role": opts.role, "env": opts.env,
            "context": context, "session_id": os.environ.get("IAF_SESSION_ID") or None,
            "tool_annotations": {}}   # a tool KAVACH doesn't know becomes a cautious draft: escalate, not deny
    headers = {"Content-Type": "application/json"}
    if os.environ.get("KAVACH_TOKEN"):           # when KAVACH runs with auth, the role comes from this token
        headers["Authorization"] = "Bearer " + os.environ["KAVACH_TOKEN"]
    req = urllib.request.Request(f"{opts.url}/api/v1/check", data=json.dumps(body).encode(), headers=headers)
    with urllib.request.urlopen(req, timeout=opts.timeout) as r:
        d = json.loads(r.read())
    STATE.mkdir(parents=True, exist_ok=True)
    cached.write_text(json.dumps({k: d.get(k) for k in ("verdict", "reason", "explanation", "receipt_id", "task_id")}))
    return d


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description="KAVACH hook for Topaz AgentOS")
    ap.add_argument("mode", nargs="?", default="deny", choices=("record", "deny", "hitl"))
    ap.add_argument("--role", default=os.environ.get("KAVACH_ROLE", "support"))
    ap.add_argument("--url", default=os.environ.get("KAVACH_URL", "http://localhost:8000"))
    ap.add_argument("--env", default=os.environ.get("KAVACH_ENV", "prod"))
    ap.add_argument("--timeout", type=float, default=9.0)    # the Qualcomm judge can take a few seconds
    opts = ap.parse_args(argv)
    if opts.mode == "record":
        return record()
    d = check(opts)                             # any exception -> non-zero exit -> fail_policy: closed
    verdict = d.get("verdict", "DENY")
    blocks = verdict == "DENY" if opts.mode == "deny" else verdict == "ESCALATE"
    if blocks:
        print(json.dumps({"blocked": True, "reason": f"KAVACH {verdict}: {d.get('explanation') or d.get('reason')}",
                          "receipt": d.get("receipt_id")}))
        return 1
    print(json.dumps({"blocked": False, "message": f"KAVACH {verdict} ({d.get('receipt_id')})"}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
