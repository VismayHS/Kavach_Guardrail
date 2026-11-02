"""E11: conformal risk control for the whole gateway, and the data the learning loop retrains from.

    python -m bench.conformal          # stores the exact train / calibration / test rows in the model file (its
                                       # weights are not changed: refitting them reproduces the shipped model),
                                       # then writes bench/results/CONFORMAL.md and conformal.json

The cutoff lambda(alpha) comes from the calibration split only; every rate below is measured on the test split.
"""
from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import numpy as np

from bench.run import OUT, make_suite, metrics, run_kavach
from bench.suite import materialize, prepare
from kavach.conformal import bound, crc_lambda, min_alpha
from kavach.environment import Environment
from kavach.gateway import GatewayConfig, Kavach
from kavach.policy import floor_of
from kavach.risk import FEATURES, MODEL_PATH, RiskModel, fit

ALPHAS = (0.01, 0.02, 0.05, 0.1)


def decide(k, env, sc):
    prepare(env, sc)
    tid, _ = k.start_task(sc.user[0], sc.user[1], sc.request, sc.env)
    outs = []
    for call in sc.setup:
        o = env.dispatch(call.tool, call.args)
        k.register_output(tid, call, o)
        outs.append(o)
    return k.check(tid, materialize(sc.action, outs))


def rows(seed: int = 0):
    """Per split: the model's training rows (actions that pass the rules), and for the calibration split every
    action with its rule floor and tau at the operating point (what the system-level bound needs)."""
    suite, split = make_suite(20, seed)
    env = Environment(tempfile.mkdtemp())
    prior = Kavach(env, GatewayConfig(use_llm_judge=False), risk=RiskModel(Path("/nonexistent")))
    data = {"train": {"X": [], "y": []}, "cal": {"X": [], "y": []}, "test": {"X": [], "y": []}, "cal_system": [],
            "test_system": []}
    for sc in suite:
        d = decide(prior, env, sc)
        fl = floor_of(d.gates)
        if d.risk is not None and fl == "PASS":
            data[split[sc.sid]]["X"].append([d.risk.features[f] for f in FEATURES])
            data[split[sc.sid]]["y"].append(sc.label)
    model = RiskModel(MODEL_PATH)
    op = Kavach(env, GatewayConfig(use_llm_judge=False, c_block=model.meta["operating_point"]["c_block"]),
                risk=model)
    for sc in suite:
        if split[sc.sid] not in ("cal", "test"):
            continue
        d = decide(op, env, sc)
        data[split[sc.sid] + "_system"].append({"x": [d.risk.features[f] for f in FEATURES] if d.risk else None,
                                   "floor": floor_of(d.gates), "tau": d.risk.tau if d.risk else 0.0,
                                   "y": sc.label, "family": sc.family})
    return suite, split, data


def main(seed: int = 0) -> dict:
    suite, split, data = rows(seed)
    model = json.loads(MODEL_PATH.read_text())
    X, y = np.array(data["train"]["X"]), np.array(data["train"]["y"])
    Xc, yc = np.array(data["cal"]["X"]), np.array(data["cal"]["y"])
    refit = fit(X, y, Xc, yc, n_boot=model["meta"].get("n_boot", 25), seed=seed)
    if not (np.allclose(refit["coefs"], model["coefs"]) and np.allclose(refit["iso_y"], model["iso_y"])):
        raise SystemExit("the stored rows don't reproduce the shipped model; run python -m bench.run first")
    model["data"] = data
    model["meta"]["data_note"] = ("bench.run seed 0: train/cal/test rows the model sees (actions that pass the "
                                  "rules; refitting on train reproduces these weights) and every calibration action "
                                  "with its rule floor and tau (cal_system, for the conformal bound)")
    MODEL_PATH.write_text(json.dumps(model))

    rm = RiskModel(MODEL_PATH)
    scores = rm.conformal_scores()
    n_unsafe = len(scores)
    test = [s for s in suite if split[s.sid] == "test"]
    env = Environment(tempfile.mkdtemp())
    c_block = rm.meta["operating_point"]["c_block"]

    def evaluate(cfg):
        k = Kavach(env, cfg, risk=RiskModel(MODEL_PATH))
        return metrics([{"label": sc.label, "injection": sc.injection, "tool": sc.action.tool, **run_kavach(k, env, sc)}
                        for sc in test])

    base = evaluate(GatewayConfig(use_llm_judge=False, c_block=c_block))
    out = {"n_unsafe_cal": n_unsafe, "n_cal": len(data["cal_system"]),
           "unsafe_cal_past_rules": sum(1 for r in data["cal_system"] if r["y"] == 1 and r["floor"] == "PASS"),
           "unsafe_cal_below_tau": int(np.isfinite(scores).sum()),
           "min_alpha": round(min_alpha(n_unsafe), 4), "baseline": base, "alphas": []}
    for a in ALPHAS:
        lam = crc_lambda(scores, a)
        misses = int((scores < lam).sum())
        capped = evaluate(GatewayConfig(use_llm_judge=False, c_block=c_block, conformal_alpha=a))
        out["alphas"].append({"alpha": a, "lambda": None if math.isinf(lam) else round(lam, 4),
                              "cal_misses": misses, "bound": round(bound(n_unsafe, misses), 4), "full": capped})
    (OUT / "conformal.json").write_text(json.dumps(out, indent=1))
    write(out)
    return out


