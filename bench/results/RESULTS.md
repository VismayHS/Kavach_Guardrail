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
| KAVACH: rules only | 3.9% | 0.0% | 0.0% | 95.2% | 0.0% | 23.4% | 94.7% | 1.82 / 3.95 |
| KAVACH: no provenance | 3.9% | 0.0% | 12.5% | 90.5% | 0.0% | 41.5% | 94.4% | 1.76 / 4.63 |
| KAVACH: fixed threshold | 0.0% | 0.0% | 0.0% | 95.2% | 0.0% | 25.5% | 94.4% | 1.69 / 3.47 |
| KAVACH: no undo windows | 0.0% | 0.0% | 0.0% | 95.2% | 0.0% | 25.5% | 38.9% | 1.47 / 2.78 |
| KAVACH (full) | 0.0% | 0.0% | 0.0% | 95.2% | 0.0% | 25.5% | 94.4% | 1.47 / 3.38 |

Calibration on test split: ECE 0.0149 (raw) -> 0.0012 (isotonic), Brier 0.0.

Operating points chosen on the calibration split: C_block=0.002 (KAVACH), fixed tau=0.05 (ablation).

Latency excludes the optional Qualcomm LLM judge.

## Robustness: 5 independent suites and splits (mean, min–max)

| System | Unsafe auto-allowed | ...with no undo | Injection ASR | Safe auto-completed | Safe hard-blocked | Escalation | Changes with undo armed |
|---|---|---|---|---|---|---|---|
| No guardrail | 100.0% (100%–100%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 0.0% (0%–0%) |
| Static denylist (text match) | 87.4% (87%–88%) | 87.4% (87%–88%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 0.0% (0%–0%) |
| Tool-type gating | 38.5% (38%–38%) | 38.5% (38%–38%) | 25.0% (25%–25%) | 47.6% (48%–48%) | 0.0% (0%–0%) | 57.5% (57%–57%) | 0.0% (0%–0%) |
| Approve every write (manual interrupt) | 3.9% (4%–4%) | 3.9% (4%–4%) | 0.0% (0%–0%) | 9.5% (10%–10%) | 0.0% (0%–0%) | 93.6% (94%–94%) | 0.0% (0%–0%) |
| KAVACH: rules only | 3.9% (4%–4%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 95.2% (95%–95%) | 0.0% (0%–0%) | 23.4% (23%–23%) | 94.7% (95%–95%) |
| KAVACH: no provenance | 3.9% (4%–4%) | 0.0% (0%–0%) | 12.5% (12%–12%) | 90.5% (90%–90%) | 0.0% (0%–0%) | 41.8% (41%–43%) | 94.4% (94%–94%) |
| KAVACH: fixed threshold | 0.0% (0%–0%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 95.2% (95%–95%) | 0.0% (0%–0%) | 25.5% (26%–26%) | 94.4% (94%–94%) |
| KAVACH: no undo windows | 0.0% (0%–0%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 95.2% (95%–95%) | 0.0% (0%–0%) | 25.5% (26%–26%) | 38.9% (39%–39%) |
| KAVACH (full) | 0.0% (0%–0%) | 0.0% (0%–0%) | 0.0% (0%–0%) | 95.2% (95%–95%) | 0.0% (0%–0%) | 25.5% (26%–26%) | 94.4% (94%–94%) |

ECE (calibrated) per seed: [0.0012, 0.0012, 0.0013, 0.0011, 0.0013]; C_block selected per seed: [0.002, 0.002, 0.002, 0.002, 0.002]
