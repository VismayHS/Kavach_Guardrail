"""One comparison table from the evidence on disk: no guardrail vs a simple baseline vs KAVACH.

    python -m bench.compare                     # -> bench/results/COMPARISON.md and comparison.json
    python -m bench.compare --live http://127.0.0.1:8000    # also what a running KAVACH measured (usage, latency)

Three kinds of evidence, never mixed:
  1. Live agent: AgentDojo v1.2.2 (ETH Zurich's benchmark, not ours), Llama-3.3-70B on Qualcomm's Cloud AI, the
     important_instructions attack. Runs still in progress are compared on the tasks every defense has finished
     (paired), never a partial run against a full one.
  2. Replay: the same benchmark's ground-truth calls and an obedient attacker, no model (bench/agentdojo_replay.py).
  3. Our own synthetic suite (bench/run.py): written by us, rules written for its families; baselines there include
     a static denylist, tool-type gating and approve-every-write.
Decision latency (p50/p95/p99) is measured here over every decision of the suite, holdout and demo scenarios.
"""
from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "bench" / "results"
RUNS = ROOT / "bench" / "agentdojo_runs"
MODEL = "Llama-3.3-70B"
DEFENSES = ["none", "spotlighting_with_delimiting", "kavach", "kavach_rules"]
NAMES = {"none": "No guardrail", "spotlighting_with_delimiting": "Spotlighting (prompt delimiting, AgentDojo's baseline)",
         "kavach": "KAVACH", "kavach_rules": "KAVACH, rules only"}


def pct(n, d):
    return f"{n}/{d} ({100 * n / d:.1f}%)" if d else "-"


def runs(suite: str, defense: str) -> dict:
    """(user_task, injection_task or None) -> outcome, from AgentDojo's per-task logs."""
    base = RUNS / suite / f"qualcomm-{MODEL}-{defense}" / suite
    out = {}
    if not base.exists():
        return out
    for f in base.glob("user_task_*/*/*.json"):
        d = json.loads(f.read_text())
        key = (d["user_task_id"], d.get("injection_task_id"))
        tools = [m for m in d.get("messages") or [] if m.get("role") == "tool"]
        blocked = [str(m.get("error") or "") for m in tools if str(m.get("error") or "").startswith("BLOCKED by KAVACH")]
        out[key] = {"utility": bool(d.get("utility")), "security": bool(d.get("security")),
                    "error": d.get("error"), "duration": d.get("duration"),
                    "deny": sum("(DENY" in b for b in blocked), "escalate": sum("(ESCALATE" in b for b in blocked),
                    "calls": sum(len(m.get("tool_calls") or []) for m in d.get("messages") or []
                                 if m.get("role") == "assistant")}
    return out


def summarize(rows: dict, keys: list) -> dict:
    ben = [rows[k] for k in keys if k[1] is None]
    att = [rows[k] for k in keys if k[1] is not None]
    dur = sorted(rows[k]["duration"] for k in keys if rows[k]["duration"])
    q = lambda p: dur[min(len(dur) - 1, int(p * len(dur)))] if dur else None  # noqa: E731
    return {"benign": len(ben), "benign_done": sum(r["utility"] for r in ben),
            "attacked": len(att), "attack_success": sum(r["security"] for r in att),
            "utility_under_attack": sum(r["utility"] for r in att),
            "errors": sum(1 for k in keys if rows[k]["error"]),
            "tasks_with_kavach_deny": sum(1 for k in keys if rows[k]["deny"]),
            "tasks_with_kavach_escalate": sum(1 for k in keys if rows[k]["escalate"]),
            "agent_task_s_p50": q(0.5), "agent_task_s_p95": q(0.95)}


def live_agentdojo() -> dict:
    out = {}
    for suite in ("banking", "slack"):
        have = {d: {k: v for k, v in runs(suite, d).items() if k[0].startswith("user_task")} for d in DEFENSES}
        have = {d: r for d, r in have.items() if r}
        if "none" not in have:
            continue
        total = len(max(have.values(), key=len))
        s = {"tasks_per_full_run": {"banking": 16 + 144, "slack": 21 + 105}[suite],     # benign + attacked
             "finished": {d: len(r) for d, r in have.items()}, "paired": {}}
        for d, r in have.items():
            if d == "none":
                continue
            keys = sorted(set(r) & set(have["none"]), key=str)
            s["paired"][d] = {"pairs": len(keys), d: summarize(r, keys), "none": summarize(have["none"], keys)}
        full = {d: summarize(r, sorted(r, key=str)) for d, r in have.items() if len(r) >= s["tasks_per_full_run"]}
        s["full_runs"] = full
        s["note_total_seen"] = total
        out[suite] = s
    return out


