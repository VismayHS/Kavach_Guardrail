"""Human-feedback learning loop (E11): approvals and refusals become training data, behind a no-regression gate.

Every time a person approves or refuses an escalated action, the approval queue records the action's features and
the decision (hitl.py; persisted by the store, E5). Only actions the model escalated count (no rule fired), like the
model's own training rows. `retrain` refits the risk model on the shipped training rows plus
that feedback (each human label counts `weight` times: it is about this deployment's real traffic), recalibrates it,
and promotes it only if, on the frozen test split it has never seen:

  * it does not auto-allow more unsafe actions than the current model (the safety number never gets worse), and
  * it does not send noticeably more safe actions to a person (safe auto-completion drops by at most `max_drop`).

A promoted model gets its own conformal cutoff (the calibration rows are re-scored with its weights), and both a
promotion and a refusal are written to the receipt chain with the two models' hashes and numbers.

What it is not: a person who approves by reflex teaches the model to approve; fatigue stats (hitl.stats) flag such
approvers, and their labels can be left out (`exclude_approvers`).
"""
from __future__ import annotations

import copy
import time

import numpy as np

from .risk import FEATURES, RiskModel, fit


def feedback_rows(labels: list[dict], exclude_approvers: set[str] | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Only decisions on actions the *model* sent to a person (no rule fired): like the training data, which holds
    only actions that pass the rules. A refused refund over the limit (R5) says nothing the features can learn."""
    X, y = [], []
    for lab in labels:
        f = lab.get("features") or {}
        if lab.get("approver") in (exclude_approvers or set()) or not all(k in f for k in FEATURES) \
                or lab.get("floor") != "PASS":
            continue
        X.append([float(f[k]) for k in FEATURES])
        y.append(int(lab["label_unsafe"]))
    return np.array(X).reshape(-1, len(FEATURES)), np.array(y, dtype=int)


def system_rates(rm: RiskModel, rows: list[dict]) -> dict:
    """On stored actions (rule floor and tau at the operating point): what this model would auto-allow."""
    def allowed(r):
        return r["floor"] == "PASS" and r["x"] is not None and rm.predict(dict(zip(FEATURES, r["x"])))[2] < r["tau"]
    unsafe = [r for r in rows if r["y"] == 1]
    safe = [r for r in rows if r["y"] == 0]
    return {"n": len(rows), "UAR": round(sum(map(allowed, unsafe)) / max(1, len(unsafe)), 4),
            "safe_auto": round(sum(map(allowed, safe)) / max(1, len(safe)), 4)}


def retrain(current: RiskModel, labels: list[dict], weight: float = 3.0, max_drop: float = 0.02, seed: int = 0,
            exclude_approvers: set[str] | None = None) -> dict:
    """Fit a candidate on training rows + feedback; gate it on the frozen test split. Returns a report with the
    candidate model (`model`) and `promote` (True/False)."""
    doc, data = current.doc, current.data
    if not doc or not data.get("train") or not data.get("test_system"):
        raise ValueError("the current model has no stored training rows (run python -m bench.conformal)")
    Xf, yf = feedback_rows(labels, exclude_approvers)
    X = np.vstack([np.array(data["train"]["X"], dtype=float), Xf]) if len(yf) else np.array(data["train"]["X"])
    y = np.concatenate([np.array(data["train"]["y"]), yf]) if len(yf) else np.array(data["train"]["y"])
    w = np.concatenate([np.ones(len(data["train"]["y"])), np.full(len(yf), weight)])
    new = fit(X, y, np.array(data["cal"]["X"], dtype=float), np.array(data["cal"]["y"]),
              n_boot=doc.get("meta", {}).get("n_boot", 25), seed=seed, sample_weight=w)
    new["meta"].update({k: v for k, v in doc.get("meta", {}).items() if k in ("operating_point", "data_note")})
    new["meta"].update({"parent": current.sha, "feedback_labels": int(len(yf)), "feedback_weight": weight,
                        "retrained_at": time.strftime("%Y-%m-%d %H:%M")})
    new["data"] = copy.deepcopy(data)
    cand = RiskModel(model=new)
    before, after = system_rates(current, data["test_system"]), system_rates(cand, data["test_system"])
    ok_safety = after["UAR"] <= before["UAR"]
    ok_autonomy = after["safe_auto"] >= before["safe_auto"] - max_drop
    return {"promote": bool(ok_safety and ok_autonomy and len(yf) > 0), "feedback_labels": int(len(yf)),
            "current": {"sha": current.sha, **before}, "candidate": {"sha": cand.sha, **after},
            "reasons": [r for r, bad in (("would auto-allow more unsafe test actions", not ok_safety),
                                         (f"safe auto-completion would drop more than {max_drop:.0%}", not ok_autonomy),
                                         ("no usable feedback labels yet", len(yf) == 0)) if bad],
            "model": new}


def apply(gw, report: dict, by: str) -> dict:
    """Promote (or record the refusal of) a retrained model; either way a receipt says what happened."""
    out = {k: v for k, v in report.items() if k != "model"}
    if report["promote"]:
        gw.risk = RiskModel(model=report["model"])
        if gw.store is not None:
            gw.store.save_model(report["model"])
    gw.receipts.append({"type": "risk-model-promoted" if report["promote"] else "risk-model-rejected", "by": by,
                        **{k: out[k] for k in ("feedback_labels", "current", "candidate", "reasons")}})
    return out
