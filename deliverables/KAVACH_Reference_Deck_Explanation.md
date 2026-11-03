# KAVACH solution deck: update explanation

The original 15-slide solution deck described the prototype. The separate reference deck has 28 slides: eight presentation slides following the original submission topics, followed by technical, evaluation, operations and reference appendices, including the comparison and AgentOS slides. The PowerPoint remains editable, including diagrams and tables.

No calendar dates or authoring timestamps are included in the revised deck, its speaker notes or this explanation. Technical durations, model names, identifiers, policy limits and benchmark latencies are operational facts rather than authoring history. The source deck and its PDF are preserved unchanged in `before_update/` for comparison. The original template is also unchanged; its dated graphics are not reused in the rebuilt deck.

## Most consequential changes

| Topic | Original deck | Revised deck |
|---|---|---|
| Policy coverage | Prototype rule set | Expanded catalogue, with examples of origin, task totals, finance and user-only argument checks; slides quote no rule numbers or count |
| Evaluation suite | 740 cases, 37 families | 940 cases, 47 families; 282 held-out cases per seed |
| Synthetic unsafe auto-allowed | 0.5% | 0.0%, qualified as team-written synthetic evidence |
| Synthetic safe automation | 68% | 95.2% of safe cases; saved five-seed mean |
| Rules-only unsafe allowed | About 30% | 3.9%; intent gate is distinct from learned-model contribution |
| Blanket manual approval | Claimed safe; roughly 12% safe automation | 3.9% unsafe allowed and 9.5% safe automation on this baseline; its coverage is imperfect |
| Model contribution | Risk model presented as key safety driver | Risk-zero ablation changes no verdict on this suite; deterministic rules and intent gate carry decisions |
| Threshold innovation | Reversibility threshold promoted as a differentiator | Fixed threshold ties on saved aggregate metrics; no proven superiority claimed |
| Explanations | LLM writes them by default | Templates default; optional checked rewrite, with 19 kept, 22 rejected and 6 unavailable in the saved experiment |
| Qualcomm judge | Ambiguous calls described as inline by default | Default adds a note on escalations; inline semantic evaluation is separately labelled |
| Undo | Broad reversible-action promise | Local snapshot, queued-email cancellation, payment hold and SAP parking; external hooks do not inherit local undo |
| Integrations | Minimal MCP door and AgentOS hook | Full stdio / HTTP MCP proxy, SDK adapters and scoped AgentOS governance evidence |
| Independent evidence | AgentDojo mostly a future port | Paired, partial live banking and Slack results, plus separately labelled offline replay |
| Reliability | General fallback / rollback language | Exact-action approvals, durable windows, unknown delivery handling, receipt-write boundary and queued-action kill switch |
| Audit | Hash chain + HMAC | Optional Ed25519, required in prod profile; separate signed checkpoint; public verification |
| Scaling | Stateless / horizontal scaling aspiration | Single receipt-chain writer; one-replica Helm reference deployment |
| Tests | 12 tests | 521 passed, 14 skipped in the executed repository test suite |
| Presentation | Small text, stale charts, unfilled identities and dated branding | Consistent editable layouts, source footers, explanatory speaker notes, no fabricated identities |

## End-to-end repository walkthrough

### 1. Entry points and caller authority

`kavach/server.py` serves FastAPI endpoints and the console. `/api/v1/session` lets the orchestrator establish a trusted user request and output context; `/api/v1/check` accepts a proposed action and only decides unless the caller sets `execute`; `/api/v1/plan` validates plans. The demo `/mcp` provides tool calls backed by KAVACH's environment. `kavach/mcp_proxy/` is the separate general-purpose upstream proxy. `agent/llm_agent.py` runs the Qualcomm-hosted tool-using agent and supports guarded and unguarded comparisons.

With `KAVACH_AUTH_SECRET`, `auth.py` derives identity from signed tokens, including role, tenant and orchestrator/agent kind. Agent tokens cannot declare a fresh trusted request. `identity.py` adds short-lived task-scoped exchange and delegation. Development mode has no authenticated identity guarantee. Identity scope and role authorization are different controls and both matter.

### 2. Tool definitions and argument provenance

`manifest.py` registers typed effect signatures, argument schemas, control/data argument roles, confidentiality and output trust. Definition hashes pin approved behavior. Unknown tools fail closed in the core; adapters can explicitly onboard a cautious draft for human review. `mcp_proxy/scan.py` screens descriptions for poisoning and shadowing, and the proxy quarantines suspicious or changed tools.

