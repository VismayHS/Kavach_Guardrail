"""Compliance evidence pack (F4): for one session, every decision, the rule behind it and the controls it evidences.

GET /api/evidence/{task_id}?format=md|html. The pack shows *evidence that a control operated* (a receipt id per
claim), not a legal opinion that a framework is satisfied: mapping KAVACH's rules to these frameworks is our reading,
cited at the level of articles, sections and functions, and a compliance team should review it.

Frameworks: OWASP Top 10 for Agentic Applications (2026), EU AI Act (Regulation (EU) 2024/1689), NIST AI RMF 1.0,
India's Digital Personal Data Protection Act 2023, and the RBI Master Direction on Digital Payment Security Controls.
"""
from __future__ import annotations

import html
import time

OWASP = {"ASI01": "Agent Goal Hijack", "ASI02": "Tool Misuse and Exploitation", "ASI03": "Identity and Privilege Abuse",
         "ASI04": "Agentic Supply Chain Vulnerabilities", "ASI05": "Unexpected Code Execution",
         "ASI06": "Memory and Context Poisoning", "ASI07": "Insecure Inter-Agent Communication",
         "ASI08": "Cascading Failures", "ASI09": "Human-Agent Trust Exploitation", "ASI10": "Rogue Agents"}
EU = {"Art. 12": "Record-keeping (automatic logging)", "Art. 13": "Transparency to deployers",
      "Art. 14": "Human oversight", "Art. 14(4)(e)": "Ability to interrupt the system (stop)",
      "Art. 15": "Accuracy, robustness and cybersecurity"}
NIST = {"GOVERN": "Policies, accountability", "MAP": "Context and risks identified", "MEASURE": "Risks measured",
        "MANAGE": "Risks treated, incidents handled, systems disengaged when needed"}
DPDP = {"s.8(5)": "Reasonable security safeguards to prevent personal data breach",
        "s.8(6)": "Personal data breach: knowing what happened, to notify"}
RBI = {"DPSC": "Digital payment security controls: limits, authorisation, fraud and transaction monitoring"}

RULE_CONTROLS = {
    "R1": ["ASI01", "ASI02", "Art. 15", "MANAGE"], "R11": ["ASI01", "ASI02", "Art. 15", "MANAGE"],
    "R29": ["ASI01", "ASI06", "Art. 15", "MEASURE"], "R25": ["ASI01", "ASI09", "Art. 15"],
    "R2": ["ASI02", "s.8(5)", "Art. 15"], "R17": ["ASI02", "s.8(5)"], "R13": ["ASI02", "s.8(5)", "Art. 15"],
    "R14": ["ASI01", "ASI02", "s.8(5)", "Art. 14"], "R24": ["ASI02", "s.8(5)"],
    "R6": ["ASI04", "Art. 15", "GOVERN"], "R7": ["ASI02"], "R8": ["ASI03", "GOVERN"],
    "R9": ["ASI03", "Art. 15"], "R32": ["ASI03", "Art. 15"], "R33": ["ASI03", "ASI07"],
    "R3": ["ASI02", "ASI08", "GOVERN"], "R4": ["ASI02", "ASI08"], "R10": ["ASI08", "Art. 14"],
    "R16": ["ASI02", "ASI08"], "R22": ["ASI02", "GOVERN"], "R26": ["ASI02", "ASI08"],
    "R5": ["DPSC", "Art. 14"], "R15": ["DPSC", "ASI02"], "R18": ["DPSC", "Art. 14"], "R19": ["DPSC", "ASI03"],
    "R20": ["DPSC", "ASI01", "ASI09"], "R21": ["DPSC", "GOVERN"], "R23": ["DPSC"], "R30": ["DPSC"], "R31": ["DPSC", "ASI09"],
    "R28": ["ASI01", "ASI10", "s.8(6)", "MEASURE"], "KILL": ["Art. 14(4)(e)", "ASI10", "MANAGE"],
}
ALWAYS = [("Art. 12", "every decision is a hash-chained, signed receipt"),
          ("Art. 13", "every decision carries a plain-language explanation and the evidence behind it"),
          ("GOVERN", "the policy that decided is pinned by its sha256 on each receipt")]


def control_name(c: str) -> str:
    for table, fw in ((OWASP, "OWASP"), (EU, "EU AI Act"), (NIST, "NIST AI RMF"), (DPDP, "DPDP Act 2023"),
                      (RBI, "RBI")):
        if c in table:
            return f"{fw} {c}: {table[c]}"
    return c


