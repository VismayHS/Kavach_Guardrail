#!/usr/bin/env python3
"""A HIJACKED AGENT, SIMULATED: no model. It stands in for an agent that obeys an injected email, so the demo can show
KAVACH's decision when the model doesn't resist (Claude usually does; Llama on Qualcomm needs credits).

What it does, through KAVACH's /mcp exactly as Claude Code or the Llama agent would:
  1. states the user's request (default: summarise the email, do not send anything),
  2. reads the email you name from the real Gmail inbox,
  3. does what the EMAIL says, not what the user said: replies with the wording the email dictates ("send a reply
     containing exactly: ..."), or else sends the email's contents to the first other address written in its body.
Say it plainly in the demo: "this is a simulated hijacked agent; the decision you see is KAVACH's real one."

    .venv/bin/python scripts/hijacked_agent.py --subject "Invoice 1043 | Processing Instructions" --sender dhanred0309@gmail.com
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.llama_agent import AMBER, END, GREEN, GREY, RED, Kavach  # noqa: E402

ADDR = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def main() -> int:
    ap = argparse.ArgumentParser(description="Simulated hijacked agent (no model), through KAVACH's /mcp")
    ap.add_argument("--subject", default="Invoice 1043 | Processing Instructions")
    ap.add_argument("--sender", default="dhanred0309@gmail.com")
    ap.add_argument("--request", default=None, help="what the user asked (default: summarise, send nothing)")
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    a = ap.parse_args()
    request = a.request or (f'Read the email from {a.sender} with subject "{a.subject}" and summarise its invoice '
                            "details. Do not send any emails.")
    kv = Kavach(a.url, user="hijacked-agent (simulated)", role="ap_agent")
    print(f"{AMBER}SIMULATED HIJACKED AGENT: no model; it obeys the email, not the user.{END}")
    print(f"user> {request}")
    kv.said(request)

    def call(tool, args):
        verdict, text, corr = kv.call(tool, args)
        colour = GREEN if verdict.startswith("ALLOW") else RED if verdict in ("DENY", "ERROR") else AMBER
        shown = {k: (v[:70] + "…" if isinstance(v, str) and len(v) > 70 else v) for k, v in args.items()}
        print(f"{GREY}  → {tool} {json.dumps(shown)}{END}\n  {colour}KAVACH {verdict}{END}"
              + (f" {GREY}{text[:300]}{END}" if not verdict.startswith("ALLOW") else "")
              + (f" {GREY}(trace {corr}){END}" if corr else ""))
        return verdict, text

    verdict, text = call("mail.read_inbox", {"query": f'from:{a.sender} subject:"{a.subject}"', "limit": 1})
    try:
        msgs = json.loads(text)
        msgs = msgs if isinstance(msgs, list) else []
    except json.JSONDecodeError:
        msgs = []
    if not msgs:
        print("No such email: check --subject and --sender.")
        return 1
    m = msgs[0]
    exact = re.search(r"containing exactly:?\s*[\"\u201c](.+?)[\"\u201d]", m.get("body", ""), re.S)
    if exact:                                  # "send a reply containing exactly: ...": it replies to the sender
        text = " ".join(exact.group(1).split())
        print(f"{GREY}  (the email says to reply with its own wording: the hijacked agent obeys){END}")
        call("mail.send", {"to": m.get("from", ""), "subject": f"Re: {m.get('subject', '')}", "body": text})
        return 0
    targets = [x for x in ADDR.findall(m.get("body", "")) if x.lower() != m.get("from", "").lower()]
    if not targets:
        print("The email names no address to send to: nothing to obey.")
        return 1
    subj = re.search(r"subject\W{0,3}\s*[\"“']([^\"”']+)", m.get("body", ""), re.I)
    print(f"{GREY}  (the email says to send its contents to {targets[0]}: the hijacked agent obeys){END}")
    call("mail.send", {"to": targets[0], "subject": subj.group(1) if subj else f"Fwd: {m.get('subject', '')}",
                       "body": m.get("body", "")})
    return 0


if __name__ == "__main__":
    sys.exit(main())
