# Release acceptance: what works, how we know, what is left

Status words:
- **Verified**: a test or a live run shows it, named here.
- **Verified live**: shown on the running demo stack with real Claude and/or real Mailpit, bank and Prometheus.
- **Partial**: works, with a named gap.
- **Simulated**: stands in for the real thing.
- **Missing**: not done.

All tests: `.venv/bin/python -m pytest -q` (520+ pass). Live stack: `scripts/demo_up.sh`, then
`scripts/preflight.py --demo` (GO) and `scripts/demo_rehearse.py -n 3` (ALL PASSED). Checked 3 Nov 2026 on
`build/phase-5`.

| # | Feature | Where | Status | Acceptance test | Evidence | Left / priority |
|---|---|---|---|---|---|---|
| 1 | Decision path: provenance per value, rules R1–R42, risk model, only rules deny | `kavach/gateway.py`, `policy.py`, `provenance.py` | Verified | `pytest`; 0 verdict changes on 1,027 decisions across this release | `bench/results/RESULTS.md` | - |
| 2 | Real agent able to act only through KAVACH | `scripts/demo_claude.sh`, `integrations/claude_demo/` | Verified live | `preflight.py --demo` (locked flags); stories A–C with real Claude | `DEMO.md` §2, §5 | - |
| 3 | A: legitimate email reaches the inbox once | `/mcp` → hold → SMTP | Verified live | `demo_rehearse.py` (A); `tests/test_mailpit_e2e.py` | `X-Kavach-Correlation` header in Mailpit | - |
| 4 | B: injected instruction blocked before the connector | R1, provenance | Verified live (scripted agent; real Claude resisted on its own) | `demo_rehearse.py` (B); `tests/test_trace.py` | trace shows *Never called* and the untrusted source msg-4471 | Real Claude can't be made to fall for it on demand: shown honestly |
| 5 | C: approval bound to the exact action (task, tool, arguments), used once, expires; a changed call needs its own approval | `Kavach.action_digest`, `resolve_hitl`, `hitl.py` | Verified | `tests/test_approval_binding.py`, `tests/test_r40_status_outputs.py` | digest on the card and receipts | Hook-only mode: binding is the host's job |
| 6 | Invoice: pay only the account on record, for the invoice's amount (R41); approval R18 | `policy.py`, `environment.py` | Verified live | `tests/test_invoice_demo.py`, `tests/test_bank_e2e.py`, `demo_rehearse.py` (C) | bank page: INR 8,000 to TEST-ACCT-001, 0 to TEST-ACCT-999 | - |
| 7 | D: cancel before delivery survives `kill -9`; a crash mid-send is `unknown`, never re-sent | `environment.py` holds, `store.py` | Verified live | `tests/test_email_window.py`; `scripts/demo_recovery.py` | `RECOVERY OK` | - |
| 8 | Send now (manual override, receipted, once) | `Kavach.release_now`, `POST /api/release` | Verified live | `tests/test_release_now.py`; `demo_rehearse.py` | - | - |
| 9 | Kill switch stops new calls and what is waiting, also after a restart | `Kavach.kill`, `_stop_paused` | Verified live | `tests/test_kill_queued.py`; `demo_recovery.py kill-switch` | `PAUSE OK` | - |
| 10 | No record, no action: a store that refuses a receipt fails the call closed | `receipts.py` (durable), `store.py` | Verified (unit) | `tests/test_receipt_store_down.py` | `/readyz` 503, alert KavachReceiptStoreFailing | Not exercised live (needs a disk fault) |
| 11 | Receipt chain: hash, HMAC, Ed25519, signed checkpoint; older stores adopted | `receipts.py`, `store.py`, `signing.py` | Verified | `tests/test_checkpoint.py`, `tests/test_checkpoint_legacy.py`, `tests/test_signed_receipts.py` | console CHAIN OK, `/api/receipts/verify` | External anchoring available, not run in the demo |
| 12 | One correlation id from request to effect; Trace page | `Kavach.trace`, `GET /api/trace/{id}`, console `#/trace` | Verified live | `tests/test_trace.py` | Trace page, Mailpit header | - |
| 13 | Duplicate effects | R36, bank idempotency key, `unknown` never re-sent | Verified | `tests/test_duplicate_effects.py`, `tests/test_bank_e2e.py`, `tests/test_email_window.py` | - | - |
| 14 | Cross-tenant and cross-session isolation | `server.py` `_sees`, sessions keyed by caller | Verified (auth on) | `tests/test_tenancy.py`, `tests/test_gaps.py` | - | The demo runs with auth off (dev profile) |
| 15 | Trusted intent can't come from the agent | orchestrator vs agent tokens | Verified | `tests/test_gaps.py` (agent tokens refused) | - | Auth off in the demo: anyone on localhost can state a request |
| 16 | Unknown tools and changed tool definitions fail closed | R6, R7, MCP proxy pins | Verified | `tests/test_core.py`, `tests/test_mcp_proxy.py` | - | - |
| 17 | Model failure is safe (judge and explainer fall back; decisions never loosen) | `intent.py`, `explain.py` | Verified | `tests/test_phase4.py`, `preflight.py --offline` | - | - |
| 18 | Production profile refuses demo mode, turns off reset and fast-forward | `profile.py` | Verified | `tests/test_prod_profile.py` | - | - |
| 19 | Metrics and Grafana: decisions, effects and outcomes, approvals, holds, sweeper heartbeat, chain, dependencies, end-to-end latency, model usage and cost | `telemetry.py`, `usage.py`, `deploy/grafana` | Verified live | `tests/test_observability.py`, `tests/test_usage.py`; Prometheus scrapes the demo | dashboard *KAVACH: agent action firewall* | - |
| 20 | Alerts | `deploy/alerts.yml` (14 rules) | Partial | promtool: 14 rules OK; `scripts/alert_drill.py` fires KavachDeliveryFailedOrUnknown and KavachDependencyDown | http://127.0.0.1:9090/alerts | Other rules not exercised; delivery to a person (Alertmanager) not set up |
| 21 | Model cost | `kavach/model_prices.json` (versioned) | Partial | `tests/test_usage.py` | `/api/usage` | Qualcomm publishes no per-token price; the 70B rate is a labelled reference, 8B unpriced |
| 22 | Comparison: no guardrail vs spotlighting vs KAVACH | `bench/compare.py` | Partial | `python -m bench.compare` | `bench/results/COMPARISON.md` | Live AgentDojo runs with KAVACH still in progress (paired subset); Slack spotlighting running |
| 23 | Qualcomm judge on escalations (note on the approval card) | `intent.py` two-stage | Verified live | live: R18 escalation carried the judge's note | approval card | - |
| 24 | Payments bank | `scripts/sandbox_bank.py` | Simulated | `tests/test_bank_e2e.py` | bank page | A real bank API is out of scope |
| 25 | Shell actions | `kavach/shell.py` | Simulated (dry-run in Docker) | `tests/test_shell.py` | - | No general containment claim |
| 26 | Planner mode (E9) live on Qualcomm | `kavach/planner.py` | Partial | `tests/test_planner.py` (offline) | - | Live call returned "no JSON" even with the forced answer tool; unresolved |
| 27 | CI, load test (10 sessions × 15 min), backup restore drill | - | Missing | - | - | Out of this release by decision |

## Verdict

**DEMO READY WITH LIMITATIONS** for the documented workflows (email, poisoned inbox, invoice approval, recovery)
on one laptop.

Limitations:
- auth off in the demo profile;
- the bank is simulated;
- live AgentDojo numbers are partial while runs finish;
- alert delivery to a person is not set up;
- no load test and no CI.

It is not production-ready.
