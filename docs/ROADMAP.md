# KAVACH Phase 5 roadmap

**Status:** draft v2 for approval. Nothing below has been started.
**Date:** 2 Nov 2026
**Base:** branch `build/phase-4`, commit `afcf5ea`
**Inputs:** [kavach_phase4_review.md](../kavach_phase4_review.md) (holes N1 to N8, the 12 additions), the reviewer's comments on draft v1, the Tier 1 / Tier 2 research (Kairos, FIDES, CaMeL, Progent, MELON, LlamaFirewall, AgentDojo, Cedar, OpenTelemetry GenAI, OWASP Agentic Top 10), and a full read of the code.

**Changes since v1 (reviewer feedback):**
- Added: an AgentDojo smoke test (B0), demo safety (A10), the team understanding check (G4), an honest Kairos row, and the split deck claim.
- Moved: docs and pitch now come right after M2, not last.
- Changed: MELON escalates instead of denying and is scoped to transcripts KAVACH sees. PromptGuard runs on CPU. A4 is scoped to gateway mode. C2 reports latency as a number. Milestones are pushed to `build/phase-5` by default.
- Moved to the post-event track (Section 5, one roadmap slide): E5 Postgres, E6 Temporal, E7 connectors, E9 planner mode, E10 shell sandbox, E11 conformal guarantees, B2, and all of Phase F except F3. E4 (Cedar) is kept only if a 1-hour check passes.

---

## 1. Goals

1. **Nothing a judge can break live.** Close every hole the review found, plus two more found in the code.
2. **Numbers someone else can check.** Report results on AgentDojo (ETH Zurich), not only on our own suite.
3. **Qualcomm does a job that changes a number:** the agent, MELON, and the red-team attacker.
4. **A demo that can't fail on stage, and a team that can explain every part of it.**

## 2. Ground rules

- Work on a new branch `build/phase-5`. `build/phase-4` stays untouched. **Each milestone is pushed to `build/phase-5`** so the team can follow progress. Merging to main is a human decision.
- The existing 101 tests must stay green after every step. Every fixed hole gets a regression test.
- The decision path stays deterministic. **Only rules block.** Model signals (risk model, judge, MELON, PromptGuard) can only escalate or raise risk.
- Every new mechanism gets an ablation switch in `GatewayConfig`, so the benchmark can show what it adds.
- Everything except the Qualcomm calls must run offline.
- Anything that sends data to an outside service is opt-in and off by default.
- Results are reported as measured, including the ones that look bad.
- Size: **S** = under half a day, **M** = 1 to 2 days, **L** = 3+ days.

---

## Phase A: Close the live holes, and make the demo safe (M1)

Each hole gets a probe in a new `tests/test_phase5_holes.py`. The probe fails on `afcf5ea` and passes after the fix.

### A0. Hygiene (S)
- Add `.env`, `.venv/` and `*.env` to `.gitignore`. `.env` (the Qualcomm key) is untracked today but not ignored.
- Add `pytest.ini` with `testpaths = tests`, so `python -m pytest -q` from the README works. Today it crashes collecting `integrations/agentos_live_test.py`.
- Create a project `.venv` and install `requirements.txt`.
- **Done when:** `python -m pytest -q` passes with 101 tests, and `git status` never shows `.env`.

### A1. Recipient parsing (N1) (S)
- One shared `parse_recipients()` built on `email.utils.getaddresses`. It handles commas, semicolons, display names, and to/cc/bcc.
- It replaces the three comma splits in `policy.py:239`, `consequence.py:52` and `gateway.py:136`.
- **Done when:** `audit@big4-review.co; ops@infycorp.com` carrying 3 customers' PII is ESCALATEd by R2/R17 and counted as 1 external recipient.

### A2. Data hidden in URLs and finance files (N2) (S)
- R13 measures the path and subdomain as well as the query and fragment. Any value from a confidential or PII output, in any part of the URL, counts as a leak.
- File sensitivity labels (for example finance CSVs, `q3_*`), so `files.read` output takes the file's label instead of a blanket `INTERNAL`.
- **Done when:** `https://tracker.evil.example/q3/south-12.4/west-9.8/north-7.1` after reading `q3_summary.csv` is DENIED.

