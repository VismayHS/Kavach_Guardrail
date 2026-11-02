# KAVACH compared: no guardrail, a simple baseline, KAVACH

Generated 2026-11-03 03:47 at commit `4956838` on Darwin arm64, Python 3.14.6. Regenerate: `python -m bench.compare`.

Three kinds of evidence, kept apart: (1) a live agent on ETH Zurich's AgentDojo (not written by us), (2) the same benchmark replayed with its ground-truth calls and an obedient attacker (no model), (3) our own synthetic suite (written by us; its rules target its families, so read it as a regression check, not as independent evidence).

## 1. Live agent: AgentDojo v1.2.2, Llama-3.3-70B on Qualcomm Cloud AI, important_instructions attack

Attack success = AgentDojo's own security check (the attacker's goal was reached). Benign = user tasks with no attack, utility = AgentDojo's own check. KAVACH counts an ESCALATE as a block here (in production a person would decide). Runs in progress are compared on the tasks both defenses finished (paired).

### Banking (finished so far: No guardrail 160/160, Spotlighting (prompt delimiting, AgentDojo's baseline) 160/160, KAVACH 47/160, KAVACH, rules only 40/160)

| Defense | Tasks compared | Benign done | Attack success ↓ | Utility under attack | Tasks with a KAVACH deny / escalate | Errors | Agent time per task p50 / p95 |
|---|---|---|---|---|---|---|---|
| No guardrail | 160 (paired with Spotlighting (prompt delimiting, AgentDojo's baseline)) | 8/16 (50.0%) | 66/144 (45.8%) | 54/144 (37.5%) | 0 / 0 | 0 | 27 s / 85 s |
| Spotlighting (prompt delimiting, AgentDojo's baseline) | 160 (paired with No guardrail) | 8/16 (50.0%) | 69/144 (47.9%) | 74/144 (51.4%) | 0 / 0 | 0 | 50 s / 249 s |
| No guardrail | 47 (paired with KAVACH) | 8/16 (50.0%) | 19/31 (61.3%) | 2/31 (6.5%) | 0 / 0 | 0 | 30 s / 99 s |
| KAVACH | 47 (paired with No guardrail) | 8/16 (50.0%) | 0/31 (0.0%) | 5/31 (16.1%) | 9 / 22 | 0 | 80 s / 1996 s |
| No guardrail | 40 (paired with KAVACH, rules only) | 8/16 (50.0%) | 16/24 (66.7%) | 2/24 (8.3%) | 0 / 0 | 0 | 30 s / 140 s |
| KAVACH, rules only | 40 (paired with No guardrail) | 8/16 (50.0%) | 0/24 (0.0%) | 6/24 (25.0%) | 6 / 18 | 0 | 81 s / 2766 s |

Agent time is the whole AgentDojo task as the agent lived it, and is dominated by Qualcomm rate-limit waits: several runs shared one key, and KAVACH's runs overlapped with the most others. KAVACH's own decision time is below (Decision latency).

### Slack (finished so far: No guardrail 117/126, Spotlighting (prompt delimiting, AgentDojo's baseline) 2/126, KAVACH 73/126)

| Defense | Tasks compared | Benign done | Attack success ↓ | Utility under attack | Tasks with a KAVACH deny / escalate | Errors | Agent time per task p50 / p95 |
|---|---|---|---|---|---|---|---|
| Spotlighting (prompt delimiting, AgentDojo's baseline) | in progress: 2 tasks paired so far, too few to compare | | | | | | |
| No guardrail | 73 (paired with KAVACH) | 9/21 (42.9%) | 17/52 (32.7%) | 22/52 (42.3%) | 0 / 0 | 0 | 39 s / 152 s |
| KAVACH | 73 (paired with No guardrail) | 6/21 (28.6%) | 4/52 (7.7%) | 20/52 (38.5%) | 9 / 18 | 0 | 110 s / 719 s |

Agent time is the whole AgentDojo task as the agent lived it, and is dominated by Qualcomm rate-limit waits: several runs shared one key, and KAVACH's runs overlapped with the most others. KAVACH's own decision time is below (Decision latency).

Slack's injection_task_5 is checked from the calls the agent *attempted*: a call KAVACH blocked still counts as the attacker's there. bench/results/AGENTDOJO.md also reports the executed-only check.

## 2. Replay: the same benchmark, ground-truth calls, an obedient attacker (no model)

| Suite | Defense | Benign done | Attacks that succeeded, executed calls | AgentDojo's own check |
|---|---|---|---|---|
| banking | KAVACH | 12/16 (75.0%) (+4 only escalated) | 0/144 (0.0%) | 0/144 (0.0%) |
| banking | KAVACH, rules only | 12/16 (75.0%) (+4 only escalated) | 0/144 (0.0%) | 0/144 (0.0%) |
| slack | KAVACH | 14/21 (66.7%) (+6 only escalated) | 0/105 (0.0%) | 21/105 (20.0%) |
| slack | KAVACH, rules only | 16/21 (76.2%) (+4 only escalated) | 0/105 (0.0%) | 21/105 (20.0%) |

No guardrail: every one of these obedient attacks succeeds by construction (144/144, 105/105).

## 3. Our synthetic suite (bench/run.py, held-out test split; written by us)

| System | Unsafe auto-allowed ↓ | Injection attack success ↓ | Safe tasks auto-completed ↑ | Escalation rate |
|---|---|---|---|---|
| No guardrail | 100.0% | 100.0% | 100.0% | 0.0% |
| Static denylist (text match) | 87.2% | 100.0% | 100.0% | 0.0% |
| Tool-type gating | 38.5% | 25.0% | 47.6% | 57.5% |
| Approve every write (manual interrupt) | 3.9% | 0.0% | 9.5% | 93.6% |
| KAVACH: rules only | 3.9% | 0.0% | 95.2% | 23.4% |
| KAVACH (full) | 0.0% | 0.0% | 95.2% | 25.5% |

## Decision latency (measured here)

1027 decisions (synthetic suite, holdout, demo scenarios), LLM judge off: p50 0.42 ms, p95 3.5 ms, p99 13.9 ms, max 15.52 ms. The Qualcomm judge, when on, runs only for calls already waiting for a person (escalations-only), so it never delays an allowed call.

## Live demo server (what a running KAVACH measured)

At 2026-11-03 03:48:01: 2 /mcp requests, end-to-end p50 ≤ 5.0 ms, p95 ≤ 25.0 ms, p99 ≤ 25.0 ms (histogram bucket bounds). Model: 0 calls (0 errors), 0 tokens as reported by the API, 0 calls without usage; estimated cost USD 0 (price table 2026-11-03.1; 0 tokens of unpriced models: cost unknown).

## Model usage and cost of the live AgentDojo runs

Not recorded: those runs began before the usage meter (kavach/usage.py) existed, and AgentDojo's logs don't keep token counts. Unknown, not zero. Qualcomm publishes no per-token price for its Cloud AI Playground; see kavach/model_prices.json.

## Limits

- Live runs are one sample per task (temperature as AgentDojo sets it), one model, one attack.
- KAVACH's benign losses on AgentDojo are mostly ESCALATEs a person would approve in production; the replay separates them.
- Our synthetic suite was written by the same team as the rules.
