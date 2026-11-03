# KAVACH claim verification register

The deck is grounded in implementation, executed local tests and named saved experiments. These evidence types have different limits. A source audit proves what is implemented; a passing test proves its exercised case; a saved report records an earlier result. None alone establishes general safety or production readiness. No external benchmark or deployment was independently reproduced for this audit.

Numeric/source checks: 118/118 passed. Local test run: 521 passed, 14 skipped, 0 failed. Tests ran in the repository checkout. Test names, statuses and skip reasons are in `review/test_results.json`.

Corrections made by this audit: approval checks the stored digest but does not rerun full policy/tool-definition checks; REST `/api/v1/check` decides without executing unless the caller sets `execute`; authentication depends on the auth secret; live benchmark figures are explicitly saved summaries whose raw live-task logs are unavailable here.

Numeric checks recompute semantic and explanation totals from their case rows and offline replay totals from per-task records. Live AgentDojo summary denominators and rate arithmetic are checked; absent raw logs prevent independently validating the underlying live outcomes. Synthetic results remain team-authored, and their multiseed performance was not rerun.

## Slide evidence

### Slide 1: KAVACH

Pre-execution gateway with four outcomes.

**Evidence scope:** Code + local tests.

- [kavach/gateway.py:423](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/gateway.py:423)
- [kavach/models.py:44](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/models.py:44)

Relevant local test outcomes: {'passed': 12}.

### Slide 2: Project context & delivery scope

Delivered components and intended operator roles.

**Evidence scope:** Repository scope; user roles are intended users.

- [PRODUCT.md:15](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/PRODUCT.md:15)
- [kavach/server.py:111](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/server.py:111)

Relevant local test outcomes: {'passed': 7}.

### Slide 3: Problem Statement

Poisoned email, invoice substitution and scope expansion.

**Evidence scope:** Code + local regression cases.

- [THREAT_MODEL.md:3](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/THREAT_MODEL.md:3)
- [kavach/policy.py:468](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/policy.py:468)

Relevant local test outcomes: {'passed': 80}.

### Slide 4: Proposed Solution

Policy catalogue and synthetic headline.

**Evidence scope:** Code + checked saved synthetic results.

- [kavach/policies/default.yaml:105](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/policies/default.yaml:105)
- [bench/results/multiseed.json:343](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/multiseed.json:343)

Relevant local test outcomes: {'passed': 12}.

### Slide 5: Architecture & Technical Design

Components and execution ownership.

**Evidence scope:** Code + local tests; REST check executes only when the caller sets execute.

- [kavach/gateway.py:73](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/gateway.py:73)
- [kavach/server.py:314](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/server.py:314)
- [kavach/adapters/guard.py:11](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/adapters/guard.py:11)

Relevant local test outcomes: {'passed': 3}.

### Slide 6: AI Usage & Innovation

Default advisory judge and risk-zero finding.

**Evidence scope:** Code + local tests + saved semantic experiment.

- [kavach/gateway.py:53](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/gateway.py:53)
- [bench/results/layers.json:116](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/layers.json:116)
- [bench/results/semantic.json:653](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/semantic.json:653)

Relevant local test outcomes: {'passed': 6}.

### Slide 7: Readiness, Scalability & Security

Test result, prod profile and single writer.

**Evidence scope:** Local tests; no load or production-readiness proof.

- [kavach/profile.py:30](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/profile.py:30)
- [deploy/helm/kavach/templates/deployment.yaml:8](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/deploy/helm/kavach/templates/deployment.yaml:8)
- [deliverables/review/validation.json:3](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/deliverables/review/validation.json:3)

Relevant local test outcomes: {'passed': 6}.

### Slide 8: Demo: prove what actually happened

Demonstration procedure and effect evidence.

**Evidence scope:** Procedure + local tests + saved Claude report; stage demo not rerun.

- [DEMO.md:34](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/DEMO.md:34)
- [tests/test_trace.py:22](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/tests/test_trace.py:22)
- [bench/results/CLAUDE_WITH_WITHOUT.md:3](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/CLAUDE_WITH_WITHOUT.md:3)

Relevant local test outcomes: {'passed': 18}.

### Slide 9: Decision path: from call to effect

Decision then receipt then controlled effect.

**Evidence scope:** Code + local tests.

- [kavach/gateway.py:832](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/gateway.py:832)
- [kavach/receipts.py:37](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/receipts.py:37)

Relevant local test outcomes: {'passed': 7}.

### Slide 10: Provenance & policy: what is trusted

Origin, destination, finance and task-budget rules.

**Evidence scope:** Code + local regression tests; lineage inference has limits.

- [kavach/policy.py:230](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/policy.py:230)
- [kavach/policies/default.yaml:148](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/policies/default.yaml:148)
- [kavach/provenance.py:233](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/provenance.py:233)

Relevant local test outcomes: {'passed': 76}.

### Slide 11: Consequences & the real limits of undo

