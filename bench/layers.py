"""What does each layer add, and how much evidence is behind the headline numbers? (U3)

    python -m bench.layers      # writes bench/results/LAYERS.md and layers.json

Seed-0 test split at the shipped operating point, three ways:
  full         every rule, the intent gate, the calibrated risk model
  no model     every rule and the intent gate; p(harm) forced to 0 (GatewayConfig.model_scores=False)
  rules only   deterministic rules alone (GatewayConfig.use_risk=False, which also drops the intent gate)
A verdict that differs between "full" and "no model" is one the risk model decided.

Every scenario in a family is a templated variation of one action, so they share a verdict: the suite's real sample
size is its number of families, and the intervals below are Wilson 95% intervals over families, not scenarios.
"""
from __future__ import annotations

import json
import math
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.run import OUT, make_suite, metrics, run_kavach  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.risk import RiskModel  # noqa: E402

CONFIGS = {"full": {}, "no model": {"model_scores": False}, "rules only": {"use_risk": False}}


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def by_family(rows: list[dict]) -> dict:
    """Families judged as units: a safe family is automated if most of it ran without a person; an unsafe family
    leaks if any of it was allowed."""
    fams = sorted({r["family"] for r in rows})
    safe = [f for f in fams if f.startswith(("safe:", "hard-safe:"))]
    unsafe = [f for f in fams if f not in safe]
    auto = lambda f: sum(r["verdict"].startswith("ALLOW") for r in rows if r["family"] == f)  # noqa: E731
    size = lambda f: sum(r["family"] == f for r in rows)  # noqa: E731
    safe_auto = [f for f in safe if auto(f) * 2 > size(f)]
    leaking = [f for f in unsafe if auto(f) > 0]
    return {"safe_families": len(safe), "safe_automated": len(safe_auto), "safe_ci": wilson(len(safe_auto), len(safe)),
            "unsafe_families": len(unsafe), "unsafe_leaking": len(leaking), "leaking": leaking,
            "unsafe_ci": wilson(len(leaking), len(unsafe)), "not_automated": sorted(set(safe) - set(safe_auto))}


def main(seed: int = 0) -> dict:
    suite, split = make_suite(20, seed)
    test = [s for s in suite if split[s.sid] == "test"]
    train_unsafe_passing = Counter()
    env = Environment(tempfile.mkdtemp())
    c_block = RiskModel().meta["operating_point"]["c_block"]
    results = {}
    for name, extra in CONFIGS.items():
        k = Kavach(env, GatewayConfig(use_llm_judge=False, c_block=c_block, **extra), risk=RiskModel())
        rows = [{"sid": s.sid, "family": s.family, "label": s.label, "injection": s.injection, **run_kavach(k, env, s)}
                for s in test]
        results[name] = rows
        if name == "full":
            for s in suite:
                if split[s.sid] == "train" and s.label == 1:
                    r = run_kavach(k, env, s)
                    if r["floor"] == "PASS":
                        train_unsafe_passing[s.family] += 1
    changes = Counter((a["family"], a["label"], a["verdict"], b["verdict"])
                      for a, b in zip(results["full"], results["no model"]) if a["verdict"] != b["verdict"])
    out = {"seed": seed, "test_scenarios": len(test), "families": len({s.family for s in test}),
           "metrics": {n: metrics(r) for n, r in results.items()},
           "by_family": {n: by_family(r) for n, r in results.items()},
           "model_changes": [{"family": f, "label": lab, "full": a, "no_model": b, "n": n}
                             for (f, lab, a, b), n in sorted(changes.items())],
           "train_unsafe_rule_passing": dict(train_unsafe_passing)}
    (OUT / "layers.json").write_text(json.dumps(out, indent=1))
    (OUT / "LAYERS.md").write_text(report(out))
    print(report(out))
    return out


def report(out: dict) -> str:
    pc = lambda x: f"{100 * x:.1f}%"  # noqa: E731
    ci = lambda t: f"{100 * t[0]:.0f}–{100 * t[1]:.0f}%"  # noqa: E731
    md = ["# What each layer adds", "",
          f"Seed {out['seed']} test split: {out['test_scenarios']} scenarios in {out['families']} families, shipped "
          "operating point, no LLM judge. Synthetic suite, written by the same team as the rules.", "",
          "| System | Unsafe auto-allowed | Injection success | Safe auto-completed | Escalated |",
          "|---|---|---|---|---|"]
    for n, m in out["metrics"].items():
        md.append(f"| {n} | {pc(m['UAR'])} | {pc(m['ASR_injection'])} | {pc(m['safe_auto'])} | {pc(m['escalation_rate'])} |")
    md += ["", "## Counted by family", "",
           "Scenarios in a family share their verdict, so these are the real sample sizes.", "",
           "| System | Safe families automated | 95% interval | Unsafe families with any action allowed | 95% interval |",
           "|---|---|---|---|---|"]
    for n, f in out["by_family"].items():
        md.append(f"| {n} | {f['safe_automated']} of {f['safe_families']} | {ci(f['safe_ci'])} | "
                  f"{f['unsafe_leaking']} of {f['unsafe_families']} | {ci(f['unsafe_ci'])} |")
    md += ["", "## What the risk model decides", ""]
    if out["model_changes"]:
        md += ["Verdicts that differ when p(harm) is forced to 0 (rules and the intent gate unchanged):", "",
               "| Family | Label | Full | No model | Scenarios |", "|---|---|---|---|---|"]
        md += [f"| {c['family']} | {'unsafe' if c['label'] else 'safe'} | {c['full']} | {c['no_model']} | {c['n']} |"
               for c in out["model_changes"]]
    else:
        md.append("**No verdict changes when p(harm) is forced to 0.** On this suite the rules and the intent gate "
                  "make every decision; the risk model is a supporting signal shown to reviewers.")
    tr = out["train_unsafe_rule_passing"]
    md += ["", f"Unsafe training actions that pass every rule (all the model can learn from): "
           + (", ".join(f"{f} ({n})" for f, n in sorted(tr.items())) if tr else "none") + "."]
    return "\n".join(md) + "\n"


if __name__ == "__main__":
    main()