def pack(gw, task_id: str) -> dict:
    t = gw.task_summary(task_id)
    recs = [r for r in gw.receipts.items if r["body"].get("task_id") == task_id or
            (r["body"].get("type") in ("kill", "resume") and task_id in (r["body"].get("tasks") or []))]
    decisions, controls = [], {}
    for r in recs:
        d = r["body"].get("decision")
        if not d:
            continue
        fired = [(g["rule_id"], g["outcome"]) for g in d.get("gates", []) if g.get("outcome") != "PASS"]
        decisions.append({"receipt": r["id"], "tool": d["call"]["tool"], "verdict": d["verdict"], "reason": d["reason"],
                          "rules": fired, "explanation": d.get("explanation", "")})
        for rule, _ in fired:
            for c in RULE_CONTROLS.get(rule, []):
                controls.setdefault(c, set()).add(r["id"])
    for c, why in ALWAYS:
        controls.setdefault(c, set()).update(x["receipt"] for x in decisions)
    approvals = [r for r in gw.receipts.items if r["body"].get("type", "").startswith("human-") and
                 r["body"].get("task_id") == task_id]
    if approvals:
        controls.setdefault("Art. 14", set()).update(r["id"] for r in approvals)
    chain = gw.receipts.verify()
    return {"task": t, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S %Z"), "decisions": decisions,
            "approvals": [{"receipt": r["id"], "type": r["body"]["type"], "approver": r["body"].get("approver"),
                           "approvals": r["body"].get("approvals")} for r in approvals],
            "controls": {c: sorted(v) for c, v in sorted(controls.items())},
            "chain": chain, "policy": {"version": gw.policy.version, "sha256": gw.policy.sha256},
            "signing_key": gw.receipts.signer.key_id if gw.receipts.signer else None}


def markdown(p: dict) -> str:
    t = p["task"]
    out = [f"# KAVACH evidence pack: {t['task_id']}", "",
           f"Generated {p['generated_at']}. Request: \"{t['request']}\". Acting: {t['user']} as {t['role']}"
           f"{' (signed in)' if t['authenticated'] else ' (dev mode: identity not verified)'}, tenant {t.get('tenant', 'default') if 'tenant' in t else 'default'}.",
           f"Policy {p['policy']['version']} (sha256 {p['policy']['sha256'][:16]}). Receipt chain: "
           f"{'verified' if p['chain'].get('valid') else 'BROKEN at ' + str(p['chain'].get('broken_at'))}"
           f"{', Ed25519 key ' + p['signing_key'] if p['signing_key'] else ''}.", "",
           "This pack lists evidence that controls operated, with the receipt that proves each one. The mapping to "
           "frameworks is KAVACH's reading, to be reviewed by your compliance team; it is not a legal opinion.", "",
           "## Decisions", "", "| Receipt | Action | Verdict | Rules | Reason |", "|---|---|---|---|---|"]
    out += [f"| {d['receipt']} | {d['tool']} | {d['verdict']} | {', '.join(f'{r}:{o}' for r, o in d['rules']) or '-'} | "
            f"{d['reason'][:140].replace('|', '/')} |" for d in p["decisions"]]
    if p["approvals"]:
        out += ["", "## People who decided", ""]
        out += [f"- {a['receipt']}: {a['type']} by {a['approver']}"
                + (f" ({', '.join(str(x.get('role') or '') + ' ' + str(x.get('approver')) for x in a['approvals'])})"
                   if a.get("approvals") else "") for a in p["approvals"]]
    out += ["", "## Controls evidenced", "", "| Control | Evidence (receipts) |", "|---|---|"]
    out += [f"| {control_name(c)} | {', '.join(v[:8])}{' ...' if len(v) > 8 else ''} |" for c, v in p["controls"].items()]
    r2 = t.get("rule_of_two") or {}
    out += ["", "## Session", "", f"- Rule of Two: {r2.get('legs', 0)} of 3 (untrusted input "
            f"{r2.get('untrusted_input')}, private data {r2.get('private_data')}, outbound {r2.get('outbound_action')})",
            f"- Blocks: {t['denials']} (circuit breaker at {t['circuit_breaker']}); harm spent {t['harm_spent']} of "
            f"{t['harm_budget']}", f"- Flagged sources: {', '.join(t['hostile_sources']) or 'none'}"]
    return "\n".join(out) + "\n"


def html_page(p: dict) -> str:
    """The same pack as a printable page (print to PDF from the browser)."""
    body = []
    for line in markdown(p).splitlines():
        if line.startswith("# "):
            body.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            body.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.startswith("|---"):
            continue
        elif line.startswith("| "):
            cells = [html.escape(c.strip()) for c in line.strip("|").split("|")]
            tag = "th" if not body or not body[-1].startswith("<tr") and not body[-1].startswith("<table") else "td"
            if tag == "th":
                body.append("<table>")
            body.append("<tr>" + "".join(f"<{tag}>{c}</{tag}>" for c in cells) + "</tr>")
        else:
            if body and body[-1].startswith("<tr"):
                body.append("</table>")
            if line.startswith("- "):
                body.append(f"<p>• {html.escape(line[2:])}</p>")
            elif line.strip():
                body.append(f"<p>{html.escape(line)}</p>")
    if body and body[-1].startswith("<tr"):
        body.append("</table>")
    return ("<!doctype html><html><head><meta charset='utf-8'><title>KAVACH evidence pack</title><style>"
            "body{font:14px/1.5 system-ui,sans-serif;max-width:1000px;margin:32px auto;padding:0 16px;color:#1b2333}"
            "table{border-collapse:collapse;width:100%;margin:8px 0 16px}td,th{border:1px solid #ccd;padding:4px 6px;"
            "text-align:left;vertical-align:top;font-size:12.5px}th{background:#f2f4f8}h1{font-size:20px}h2{font-size:16px;"
            "margin-top:24px}</style></head><body>" + "\n".join(body) + "</body></html>")
