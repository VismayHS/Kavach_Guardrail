"""Should Qualcomm write the explanations? (U4)

    python -m bench.explain_eval      # needs the Qualcomm key; writes bench/results/EXPLAIN.md and explain.json

One decision per scenario family (seed-0 test split) goes to the explainer with the LLM on. A rewrite is kept only if
every number in it appears in the evidence and, for DENY / ESCALATE, it doesn't call the action safe or approved;
otherwise the template stands. The report counts kept and rejected rewrites, the reasons and the latency, and shows a
few side by side, so the team can decide whether to switch GatewayConfig.use_llm_explainer on.

Against the offline stand-in (scripts/fake_imagine.py) the run is a rehearsal, written under bench/results/rehearsal/.
"""
from __future__ import annotations

import json
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.run import OUT, make_suite  # noqa: E402
from bench.suite import materialize, prepare  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.explain import Explainer  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402


def decisions(gw: Kavach, env: Environment) -> list[dict]:
    suite, split = make_suite(20, 0)
    seen, out = set(), []
    for sc in suite:
        if split[sc.sid] != "test" or sc.family in seen:
            continue
        seen.add(sc.family)
        prepare(env, sc)
        tid, _ = gw.start_task(sc.user[0], sc.user[1], sc.request, sc.env)
        outputs = []
        for call in sc.setup:
            spec = gw.registry.get(call.tool)
            o = env.dispatch(call.tool, call.args)
            gw.tasks[tid].prov.register_output(call.tool, o, spec.output_trust, spec.output_conf)
            outputs.append(o)
        out.append({"family": sc.family, **gw.check(tid, materialize(sc.action, outputs)).to_dict()})
    return out


def main() -> dict | None:
    env = Environment(tempfile.mkdtemp())
    gw = Kavach(env, GatewayConfig(use_llm_judge=False, use_llm_explainer=False))
    ex = Explainer(use_llm=True)
    if not ex.llm.enabled:
        print("No Qualcomm key/endpoint (IMAGINE_* or INFERENCE_CLOUD_*): nothing to measure.")
        return None
    rows = []
    for d in decisions(gw, env):
        t0 = time.perf_counter()
        text, src = ex.explain(d)
        rows.append({"family": d["family"], "verdict": d["verdict"], "source": src, "text": text,
                     "ms": round((time.perf_counter() - t0) * 1000)})
    host = urlparse(ex.llm.endpoint).hostname or ""
    out = {"endpoint_host": host, "model": ex.llm.model, "when": time.strftime("%Y-%m-%d %H:%M %Z"),
           "rehearsal": host in ("localhost", "127.0.0.1", "0.0.0.0"), "rows": rows,
           "sources": dict(Counter(r["source"] for r in rows))}
    dest = OUT / "rehearsal" if out["rehearsal"] else OUT
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "explain.json").write_text(json.dumps(out, indent=1))
    (dest / "EXPLAIN.md").write_text(report(out))
    print(report(out))
    return out


def report(out: dict) -> str:
    ms = sorted(r["ms"] for r in out["rows"])
    md = ["# LLM-written explanations", ""]
    if out["rehearsal"]:
        md += [f"**Rehearsal against `{out['endpoint_host']}`, not a measurement.**", ""]
    md += [f"Run {out['when']} against `{out['endpoint_host']}` with {out['model']}: one decision per family "
           f"({len(out['rows'])}). Median {ms[len(ms) // 2]} ms per explanation.", "",
           "| Outcome | Decisions |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in sorted(out["sources"].items(), key=lambda kv: -kv[1])]
    kept = [r for r in out["rows"] if r["source"].startswith("qualcomm")][:4]
    if kept:
        md += ["", "Examples kept (the LLM text comes first, the template after it):", ""]
        for r in kept:
            md += [f"**{r['family']}, {r['verdict']}**", "", "```", r["text"].strip(), "```", ""]
    return "\n".join(md) + "\n"


if __name__ == "__main__":
    main()
