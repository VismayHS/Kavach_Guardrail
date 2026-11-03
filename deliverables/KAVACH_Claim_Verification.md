# KAVACH submission verification

Template fidelity and filled-content checks: 140/140 passed. The main submission fills the supplied eight-slide Infosys template and adds three slides in its style; the 28-slide redesign is a separate reference deck.

## Template fidelity

- Original source: `/home/vismay-hs/Hack-AI-Thon_Solution_Presentation_Template.pptx`.
- Template checksum: `cf3c95de665acf7ea6d19de8da6b617291dbe35a1a411058da860ce66fbc9126`.
- All eight template slides kept in order; dimensions, shape identities, positions, sizes and graphics retained. Three slides added: architecture diagram, comparison with USP, AgentOS.
- All master, layout, theme and media package parts are byte-identical to the supplied template.
- Team fields use the user-provided details; no identities were guessed.
- No added work dates or authoring timestamps. Template branding is unchanged; helper text is replaced and suggested-time labels are emptied, with their shapes left in place.
- The original DEMO divider is retained; the demonstration procedure is in its speaker notes.
- Edited content is checked for presence in the exported PDF; source-backed notes are included.

## Claim evidence

The repository test result is 521 passed and 14 skipped. The detailed reference audit has 118 passing numeric-consistency/source checks. These do not independently reproduce external experiments. The primary submission retains only scoped implementation, test and synthetic/semantic findings, with sources in notes. Optional capabilities, simulations and production gaps remain qualified.

For exact source locations and per-test outcomes, read `KAVACH_Reference_Claim_Verification.md`, `review/claim_audit.json` and `review/test_results.json`.

### Slide 1: KAVACH

**Sources:** README.md; kavach/gateway.py; THREAT_MODEL.md

Introduce KAVACH as an action firewall between an agent and tools. It evaluates source, effect and authority before controlled execution.

### Slide 2: Team Introduction

**Sources:** README.md

We are Team Kavach, working on ET-03, Agentic AI Guardrail Validator, on the Qualcomm Cloud AI Playground. This is a software solution: no hardware is involved.

### Slide 3: Problem Statement

**Sources:** THREAT_MODEL.md; tests/test_trace.py; tests/test_invoice_demo.py

The statement on the slide is a summary of ET-03. The poisoned-email example is implemented in the repository: the destination comes from the email, not the user, so the provenance rule refuses the call. Do not present a model’s independent refusal as KAVACH enforcement.

### Slide 4: Proposed Solution

**Sources:** kavach/gateway.py; provenance.py; consequence.py; policy.py; bench/results/comparison.json; bench/results/COMPARISON.md; bench/results/multiseed.json

Register tool outputs, trace proposed arguments, stage SQL/files or predict external effects, apply deterministic floors and then evaluate intent/risk. Only deterministic controls deny outright. AgentDojo is the evidence we did not write ourselves: a saved paired run on Llama-3.3-70B, one model and one attack with one sample per task, comparing only tasks both defenses finished (144 banking, 124 Slack). An escalation counts as a block because no reviewer takes part. Say the Slack cost out loud: fewer attacks succeed, and fewer benign tasks finish. Suite metrics are five-seed means on the team-written synthetic suite of 940 scenarios / 47 families, not a universal safety rate. Unknown tools fail closed in the core; configured adapters can onboard cautious drafts for review.

### Slide 5: Architecture & Technical Design

**Sources:** kavach/server.py; gateway.py; adapters/guard.py; tests/

The REST /api/v1/check endpoint is decision-only by default: it executes, and can arm undo, only when the caller sets execute to true. The demo MCP/local gateway path can control effects; the full MCP proxy and SDK wrappers forward permitted calls to an external executor. The test run has 521 passes and 14 skips; optional SDK/AgentDojo/PII/shell/probe tests have documented skips. Approval checks the stored digest but does not repeat the full policy/tool-definition check. Auth depends on a configured secret; the production profile requires actual keys.

### Slide 6: System Architecture

**Sources:** kavach/gateway.py; provenance.py; consequence.py; policy.py; receipts.py; server.py; docs/diagrams/architecture.mmd

Walk left to right. An agent proposes a tool call; it reaches KAVACH through /mcp, where KAVACH also runs the tool, or through the proxy, REST check, SDK adapters or AgentOS hooks, where the host runs it. The gateway first checks the kill switch, then traces each argument, works out the effect, applies the deterministic rules and adds intent and risk. The verdict and signed receipt come before anything runs. Only rules and the kill switch can deny; models can only add caution. By default the Qualcomm judge adds a note on escalated calls.

### Slide 7: AI Usage & Innovation

