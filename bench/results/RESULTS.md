# KAVACH benchmark results

Suite: 740 labelled scenarios, 37 families; train 360 / calibration 144 / test 222 (all numbers below are on the held-out test split).

**Synthetic suite.** Not comparable with numbers published on AgentDojo / AmPermBench.

| System | UAR (unsafe auto-allowed) ↓ | Injection ASR ↓ | Safe auto-completed ↑ | Safe hard-blocked ↓ | Escalation rate | p50 / p95 ms |
|---|---|---|---|---|---|---|
| No guardrail | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | - |
| Static denylist (text match) | 83.3% | 100.0% | 100.0% | 0.0% | 0.0% | - |
| Tool-type gating | 40.0% | 16.7% | 47.1% | 0.0% | 56.8% | - |
| Approve every write (manual interrupt) | 5.0% | 0.0% | 11.8% | 0.0% | 91.9% | - |
| KAVACH: rules only | 30.0% | 0.0% | 94.1% | 0.0% | 8.1% | 0.65 / 1.63 |
| KAVACH: no provenance | 0.8% | 0.0% | 41.2% | 0.0% | 63.1% | 0.71 / 1.71 |
| KAVACH: fixed threshold | 0.8% | 0.0% | 70.6% | 0.0% | 34.7% | 0.76 / 1.84 |
| KAVACH (full) | 0.8% | 0.0% | 70.6% | 0.0% | 34.7% | 0.83 / 2.32 |

Calibration on test split: ECE 0.1298 (raw) -> 0.0332 (isotonic), Brier 0.0559.

Operating points chosen on the calibration split: C_block=0.15 (KAVACH), fixed tau=0.3 (ablation).

Latency excludes the optional Qualcomm LLM judge.

## Robustness: 5 independent suites and splits (mean, min–max)

| System | Unsafe auto-allowed | Injection ASR | Safe auto-completed | Safe hard-blocked | Escalation |
|---|---|---|---|---|---|
| No guardrail | 100.0% (100%–100%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 0.0% (0%–0%) |
| Static denylist (text match) | 83.7% (82%–85%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 0.0% (0%–0%) |
| Tool-type gating | 40.0% (40%–40%) | 16.7% (17%–17%) | 47.1% (47%–47%) | 0.0% (0%–0%) | 56.8% (57%–57%) |
| Approve every write (manual interrupt) | 5.0% (5%–5%) | 0.0% (0%–0%) | 11.8% (12%–12%) | 0.0% (0%–0%) | 91.9% (92%–92%) |
| KAVACH: rules only | 30.0% (30%–30%) | 0.0% (0%–0%) | 94.1% (94%–94%) | 0.0% (0%–0%) | 8.1% (8%–8%) |
| KAVACH: no provenance | 0.5% (0%–2%) | 0.0% (0%–0%) | 48.2% (41%–53%) | 0.0% (0%–0%) | 60.4% (59%–63%) |
| KAVACH: fixed threshold | 0.5% (0%–2%) | 0.0% (0%–0%) | 69.4% (66%–72%) | 0.0% (0%–0%) | 35.4% (34%–37%) |
| KAVACH (full) | 0.5% (0%–2%) | 0.0% (0%–0%) | 68.4% (65%–71%) | 0.0% (0%–0%) | 35.9% (35%–38%) |

ECE (calibrated) per seed: [0.0332, 0.0234, 0.0413, 0.0859, 0.0678]; C_block selected per seed: [0.15, 0.02, 0.03, 0.04, 0.02]
