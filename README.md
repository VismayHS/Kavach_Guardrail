<h1 align="center">KAVACH</h1>

<p align="center"><strong>A pre-execution security layer for AI agents</strong></p>

<p align="center">
KAVACH evaluates every tool call an AI agent proposes, before the call can affect data, money or people.<br>
Built for problem statement ET-03, Agentic AI Guardrail Validator, at Infosys ENG NEXT 2026.
</p>

<p align="center">
<a href="#overview">Overview</a> ·
<a href="#how-a-decision-is-made">Decision pipeline</a> ·
<a href="#the-console">Console</a> ·
<a href="#getting-started">Getting started</a> ·
<a href="#evaluation">Evaluation</a> ·
<a href="#limitations">Limitations</a>
</p>

![KAVACH blocking a forged claim approval, with the reasoning for the decision](docs/img/console/forged-approval-blocked.png)

<sub>A claim email instructed the agent to tell the customer the claim was approved. The recipient was legitimate, so a recipient check would have passed. KAVACH refused the email because the approval wording came from the untrusted message and the user had withheld that authority.</sub>

## Overview

Agents now send email, change records and move money. A single wrong tool call can leak data or commit an organisation to something nobody approved, and the instruction behind that call may have arrived inside a document the agent was only asked to read.

KAVACH sits between the agent and its tools. For each proposed call it determines:

| Question | Mechanism |
|---|---|
| Is the call **safe**? | The effect is staged in a sandbox where possible and predicted from typed arguments where not. |
| Is it **authorized**? | Deterministic policy rules, role checks, and the origin of every argument. |
| Is it **explainable**? | Each decision carries a plain-language reason, the rules evaluated, and the evidence used. |
| Is it **reversible**? | Snapshots, hold windows and cancellation, wherever the execution path allows them. |

Each call receives one of four outcomes, and each outcome is written to a tamper-evident receipt:

| Verdict | Meaning |
|---|---|
| `ALLOW` | The call runs. |
| `ALLOW_WITH_SAFEGUARD` | The call runs with undo armed, for example a 30-second hold before an email leaves. |
| `ESCALATE` | The call waits for a person, and approval is bound to that exact action. |
| `DENY` | The call does not run. The agent receives the reason and a suggested alternative. |

### Design principles

- **Only deterministic rules can deny.** The risk model can only allow or escalate, and a language model can only make a decision stricter. A deceived model cannot release a blocked action.
- **Provenance is tracked per value.** A recipient, amount or account is traced to the user, to KAVACH's records, or to untrusted content.
- **Unknown means no.** Unknown tools, changed tool definitions, timeouts and model errors never become an allow.
- **No record, no action.** If a receipt cannot be written durably, the call fails closed.
- **Credentials stay out of the agent.** The agent holds no mailbox password or API secret; connectors run on KAVACH's side of the boundary.

## How a decision is made

```mermaid
flowchart LR
    A[Agent proposes<br>a tool call] --> B[Tool manifest<br>and schema check]
    B --> C[Argument<br>provenance]
    C --> D[Consequence<br>analysis]
    D --> E[Policy rules<br>R1 to R45]
    E --> F[Intent check and<br>calibrated risk model]
    F --> G{Verdict}
    G -->|ALLOW| H[Execute]
    G -->|ALLOW_WITH_SAFEGUARD| I[Hold or snapshot,<br>then execute]
    G -->|ESCALATE| J[Human approval]
    G -->|DENY| K[Refuse with reason]
    H --> L[(Signed, hash-chained<br>receipts)]
    I --> L
    J --> L
    K --> L
```

| Stage | Purpose | Implementation |
|---|---|---|
| Manifest | Types each tool's effect, pins its definition by hash, and refuses changed definitions | `kavach/manifest.py` |
| Provenance | Labels each argument as trusted, derived or untrusted, with its source | `kavach/provenance.py` |
| Consequence | Measures or predicts the effect: rows changed, recipients, data leaving, reversibility | `kavach/consequence.py`, `kavach/sql.py`, `kavach/shell.py` |
| Policy | Applies 45 rules defined as policy-as-code, with Cedar proofs and parity checks for the core rules | `kavach/policy.py`, `kavach/policies/` |
| Intent and risk | Scores fit with the request and estimates the probability of harm, conditioned on reversibility | `kavach/intent.py`, `kavach/risk.py` |
| Approval | Binds a human decision to a digest of the exact action; each approval is single-use and expires | `kavach/hitl.py`, `kavach/gateway.py` |
| Record | Writes HMAC and Ed25519 signed receipts in a hash chain with a signed checkpoint | `kavach/receipts.py`, `kavach/signing.py` |