Operation-specific safeguards.

**Evidence scope:** Code + local tests; no recall after accepted delivery.

- [kavach/gateway.py:757](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/gateway.py:757)
- [kavach/consequence.py:53](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/consequence.py:53)
- [kavach/environment.py:518](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/environment.py:518)

Relevant local test outcomes: {'passed': 15}.

### Slide 12: Human approval is bound to the exact call

Digest-bound one-use approval and quorum.

**Evidence scope:** Code + local tests; no full policy recheck at approval time.

- [kavach/gateway.py:912](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/gateway.py:912)
- [kavach/gateway.py:918](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/gateway.py:918)
- [kavach/hitl.py:96](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/hitl.py:96)

Relevant local test outcomes: {'passed': 12}.

### Slide 13: Delivery, crash recovery & the kill switch

Unknown delivery, persistent windows, fail-closed receipts and pause.

**Evidence scope:** Code + local tests; unknown outcome is not exactly-once proof.

- [kavach/receipts.py:37](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/receipts.py:37)
- [kavach/gateway.py:336](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/gateway.py:336)
- [kavach/environment.py:346](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/environment.py:346)

Relevant local test outcomes: {'passed': 19}.

### Slide 14: Identity, receipts & verifiable evidence

Conditional auth, Ed25519 and checkpoint verification.

**Evidence scope:** Code + local tests; auth/signing must be configured.

- [kavach/server.py:163](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/server.py:163)
- [kavach/receipts.py:44](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/receipts.py:44)
- [kavach/store.py:8](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/store.py:8)

Relevant local test outcomes: {'passed': 16}.

### Slide 15: Integrations & who owns execution

MCP/SDK ownership and scoped AgentOS report.

**Evidence scope:** Proxy tested locally; SDK dependency skips; AgentOS is saved-report evidence.

- [kavach/mcp_proxy/proxy.py:108](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/mcp_proxy/proxy.py:108)
- [kavach/adapters/guard.py:11](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/adapters/guard.py:11)
- [bench/results/AGENTOS_LIVE.md:26](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/AGENTOS_LIVE.md:26)

Relevant local test outcomes: {'passed': 11, 'skipped': 3}.

### Slide 16: How Qualcomm Cloud AI is used

Qualcomm interface, checked explanation counts and unknown costs.

**Evidence scope:** Client tests use stand-ins; saved experiment counts independently recomputed.

- [kavach/qualcomm.py:74](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/qualcomm.py:74)
- [kavach/explain.py:55](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/explain.py:55)
- [bench/results/explain.json:337](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/explain.json:337)

Relevant local test outcomes: {'passed': 9}.

### Slide 17: Synthetic evaluation: what was measured

Synthetic multiseed figures and denominators.

**Evidence scope:** Saved synthetic results; not a fresh benchmark rerun.

- [bench/results/results.json:2](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/results.json:2)
- [bench/results/multiseed.json:2](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/multiseed.json:2)
- [bench/run.py:39](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/run.py:39)

Relevant local test outcomes: {'passed': 3}.

### Slide 18: Ablations: which layers earn the result?

Model/provenance ablations and family interval.

**Evidence scope:** Saved ablations; numeric consistency checked.

- [bench/results/layers.json:58](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/layers.json:58)
- [bench/results/results.json:98](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/results.json:98)

Relevant local test outcomes: {'passed': 3}.

### Slide 19: Live AgentDojo: banking paired results

Paired banking live aggregate.

**Evidence scope:** Saved aggregate only; raw live-task logs absent; experiment not reproduced.

- [bench/results/comparison.json:8](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/comparison.json:8)
- [bench/compare.py:61](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/compare.py:61)

Relevant local test outcomes: No applicable tests executed; use the evidence scope above..

### Slide 20: Live AgentDojo: Slack tradeoffs

Paired Slack live aggregate and utility losses.

**Evidence scope:** Saved aggregate only; raw live-task logs absent; experiment not reproduced.

- [bench/results/comparison.json:127](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/comparison.json:127)
- [bench/compare.py:61](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/compare.py:61)

Relevant local test outcomes: No applicable tests executed; use the evidence scope above..

### Slide 21: Replay evidence is a different experiment

Offline replay with official and executed-only scores.

**Evidence scope:** Summaries recomputed from saved per-task records; AgentDojo execution dependency skipped.

- [bench/results/agentdojo_replay_banking.json:7](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/agentdojo_replay_banking.json:7)
- [bench/results/agentdojo_replay_slack.json:12](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/agentdojo_replay_slack.json:12)

Relevant local test outcomes: No applicable tests executed; use the evidence scope above..

### Slide 22: Infosys integration & local baseline evidence

Named Infosys baseline configurations.

**Evidence scope:** Saved external-code harness report; external deployment not revalidated.

