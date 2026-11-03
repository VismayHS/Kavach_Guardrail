# KAVACH: project instructions for Claude Code

KAVACH is our entry for **ET-03 "Agentic AI Guardrail Validator"** in the Infosys IGNITE ENG NEXT 2026 Hack-AI-Thon: check whether an AI agent's planned action is **safe, authorized, explainable and reversible** before it runs. Platform: Qualcomm Cloud AI Playground. Read `docs/HANDOFF.md` for the full context (competition, research, design, results, open tasks) before starting non-trivial work.

## Branches (check first)
- `main` (`b3c4b1b`): `build/phase-5` (PR #1) and `vismay-dev` (PR #2) merged.
- `build/phase-5` (Ashwin): `main` + `build/e2e-demos` merged (3 Nov) + his later work (R42 user-only arguments, AgentDojo replay, link and provenance fixes).
- `build/e2e-demos` / `build/live-demo` (dhanush-sr): `build/phase-5` + the live demo with real effects: Mailpit cancel-before-delivery lifecycle, sandbox bank, R41 (pay only the vendor's account on record), Live demo page (#/demo), Claude locked to `/mcp`, with/without comparison, optional Gmail. See `docs/LIVE_DEMO.md`.
- `build/phase-0` … `build/phase-4` (`4c42d4e`): stacked work by dhanush-sr (1–2 Nov 2026): 940 scenarios, 47 families, rules R1–R24, undo windows, Qualcomm judge, AgentOS hook.
- **`vismay-dev`** (the most complete branch): `main` + `build/phase-5` + `build/live-demo` + Vismay's work, one fix per commit, every commit tested. Rules R35–R40 (R25–R34 are Phase 5's; R41 is the invoice-account rule, R42 the user-only-arguments rule; new rules start at R43), SQL sandbox authorizer, server-set environment (`KAVACH_ENV`), orchestrator/agent tokens, per-task totals across delegation chains, signed receipt checkpoint on the Phase 5 store, and the eval scripts (`bench/layers.py`, `semantic_eval.py`, `explain_eval.py`). This work's log and open items: `docs/SESSION_HANDOFF.md`; changes to teammates' files: `docs/MERGE_NOTES.md`; project context: `docs/HANDOFF.md`. `build/truth-check` is not merged anywhere.
- Merging into `main` is a team decision; ask before pushing anything but `vismay-dev`.

## Commands
```bash
pip install -r requirements.txt            # Python 3.11+
python -m pytest -q                        # every test; a commit must keep them all passing
python -m bench.run --quick                # seed-0 benchmark (~1 min); without --quick also 5 seeds
python -m bench.conformal                  # after bench.run: model rows for the learning loop + CONFORMAL.md
python -m bench.lofo ; python -m bench.holdout ; python -m bench.layers
python -m bench.redteam fuzz ; python -m kavach.policy_verify     # offline red team; Cedar proofs + parity
pip install -r requirements-extra.txt      # optional features (Cedar, OTel, MCP, AgentDojo...); their tests skip without
python -m bench.semantic_eval --offline     # judge-on runs need the Qualcomm key (rehearsals go to bench/results/rehearsal/)
python -m uvicorn kavach.server:app --port 8000   # dashboard http://localhost:8000
scripts/demo_up.sh ; scripts/demo_reset.sh ; scripts/demo_claude.sh [--without-kavach]   # live demo: docs/LIVE_DEMO.md
python scripts/build_deck.py && (cd deliverables && soffice --headless --convert-to pdf KAVACH_Solution_Deck.pptx)
python scripts/build_page.py               # docs/KAVACH_Blueprint.html from docs/BLUEPRINT.md
python bench/infosys_compare.py <clone of Infosys/Infosys-Agentic-Foundry>
```
Qualcomm: `IMAGINE_API_KEY` + `IMAGINE_API_ENDPOINT=https://aisuite.cirrascale.com/apis/v2` (or `INFERENCE_CLOUD_*`) in env or `.env`. Never commit keys. Offline mock: `python -m uvicorn scripts.fake_imagine:app --port 9100`.

## Design rules (do not break)
- Only deterministic **rules** may DENY. The risk model can only ALLOW or ESCALATE. A policy approval floor always ESCALATEs.
- The LLM (Qualcomm judge, explainer) can only make decisions **stricter**; explanations are rejected if they contain numbers not in the evidence.
- Fail closed: unknown tools, timeouts, LLM errors never become ALLOW.
- Payment facts come from records, never from the agent's text. Provenance is per value (user / derived / untrusted).
- Every decision writes a hash-chained, HMAC-signed receipt.
- Agent-kind tokens never supply the user's request or tool outputs; the server, not the caller, sets the environment.

## Working conventions
- Report numbers honestly. The suite is synthetic and written by us; say so. If a change moves a benchmark number, regenerate `bench/results/*` and every doc/slide that quotes it (README, docs/BLUEPRINT.md, docs/INFOSYS_GAP_ANALYSIS.md, scripts/build_deck.py text, deck PDF, HTML page).
- Never claim something was run live (Qualcomm, AgentOS) unless it was; label rehearsals with the mock as rehearsals.
- Synthetic data only; no real customer data, credentials or keys in the repo.
- Git: don't force-push or rewrite history without asking. Commit author is VismayHS <vismayhs@gmail.com>, and only VismayHS: no `Co-Authored-By` or other attribution trailers in commit messages.
- `bench.run` overwrites `kavach/model/risk_model.json`; run `python -m bench.conformal` after it (it puts the train/cal/test rows the learning loop needs back into the model file), then commit model + results together, or restore the file.
- `python -m bench.redteam fuzz` rewrites `bench/results/REDTEAM.md` without its hand-written "Found and fixed" section; keep that section.
- Commits: one fix per commit, its regression test in the same commit, the full suite passing at that commit. Attack first (a test that fails on the old code), then the fix.
- Runs against `scripts/fake_imagine.py` are rehearsals: they write to the git-ignored `bench/results/rehearsal/`, never to a results file.
