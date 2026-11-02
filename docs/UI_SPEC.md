# KAVACH console: UI spec

Replaces the old one-page dashboard with a proper console in the Exhibit Register design ([DESIGN.md](../DESIGN.md)). Every old function stays. Product facts are in [PRODUCT.md](../PRODUCT.md).

**Stack:** plain HTML, CSS and JavaScript served by the FastAPI server, with no build step. Fonts and icons are local, so it runs with no internet (only the live agent needs the Qualcomm connection).

**Files:** `kavach/static/index.html` (shell, icons), `vx.css` (design system), `app.js` (screens), `fonts/`.

**Run locally:** from the repository root, start `python -m uvicorn kavach.server:app --host 127.0.0.1 --port 8011` and open <http://127.0.0.1:8011>. The port can be changed if it is already in use. The UI is served by this same FastAPI process.

**Live-agent requirement:** the user running the server must supply their own Qualcomm Inference Cloud API key and load it into the server environment. See the repository README's [live-agent setup](../README.md#enable-the-live-agent-you-provide-the-key) and `.env.example`. The key is not included in the repository. Without it, the UI marks Qualcomm AI off and disables **Run both agents**; all scripted scenarios and other console screens remain available.

## Layout

A left rail, a top bar and one page frame on every screen.

| Group | Screen | Address | Old feature it replaces |
|---|---|---|---|
| Try it | **Live agent** (opens first) | `#/agent`, `#/agent/<run>` | Type any request |
| Try it | Scenarios | `#/scenarios`, `#/scenarios/<id>` | Scenario list and run view |
| Try it | Check an action | `#/check` | Raw JSON check |
| Oversight | Approvals | `#/approvals` | Human approvals |
| Oversight | Undo windows | `#/windows` | Undo, fast-forward 1 hour |
| Oversight | Receipts | `#/receipts` | Receipt chain and Verify |
| Evidence | Results | `#/results` | Benchmark panel, status chips |
| Evidence | Rulebook | `#/rules` | New: says what R1 to R24 mean |

The top bar shows the current page, whether Qualcomm is connected, whether the receipt chain checks out, and pending approvals. Below 1024px the rail becomes a drawer.

## Screens

### Live agent

The screen that sells the idea: same agent, same request, with and without KAVACH.

- **Request box:** filled in with the inbox example, so one click shows the attack. Acting-as switch, one primary button "Run both agents", six example chips that fill the box.
- **Two columns:** visible before any run, each with a note saying what will appear there. Each step shows a stamp, the action in plain words, the tool name, its values and the reason. A step's stamp lands when it arrives.
- **When both finish:** one sentence on top saying what left the company each way, with three numbers. Each column ends with the agent's own answer next to what really left the company.
- **Reload:** the run id is in the address, so a reload brings the run back.
- **States:** Qualcomm off (callout that links to Scenarios, Run button off); agent crashed (note in that column, other column carries on); server down (notice). Live runs require the operator to configure their own Qualcomm credentials; the UI cannot enable them by itself.
- **Caveat stays visible:** a step needing a person just doesn't run here, because nobody approves in this view.

### Scenarios

- List of 16 cards in two groups, each with a plain title, one sentence on what it shows, who is acting and the last result (Not run until tried).
- Clicking a card runs it. A reload shows the Run button and never re-runs by itself, since a run resets the demo company.
- Result page: the plan check, then each step. Allowed steps are folded; the step that decided the outcome is open as a full decision card. Then what to do next (Go to approvals, Undo, Undo windows) and the state of the company.

### Decision card (used everywhere)

In reading order: big stamp and action; why, with the rule linked; what it would do; the four questions (Safe, Authorized, Explainable, Reversible) as stamps with evidence; where each value came from; what the agent was told; then folded: risk meter, rules checked, full explanation. Undo button when there is something to take back, and the receipt id with a copy button.

### Check an action

The problem statement's MVP: action in, decision and explanation out. Nothing runs. A form (what the user asked, role, tool, values, what the agent read first) with a switch to raw JSON. Example chips. The decision card sits beside the form on wide screens. Bad JSON shows an inline error, never a pop-up.

### Approvals

One open card at a time: what is being asked, who asked, why, the impact, where values came from, time left. Approver name field, Approve, Deny, and Approve as draft for email. Four-eyes is explained, and the refusal shows inline. After deciding, a notice says what happened and links to Undo windows. Empty note links to the EUR 650,000 scenario.

### Undo windows

Four sections: waiting to go out (live countdown, Cancel), parked in SAP (Discard), saved as drafts, went out. Fast-forward 1 hour button. Items go out by themselves when their window ends while this page is open. Each section has its own empty note.

### Receipts

Register table, newest first: number, time, what happened (stamp), who, hash with copy. Filter pills. View opens the full receipt. Verify the chain gives the Sealed stamp or the Broken stamp with the break point.

### Results

Honest label first: 940 synthetic scenarios written by the team, not comparable with other benchmarks. Three numbers, the safety-versus-friction chart drawn in the design system, systems table, seen / unseen / fresh table, this session's autonomy with the cost basis in a tip, system facts, and the written reports opened in a dialog.

### Rulebook

Every rule in plain words, who can use which tool, the limits and the payment approval tiers, all read from the policy file. Rule links from decision cards land on the highlighted row.

## Copy rules

Short, plain words. Verdicts use the words in DESIGN.md. Phrases the engine writes for engineers are translated on screen ("p(harm) upper bound" disappears, "PII values" becomes "personal details"); the original stays in the full explanation and receipts.

## Done when

- [ ] Every old function still works (flows list above).
- [ ] A first-time visitor can run the inbox attack in one click and read the result without help. (Requires operator-provided Qualcomm credentials.)
- [ ] Every screen has its empty, loading and error states.
- [x] No page scrolls sideways at 390px; wide tables scroll inside their sheet. (Checked in Chromium on all eight routes.)
- [x] No console errors in real Chrome on any screen. (Checked in Chromium on all eight routes.)
- [ ] Works with the internet off, apart from the live agent.
- [ ] Tab key reaches everything, with a visible focus ring.
- [x] `python -m pytest -q` passes, including one test that the page and its files are served. (103 passed on 2 Nov 2026.)

### Browser check (2 Nov 2026)

Checked in installed Google Chrome through Playwright at 1440px desktop and 390px mobile widths. All eight route headings rendered; no browser page errors, console errors, failed requests, or horizontal overflow were observed. The action-check form returned a decision, a read-only scripted scenario completed, and the mobile navigation drawer opened. Qualcomm-dependent live-agent execution was not tested because credentials were not loaded. Keyboard-only coverage and offline operation remain unverified.