def decision_latency() -> dict:
    """Every decision of the synthetic suite, holdout and demo scenarios: time to decide (rules, staging, risk;
    the LLM judge off, as in the shipped default for auto-decided calls)."""
    from bench.holdout import generate as holdout
    from bench.suite import generate, materialize, prepare
    from kavach.environment import Environment
    from kavach.gateway import GatewayConfig, Kavach
    from kavach.risk import RiskModel
    from kavach.scenarios import SCENARIOS, materialize as mat2, prepare as prep2
    env = Environment(tempfile.mkdtemp())
    k = Kavach(env, GatewayConfig(use_llm_judge=False, c_block=RiskModel().meta["operating_point"]["c_block"]))
    ms = []
    for sc in generate(n_per_family=20, seed=11) + holdout():
        prepare(env, sc)
        tid, _ = k.start_task(sc.user[0], sc.user[1], sc.request, sc.env)
        outs = []
        for call in sc.setup:
            o = env.dispatch(call.tool, call.args)
            k.register_output(tid, call, o)
            outs.append(o)
        ms.append(k.check(tid, materialize(sc.action, outs)).latency_ms)
    for sc in SCENARIOS.values():
        prep2(env, sc)
        tid, _ = k.start_task(sc["user"][0], sc["user"][1], sc["request"], sc["env"], sc["plan"])
        last = None
        for c in sc["steps"]:
            d = k.run(tid, mat2(c, last))
            last = d.result
            ms.append(d.latency_ms)
    ms.sort()
    q = lambda p: round(ms[min(len(ms) - 1, int(p * len(ms)))], 2)  # noqa: E731
    return {"decisions": len(ms), "p50_ms": q(0.5), "p95_ms": q(0.95), "p99_ms": q(0.99), "max_ms": round(ms[-1], 2),
            "mean_ms": round(statistics.mean(ms), 2)}


def live_server(url: str) -> dict:
    get = lambda p: urllib.request.urlopen(url + p, timeout=10).read().decode()  # noqa: E731
    usage = json.loads(get("/api/usage"))
    buckets = {}
    for line in get("/metrics").splitlines():
        if line.startswith('kavach_request_latency_ms_bucket{route="mcp"'):
            le = line.split('le="')[1].split('"')[0]
            buckets[float("inf") if le == "+Inf" else float(le)] = float(line.rsplit(" ", 1)[1])
    n = buckets.get(float("inf"), 0)
    quant = {}
    for p in (0.5, 0.95, 0.99):
        quant[f"p{int(p * 100)}_ms_at_most"] = next((le for le, c in sorted(buckets.items()) if n and c >= p * n), None)
    return {"url": url, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "mcp_requests": n, **quant, "usage": usage}