### A3. Lookalike domains and sender trust (N3) (M)
- New `kavach/lookalike.py`: dnstwist-style permutations (typos, homoglyphs, added words like `-finance`) plus edit distance against `internal_domains` and the vendor master's known domains. Known vendor domains are allowlisted first.
- "Reply to sender" trust applies only when the sender is not a lookalike.
- A new rule, **R25**: a lookalike recipient, sender-derived destination or URL host is ESCALATEd.
- **Done when:** replying to `cfo.office@infycorp-finance.co` with Q3 revenue escalates, and replying to a genuine client still passes.

### A4. Approver roles and quorum (N4) (M)
- Each approval tier in `default.yaml` gets `approver_roles` and a quorum (the €650k tier needs `{cfo: 1, finance_director: 1}`, two different people).
- `hitl.resolve` checks the approver's verified role and counts approvals until the quorum is met. An approval from the agent's own session or principal never counts. In dev mode, approvals are marked `authenticated: false`.
- **Scope:** this applies only when KAVACH is the gateway (API, MCP, proxy). Inside AgentOS, approvals happen in AgentOS's own queue, so KAVACH's quorum doesn't apply there. KAVACH passes the required approvers in its escalation message. The README and deck will say this.
- **Done when:** `intern-07` approving the €650k release fails with 403, while a CFO plus a Finance Director releases it.

### A5. Row and column diffs from the sandbox (N5, N6) (M)
- In the cloned sandbox, add temporary triggers on each table being written that log the changed rowids, changed columns, and old and new values.
- The effect reports `rows_changed` and `columns_changed`.
- R16 compares the actual changed record ids with the ids the user named.
- A new rule, **R26**: changing a column the request doesn't mention (email, iban, phone, amount) needs approval.
- **Done when:** `WHERE id = 1042 OR customer_id = 7` and `SET tier='gold', email='payments@acme-invoices.co'` both ESCALATE, and the request-matched updates still auto-complete.

### A6. Lock down `/api/settle` (N8) (S)
- `advance_s` works only in dev mode or for the admin role.
- **Done when:** a non-admin token gets 403 on `?advance_s=3600`.

### A7. Undo that doesn't wipe other people's work (code finding) (M)
- Today undo restores a snapshot of the whole database (`gateway.py:375`), so it erases every later write by anyone.
- Use the A5 change log to undo with inverse statements on only the action's own rows. If someone else changed those rows since, undo refuses and explains why. Files keep per-file snapshots.
- **Done when:** task A updates customer 5, task B updates customer 9, undoing A leaves B's change intact.

### A8. Time limit for sandbox SQL (code finding) (S)
- `set_progress_handler` with a 250 ms budget on staging connections. A statement that runs out of time is DENIED as R7, "too expensive to stage".
- **Done when:** a recursive CTE bomb returns DENY in under 300 ms.

### A9. A production profile that fails closed (S)
- `KAVACH_PROFILE=prod` requires `KAVACH_AUTH_SECRET` and a real `KAVACH_RECEIPT_KEY` (refuses the demo key), sets `require_tool_hash: true`, and disables `/api/demo/*` and `advance_s`.
- **Done when:** starting with `prod` and no secrets exits with a clear error.

### A10. Demo safety (S, plus rehearsal by the team)
- `scripts/preflight.py`: checks dependencies, the shipped model, the receipt chain, auth mode, every demo scenario's expected verdict, and the Qualcomm endpoint (`GET /models` plus one warm-up call with timing). It prints a pass/fail table.
- An **offline check**: with Qualcomm unset, the server, dashboard, every scripted scenario, the benchmarks and the tests all run. The judge and explainer fall back to templates.
- `docs/DEMO_SCRIPT.md`: the minute-by-minute script, the exact commands, the expected screen at each step, and what to do if a step fails.
- **Team does:** rehearse the full script twice, and record a fallback video of the full demo.
- **Done when:** preflight is all green, the offline check passes, the script exists, and the video is recorded.

---

## Phase B: External evaluation (M2)

