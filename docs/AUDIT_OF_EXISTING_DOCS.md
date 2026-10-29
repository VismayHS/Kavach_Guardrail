# Brutal audit of the team's ET-03 material

**Scope:** the four documents and one template the team shared on 26 Oct 2026, judged against what an ET-03 judging panel will ask for. The panel's questions: does it work, how does data flow, what is the decision logic, how confident is it, where is the human, why this design, what runs on Qualcomm, and how does it scale and stay secure.

**Verdict in one line:** the research is above hackathon average, but **none of it had been turned into a single design, a single name or a single line of running code**. Every document stops at a list of components. None of them defines the data flowing between components, the decision procedure, the confidence model or the human-in-the-loop protocol. Those are exactly the four things the team said were missing.

| # | Document | What it is | Score /10 | One-line judgement |
|---|---|---|---|---|
| 1 | `Infosys_ENGNEXT_2026_Winning_PS_Analysis.md` | PS selection across 23 statements | **3.5** | Recommends a *different* PS (NC-04); ET-03 gets one page of bullet points |
| 2 | `ET03_Guardrail_Validator_Strategy (2).pdf` | First solution concept ("gateway", four lights) | **4.5** | Best product instinct (Infosys integration) but an LLM sits in the decision path and nothing is quantified |
| 3 | `DOC-20260928-WA0009.pdf` (critical audit) | Corrections to doc 2 | **6.0** | Accurate and useful as a correction; contains no design, no build plan the team can execute in time, and no Qualcomm plan |
| 4 | `ET-03_Guardrail_Research_Dossier.pdf` ("REVOKE") | Research dossier + playbook | **6.5** | Has the one genuinely good idea (reversibility-conditioned threshold) but never says where the probability comes from, ignores Infosys, and over-engineers the ML |
| — | Combined state of the project | | **~2 / 10 on the judging rubric** | Research ≈ 30% done, design ≈ 10%, build 0%. A working demo is the hard cap: without one, the internal rubric caps the score at 65/100 regardless of slides |

The scoring dimensions behind each number: factual accuracy, PS coverage, decision logic, confidence/calibration, HITL design, data flow, evaluation, Qualcomm usage and buildability.

---

## 1. `Infosys_ENGNEXT_2026_Winning_PS_Analysis.md` — 3.5/10

**What is good**
- Correct instinct: "a weak team builds `prompt → LLM → BLOCK`; a winning team builds a deterministic pre-execution safety compiler."
- The "judge Q&A" line is the single most valuable sentence across all your docs: *"Why should one AI model be trusted to judge another? It should not."*
- The internal rubric and the self-penalties (−15 for an LLM wrapper, a cap of 65 without a working demo) are a good self-check.

**What is bad**
1. **It recommends NC-04, not ET-03.** The team is building against its own primary recommendation. Anyone who reads this file will ask why.
2. **The ET-03 section is a list of nouns.** "Identity check, taint propagation, reversibility, blast radius, side-effect reachability, policy-as-code, counterfactual execution, HITL, audit." Nothing says how one stage feeds the next, what a stage outputs, or how ten signals become one decision.
3. **The scores are invented precision.** "93/100", "Novelty 19/20" come from a self-made rubric. Putting them on a slide invites the question "measured how?"
4. **"Counterfactual/sandbox execution" is undefined.** You cannot sandbox an email or a bank transfer, and the doc never says what happens then. (Doc 3 caught this later.)
5. **Unverified citation.** "OWASP guidance emphasises reversibility classification, blast-radius gating…" is cited to an OWASP Cornucopia companion page. The authoritative source is the **OWASP Top 10 for Agentic Applications (9 Dec 2025)**, ASI01–ASI10, which the doc never names.
6. Roughly 90% of the file covers other problem statements and is now dead weight.

**Replace with:** the KAVACH blueprint (`docs/BLUEPRINT.md`) §5–§9, which defines each stage's input, output and decision rule.

---

## 2. `ET03_Guardrail_Validator_Strategy (2).pdf` — 4.5/10

**What is good**
- **The Infosys angle is the best strategic idea anyone had.** Infosys open-sourced Agentic AI Foundry and the Responsible AI Toolkit. A guardrail that drops into Infosys's own stack is something a sponsor can adopt.
- The four-light scorecard maps the PS's four words to evidence. Judges love a visible mapping to the PS.
- Five outcomes rather than two, a decision receipt, an attack-first demo and a Tier 1 vs Tier 2 framing.