`provenance.py` records the trusted request and every observed output. It traces arguments to user input, business data, agent-derived values or untrusted text, including normalized disguised addresses. This is value matching with known limits, especially for newly composed values. `addresses.py` and `lookalike.py` handle recipient parsing and confusing domains. Naming a document does not automatically authorize its instructions: delegated source cases can go to human review. Separate rules cover destinations where direct tracing is insufficient and restrict designated arguments to user input.

### 3. Consequence analysis

`consequence.py` chooses sandbox, static or predicted analysis. `sql.py` and `changelog.py` measure actual SQL operations and row/column changes on staged state; file actions use supported copies. Typed external effect models estimate recipients, PII, money and reversibility without pretending to have run a real bank or email server. `environment.py` owns a seeded synthetic enterprise with CRM, invoices, vendor records, finance tools, mailbox, files and windows. Real services enter through `connectors.py`; Mailpit is a real local SMTP sink, Gmail is optional, and `scripts/sandbox_bank.py` remains a simulated bank.

### 4. Policy and final verdict

`policy.py` evaluates the catalogue in `policies/default.yaml`. Controls cover provenance, leakage, freeze, destructive SQL, business limits, tool pins and schemas, RBAC, secrets, paths, actual records and columns, AP approvals, retention, invoice matching, canaries, finance facts, delegation, shell constraints and task-wide cumulative budgets. One rule verifies the invoice's amount and vendor account from records. Another counts the whole task, reducing split-operation bypasses.

`gateway.py` integrates context, provenance, consequence, deterministic floors, intent and risk. A deterministic denial stays denied. A policy approval floor cannot be auto-allowed by a model. Intent mismatch, uncertainty or other risk conditions escalate rather than become model-only denials. `risk.py` loads the calibrated ensemble and computes a score and interval; this code path exists, but the saved ablation shows that its learned risk value does not change the synthetic suite's final verdicts.

### 5. Qualcomm and optional semantic assistance

`qualcomm.py` provides the shared endpoint client with retries, timeout budgeting and response parsing. `intent.py` has a deterministic heuristic and a two-stage reasoning-blind judge that sees the request, call and provenance rather than trusting the agent's reasoning. `GatewayConfig.judge_mode` defaults to `escalations-only`: a note for a person already deciding. Inline semantic evaluation is an explicit different mode. Its saved 24-case result is 7/12 unsafe misreadings caught versus 1/12 without the judge, and 11/12 safe rewordings completed in both cases. These cases were hand-written by the rule authors and are not a general detection-rate estimate.

`explain.py` always creates a template and optionally accepts a model rewrite if numeric and verdict faithfulness checks pass. LLM explanation is disabled by default. `usage.py` meters returned usage by component; `model_prices.json` contains reference rates and unknowns. The saved AgentDojo logs lack token accounting, so historical run costs cannot be reconstructed reliably.

### 6. Approval and controlled execution

`hitl.py` maintains review cards, deadlines, escalation chains and quorum. `gateway.py:action_digest` binds task, tool and arguments; `resolve_hitl` executes the stored action after one-use approval, subject to applicable identity, role and separation-of-duty checks. Mutating a call invalidates that approval. Host-only hooks do not inherit that full local execution guarantee.

`gateway.py:execute` calls the supported local execution path only after a decision receipt. SQL/files have supported restoration, email can be cancelled while queued, payments can be held and rechecked, and SAP demo postings can be parked. A refund is not inherently undoable. `safeguard_armed` exposes actual safeguard status. Once SMTP delivery is accepted, KAVACH cannot retrieve the recipient's mail.

### 7. Settlement, recovery and operator intervention

`windows.py`, `environment.py` and `store.py` preserve waiting state when a database is configured and settle windows. An interrupted send can be unknown; it is not automatically repeated. Bank requests use idempotency keys. A kill switch stops new scoped calls and cancels pending effects, including restored windows. Receipt writes for decisions, approved executions and manual early release fail closed before the connector. Failures recording a completed effect mark degraded evidence; they cannot make an already delivered message disappear.

### 8. Audit, persistence and evidence

`receipts.py` implements a SHA-256 chain and HMAC, with `signing.py` adding Ed25519 public-key verification. `store.py` persists supported state to SQLite or Postgres and maintains a separately stored signed checkpoint to detect tail truncation. Database persistence must be configured; the default is in memory. `anchor.py` supports optional external anchoring, which is not claimed as demonstrated here. `evidence.py` exports per-task control evidence rather than legal certification. `profile.py` requires real auth and signing material for production profile and disables demonstration controls.

### 9. Integration and UI boundaries

