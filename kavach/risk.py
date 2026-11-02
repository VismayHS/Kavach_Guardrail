"""Risk model (stage 6): calibrated probability of harm + confidence interval,
and the reversibility-conditioned decision threshold.

    p      = P(action is unsafe or unintended | features)      bootstrap ensemble of
                                                                logistic models, isotonic-calibrated
    [p_lo, p_hi]                                                spread of the ensemble (epistemic
                                                                uncertainty; widens off-distribution)
    H      = harm magnitude in [0,1]                            from the consequence engine
    r      = recoverable fraction                               from the reversibility class
    EUH    = p * H * (1 - r)                                    expected unrecoverable harm
    tau    = min(p_ceiling, C_block / (H * (1 - r)))            allow iff EUH < C_block  <=>  p < tau
             (1 when H * (1 - r) = 0: a read can't lose anything, so rules alone decide)

Reversible actions get a permissive threshold (undo is armed); irreversible ones a
strict threshold. When the interval straddles tau the gateway escalates to a human
instead of guessing (selective prediction / "ask for help", cf. KnowNo, CoRL 2023).
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .manifest import ToolSpec, model_of
from .models import Effect, Label, Risk, Trust
from .provenance import arg_targets, named_targets

FEATURES = ["untrusted_control", "untrusted_data", "external_sink", "pii_out", "rows", "no_where", "ddl",
            "prod", "amount", "payee_unknown", "misalignment", "scope_excess", "irreversibility", "harm",
            "secret", "ingress_untrusted_url", "control_from_user", "target_mismatch"]

MODEL_PATH = Path(__file__).parent / "model" / "risk_model.json"

# Prior used before the model is trained (hand-set, documented; replaced by bench/train output)
PRIOR = {"intercept": -3.2, "coef": {"untrusted_control": 4.0, "untrusted_data": 0.6, "external_sink": 0.5,
         "pii_out": 1.2, "rows": 0.35, "no_where": 1.5, "ddl": 2.5, "prod": 0.3, "amount": 0.25,
         "payee_unknown": 1.5, "misalignment": 3.0, "scope_excess": 1.8, "irreversibility": 0.4, "harm": 1.0,
         "secret": 3.0, "ingress_untrusted_url": 1.5, "control_from_user": -2.0, "target_mismatch": 2.0}}



def featurize(spec: ToolSpec, args: dict, labels: dict[str, Label], effect: Effect, intent: dict, env: str,
              user_request: str = "") -> dict:
    m = effect.magnitude
    # targets the user named (ids, invoice numbers like INV-3040...) that a state-changing action ignores entirely
    named = named_targets(user_request)
    target_mismatch = float(bool(named) and spec.effect not in ("read", "ingress")
                            and not named & arg_targets(args))
    ctrl = [labels[a] for a in spec.control_args if a in labels]
    data = [labels[a] for a in spec.data_args if a in labels]
    rows = m.get("rows_affected", 0) or 0
    pii_out = m.get("pii_records", 0) if spec.sink == "external" else 0
    return {
        "untrusted_control": float(any(l.trust == Trust.UNTRUSTED for l in ctrl) and spec.effect != "ingress"),
        "untrusted_data": float(any(l.trust == Trust.UNTRUSTED for l in data)),
        "external_sink": float(spec.sink == "external"),
        "pii_out": math.log1p(pii_out),
        "rows": math.log1p(rows),
        "no_where": float(bool(m.get("no_where"))),
        "ddl": float(bool(m.get("ddl"))),
        "prod": float(env == "prod" and spec.effect not in ("read", "ingress")),
        "amount": math.log1p(float(m.get("amount", 0) or 0)) / 12.0,
        "payee_unknown": float(model_of(spec) == "transfer" and not m.get("payee_known", True)),
        "misalignment": 1.0 - float(intent.get("alignment", 0.5)),
        "scope_excess": float(rows > 5 and not intent.get("breadth_requested", False)),
        "irreversibility": 1.0 - spec.reversibility.recoverable_fraction,   # the tool's own; windows only move tau
        "harm": effect.harm,
        "secret": float(bool(m.get("secret"))),
        "ingress_untrusted_url": float(spec.effect == "ingress" and any(l.trust == Trust.UNTRUSTED for l in ctrl)),
        # positive provenance: every destination/amount argument was typed by the user
        "control_from_user": float(bool(ctrl) and all(l.trust == Trust.TRUSTED for l in ctrl)),
        "target_mismatch": target_mismatch,
    }


class RiskModel:
    def __init__(self, path: Path | None = None, model: dict | None = None):
        path = path or MODEL_PATH
        if model is not None or path.exists():
            d = model if model is not None else json.loads(path.read_text())
            self.W = np.array(d["coefs"])            # (n_boot, n_features)
            self.b = np.array(d["intercepts"])       # (n_boot,)
            self.iso_x = np.array(d["iso_x"])
            self.iso_y = np.array(d["iso_y"])
            self.mu = np.array(d["mu"])
            self.sd = np.array(d["sd"])
            self.source = f"trained ({d.get('n_train', '?')} labelled actions, {len(self.b)} bootstrap models)"
            self.meta = d.get("meta", {})
            self.data = d.get("data") or {}          # the train / calibration / test rows (E11), when stored
            self.sha = __import__("hashlib").sha256(json.dumps({k: d[k] for k in ("coefs", "intercepts", "iso_y")}
                                                               ).encode()).hexdigest()[:12]
        else:
            w = np.array([PRIOR["coef"][f] for f in FEATURES])
            self.W, self.b = w[None, :], np.array([PRIOR["intercept"]])
            self.iso_x = self.iso_y = None
            self.mu, self.sd = np.zeros(len(FEATURES)), np.ones(len(FEATURES))
            self.source = "prior (untrained)"
            self.meta = {}
            self.data = {}
            self.sha = "prior"
        self._lam: dict[float, float] = {}
        self.doc = d if (model is not None or path.exists()) else None    # the model file, for retraining

    def _calibrate(self, p: np.ndarray) -> np.ndarray:
        if self.iso_x is None:
            return p
        return np.interp(p, self.iso_x, self.iso_y)

    def predict(self, feats: dict) -> tuple[float, float, float]:
        return self._predict_x(np.array([feats[f] for f in FEATURES]))

    def scores(self, X) -> np.ndarray:
        """p_hi (the score the gateway compares with tau) for each row of a feature matrix."""
        return np.array([self._predict_x(np.asarray(x, dtype=float))[2] for x in X])

    def conformal_scores(self) -> np.ndarray | None:
        """E11: for each unsafe calibration action, the score at which the whole gateway would auto-allow it: p_hi
        if the rules let it through and p_hi < tau, else +inf (a rule or tau stops it whatever the cutoff). Uses the
        current weights, so a retrained model gets its own cutoff."""
        cal = self.data.get("cal_system")
        if not cal:
            return None
        out = []
        for r in cal:
            if r["y"] != 1:
                continue
            if r["floor"] != "PASS" or r["x"] is None:
                out.append(np.inf)
                continue
            p_hi = self._predict_x(np.asarray(r["x"], dtype=float))[2]
            out.append(p_hi if p_hi < r["tau"] else np.inf)
        return np.array(out)

    def conformal_lambda(self, alpha: float) -> float | None:
        """E11: the conformal cutoff for this alpha (None when no calibration rows are stored)."""
        if alpha not in self._lam:
            s = self.conformal_scores()
            if s is None:
                return None
            from .conformal import crc_lambda
            self._lam[alpha] = crc_lambda(s, alpha)
        return self._lam[alpha]

    def _predict_x(self, x: np.ndarray) -> tuple[float, float, float]:
        x = (x - self.mu) / self.sd
        z = self.W @ x + self.b
        ps = self._calibrate(1 / (1 + np.exp(-z)))
        p = float(np.median(ps))
        if len(ps) > 1:
            lo, hi = float(np.quantile(ps, 0.1)), float(np.quantile(ps, 0.9))
        else:
            lo, hi = max(0.0, p - 0.1), min(1.0, p + 0.1)
        return p, lo, hi

    def assess(self, feats: dict, effect: Effect, c_block: float, intent: dict, p_ceiling: float = 0.5) -> Risk:
        p, lo, hi = self.predict(feats)
        r = effect.reversibility.recoverable_fraction
        exposure = effect.harm * (1 - r)
        # Nothing can be lost (idempotent reads): expected unrecoverable harm is 0 whatever p is, so rules decide
        # (R9 secrets, R13 URLs, R1 untrusted fetches). Otherwise p_ceiling: undo only helps if someone notices,
        # so an action that is more likely unintended than not is never auto-executed, however reversible it is.
        tau = 1.0 if exposure <= 1e-6 else min(p_ceiling, c_block / exposure)
        return Risk(round(p, 4), round(lo, 4), round(hi, 4), round(tau, 4), round(p * exposure, 5),
                    {k: round(v, 3) for k, v in feats.items()}, intent)


def fit(X: np.ndarray, y: np.ndarray, X_cal: np.ndarray, y_cal: np.ndarray, n_boot: int = 25, seed: int = 0,
        sample_weight: np.ndarray | None = None) -> dict:
    """Bootstrap logistic regression + isotonic calibration (the model file format RiskModel loads). Used by
    bench/run.py to train and by kavach/learning.py to retrain with human feedback (E11)."""
    import time
    from sklearn.isotonic import IsotonicRegression
    from sklearn.linear_model import LogisticRegression

    mu, sd = X.mean(0), X.std(0) + 1e-6
    Xs, Xc = (X - mu) / sd, (X_cal - mu) / sd
    rng = np.random.default_rng(seed)
    coefs, ints = [], []
    for _ in range(n_boot):
        idx = rng.integers(0, len(y), len(y))
        if len(set(y[idx])) < 2:
            continue
        w = None if sample_weight is None else sample_weight[idx]
        lr = LogisticRegression(C=0.5, max_iter=2000).fit(Xs[idx], y[idx], sample_weight=w)
        coefs.append(lr.coef_[0].tolist())
        ints.append(float(lr.intercept_[0]))
    W, b = np.array(coefs), np.array(ints)
    raw_cal = np.median(1 / (1 + np.exp(-(Xc @ W.T + b))), axis=1)
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999).fit(raw_cal, y_cal)
    xs = np.linspace(0, 1, 101)
    return {"coefs": coefs, "intercepts": ints, "mu": mu.tolist(), "sd": sd.tolist(),
            "iso_x": xs.tolist(), "iso_y": iso.predict(xs).tolist(), "features": FEATURES,
            "n_train": int(len(y)), "n_cal": int(len(y_cal)),
            "meta": {"model": "bootstrap logistic regression + isotonic calibration", "n_boot": len(ints),
                     "trained_at": time.strftime("%Y-%m-%d %H:%M")}}
