# KAVACH: project instructions for Claude Code

KAVACH is our entry for **ET-03 "Agentic AI Guardrail Validator"** in the Infosys IGNITE ENG NEXT 2026 Hack-AI-Thon: check whether an AI agent's planned action is **safe, authorized, explainable and reversible** before it runs. Platform: Qualcomm Cloud AI Playground. Read `docs/HANDOFF.md` for the full context (competition, research, design, results, open tasks) before starting non-trivial work.

## Branches (check first)
- `main`: original prototype (740 scenarios, 12 rules, 68.4% safe auto). Deck, blueprint and Infosys comparison on `main` still describe this version.
- `build/phase-0` … `build/phase-4`: stacked work by dhanush-sr (1–2 Nov 2026). **`build/phase-4` contains all of it** and is a fast-forward of `main` except for the commit that added this file. Latest: 940 scenarios, 47 families, rules R1–R24, 95.2% safe auto, 0% unsafe auto-allowed, real Qualcomm runs, KAVACH verified inside Topaz AgentOS.
- First open task: merge `build/phase-4` into `main` (ask the user before pushing).

## Commands
```bash
pip install -r requirements.txt            # Python 3.11+
python -m pytest tests -q                  # NOT plain `pytest`: integrations/agentos_live_test.py needs a real AgentOS
python -m bench.run --quick                # seed-0 benchmark (~1 min); without --quick also 5 seeds
python -m bench.lofo ; python -m bench.holdout
python -m uvicorn kavach.server:app --port 8000   # dashboard http://localhost:8000
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

## Working conventions
- Report numbers honestly. The suite is synthetic and written by us; say so. If a change moves a benchmark number, regenerate `bench/results/*` and every doc/slide that quotes it (README, docs/BLUEPRINT.md, docs/INFOSYS_GAP_ANALYSIS.md, scripts/build_deck.py text, deck PDF, HTML page).
- Never claim something was run live (Qualcomm, AgentOS) unless it was; label rehearsals with the mock as rehearsals.
- Synthetic data only; no real customer data, credentials or keys in the repo.
- Git: don't force-push or rewrite history without asking. Commit author is VismayHS <vismayhs@gmail.com>.
- `bench.run` overwrites `kavach/model/risk_model.json`; commit model + results together or restore the file.
