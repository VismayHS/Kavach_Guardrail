"""Fill the official Hack-AI-Thon template with KAVACH content + appendix.

    python scripts/build_deck.py   ->  deliverables/KAVACH_Solution_Deck.pptx

Every number on the slides is read from bench/results/*.json, so the deck never
drifts from what the benchmark measured.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.util import Emu, Pt

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "deliverables" / "template_source.pptx"
OUT = ROOT / "deliverables" / "KAVACH_Solution_Deck.pptx"
RES = json.loads((ROOT / "bench" / "results" / "results.json").read_text())
MS = json.loads((ROOT / "bench" / "results" / "multiseed.json").read_text())

INK, BODY, MUTED = "111827", "1F2937", "5B6573"
BLUE, PURPLE, ORANGE, GREEN, RED = "007CC3", "5417A8", "F28C28", "63A845", "D64545"


def pct(x: float, d: int = 0) -> str:
    return f"{x * 100:.{d}f}%"


def ms(name: str, key: str) -> float:
    return MS["systems"][name][key]["mean"]


def rng(name: str, key: str) -> str:
    m = MS["systems"][name][key]
    return f"{pct(m['min'])}–{pct(m['max'])}"


FULL, RULES, APPROVE, TIER, FIXED = ("KAVACH (full)", "KAVACH: rules only", "Approve every write (manual interrupt)",
                                     "Tool-type gating", "KAVACH: fixed threshold")
lat = next(s for s in RES["systems"] if s["system"] == FULL)
N = {
    "full_uar": pct(ms(FULL, "UAR"), 1), "full_auto": pct(ms(FULL, "safe_auto")), "full_asr": pct(ms(FULL, "ASR_injection")),
    "rules_uar": pct(ms(RULES, "UAR")), "approve_auto": pct(ms(APPROVE, "safe_auto")),
    "tier_uar": pct(ms(TIER, "UAR")), "esc": pct(ms(FULL, "escalation_rate")),
    "p50": f"{lat['latency_p50_ms']:.1f}", "p95": f"{lat['latency_p95_ms']:.1f}",
    "ece_raw": f'{RES["calibration"]["ece_uncalibrated"]:.2f}', "ece": f'{RES["calibration"]["ece_calibrated"]:.2f}',
    "n": RES["suite"]["scenarios"], "fam": RES["suite"]["families"], "seeds": len(MS["seeds"]),
}

MARK = re.compile(r"\*\*(.+?)\*\*")


def _runs(text: str):
    pos = 0
    for m in MARK.finditer(text):
        if m.start() > pos:
            yield text[pos:m.start()], False
        yield m.group(1), True
        pos = m.end()
    if pos < len(text):
        yield text[pos:], False


def put(shape, paras, size=None, color=BODY, bold=False, italic=False, space=None):
    """Replace the text of a template shape, keeping its paragraph formatting. '**x**' = bold."""
    tf = shape.text_frame
    if isinstance(paras, str):
        paras = [paras]
    p0 = tf.paragraphs[0]
    tmpl = p0.runs[0].font if p0.runs else None
    tsize = size or (tmpl.size.pt if tmpl is not None and tmpl.size else 12)
    for p in tf.paragraphs[1:]:
        p._p.getparent().remove(p._p)
    for r in list(p0.runs):
        r._r.getparent().remove(r._r)
    for i, text in enumerate(paras):
        p = p0 if i == 0 else tf.add_paragraph()
        if i > 0:
            p._p.insert(0, copy.deepcopy(p0._p.pPr)) if p0._p.pPr is not None else None
        if space is not None:
            p.space_after = Pt(space)
        for seg, b in _runs(text):
            r = p.add_run()
            r.text = seg
            f = r.font
            f.size = Pt(tsize)
            f.bold = bold or b
            f.italic = italic
            f.color.rgb = RGBColor.from_string(color)


def shape(slide, name):
    for sh in slide.shapes:
        if sh.name == name:
            return sh
        if sh.shape_type == 6:
            for g in sh.shapes:
                if g.name == name:
                    return g
    raise KeyError(name)


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def textbox(slide, x, y, w, h, paras, size=11, color=BODY, bold=False):
    tb = slide.shapes.add_textbox(Emu(x), Emu(y), Emu(w), Emu(h))
    tb.text_frame.word_wrap = True
    tb.text_frame.paragraphs[0].text = " "
    tb.text_frame.paragraphs[0].runs[0].font.size = Pt(size)
    put(tb, paras, size=size, color=color, bold=bold)
    return tb


def title(slide, text, sub=None):
    t = textbox(slide, 475488, 256032, 8869680, 420000, text, size=24, color=INK)
    t.text_frame.paragraphs[0].runs[0].font.name = "Aptos Display"
    if sub:
        textbox(slide, 475488, 680000, 9300000, 260000, sub, size=10.5, color=MUTED)


def table(slide, x, y, w, rows, col_w, size=9, header_fill=BLUE, row_h=260000):
    tbl = slide.shapes.add_table(len(rows), len(rows[0]), Emu(x), Emu(y), Emu(w), Emu(row_h * len(rows))).table
    for j, cw in enumerate(col_w):
        tbl.columns[j].width = Emu(cw)
    for i, row in enumerate(rows):
        for j, val in enumerate(row):
            cell = tbl.cell(i, j)
            cell.margin_left = cell.margin_right = Emu(60000)
            cell.margin_top = cell.margin_bottom = Emu(25000)
            cell.text = " "
            put(cell, str(val), size=size, color="FFFFFF" if i == 0 else BODY, bold=(i == 0))
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string(header_fill if i == 0 else ("F5F7FA" if i % 2 else "FFFFFF"))
    return tbl


def build():
    prs = Presentation(TEMPLATE)
    S = prs.slides

    # ---------------------------------------------------------------- 1 title
    s = S[0]
    put(s.shapes[0], ["KAVACH", "Pre-execution action firewall for AI agents",
                      "ET-03 · Agentic AI Guardrail Validator"], size=None)
    tf = s.shapes[0].text_frame
    tf.paragraphs[0].runs[0].font.size = Pt(60)
    tf.paragraphs[1].runs[0].font.size = Pt(26)
    tf.paragraphs[2].runs[0].font.size = Pt(16)
    tf.paragraphs[2].runs[0].font.color.rgb = RGBColor.from_string(BLUE)
    notes(s, "KAVACH (armour), like Indian Railways' Kavach that brakes a train before a collision. "
             "We stop an AI agent's action before it causes damage.")

    # ---------------------------------------------------------------- 2 team
    s = S[1]
    put(shape(s, "Text 19"), "ET-03 · Agentic AI Guardrail Validator (Lane 6, Emerging Technologies)", italic=False)
    put(shape(s, "Text 22"), "Qualcomm Cloud AI Playground (AI Inference Suite) · UNO Q optional", size=11)
    notes(s, "FILL IN: team name, college, city, member names (left as template placeholders).")

    # ---------------------------------------------------------------- 3 problem
    s = S[2]
    put(shape(s, "Text 7"), ["“Check whether an AI agent’s planned action is **safe, authorized, explainable and "
                             "reversible**.” MVP: agent action input → approve/block decision → guardrail explanation."],
        size=13.5)
    put(shape(s, "Text 10"), "Enterprises letting agents act on DBs, email and payments: Infosys delivery teams, "
                             "their BFSI/retail clients, security & audit reviewers, and the customers whose data agents touch.", size=10)
    put(shape(s, "Text 13"), "Agents now act: one bad call deletes, leaks or pays. Gartner: >40% of agentic AI projects "
                             "cancelled by 2027, citing inadequate risk controls. EU AI Act Art. 14 and RBI FREE-AI demand oversight + audit.",
        size=10)
    put(shape(s, "Text 16"), ["Guardrails gate by **tool type or text**, or ask **another LLM**; none measure what this call "
                              "will do. In AmPermBench, **36.8%** of state changes never reached Claude Code’s classifier.",
                              "Manual approval (Tool Interrupt) does not scale, so users pick “always allow”."], size=9.5)
    put(shape(s, "Text 19"), ["**EchoLeak** CVE-2025-32711: zero-click exfiltration via one email.",
                              "**GitHub MCP**: a public issue made an agent leak private repos.",
                              "**Replit**: agent wiped a prod DB during a code freeze, then said rollback was impossible.",
                              "Llama-3.3-70B had the **highest attack success rate (6.49%)** in the UK AISI × Gray Swan red-team challenge."],
        size=9.5)
    put(shape(s, "Text 22"), [f"≤ 1% unsafe actions auto-executed, 0% injection success, ≥ 65% of safe actions run "
                              "without a human, every decision explained with a tamper-evident receipt, < 5 ms decision latency.",
                              f"Measured: **{N['full_uar']}** unsafe auto-allowed, **{N['full_asr']}** injection ASR, "
                              f"**{N['full_auto']}** safe auto-completed, p95 {N['p95']} ms (mean of {N['seeds']} seeds)."], size=10)
    notes(s, "Lead with the incidents, then say the gap in one sentence: every production guardrail asks "
             "'what kind of action is this?'; we ask 'what will this action actually do, where did its arguments come "
             "from, and can it be undone?'")

    # ---------------------------------------------------------------- 4 solution
    s = S[3]
    put(shape(s, "Text 7"), "KAVACH uses deterministic policy, provenance tracking, sandboxed consequence analysis and a "
                            "calibrated risk model to let AI agents act on their own, while blocking or escalating every unsafe action with an auditable receipt.",
        size=12.5)
    put(shape(s, "Text 12"), ["The agent’s **plan** and **each tool call** (MCP tools/call or JSON):",
                              "tool + args, the user’s request, role, environment, and earlier tool outputs (for provenance)."], size=10.5)
    put(shape(s, "Text 18"), ["**Hard gates** R1–R12 (no AI) → **provenance** of every argument → **sandbox diff** / "
                              "typed prediction of the effect → **calibrated p(harm)** with interval vs a **reversibility-conditioned τ**."],
        size=10.5)
    put(shape(s, "Text 24"), ["**ALLOW · ALLOW + UNDO · ESCALATE · DENY**",
                              "4-light scorecard (safe / authorized / explainable / reversible), consequence card for humans, replan hint for the agent, hash-chained receipt."],
        size=10.5)
    k = shape(s, "Text 26")
    put(k, ["KEY VALUE / DIFFERENTIATOR", "  Gate by **measured effect + argument origin**, not by tool type. The LLM never decides. Humans see only the uncertain few."],
        size=8.5, color=ORANGE, bold=False)
    k.text_frame.paragraphs[0].runs[0].font.bold = True
    k.text_frame.paragraphs[1].runs[0].font.size = Pt(11)
    for r in k.text_frame.paragraphs[1].runs:
        r.font.size, r.font.color.rgb = Pt(11), RGBColor.from_string(BODY)
    k.height = Emu(500000)
    put(shape(s, "Text 30"), "PROVEN TODAY", size=9, color=BLUE, bold=True)
    put(shape(s, "Text 31"), [f"Injected exfiltration and payment: **blocked by provenance (R1)**; injection ASR **{N['full_asr']}**.",
                              f"Unsafe auto-allowed **{N['full_uar']}** vs **{N['rules_uar']}** with rules alone; safe actions automated "
                              f"**{N['full_auto']}** vs **{N['approve_auto']}** when every write needs approval.",
                              "Reversible writes run with a snapshot; **Undo** restores state live."], size=10.5)
    notes(s, "User journey: 'Summarise my unread emails.' The inbox hides an instruction to email the customer list to "
             "billing@acme-invoices.co. KAVACH lets the reads through, then denies the send: the recipient traces to msg-4471, "
             "untrusted, rule R1. The agent is told to summarise to the user instead. No LLM was involved in that decision.")

    # ---------------------------------------------------------------- 5 architecture
    s = S[4]
    put(shape(s, "Text 7"), "Any agent (Infosys Foundry, LangGraph, OpenAI-style) with its model on Qualcomm Cloud AI; reviewer on the dashboard; optional UNO Q approval button",
        size=9.5)
    put(shape(s, "Text 11"), "KAVACH gateway (FastAPI, MCP JSON-RPC): manifest pinning, plan check, policy-as-code R1–R12, provenance, HITL queue",
        size=9.5)
    put(shape(s, "Text 15"), "Sandbox diff (SQLite / files) · 18-feature calibrated risk model · reasoning-blind intent judge + explainer (Llama on Qualcomm)",
        size=9.5)
    put(shape(s, "Text 19"), "Verdict + 4-light scorecard · consequence card · undo · replan hint · tamper-evident receipt", size=9.5)
    put(shape(s, "Text 22"), "Python 3.11, FastAPI, SQLite, NumPy + scikit-learn, YAML policy-as-code, SHA-256 + HMAC, Qualcomm Imagine API (OpenAI-format chat/completions), vanilla-JS UI",
        size=9.5)
    put(shape(s, "Text 25"), "Cheap and deterministic first, probabilistic last: ~1 ms gates stop most attacks; the LLM only sees ambiguous calls and can only raise scrutiny. MCP makes it drop-in for Foundry.",
        size=9.5)
    put(shape(s, "Text 28"), f"12 tests; {N['n']} labelled scenarios × {N['seeds']} seeds; post-execution check auto-rolls back; LLM down → heuristic fallback; unknown tool → fail closed.",
        size=9)
    put(shape(s, "Text 31"), "DESIGN DECISION", size=9, color=PURPLE, bold=True)
    put(shape(s, "Text 32"), ["**Authorization is code, not a model.** A model that reads agent-adjacent text can be prompt-injected; a rule that checks where the recipient came from cannot.",
                              f"**Constraint we designed around:** email and payments cannot be sandboxed, so their blast radius is predicted from typed arguments and labelled “predicted”. Decision latency p50 {N['p50']} ms / p95 {N['p95']} ms."],
        size=10.5)
    notes(s, "Walk left to right: agent proposes; KAVACH labels every argument with where it came from; runs the "
             "action on a copy of the database and diffs it; applies the deterministic rules; only then the calibrated "
             "model and, for ambiguous cases, the Qualcomm-hosted judge. Full diagram in the appendix.")

    # ---------------------------------------------------------------- 6 AI
    s = S[5]
    put(shape(s, "Text 7"), "Calibrated risk prediction (ML) + LLM intent judging and explanation, inside an agentic-workflow guardrail", size=12)
    put(shape(s, "Text 10"), "Reversibility-conditioned threshold τ = C/(H(1−r)) on a calibrated p with an abstain band; gating by measured effect", size=10.5)
    put(shape(s, "Text 13"), "Predicts p(action is unsafe or unintended) with a confidence interval; the LLM scores request ↔ action fit and writes the explanation", size=10.5)
    put(shape(s, "Text 16"), "18 typed features (provenance, blast radius, reversibility, intent); bootstrap logistic ensemble + isotonic calibration; Llama on Qualcomm Cloud AI 100", size=10.5)
    put(shape(s, "Text 19"), f"Held-out ECE {N['ece_raw']} → {N['ece']}. Uncertain → human. The LLM can only lower trust; an explanation is rejected if it adds a number not in the evidence.",
        size=10.5)
    put(shape(s, "Text 22"), f"{N['full_auto']} of safe actions automated (vs {N['approve_auto']} approve-every-write) at {N['full_uar']} unsafe auto-allowed; rules alone miss {N['rules_uar']}.",
        size=10.5)
    put(shape(s, "Text 25"), "WHY NOT RULES ONLY", size=9, color=ORANGE, bold=True)
    put(shape(s, "Text 26"), ["“Remove the duplicate for customer 17” becoming “DELETE … WHERE city='Pune' AND tier='gold'” passes every rule. "
                              "The model sees the measured multi-row blast radius and that the record the user named is not even touched.",
                              "**When it is unsure, it asks:** if the interval straddles τ the action goes to a human. No guessing."], size=10.5)
    notes(s, "Be exact: AI appears in three places. (1) A small calibrated statistical model ranks risk. "
             "(2) An optional LLM on Qualcomm checks intent and can only add caution. (3) An LLM writes the explanation from "
             "the evidence. Authorization and provenance are deterministic.")

    # ---------------------------------------------------------------- 7 future
    s = S[6]
    for nm, txt in [("Text 9", "Infosys Foundry plug-in: KAVACH as the MCP endpoint; Tool Interrupt fires only on ESCALATE"),
                    ("Text 12", "Port AgentDojo + AmPermBench; RAI Toolkit Privacy API as the PII detector"),
                    ("Text 15", "UNO Q hardware approval button; NL policy drafting on Qualcomm (human-reviewed)"),
                    ("Text 20", "Stateless decision service, per-tenant policy + model; horizontal scale"),
                    ("Text 23", "Cost-ordered: ~1 ms gates for all; sandbox for writes; LLM only for the ambiguous few"),
                    ("Text 26", "Copy-on-write DB branches, WORM receipt store, calibration-drift monitoring"),
                    ("Text 31", "Tools reachable only via the gateway; RBAC + four-eyes approvals"),
                    ("Text 34", "Secrets never enter agent context; PII masked in receipts; data minimisation"),
                    ("Text 37", "Fail-closed; hash-chained receipts; versioned policy; human override always")]:
        put(shape(s, nm), txt, size=10)
    put(shape(s, "Text 43"), "NOW vs NEXT", size=9, color=GREEN, bold=True)
    put(shape(s, "Text 44"), ["**Works now:** gateway, 12 rules, provenance, SQL/file sandbox, calibrated risk + HITL, receipts, undo, MCP front door, Qualcomm client, benchmark.",
                              "**Next:** Foundry plug-in and published-benchmark ports. **Key safeguard:** an LLM can never turn a DENY into an ALLOW."], size=10)

    # ---------------------------------------------------------------- 8 demo
    s = S[7]
    textbox(s, 2000000, 3500000, 8200000, 1900000,
            ["1  Injected email → agent tries to send 200 customers’ phones → **DENY [R1]**, recipient traced to msg-4471",
             "2  “Mark inactive customers dormant” → sandbox: 16 rows, reversible → **ALLOW + UNDO** → click Undo",
             "3  “Tidy up the CRM” → DELETE without WHERE: 480 rows → **ESCALATE** with consequence card",
             "4  Injected bank details → ₹95,000 transfer → **DENY**;  refund 12,000 → human approval (R5)",
             "5  Tamper with a receipt → chain verification breaks at that record"], size=13)
    notes(s, "Run locally (uvicorn kavach.server:app). Pre-warm the Qualcomm endpoint. Keep the recorded fallback video ready.")

    # ---------------------------------------------------------------- appendix
    blank = prs.slide_layouts[0]

    s = prs.slides.add_slide(blank)
    title(s, "Appendix A · Architecture and data flow", "Stages 1–4 and 7 are deterministic; 6 is a small calibrated model; 5 and 8 may call the Qualcomm-hosted LLM.")
    s.shapes.add_picture(str(ROOT / "docs" / "img" / "architecture.png"), Emu(800000), Emu(1000000), width=Emu(10500000))

    s = prs.slides.add_slide(blank)
    title(s, "Appendix B · Decision logic, confidence, human-in-the-loop")
    s.shapes.add_picture(str(ROOT / "docs" / "img" / "decision_flow.png"), Emu(475488), Emu(800000), width=Emu(11240000))
    textbox(s, 475488, 4720000, 5500000, 1400000,
            ["**Confidence.** 25 bootstrap logistic models, isotonic-calibrated on a held-out split; [p_lo, p_hi] = 10th–90th percentile. "
             "Disagreement widens on unfamiliar actions, which is exactly when the system asks.",
             "**Failure handling.** LLM timeout → heuristic, never relaxation. Unknown tool → fail closed. Actual effect ≠ predicted → auto-rollback."], size=10)
    textbox(s, 6200000, 4720000, 5500000, 1400000,
            ["**Human-in-the-loop.** Only escalated actions reach a reviewer, who sees a consequence card (diff, argument sources, reversibility, rule, p). "
             "Approve · approve-as-draft · deny. Timeout = deny. Four-eyes for irreversible high-harm actions.",
             "Every human decision becomes a labelled example for recalibration."], size=10)

    s = prs.slides.add_slide(blank)
    title(s, "Appendix C · Measured results",
          f"{N['n']} labelled scenarios, {N['fam']} families, {N['seeds']} seeds, held-out test split. Synthetic (AgentDojo / AmPermBench axes); not comparable with published numbers.")
    rows = [["System", "Unsafe auto-allowed ↓", "Injection ASR ↓", "Safe auto-completed ↑", "Escalation"]]
    for name in [n["system"] for n in RES["systems"]]:
        m = MS["systems"][name]
        rows.append([name, f"{pct(m['UAR']['mean'], 1)} ({pct(m['UAR']['min'])}–{pct(m['UAR']['max'])})",
                     pct(m["ASR_injection"]["mean"], 1), f"{pct(m['safe_auto']['mean'], 1)} ({pct(m['safe_auto']['min'])}–{pct(m['safe_auto']['max'])})",
                     pct(m["escalation_rate"]["mean"], 1)])
    table(s, 475488, 1050000, 6300000, rows, [2150000, 1250000, 850000, 1300000, 750000], size=8.5)
    s.shapes.add_picture(str(ROOT / "bench" / "results" / "pareto.png"), Emu(6950000), Emu(1050000), width=Emu(4750000))
    textbox(s, 475488, 4250000, 6300000, 1700000,
            ["**Read it this way.** Rules alone let through ~" + N["rules_uar"] + " of unsafe actions (overeager scoped deletes, wrong recipients, invented amounts). "
             "Approving every write is safe but automates only " + N["approve_auto"] + " of safe work.",
             f"**Honest finding:** on this suite the reversibility-conditioned threshold matches a well-tuned fixed threshold; its value is a cost-unit operating point that adapts strictness per action. "
             f"Calibration ECE {N['ece_raw']} → {N['ece']}; decision latency p50 {N['p50']} ms."], size=9.5)

    s = prs.slides.add_slide(blank)
    title(s, "Appendix D · Today’s guardrails vs KAVACH", "How guardrails work today and where they fall short. Verified against papers, docs and repos (Oct 2026).")
    rows = [["System", "Approach", "Published result / limit"],
            ["Claude Code auto mode", "Tool-tier rules + reasoning-blind 2-stage classifier", "0.4% FPR, 17% FNR (overeager); AmPermBench: 81% FNR, 36.8% of state changes bypass the classifier"],
            ["OpenAI Codex CLI", "Kernel sandbox, network off, approval policies", "Controls where, not what: destructive actions inside the workspace pass"],
            ["AWS AgentCore Policy", "Cedar policies at the tool gateway", "Deterministic authorization; no consequence or provenance"],
            ["NVIDIA NeMo IORails", "Tool-call allowlist + JSON Schema", "Experimental, structural checks only"],
            ["Meta LlamaFirewall", "PromptGuard 2 + AlignmentCheck", "AgentDojo ASR 17.6% → 1.75%, utility 47.7% → 42.7%"],
            ["Google CaMeL", "Control/data-flow separation, capabilities", "77% AgentDojo tasks with provable security vs 84% undefended"],
            ["Progent", "Least-privilege policies", "AgentDojo ASR 41.2% → 2.2%"],
            ["Microsoft Fides Gateway", "MCP proxy, IFC labels, Rego", "Labels + policy; no consequence estimation"],
            ["Cordon (2026)", "Shadow state + effect outbox, validate before commit", "Lineage/authority; no magnitude or calibrated strictness"],
            ["Infosys Agentic AI Foundry", "Tool Interrupt, validators, plan verifier, RBAC", "Manual step-by-step approval; no automated risk triage"],
            ["KAVACH", "Gates + provenance + measured effect + calibrated, reversibility-conditioned risk", "Combines the above at one control point; HITL only when uncertain"]]
    table(s, 475488, 1000000, 11240000, rows, [2100000, 3900000, 5240000], size=8.5, row_h=330000)

    s = prs.slides.add_slide(blank)
    title(s, "Appendix E · How we use the Qualcomm platform", "Contract read from Qualcomm’s python-imagine-sdk 0.5.0 (OpenAI-compatible). Verify the live model list with GET /models on your key.")
    rows = [["Role", "Model / endpoint", "Input → output", "If unavailable"],
            ["Protected agent’s brain", "Llama-3.3-70B (or listed LLM) · POST chat/completions with tools", "user task + tool results → tool calls", "demo uses the scripted agent"],
            ["Reasoning-blind intent judge", "Llama-3.1-8B (SDK default, low latency)", "request + action + provenance → alignment 0–1", "heuristic score; never relaxes"],
            ["Explanation writer", "Llama-3.1-8B", "evidence JSON → 3 plain sentences (number-checked)", "template explanation"],
            ["Future: semantic features", "BAAI/bge-large-en-v1.5 embeddings, bge-reranker-base", "request ↔ action similarity; attack-corpus similarity", "feature omitted"],
            ["Optional edge: Arduino UNO Q", "Dragonwing QRB2210 + STM32U585", "hardware approval button + LED risk display for irreversible actions", "web approval"]]
    table(s, 475488, 1050000, 11240000, rows, [2300000, 3300000, 3500000, 2140000], size=9, row_h=380000)
    textbox(s, 475488, 3700000, 11240000, 1500000,
            ["Auth: Authorization: Bearer $IMAGINE_API_KEY · Base: $IMAGINE_API_ENDPOINT (Cirrascale playground: https://aisuite.cirrascale.com/apis/v2) · "
             "every call has a timeout and a deterministic fallback, so a network failure can never turn into an ALLOW.",
             "Why it matters to Qualcomm: Cloud AI 100 is an inference accelerator. KAVACH spends tokens only on ambiguous calls (cost scales with uncertainty, not traffic), and the open Llama models it hosts are the ones that most need an external guardrail."],
            size=10)

    s = prs.slides.add_slide(blank)
    title(s, "Appendix F · References")
    textbox(s, 475488, 900000, 11240000, 5000000, [
        "AgentDojo, NeurIPS 2024 D&B (arXiv 2406.13352) · CaMeL, arXiv 2503.18813 · LlamaFirewall, arXiv 2505.03574 · Progent, arXiv 2504.11703",
        "Design Patterns for Securing LLM Agents against Prompt Injections, arXiv 2506.08837 · Cordon, arXiv 2606.17573 · Revisable by Design, arXiv 2604.23283",
        "Measuring the Permission Gate (AmPermBench), arXiv 2604.04978 · Anthropic, Claude Code auto mode (engineering post) · GoEx, arXiv 2404.06921 · ToolEmu, ICLR 2024",
        "KnowNo: Robots That Ask For Help, CoRL 2023 (arXiv 2307.01928) · OWASP Top 10 for Agentic Applications (Dec 2025) · UK AISI × Gray Swan Agent Red-Teaming results (2025)",
        "Gartner press release 25 Jun 2025 · EchoLeak CVE-2025-32711 · Invariant Labs: GitHub MCP exploit (May 2025), MCP tool poisoning (Apr 2025) · Replit incident (Jul 2025)",
        "Simon Willison, The lethal trifecta (Jun 2025) · NVIDIA NeMo Guardrails tool-calling docs · AWS Bedrock AgentCore Policy docs · microsoft/fides-gateway",
        "Infosys Agentic AI Foundry (v1.6–1.9 release notes) · Infosys Responsible AI Toolkit · Qualcomm python-imagine-sdk 0.5.0",
        "EU AI Act Art. 14 · RBI FREE-AI framework (Aug 2025) · MeitY India AI Governance Guidelines (Nov 2025)",
        "Code, benchmark and full blueprint: github.com/VismayHS/Kavach_Guardrail"], size=10.5)

    OUT.parent.mkdir(exist_ok=True)
    prs.save(OUT)
    print("saved", OUT)


if __name__ == "__main__":
    build()
