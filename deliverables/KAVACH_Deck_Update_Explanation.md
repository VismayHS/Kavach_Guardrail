# KAVACH solution deck: template correction and content changes

The main `KAVACH_Solution_Deck.pptx` now fills the actual eight-slide Infosys template supplied at `/home/vismay-hs/Hack-AI-Thon_Solution_Presentation_Template.pptx`. Three slides are added in the template’s style: the architecture diagram, the comparison with USP, and AgentOS. The earlier redesign followed the template’s subjects but did not follow its layouts exactly. That redesign is retained separately as `KAVACH_Verified_Reference_Deck.pptx` and `.pdf`; it is not the template submission.

The official template’s slide order, slide sizes, headings, shape positions, logos, colours, original images and branding are preserved. On template slides only content fields, related speaker notes and authoring metadata are changed. Template helper text is replaced with real subtitles and the suggested-time labels are emptied, with their shapes left in place; no work dates or authoring timestamps are added. The demo divider remains the original DEMO slide, with the verified demonstration script in its speaker notes.

Team information was supplied by the user: Team Kavach; PES University, Bengaluru; Vismay H S, Ashwin C H and Dhanush S R. These details are not inferred from git or fabricated.

## Content compared with the original solution deck

- Rule catalogue expanded; slides no longer quote rule numbers or a rule count. Synthetic suite: 740 / 37 → 940 scenarios / 47 families.
- Saved synthetic safe automation: 68% → 95.2%; unsafe auto-allowed: 0.5% → 0.0%. Both revised rates are explicitly limited to the team-authored synthetic suite.
- Learned model: supporting signal; risk-zero ablation changes no suite verdict. Default judge: escalation advice; template explanations default.
- Undo: operation-specific local snapshots, holds or parking, not a blanket promise. REST check is decision-only by default; external proxy/SDK execution does not inherit local undo.
- Approval: bound to the stored task, tool and arguments, one-use and expiring. Full policy/tool-definition checks are not repeated at approval time.
- Validation: 521 passed; 14 skipped; per-test outcomes and skip reasons retained. Optional features and unproven production readiness remain qualified.
- Future work: CI, load/restore tests, alert delivery and broader evaluations; no unsupported hardware or horizontal-scaling claim.
- AgentDojo headline counts are on slide 4; full live benchmarking stays in the separate reference deck, labelled saved aggregate evidence. Raw live-task logs are absent here, so those external runs were not independently revalidated.

## Slide-by-slide explanation

### Slide 1: KAVACH

Introduce KAVACH as an action firewall between an agent and tools. It evaluates source, effect and authority before controlled execution.

**Evidence:** README.md; kavach/gateway.py; THREAT_MODEL.md

### Slide 2: Team Introduction

We are Team Kavach, working on ET-03, Agentic AI Guardrail Validator, on the Qualcomm Cloud AI Playground. This is a software solution: no hardware is involved.

**Evidence:** README.md

### Slide 3: Problem Statement

The statement on the slide is a summary of ET-03. The poisoned-email example is implemented in the repository: the destination comes from the email, not the user, so the provenance rule refuses the call. Do not present a model’s independent refusal as KAVACH enforcement.

**Evidence:** THREAT_MODEL.md; tests/test_trace.py; tests/test_invoice_demo.py

### Slide 4: Proposed Solution

Register tool outputs, trace proposed arguments, stage SQL/files or predict external effects, apply deterministic floors and then evaluate intent/risk. Only deterministic controls deny outright. AgentDojo is the evidence we did not write ourselves: a saved paired run on Llama-3.3-70B, one model and one attack with one sample per task, comparing only tasks both defenses finished (144 banking, 124 Slack). An escalation counts as a block because no reviewer takes part. Say the Slack cost out loud: fewer attacks succeed, and fewer benign tasks finish. Suite metrics are five-seed means on the team-written synthetic suite of 940 scenarios / 47 families, not a universal safety rate. Unknown tools fail closed in the core; configured adapters can onboard cautious drafts for review.

**Evidence:** kavach/gateway.py; provenance.py; consequence.py; policy.py; bench/results/comparison.json; bench/results/COMPARISON.md; bench/results/multiseed.json

### Slide 5: Architecture & Technical Design

The REST /api/v1/check endpoint is decision-only by default: it executes, and can arm undo, only when the caller sets execute to true. The demo MCP/local gateway path can control effects; the full MCP proxy and SDK wrappers forward permitted calls to an external executor. The test run has 521 passes and 14 skips; optional SDK/AgentDojo/PII/shell/probe tests have documented skips. Approval checks the stored digest but does not repeat the full policy/tool-definition check. Auth depends on a configured secret; the production profile requires actual keys.

**Evidence:** kavach/server.py; gateway.py; adapters/guard.py; tests/

### Slide 6: System Architecture

Walk left to right. An agent proposes a tool call; it reaches KAVACH through /mcp, where KAVACH also runs the tool, or through the proxy, REST check, SDK adapters or AgentOS hooks, where the host runs it. The gateway first checks the kill switch, then traces each argument, works out the effect, applies the deterministic rules and adds intent and risk. The verdict and signed receipt come before anything runs. Only rules and the kill switch can deny; models can only add caution. By default the Qualcomm judge adds a note on escalated calls.

**Evidence:** kavach/gateway.py; provenance.py; consequence.py; policy.py; receipts.py; server.py; docs/diagrams/architecture.mmd

