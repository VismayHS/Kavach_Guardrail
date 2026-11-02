# KAVACH handoff: full context (as of 2 Nov 2026)

Everything a new session (person or Claude Code) needs to continue the project. Short version and rules: `CLAUDE.md`.

---

## 1. The competition

- **Event:** Infosys IGNITE ENG NEXT 2026 Hack-AI-Thon.
- **Problem statement ET-03, "Agentic AI Guardrail Validator":** check whether an AI agent's planned action is **safe, authorized, explainable and reversible**.
  - Required MVP: agent action input → approve/block decision → guardrail explanation.
  - Platform: Qualcomm Cloud AI Playground.
- **Deliverables:**
  - A solution deck in the official template: `deliverables/template_source.pptx`, filled by `scripts/build_deck.py` into `deliverables/KAVACH_Solution_Deck.pptx/.pdf`.
  - A working prototype and a demo.
- **Team:**
  - Repo owner: VismayHS.
  - Contributor: dhanush-sr (phases 0–4).
  - Slide 2 still needs the team name, college and members.

### Why Infosys set this problem
This is our inference; Infosys hasn't stated a reason.
- Infosys sells AI agents to enterprises, mostly banks and finance.
- Agents that act (email, SQL, payments) can leak data or move money.
- Clients and regulators require checks, human override and audit trails:
  - RBI FREE-AI framework (Aug 2025);
  - MeitY AI Governance Guidelines (Nov 2025);
  - EU AI Act Art. 14.
- Gartner (Jun 2025) predicts more than 40% of agentic AI projects will be cancelled by 2027, partly for inadequate risk controls.
- Infosys's own open-source stack has an agent platform and text filters, but **nothing that judges actions**. ET-03 asks for that missing piece.

### Why the Qualcomm platform
Again our inference: Qualcomm is the sponsor and partner.
- Projects on the Playground show its Cloud AI 100 inference hardware running open models (Llama).
- Every team gets the same free models.
- Open models are the ones that most need an external guardrail: Llama-3.3-70B was hijacked in about 6.5% of attacks in the UK AISI × Gray Swan agent red-teaming challenge.
- Qualcomm now owns Arduino. The UNO Q board, with a hardware approval button, is our optional edge feature.

---

## 2. What KAVACH is

A pre-execution **action firewall** between an agent and its tools. For each tool call it decides one of:
- `ALLOW`
- `ALLOW_WITH_SAFEGUARD` (undo armed)
- `ESCALATE` (human approval)
- `DENY` (with a replan hint)

It writes a tamper-evident receipt for every decision.