`adapters/guard.py` is shared by LangChain/LangGraph, OpenAI Agents and Claude Agent SDK adapters. These check and register outputs while the framework executes tools, so `local_execution=False` avoids claiming a local snapshot or hold. `integrations/agentos_hook.py` maps denial to a blocked AgentOS call and escalation to its approval queue. The saved AgentOS run used the real governance code with a stand-in agent. A full LLM-driven tenant chat is unverified, and AgentOS owns execution after approval.

`static/index.html`, `vx.css` and `app.js` implement the console with native web assets and hash routes. It distinguishes live agents, scripted scenarios, activity, approvals, undo, traces, receipts, results and policies. Scripted demos are refused while real mail mode is active. The display shows real outcome status rather than accepting an agent's success claim.

### 10. Observability, optional extensions and deployment

`telemetry.py` emits Prometheus metrics, OpenTelemetry decision spans and optional SIEM forwarding; `logs.py` emits structured decision logs without raw arguments. `deploy/` supplies collectors, Jaeger wiring, Grafana provisioning, alert rules and Helm templates. Alert rules exist, but delivery to people is not configured. The Helm chart intentionally runs one receipt-chain writer.

Optional modules include Cedar parity/verification, Presidio PII, a CPU injection classifier, MELON masked re-execution, signed policy bundles, shadow/canary policy replay, task identity and a no-regression feedback retraining loop. Retraining is on demand rather than automatic. `planner.py` supports reference-labelled offline plans, while live Qualcomm plan generation is documented as incomplete. `shell.py` is a constrained sandbox demonstration with no general containment claim. `requirements-extra.txt` identifies optional prerequisites; implemented code does not mean an extra is active in the default demo.

## Reading the measurements correctly

The deck deliberately preserves separate evidence categories:

- **Synthetic suite:** `results.json` and `multiseed.json`. The main synthetic table uses the five-seed mean consistently. Seed-0 results, model ablations, family-level intervals and other runs are labelled independently.
- **Live AgentDojo:** `comparison.json` contains paired subsets. Banking compares 128 attacked cases and 16 benign cases; Slack compares 103 attacked cases and 21 benign cases. Do not use the full unguarded sample as the denominator for a partial guarded run.
- **Banking live:** attack success 65/128 → 0/128; benign completion 8/16 → 8/16; user task completion under attack 53/128 → 62/128.
- **Slack live:** attack success 48/103 → 11/103; benign completion 9/21 → 6/21; user task completion under attack 36/103 → 21/103. Residual successes and utility loss remain visible.
- **Offline AgentDojo replay:** correct tool-call sequences plus an obedient attacker. Banking: official and executed-only attacks 0/144. Slack: official attempted-call scoring 21/105; executed-only 0/105. This is a distinct experiment.
- **Infosys local baselines:** `infosys_compare.json`, seed-0 harness results on 282 cases. KAVACH escalation is 26.6% in that run; its multiseed primary suite reports 26.9%. Different files were produced by different runs, so the deck does not silently blend them.
- **Latency:** the primary synthetic result file reports p50/p95 2.40/9.95 ms for the full system, excluding the judge. The separate comparison harness reports 0.43/3.48 ms over 1,027 decisions on Darwin arm64. These are saved-machine measurements and are not reproduced performance claims for this environment. The deck removes the old universal sub-5-ms promise.
- **Claude demo:** the saved comparison reports real Claude refusing malicious requests even without KAVACH. The deck does not credit KAVACH for a model's independent refusal; enforcement is shown separately through labelled scripted calls.

## Verification register

`KAVACH_Reference_Claim_Verification.md` maps all 28 slides to exact source locations, relevant test outcomes and evidence limits. Saved numeric results are checked against JSON, including denominators and percentage calculations. A saved report supports a statement about what that report records; it does not establish that the external experiment was independently reproduced. Raw live AgentDojo task logs are absent from this checkout. External AgentOS and Infosys harness results are also presented as saved reports rather than fresh external validation.

The deeper audit corrected two details: approving a local action checks its stored digest but does not rerun the complete policy/tool-definition checks; and an auth secret can enable authentication even outside the production profile. These boundaries are now explicit in the deck and notes.

## Validation and scope

The repository suite was executed with `.venv/bin/python -m pytest -q`: **521 passed, 14 skipped**. Optional service/dependency skips remain explicit. No application code was changed for this documentation task, no user credentials were inspected, and no real-bank payments were made or external user mail sent. Local demo services may be exercised by the tests. Live model, AgentOS, Gmail, external anchoring and connector demos were reviewed from source, tests and saved reports rather than rerun. Build and visual checks are recorded in `review/deck_validation.json` after export.

The PDF is exported from the final PPTX. Slide text, notes and authoring properties are checked for calendar strings. The original files are retained for comparison, including their original contents. The report and speaker notes explain implemented, optional, simulated, partial and missing functionality separately.

