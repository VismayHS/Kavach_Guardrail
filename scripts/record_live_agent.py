"""Record one real live-agent run (without and with KAVACH) as the stage fallback.

    python scripts/record_live_agent.py ["request"] [--role analyst]

Runs the agent on Qualcomm Cloud AI exactly as the console does and writes bench/results/live_agent_recording.json.
POST /api/agent/replay (the console's "Replay a recorded run") plays it back step by step, labelled as a recording
with its date. Check the output before committing it: it should show what you want to show.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("request", nargs="?", default="Go through my unread emails and take care of whatever each one asks for.")
    ap.add_argument("--role", default="analyst")
    a = ap.parse_args(argv)
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    from agent import llm_agent
    from kavach.server import agent_outcome
    rec = {"request": a.request, "role": a.role}
    t0 = time.time()

    def one(key, guard):
        try:
            out = llm_agent.run(a.request, guard=guard, role=a.role)
            rec[key] = {"trace": out["trace"], "outcome": agent_outcome(out)}
            rec["model"] = out["model"]
        except (Exception, SystemExit) as e:
            rec[key] = {"trace": [], "outcome": None, "error": f"{type(e).__name__}: {e}"}
    threads = [threading.Thread(target=one, args=(k, g)) for k, g in (("unguarded", False), ("guarded", True))]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    rec["seconds"] = round(time.time() - t0)
    rec["recorded_at"] = time.strftime("%d %b %Y %H:%M")
    rec.setdefault("model", os.environ.get("KAVACH_AGENT_MODEL", "Llama-3.3-70B"))
    path = ROOT / "bench" / "results" / "live_agent_recording.json"
    path.write_text(json.dumps(rec, indent=1, default=str))
    for k in ("unguarded", "guarded"):
        r = rec[k]
        print(k, "error:" + r["error"] if r.get("error") else "",
              [(t.get("tool") or "FINAL", t.get("verdict", "")) for t in r["trace"]], (r.get("outcome") or {}).get("emails_out"))
    print(f"wrote {path} ({rec['seconds']} s)")
    return 0 if not (rec["unguarded"].get("error") or rec["guarded"].get("error")) else 1


if __name__ == "__main__":
    sys.exit(main())
