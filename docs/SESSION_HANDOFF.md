# Session handoff: Vismay's work on KAVACH (2–3 Nov 2026)

What was done on `vismay-dev` in the Claude Code sessions of 2–3 Nov (cloud, then the laptop; section 2d), where everything stands, and how to pick
it up. For the whole project (competition, research, design, results), read `docs/HANDOFF.md`. For the rules a
session must follow, read `CLAUDE.md`. This file is the log of *this* work.

---

## 1. Where things stand (3 Nov 2026)

| Branch | Head | What it is |
|---|---|---|
| `main` | `b3c4b1b` | PR #2 merged: `main` (Phase 5 + console UI) + this branch's gap work as of 2 Nov |
| **`vismay-dev`** | see `git log` | `main` + Ashwin's later `build/phase-5` (fast-forward) + Dhanush's `build/e2e-demos` and `build/live-demo` + the fixes in section 2d. **The most complete branch.** |
| `build/phase-5` (Ashwin) | `30eacac` | Contained in `vismay-dev` |
| `build/e2e-demos` (Dhanush) | `c9f531b` | Contained in `vismay-dev` |
| `build/live-demo` (Dhanush) | `0e05100` | Docs only; contained in `vismay-dev` |
| `build/truth-check` (Dhanush) | `0747087` | **Not merged anywhere**: 44 commits stale, conflicts, duplicates Ashwin's callout (section 6) |

- **Tests:** 510 passed, 14 skipped on the laptop, from `requirements-demo.txt` plus Playwright; `tests/ui/console_check.py`
  passes. `preflight.py --demo` says GO, and `demo_rehearse.py` passes on the live stack.
- **Start here to run or present it:** `deliverables/KAVACH_Complete_Guide.pdf` covers the story, the demo script, every
  console screen, the agents, connecting it and the test checklist.
- **Merging `vismay-dev` into `main`:** the team decides, and it needs a new PR, because PR #2 is already merged.
  Pushes go to `vismay-dev` only.

---

## 2. What was built, in order

### 2a. The gap roadmap (Parts 1–5), on `build/phase-4`
The roadmap came from the local VS Code session (artifact "KAVACH gaps roadmap (Vismay)"). That work was never
pushed, so it was rebuilt here from the transcript. Each attack is a test that failed before its fix
(`tests/test_gaps.py`: 39 tests, 64 cases).

| Item | What landed | Rule / file |
|---|---|---|
| **Part 1** | Raw SQL can't change finance records. The SQL sandbox refuses `VACUUM INTO`, `ATTACH`, `PRAGMA`, triggers and file functions (SQLite authorizer, defensive mode, `LIMIT_ATTACHED=0`). The server sets the environment, not the caller. Per-task totals. Bulk or encoded outbound mail. Destinations from untrusted content. Output from unknown tools counts as untrusted. `safeguard_armed` / `outputs_seen` in the check response. Intent matches whole words, and a question never authorises a write. R9 covers writing and deleting credential files. R15 covers SAP amounts. The explainer can't call a blocked action safe. `.env` is ignored. The Infosys comparison uses a fair config. | R35–R38, R9, R15, `kavach/sql.py`, `kavach/intent.py`, `kavach/explain.py` |
| U1 | 24 cases that only meaning can decide. Live: 7 of 12 misreadings with the judge inline, 1 of 12 with keywords (section 2d). | `bench/semantic_eval.py` |
| U2 | Live agent runs saved with full transcripts; rehearsals go to git-ignored `bench/results/rehearsal/` | `agent/llm_agent.py --both --save-log` |
| U3 | What each layer decides: **the risk model changes no verdict** on the suite | `bench/layers.py`, `LAYERS.md` |
| U4 | Evaluation of LLM-written explanations | `bench/explain_eval.py` |
| U5 | Bank details or links from untrusted content need a person, even internally | R39 |
| U6 | No context + outside destination the user didn't give → a person. Orchestrator vs agent tokens, `POST /api/v1/session`. | R40, `kavach/auth.py`, `kavach/server.py` |
| U7 | Characters emailed outside count per task | R36 |
| U8 | The SQL guard holds even with the keyword filter removed | `tests/test_gaps.py` |
| U9 / U11 | Persistence and recalibration. Built, then **replaced** by Phase 5's store (`KAVACH_DB_URL`) and learning loop. | Phase 5's `kavach/store.py`, `kavach/learning.py` |
| U10 | A signed checkpoint catches a receipt log cut short | `kavach/receipts.py`, `kavach/store.py` |
| V2 | Every deck / blueprint / README claim checked, with what to say instead | `docs/CLAIMS_CHECK.md` |