**What is bad (and why it would lose points)**
1. **An LLM is in the security decision path.** "Layer 3: semantic judge on Qualcomm Cloud AI", plus "plain-English policy compiler", "red-team attack generation", "effect prediction". That puts five model tasks in the loop. Any text the agent read can attack a model that reads agent-adjacent text. This contradicts doc 1's best line. *Fix:* the model contributes one feature and the explanation, and it can only **raise** scrutiny (KAVACH `intent.py`).
2. **The four lights are combined as if they were equal.** "Authorized" is a hard gate, not a colour that the other three can outvote. *Fix:* hard gates first (DENY is final), then the risk model.
3. **There is no decision math, no probability and no confidence.** What makes an action "uncertain" enough for a human? The doc never says. This is the gap you named.
4. **The "digital twin shows exactly what would change" claim is false.** It can't hold for email, payments or any external API. *Fix:* a capability matrix: sandbox where forkable, static where computable, predicted (and labelled as predicted) otherwise.
5. **The prior-art claims are outdated or wrong.** Doc 3 found these, and we re-verified them:
   - Foundry *does* have Tool Validation, Validators, Tool Interrupt, a plan verifier (v1.7.0, Feb 2026) and sandboxed tool execution (v1.9.0, May 2026).
   - NeMo Guardrails *does* validate tool calls before execution: IORails, opt-in and experimental, with structural checks only (allowlist + JSON Schema).
6. **"90%+ auto-approved" and "41 ms" are fabricated targets presented next to real-looking UI.** A judge who asks "where's that from?" ends the credibility of every other number.
7. **"REPLAN" is listed as a decision.** Replanning is what the agent does after a DENY; it is not a security outcome.
8. **The learning loop promotes bypass rules into the policy after "a human approves".** An attacker can poison that loop. *Fix:* candidate rule → regression suite → review → versioned policy → canary.
9. **No HITL protocol.** It doesn't say who approves, how fast, what happens on timeout, how you stop the requester approving their own request, or how you measure approval fatigue.
10. **The 12-week roadmap assumes time the team does not have**, and the "Week 1 checklist" requires installing five external systems before a single line of your own code exists.

---

## 3. `DOC-20260928-WA0009.pdf` (the critical audit) — 6.0/10

**What is good**
- It is the most *accurate* document you have. The corrections to Foundry, NeMo, Fides and Invariant are right, and we re-verified them against the repos.
- The five-class reversibility table (reversible / compensable / previewable / predictable-non-forkable / irreversible) and the 10-step control flow are correct.
- The metrics are right: ASR, task completion, false block, escalation, latency, policy precision, provenance accuracy, consequence accuracy. So is the rule "never compare published numbers that weren't produced under the same protocol."
- The replacement wording table (§12) should be kept and used in the Q&A.

**What is bad**
1. **It is a critique, not a design.** It names the right controls but never specifies one: no schemas, no thresholds, no algorithm, no UI.
2. **Its Week-1 plan is unexecutable for a student team.** "Run Foundry, test Tool Interrupt, run NeMo IORails, run Fides Gateway, run Invariant, run Progent" is six heavyweight systems, three of them research code. The "kill criterion" (beat all five on your task set in week 1) would kill every hackathon project. *Fix:* reproduce baselines that represent each *design* (text denylist, tool-type gating, approve-every-write, rules-only, LLM judge) inside one harness, and cite the published systems as related work with their published numbers clearly labelled as such.
3. **No confidence model.** "ALLOW / SAFEGUARD / APPROVAL / DENY" is stated, but it never says what moves an action between these states.
4. **Nothing on Qualcomm, nothing on the UI, nothing on scalability or securing the guardrail itself.**
5. "Previewable" and "predictable but non-forkable" are a property of the *mechanism* (how we learn the effect), not of reversibility. Mixing the two axes confuses the decision math. *Fix:* KAVACH keeps them separate. `Effect.method ∈ {sandbox, static, predicted}` and `Reversibility ∈ {idempotent, reversible, compensable, irreversible}`.

---

## 4. `ET-03_Guardrail_Research_Dossier.pdf` ("REVOKE") — 6.5/10

**What is good**
- **The core idea is genuinely good and defensible:** set the strictness from what happens if you're wrong. `allow iff p·H·(1−r) < C_block ⇔ p < τ = C_block / (H(1−r))`. This turns "safe / reversible" from labels into a decision rule. Keep it.
- Excellent landscape work: Claude Code auto mode (0.4% FPR / 17% FNR, two-stage, reasoning-blind), AmPermBench (81% FNR, 36.8% Tier-2 bypass), Cordon, Revisable-by-Design, Codex, Cursor and Gemini CVEs. We verified the key numbers (see `BLUEPRINT.md` §3).
- UAR/OBR framing, the hostile Q&A, "the LLM never makes the decision, it only writes the explanation," and the claims-we-must-not-make table.

