# KAVACH: pre-execution action firewall for AI agents

**ET-03 · Agentic AI Guardrail Validator** · Infosys IGNITE ENG NEXT 2026 Hack-AI-Thon

Before an AI agent's tool call touches the real world, KAVACH works out:
- **what it will actually do**: a sandbox diff where the effect can be staged, a typed prediction where it can't;
- **where every argument came from**: the user, the agent, or untrusted content;
- **whether it can be undone**.

It then **allows** the call, **allows it with undo armed**, **escalates it to a human**, or **blocks it** with a replan hint, and writes a tamper-evident receipt. Undo means a snapshot for SQL and file changes, a 60-minute hold for payments, a 5-minute recall window for emails, and parking for SAP postings (nothing is booked until a person posts them). When a held payment is about to go out, KAVACH checks it is still the one that was approved (same bank account, same amount) and cancels it if not. Authorization and provenance are deterministic code. A small calibrated model ranks the remaining risk. An LLM on Qualcomm Cloud AI is used only for ambiguous intent checks and plain-English explanations, and it can only make the system *stricter*.

![architecture](docs/img/architecture.png)

## Quick start

```bash
pip install -r requirements.txt
python -m pytest -q                       # 81 tests
python -m bench.run                       # trains the risk model, benchmarks vs baselines (5 seeds)
python -m bench.lofo                      # each family judged by a model trained without it
python -m bench.holdout                   # families written after the rules, never trained on
python -m uvicorn kavach.server:app --port 8000   # then open http://localhost:8000
```

Optional, Qualcomm Cloud AI (Imagine API, OpenAI-compatible):

```bash
export IMAGINE_API_KEY=...                                    # from the Qualcomm Cloud AI Playground
export IMAGINE_API_ENDPOINT=https://aisuite.cirrascale.com/apis/v2
export KAVACH_JUDGE_MODEL=Llama-3.1-8B                        # check GET /models for your key
python -m agent.llm_agent "Summarise my unread emails."               # live agent, guarded
python -m agent.llm_agent "Summarise my unread emails." --no-guard    # same agent, unguarded
```

Offline rehearsal of the Qualcomm path: `python -m uvicorn scripts.fake_imagine:app --port 9100`, then set `IMAGINE_API_ENDPOINT=http://localhost:9100 IMAGINE_API_KEY=x`.

## API

| Endpoint | Purpose |
|---|---|
| `POST /api/v1/check` | Raw action input → decision, scorecard, explanation, receipt (the PS's "agent action input → approve/block → explanation") |
| `POST /api/v1/plan` | Validate a whole plan before step one |
| `POST /mcp` | MCP JSON-RPC (`initialize`, `tools/list`, `tools/call`): put KAVACH between any MCP client and the tools |
| `POST /api/demo/{scenario}` | Replay a scripted attack or benign scenario |
| `GET/POST /api/hitl[/{id}]` | Human approvals (approve / approve-as-draft / deny) |
| `POST /api/undo/{receipt}` | Take back a safeguarded action: restore its snapshot, or cancel its hold, recall window or parked document |
| `POST /api/settle?advance_s=` | Let held payments and queued emails whose window has passed go out (`advance_s` fast-forwards for the demo) |
| `GET /api/receipts/verify` | Verify the hash chain |

Auth: set `KAVACH_AUTH_SECRET` (32+ random bytes) and the API requires `Authorization: Bearer <token>`; user and role come from the token (`python -m kavach.auth mint <user> <role>`), never from the request body. Without it the server runs in dev mode and every receipt records `authenticated: false`.

## Layout

```
kavach/   models · manifest · provenance · consequence · policy (+ policies/default.yaml) · intent · risk
          gateway · hitl · receipts · explain · plan · qualcomm · environment · scenarios · server · static/
bench/    suite.py (labelled scenarios) · run.py (train, calibrate, baselines, Pareto, multi-seed) · lofo.py · holdout.py
          infosys_compare.py · results/
agent/    llm_agent.py: real tool-using agent on Qualcomm Cloud AI behind KAVACH
integrations/  agentos_hook.py: KAVACH as Infosys Topaz AgentOS hooks
docs/     BLUEPRINT.md (end-to-end design + research) · INFOSYS_GAP_ANALYSIS.md · AUDIT_OF_EXISTING_DOCS.md · img/
deliverables/  KAVACH_Solution_Deck.pptx (filled Hack-AI-Thon template + appendix)
```

## Plugging into Infosys Topaz AgentOS

`integrations/agentos_hook.py` runs KAVACH as AgentOS `PostToolUse` / `PreToolUse` hooks: DENY blocks the call, ESCALATE goes to the AgentOS `#approvals` queue, everything else runs. The config snippet is in the file header.

We read and ran Infosys's own guardrails (PromptGuard, RAI moderation proxy, AgentOS pre-tool gate) on our suite:

```bash
git clone --depth 1 https://github.com/Infosys/Infosys-Agentic-Foundry ../iaf
python bench/infosys_compare.py ../iaf          # writes bench/results/INFOSYS_COMPARISON.md
```

Findings and the gaps they show: [`docs/INFOSYS_GAP_ANALYSIS.md`](docs/INFOSYS_GAP_ANALYSIS.md).

## Results

See [`bench/results/RESULTS.md`](bench/results/RESULTS.md), [`LOFO.md`](bench/results/LOFO.md) (leave one family out) and [`HOLDOUT.md`](bench/results/HOLDOUT.md). The suite is synthetic: its scenario families mirror the axes of AgentDojo and AmPermBench, but the numbers are **not** comparable with results published on those benchmarks.