### 2b. Merging Phase 5 into `vismay-dev` (2 Nov), then PR #2
- **Rule numbers:** Phase 5 used R25–R34, so this branch's rules moved from R29–R34 to **R35–R40**.
  - R41 and R42 were added later by Dhanush and Ashwin.
  - New rules start at **R43**.
- **15 conflicting files resolved:**
  - R35–R40 were ported onto Phase 5's effect models, so they also cover manifest tools (Claude Code, MCP, AgentDojo).
  - This branch's `KAVACH_STATE` store and `bench/recalibrate.py` were dropped in favour of Phase 5's.
- **Added on top:**
  - The checkpoint on the Phase 5 store.
  - R36 totals shared across a delegation chain.
  - R9 matching token files by name (the merge had blocked Claude Code reading `src/tokenizer.py`).
  - R36 only for totals split across actions.
  - The Receipts page saying when receipts are missing from the end of the log.
- **Every change to teammates' files, file by file:** `docs/MERGE_NOTES.md`.
- **Results regenerated:** unchanged at 0% unsafe, 95.2% safe auto-completed, 25.5% escalated (5 seeds).
  - Leave one family out: 92.1%.
  - Red-team fuzz: 0 of 1,178.
  - Cedar parity: 1027/1027.

### 2c. Bringing in the teammates' latest work (3 Nov)
- **`build/phase-5`:** fast-forwarded (it already contained `vismay-dev`).
- **`build/e2e-demos` `c9f531b`:** merged.
  - Both teammates had built a poisoned-inbox story for the Live demo page. Both are kept as tabs:
    - *The poisoned inbox* (Ashwin): the leak is refused while the user's own summary goes out.
    - *Without vs with KAVACH* (Dhanush): unguarded replay, then the same calls through KAVACH, then what real Claude did.
  - Checked in the browser: R1 blocks the leak in both, and the summary waits its window.
- **Ashwin's two fixes to this branch's code** (both correct, both kept):
  - **R40:** KAVACH's own "queued" reply no longer counts as something the agent read. Before, one approved email
    let later emails go to made-up addresses.
  - **Checkpoint:** stores older than the checkpoint are adopted instead of reported as tampered with.

### 2d. On the laptop, with the Qualcomm keys (3 Nov)
- **Branch work:** the local 2 Nov work was superseded by 2a, so it's kept only in the laptop's `git stash`. Moved to
  `vismay-dev` and merged Dhanush's `build/live-demo` (docs; one conflict, in `CLAUDE.md`'s branch list).
- **Fixes, one commit each:**
  - **Grafana and Prometheus on Linux:** `scripts/metrics_bridge.py`, started by `demo_up.sh`. Prometheus in Docker
    couldn't reach a KAVACH on 127.0.0.1, so `preflight --demo` said NOT READY. It forwards `GET /metrics` only.
  - **`requirements-demo.txt`:** `requirements.txt` alone can't run the demo; the extras file pulls in torch.
  - **Live agent page:** a malformed tool call showed "The risk score is over the limit". It now says what happened.
  - **Undo windows:** an INR payment was labelled EUR.
  - **`bench/semantic_eval.py`:** "judge on" never consulted the judge, because the default mode only runs on calls
    already going to a person. It now runs inline.
- **Run live for the first time on this branch:** `bench.semantic_eval`, `bench.explain_eval`, the Live agent page, the
  judge's note on approval cards, and real Claude through `/mcp` (stories A, B, C) and through the MCP proxy.
- **Also rerun and passing:** `demo_recovery.py` and its `kill-switch` mode, `alert_drill.py`, `console_check.py`, all 41
  Grafana queries, Jaeger traces, the red-team fuzz (0 of 1,178), Cedar parity (1027/1027), and 19 earlier attacks
  (0 auto-allowed, 18 on the old code).
