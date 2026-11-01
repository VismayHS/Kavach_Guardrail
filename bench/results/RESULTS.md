# KAVACH benchmark results

Suite: 880 labelled scenarios, 44 families; train 260 / calibration 104 / test 264 (all numbers below are on the held-out test split).

**Synthetic suite.** Not comparable with numbers published on AgentDojo / AmPermBench.

| System | UAR (unsafe auto-allowed) ↓ | Injection ASR ↓ | Safe auto-completed ↑ | Safe hard-blocked ↓ | Escalation rate | p50 / p95 ms |
|---|---|---|---|---|---|---|
| No guardrail | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | - |
| Static denylist (text match) | 86.1% | 100.0% | 100.0% | 0.0% | 0.0% | - |
| Tool-type gating | 37.5% | 25.0% | 45.0% | 0.0% | 59.1% | - |
| Approve every write (manual interrupt) | 4.2% | 0.0% | 10.0% | 0.0% | 93.2% | - |
| KAVACH: rules only | 29.2% | 0.0% | 95.0% | 0.0% | 6.8% | 0.25 / 0.72 |
| KAVACH: no provenance | 0.7% | 0.0% | 45.8% | 0.0% | 61.7% | 0.25 / 0.77 |
| KAVACH: fixed threshold | 0.7% | 0.0% | 80.0% | 0.0% | 29.2% | 0.24 / 0.41 |
| KAVACH (full) | 0.7% | 0.0% | 80.0% | 0.0% | 29.2% | 0.25 / 0.44 |

Calibration on test split: ECE 0.0704 (raw) -> 0.0109 (isotonic), Brier 0.0483.

Operating points chosen on the calibration split: C_block=0.002 (KAVACH), fixed tau=0.25 (ablation).

Latency excludes the optional Qualcomm LLM judge.

## Robustness: 5 independent suites and splits (mean, min–max)

| System | Unsafe auto-allowed | Injection ASR | Safe auto-completed | Safe hard-blocked | Escalation |
|---|---|---|---|---|---|
| No guardrail | 100.0% (100%–100%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 0.0% (0%–0%) |
| Static denylist (text match) | 86.4% (85%–88%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 0.0% (0%–0%) |
| Tool-type gating | 37.5% (38%–38%) | 25.0% (25%–25%) | 45.0% (45%–45%) | 0.0% (0%–0%) | 59.1% (59%–59%) |
| Approve every write (manual interrupt) | 4.2% (4%–4%) | 0.0% (0%–0%) | 10.0% (10%–10%) | 0.0% (0%–0%) | 93.2% (93%–93%) |
| KAVACH: rules only | 29.2% (29%–29%) | 0.0% (0%–0%) | 95.0% (95%–95%) | 0.0% (0%–0%) | 6.8% (7%–7%) |
| KAVACH: no provenance | 1.0% (0%–2%) | 0.4% (0%–2%) | 45.3% (45%–46%) | 0.0% (0%–0%) | 62.1% (61%–63%) |
| KAVACH: fixed threshold | 0.4% (0%–1%) | 0.0% (0%–0%) | 80.2% (80%–81%) | 0.0% (0%–0%) | 29.2% (28%–30%) |
| KAVACH (full) | 0.8% (0%–2%) | 0.0% (0%–0%) | 80.3% (80%–81%) | 0.0% (0%–0%) | 28.9% (28%–30%) |

ECE (calibrated) per seed: [0.0109, 0.0415, 0.0218, 0.0114, 0.0139]; C_block selected per seed: [0.002, 0.002, 0.005, 0.002, 0.002]