### B0. AgentDojo smoke test (S)
- Run 5 AgentDojo banking tasks with Llama-3.3-70B on Qualcomm, without KAVACH.
- Check that the model makes **real tool calls** (structured `tool_calls`, or text calls that `text_tool_calls()` recovers), that arguments arrive with the right types, and that a task can finish.
- Record the call shapes and failure modes in `bench/results/AGENTDOJO_SMOKE.md`.
- **Gate:** if Llama mostly answers in plain text and doesn't recover, stop and decide with you (prompt fix, a different Qualcomm model, or report the limitation) before B1.

### B1. AgentDojo with Qualcomm's Llama as the agent (L)
- `bench/agentdojo_kavach.py`: a `BasePipelineElement` placed before AgentDojo's tool executor. It maps AgentDojo tools to KAVACH manifest entries, calls `gateway.check()`, and replaces denied or escalated calls with the replan hint. In the benchmark, escalations are counted as blocked, which is reported.
- Banking suite first. The other suites (slack, workspace, travel) only in M6, after you OK the spend.
- Report **utility**, **utility under attack** and **attack success rate** for: no defense, AgentDojo's built-in defenses (tool filter, spotlighting), KAVACH rules only, KAVACH full, and KAVACH with MELON (added in M4).
- Write `bench/results/AGENTDOJO.md` with the AgentDojo version, suite, attack and seed.
- **Done when:** reproducible from one command.

### B3. Honest self-graded numbers (S)
- `RESULTS.md` explains that the suite and the rules were written by the same team, and that Brier 0.0 means the model sees only rule-passing actions, which are almost all safe.
- Add a row for the model alone (rules off), so its real contribution is visible.

### C2. Judge off the decision path (S) (moved into M2)
- Mode `judge: escalations-only` (new default): the judge runs only on calls that would escalate anyway. Mode `judge: async`: the verdict returns immediately and the judge's note is attached to the approval card and receipt later.
- **Report as numbers** in `bench/results/JUDGE.md`: `check()` p50/p95 latency for auto-completed calls before (3,838 / 5,296 ms with the two-stage judge) and after, plus the verdict changes.

---

## Phase G: Docs and pitch (M3, right after M2)

### G1. Update the written material
- `README.md`, `docs/BLUEPRINT.md`, `docs/INFOSYS_GAP_ANALYSIS.md`, a regenerated `INFOSYS_COMPARISON.md`, and the deck with M1 and M2 numbers: AgentDojo next to the self-graded suite, clearly labelled.
- **Split the claim** "verified inside AgentOS with a live Qualcomm agent" into two bullets, because they were separate tests:
  - Verified inside Topaz AgentOS 1.0.0 through its own governance code (`AGENTOS_LIVE.md`).
  - Stopped a live Llama 3.3 70B agent on Qualcomm Inference Cloud from exfiltrating customer data (`LIVE_AGENT.md`).
- Honest scoping: undo windows and quorum apply when KAVACH is the gateway or proxy. Inside AgentOS, KAVACH decides, and AgentOS executes and approves.

### G2. Competitor table, with an honest Kairos row
- Rows: Kairos, FIDES, CaMeL, Progent, Microsoft Agent Governance Toolkit, AWS AgentCore Policy, LlamaFirewall, NeMo Guardrails, Cordon, Infosys RAI / PromptGuard.
- The Kairos row says plainly: **"Catches shell commands and scripts the agent writes: Kairos yes, KAVACH no."**
- **Never put our numbers next to theirs.** Our self-graded 0% and their AgentDojo 2.7% come from different tests, so they are not comparable. If our AgentDojo banking number exists, it is shown in its own row with its suite and model named, and no ranking is implied.