### Representative rules

| Rule | Protection | Outcome |
|---|---|---|
| R1 | Untrusted content cannot choose a recipient, URL, account or amount | Deny |
| R45 | An email announcing a decision needs the authorised reviewer; wording copied from content the agent read is refused | Approval or deny |
| R43 | A first email to a new outside address needs a person | Approval |
| R44 | Content marked Internal Only or Confidential cannot be emailed outside | Deny |
| R41 | An invoice is paid only to the vendor's account on record, for the invoice amount | Deny |
| R3, R4 | No production writes during a change freeze; no destructive schema changes in production | Deny |
| R36 | Totals across a task count: rows changed, money moved, data emailed, repeated actions | Approval |
| R28 | Canary records exist only to be stolen; any external action carrying one is blocked | Deny |

The complete catalogue is in [`kavach/policies/default.yaml`](kavach/policies/default.yaml) and on the console's Rulebook page.

### Use of language models

Language models are advisory and are not on the path that blocks or releases an action.

| Component | Role | If unavailable |
|---|---|---|
| Intent judge | Sees only the user's request and the proposed action, never the agent's reasoning or raw tool output. By default it adds a note for the reviewer on escalated calls. | Heuristic score; the decision is unaffected |
| Explainer (optional) | Rewrites the explanation in plain language; rejected if it adds numbers absent from the evidence | Template explanation |
| Planner (optional) | Writes a plan from the request alone, before any untrusted content is read | Planner mode unavailable |

Hosted models run on Qualcomm Cloud AI through an OpenAI-compatible API.

## The console

The console shows each action an agent requests, the decision, and what happened afterwards.

![Activity page](docs/img/console/activity.png)

<table>
<tr>
<td width="50%"><img src="docs/img/console/injection-blocked.png" alt="Prompt injection blocked"><br><strong>Prompt injection.</strong> The recipient is traced to an email the agent read, not to the user.</td>
<td width="50%"><img src="docs/img/console/confidential-blocked.png" alt="Confidential content blocked"><br><strong>Data policy.</strong> The auditor is a trusted address, but content marked Internal Only may not leave.</td>
</tr>
<tr>
<td><img src="docs/img/console/approval-required.png" alt="Approval required"><br><strong>Human approval.</strong> The reviewer sees the exact recipient and content; nothing runs until they decide.</td>
<td><img src="docs/img/console/cancelled-before-delivery.png" alt="Cancelled before delivery"><br><strong>Cancel before delivery.</strong> An allowed email waits in a hold window and can be cancelled before it leaves.</td>
</tr>
</table>

| Trace of a single action | Evaluation summary |
|---|---|
| ![Trace page](docs/img/console/trace.png) | ![Results page](docs/img/console/results.png) |

| Policy rulebook | Operations dashboard (Grafana) |
|---|---|
| ![Rulebook page](docs/img/console/rulebook.png) | ![Grafana dashboard](docs/img/console/grafana.png) |

<sub>Captured from KAVACH connected to a real mailbox, using synthetic content. The tool calls were issued by a test harness, so the agent names are labels. Email addresses were replaced with placeholders.</sub>

## Getting started

### Requirements

- Python 3.11 or later
- Docker, for the optional observability stack
- Optional: a Qualcomm Cloud AI key, a Gmail App Password, Claude Code

### Install and run

```bash
git clone https://github.com/VismayHS/Kavach_Guardrail.git
cd Kavach_Guardrail
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python -m pytest -q
python -m uvicorn kavach.server:app --port 8000
```

Open <http://127.0.0.1:8000>. The scripted scenarios, action checker, approvals, undo windows, receipts, results and rulebook work without any external key.

### Connect a real agent to a real mailbox

Add the mailbox credentials to a local `.env` file, which is ignored by Git. Never commit this file.

```bash
KAVACH_GMAIL_USER=you@example.com
KAVACH_GMAIL_APP_PASSWORD=your-app-password
KAVACH_MAIL_TRUSTED=auditor@example.com    # optional: addresses exempt from first-contact approval
```

Start KAVACH, then start an agent in a second terminal:

```bash
scripts/gmail_up.sh       # KAVACH on the mailbox; console at http://127.0.0.1:8000/#/activity
scripts/demo_claude.sh    # Claude Code, restricted to KAVACH's MCP endpoint
```