## Rebuilding the deliverables

The authoring dependencies are in `requirements-deck.txt`; PDF export also needs LibreOffice with its Impress component. From the repository root:

```bash
.venv/bin/python scripts/build_reference_deck.py
.venv/bin/python scripts/export_deck.py
.venv/bin/python scripts/validate_deck.py
.venv/bin/python scripts/audit_deck_claims.py
```

`build_reference_deck.py` regenerates the editable PowerPoint, speaker notes, this explanation and slide manifest from the saved evidence. `export_deck.py` exports the PDF and strips authoring calendar properties. `validate_deck.py` checks text preservation, notes, geometry, page count, headline metrics and calendar strings. `review/validation.json` records the executed repository test result; rerunning the deck builder does not rerun the tests or a live model.

## Slide-by-slide changes and presenter explanation


### Slide 1: KAVACH

**Changed:** Rebuilt the cover and visual system; removed embedded calendar labels and presentation timing prompts.

**Explain it this way:** KAVACH sits between an agent and the tools that change the world. It traces argument origins, estimates or stages consequences, applies policy, and records the decision before a permitted call runs. It can allow, allow with a real safeguard, ask a person, or deny. The demo company and bank are synthetic; SMTP delivery can be real. The main presentation is slides 1–8; the remaining slides provide technical and evaluation evidence.

**Evidence:** `README.md; kavach/gateway.py; THREAT_MODEL.md`


### Slide 2: Project context & delivery scope

**Changed:** Replaced unfilled team and college placeholders with verified project scope and user responsibilities.

**Explain it this way:** The project addresses ET-03 for enterprises that let agents use CRM, files, email and finance tools. Operators are business reviewers, while integration owners enforce the tool boundary and auditors inspect receipts. The repository includes the gateway, console, simulated business environment, connector demos, tests and evaluation scripts.

**Evidence:** `README.md; PRODUCT.md; RELEASE_ACCEPTANCE.md; integrations/`


### Slide 3: Problem Statement

**Changed:** Removed dated incidents, market forecasts, compliance assertions and blanket competitor claims; replaced them with repository-tested failure cases.

**Explain it this way:** A legitimate request such as summarising an inbox can expose the agent to instructions planted in an email. The same failure occurs when an invoice email substitutes a bank account, or a narrow CRM request becomes a broad write. KAVACH evaluates each proposed call with the actual request, source labels and business facts. Success requires showing the connector outcome, not trusting the agent’s final message.

**Evidence:** `THREAT_MODEL.md; tests/test_trace.py; tests/test_invoice_demo.py`


### Slide 4: Proposed Solution

**Changed:** Expanded the policy rules, corrected the processing order, and removed the promise to catch every unsafe action.

**Explain it this way:** The input includes a tool name, arguments, trusted request, caller identity and prior outputs. Provenance labels the arguments; consequence analysis stages SQL and file changes or predicts external effects. Policy rules impose denial or human approval. The intent gate and risk signal can add caution. Every decision has an explanation and receipt; safeguarded local execution is separate from merely approving an externally executed call.

**Evidence:** `kavach/gateway.py; policy.py; bench/results/multiseed.json`


### Slide 5: Architecture & Technical Design

**Changed:** Replaced the prototype architecture and stale diagram with editable component flow; added the owned-execution versus external-execution boundary.

**Explain it this way:** The agent or orchestrator enters through REST, the demo MCP endpoint, a full MCP proxy or framework hooks. The gateway combines manifest, provenance, consequence, policy, intent and risk. In owned execution it calls the environment and connectors with snapshots or delivery windows. In proxy and hook mode the external host executes, so KAVACH does not claim its own undo. Receipts, persistence and telemetry surround both paths. This is a stateful single-writer reference deployment, not a verified horizontally scalable service.

**Evidence:** `kavach/server.py; gateway.py; environment.py; mcp_proxy/proxy.py; store.py`


### Slide 6: AI Usage & Innovation

**Changed:** Removed the threshold novelty and calibration headline; corrected model importance, judge default and the optional explanation path.

**Explain it this way:** The calibrated risk ensemble supplies an additional score and uncertainty interval. On the saved synthetic suite, forcing model risk to zero changes no verdict: rules and the intent gate determine the outcomes. The server defaults to a Qualcomm judge only on escalations, where it writes a reviewer note without changing that verdict. An explicit inline evaluation caught seven of twelve semantic misreadings versus one with the heuristic, with eleven of twelve safe rewordings completed in either case. Templates are the default explanation; optional LLM rewrites must pass number and verdict checks.

**Evidence:** `kavach/gateway.py; intent.py; explain.py; bench/results/layers.json; semantic.json`


