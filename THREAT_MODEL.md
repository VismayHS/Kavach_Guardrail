# KAVACH threat model (short)

KAVACH decides, before execution, whether an action an AI agent proposes becomes a real effect. The adversary
controls content the agent reads (emails, invoices, web pages, tool output) and may control the agent's choices
through it. The model is never trusted to decide.

## Inputs: who is trusted for what

| Input | Trust | Why / how it is enforced |
|---|---|---|
| The user's request | Trusted for intent and for values they typed | Comes from the orchestrator or hook, not the agent. With auth on, only an orchestrator token may state it (agent tokens can't). |
| Records (vendor master, CRM, invoices) | Trusted as data; private | Payment facts come from records, never from the agent's text (R41 pays the account on record only). |
| Tool output from outside (inbox, web, documents, MCP tool descriptions) | **Untrusted** | Labelled per value. An untrusted value in a control argument (recipient, account, URL) is refused (R1) or goes to a person. |
| The agent's arguments | Untrusted until traced | Each value's source is looked up; a destination the user didn't give needs a person (R38/R40). |
| Tool definitions | Pinned | A changed definition (rug pull) is denied until a person re-approves it (R6). Unknown tools fail closed. |
| The Qualcomm judge and explainer | Advisory | They can only add strictness or text; a failure falls back to deterministic rules. Only rules deny. |
| Approvers | Trusted humans with roles | Role from the signed token when auth is on. Four-eyes and quorum for irreversible high-value actions. |

## Credentials and what the agent can reach

- Connector credentials (SMTP, bank URL, Qualcomm key) are in KAVACH's process environment.
  `{{secret:NAME}}` placeholders resolve only at execution and are never shown to the agent.
- In the live demo, Claude Code runs with every built-in tool off (`--tools ""`), no browser (`--no-chrome`) and no
  other MCP server (`--strict-mcp-config`). KAVACH's `/mcp` is its only way to act. It has no shell or file access,
  so it can't read any environment variable or reach Mailpit's SMTP port. `preflight.py --demo` checks those flags.

## What gateway mode guarantees (KAVACH executes: `/mcp`, the API with execute, the MCP proxy)

- **No effect without a decision**, and no decision without a durable receipt. If the store refuses a decision or
  approval receipt, the call does not run (`tests/test_receipt_store_down.py`).
- **Deny is final.** Only deterministic rules deny, and no approval can override a deny (R41 leaves nothing to approve).
- **Approvals are bound** to task, tool and exact arguments by a digest. They are used once, expire (no answer
  means no), and a changed call needs its own approval (`tests/test_approval_binding.py`).
- **Cancel before delivery.** Email and payments wait in a window. Cancel and send can't both win. State survives
  `kill -9`. A crash mid-send ends as `unknown` and is never re-sent; a refused send ends as `failed`, never `sent`
  (`tests/test_email_window.py`, `scripts/demo_recovery.py`).
- **The kill switch** denies new calls and cancels what is waiting, also after a restart, and checks again before
  any window closes (`tests/test_kill_queued.py`).
- **Every action is traceable** by one correlation id, from request to effect (`tests/test_trace.py`).

## What hook-only mode cannot guarantee (AgentOS hook, Claude Code PreToolUse hook)

KAVACH advises and the host enforces. A tool the hook doesn't see is invisible. KAVACH holds no undo window for
an action it doesn't execute. An approval means the host calls again, and binding that call to the approved one is
the host's job. Use gateway mode where it matters.

## Trust anchor of the receipts

Receipts are SHA-256 chained, HMAC'd (`KAVACH_RECEIPT_KEY`) and Ed25519-signed (`KAVACH_SIGNING_KEY`). A signed
checkpoint (count + head) kept apart from the database catches truncation. Someone who controls the database, the
checkpoint file *and* the keys can rewrite history. Anchor the head outside (`POST /api/receipts/anchor`) and keep
keys out of the database host.

## Demo profile vs production profile

The demo runs `dev`: auth off on 127.0.0.1, so anyone on the machine can call `/mcp`, approve, reset or fast-forward.
`KAVACH_PROFILE=prod` refuses to start without `KAVACH_AUTH_SECRET`, `KAVACH_RECEIPT_KEY` and `KAVACH_SIGNING_KEY`,
and turns off reset, fast-forward and the demo endpoints. Approvals, kill, release and the receipt export then
need a signed token with the right role.

## Out of scope and known limits

- **What the agent tells the user.** A misleading summary that never becomes a tool call is out of scope. KAVACH
  sees actions, not prose. The console flags agent replies that claim a blocked action ran.
- **Invented addresses.** An outside address the agent makes up, in a task that read only trusted data, is allowed.
  It is held in its window and can be cancelled. R38 and R40 ask a person once untrusted content was read, or when
  nothing was shown.
- **Shell execution.** Commands are judged, and dry-run only in a Docker sandbox. KAVACH makes no general shell
  containment claim.
- **Not done in this release:** load, DoS and multi-tenant hosting hardening; supply chain of dependencies; alert
  delivery to people (Alertmanager).
- **The demo's company is simulated**, and the bank is a sandbox. Mailpit is a real SMTP server that catches mail
  locally.
