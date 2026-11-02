# Conformal risk control (E11)

Conformal risk control (Angelopoulos et al., ICLR 2024) turns the calibration split into a promise about the **whole gateway**: for a new unsafe action exchangeable with the unsafe calibration actions, E[1{auto-allowed}] <= alpha. Each unsafe calibration action gets the score at which KAVACH would auto-allow it: the model's p_hi if the rules let it through and p_hi < tau, otherwise +inf. The cap then allows an action only if p_hi < min(tau, lambda(alpha)).

Calibration split: 188 actions, 104 unsafe. Of those, 4 get past the rules to the model, and 0 of these also score below tau (would be auto-allowed). Smallest alpha this data can promise: 0.0095 (1/(n+1)).

Rates on the **test split** (self-graded synthetic suite; see RESULTS.md for its limits). UAR = unsafe auto-allowed; safe auto = safe actions completed without a person.

| alpha | lambda | calibration misses | bound | UAR | safe auto |
|---|---|---|---|---|---|
| cap off | - | - | - | 0.000 | 0.952 |
| 0.01 | +inf (never binds) | 0 | 0.0095 | 0.000 | 0.952 |
| 0.02 | +inf (never binds) | 0 | 0.0095 | 0.000 | 0.952 |
| 0.05 | +inf (never binds) | 0 | 0.0095 | 0.000 | 0.952 |
| 0.1 | +inf (never binds) | 0 | 0.0095 | 0.000 | 0.952 |

Reading it:

- When lambda is +inf, the rules and tau already stop every unsafe calibration action, so the cap costs nothing, and 1/(n+1) is a certificate for the gateway as it is: on traffic like the calibration data, the expected unsafe auto-allow rate is at most that.
- The promise is only as good as exchangeability. This suite is ours (self-graded), and attacks unlike its examples are what the rules and provenance are for. It is an expectation over draws of data, not a high-probability bound for one deployment.
- Human decisions grow the calibration data: the learning loop (kavach/learning.py) refits with them, and the cutoff is recomputed with the new weights.

Turn it on with `GatewayConfig(conformal_alpha=0.05)` (server: `KAVACH_CONFORMAL_ALPHA=0.05`).