### Slide 7: AI Usage & Innovation

The learned risk score is a supporting signal: forcing it to zero changed no saved synthetic-suite verdicts. The server’s default judge mode is escalations-only, adding a reviewer note; the separate inline semantic test, run live, caught 7/12 unsafe misreadings versus 1/12 heuristic, with 11/12 safe rewordings completed in both modes, at about 5 s per check. Two clean runs gave 7/12 and a third, with other jobs competing for the service, gave 6/12. We wrote the cases ourselves, so this is not a general detection rate. Templates are default explanations; optional LLM rewrites must pass number and verdict checks. No measured benefit is attributed to the reversibility threshold, which ties a fixed-threshold baseline.

**Evidence:** kavach/gateway.py; intent.py; explain.py; bench/results/layers.json; semantic.json

### Slide 8: How KAVACH Compares

Say it plainly: nobody here is useless, each approach solves part of the problem. KAVACH’s difference is the combination at the tool call. Be ready for the honest answer: CaMeL and FIDES have stronger guarantees by design, but the agent must run inside their planner; KAVACH sits in front of an existing agent. Partly means: LlamaFirewall audits agent reasoning and scans inputs, rather than deciding on the call’s arguments; AgentOS has a real approval queue, and collects provenance metadata that its default gate doesn’t use to decide; Progent asks for approval when a policy widens; CaMeL asks the user when a policy blocks. Published attack rates are left out on purpose: other tests and models can’t be ranked against ours. This table covers published systems. We have no information about what other hackathon teams built.

**Evidence:** arXiv 2503.18813 (CaMeL); arXiv 2505.23643 (FIDES); arXiv 2504.11703 (Progent); arXiv 2505.03574 (LlamaFirewall); docs.nvidia.com NeMo Guardrails tool-calling page; aws.amazon.com Policy in Bedrock AgentCore; docs/INFOSYS_GAP_ANALYSIS.md

### Slide 9: Infosys AgentOS and KAVACH

AgentOS is Infosys’s own agent runtime, inside Infosys Agentic Foundry. We read and ran its code rather than relying on its documentation. Its default gate looks for dangerous patterns. Hardening it works, with zero injection success, but only by sending most actions to a person, which risks approval fatigue. KAVACH allows no unsafe action on the same suite while sending far fewer to a person, because it knows the origin and effect of each call. This suite is written by us, so read the numbers as showing the mechanism. The Infosys gate code was loaded and executed; the RAI classifiers were not run. Don’t say Infosys has no guardrails: say the built-in paths we read don’t combine these checks by default, and custom hooks can add more. KAVACH’s payment facts are the demo company’s; a real ERP needs integration work. AgentOS also truncates hook outputs, which can weaken tracing. Approval SLAs, durable approvals, SafeKernel, RBAC and multi-tenancy are stronger than anything we built, which is why we plug into it.

**Evidence:** docs/INFOSYS_GAP_ANALYSIS.md; bench/results/infosys_compare.json; INFOSYS_COMPARISON.md; AGENTOS_LIVE.md; integrations/agentos_hook.py

### Slide 10: Future Enhancements, Scalability & Security

Distinguish present controls from future work. Persistence must be configured. The reference Helm chart has one replica and Recreate strategy for the single-writer chain. CI, sustained load, backup/restore drills and delivery of alerts to people remain incomplete in the recorded release acceptance. General production readiness and general shell containment are not established. External AgentOS governance and benchmark findings are saved reports, not fresh external validation.

**Evidence:** RELEASE_ACCEPTANCE.md; docs/DEPLOY.md; profile.py; deploy/helm/kavach/; telemetry.py

### Slide 11: DEMO

Demo sequence: (1) queue a legitimate email and prove delivery once in Mailpit, or cancel before delivery; (2) show a poisoned-email call denied by the provenance rule and trace that the connector never ran; (3) read invoice INV-101 and vendor record, refuse a substituted account, request human approval and show the sandbox ledger; (4) optionally demonstrate recovery or kill-switch cancellation. For real Gmail, start scripts/gmail_up.sh instead (scripted stories switch off there): asked to summarise a poisoned email and do what it asks, Llama tried to send to the address in the email, KAVACH refused it and Gmail was never called; asked only to summarise, neither Llama nor Claude obeyed in our runs, so say that this depends on the model. Label REAL agent, SCRIPTED calls and REPLAY distinctly. A model may refuse the malicious request itself. The bank is simulated; Mailpit is a real local SMTP sink. Further numeric details are in the separate reference deck.

**Evidence:** DEMO.md; docs/LIVE_DEMO.md; scripts/gmail_up.sh; tests/test_gmail.py; tests/test_trace.py; tests/test_invoice_demo.py; bench/results/CLAUDE_WITH_WITHOUT.md

## Review artifacts

- `KAVACH_Claim_Verification.md`: submission-template fidelity and eight-slide claim register.
- `KAVACH_Reference_Deck_Explanation.md`: detailed repository walkthrough and reference deck explanation.
- `KAVACH_Reference_Claim_Verification.md`: detailed reference source audit and numeric checks.
- `review/test_results.json`: test outcomes and skip reasons.
- `before_update/`: unchanged original solution deck and its generator.

## Rebuild

```bash
.venv/bin/python scripts/build_deck.py
.venv/bin/python scripts/export_deck.py
.venv/bin/python scripts/validate_template_deck.py
```
