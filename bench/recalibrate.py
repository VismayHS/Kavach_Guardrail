"""Retrain the risk model with the decisions reviewers made (U11).

    python -m bench.recalibrate --state /var/lib/kavach/kavach.db            # writes kavach/model/recalibrated.json
    python -m bench.recalibrate --state ... --install                        # ...and replaces the shipped model

Every approve or deny in the approval queue is kept as a label with the features the reviewer saw (kavach.hitl;
persisted with KAVACH_STATE, kavach.store). This adds the older 70% of those labels to the suite's training split,
retrains and recalibrates exactly as bench.run does, and checks the result two ways before anything is installed:
  * the newest 30% of labels, held out: does the new model separate what people denied from what they approved?
  * the suite's seed-0 test split: does the gateway still decide as before (unsafe allowed, safe automated)?
The shipped operating point (C_block) is kept; the model alone changes. Fewer than MIN_LABELS usable labels, or
labels of only one kind, and nothing is trained.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.run import make_suite, metrics, run_kavach, train  # noqa: E402
from kavach.environment import Environment  # noqa: E402
from kavach.gateway import GatewayConfig, Kavach  # noqa: E402
from kavach.risk import FEATURES, MODEL_PATH, RiskModel  # noqa: E402
from kavach.store import Store  # noqa: E402

MIN_LABELS = 20
HOLDOUT = 0.3


def suite_rows(seed: int = 0):
    """(features, label) per scenario that passes every rule, by split, as in bench.run."""
    suite, split = make_suite(20, seed)
    env = Environment(tempfile.mkdtemp())
    prior = Kavach(env, GatewayConfig(use_llm_judge=False), risk=RiskModel(Path(tempfile.mkdtemp()) / "none.json"))
    out = {"train": [], "cal": [], "test": []}
    for sc in suite:
        r = run_kavach(prior, env, sc)
        if r["features"] and r["floor"] == "PASS":
            out[split[sc.sid]].append(([r["features"][f] for f in FEATURES], sc.label))
    return suite, split, out


def usable(labels: list[dict]) -> list[tuple[list[float], int, float]]:
    rows = []
    for lab in labels:
        f = lab.get("features") or {}
        if all(k in f for k in FEATURES):
            rows.append(([float(f[k]) for k in FEATURES], int(lab["label_unsafe"]), float(lab.get("at", 0))))
    return sorted(rows, key=lambda r: r[2])


def p_of(model: RiskModel, x: list[float]) -> float:
    return model.predict(dict(zip(FEATURES, x)))[0]


def main(state: str, out: str | None = None, install: bool = False, seed: int = 0) -> dict:
    labels = usable(Store(state).labels())
    cut = int(len(labels) * (1 - HOLDOUT))
    fit, held = labels[:cut], labels[cut:]
    if len(labels) < MIN_LABELS or len({y for _, y, _ in fit}) < 2 or len({y for _, y, _ in held}) < 2:
        raise SystemExit(f"Not enough to recalibrate: {len(labels)} usable labels (need {MIN_LABELS}, with both "
                         "approvals and denials among the older 70% and the newest 30%). Nothing trained.")
    suite, split, rows = suite_rows(seed)
    xy = lambda rs: (np.array([x for x, _ in rs]), np.array([y for _, y in rs]))  # noqa: E731
    xtr, ytr = xy(rows["train"] + [(x, y) for x, y, _ in fit])
    xca, yca = xy(rows["cal"])
    shipped = RiskModel()
    model = train(xtr, ytr, xca, yca, seed=seed)
    model["meta"]["operating_point"] = shipped.meta.get("operating_point", {"c_block": 0.02})
    model["meta"]["recalibrated_with"] = {"human_labels": len(fit), "held_out": len(held)}
    dest = Path(out) if out else MODEL_PATH.with_name("recalibrated.json")
    dest.write_text(json.dumps(model))
    new = RiskModel(dest)

    def separation(m: RiskModel) -> dict:
        denied = [p_of(m, x) for x, y, _ in held if y == 1]
        approved = [p_of(m, x) for x, y, _ in held if y == 0]
        return {"p_denied": round(float(np.mean(denied)), 3), "p_approved": round(float(np.mean(approved)), 3)}

    test = [s for s in suite if split[s.sid] == "test"]
    env = Environment(tempfile.mkdtemp())
    c_block = shipped.meta.get("operating_point", {}).get("c_block", 0.02)
    gate = lambda m: metrics([{"label": s.label, "injection": s.injection,  # noqa: E731
                               **run_kavach(Kavach(env, GatewayConfig(use_llm_judge=False, c_block=c_block), risk=m),
                                            env, s)} for s in test])
    report = {"labels": len(labels), "trained_on": len(fit), "held_out": len(held), "model": str(dest),
              "held_out_separation": {"shipped": separation(shipped), "recalibrated": separation(new)},
              "suite_test": {"shipped": gate(shipped), "recalibrated": gate(new)}, "installed": False}
    if install:
        MODEL_PATH.write_text(dest.read_text())
        report["installed"] = True
    print(json.dumps(report, indent=1))
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True, help="the KAVACH_STATE file the server wrote")
    ap.add_argument("--out", help="where to write the recalibrated model")
    ap.add_argument("--install", action="store_true", help="replace kavach/model/risk_model.json with it")
    a = ap.parse_args()
    main(a.state, a.out, a.install)