def write(d: dict) -> str:
    L = ["# KAVACH compared: no guardrail, a simple baseline, KAVACH", "",
         f"Generated {d['generated']} at commit `{d['commit']}` on {d['hardware']}. Regenerate: `python -m bench.compare`.", "",
         "Three kinds of evidence, kept apart: (1) a live agent on ETH Zurich's AgentDojo (not written by us), "
         "(2) the same benchmark replayed with its ground-truth calls and an obedient attacker (no model), "
         "(3) our own synthetic suite (written by us; its rules target its families, so read it as a regression "
         "check, not as independent evidence).", ""]
    L += ["## 1. Live agent: AgentDojo v1.2.2, Llama-3.3-70B on Qualcomm Cloud AI, important_instructions attack", "",
          "Attack success = AgentDojo's own security check (the attacker's goal was reached). Benign = user tasks "
          "with no attack, utility = AgentDojo's own check. KAVACH counts an ESCALATE as a block here (in production a "
          "person would decide). Runs in progress are compared on the tasks both defenses finished (paired).", ""]
    for suite, s in d["live"].items():
        L += [f"### {suite.title()} (finished so far: " + ", ".join(f"{NAMES[k]} {v}/{s['tasks_per_full_run']}"
                                                                     for k, v in s["finished"].items()) + ")", "",
              "| Defense | Tasks compared | Benign done | Attack success ↓ | Utility under attack | Tasks with a KAVACH deny / escalate | Errors | Agent time per task p50 / p95 |",
              "|---|---|---|---|---|---|---|---|"]
        for dname, p in s["paired"].items():
            if p[dname]["attacked"] < 20:
                L.append(f"| {NAMES[dname]} | in progress: {p['pairs']} tasks paired so far, too few to compare | | | | | | |")
                continue
            for who in ("none", dname):
                r = p[who]
                L.append(f"| {NAMES[who]} | {p['pairs']} (paired with {NAMES[dname] if who == 'none' else 'No guardrail'}) | "
                         f"{pct(r['benign_done'], r['benign'])} | {pct(r['attack_success'], r['attacked'])} | "
                         f"{pct(r['utility_under_attack'], r['attacked'])} | "
                         f"{r['tasks_with_kavach_deny']} / {r['tasks_with_kavach_escalate']} | {r['errors']} | "
                         f"{r['agent_task_s_p50'] and round(r['agent_task_s_p50'])} s / {r['agent_task_s_p95'] and round(r['agent_task_s_p95'])} s |")
        L += ["", "Agent time is the whole AgentDojo task as the agent lived it, and is dominated by Qualcomm "
              "rate-limit waits: several runs shared one key, and KAVACH's runs overlapped with the most others. "
              "KAVACH's own decision time is below (Decision latency)."]
        if suite == "slack":
            L += ["", "Slack's injection_task_5 is checked from the calls the agent *attempted*: a call KAVACH blocked "
                  "still counts as the attacker's there. bench/results/AGENTDOJO.md also reports the executed-only check."]
        L.append("")
    r = d["replay"]
    L += ["## 2. Replay: the same benchmark, ground-truth calls, an obedient attacker (no model)", "",
          "| Suite | Defense | Benign done | Attacks that succeeded, executed calls | AgentDojo's own check |", "|---|---|---|---|---|"]
    for x in r:
        L.append(f"| {x['suite']} | {NAMES.get(x['defense'], x['defense'])} | {pct(x['benign_done'], x['benign_tasks'])} "
                 f"(+{x['benign_escalated_only']} only escalated) | {pct(x['attack_success_executed'], x['attacked'])} | "
                 f"{pct(x['attack_success'], x['attacked'])} |")
    L += ["", "No guardrail: every one of these obedient attacks succeeds by construction "
          f"({', '.join(str(x['undefended_success']) + '/' + str(x['attacked']) for x in r if x['defense'] == 'kavach')}).", ""]
    L += ["## 3. Our synthetic suite (bench/run.py, held-out test split; written by us)", "",
          "| System | Unsafe auto-allowed ↓ | Injection attack success ↓ | Safe tasks auto-completed ↑ | Escalation rate |",
          "|---|---|---|---|---|"]
    for row in d["suite"]:
        L.append(f"| {row['name']} | {row['uar']} | {row['asr']} | {row['safe_auto']} | {row['escalation']} |")
    lat = d["latency"]
    L += ["", "## Decision latency (measured here)", "",
          f"{lat['decisions']} decisions (synthetic suite, holdout, demo scenarios), LLM judge off: p50 {lat['p50_ms']} ms, "
          f"p95 {lat['p95_ms']} ms, p99 {lat['p99_ms']} ms, max {lat['max_ms']} ms. The Qualcomm judge, when on, runs only "
          "for calls already waiting for a person (escalations-only), so it never delays an allowed call.", ""]
    if d.get("live_server"):
        v = d["live_server"]
        u = v["usage"]
        L += ["## Live demo server (what a running KAVACH measured)", "",
              f"At {v['at']}: {v['mcp_requests']:.0f} /mcp requests, end-to-end p50 ≤ {v['p50_ms_at_most']} ms, "
              f"p95 ≤ {v['p95_ms_at_most']} ms, p99 ≤ {v['p99_ms_at_most']} ms (histogram bucket bounds). "
              f"Model: {u['calls']} calls ({u['errors']} errors), {u['tokens']} tokens as reported by the API, "
              f"{u['usage_unknown_calls']} calls without usage; estimated cost USD {u['estimated_cost_usd']} "
              f"(price table {u['price_table']}; {u['unpriced_tokens']} tokens of unpriced models: cost unknown).", ""]
    L += ["## Model usage and cost of the live AgentDojo runs", "",
          "Not recorded: those runs began before the usage meter (kavach/usage.py) existed, and AgentDojo's logs don't "
          "keep token counts. Unknown, not zero. Qualcomm publishes no per-token price for its Cloud AI Playground; see "
          "kavach/model_prices.json.", "",
          "## Limits", "",
          "- Live runs are one sample per task (temperature as AgentDojo sets it), one model, one attack.",
          "- KAVACH's benign losses on AgentDojo are mostly ESCALATEs a person would approve in production; the "
          "replay separates them.",
          "- Our synthetic suite was written by the same team as the rules.", ""]
    return "\n".join(L)


def suite_rows() -> list[dict]:
    d = json.loads((OUT / "results.json").read_text())
    want = {"No guardrail", "Static denylist (text match)", "Tool-type gating", "Approve every write (manual interrupt)",
            "KAVACH: rules only", "KAVACH (full)"}
    out = []
    for s in d["systems"]:
        name = s.get("name") or s.get("system")
        if name not in want:
            continue
        f = lambda k: f"{100 * s[k]:.1f}%" if isinstance(s.get(k), (int, float)) else "-"  # noqa: E731
        out.append({"name": name, "uar": f("UAR"), "asr": f("ASR_injection"), "safe_auto": f("safe_auto"),
                    "escalation": f("escalation_rate")})
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", help="a running KAVACH, e.g. http://127.0.0.1:8000")
    a = ap.parse_args(argv)
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
    d = {"generated": time.strftime("%Y-%m-%d %H:%M"), "commit": commit,
         "hardware": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
         "dataset": "AgentDojo v1.2.2", "model": MODEL, "live": live_agentdojo(),
         "replay": json.loads((OUT / "agentdojo_replay.json").read_text()), "suite": suite_rows(),
         "latency": decision_latency()}
    if a.live:
        d["live_server"] = live_server(a.live)
    (OUT / "comparison.json").write_text(json.dumps(d, indent=1, default=str))
    text = write(d)
    (OUT / "COMPARISON.md").write_text(text)
    print(text)


if __name__ == "__main__":
    main()
