"""Conformal risk control (E11): a cutoff for the risk model with a stated, finite-sample guarantee.

The risk model's threshold tau comes from a cost argument (allow iff p·H·(1−r) < C_block), and the operating point was
picked on a calibration split. That is a good rule, but it promises nothing about new traffic. Conformal risk control
(Angelopoulos, Bates, Fisch, Lei, Schuster, "Conformal Risk Control", ICLR 2024) turns the same calibration split
into a promise:

    For an unsafe action exchangeable with the unsafe calibration actions,
        P(KAVACH auto-allows it) <= alpha            (rules, tau and the cutoff together)

How: for each of the n unsafe actions in the calibration split, s_i is the score at which the whole gateway would
auto-allow it: the model's p_hi if the rules let it through and p_hi < tau, and +inf if a rule (or tau) stops it
whatever the cutoff. The loss of a cutoff lambda is L_i(lambda) = 1{s_i < lambda} ("this unsafe action would be
auto-allowed"). L is non-decreasing in lambda and bounded by B = 1, so the largest lambda with
(n·R_n(lambda) + B) / (n + 1) <= alpha satisfies E[L_{n+1}(lambda)] <= alpha (the paper's Theorem 1, mirrored for a
non-decreasing loss). With KAVACH's cap on, the gateway auto-allows only if p_hi < min(tau, lambda). When the rules
already stop every unsafe calibration action, lambda is +inf: the cap never binds, and the bound 1/(n+1) is a
certificate for the gateway as it is.

What it is not: the guarantee is marginal and class-conditional (over unsafe actions like the calibration ones). It
says nothing about attacks unlike anything in the calibration data (rules and provenance are for those), and it needs
n >= 1/alpha − 1 unsafe calibration examples; with fewer, lambda is 0 and the model alone allows nothing. It is an
expectation over draws of calibration and test data, not a high-probability statement about one deployment.
"""
from __future__ import annotations

import math

import numpy as np


def crc_lambda(scores_unsafe, alpha: float, B: float = 1.0) -> float:
    """The largest cutoff whose conformal bound on the unsafe auto-allow rate is <= alpha."""
    s = np.sort(np.asarray(list(scores_unsafe), dtype=float))
    n = len(s)
    k = math.floor(alpha * (n + 1) - B)          # how many calibration misses the bound tolerates
    if n == 0 or k < 0:
        return 0.0                               # not enough data for this alpha: the model alone allows nothing
    if k >= n:
        return math.inf                          # every calibration example could be missed and still be within alpha
    return float(s[k])                           # at most k scores lie strictly below it (+inf if rules stop the rest)


def bound(n_unsafe: int, misses: int, B: float = 1.0) -> float:
    """The conformal bound (n·R_n + B) / (n + 1) for a given number of calibration misses."""
    return (misses + B) / (n_unsafe + 1)


def min_alpha(n_unsafe: int, B: float = 1.0) -> float:
    """The smallest alpha this much calibration data can promise (with zero misses)."""
    return B / (n_unsafe + 1)