### G3. Pitch and roadmap slide
- A 3-idea pitch: "where every value came from", "what the action really does, read from the record", "everything can be taken back".
- One roadmap slide listing the post-event track (Section 5).
- Team name and members filled in from you (I won't make them up).

### G4. Team understanding check (team does; I prepare)
- `docs/TEAM_BRIEF.md`: the 3 ideas, the main rules (R1, R2, R13, R14, R16, R18 to R23, plus the new R25 to R28), the risk formula (`EUH = p·H·(1−r)`, `tau = min(0.5, C_block / (H·(1−r)))`, and why the interval escalates), the decision order, and the likely judge questions with short answers.
- A 20-question self-quiz at the end.
- **Done when:** every member can explain the 3 ideas, the main rules and the risk formula without notes.

---

## Phase C and D: Qualcomm's measurable job, and demo extras (M4)

### C1. MELON: masked re-execution (M)
- **Scope:** only where KAVACH sees the agent's conversation, which means our agent script (`agent/llm_agent.py`) and the AgentDojo pipeline. Not the plain `/api/v1/check` API and not the AgentOS hook, which only see single calls.
- Before a state-changing call would auto-complete or escalate, re-run the agent's last step on Qualcomm with the user's request masked out. If the model still proposes the same call, the call is being driven by injected content.
- **Result: ESCALATE, never deny** ("the agent proposes this action even without your request"). The signal is recorded as **R27** in the receipt but has REQUIRE_APPROVAL strength, because only deterministic rules may block.
- **Done when:** measured on AgentDojo banking as its own row (ASR, utility, extra latency, extra Qualcomm calls).

### C3. Prompt-injection classifier on tool outputs, on CPU (M)
- Meta's PromptGuard 2 (the small 22M model) running locally on **CPU**. It scans each email, web page and record when it enters the task.
- A hit marks that source hostile: it raises risk and blocks "reply to sender" trust for that message. It never blocks on its own.
- It replaces the triage model that flags 80% of calls. Qualcomm's jobs become the agent, MELON and the red-team attacker.
- **Done when:** detection rate on our injection families, false positives on safe families, and CPU latency are reported.

### B4. Automated red team, attacker on Qualcomm (M)
- `bench/redteam.py`: an attacker model on Qualcomm writes new injections against the guarded agent, seeded with promptfoo and garak templates. Every bypass becomes a scenario in `bench/redteam_found/` and a regression test.

### D1. Canary records (S)
- Fake customers, a fake IBAN and a fake API key seeded into the mock data. Any **external** action carrying one is DENIED as **R28**, "canary tripped: record X". Internal moves of canary data are only logged (a legitimate backup must not trip it).

### D2. "Rule of Two" meter (S)
- The dashboard shows the three legs per session (untrusted input, private data, outbound action). With all three active, a human decides (R14, shown visually).

### D3. Approval-fatigue demo (S)
- A dashboard mode: 15 quick approval prompts with one disguised exfiltration, then the reveal of KAVACH's provenance card.

---

## Phase E (selected): Platform pieces for the event (M5)

### E1. Real MCP proxy (L)
- `kavach/mcp_proxy/`: an MCP server over Streamable HTTP and stdio in front of real **upstream** MCP servers. It reads their `tools/list`, records hashes, and scans descriptions for poisoning and cross-server name shadowing. Each `tools/call` goes through the gateway, and allowed calls are forwarded upstream.
- **Done when:** the MCP Inspector or Claude Desktop, connected through KAVACH to the reference filesystem and fetch MCP servers, has the injection demo blocked end to end.

### E2. Framework plug-ins (M)
- Thin adapters over `/api/v1/check`, each with an example and a test: Claude Agent SDK `PreToolUse` hook, OpenAI Agents SDK tool guardrail, LangGraph tool wrapper, and the existing AgentOS hook (kept).

### E3. Tool effects as data, not if-branches (M)
- Move staging method, harm formula, target arguments and safeguard per tool into `kavach/manifests/*.yaml`. A parity test confirms identical decisions on the whole suite.

### E8. Provenance upgrades (M)
- Microsoft Presidio with Indian recognisers (Aadhaar with Verhoeff check, PAN, GSTIN, IFSC, UPI, Indian phone numbers, voter ID). The regexes stay as a fast path.
- Normalise before matching (`[at]`, `[dot]`, homoglyphs, base64, URL and HTML entities, spaced digits).

### F3. Kill switch (S)
- `POST /api/kill` pauses one agent, one tenant, or everything. Pending holds are cancelled, new calls are DENIED with "paused by <who>". A dashboard button and a receipt entry (EU AI Act Art. 14(4)(e)).

### E4. Cedar policies with proofs (gated)
- **1-hour check first:** install `cedarpy`, write R1 and R18 in Cedar, and try to run the policy analyzer from Python to prove "no external send with an untrusted destination is ever allowed".
- **If it works:** compile the expressible rules to Cedar, keep the Python engine with a 100% parity test, and print the proofs from `python -m kavach.policy_verify`. Facts KAVACH computes (provenance, lookalikes, staged rows) go in as Cedar context.
- **If it doesn't:** stop, note the result, and move E4 to the post-event track.

### If time (S each)
- **IBAN check-digit validation** (mod-97, country length) and IFSC format checks on `vendor.update_bank` and payments (from F7).
- **Minimal OpenTelemetry:** one `execute_tool` span per decision with `kavach.verdict`, `kavach.rule_ids` and `kavach.receipt_id`, without arguments, exported only when an OTel endpoint is set (from F6).

---

## 3. Order and milestones

| Milestone | Contents | What it proves |
|---|---|---|
| **M1** | A0 to A10 | No known live hole, ~15 new tests, and a demo that runs offline |
| **M2** | B0, B1 (banking), B3, C2 | An external number, and the judge off the hot path, with latency in numbers |
| **M3** | G1 to G4 | Deck, docs and team brief current with honest claims |
| **M4** | C1, C3, B4, D1 to D3 | Qualcomm with measured jobs, and demo extras |
| **M5** | E1, E2, E3, E8, F3, E4 (if the check passes), the "if time" items | Real proxy, plug-ins, better provenance, kill switch |
| **M6** | B1 on the remaining suites (after your OK), a refresh of the G1 numbers | Full AgentDojo picture |

After each milestone I push to `build/phase-5`, report test results and benchmark deltas, and wait for your go-ahead.

## 4. What I need from you

| Item | For | Required? |
|---|---|---|
| Permission to create `.venv` and `pip install` | Everything | **Yes, to start** |
| OK to spend Qualcomm API calls (your `INFERENCE_CLOUD_*` key) | B0, B1, C1, B4 | Yes for M2 and M4 |
| Push access to `VismayHS/Kavach_Guardrail` from this machine | Pushing each milestone to `build/phase-5` | Yes (default is to push each milestone; merging to main stays with you) |
| Team name and members | G3 | Before M3 |
| Rehearsal, fallback video, team quiz | A10, G4 | Team tasks |

## 5. Post-event track (the roadmap slide)

Kept in full and not scheduled now. Each item gets a detailed plan (files, done-when, needs) when we pick it up.

| Area | Items |
|---|---|
| Durable, persistent platform | E5 Postgres for all state, E6 Temporal workflows for holds and compensations, E7 real connectors (Mailpit/Gmail/Outlook, Postgres staging, Stripe test mode, SAP parking BAPIs) |
| Stronger guarantees | E9 FIDES/CaMeL-style planner mode (exact information flow), E10 shell and script sandbox with an egress proxy (closes the Kairos gap), E11 conformal risk control and the human-feedback learning loop, E4 Cedar proofs if the check fails |
| Enterprise and compliance | F1 agent identity (RFC 8693 token exchange) and secrets broker, F2 agent-to-agent delegation, F4 compliance evidence pack (OWASP ASI01 to ASI10, NIST AI RMF, EU AI Act, DPDP Act 2023, RBI), F5 signed and anchored receipts (KMS, RFC 3161, Rekor, Object Lock), F6 full telemetry and SIEM export, F7 sanctions screening and payee-name match, F8 Slack/Teams approvals in English and Hindi with fatigue detection, F9 shadow mode and policy replay, F10 multi-tenancy, F11 Docker/Helm deployment |
| Evaluation | B2 a second benchmark (ASB or InjecAgent) |
| Tier 3 | Kairos-style deferred decisions on the trace, digital-twin sandboxes, browser and computer-use agents, a Rust data plane |

## 6. Risks

- **AgentDojo numbers may look worse than our suite.** We report them as measured, and fix what they reveal.
- **Llama may not call tools reliably on AgentDojo.** That's what the B0 gate is for.
- **MELON doubles model calls for the calls it checks.** It's scoped to state-changing calls in transcript-visible paths, and its cost is reported.
- **The Cedar analyzer may not be reachable from Python.** That's what the 1-hour gate is for.
- **Demo-day network or endpoint failure.** Covered by the offline mode, the preflight warm-up and the fallback video (A10).