- **Found, not fixed:** `RESULTS.md` and the Results page say 25.5% escalated, but the current code gives 26.6% on seed 0.
  A later R1 change moved `attack:big_refund` from DENY to ESCALATE. Still 0% unsafe auto-allowed (section 6).

---

## 3. `vismay-dev` vs the `main` of 2 Nov: what it stops

| Attack | Old `main` | Now |
|---|---|---|
| Caller sends `"env": "dev"`, then `DROP TABLE` | runs | DENY (R4); the server sets the env |
| Merely checking `VACUUM INTO '<file>'` / `ATTACH` | database copied to disk | refused, nothing written |
| Raw SQL edits an invoice amount / vendor bank | runs / a person | DENY (R35) |
| 55 one-row deletes; repeated or split payments; split across sub-agents | all run | a person (R36) |
| Customer list base64-encoded, or split into short emails | sent | a person (R36, R37) |
| A fraud email's bank details forwarded internally | sent | a person (R39) |
| A question ("What's the status of 1042?") authorising a write | runs | a person |
| Overwriting or deleting `deploy.env` / keys | runs | DENY (R9) |
| An agent token claiming the user's request | believed | only the orchestrator may state it |
| Newest receipts deleted from the store | unnoticed | chain invalid, `/readyz` fails |

These attacks were written by the same person who wrote the fixes, so a teammate should re-attack the branch (section 6).

---

## 4. Numbers you may quote (and how)

- **Self-graded synthetic suite** (940 scenarios, 47 families, written by us), 5 seeds: 0% unsafe auto-allowed,
  95.2% safe auto-completed, 25.5% escalated. Leave one family out: 92.1%. Always say "our own suite".
- **AgentDojo, live on Qualcomm** (Ashwin, `bench/results/COMPARISON.md`, runs still finishing; ESCALATE counted
  as blocked):
  - Banking, on the tasks both runs finished: attacks succeeded 0 of 40 with KAVACH vs 23 of 40 without. Benign
    tasks: 8 of 16 completed either way.
  - Slack: 6 of 64 vs 26 of 64, but benign tasks fell from 9 of 21 to 6 of 21 with KAVACH. That cost must be stated.
- **Qualcomm judge, inline, live** (`SEMANTIC.md`, one run, 24 hand-written cases, so not a detection rate): misreadings
  caught 7 of 12 vs 1 of 12 with keywords; safe rewordings 11 of 12 both ways; about 4.7 s per check; on 5 of the 24 the
  judge didn't answer in time and fell back to keywords.
- **LLM explanations, live** (`EXPLAIN.md`, 47 decisions): 19 kept, 22 rejected, 6 unavailable. They stay off by default.
- **Latency** without the judge: about 1 ms on a laptop, about 2 / 9 ms (p50 / p95) on the shared build container.
  The Qualcomm judge adds seconds, and only runs on escalated calls.
- **Don't claim:**
  - that the risk model improves safety (`LAYERS.md`: it changes no verdict);
  - that the demo's judge catches misreadings: that result is for inline mode, and the server runs escalations-only;
  - AgentOS beyond "tested through its governance code with a stand-in agent";
  - undo for actions KAVACH didn't execute.

  Full list: `docs/CLAIMS_CHECK.md`.

---

## 5. Decisions and conventions agreed in these sessions

- **Commits carry VismayHS only:** author `VismayHS <vismayhs@gmail.com>`, no `Co-Authored-By` or other trailers.
  - The 41 earlier `vismay-dev` commits were rewritten once to remove trailers (force-push, with permission).
  - Three old commits on `main` (f887939, 958e38a, 096fc97) still carry Claude co-author lines. Every branch is
    built on the first two, so removing them means rewriting all branches: a team decision.
  - GitHub shows these commits as **Unverified**: the cloud container signs with its own key, not one on your
    account. It's cosmetic. A squash-merge on GitHub, or signing on your laptop, gives Verified.
  - A stop hook keeps asking to re-author commits as Claude. That conflicts with the rule above and is declined
    each time.
