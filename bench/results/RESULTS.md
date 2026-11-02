# KAVACH benchmark results

Suite: 880 labelled scenarios, 44 families; train 200 / calibration 80 / test 264 (all numbers below are on the held-out test split).

**Synthetic suite.** Not comparable with numbers published on AgentDojo / AmPermBench.

| System | UAR (unsafe auto-allowed) ↓ | Injection ASR ↓ | Safe auto-completed ↑ | Safe hard-blocked ↓ | Escalation rate | p50 / p95 ms |
|---|---|---|---|---|---|---|
| No guardrail | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | - |
| Static denylist (text match) | 86.1% | 100.0% | 100.0% | 0.0% | 0.0% | - |
| Tool-type gating | 37.5% | 25.0% | 45.0% | 0.0% | 59.1% | - |
| Approve every write (manual interrupt) | 4.2% | 0.0% | 10.0% | 0.0% | 93.2% | - |
| KAVACH: rules only | 4.2% | 0.0% | 95.0% | 0.0% | 20.4% | 0.42 / 0.79 |
| KAVACH: no provenance | 4.2% | 12.5% | 95.0% | 0.0% | 37.5% | 0.41 / 0.91 |
| KAVACH: fixed threshold | 0.0% | 0.0% | 95.0% | 0.0% | 22.7% | 0.42 / 0.77 |
| KAVACH (full) | 0.0% | 0.0% | 95.0% | 0.0% | 22.7% | 0.43 / 0.96 |

Calibration on test split: ECE 0.014 (raw) -> 0.001 (isotonic), Brier 0.0.

Operating points chosen on the calibration split: C_block=0.002 (KAVACH), fixed tau=0.02 (ablation).

Latency excludes the optional Qualcomm LLM judge.

## Robustness: 5 independent suites and splits (mean, min–max)

| System | Unsafe auto-allowed | Injection ASR | Safe auto-completed | Safe hard-blocked | Escalation |
|---|---|---|---|---|---|
| No guardrail | 100.0% (100%–100%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 0.0% (0%–0%) |
| Static denylist (text match) | 86.4% (85%–88%) | 100.0% (100%–100%) | 100.0% (100%–100%) | 0.0% (0%–0%) | 0.0% (0%–0%) |
| Tool-type gating | 37.5% (38%–38%) | 25.0% (25%–25%) | 45.0% (45%–45%) | 0.0% (0%–0%) | 59.1% (59%–59%) |
| Approve every write (manual interrupt) | 4.2% (4%–4%) | 0.0% (0%–0%) | 10.0% (10%–10%) | 0.0% (0%–0%) | 93.2% (93%–93%) |
| KAVACH: rules only | 4.2% (4%–4%) | 0.0% (0%–0%) | 95.0% (95%–95%) | 0.0% (0%–0%) | 20.4% (20%–20%) |
| KAVACH: no provenance | 4.2% (4%–4%) | 12.5% (12%–12%) | 95.0% (95%–95%) | 0.0% (0%–0%) | 37.8% (37%–39%) |
| KAVACH: fixed threshold | 0.0% (0%–0%) | 0.0% (0%–0%) | 95.0% (95%–95%) | 0.0% (0%–0%) | 22.7% (23%–23%) |
| KAVACH (full) | 0.0% (0%–0%) | 0.0% (0%–0%) | 95.0% (95%–95%) | 0.0% (0%–0%) | 22.7% (23%–23%) |

ECE (calibrated) per seed: [0.001, 0.0011, 0.0011, 0.0012, 0.0011]; C_block selected per seed: [0.002, 0.002, 0.002, 0.002, 0.002]