**What is bad**
1. **`p` appears from nowhere.** "Classifier + policy signals, calibrated" without features, training data, model, or how it is calibrated. The whole formula rests on `p`. *Fix:* 18 typed features, a bootstrap ensemble of logistic models, isotonic calibration on a held-out split, reported ECE (KAVACH `risk.py`, `bench/run.py`).
2. **A blind spot that our testing exposed.** A reversibility-conditioned threshold auto-allows *wrong* actions whenever they are reversible: τ → 1 as r → 1. In our first benchmark run, an overeager `DELETE … WHERE city=…` (user asked to remove one duplicate) was auto-allowed "because undo exists". Undo only helps if someone notices. *Fix:* a probability ceiling `τ = min(p_max, C_block/(H(1−r)))`, plus a `target_mismatch` feature (the user named customer 17; the action never touches 17).
3. **Over-engineered ML for the time available.** A self-supervised blast-radius predictor trained on staged runs, transferred to unstageable actions, with conformal intervals, is a research project. *Fix:* for unstageable actions, compute blast radius *deterministically* from arguments and provenance (recipients, external domains, PII count, amount, payee known). Learning is reserved for `p`, where it belongs.
4. **Infosys is absent.** The dossier dropped doc 2's best idea entirely. *Fix:* KAVACH speaks MCP, which Foundry already integrates. The integration is "register KAVACH as the MCP endpoint", plus a Foundry Tool Interrupt that fires only on ESCALATE.
5. **The "Comparative Ratings" table (Claude Code 7.5, Codex 7.0 …) is judgement dressed as data.** Never put it on a slide.
6. **The DeepSeek motivation slide is off-platform.** The Qualcomm playground serves **Llama** models, and the strongest motivation is about Llama itself. In the UK AISI × Gray Swan agent red-teaming challenge (1.8 M attacks, 22 models), every model was broken, and **Llama-3.3-70B had the highest attack success rate (6.49%)**. That is the model the playground serves. It is a cleaner and more relevant argument for an external guardrail.
7. **No data-flow diagram, HITL protocol, security model for the guardrail itself, or scalability story.**
8. Many `[S]` claims were left unverified. We verified: CaMeL 77% vs 84% (arXiv 2503.18813 v2+; 67% in v1), LlamaFirewall 17.6% → 1.75% (the paper says 1.75%, not 1.7%), AgentDojo 97 tasks / 629 cases, Replit incident details (the agent said rollback was impossible; it worked), and Progent 41.2% → 2.2% (v1).

---

## 5. The template (`Hack-AI-Thon_Solution_Presentation_Template.pptx`)

Seven content slides plus DEMO, with suggested times totalling **≈ 4:10** (0:20 + 0:55 + 0:55 + 0:45 + 0:35, plus the problem slide). The template **explicitly asks** for:
- *"State exactly where AI is used and why a simpler rule-based approach is insufficient"* and *"what happens when AI is uncertain"* (slide 6). None of your docs answer this.
- *"Mention one constraint, test or fallback that demonstrates engineering depth"* (slide 5).
- *"Separate what works now from what is planned"* (slide 7). Your docs mix the two everywhere.

The filled deck (`deliverables/KAVACH_Solution_Deck.pptx`) answers each of these in the template's own boxes.

---

## 6. What changed, mapped to each weakness

| Weakness (doc) | What KAVACH does instead | Where |
|---|---|---|
| LLM decides (2) | Deterministic gates → calibrated statistical model → LLM is one monotone feature + explainer | `policy.py`, `risk.py`, `intent.py` |
| No `p` source (4) | 18 typed features, bootstrap logistic ensemble, isotonic calibration, held-out ECE | `risk.py`, `bench/run.py` |
| No confidence (all) | `[p_lo, p_hi]` from ensemble spread; interval straddles τ ⇒ ESCALATE | `gateway._decide` |
| Reversible ⇒ auto-allow (4) | `p_ceiling` + `target_mismatch` feature | `risk.py` |
| "Digital twin" overclaim (2) | Effect `method` reported per action: sandbox / static / predicted | `consequence.py` |
| No HITL protocol (all) | Consequence card, approve / approve-as-draft / deny, four-eyes, timeout = deny, labels fed back | `hitl.py` |
| No data flow (all) | Typed `ToolCall → Label → Effect → GateResult → Risk → Decision → Receipt` | `models.py`, `BLUEPRINT.md` §6 |
| Unverifiable numbers (2) | Every number comes from `bench/results/` on a held-out split, over 5 seeds | `bench/` |
| Infosys missing (4) | MCP front door; Foundry integration path; RAI Toolkit privacy API as PII detector (roadmap) | `server.py /mcp` |
| Qualcomm vague (2, 3, 4) | Exact Imagine API contract read from the official SDK wheel; 3 roles; fail-safe fallback | `qualcomm.py` |
| Three names (AegisGraph / REVOKE / gateway) | One name: **KAVACH**, matching your repo `VismayHS/Kavach_Guardrail` | — |