**Sources:** kavach/gateway.py; intent.py; explain.py; bench/results/layers.json; semantic.json

The learned risk score is a supporting signal: forcing it to zero changed no saved synthetic-suite verdicts. The server’s default judge mode is escalations-only, adding a reviewer note; the separate inline semantic test, run live, caught 7/12 unsafe misreadings versus 1/12 heuristic, with 11/12 safe rewordings completed in both modes, at about 5 s per check. Two clean runs gave 7/12 and a third, with other jobs competing for the service, gave 6/12. We wrote the cases ourselves, so this is not a general detection rate. Templates are default explanations; optional LLM rewrites must pass number and verdict checks. No measured benefit is attributed to the reversibility threshold, which ties a fixed-threshold baseline.

### Slide 8: How KAVACH Compares

**Sources:** arXiv 2503.18813 (CaMeL); arXiv 2505.23643 (FIDES); arXiv 2504.11703 (Progent); arXiv 2505.03574 (LlamaFirewall); docs.nvidia.com NeMo Guardrails tool-calling page; aws.amazon.com Policy in Bedrock AgentCore; docs/INFOSYS_GAP_ANALYSIS.md

Say it plainly: nobody here is useless, each approach solves part of the problem. KAVACH’s difference is the combination at the tool call. Be ready for the honest answer: CaMeL and FIDES have stronger guarantees by design, but the agent must run inside their planner; KAVACH sits in front of an existing agent. Partly means: LlamaFirewall audits agent reasoning and scans inputs, rather than deciding on the call’s arguments; AgentOS has a real approval queue, and collects provenance metadata that its default gate doesn’t use to decide; Progent asks for approval when a policy widens; CaMeL asks the user when a policy blocks. Published attack rates are left out on purpose: other tests and models can’t be ranked against ours. This table covers published systems. We have no information about what other hackathon teams built.

### Slide 9: Infosys AgentOS and KAVACH

**Sources:** docs/INFOSYS_GAP_ANALYSIS.md; bench/results/infosys_compare.json; INFOSYS_COMPARISON.md; AGENTOS_LIVE.md; integrations/agentos_hook.py

AgentOS is Infosys’s own agent runtime, inside Infosys Agentic Foundry. We read and ran its code rather than relying on its documentation. Its default gate looks for dangerous patterns. Hardening it works, with zero injection success, but only by sending most actions to a person, which risks approval fatigue. KAVACH allows no unsafe action on the same suite while sending far fewer to a person, because it knows the origin and effect of each call. This suite is written by us, so read the numbers as showing the mechanism. The Infosys gate code was loaded and executed; the RAI classifiers were not run. Don’t say Infosys has no guardrails: say the built-in paths we read don’t combine these checks by default, and custom hooks can add more. KAVACH’s payment facts are the demo company’s; a real ERP needs integration work. AgentOS also truncates hook outputs, which can weaken tracing. Approval SLAs, durable approvals, SafeKernel, RBAC and multi-tenancy are stronger than anything we built, which is why we plug into it.

### Slide 10: Future Enhancements, Scalability & Security

**Sources:** RELEASE_ACCEPTANCE.md; docs/DEPLOY.md; profile.py; deploy/helm/kavach/; telemetry.py

Distinguish present controls from future work. Persistence must be configured. The reference Helm chart has one replica and Recreate strategy for the single-writer chain. CI, sustained load, backup/restore drills and delivery of alerts to people remain incomplete in the recorded release acceptance. General production readiness and general shell containment are not established. External AgentOS governance and benchmark findings are saved reports, not fresh external validation.

### Slide 11: DEMO

**Sources:** DEMO.md; docs/LIVE_DEMO.md; scripts/gmail_up.sh; tests/test_gmail.py; tests/test_trace.py; tests/test_invoice_demo.py; bench/results/CLAUDE_WITH_WITHOUT.md

Demo sequence: (1) queue a legitimate email and prove delivery once in Mailpit, or cancel before delivery; (2) show a poisoned-email call denied by the provenance rule and trace that the connector never ran; (3) read invoice INV-101 and vendor record, refuse a substituted account, request human approval and show the sandbox ledger; (4) optionally demonstrate recovery or kill-switch cancellation. For real Gmail, start scripts/gmail_up.sh instead (scripted stories switch off there): asked to summarise a poisoned email and do what it asks, Llama tried to send to the address in the email, KAVACH refused it and Gmail was never called; asked only to summarise, neither Llama nor Claude obeyed in our runs, so say that this depends on the model. Label REAL agent, SCRIPTED calls and REPLAY distinctly. A model may refuse the malicious request itself. The bank is simulated; Mailpit is a real local SMTP sink. Further numeric details are in the separate reference deck.

