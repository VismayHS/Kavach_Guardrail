"""What the two-stage Qualcomm judge changes, and what it costs in latency.

    python -m bench.judge_eval      # needs IMAGINE_API_KEY and IMAGINE_API_ENDPOINT; writes bench/results/JUDGE.md

Runs the seed-0 test split and the fresh holdout with the judge off and on, at the shipped operating point.
Against the offline stand-in (uvicorn scripts.fake_imagine:app --port 9100, IMAGINE_API_ENDPOINT=http://localhost:9100,
IMAGINE_API_KEY=x) this rehearses the plumbing only, and the report says so: that "model" is a script.
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.holdout import generate as holdout  # noqa: E402
from bench.run import OUT, make_suite, metrics, run_kavach  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.risk import RiskModel  # noqa: E402


def pct(xs, q):
    return round(float(np.quantile(xs, q)), 1) if xs else None


def main() -> dict | None:
    c_block = RiskModel().meta["operating_point"]["c_block"]
    env = Environment(tempfile.mkdtemp())
    on = Kavach(env, GatewayConfig(use_llm_judge=True, c_block=c_block))
    llm = on.judge.llm
    if not llm.enabled:
        print("IMAGINE_API_KEY / IMAGINE_API_ENDPOINT not set (or httpx missing): nothing to measure.")
        return None
    off = Kavach(env, GatewayConfig(use_llm_judge=False, c_block=c_block))
    suite, split = make_suite(20, 0)
    scenarios = [s for s in suite if split[s.sid] == "test"] + holdout()
    rows = {"off": [], "on": []}
    for sc in scenarios:
        for name, k in (("off", off), ("on", on)):
            rows[name].append({"sid": sc.sid, "family": sc.family, "label": sc.label, "injection": sc.injection,
                               "tool": sc.action.tool, **run_kavach(k, env, sc)})
    src = Counter((r["intent"] or {}).get("source", "no intent check") for r in rows["on"])
    stage_ms = [ms for r in rows["on"] for ms in (r["intent"] or {}).get("llm_latency_ms", []) or [] if ms]
    changes = Counter((a["family"], a["verdict"], b["verdict"]) for a, b in zip(rows["off"], rows["on"])
                      if a["verdict"] != b["verdict"])
    host = urlparse(llm.endpoint).hostname or ""
    out = {"endpoint_host": host, "rehearsal": host in ("localhost", "127.0.0.1", "0.0.0.0"),
           "models": list(llm.picked or [llm.model]), "scenarios": len(scenarios),
           "metrics": {k: metrics(v) for k, v in rows.items()}, "judge_sources": dict(src),
           "distinct_calls_asked": len(on.judge.cache),
           "check_ms": {k: {"p50": pct([r["ms"] for r in v], 0.5), "p95": pct([r["ms"] for r in v], 0.95)}
                        for k, v in rows.items()},
           "llm_call_ms": {"p50": pct(stage_ms, 0.5), "p95": pct(stage_ms, 0.95), "n": len(stage_ms)},
           "verdict_changes": [{"family": f, "off": a, "on": b, "n": n} for (f, a, b), n in sorted(changes.items())]}
    (OUT / "judge.json").write_text(json.dumps(out, indent=1))
    write_report(out)
    return out


def write_report(out: dict) -> None:
    m = out["metrics"]
    line = lambda name, s, ms: (f"| {name} | {s['UAR']:.1%} | {s['ASR_injection']:.1%} | {s['safe_auto']:.1%} | "  # noqa: E731
                                f"{s['escalation_rate']:.1%} | {ms['p50']} / {ms['p95']} |")
    md = ["# Qualcomm two-stage judge", ""]
    if out["rehearsal"]:
        md += [f"**Rehearsal, not a measurement.** The endpoint is `{out['endpoint_host']}`, the offline stand-in "
               "(`scripts/fake_imagine.py`), whose \"model\" is a script. These numbers only show the plumbing works.", ""]
    md += [f"Endpoint `{out['endpoint_host']}`, models {' → '.join(out['models'])} (fast triage → strong review). "
           f"{out['scenarios']} scenarios: the seed-0 test split and the fresh holdout. Shipped operating point.", "",
           "| Judge | Unsafe auto-allowed | Injection success | Safe auto-completed | Escalated | check() p50 / p95 ms |",
           "|---|---|---|---|---|---|",
           line("Off (heuristic only)", m["off"], out["check_ms"]["off"]),
           line("On (two-stage)", m["on"], out["check_ms"]["on"]), "",
           f"Judge path per decision: {', '.join(f'{k} {v}' for k, v in sorted(out['judge_sources'].items()))}. "
           f"Distinct calls sent to the model: {out['distinct_calls_asked']} (the rest came from the cache). "
           f"Model calls: {out['llm_call_ms']['n']}, p50 {out['llm_call_ms']['p50']} ms, p95 {out['llm_call_ms']['p95']} ms.",
           ""]
    if out["verdict_changes"]:
        md += ["| Family | Off | On | Scenarios |", "|---|---|---|---|"]
        md += [f"| {c['family']} | {c['off']} | {c['on']} | {c['n']} |" for c in out["verdict_changes"]]
    else:
        md.append("No verdict changed.")
    (OUT / "JUDGE.md").write_text("\n".join(md) + "\n")
    print("\n".join(md))


if __name__ == "__main__":
    main()