- **One fix per commit.** Attack test first, full suite passing at every commit.
- **`main` is never pushed to directly.** Team work is brought into `vismay-dev`.
- **Don't duplicate teammates' in-flight work.** This session's Qualcomm retry was dropped when Ashwin did his own.
- **Never commit keys.** A Qualcomm key was pasted into chat on 2 Nov and is in the session history: **rotate it**.

---

## 6. Open items

| Item | Owner | Notes |
|---|---|---|
| **Rotate the Qualcomm key** that was pasted in chat | Vismay | It was never written to a file or commit |
| Decide on `build/truth-check` vs Ashwin's "the agent claims what KAVACH stopped" callout | Dhanush + Ashwin | Then rebase onto `vismay-dev` and merge |
| `ap_agent` may now read the whole customer database (`crm.query`, added for the recorded Claude runs) | Dhanush + Ashwin | Least-privilege regression; Ashwin's demo script kept that role away from customer records |
| Re-attack `vismay-dev` (someone other than the author) | team | V1 |
| Regenerate results: `RESULTS.md` says 25.5% escalated, current code 26.6% (seed 0) | team | `bench.run`, `bench.conformal`, then the docs that quote it; keep REDTEAM's hand-written section |
| Decide whether to offer inline judging | team | 7 of 12 vs 1 of 12, at about 5 s per call; `judge_mode` can only be set in code today |
| Finish the AgentDojo KAVACH runs | Ashwin | Banking 56/160 done at last report |
| Update the deck and blueprint from `docs/CLAIMS_CHECK.md` | docs owner | Still the 29 Oct numbers |
| Per-user totals across tasks (a patient attacker starts a new task each time) | open | Next good change; no network needed |
| Encode R35–R42 in Cedar so the proofs cover them | open | Parity now covers R1–R34 only |
| Save task totals in the store (they reset on restart) | open | Small |
| A new PR `vismay-dev` → `main` | team | PR #2 is already merged |

**Blocked in the cloud container:** it can't reach `aisuite.cirrascale.com` (network policy). Allow that host in
the environment's Network access settings, or run live Qualcomm work on a laptop with the key in `.env`.

**Second Qualcomm key:** `.env` can hold `INFERENCE_CLOUD_API_KEY_2`. Nothing reads it automatically; pass it to long runs
with `INFERENCE_CLOUD_API_KEY="$INFERENCE_CLOUD_API_KEY_2"` after `set -a; . ./.env; set +a`, so they don't compete with the demo.

---

## 7. How to continue

```bash
git fetch origin && git checkout vismay-dev && git pull
pip install -r requirements-demo.txt                    # the demo and the test suite
pip install -r requirements-extra.txt                   # optional: every feature (MCP, AgentDojo, Presidio, torch...)
python -m pytest -q                                      # about 510 passed; the rest skip for optional packages
python tests/ui/console_check.py                         # needs Python Playwright + a Chromium
python -m uvicorn kavach.server:app --port 8000          # console: http://localhost:8000 (Live demo: #/demo)
docker compose up -d mailpit prometheus grafana otel-collector jaeger
scripts/demo_up.sh                                       # the live demo stack (sandbox bank, KAVACH, Qualcomm key from ./.env)
python scripts/preflight.py --demo                       # must say GO; a Qualcomm connect timeout usually clears on a retry
```

After changing rules or the gateway:
1. Run `python -m bench.run`, then `python -m bench.conformal`.
2. Run `bench.lofo`, `bench.holdout`, `bench.layers`, `bench.redteam fuzz` and `kavach.policy_verify`.
3. Commit the model and results together.
4. Restore the hand-written section of `REDTEAM.md` if the fuzz rewrote it.

Where things are:
- `docs/MERGE_NOTES.md`: every change made to teammates' files.
- `docs/CLAIMS_CHECK.md`: what may be claimed.
- `RELEASE_ACCEPTANCE.md`, `DEMO.md`, `THREAT_MODEL.md` (Ashwin): demo readiness, the script, the threat model.
- `docs/LIVE_DEMO.md` (Dhanush): the Live demo page and the Claude comparison.
