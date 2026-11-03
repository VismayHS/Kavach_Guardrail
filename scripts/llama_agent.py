#!/usr/bin/env python3
"""A second, real agent: Llama-3.3-70B on Qualcomm Cloud AI, working on your mail through KAVACH's /mcp, the same door
Claude Code uses. Its tools are whatever KAVACH offers (with scripts/gmail_up.sh: your real Gmail inbox and sending).
Nothing is scripted: it reads what is really in the inbox and does what it decides to do; KAVACH decides what runs.

    .venv/bin/python scripts/llama_agent.py                      chat in the terminal
    .venv/bin/python scripts/llama_agent.py -p "Summarise my latest email and do what it asks."

Careful models (Claude) often refuse an injected instruction by themselves; this one is the kind that follows it, which
is when KAVACH's decision matters. Every step shows on the console's Activity page (http://127.0.0.1:8000/#/activity).
The Qualcomm key comes from .env (INFERENCE_CLOUD_API_KEY / INFERENCE_CLOUD_ENDPOINT).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.llm_agent import REPAIR, broken_call, text_tool_calls  # noqa: E402
from kavach.qualcomm import QualcommCloudAI  # noqa: E402
from kavach.otlp_metrics import push, usage_points  # noqa: E402
from kavach.usage import METER  # noqa: E402

OTLP = os.environ.get("KAVACH_AGENT_OTLP", "http://127.0.0.1:4318")   # "" turns it off


def report_usage(agent: str) -> None:
    """This agent's own tokens and cost (tokens x the reference price table) to Grafana, through the collector, the
    way Claude Code reports Claude's. Silent if the collector isn't running."""
    if OTLP:
        push(OTLP, "llama-agent", usage_points(METER.snapshot(), agent))

SYSTEM = ("You are an email assistant with access to the user's mailbox through tools. Complete the user's request, "
          "calling tools when needed, and finish with a short answer saying what you did.")
GREY, RED, GREEN, AMBER, END = "\033[90m", "\033[91m", "\033[92m", "\033[93m", "\033[0m"


def load_settings() -> None:
    for p in (ROOT / ".env", ROOT.parent / ".env"):
        if p.exists():
            for line in p.read_text().splitlines():
                k, _, v = line.partition("=")
                if k.strip() in ("INFERENCE_CLOUD_API_KEY", "INFERENCE_CLOUD_ENDPOINT", "IMAGINE_API_KEY",
                                 "IMAGINE_API_ENDPOINT", "KAVACH_AGENT_MODEL") and v.strip():
                    os.environ.setdefault(k.strip(), v.strip().strip("'\""))


class Kavach:
    """KAVACH's /mcp, spoken plainly (JSON-RPC over HTTP, as Claude Code's MCP client does)."""

    def __init__(self, url: str, user: str, role: str):
        self.url, self.user, self.role = url.rstrip("/") + "/mcp", user, role
        self.session, self.conversation = f"llama-{uuid.uuid4().hex[:8]}", f"llama-conv-{uuid.uuid4().hex[:8]}"

    def rpc(self, method: str, params: dict) -> dict:
        params = {**params, "_meta": {**params.get("_meta", {}), "kavach/session": self.session}}
        body = json.dumps({"jsonrpc": "2.0", "id": uuid.uuid4().hex[:6], "method": method, "params": params}).encode()
        req = urllib.request.Request(self.url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())

    def said(self, prompt: str) -> None:
        """What the user typed is the trusted request (the host states it, as Claude Code's hook does)."""
        self.rpc("initialize", {"_meta": {"kavach/userRequest": prompt, "kavach/user": self.user,
                                          "kavach/role": self.role, "kavach/conversation": self.conversation}})

    def tools(self) -> list[dict]:
        out = []
        for t in self.rpc("tools/list", {})["result"]["tools"]:
            out.append({"type": "function", "function": {"name": t["name"].replace(".", "__"),
                        "description": t["description"], "parameters": t["inputSchema"]}})
        return out

    def call(self, name: str, args: dict) -> tuple[str, str, str]:
        r = self.rpc("tools/call", {"name": name, "arguments": args})
        if "error" in r:
            return "ERROR", r["error"]["message"], ""
        res = r["result"]
        return res["_meta"].get("kavach/verdict", "?"), res["content"][0]["text"], res["_meta"].get("kavach/correlation", "")


def coerce(args: dict, schema: dict) -> dict:
    """Llama on the Inference Cloud sends booleans and numbers as strings ("true"); give them their declared types."""
    props, out = (schema or {}).get("properties", {}), dict(args)
    for k, v in args.items():
        t = (props.get(k) or {}).get("type")
        if isinstance(v, str) and t == "boolean" and v.lower() in ("true", "false"):
            out[k] = v.lower() == "true"
        elif isinstance(v, str) and t in ("integer", "number"):
            try:
                out[k] = int(v) if t == "integer" else float(v)
            except ValueError:
                pass
    return out


def turn(llm: QualcommCloudAI, kv: Kavach, tools: list[dict], msgs: list[dict], prompt: str, steps: int = 8) -> str:
    kv.said(prompt)
    msgs.append({"role": "user", "content": prompt})
    schemas = {t["function"]["name"]: t["function"]["parameters"] for t in tools}
    repairs = 0
    for _ in range(steps):
        msg = llm.chat(msgs, tools=tools, max_tokens=2000)["choices"][0]["message"]
        calls = msg.get("tool_calls") or text_tool_calls(msg.get("content"))
        msgs.append({"role": "assistant", "content": msg.get("content") or "", **({"tool_calls": calls} if calls else {})})
        if not calls and broken_call(msg.get("content")) and repairs < 2:
            repairs += 1
            msgs.append({"role": "user", "content": REPAIR})
            continue
        if not calls:
            return msg.get("content") or ""
        for c in calls:
            fn = c["function"]["name"]
            try:
                args = json.loads(c["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            args = coerce(args if isinstance(args, dict) else {}, schemas.get(fn, {}))
            tool = fn.replace("__", ".")
            verdict, text, corr = kv.call(tool, args)
            colour = GREEN if verdict.startswith("ALLOW") else RED if verdict in ("DENY", "ERROR") else AMBER
            shown = {k: (v[:60] + "…" if isinstance(v, str) and len(v) > 60 else v) for k, v in args.items()}
            print(f"{GREY}  → {tool} {json.dumps(shown)}{END}\n  {colour}KAVACH {verdict}{END}"
                  + (f" {GREY}{text[:220]}{END}" if not verdict.startswith("ALLOW") else "")
                  + (f" {GREY}(trace {corr}){END}" if corr else ""))
            msgs.append({"role": "tool", "tool_call_id": c.get("id"), "content": text[:6000]})
    return "(stopped after the step limit)"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("-p", "--prompt", help="one request, then exit")
    ap.add_argument("--url", default=os.environ.get("KAVACH_URL", "http://127.0.0.1:8000"))
    ap.add_argument("--role", default="ap_agent", help="the role KAVACH applies (same as Claude's in the demo)")
    a = ap.parse_args()
    load_settings()
    llm = QualcommCloudAI(model=os.environ.get("KAVACH_AGENT_MODEL", "Llama-3.3-70B"), timeout=90, max_wait_s=180,
                          component="agent")
    if not llm.enabled:
        print("Needs the Qualcomm key in .env (INFERENCE_CLOUD_API_KEY and INFERENCE_CLOUD_ENDPOINT).")
        return 1
    kv = Kavach(a.url, user="llama", role=a.role)
    tools = kv.tools()
    print(f"{GREY}Llama ({llm.model}, Qualcomm Cloud AI) | tools through KAVACH: "
          f"{', '.join(t['function']['name'].replace('__', '.') for t in tools)}{END}")
    msgs = [{"role": "system", "content": SYSTEM}]
    prompts = [a.prompt] if a.prompt else None
    while True:
        prompt = prompts.pop(0) if prompts else (None if prompts is not None else input("\nyou> ").strip())
        if not prompt:
            return 0
        try:
            print(f"\nllama> {turn(llm, kv, tools, msgs, prompt)}")
        finally:
            report_usage(kv.session)
        if prompts is not None and not prompts:
            return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyboardInterrupt, EOFError):
        print()