The demo script starts Claude Code with built-in tools disabled and KAVACH as its only MCP server. Mailbox reading is read-only, and every outgoing email waits in a 30-second hold.

`scripts/llama_agent.py` runs Llama 3.3 70B on Qualcomm Cloud AI against the same endpoint. `scripts/hijacked_agent.py` is a test harness with no model that obeys injected instructions, for exercising KAVACH when a model resists them.

### Observability

```bash
docker compose up -d otel-collector prometheus grafana jaeger
```

| Service | Address |
|---|---|
| Grafana | <http://localhost:3000> |
| Prometheus | <http://localhost:9090> |
| Jaeger | <http://localhost:16686> (service `kavach-gmail`) |

The dashboard covers decisions by verdict, rule activity, latency, approvals, holds, delivery outcomes, receipt-chain health, and model usage. Model cost is an estimate from a versioned table of reference prices in [`kavach/model_prices.json`](kavach/model_prices.json); those are not prices published by Qualcomm.

## Integration

| Endpoint | Purpose |
|---|---|
| `POST /mcp` | MCP JSON-RPC (`initialize`, `tools/list`, `tools/call`), placing KAVACH between any MCP client and its tools |
| `POST /api/v1/check` | Evaluate a raw action and return the decision, scorecard, explanation and receipt |
| `POST /api/v1/session` | Open a session with the user's request and tool outputs (orchestrator tokens only) |
| `POST /api/v1/plan` | Validate a whole plan before its first step |
| `GET`, `POST /api/hitl[/{id}]` | List and resolve human approvals |
| `POST /api/undo/{receipt}` | Restore a snapshot or cancel a hold |
| `POST /api/release/{receipt}` | Release a held action early, recorded as a manual override |
| `GET /api/trace/{correlation}` | The full record of one action |
| `GET /api/receipts/verify` | Verify the hash chain and signed checkpoint |
| `GET /metrics`, `GET /readyz` | Prometheus metrics and readiness |

[`integrations/agentos_hook.py`](integrations/agentos_hook.py) runs KAVACH as Infosys Topaz AgentOS hooks. See [`docs/MCP_PROXY.md`](docs/MCP_PROXY.md) for the MCP proxy and [`docs/DEPLOY.md`](docs/DEPLOY.md) for deployment.

### Configuration

| Variable | Purpose |
|---|---|
| `KAVACH_AUTH_SECRET` | Enables signed-token authentication; user and role then come from the token |
| `KAVACH_DB_URL` | Durable store for receipts, holds, pins and kill-switch state (SQLite or Postgres) |
| `KAVACH_ENV` | Server-set environment; a request cannot override it |
| `KAVACH_MAIL` | `gmail` enables the real mailbox connector and its policy additions |
| `KAVACH_MAIL_HOLD_S` | Length of the email hold window, in seconds |
| `KAVACH_MCP_TOOLS` | Restricts the tools offered over MCP |
| `IMAGINE_API_KEY`, `IMAGINE_API_ENDPOINT` | Qualcomm Cloud AI access (or `INFERENCE_CLOUD_*`) |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Sends decision spans to an OpenTelemetry collector |

## Evaluation

Evidence is reported in separate categories because they support different claims.

### Independent benchmark: AgentDojo

AgentDojo v1.2.2 with the `important_instructions` attack and Llama 3.3 70B on Qualcomm Cloud AI. The tasks and attacks were not written by this team. Results are paired on the tasks both configurations finished, and an escalation is counted as a block.

| Suite | Configuration | Attack success | Utility under attack | Benign utility |
|---|---|---|---|---|
| Banking (144 of 160 tasks) | No guardrail | 65/128 (50.8%) | 53/128 (41.4%) | 8/16 (50.0%) |
| | KAVACH | 0/128 (0.0%) | 62/128 (48.4%) | 8/16 (50.0%) |
| Slack (124 of 126 tasks) | No guardrail | 48/103 (46.6%) | 36/103 (35.0%) | 9/21 (42.9%) |
| | KAVACH | 11/103 (10.7%) | 21/103 (20.4%) | 6/21 (28.6%) |

The Slack result shows a real cost: utility fell, and some attacks still succeeded. Full tables are in [`bench/results/COMPARISON.md`](bench/results/COMPARISON.md).

### Internal synthetic suite

940 labelled scenarios in 47 families; figures are from the held-out test split.

