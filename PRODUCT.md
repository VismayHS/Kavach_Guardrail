# Product

<!-- impeccable:product-schema 1 -->

Written from the repo and the team's working notes, not from an interview: the team delegated the UI call on 2 Nov 2026. Correct anything here that is wrong.

## Platform

web

## Stack

Delegated: plain HTML, CSS and JavaScript served by the FastAPI server. No build step and no Node, so the console starts with one command and runs offline.

## Users

- **Judges and first-time visitors at the live demo.** They have a few minutes, may never have seen an agent guardrail, and will want to try their own requests and attacks.
- **The team presenting it,** on a laptop or a projector, who need every step to be readable from across a room.
- **The people it is for in real use:** back-office reviewers (an accounts-payable supervisor, a finance manager) who decide what an AI agent may do. They are not security engineers.

## Product Purpose

KAVACH checks what an AI agent is about to do before it happens, and answers four questions: is it safe, is it authorized, can we explain why, and can it be undone? It then lets the action run, runs it with undo ready, asks a person, or blocks it, and writes a tamper-evident receipt.

Success for this console: someone who has never seen KAVACH can type a request, watch what happens, and explain the result to someone else.

## Positioning

KAVACH works out where every value in an action came from (the user, a record, or an email the agent read), reads the facts from the company's own records instead of trusting the agent, and keeps risky actions reversible with holds, recall windows and parked documents.

## Operating Context

The console runs on one server beside a synthetic company (customers, invoices, vendors, a mailbox, a ledger, SAP documents). No real data is involved. Live agent runs use Llama on Qualcomm Cloud AI and take about a minute; they require the operator to supply and load their own Qualcomm API key and endpoint into the server environment. The key is never shipped with the code. Without it, the live-agent control stays disabled; scripted scenarios and the other console screens remain usable. Everything else is designed to work offline.

## Capabilities and Constraints

- A real agent can run any typed request twice, without and with KAVACH, side by side.
- The live-agent screen is gated by server-side Qualcomm credentials. Obtain a key through the Qualcomm account and load it locally using `.env.example`; do not commit or share the populated `.env` file.
- Sixteen scripted scenarios, a raw action check, a human approval queue, undo windows (payment hold, email recall, SAP park), a verifiable receipt chain, benchmark results and the rulebook.
- Terms: **verdicts** are ALLOW, ALLOW_WITH_SAFEGUARD, ESCALATE and DENY in the API; the console says Allowed, Allowed with undo, Needs a person and Blocked.
- AI agents are not deterministic: the same request can go differently, and agents sometimes claim things they did not do. The console shows what really happened.

## Evidence on Hand

Measured results in `bench/results/` (`RESULTS.md`, `LOFO.md`, `HOLDOUT.md`, `JUDGE.md`, `LIVE_AGENT.md`, `AGENTOS_LIVE.md`). The test suite is synthetic and written by the team; it must always be labelled that way and never compared with numbers published on other benchmarks.

## Product Principles

- Show what happened, not what the agent says happened.
- Plain words first, technical evidence one click away.
- Every result says what to do next.
- Never claim more than was measured.

## Accessibility & Inclusion

State must never rely on colour alone. Text must stay readable on a projector. Keyboard use must work everywhere.
