"""E11: conformal risk control (the cutoff and its guarantee) and the human-feedback learning loop."""
import math
import tempfile

import numpy as np
import pytest

from kavach.conformal import bound, crc_lambda, min_alpha
from kavach.environment import Environment
from kavach.gateway import GatewayConfig, Kavach
from kavach.learning import apply, retrain, system_rates
from kavach.models import ToolCall, Verdict
from kavach.risk import FEATURES, RiskModel


def test_cutoff_keeps_the_calibration_bound_within_alpha():
    rng = np.random.default_rng(0)
    s = rng.uniform(0, 1, 199)
    for a in (0.01, 0.05, 0.1, 0.3):
        lam = crc_lambda(s, a)
        assert bound(len(s), int((s < lam).sum())) <= a + 1e-12
        assert bound(len(s), int((s <= lam).sum())) > a          # and it is the largest such cutoff
    assert crc_lambda(s, 0.001) == 0.0 and min_alpha(199) == 0.005  # too little data: nothing auto-allowed


def test_rules_stopping_everything_make_the_cap_free():
    assert crc_lambda([math.inf] * 104, 0.05) == math.inf and round(bound(104, 0), 4) == 0.0095


def test_the_guarantee_holds_on_fresh_draws():
    """Exchangeable calibration and test draws: the average unsafe auto-allow rate stays within alpha."""
    rng = np.random.default_rng(1)
    rates = []
    for _ in range(400):
        cal, test = rng.beta(2, 5, 60), rng.beta(2, 5, 200)
        lam = crc_lambda(cal, 0.1)
        rates.append(float((test < lam).mean()))
    assert np.mean(rates) <= 0.1 + 0.01


def test_the_shipped_model_carries_its_calibration_rows():
    rm = RiskModel()
    assert rm.data.get("cal_system") and rm.conformal_lambda(0.05) is not None


def stub_model(score_unsafe_cal: list[float]) -> RiskModel:
    """A copy of the shipped model whose calibration split has unsafe actions the model would allow."""
    rm = RiskModel()
    doc = dict(rm.doc)
    x = [0.0] * len(FEATURES)
    doc["data"] = dict(rm.data, cal_system=[{"x": x, "floor": "PASS", "tau": 1.0, "y": 1} for _ in score_unsafe_cal])
    m = RiskModel(model=doc)
    m.conformal_scores = lambda: np.array(score_unsafe_cal)          # noqa: E731  (scores fixed for the test)
    return m


def test_the_cap_sends_a_low_confidence_allow_to_a_person():
    risk = stub_model([0.0001] * 5 + [0.9] * 95)                       # lambda(0.1) = 0.9; lambda(0.02) = 0.0001
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False, conformal_alpha=0.02), risk=risk)
    tid, _ = gw.start_task("ravi", "analyst", "Email john.menon@client4.com that invoice 1042 is being processed.")
    d = gw.check(tid, ToolCall("mail.send", {"to": "john.menon@client4.com", "subject": "Invoice 1042",
                                             "body": "Hi John, invoice 1042 is being processed. Regards, Ravi"}))
    assert d.verdict == Verdict.ESCALATE and d.reason.startswith("Conformal cap")
    gw.cfg.conformal_alpha = 0.1
    assert gw.check(tid, d.call).verdict == Verdict.ALLOW_WITH_SAFEGUARD
    read = gw.check(tid, ToolCall("crm.query", {"sql": "SELECT COUNT(*) FROM customers"}))
    assert read.verdict == Verdict.ALLOW                               # reads lose nothing: never capped


def labels_from(rows, n, unsafe):
    out = []
    for r in rows[:n]:
        out.append({"features": dict(zip(FEATURES, r["x"])), "label_unsafe": unsafe, "approver": "asha",
                    "floor": r["floor"]})
    return out


def test_retrain_promotes_only_past_the_gate_and_receipts_it():
    rm = RiskModel()
    rows = [r for r in rm.data["test_system"] if r["x"] is not None and r["floor"] == "PASS"]
    rep = retrain(rm, [])
    assert not rep["promote"] and "no usable feedback labels yet" in rep["reasons"]
    good = labels_from([r for r in rows if r["y"] == 0], 10, 0) + labels_from([r for r in rows if r["y"] == 1], 10, 1)
    ruled = labels_from([r for r in rm.data["test_system"] if r["floor"] == "REQUIRE_APPROVAL" and r["x"]], 5, 1)
    assert retrain(rm, ruled)["feedback_labels"] == 0                 # rule escalations don't teach the model
    rep = retrain(rm, good)
    assert rep["candidate"]["UAR"] <= rep["current"]["UAR"] and rep["promote"], rep["reasons"]
    gw = Kavach(Environment(tempfile.mkdtemp()), GatewayConfig(use_llm_judge=False))
    out = apply(gw, rep, "admin")
    assert gw.risk.sha == rep["candidate"]["sha"] and gw.risk.meta["parent"] == rm.sha
    assert gw.receipts.items[-1]["body"]["type"] == "risk-model-promoted" and "model" not in out


def test_poisoned_feedback_is_refused():
    """An approver who approves unsafe actions (fatigue, or an insider) must not teach the model to allow them."""
    rm = RiskModel()
    unsafe = [r for r in rm.data["test_system"] if r["x"] is not None and r["y"] == 1 and r["floor"] == "PASS"]
    bad = labels_from(unsafe, len(unsafe), 0) * 30
    rep = retrain(rm, bad, weight=10.0)
    if rep["candidate"]["UAR"] > rep["current"]["UAR"]:
        assert not rep["promote"] and "would auto-allow more unsafe test actions" in rep["reasons"]
    assert system_rates(rm, rm.data["test_system"])["UAR"] == rep["current"]["UAR"]
    assert retrain(rm, bad, exclude_approvers={"asha"})["feedback_labels"] == 0