### Pipeline
1. **Plan check.** `kavach/plan.py` flags the lethal trifecta (private data + untrusted content + an external sink), RBAC problems, unknown tools and unrequested state changes.
2. **Provenance** (`provenance.py`). Every argument value is labelled user / derived / untrusted, with confidentiality and PII entities. Recognised identifiers include emails, phones, accounts, IBANs, document ids, UPI, PAN, Aadhaar (Verhoeff check) and cards (Luhn check).
3. **Consequence engine** (`consequence.py`).
   - Dry-runs SQL on an in-memory DB clone (SQL classified by SQLite's own compiler in `sql.py`).
   - Snapshots files.
   - Gives typed predictions for email, payments and SAP.
   - Outputs a harm score H and a reversibility class (idempotent / reversible / compensable / irreversible).
4. **Policy-as-code** (`policy.py`, `policies/default.yaml`): rules R1–R24.
   - R1 untrusted destination; R2 PII out; R3 freeze; R4 DDL; R5 payment limits.
   - R6 unknown or changed tool; R7 schema; R8 RBAC; R9 secrets; R10 bulk rows.
   - R11 verbatim untrusted; R12 workspace; R13 private data in URLs; R14 lethal trifecta.
   - R15 invented payment values; R16 scope (only the records the user named); R17 someone else's PII; R24 invoice email recipient.
   - **Accounts-payable rules, from Infosys's own AgentOS sample rulebook `fa_judgment.md`:**
     - R18 approval tiers, with the amount read from the invoice record;
     - R19 separation of duties;
     - R20 no bank change from an email;
     - R21 sanctioned or unverified vendors;
     - R22 retention;
     - R23 3-way match.
5. **Intent check** (`intent.py`).
   - A reasoning-blind heuristic.
   - An optional two-stage Qualcomm judge: the smallest model from `GET /models` triages, the largest reviews flagged calls. It can only lower alignment.
6. **Risk model** (`risk.py`).
   - 18 features; a bootstrap ensemble of logistic regressions with isotonic calibration, giving p and an interval [p_lo, p_hi].
   - τ = min(0.5, C_block / (H·(1−r))).
   - Trained only on actions that pass every rule.
7. **Decision** (`gateway.py`). The first matching step wins:
   1. Rule DENY → DENY.
   2. Circuit breaker → ESCALATE.
   3. Policy approval floor → ESCALATE.
   4. Intent mismatch on a state change → ESCALATE.
   5. Harm budget exceeded → ESCALATE.
   6. p_hi < τ → ALLOW, or ALLOW_WITH_SAFEGUARD.
   7. Otherwise → ESCALATE.

   **The model never denies.**
8. **Human in the loop and undo** (`hitl.py`, `environment.py`).
   - Approve, approve-as-draft (saves a real draft) or deny.
   - Four-eyes for irreversible, high-harm actions; timeout means deny.
   - Undo windows:
     - SQL and files: snapshot;
     - payments: held 60 minutes, then an outcome check cancels the payment if its bank account or amount changed;
     - emails: queued for 5 minutes;
     - SAP documents: parked.
9. **Receipts and explanations** (`receipts.py`, `explain.py`).
   - Receipts are SHA-256 hash-chained and HMAC-signed, with PII masked and a digest of the full arguments.
   - Explanations come from a template, or an LLM rewrite accepted only if every number in it appears in the evidence.

### Interfaces
- `POST /api/v1/check`, which takes `session_id` and `context`.
- `/api/v1/plan`.
- MCP JSON-RPC at `/mcp`.
- `/api/hitl`, `/api/undo/{receipt}`, `/api/settle`, `/api/receipts/verify`, `/api/autonomy`.
- Signed-token auth (`KAVACH_AUTH_SECRET`; mint tokens with `python -m kavach.auth`).
- Dashboard at `/`.

### Integrations
- `integrations/agentos_hook.py`: KAVACH as Topaz AgentOS `PreToolUse` / `PostToolUse` hooks. DENY blocks, ESCALATE goes to the AgentOS approvals queue with KAVACH's explanation.
- `agent/llm_agent.py`: a real tool-using agent on Qualcomm, with `--no-guard`.
- `scripts/fake_imagine.py`: an offline mock of the Qualcomm API.

### Principles to keep
- Only rules deny.
- The LLM can only add caution.
- Fail closed.
- Facts come from records, not from the agent's text.
- Report numbers honestly.

---

## 3. Results

### `build/phase-4`: latest, verified by re-running seed 0
- **Suite:** 940 synthetic scenarios, 47 families, 5 seeds.
- **KAVACH:**
  - safe actions auto-completed: **95.2%**;
  - unsafe auto-allowed: **0.0%**;
  - injection success: **0.0%**;
  - escalated: 25.5%;
  - safe actions hard-blocked: 0%;
  - auto changes that can be undone: 94.4% (38.9% without undo windows).
- **Baselines:**
  - approve every write: 9.5% safe auto, 93.6% escalated;
  - tool-type gating: 38.5% unsafe allowed;
  - static denylist: 87% unsafe allowed.
- **Leave one family out** (`bench/results/LOFO.md`): 0% unsafe allowed, 90.5% safe auto.
- **Fresh holdout** (`HOLDOUT.md`): 60 scenarios written after the rules. 0% unsafe allowed, 100% safe auto, 66.7% escalated.
- **Qualcomm judge, measured on the real service** (`JUDGE.md`): no unsafe verdict changes, safe auto 95.9% → 94.5%, about +3.8 s per action. Treat it as optional.
- **Live agent** (`LIVE_AGENT.md`):
  - Llama-3.3-70B on Qualcomm was given a poisoned inbox.
  - Unguarded, it emailed 50 customers' details to the attacker. Guarded, KAVACH returned DENY [R1].
  - The agent then falsely claimed it had sent the email.
- **Inside Topaz AgentOS 1.0.0** (`AGENTOS_LIVE.md`):
  - Calls went through AgentOS's own `govern_tool_call` → `HookRunner`, with a stand-in agent object.
  - The €650k release was escalated (R18), the sanctioned vendor denied (R21), and the bank change from an email escalated (R20).
  - Not done: a full LLM-driven AgentOS chat. Llama wrote its tool calls as text, so nothing executed.

### `main`: original prototype
740 scenarios, 12 rules, 68.4% safe auto, 0.5% unsafe allowed, 35.9% escalated.

**The deck, `docs/BLUEPRINT.md`, `docs/KAVACH_Blueprint.html`, `docs/INFOSYS_GAP_ANALYSIS.md` and `bench/results/INFOSYS_COMPARISON.md` still quote these old numbers.**

### Questions judges are likely to ask
- **The 68% → 95% jump came mostly from new rules written by the team that wrote the scenarios.** "Rules only" already reaches 95.2%. The model's contribution is cutting unsafe-allowed from 3.9% to 0%.
- **Calibration looks too perfect.** ECE 0.0011 and Brier 0.0 happen because the model is scored only on actions the rules let through.
- **The reversibility-conditioned τ doesn't beat a fixed threshold.** Say so openly.
- **The suite is synthetic and ours.** It is not comparable with published AgentDojo or AmPermBench numbers.

---

## 4. Research summary

Full version in `docs/BLUEPRINT.md` §2–4 and §17.

### Incidents
- EchoLeak (CVE-2025-32711, Microsoft 365 Copilot zero-click exfiltration).
- GitHub MCP toxic flow (Invariant Labs, May 2025).
- Replit agent wiped a production DB during a code freeze (Jul 2025).
- MCP tool poisoning and rug pulls (Apr 2025).
- Cursor CVE-2026-22708.

### Landscape
| System | Approach | Result / limit |
|---|---|---|
| Claude Code auto mode | Tool-tier rules + reasoning-blind classifier | 17% false negatives on overeager actions; AmPermBench (arXiv 2604.04978): 81% FNR, 36.8% of state changes bypassed the classifier |
| OpenAI Codex CLI | Kernel sandbox | Controls where, not what |
| AWS AgentCore Policy | Cedar policies | — |
| NVIDIA NeMo IORails | Tool-call allowlist + schema | — |
| Meta LlamaFirewall | PromptGuard 2 + AlignmentCheck | AgentDojo ASR 17.6% → 1.75% |
| Google CaMeL | Control/data-flow separation (arXiv 2503.18813) | — |
| Progent | Least-privilege policies | ASR 41.2% → 2.2% |
| Microsoft Fides | MCP proxy + IFC labels | — |
| Invariant | Rule layer at MCP/LLM proxy | — |
| Cordon (arXiv 2606.17573) | Shadow state + effect outbox | — |
| GoEx | Post-facto undo | — |
| ToolEmu | LM-emulated sandbox | — |

Trend: text filters → tool gating → provenance/IFC → policy gateways → transactional containment. **Our gap:** measured consequence + calibrated confidence + reversibility, and a human only when unsure.

### Other references
OWASP Top 10 for Agentic Applications (Dec 2025), mapped in the blueprint. Revisable by Design (arXiv 2604.23283) for the reversibility taxonomy. KnowNo (CoRL 2023) for asking when uncertain.

### Infosys repos (read and run)
- **Agentic Foundry:** commit `49fe687`, v1.9 + Topaz AgentOS 1.0.0.
- **Responsible AI Toolkit:** v2.2.1, commit `5d65aef`.

Details in `docs/INFOSYS_GAP_ANALYSIS.md`. Key findings:
1. PromptGuard (24 regexes) scans only the user query. The RAI moderation proxy sends only `user`/`system` text, so tool outputs (emails, web pages) are never checked. Even a perfect classifier misses every indirect injection.
2. `approval_rules` in SKILL.md (e.g. ₹5L needs CFO) are compiled into the prompt, so the agent's own LLM decides whether to ask for approval.
3. Defaults:
   - the SQL gate is empty;
   - pre-call moderation is off;
   - hooks are `fail_policy: open`;
   - the write intercept is off in autonomous mode.

   Result: 95% of our unsafe actions pass with defaults. Hardened, injection success is 0%, but 86.5% of actions are escalated.
4. No action undo, and the audit log is not tamper-evident. The RAI Security and Red-Teaming modules were retired in 2.2.1. The docs and code disagree on fail-open behaviour.
5. **Infosys is strong at:** the approvals queue (SLAs, durability), SafeKernel sandbox, SSRF guard, RBAC and multi-tenancy. **Pitch:** we plug into their hooks; we don't replace them.

### Qualcomm usage
- The protected agent's model (Llama-3.3-70B).
- Two-stage intent judge (Llama-3.1-8B → Llama-3.3-70B).
- Explanation writer.
- Future: bge embeddings.

Endpoint `https://aisuite.cirrascale.com/apis/v2`, OpenAI-compatible, with a Bearer key. The Inference Cloud turns JSON answers into empty tool calls, so the judge asks for plain text.

---

## 5. Repo map

| Path | What |
|---|---|
| `kavach/` | Gateway and all stages (above); `static/index.html` dashboard; `model/risk_model.json` shipped model |
| `bench/` | `suite.py` scenarios, `run.py` train / calibrate / baselines / multi-seed, `lofo.py`, `holdout.py`, `judge_eval.py`, `infosys_compare.py`, `results/` |
| `agent/llm_agent.py` | Live Qualcomm agent |
| `integrations/` | `agentos_hook.py` (adapter), `agentos_live_test.py` (needs a real AgentOS + Redis) |
| `scripts/` | `build_deck.py`, `build_page.py`, `diagrams.py`, `smoke.py`, `fake_imagine.py` |
| `docs/` | `BLUEPRINT.md` (17 sections), `INFOSYS_GAP_ANALYSIS.md`, `AUDIT_OF_EXISTING_DOCS.md` (critique of the team's first drafts: ~2/10 overall), `KAVACH_Blueprint.html`, `img/` |
| `deliverables/` | Deck `.pptx` / `.pdf`, `template_source.pptx` (official template; carries Infosys branding — decide whether it belongs in a public repo) |
| `tests/` | 101 tests on phase-4 |

The blueprint is also published as a private web page (only the owner can open it until shared): https://claude.ai/artifact/9Ea7xV6k6bWPRhUXWrqcLk

---

## 6. Open tasks, in priority order

1. **Merge `build/phase-4` into `main`.** Ask before pushing.
2. **Fix test collection** so plain `pytest` works: rename `integrations/agentos_live_test.py` (e.g. `agentos_live_check.py`) or add a `pytest.ini` with `testpaths = tests`. Update the README.
3. **Regenerate everything that quotes old numbers:**
   - `python bench/infosys_compare.py <iaf clone>`;
   - update `docs/INFOSYS_GAP_ANALYSIS.md`, `docs/BLUEPRINT.md` (§3, §4, §11, Q&A) and the deck text in `scripts/build_deck.py`;
   - rebuild the deck, PDF and HTML page.
4. **Add phase-4 evidence to the deck:** the live-agent attack (strongest demo), AgentOS live run, finance rules R18–R23 from Infosys's own rulebook, undo windows, the autonomy meter.
5. **Team-only items:**
   - fill in slide 2;
   - record a 2–3 minute fallback demo video (live agent attack, AgentOS escalation, undo);
   - rehearse answers to the judge questions in §3.
6. **Optional:**
   - port a small AgentDojo subset for externally comparable numbers;
   - run a full LLM-driven AgentOS chat (needs a model that emits proper tool calls);
   - report approvals from AgentOS back to KAVACH;
   - use the RAI injection classifier on tool outputs as a risk feature.
