"""E11: conformal risk control (the cutoff and its guarantee) and the human-feedback learning loop."""
import math

import numpy as np

from kavach.conformal import bound, crc_lambda, min_alpha
from kavach.risk import RiskModel


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