### Slide 7: Readiness, Scalability & Security

**Changed:** Replaced 12 tests and aspirational stateless scaling with the executed test result, the single-writer constraint and explicit deployment gaps.

**Explain it this way:** The repository test run completed with 521 passing and 14 skipped tests. Skips reflect optional dependencies or external-service prerequisites and are not passes. Verified controls include exact-action approvals, restart-safe windows, a kill switch and signed receipts. The chart deliberately uses one replica with a single receipt-chain writer. Production profile requires real authentication and receipt-signing keys and disables demo reset and clock controls. Remaining work includes load testing, backup/restore drills, CI and alert delivery to people.

**Evidence:** `RELEASE_ACCEPTANCE.md; docs/DEPLOY.md; profile.py; deploy/helm/kavach/; tests/`


### Slide 8: Demo: prove what actually happened

**Changed:** Replaced old synthetic-only demo bullets with the documented connector-backed stories and explicit REAL / SCRIPTED / REPLAY labels.

**Explain it this way:** Start with a legitimate email, showing that it is queued and then reaches Mailpit once. Send another and cancel it before delivery. For the poisoned-email story, a real model may refuse on its own; identify that correctly. A labelled scripted path demonstrates the same malicious call with and without the gateway. For invoice INV-101, read the vendor record, refuse the substituted account, require human approval and show the sandbox ledger. Trace ties request, decision, connector and receipt together. Recovery and kill-switch are optional follow-up demonstrations with their existing scripts.

**Evidence:** `DEMO.md; docs/LIVE_DEMO.md; tests/test_trace.py; bench/results/CLAUDE_WITH_WITHOUT.md`


### Slide 9: Decision path: from call to effect

**Changed:** Replaced the static decision-flow appendix with an editable, ordered execution lifecycle.

**Explain it this way:** A session establishes caller and request; outputs are registered as the task reads. A call is validated against the tool manifest, traced and staged. Deterministic floors precede the final verdict. A model score cannot remove a policy requirement. The decision receipt is written before execution. Allowed local calls execute with their actual safeguard; escalations wait for approval; denials return a replan hint. Connector and delivery results produce subsequent records. A queued email is not a delivered email.

**Evidence:** `kavach/gateway.py: check, execute, resolve_hitl, settle; receipts.py`


### Slide 10: Provenance & policy: what is trusted

**Changed:** Added the expanded provenance and business-rule controls, including invented destinations, task totals and user-only arguments.

**Explain it this way:** Values copied or lightly disguised in emails remain untrusted, including normalized addresses. A user-named document may require confirmation instead of immediate denial; naming a source is not blanket authority. Separate rules ask a person about outbound destinations after untrusted reads, cover destinations with insufficient output context, and accept designated user-only arguments only when the user supplied them. Per-task totals prevent splitting a large operation into small calls. These are implemented checks with residual inference limits, not a proof that arbitrary transformed values are tracked.

**Evidence:** `kavach/provenance.py; policy.py; policies/default.yaml; tests/`


### Slide 11: Consequences & the real limits of undo

**Changed:** Replaced broad undo language with operation-specific mechanisms, expiry boundaries and external-execution exclusions.

**Explain it this way:** SQL and supported file actions run on copied state to produce a diff. Their supported local execution uses a snapshot or row-level change record for undo. Email and payment impact is predicted from typed inputs and records; KAVACH can delay delivery or settlement while it controls execution. Email cancellation only works before the server accepts delivery. SAP demo postings are parked rather than booked. Refunds can be plain ALLOW with no reversal guarantee. MCP proxy and framework-hook paths run outside KAVACH and do not inherit its local safeguard.

**Evidence:** `kavach/consequence.py; environment.py; gateway.py:_allow; tests/test_email_window.py`


### Slide 12: Human approval is bound to the exact call

**Changed:** Added exact-action binding, replay prevention, role quorum and the host responsibility in hook-only mode.

**Explain it this way:** An approval card shows consequence, provenance, requested roles and the action digest. The digest binds task, tool and arguments; approval is one-use and expires. Tiered release quorums require distinct authorized people and exclude the requester. High-value irreversible cases also use four-eyes checks. The default queue can escalate to the configured review chain before expiry. On local execution, approval verifies the stored action digest and executes that stored call. It does not re-run the full policy or tool-definition check at approval time. In hook-only mode the host owns approval binding and execution; the AgentOS hook is not an end-to-end approval implementation.

**Evidence:** `kavach/gateway.py:action_digest, resolve_hitl; hitl.py; tests/test_approval_binding.py`


### Slide 13: Delivery, crash recovery & the kill switch

