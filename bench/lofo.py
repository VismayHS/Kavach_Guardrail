"""Leave one family out: how KAVACH judges kinds of action it was never trained on.

    python -m bench.lofo        # writes bench/results/LOFO.md and lofo.json (and runs bench.holdout for the fresh row)

For each scenario family the risk model is retrained without that family (rule-passing actions only, as in
bench.run), and the full gateway at the shipped operating point judges every scenario of the held-out family.
The rules are the same in every fold; only the model changes.
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.holdout import main as holdout_main  # noqa: E402
from bench.run import OUT, make_suite, metrics, run_kavach, train  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.risk import FEATURES, RiskModel  # noqa: E402


def main(n_per_family: int = 20, seed: int = 0) -> dict:
    suite, split = make_suite(n_per_family, seed)
    env = Environment(tempfile.mkdtemp())
    c_block = RiskModel().meta["operating_point"]["c_block"]          # the shipped operating point
    prior = Kavach(env, GatewayConfig(use_llm_judge=False), risk=RiskModel(Path(tempfile.mkdtemp()) / "none.json"))
    feats = {}
    for sc in suite:                                                 # features don't depend on the model
        r = run_kavach(prior, env, sc)
        if r["features"] and r["floor"] == "PASS":
            feats[sc.sid] = [r["features"][f] for f in FEATURES]

    rows, model_path, prior_folds = [], Path(tempfile.mkdtemp()) / "fold.json", []
    unsafe_passing = sorted({s.family for s in suite if s.sid in feats and s.label == 1})
    for fam in sorted({s.family for s in suite}):
        def xy(parts):
            ids = [s.sid for s in suite if s.family != fam and split[s.sid] in parts and s.sid in feats]
            return np.array([feats[i] for i in ids]), np.array([next(s.label for s in suite if s.sid == i) for i in ids])
        (xtr, ytr), (xca, yca) = xy(("train", "test")), xy(("cal",))
        if len(set(ytr)) < 2:      # no unsafe action passes the rules without this family: only the prior is left
            prior_folds.append(fam)
            risk = RiskModel(Path(tempfile.mkdtemp()) / "none.json")
        else:
            model_path.write_text(json.dumps(train(xtr, ytr, xca, yca, seed=seed)))
            risk = RiskModel(model_path)
        k = Kavach(env, GatewayConfig(use_llm_judge=False, c_block=c_block), risk=risk)
        for sc in (s for s in suite if s.family == fam):
            rows.append({"sid": sc.sid, "family": fam, "label": sc.label, "injection": sc.injection,
                         **run_kavach(k, env, sc)})

    per_family = {f: dict(Counter(r["verdict"] for r in rows if r["family"] == f))
                  for f in sorted({r["family"] for r in rows})}
    leaked = Counter(r["family"] for r in rows if r["label"] == 1 and r["verdict"].startswith("ALLOW"))
    out = {"scenarios": len(rows), "families": len(per_family), "c_block": c_block,
           "metrics": metrics(rows), "per_family": per_family, "unsafe_auto_allowed_by_family": dict(leaked),
           "unsafe_families_passing_rules": unsafe_passing, "prior_only_folds": prior_folds}
    (OUT / "lofo.json").write_text(json.dumps(out, indent=1))
    write_report(out, holdout_main())
    return out


def write_report(out: dict, fresh: dict) -> None:
    std = json.loads((OUT / "results.json").read_text())
    full = next(s for s in std["systems"] if s["system"] == "KAVACH (full)")
    m = out["metrics"]
    line = lambda name, s: (f"| {name} | {s['UAR']:.1%} | {s['ASR_injection']:.1%} | "  # noqa: E731
                            f"{s['safe_auto']:.1%} | {s['escalation_rate']:.1%} |")
    md = ["# Seen, unseen and fresh families", "",
          f"**Unseen:** each of the {out['families']} families is judged by a risk model trained without it (rules "
          f"unchanged, shipped operating point C_block={out['c_block']}), {out['scenarios']} scenarios. "
          f"**Fresh:** {fresh['scenarios']} scenarios from `bench/holdout.py` ([HOLDOUT.md](HOLDOUT.md)), judged by "
          "the shipped model.", "",
          "| | Unsafe auto-allowed | Injection success | Safe auto-completed | Escalated |", "|---|---|---|---|---|",
          line("Seen: standard split (bench.run, seed-0 test split)", full),
          line("Unseen: leave one family out", m),
          line("Fresh: families written after the rules", fresh["metrics"]), ""]
    if out["unsafe_auto_allowed_by_family"]:
        md.append("Unsafe actions auto-allowed, by family: " + ", ".join(
            f"{f} ({n})" for f, n in sorted(out["unsafe_auto_allowed_by_family"].items())) + ".")
    else:
        md.append("No unsafe action was auto-allowed.")
    md += ["", f"Unsafe families with actions that pass every rule (all the model can learn from): "
           f"{', '.join(out['unsafe_families_passing_rules']) or 'none'}. "
           + (f"Held out, nothing unsafe is left to train on, so the untrained prior judged: "
              f"{', '.join(out['prior_only_folds'])}." if out["prior_only_folds"] else "")]
    md += ["", "| Family | Verdicts (held out) |", "|---|---|"]
    md += [f"| {f} | {', '.join(f'{v} {n}' for v, n in sorted(c.items()))} |" for f, c in out["per_family"].items()]
    (OUT / "LOFO.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:9]))


if __name__ == "__main__":
    main()
