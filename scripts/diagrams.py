"""Render architecture + decision-flow diagrams used in the deck and blueprint."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch

INK, MUTED, BLUE, PURPLE, ORANGE, GREEN, RED = "#111827", "#5B6573", "#007CC3", "#5417A8", "#F28C28", "#63A845", "#D64545"


def box(ax, x, y, w, h, title, body, col, fill="#ffffff", tsize=9.5, bsize=7.6):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.008,rounding_size=0.012",
                                fc=fill, ec=col, lw=1.6))
    ax.text(x + 0.012, y + h - 0.022, title, fontsize=tsize, fontweight="bold", color=col, va="top")
    ax.text(x + 0.012, y + h - 0.062, body, fontsize=bsize, color=INK, va="top", linespacing=1.35)


def arrow(ax, x1, y1, x2, y2, col=MUTED, label=None, style="-|>"):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=11, color=col, lw=1.3))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2 + 0.012, label, fontsize=6.8, color=col, ha="center")


def architecture(path):
    fig = plt.figure(figsize=(13.33, 5.9), dpi=170)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    box(ax, 0.012, 0.56, 0.155, 0.37, "AGENT", "Infosys Foundry / LangGraph /\nOpenAI-style agent; model\non Qualcomm Cloud AI\n\nsends plan + each tool call\n(MCP tools/call or REST):\ntool, args, user request,\nrole, env, prior outputs", BLUE, "#EAF5FC")
    box(ax, 0.012, 0.385, 0.155, 0.135, "ALLOW / ALLOW+UNDO", "real tool runs; snapshot first;\npost-check vs prediction", GREEN, "#F1F8EC", bsize=7.2)
    box(ax, 0.012, 0.215, 0.155, 0.135, "ESCALATE  (human)", "consequence card; approve /\ndraft / deny; timeout = deny", ORANGE, "#FEF5EC", bsize=7.2)
    box(ax, 0.012, 0.045, 0.155, 0.135, "DENY", "rule id + replan hint\nreturned to the agent", RED, "#FDEEEE", bsize=7.2)
    gx, gw = 0.19, 0.80
    ax.add_patch(FancyBboxPatch((gx, 0.03), gw, 0.92, boxstyle="round,pad=0.004,rounding_size=0.015",
                                fc="#F6F4FB", ec=PURPLE, lw=2))
    ax.text(gx + 0.012, 0.93, "KAVACH GATEWAY: reference monitor, every call passes here before any real tool runs",
            fontsize=10.5, fontweight="bold", color=PURPLE, va="top")
    gap, W, H = 0.034, (gw - 0.04 - 3 * 0.034) / 4, 0.36
    xs = [gx + 0.02 + i * (W + gap) for i in range(4)]
    top = [("1  INGEST + PLAN CHECK", "tool manifest (hash-pinned,\nunknown = fail-closed);\nwhole-plan scan: lethal-\ntrifecta path, unrequested\nstate changes, RBAC", PURPLE),
           ("2  PROVENANCE", "label every argument:\ntrust user / derived / untrusted,\nconfidentiality, PII count\n(value lineage from the request\nand every tool output)", PURPLE),
           ("3  CONSEQUENCE", "sandbox diff (SQL, files) |\nstatic | typed prediction\n(email, payments) -> blast\nradius, harm H, reversibility\nclass r, safeguard", ORANGE),
           ("4  HARD GATES (no AI)", "policy-as-code R1-R12: RBAC,\nuntrusted destination, PII out,\nfreeze, DDL, limits, secrets,\nrug pull, workspace\nDENY is final", RED)]
    for x, (t, b, c) in zip(xs, top):
        box(ax, x, 0.51, W, H, t, b, c)
    for i in range(3):
        arrow(ax, xs[i] + W + 0.003, 0.69, xs[i + 1] - 0.003, 0.69, MUTED)
    bot = [("8  EXPLAIN + RECEIPT", "template from evidence;\nQualcomm LLM rewrite only if\nevery number is in evidence;\nSHA-256 chain + HMAC receipt", GREEN),
           ("7  DECIDE", "DENY | ESCALATE |\nALLOW + UNDO | ALLOW\n+ task harm budget\n+ circuit breaker", GREEN),
           ("6  RISK (ML)", "18 features -> bootstrap\nlogistic ensemble + isotonic\n-> p and [p_lo, p_hi]\ntau = min(.5, C/(H(1-r)))", ORANGE),
           ("5  INTENT (AI, optional)", "reasoning-blind: request <->\naction only; Qualcomm LLM\nonly when ambiguous; can\nonly RAISE scrutiny", ORANGE)]
    for x, (t, b, c) in zip(xs, bot):
        box(ax, x, 0.07, W, H, t, b, c)
    for i in range(3, 0, -1):
        arrow(ax, xs[i] - 0.003, 0.25, xs[i - 1] + W + 0.003, 0.25, MUTED)
    arrow(ax, xs[3] + W / 2, 0.51, xs[3] + W / 2, 0.43, MUTED)
    arrow(ax, 0.167, 0.80, xs[0] - 0.003, 0.80, BLUE)
    for y, c in ((0.45, GREEN), (0.28, ORANGE), (0.11, RED)):
        arrow(ax, xs[0] - 0.006, 0.22, 0.169, y, c)
    fig.savefig(path, facecolor="white")


def decision(path):
    fig = plt.figure(figsize=(13.33, 4.6), dpi=170)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
    steps = [("Any gate DENY?", "-> DENY", RED), ("Policy floor\n(approval rule)?", "-> ESCALATE", ORANGE),
             ("State change the\nuser never asked?", "-> ESCALATE", ORANGE), ("Task harm budget\nexceeded?", "-> ESCALATE", ORANGE),
             ("p_hi < tau ?", "-> ALLOW\n(+undo if reversible)", GREEN), ("p_lo >= tau\nand p >= 0.5 ?", "-> ESCALATE\n(flagged likely unsafe)", ORANGE),
             ("otherwise\n(interval straddles tau)", "-> ESCALATE", ORANGE)]
    w = 0.121
    for i, (q, a, c) in enumerate(steps):
        x = 0.012 + i * (w + 0.021)
        ax.add_patch(FancyBboxPatch((x, 0.52), w, 0.3, boxstyle="round,pad=0.006,rounding_size=0.02", fc="#fff", ec=MUTED, lw=1.2))
        ax.text(x + w / 2, 0.67, q, ha="center", va="center", fontsize=9, color=INK)
        ax.add_patch(FancyBboxPatch((x, 0.25), w, 0.17, boxstyle="round,pad=0.006,rounding_size=0.02", fc=c, ec=c))
        ax.text(x + w / 2, 0.335, a, ha="center", va="center", fontsize=8.6, color="white", fontweight="bold")
        arrow(ax, x + w / 2, 0.52, x + w / 2, 0.42, c, "yes")
        if i < len(steps) - 1:
            arrow(ax, x + w + 0.004, 0.67, x + w + 0.017, 0.67, MUTED)
    ax.text(0.01, 0.95, "Decision procedure (first match wins; only deterministic rules can DENY).  tau = min(0.5, C_block / (H x (1 - r)))   "
            "EUH = p x H x (1 - r)", fontsize=11, fontweight="bold", color=INK, va="top")
    ax.text(0.012, 0.17, "r: idempotent 1.0 · reversible 0.95 (verified snapshot) · compensable 0.5 · irreversible 0.   "
            "H: measured blast radius in the sandbox, or predicted from typed arguments.\n"
            "C_block: the organisation's cost of blocking a good action (harm units), chosen on the calibration split.",
            fontsize=8.6, color=MUTED, va="top", linespacing=1.5)
    fig.savefig(path, facecolor="white")


if __name__ == "__main__":
    architecture("docs/img/architecture.png")
    decision("docs/img/decision_flow.png")
    print("ok")