- [bench/results/infosys_compare.json:39](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/infosys_compare.json:39)
- [bench/results/INFOSYS_COMPARISON.md:7](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/INFOSYS_COMPARISON.md:7)
- [bench/results/AGENTOS_LIVE.md:26](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/AGENTOS_LIVE.md:26)

Relevant local test outcomes: {'passed': 1}.

### Slide 23: Operator console & observability

Console, telemetry and alert rule count.

**Evidence scope:** Code + local tests; no alert delivery to people demonstrated.

- [kavach/static/app.js:45](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/static/app.js:45)
- [kavach/telemetry.py:23](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/telemetry.py:23)
- [deploy/alerts.yml:4](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/deploy/alerts.yml:4)

Relevant local test outcomes: {'passed': 10}.

### Slide 24: Optional capabilities & activation limits

Optional modules and incomplete live planner.

**Evidence scope:** Mixed local tests/skips; optional availability is not default activation.

- [requirements-extra.txt:4](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/requirements-extra.txt:4)
- [kavach/learning.py:52](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/learning.py:52)
- [RELEASE_ACCEPTANCE.md:42](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/RELEASE_ACCEPTANCE.md:42)

Relevant local test outcomes: {'passed': 29, 'skipped': 7}.

### Slide 25: Deployment & remaining work

Deployment artifacts and remaining work.

**Evidence scope:** Source + local profile tests; no fresh Helm/container/load rollout.

- [docs/DEPLOY.md:75](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/docs/DEPLOY.md:75)
- [RELEASE_ACCEPTANCE.md:43](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/RELEASE_ACCEPTANCE.md:43)
- [kavach/profile.py:30](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/profile.py:30)

Relevant local test outcomes: {'passed': 6}.

### Slide 26: Evidence map & presentation takeaways

Repository evidence map.

**Evidence scope:** Navigation and source references.

- [README.md:122](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/README.md:122)
- [kavach/gateway.py:92](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/kavach/gateway.py:92)

Relevant local test outcomes: No applicable tests executed; use the evidence scope above..

### Slide 27: How KAVACH compares

Comparison with published systems.

**Evidence scope:** Feature claims from the papers and documentation named in the notes, read directly; a dash means not found there, not proof of absence.

- [docs/INFOSYS_GAP_ANALYSIS.md:11](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/docs/INFOSYS_GAP_ANALYSIS.md:11)

Relevant local test outcomes: No applicable tests executed; use the evidence scope above..

### Slide 28: Infosys AgentOS and KAVACH

AgentOS: differences, measured rows, hooks.

**Evidence scope:** Infosys code read and run locally; team-written suite; no live LLM-driven AgentOS chat.

- [docs/INFOSYS_GAP_ANALYSIS.md:26](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/docs/INFOSYS_GAP_ANALYSIS.md:26)
- [bench/results/infosys_compare.json:39](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/infosys_compare.json:39)
- [integrations/agentos_hook.py:7](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/integrations/agentos_hook.py:7)
- [bench/results/AGENTOS_LIVE.md:26](/home/vismay-hs/Downloads/Infosys_hackathon/Kavach_Guardrail/bench/results/AGENTOS_LIVE.md:26)

Relevant local test outcomes: {'passed': 1}.

## Optional checks that did not execute

- `.tests.test_agentdojo_adapter`: collection skipped
- `.tests.test_agentdojo_replay`: collection skipped
- `.tests.test_agentdojo_slack`: collection skipped
- `tests.test_adapters.test_openai_agents_tool_guardrails`: could not import 'agents': No module named 'agents'
- `tests.test_adapters.test_langchain_guarded_tools`: could not import 'langchain_core': No module named 'langchain_core'
- `tests.test_adapters.test_claude_agent_sdk_hooks`: could not import 'claude_agent_sdk': No module named 'claude_agent_sdk'
- `tests.test_melon.test_agentdojo_a_payment_the_masked_run_repeats_is_escalated_and_one_the_rules_deny_costs_nothing`: could not import 'agentdojo': No module named 'agentdojo'
- `tests.test_pii.test_indian_identifiers_are_found`: presidio-analyzer and en_core_web_sm not installed
- `tests.test_pii.test_pii_typed_from_memory_still_counts_for_r2`: presidio-analyzer and en_core_web_sm not installed
- `tests.test_pii.test_personal_data_in_a_page_makes_the_task_private`: presidio-analyzer and en_core_web_sm not installed
- `tests.test_probe.test_real_model_on_cpu`: set KAVACH_TEST_REAL_PROBE=1
- `tests.test_shell.test_dry_run_measures_the_effect_and_mass_deletes_go_to_a_person`: needs Docker and the python:3.13-slim image
- `tests.test_shell.test_an_allowed_command_runs_sandboxed_and_undo_restores_its_files`: needs Docker and the python:3.13-slim image
- `tests.test_shell.test_a_read_only_command_is_a_plain_allow_and_cannot_reach_the_network`: needs Docker and the python:3.13-slim image
