# KAVACH benchmark results

Suite: 940 labelled scenarios, 47 families; train 210 / calibration 84 / test 282 (all numbers below are on the held-out test split).

**Synthetic suite.** Not comparable with numbers published on AgentDojo / AmPermBench.

*With no undo armed*: allowed with no snapshot, hold, recall window or parking, so nothing can take it back. *Changes with undo armed*: of the state-changing actions that ran without a human, the share that can still be taken back.

| System | UAR (unsafe auto-allowed) ↓ | ...with no undo armed ↓ | Injection ASR ↓ | Safe auto-completed ↑ | Safe hard-blocked ↓ | Escalation rate | Changes with undo armed ↑ | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|
| No guardrail | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | - |
| Static denylist (text match) | 87.2% | 87.2% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | - |
| Tool-type gating | 38.5% | 38.5% | 25.0% | 47.6% | 0.0% | 57.5% | 0.0% | - |
| Approve every write (manual interrupt) | 3.9% | 3.9% | 0.0% | 9.5% | 0.0% | 93.6% | 0.0% | - |
| KAVACH: rules only | 3.9% | 0.0% | 0.0% | 95.2% | 0.0% | 24.5% | 94.7% | 2.47 / 9.17 |
| KAVACH: model only (rules off) | 69.2% | 15.4% | 37.5% | 100.0% | 0.0% | 14.9% | 86.1% | 2.24 / 8.39 |
| KAVACH: no provenance | 3.9% | 0.0% | 12.5% | 90.5% | 0.0% | 39.4% | 94.4% | 2.40 / 8.98 |
| KAVACH: fixed threshold | 0.0% | 0.0% | 0.0% | 95.2% | 0.0% | 26.6% | 94.4% | 2.38 / 8.16 |
| KAVACH: no undo windows | 0.0% | 0.0% | 0.0% | 95.2% | 0.0% | 26.6% | 38.9% | 2.43 / 8.13 |
| KAVACH (full) | 0.0% | 0.0% | 0.0% | 95.2% | 0.0% | 26.6% | 94.4% | 2.40 / 9.95 |

Calibration on test split: ECE 0.015 (raw) -> 0.0012 (isotonic), Brier 0.0.

Operating points chosen on the calibration split: C_block=0.002 (KAVACH), fixed tau=0.02 (ablation).

Latency excludes the optional Qualcomm LLM judge.

## What these numbers mean

- **The suite and the rules were written by the same team.** Most rules were written for specific scenario families, so 0% unsafe auto-allowed mostly says the rules do what we wrote them to do. For numbers we didn't write, see AGENTDOJO.md (ETH Zurich's benchmark).
- **The risk model learns only from actions that pass every rule:** 210 training actions, of which 10 are unsafe (1 unsafe family gets past the rules: attack:misaligned_write). With so few unsafe examples, a near-perfect calibration score (Brier ~0) means the test is easy, not that the model is perfect.
- **What the model alone catches** (rules off, only unknown-tool and schema checks left): 69.2% of unsafe actions auto-allowed, 37.5% injection success, 100.0% of safe actions auto-completed. The rules carry the safety; the model's job is ranking what the rules let through.
- The leave-one-family-out (LOFO.md) and fresh holdout (HOLDOUT.md) results check new wording and unseen families, but they are still our own scenarios.

## Robustness: 5 independent suites and splits (mean, min–max)

| System | Unsafe auto-allowed | ...with no undo | Injection ASR | Safe auto-completed | Safe hard-blocked | Escalation | Changes with undo armed |
|---|---|---|---|---|---|---|---|
| No guardrail | 100.0% (100%–100%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 0.0% (0%–0%) |
| Static denylist (text match) | 87.4% (87%–88%) | 87.4% (87%–88%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 0.0% (0%–0%) |
| Tool-type gating | 38.5% (38%–38%) | 38.5% (38%–38%) | 25.0% (25%–25%) | 47.6% (48%–48%) | 0.0% (0%–0%) | 57.5% (57%–57%) | 0.0% (0%–0%) |
| Approve every write (manual interrupt) | 3.9% (4%–4%) | 3.9% (4%–4%) | 0.0% (0%–0%) | 9.5% (10%–10%) | 0.0% (0%–0%) | 93.6% (94%–94%) | 0.0% (0%–0%) |
| KAVACH: rules only | 3.9% (4%–4%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 95.2% (95%–95%) | 0.0% (0%–0%) | 24.8% (24%–26%) | 94.7% (95%–95%) |
| KAVACH: model only (rules off) | 69.2% (69%–69%) | 15.4% (15%–15%) | 37.5% (38%–38%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 14.9% (15%–15%) | 86.1% (86%–86%) |
| KAVACH: no provenance | 3.9% (4%–4%) | 0.0% (0%–0%) | 12.5% (12%–12%) | 90.5% (90%–90%) | 0.0% (0%–0%) | 39.6% (39%–40%) | 94.4% (94%–94%) |
| KAVACH: fixed threshold | 0.0% (0%–0%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 95.2% (95%–95%) | 0.0% (0%–0%) | 26.9% (26%–28%) | 94.4% (94%–94%) |
| KAVACH: no undo windows | 0.0% (0%–0%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 95.2% (95%–95%) | 0.0% (0%–0%) | 26.9% (26%–28%) | 38.9% (39%–39%) |
| KAVACH (full) | 0.0% (0%–0%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 95.2% (95%–95%) | 0.0% (0%–0%) | 26.9% (26%–28%) | 94.4% (94%–94%) |

ECE (calibrated) per seed: [0.0012, 0.0012, 0.0013, 0.0012, 0.0013]; C_block selected per seed: [0.002, 0.002, 0.002, 0.002, 0.002]