| System | Unsafe auto-allowed | Injection success | Safe actions auto-completed | Escalation rate |
|---|---|---|---|---|
| No guardrail | 100.0% | 100.0% | 100.0% | 0.0% |
| Static denylist | 87.2% | 100.0% | 100.0% | 0.0% |
| Tool-type gating | 38.5% | 25.0% | 47.6% | 57.5% |
| Approve every write | 3.9% | 0.0% | 9.5% | 93.6% |
| **KAVACH** | **0.0%** | **0.0%** | **95.2%** | **25.5%** |

Median decision latency is about 2.2 ms and p95 about 8.6 ms, excluding the optional language-model judge. When the judge runs on an escalated call, that call can take several seconds.

**These figures are prototype results and not a guarantee of production safety.** The same team wrote the suite and the rules, so this table works mainly as a regression check and is not comparable with published benchmarks. Leaving each family out of training gives 0.0% unsafe auto-allowed and 92.1% safe auto-completion ([`LOFO.md`](bench/results/LOFO.md)).

### Further checks

| Check | Result | Report |
|---|---|---|
| Automated red team, with an attacker controlling one email and a fully obedient agent | 1,178 attempts, 0 bypasses | [`REDTEAM.md`](bench/results/REDTEAM.md) |
| Formal properties of the Cedar policies and parity with the Python rules | Proofs and parity results listed | [`CEDAR.md`](bench/results/CEDAR.md) |
| Conformal risk control on the calibration split | Stated finite-sample bound | [`CONFORMAL.md`](bench/results/CONFORMAL.md) |
| Infosys Agentic Foundry guardrails on the same suite | Side-by-side comparison | [`INFOSYS_COMPARISON.md`](bench/results/INFOSYS_COMPARISON.md) |

To reproduce:

```bash
python -m bench.run          # train, calibrate and benchmark over 5 seeds
python -m bench.conformal    # restore calibration rows and write the conformal report
python -m bench.lofo
python -m bench.holdout
python -m bench.redteam fuzz
python -m kavach.policy_verify
```

## Limitations

- KAVACH is a research prototype and has not been deployed in production or independently audited.
- Protection applies only to actions routed through KAVACH. An agent with another route to a tool is outside its control.
- Provenance is inferred by default. A value that a model composes from untrusted text can evade tracing unless planner mode is used.
- Rule R45 matches decision language and can produce false positives. A brief stating that it "is approved for external distribution" is currently refused when copied from an email.
- R44 depends on messages carrying an explicit classification marker, and a paraphrase without copied content may not be detected.
- An email cannot be recalled after delivery. The hold window permits cancellation before delivery only.
- The AgentDojo runs are partial, as shown above, and were recorded before the most recent rule additions.
- Cost figures are estimates based on reference prices.

See [`THREAT_MODEL.md`](THREAT_MODEL.md) for the threat model and [`RELEASE_ACCEPTANCE.md`](RELEASE_ACCEPTANCE.md) for feature-level verification status.

## Repository structure

```
kavach/          Gateway, policy, provenance, consequence analysis, risk model, receipts, connectors, console
  policies/      Policy-as-code and Cedar policies
  manifests/     Typed tool manifests
agent/           Tool-using agent on Qualcomm Cloud AI
bench/           Benchmarks, baselines, red team and generated results
integrations/    Claude Code hook and Infosys Topaz AgentOS hooks
scripts/         Startup, demonstration and verification tooling
deploy/          Prometheus, Grafana, OpenTelemetry and Helm configuration
tests/           Test suite
docs/            Design, research, deployment and operational documentation
deliverables/    Solution deck
```

## Documentation

| Document | Contents |
|---|---|
| [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md) | End-to-end design and research |
| [`THREAT_MODEL.md`](THREAT_MODEL.md) | Assets, adversaries and trust boundaries |
| [`RELEASE_ACCEPTANCE.md`](RELEASE_ACCEPTANCE.md) | What works, how it was verified, and what remains |
| [`docs/INFOSYS_GAP_ANALYSIS.md`](docs/INFOSYS_GAP_ANALYSIS.md) | Comparison with existing Infosys guardrails |
| [`docs/DEPLOY.md`](docs/DEPLOY.md) | Deployment |
| [`DEMO.md`](DEMO.md) | Demonstration guide |

## Acknowledgements

Developed for Infosys ENG NEXT 2026. KAVACH draws on published work including AgentDojo, CaMeL, FIDES, MELON and Conformal Risk Control. References are in [`docs/BLUEPRINT.md`](docs/BLUEPRINT.md).