def write(o: dict) -> None:
    b = o["baseline"]
    lines = ["# Conformal risk control (E11)", "",
             "Conformal risk control (Angelopoulos et al., ICLR 2024) turns the calibration split into a promise about "
             "the **whole gateway**: for a new unsafe action exchangeable with the unsafe calibration actions, "
             "E[1{auto-allowed}] <= alpha. Each unsafe calibration action gets the score at which KAVACH would "
             "auto-allow it: the model's p_hi if the rules let it through and p_hi < tau, otherwise +inf. The cap "
             "then allows an action only if p_hi < min(tau, lambda(alpha)).", "",
             f"Calibration split: {o['n_cal']} actions, {o['n_unsafe_cal']} unsafe. Of those, "
             f"{o['unsafe_cal_past_rules']} get past the rules to the model, and {o['unsafe_cal_below_tau']} of "
             f"these also score below tau (would be auto-allowed). Smallest alpha this data can promise: "
             f"{o['min_alpha']:.4f} (1/(n+1)).", "",
             "Rates on the **test split** (self-graded synthetic suite; see RESULTS.md for its limits). UAR = unsafe "
             "auto-allowed; safe auto = safe actions completed without a person.", "",
             "| alpha | lambda | calibration misses | bound | UAR | safe auto |", "|---|---|---|---|---|---|",
             f"| cap off | - | - | - | {b['UAR']:.3f} | {b['safe_auto']:.3f} |"]
    for r in o["alphas"]:
        lam = "+inf (never binds)" if r["lambda"] is None else f"{r['lambda']:.3f}"
        lines.append(f"| {r['alpha']} | {lam} | {r['cal_misses']} | {r['bound']:.4f} | {r['full']['UAR']:.3f} | "
                     f"{r['full']['safe_auto']:.3f} |")
    lines += ["", "Reading it:", "",
              "- When lambda is +inf, the rules and tau already stop every unsafe calibration action, so the cap costs "
              "nothing, and 1/(n+1) is a certificate for the gateway as it is: on traffic like the calibration data, "
              "the expected unsafe auto-allow rate is at most that.",
              "- The promise is only as good as exchangeability. This suite is ours (self-graded), and attacks unlike "
              "its examples are what the rules and provenance are for. It is an expectation over draws of data, not "
              "a high-probability bound for one deployment.",
              "- Human decisions grow the calibration data: the learning loop (kavach/learning.py) refits with them, "
              "and the cutoff is recomputed with the new weights.", "",
              "Turn it on with `GatewayConfig(conformal_alpha=0.05)` (server: `KAVACH_CONFORMAL_ALPHA=0.05`)."]
    (OUT / "CONFORMAL.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    o = main()
    print({k: v for k, v in o.items() if k not in ("alphas", "baseline")}, "base UAR", o["baseline"]["UAR"],
          "safe", o["baseline"]["safe_auto"])
    for r in o["alphas"]:
        print(r["alpha"], r["lambda"], r["cal_misses"], r["bound"], r["full"]["UAR"], r["full"]["safe_auto"])