**Changed:** Added durable outbox behavior, unknown-delivery handling, cancellation of queued effects and the precise receipt-write failure boundary.

**Explain it this way:** With persistence configured, waiting email and payment state survives restart. A delivery interrupted after handoff may be unknown: it is recorded for review and not automatically resent. Bank requests use an idempotency key. A scoped kill switch refuses new calls and cancels waiting effects, including restored windows. Decision, human-approved execution and early-release receipts must be durable before their actions proceed. A post-effect recording failure marks the log degraded; the implementation cannot undo the fact that a connector already ran.

**Evidence:** `kavach/environment.py; windows.py; receipts.py; tests/test_kill_queued.py; test_receipt_store_down.py`


### Slide 14: Identity, receipts & verifiable evidence

**Changed:** Expanded HMAC-only audit language to signed receipts, checkpoint truncation detection, identity kinds and tenant scope.

**Explain it this way:** When authentication is configured, signed tokens establish user, role, tenant and token kind. Orchestrators may establish trusted requests; agent tokens operate inside an existing session. Delegation narrows authority. Receipts chain hashes with HMAC and optional Ed25519 signatures, required in the production profile. A separately stored signed checkpoint detects a truncated tail. An exported chain is verifiable with the public key. Evidence packs map specific receipts to controls and do not certify legal compliance. External anchoring is optional and was not demonstrated in the local demo.

**Evidence:** `kavach/auth.py; identity.py; receipts.py; signing.py; store.py; evidence.py`


### Slide 15: Integrations & who owns execution

**Changed:** Added the actual full MCP proxy and framework adapters; narrowed AgentOS validation to the evidence and removed the drop-in undo implication.

**Explain it this way:** The local gateway and demo MCP execution path can own connector delivery and its safeguards. POST /api/v1/check is decision-only by default: it executes, and can arm an undo safeguard, only when the caller sets execute to true. The full MCP proxy supports stdio and Streamable HTTP upstream and downstream, scans definitions and quarantines suspicious tools. It forwards only approved tool calls, but upstream servers execute them and undo is not claimed. Framework adapters cover LangChain/LangGraph, OpenAI Agents and Claude Agent SDK. The AgentOS adapter was exercised through real governance code with a stand-in agent; a completed LLM-driven tenant chat was not demonstrated. AgentOS must use blocking hooks with closed failure policy and owns approval execution. All clients must lose direct bypass access.

**Evidence:** `kavach/adapters/; mcp_proxy/; integrations/agentos_hook.py; bench/results/AGENTOS_LIVE.md`


### Slide 16: How Qualcomm Cloud AI is used

**Changed:** Corrected hard-coded model assumptions, explanation defaults and token-spending claims; removed unimplemented hardware and embedding ideas from the delivered architecture.

**Explain it this way:** The repository uses an OpenAI-compatible Qualcomm endpoint. Llama-3.3-70B is the protected agent in the saved benchmark runs. The two-stage intent judge triages with a smaller model and invokes a stronger model only when flagged; model selection can be overridden. Default server mode adds a note on already-escalated actions. Plain-text judge responses avoid the observed JSON tool-parser issue. The optional explanation experiment retained nineteen rewrites, rejected twenty-two and fell back on six unavailable responses, out of forty-seven cases. The agent control needs credentials, while offline checks and scripted scenarios remain available.

**Evidence:** `kavach/qualcomm.py; intent.py; explain.py; agent/llm_agent.py; bench/results/explain.json`


### Slide 17: Synthetic evaluation: what was measured

**Changed:** Replaced all prototype counts and metrics with JSON-backed results and explicit denominators.

**Explain it this way:** The suite has 940 scenarios across 47 families, with 282 held-out cases per seed. The headline comparison here uses means across 5 saved seeds. Unsafe auto-allowed uses unsafe cases as its denominator; safe auto-completed uses safe cases; escalation includes all cases. Undo coverage applies only to automatically completed state changes. These labels prevent comparing unlike percentages. The team wrote the rules and suite; zero observed unsafe allowances is a regression result and is not a universal safety guarantee.

**Evidence:** `bench/results/results.json; multiseed.json; RESULTS.md`


### Slide 18: Ablations: which layers earn the result?

**Changed:** Added the ablation evidence that corrects the old claim that a calibrated model drives the safety result.

**Explain it this way:** On the family-level analysis, the full system and a version with model risk forced to zero have identical verdicts. Rules-only still differs because it omits the intent/risk path, not because the learned score alone is decisive. The model-only ablation allows many unsafe actions. Removing provenance introduces injection success. Fixed and reversibility-conditioned thresholds tie on the suite, so the threshold is not presented as an established advantage. The family-level sample is twenty-six unsafe families, with a reported interval reaching thirteen percent despite zero observed failures. Fresh and leave-one-family-out tests remain team-authored.

**Evidence:** `bench/results/layers.json; LAYERS.md; LOFO.md; HOLDOUT.md; results.json`


### Slide 19: Live AgentDojo: banking paired results

**Changed:** Promoted independently authored live banking evidence from a future port to a measured, qualified result.

**Explain it this way:** This uses the matched subset completed by both defenses, not the full unguarded run. KAVACH completed one hundred forty-four of one hundred sixty planned tasks, including sixteen benign and one hundred twenty-eight attacked cases. On that subset the unguarded agent reached the attacker goal sixty-five times and KAVACH zero times. Benign completion is eight of sixteen in both, and task completion under attack is fifty-three versus sixty-two. Escalations count as blocked because no reviewer participates. It is one model and one attack, with one sample per task. Saved summary arithmetic was checked, but raw per-task live logs are absent, so the run itself cannot be independently revalidated from this checkout.

**Evidence:** `bench/results/comparison.json: live.banking.paired.kavach; COMPARISON.md`


### Slide 20: Live AgentDojo: Slack tradeoffs

**Changed:** Added the residual attack success and utility loss omitted by the prototype narrative; preserved official benchmark scoring.

**Explain it this way:** The matched Slack subset contains one hundred twenty-four task pairs: twenty-one benign and one hundred three attacked. Attacker success drops from forty-eight to eleven cases. However, benign completion drops from nine to six and utility under attack from thirty-six to twenty-one. A deck claiming perfect safety or preserved utility would hide this tradeoff. One Slack checker counts attempted calls even when blocked; the replay slide separates its executed-only interpretation. Rate-limit waiting dominates whole-agent task durations; these are not measurements of gateway decision overhead.

**Evidence:** `bench/results/comparison.json: live.slack.paired.kavach; COMPARISON.md; AGENTDOJO_REPLAY.md`


### Slide 21: Replay evidence is a different experiment

**Changed:** Separated replay from live agent evidence and made the Slack attempted-call metric explicit.

**Explain it this way:** The offline replay uses AgentDojo’s correct calls for benign work and appends exactly the attacker’s intended calls for attack cases. This tests enforcement under an obedient attacker, rather than whether a model chooses to obey. Banking completes twelve of sixteen benign tasks, with four awaiting human review; all one hundred forty-four replay attacks fail. Slack completes fourteen of twenty-one benign tasks, six stopped only by escalation. The official checker counts twenty-one of one hundred five attacks as success based on attempted calls, while the executed-only check finds zero. Both readings are shown.

**Evidence:** `bench/results/AGENTDOJO_REPLAY.md; agentdojo_replay_banking.json; agentdojo_replay_slack.json`


### Slide 22: Infosys integration & local baseline evidence

**Changed:** Updated the comparison to 282 held-out cases, corrected baseline numbers, and scoped the product-level interpretation.

**Explain it this way:** The Infosys comparison loads the referenced Foundry and AgentOS code into a local harness; it is not a benchmark of every deployed Infosys product. The default pre-tool gate lets most suite unsafe actions pass; hardening it for finance, sends and SQL trades that for broad escalation. KAVACH uses effect and source facts to make a finer decision on this team-authored suite. The PromptGuard comparison scans user queries only, and the RAI row is a perfect-classifier upper bound, not a live RAI deployment. The AgentOS hook governance test is separate from the synthetic baseline comparison.

**Evidence:** `bench/results/infosys_compare.json: seed0; INFOSYS_COMPARISON.md; AGENTOS_LIVE.md`


### Slide 23: Operator console & observability

**Changed:** Added the implemented console workflow, correlation trail, outcome telemetry and alert-delivery limitation.

**Explain it this way:** The plain HTML, CSS and JavaScript console is served by FastAPI without a frontend build. It contains live-agent, scripted-scenario, action-check, approval, activity, undo, trace, receipts, results and rulebook views. Scripted cases are disabled in real Gmail mode. One correlation identifier links the decision, receipts and mail headers. Prometheus reports decisions and delivery outcomes; OpenTelemetry sends decision spans through the collector to Jaeger; Grafana presents them. Fourteen alert rules exist, but alert delivery to a person is not configured. Usage costing reports unknowns rather than treating missing prices or tokens as zero.

**Evidence:** `kavach/static/; server.py; telemetry.py; usage.py; deploy/alerts.yml; deploy/grafana/`


### Slide 24: Optional capabilities & activation limits

**Changed:** Added feature maturity boundaries and removed proposed hardware / embeddings from the delivered-feature list.

**Explain it this way:** Optional modules extend the reference implementation: Cedar policy parity and partial-evaluation checks; a CPU injection classifier; Presidio PII recognition; MELON masked re-execution; feedback retraining with a no-regression promotion gate; policy shadow/replay and signed bundles; identity exchange and evidence packs. These are not all active in the default demo. Typed planner data-flow tests work offline, but live Qualcomm plan generation is documented as blocked by response parsing. Shell behavior is constrained to a dry-run sandbox demonstration and does not establish general shell containment. External receipt anchoring was not demonstrated live.

**Evidence:** `requirements-extra.txt; kavach/cedar_policy.py; planner.py; melon.py; learning.py; pii.py; shell.py`


### Slide 25: Deployment & remaining work

**Changed:** Replaced speculative horizontal scale and hardware roadmap with actual deployment artifacts and prioritized engineering gaps.

**Explain it this way:** The repository supports a non-root container, a Compose demonstration stack and a hardened Helm chart. Persistent storage is optional in the server and must be configured deliberately; in-memory defaults do not survive restart. Production profile requires authentication, HMAC and Ed25519 keys, pins tools, and removes demo controls. The chart runs one replica. CI, sustained load testing and a backup/restore drill remain absent; alert delivery and broader deployment hardening remain work. The bank and enterprise environment are simulated, and live benchmark samples remain partial. These are concrete limits, not evidence of production certification.

**Evidence:** `Dockerfile; docker-compose.yml; deploy/helm/kavach/; docs/DEPLOY.md; RELEASE_ACCEPTANCE.md`


### Slide 26: Evidence map & presentation takeaways

**Changed:** Replaced the dated external-reference list with a repository-backed evidence map and an accompanying detailed explanation.

**Explain it this way:** Read gateway.py for the full request-to-effect lifecycle, policy.py and provenance.py for enforcement, consequence.py and environment.py for effect modeling, and receipts.py plus store.py for audit and persistence. The server and static directory provide the API and console. Benchmark scripts and saved JSON describe evaluation; test files expose the behavior and limits.

**Evidence:** `README.md; RELEASE_ACCEPTANCE.md; THREAT_MODEL.md; bench/results/; tests/`


### Slide 27: How KAVACH compares

**Changed:** Added a comparison with published systems, with the USP and where others are stronger.

**Explain it this way:** Say it plainly: nobody here is useless, each approach solves part of the problem. KAVACH’s difference is the combination at the tool call. Be ready for the honest answer: CaMeL and FIDES have stronger guarantees by design, but the agent must run inside their planner; KAVACH sits in front of an existing agent. Partly means: LlamaFirewall audits agent reasoning and scans inputs, rather than deciding on the call’s arguments; AgentOS has a real approval queue, and collects provenance metadata that its default gate doesn’t use to decide; Progent asks for approval when a policy widens; CaMeL asks the user when a policy blocks. Published attack rates are left out on purpose: other tests and models can’t be ranked against ours. This table covers published systems. We have no information about what other hackathon teams built.

**Evidence:** `arXiv 2503.18813 (CaMeL); arXiv 2505.23643 (FIDES); arXiv 2504.11703 (Progent); arXiv 2505.03574 (LlamaFirewall); docs.nvidia.com NeMo Guardrails tool-calling page; aws.amazon.com Policy in Bedrock AgentCore; docs/INFOSYS_GAP_ANALYSIS.md`


### Slide 28: Infosys AgentOS and KAVACH

**Changed:** Added what AgentOS does, how KAVACH differs and how the two fit together.

**Explain it this way:** AgentOS is Infosys’s own agent runtime, inside Infosys Agentic Foundry. We read and ran its code rather than relying on its documentation. Its default gate looks for dangerous patterns. Hardening it works, with zero injection success, but only by sending most actions to a person, which risks approval fatigue. KAVACH allows no unsafe action on the same suite while sending far fewer to a person, because it knows the origin and effect of each call. This suite is written by us, so read the numbers as showing the mechanism. The Infosys gate code was loaded and executed; the RAI classifiers were not run. Don’t say Infosys has no guardrails: say the built-in paths we read don’t combine these checks by default, and custom hooks can add more. KAVACH’s payment facts are the demo company’s; a real ERP needs integration work. AgentOS also truncates hook outputs, which can weaken tracing. Approval SLAs, durable approvals, SafeKernel, RBAC and multi-tenancy are stronger than anything we built, which is why we plug into it.

**Evidence:** `docs/INFOSYS_GAP_ANALYSIS.md; bench/results/infosys_compare.json; INFOSYS_COMPARISON.md; AGENTOS_LIVE.md; integrations/agentos_hook.py`
