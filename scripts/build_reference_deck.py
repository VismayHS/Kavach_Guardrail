"""Build the editable solution deck and its date-free explanation from repository evidence.

Run with .venv/bin/python scripts/build_reference_deck.py. Saved benchmark runs are reported;
this script never calls a model or reruns a live integration. The original deck is
preserved in deliverables/before_update/. Export the PPTX with LibreOffice for PDF.
"""
from __future__ import annotations

import json
import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

import deck_compare as dc

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'deliverables'
RESULTS = ROOT / 'bench/results'

def read(name):
    return json.loads((RESULTS / f'{name}.json').read_text())

RES, MS, COMP, IC = [read(n) for n in ['results', 'multiseed', 'comparison', 'infosys_compare']]
SEM, EXP = read('semantic'), read('explain')
VALIDATION = json.loads((OUT / 'review/validation.json').read_text())
FULL = 'KAVACH (full)'
PAPER, WHITE, INK, MUTED = 'F4F5F2', 'FFFFFF', '1C2433', '5C6474'
BLUE, VIOLET, GREEN, RED, AMBER = '007CC3', '5B3FA8', '1F6B45', 'B42318', '8A5A00'
RULE = 'D8DBD3'
FONT = 'Noto Sans'
SLIDES = []

def pc(x): return f'{100*x:.1f}%'
def mean(system, metric): return MS['systems'][system][metric]['mean']
def rgb(c): return RGBColor.from_string(c)

def rect(s, x, y, w, h, fill=WHITE, line=None, radius=False):
    sh = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
                            Inches(x), Inches(y), Inches(w), Inches(h))
    sh.fill.solid(); sh.fill.fore_color.rgb = rgb(fill)
    sh.line.fill.background() if line is None else None
    if line: sh.line.color.rgb = rgb(line)
    if radius:
        sh.adjustments[0] = .08
    return sh

def text(s, x, y, w, h, content, size=19, color=INK, bold=False, align=None):
    sh = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = sh.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = Inches(.015)
    tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.TOP
    lines = content if isinstance(content, list) else [content]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.font.name = FONT; p.font.size = Pt(size); p.font.bold = bold; p.font.color.rgb = rgb(color)
        p.space_after = Pt(10); p.line_spacing = 1.12
        if align is not None: p.alignment = align
    return sh

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333333), Inches(7.5)


def slide(title, sub, sources, talk, change, section='SOLUTION'):
    s = prs.slides.add_slide(prs.slide_layouts[6])
    s.background.fill.solid(); s.background.fill.fore_color.rgb = rgb(PAPER)
    rect(s, .48, .38, .08, .22, VIOLET)
    text(s, .69, .34, 10.8, .28, f'KAVACH  /  {section}', 10.5, VIOLET, True)
    text(s, .65, .9, 12.05, .65, title, 30, INK, True)
    text(s, .65, 1.64, 12.0, .6, sub, 15, MUTED)
    rect(s, .65, 6.86, 12.02, .012, RULE)
    text(s, .65, 7.02, 11.55, .25, 'EVIDENCE  ' + sources, 9, MUTED)
    text(s, 12.02, 6.99, .65, .3, f'{len(prs.slides):02}', 11, VIOLET, True, PP_ALIGN.RIGHT)
    s.notes_slide.notes_text_frame.text = talk + '\n\nEvidence: ' + sources
    SLIDES.append({'number': len(prs.slides), 'title': title, 'subtitle': sub,
                   'sources': sources, 'explanation': talk, 'change': change, 'content': []})
    return s


def cards(s, items, y=2.42, h=3.65):
    n = len(items); gap = .22; w = (12.02-gap*(n-1))/n
    for i, (label, body, accent) in enumerate(items):
        x = .65+i*(w+gap)
        rect(s, x, y, w, h, WHITE, RULE, True)
        rect(s, x, y, w, .06, accent)
        if h < 2:
            text(s, x+.18, y+.13, w-.36, .32, label, 16, accent, True)
            text(s, x+.18, y+.55, w-.36, h-.58, body, 14)
        else:
            text(s, x+.22, y+.26, w-.44, .7, label, 21 if n<4 else 18, accent, True)
            text(s, x+.22, y+1.13, w-.44, h-1.25, body, 18 if n<4 else 16)


def band(s, content, y=6.28, color=VIOLET):
    rect(s, .65, y, 12.02, .42, 'EFEBF8' if color==VIOLET else WHITE)
    text(s, .82, y+.07, 11.7, .32, content, 13.3, color, True)


def table(s, headers, rows, widths, y=2.42, row_h=.58, size=16):
    total=sum(widths)
    t=s.shapes.add_table(len(rows)+1,len(headers),Inches(.65),Inches(y),Inches(total),Inches(row_h*(len(rows)+1))).table
    for j,w in enumerate(widths): t.columns[j].width=Inches(w)
    for i,row in enumerate([headers]+rows):
        for j,val in enumerate(row):
            c=t.cell(i,j);c.text=str(val)
            c.fill.solid();c.fill.fore_color.rgb=rgb(INK if i==0 else WHITE if i%2 else 'EBEDE8')
            c.margin_left=c.margin_right=Inches(.13);c.margin_top=Inches(.12);c.margin_bottom=Inches(.06)
            c.vertical_anchor=MSO_ANCHOR.MIDDLE
            for p in c.text_frame.paragraphs:
                p.font.name=FONT;p.font.size=Pt(size);p.font.bold=(i==0);p.font.color.rgb=rgb(WHITE if i==0 else INK)
    return t


def flow(s, items, y=2.5, h=2.5):
    n=len(items);w=(12.02-.36*(n-1))/n
    for i,(label,body) in enumerate(items):
        x=.65+i*(w+.36)
        rect(s,x,y,w,h,WHITE,RULE,True)
        text(s,x+.16,y+.22,w-.32,.65,label,19,VIOLET,True)
        text(s,x+.16,y+1.02,w-.32,h-1.1,body,16)
        if i<n-1:text(s,x+w+.05,y+h/2-.2,.28,.45,'›',26,VIOLET,True)


def build():
    passed=VALIDATION['tests']['passed']; skipped=VALIDATION['tests']['skipped']
    # The first eight slides retain the original submission's subject sequence.
    s=slide('KAVACH', 'Pre-execution action firewall for AI agents',
        'README.md; kavach/gateway.py; THREAT_MODEL.md',
        'KAVACH sits between an agent and the tools that change the world. It traces argument origins, estimates or stages consequences, applies policy, and records the decision before a permitted call runs. It can allow, allow with a real safeguard, ask a person, or deny. The demo company and bank are synthetic; SMTP delivery can be real. The main presentation is slides 1–8; the remaining slides provide technical and evaluation evidence.',
        'Rebuilt the cover and visual system; removed embedded calendar labels and presentation timing prompts.')
    text(s,.73,2.65,10.8,1.45,'Before an agent acts,\nmake the consequence visible.',36,INK,True)
    text(s,.76,4.47,11.5,.65,'SAFE  /  AUTHORIZED  /  EXPLAINABLE  /  REVERSIBLE',18,VIOLET,True)
    rect(s,.76,5.55,11.8,.61,INK)
    text(s,.97,5.7,11.4,.35,'ET-03 · Agentic AI Guardrail Validator · Qualcomm Cloud AI',17,WHITE,True)

    s=slide('Project context & delivery scope','A working guardrail, an operator console, and evidence for each claim.',
        'README.md; PRODUCT.md; RELEASE_ACCEPTANCE.md; integrations/',
        'The project addresses ET-03 for enterprises that let agents use CRM, files, email and finance tools. Operators are business reviewers, while integration owners enforce the tool boundary and auditors inspect receipts. The repository includes the gateway, console, simulated business environment, connector demos, tests and evaluation scripts.',
        'Replaced unfilled team and college placeholders with verified project scope and user responsibilities.')
    cards(s,[('Who uses it',['Agent owners integrate tools.','AP and finance reviewers approve exceptions.','Auditors inspect decision evidence.'],BLUE),
             ('What is delivered',['FastAPI gateway + web console','MCP proxy + SDK adapters','Demo services + evaluation harness'],VIOLET),
             ('Where it fits',['Infosys agent workflows','Email, CRM, files and payments','Qualcomm-hosted agent and advisory judge'],GREEN)])
    band(s,'Submission focus: action input → decision → explanation, with enforceable execution controls.')

    s=slide('Problem Statement','An agent can turn untrusted content into an unauthorized real-world action.',
        'THREAT_MODEL.md; tests/test_trace.py; tests/test_invoice_demo.py',
        'A legitimate request such as summarising an inbox can expose the agent to instructions planted in an email. The same failure occurs when an invoice email substitutes a bank account, or a narrow CRM request becomes a broad write. KAVACH evaluates each proposed call with the actual request, source labels and business facts. Success requires showing the connector outcome, not trusting the agent’s final message.',
        'Removed dated incidents, market forecasts, compliance assertions and blanket competitor claims; replaced them with repository-tested failure cases.')
    cards(s,[('01  Data leaves',['User asks for a summary.','An email asks for the customer list.','The agent proposes an external send.'],RED),
             ('02  Money redirects',['Invoice names a vendor.','A message supplies new bank details.','The agent proposes the wrong account.'],AMBER),
             ('03  Scope expands',['User names one record.','The agent writes many rows or a sensitive field.','A tool allowlist cannot explain the impact.'],BLUE)])
    band(s,'Success = the right task completes, unauthorized calls stop, and the receipt explains the actual outcome.')

    s=slide('Proposed Solution','Check intent, authority, argument origin and impact at the tool boundary.',
        'kavach/gateway.py; policy.py; bench/results/multiseed.json',
        'The input includes a tool name, arguments, trusted request, caller identity and prior outputs. Provenance labels the arguments; consequence analysis stages SQL and file changes or predicts external effects. Policy rules impose denial or human approval. The intent gate and risk signal can add caution. Every decision has an explanation and receipt; safeguarded local execution is separate from merely approving an externally executed call.',
        'Expanded the policy rules, corrected the processing order, and removed the promise to catch every unsafe action.')
    flow(s,[('INPUT','Trusted request\nTool + arguments\nIdentity + prior outputs'),('CHECK','Provenance + impact\nPolicy rules\nIntent + risk signal'),('DECIDE','Allow\nAllow with safeguard\nEscalate / deny'),('PROVE','Receipt + source trail\nConnector outcome\nUndo status')],h=3.15)
    band(s,f"Own synthetic suite: {pc(mean(FULL,'safe_auto'))} safe auto-completion; {pc(mean(FULL,'UAR'))} unsafe auto-allowed (five-seed mean).")

    s=slide('Architecture & Technical Design','One decision engine; execution guarantees depend on the integration path.',
        'kavach/server.py; gateway.py; environment.py; mcp_proxy/proxy.py; store.py',
        'The agent or orchestrator enters through REST, the demo MCP endpoint, a full MCP proxy or framework hooks. The gateway combines manifest, provenance, consequence, policy, intent and risk. In owned execution it calls the environment and connectors with snapshots or delivery windows. In proxy and hook mode the external host executes, so KAVACH does not claim its own undo. Receipts, persistence and telemetry surround both paths. This is a stateful single-writer reference deployment, not a verified horizontally scalable service.',
        'Replaced the prototype architecture and stale diagram with editable component flow; added the owned-execution versus external-execution boundary.')
    s.shapes.add_picture(str(ROOT/'docs/diagrams/architecture.png'),Inches(.65),Inches(2.2),width=Inches(12.02))
    band(s,'Python · FastAPI · vanilla JavaScript · YAML policy · NumPy / scikit-learn · optional MCP and crypto extras')

    s=slide('AI Usage & Innovation','AI assists semantic review; deterministic controls carry the safety boundary.',
        'kavach/gateway.py; intent.py; explain.py; bench/results/layers.json; semantic.json',
        'The calibrated risk ensemble supplies an additional score and uncertainty interval. On the saved synthetic suite, forcing model risk to zero changes no verdict: rules and the intent gate determine the outcomes. The server defaults to a Qualcomm judge only on escalations, where it writes a reviewer note without changing that verdict. An explicit inline evaluation caught seven of twelve semantic misreadings versus one with the heuristic, with eleven of twelve safe rewordings completed in either case. Templates are the default explanation; optional LLM rewrites must pass number and verdict checks.',
        'Removed the threshold novelty and calibration headline; corrected model importance, judge default and the optional explanation path.')
    cards(s,[('Deterministic core',['Argument origin + business facts','Policy cannot be relaxed by AI.','Unknown or changed tools fail closed.'],BLUE),
             ('Qualcomm assistance',['Default: note on escalations','Live inline test: 7/12 misreadings caught; heuristic: 1/12','Safe rewordings: 11/12 in both'],VIOLET),
             ('Measured limits',['Risk-zero ablation: no verdict changes on the suite','LLM rewrites are optional.','Models never override a denial.'],AMBER)])
    band(s,'Differentiator: argument lineage + measured or predicted impact + exact-action approval + effect evidence.')

    s=slide('Readiness, Scalability & Security','Demo-ready for documented workflows; production work remains.',
        'RELEASE_ACCEPTANCE.md; docs/DEPLOY.md; profile.py; deploy/helm/kavach/; tests/',
        f'The repository test run completed with {passed} passing and {skipped} skipped tests. Skips reflect optional dependencies or external-service prerequisites and are not passes. Verified controls include exact-action approvals, restart-safe windows, a kill switch and signed receipts. The chart deliberately uses one replica with a single receipt-chain writer. Production profile requires real authentication and receipt-signing keys and disables demo reset and clock controls. Remaining work includes load testing, backup/restore drills, CI and alert delivery to people.',
        'Replaced 12 tests and aspirational stateless scaling with the executed test result, the single-writer constraint and explicit deployment gaps.')
    cards(s,[('Implemented',['Exact-action approvals + kill switch','Durable holds + delivery recovery','Signed receipts + checkpoint'],GREEN),
             ('Verified here',[f'{passed} tests passed',f'{skipped} optional tests skipped','External benchmarks reported as saved runs'],BLUE),
             ('Next engineering work',['CI, load + backup/restore drills','Alertmanager delivery','Wider attacks + remaining benchmark runs'],AMBER)])
    band(s,'Deployment constraint: one receipt-chain writer; no measured multi-replica scaling claim.')

    s=slide('Demo: prove what actually happened','Use the inbox, bank ledger and trace beside the agent’s explanation.',
        'DEMO.md; docs/LIVE_DEMO.md; tests/test_trace.py; bench/results/CLAUDE_WITH_WITHOUT.md',
        'Start with a legitimate email, showing that it is queued and then reaches Mailpit once. Send another and cancel it before delivery. For the poisoned-email story, a real model may refuse on its own; identify that correctly. A labelled scripted path demonstrates the same malicious call with and without the gateway. For invoice INV-101, read the vendor record, refuse the substituted account, require human approval and show the sandbox ledger. Trace ties request, decision, connector and receipt together. Recovery and kill-switch are optional follow-up demonstrations with their existing scripts.',
        'Replaced old synthetic-only demo bullets with the documented connector-backed stories and explicit REAL / SCRIPTED / REPLAY labels.')
    table(s,['Story','Action','Independent proof'],[
        ['Legitimate email','Queue → deliver or cancel','Mailpit message / empty inbox'],
        ['Poisoned email','Trace destination → refuse','Trace: connector never called'],
        ['Invoice substitution','Account check → human approval','Sandbox bank: approved payee only'],
        ['Recovery / pause','Restart with a queued action; pause','No duplicate send; waiting action cancelled']], [2.6,4.9,4.52],row_h=.73,size=17)
    band(s,'REAL = live agent  ·  SCRIPTED = chosen calls  ·  REPLAY = saved run. Identify each on stage.')

    s=slide('Decision path: from call to effect','A decision, an execution, and a delivery outcome are separate facts.',
        'kavach/gateway.py: check, execute, resolve_hitl, settle; receipts.py',
        'A session establishes caller and request; outputs are registered as the task reads. A call is validated against the tool manifest, traced and staged. Deterministic floors precede the final verdict. A model score cannot remove a policy requirement. The decision receipt is written before execution. Allowed local calls execute with their actual safeguard; escalations wait for approval; denials return a replan hint. Connector and delivery results produce subsequent records. A queued email is not a delivered email.',
        'Replaced the static decision-flow appendix with an editable, ordered execution lifecycle.', 'TECHNICAL APPENDIX')
    flow(s,[('1  CONTEXT','Session + identity\nRegistered outputs'),('2  EVALUATE','Tool pin + schema\nLineage + consequence'),('3  RECORD','Policy + intent / risk\nReceipt before action'),('4  ACT','Execute / wait / refuse\nOutcome + trace')],h=2.65)
    table(s,['Verdict','Meaning'],[['ALLOW','Permitted; no KAVACH undo implied'],['ALLOW_WITH_SAFEGUARD','Local execution with an armed snapshot, hold or parking'],['ESCALATE / DENY','Waiting for a person / refused before connector']], [3.8,8.22],y=5.3,row_h=.34,size=12)

    s=slide('Provenance & policy: what is trusted','Business records supply facts. Emails and web content do not supply authority.',
        'kavach/provenance.py; policy.py; policies/default.yaml; tests/',
        'Values copied or lightly disguised in emails remain untrusted, including normalized addresses. A user-named document may require confirmation instead of immediate denial; naming a source is not blanket authority. Separate rules ask a person about outbound destinations after untrusted reads, cover destinations with insufficient output context, and accept designated user-only arguments only when the user supplied them. Per-task totals prevent splitting a large operation into small calls. These are implemented checks with residual inference limits, not a proof that arbitrary transformed values are tracked.',
        'Added the expanded provenance and business-rule controls, including invented destinations, task totals and user-only arguments.', 'TECHNICAL APPENDIX')
    table(s,['Control group','Enforced purpose'],[
        ['Origin + destination','Untrusted text cannot grant permission.'],
        ['Data + workspace','Limit leakage, credential access and path escape.'],
        ['Business facts','Use invoice / vendor records and approval tiers.'],
        ['Tool + task controls','Pins, schema, roles, delegation and task totals.']], [3.6,8.42],row_h=.72,size=16)
    band(s,'Example: an account in a vendor email stays untrusted; a separate rule checks the account on record.')

    s=slide('Consequences & the real limits of undo','The deck names the safeguard and who actually arms it.',
        'kavach/consequence.py; environment.py; gateway.py:_allow; tests/test_email_window.py',
        'SQL and supported file actions run on copied state to produce a diff. Their supported local execution uses a snapshot or row-level change record for undo. Email and payment impact is predicted from typed inputs and records; KAVACH can delay delivery or settlement while it controls execution. Email cancellation only works before the server accepts delivery. SAP demo postings are parked rather than booked. Refunds can be plain ALLOW with no reversal guarantee. MCP proxy and framework-hook paths run outside KAVACH and do not inherit its local safeguard.',
        'Replaced broad undo language with operation-specific mechanisms, expiry boundaries and external-execution exclusions.', 'TECHNICAL APPENDIX')
    table(s,['Operation','Impact evidence','Owned-execution safeguard'],[
        ['SQL / supported files','Sandbox diff','Snapshot / row-level restoration'],
        ['Email','Typed prediction','Cancel while queued, before delivery'],
        ['Payment','Prediction + invoice / vendor facts','Hold; recheck account and amount at release'],
        ['SAP demo / refund','Typed prediction','Park document / no generic refund undo'],
        ['External proxy / hook','Manifest + available context','Host executes; no KAVACH-owned undo']], [2.65,3.8,5.57],row_h=.62,size=16)
    band(s,'The API exposes safeguard_armed. “Allowed” alone does not establish reversibility.')

    s=slide('Human approval is bound to the exact call','Approve a specific task, tool and argument set; changed calls need a new decision.',
        'kavach/gateway.py:action_digest, resolve_hitl; hitl.py; tests/test_approval_binding.py',
        'An approval card shows consequence, provenance, requested roles and the action digest. The digest binds task, tool and arguments; approval is one-use and expires. Tiered release quorums require distinct authorized people and exclude the requester. High-value irreversible cases also use four-eyes checks. The default queue can escalate to the configured review chain before expiry. On local execution, approval verifies the stored action digest and executes that stored call. It does not re-run the full policy or tool-definition check at approval time. In hook-only mode the host owns approval binding and execution; the AgentOS hook is not an end-to-end approval implementation.',
        'Added exact-action binding, replay prevention, role quorum and the host responsibility in hook-only mode.', 'TECHNICAL APPENDIX')
    cards(s,[('Before approval',['See the effect + source trail.','Verify task + tool + arguments.','Identify the required review roles.'],BLUE),
             ('At approval',['Use the stored action digest.','Enforce quorum and distinct people.','Expire or deny unattended requests.'],VIOLET),
             ('Before effect',['Changed arguments need a new check.','Approved call is used once.','Settlement rechecks payment facts.'],GREEN)])
    band(s,'A human approval is a scoped authorization, not permission for future calls in the task.')

    s=slide('Delivery, crash recovery & the kill switch','Failure handling is part of execution, rather than a promise on the approval card.',
        'kavach/environment.py; windows.py; receipts.py; tests/test_kill_queued.py; test_receipt_store_down.py',
        'With persistence configured, waiting email and payment state survives restart. A delivery interrupted after handoff may be unknown: it is recorded for review and not automatically resent. Bank requests use an idempotency key. A scoped kill switch refuses new calls and cancels waiting effects, including restored windows. Decision, human-approved execution and early-release receipts must be durable before their actions proceed. A post-effect recording failure marks the log degraded; the implementation cannot undo the fact that a connector already ran.',
        'Added durable outbox behavior, unknown-delivery handling, cancellation of queued effects and the precise receipt-write failure boundary.', 'TECHNICAL APPENDIX')
    cards(s,[('Store fails first',['Pre-action receipt rejected','No connector call','Readiness reports degraded state'],RED),
             ('Send interrupted',['Outcome may be unknown.','Keep the evidence.','Never blindly resend the email.'],AMBER),
             ('Operator pauses',['Block new calls in scope.','Cancel waiting effects.','Persist the pause across restart.'],VIOLET)])
    band(s,'Guarantee scope: controlled connectors and persisted state; no universal exactly-once delivery claim.')

    s=slide('Identity, receipts & verifiable evidence','Authentication establishes authority; cryptography makes later tampering detectable.',
        'kavach/auth.py; identity.py; receipts.py; signing.py; store.py; evidence.py',
        'When authentication is configured, signed tokens establish user, role, tenant and token kind. Orchestrators may establish trusted requests; agent tokens operate inside an existing session. Delegation narrows authority. Receipts chain hashes with HMAC and optional Ed25519 signatures, required in the production profile. A separately stored signed checkpoint detects a truncated tail. An exported chain is verifiable with the public key. Evidence packs map specific receipts to controls and do not certify legal compliance. External anchoring is optional and was not demonstrated in the local demo.',
        'Expanded HMAC-only audit language to signed receipts, checkpoint truncation detection, identity kinds and tenant scope.', 'TECHNICAL APPENDIX')
    flow(s,[('IDENTITY','Signed caller + role\nTenant + task scope'),('RECEIPT','Decision + rule + source\nHash chain + HMAC'),('VERIFICATION','Ed25519 public key\nSeparate signed checkpoint')],h=2.7)
    text(s,.85,5.58,11.5,.6,'Without an auth secret, callers are unauthenticated. Production profile requires real keys.',20,RED,True)

    s=slide('Integrations & who owns execution','One engine can guard several frameworks, with different operational guarantees.',
        'kavach/adapters/; mcp_proxy/; integrations/agentos_hook.py; bench/results/AGENTOS_LIVE.md',
        'The local gateway and demo MCP execution path can own connector delivery and its safeguards. POST /api/v1/check is decision-only by default: it executes, and can arm an undo safeguard, only when the caller sets execute to true. The full MCP proxy supports stdio and Streamable HTTP upstream and downstream, scans definitions and quarantines suspicious tools. It forwards only approved tool calls, but upstream servers execute them and undo is not claimed. Framework adapters cover LangChain/LangGraph, OpenAI Agents and Claude Agent SDK. The AgentOS adapter was exercised through real governance code with a stand-in agent; a completed LLM-driven tenant chat was not demonstrated. AgentOS must use blocking hooks with closed failure policy and owns approval execution. All clients must lose direct bypass access.',
        'Added the actual full MCP proxy and framework adapters; narrowed AgentOS validation to the evidence and removed the drop-in undo implication.', 'TECHNICAL APPENDIX')
    table(s,['Path','Executor','Guarantee boundary'],[
        ['Demo MCP / local gateway','KAVACH connectors','Local holds, snapshots, trace and receipts'],
        ['MCP proxy: stdio / HTTP','Upstream MCP server','Tool scan, pins, decisions; external undo not claimed'],
        ['REST check (default) / SDK adapters','External tool host','Decision only; host executes + registers outputs'],
        ['Topaz AgentOS hooks','AgentOS kernel','Governance-code test; LLM chat remains unverified']], [3.0,2.7,6.32],row_h=.75,size=16)
    band(s,'Deployment requirement: route every relevant tool through the guard and remove direct bypass access.')

    s=slide('How Qualcomm Cloud AI is used','The protected agent and the advisory judge have separate jobs.',
        'kavach/qualcomm.py; intent.py; explain.py; agent/llm_agent.py; bench/results/explain.json',
        'The repository uses an OpenAI-compatible Qualcomm endpoint. Llama-3.3-70B is the protected agent in the saved benchmark runs. The two-stage intent judge triages with a smaller model and invokes a stronger model only when flagged; model selection can be overridden. Default server mode adds a note on already-escalated actions. Plain-text judge responses avoid the observed JSON tool-parser issue. The optional explanation experiment retained nineteen rewrites, rejected twenty-two and fell back on six unavailable responses, out of forty-seven cases. The agent control needs credentials, while offline checks and scripted scenarios remain available.',
        'Corrected hard-coded model assumptions, explanation defaults and token-spending claims; removed unimplemented hardware and embedding ideas from the delivered architecture.', 'TECHNICAL APPENDIX')
    rows=[['Protected agent',COMP['model'],'Task + outputs → proposed tools'],
          ['Advisory judge','Small → strong model; cached','Request + action + labels → reviewer note'],
          ['Explanation rewrite','Optional; disabled by default',f"{EXP['sources']['qualcomm-llm (faithfulness-checked)']}/47 kept; 22 rejected; 6 unavailable"],
          ['Failure path','Deterministic fallback','Cannot relax policy denial or approval floor']]
    table(s,['Role','Configuration','Observed behavior'],rows,[2.6,4.0,5.42],row_h=.79,size=16)
    band(s,'Usage meter records returned tokens; unrecorded benchmark cost stays unknown, not zero.')

    s=slide('Synthetic evaluation: what was measured','Team-written suite: regression evidence, with a stated test split and denominators.',
        'bench/results/results.json; multiseed.json; RESULTS.md',
        f"The suite has {RES['suite']['scenarios']} scenarios across {RES['suite']['families']} families, with {RES['suite']['test']} held-out cases per seed. The headline comparison here uses means across {len(MS['seeds'])} saved seeds. Unsafe auto-allowed uses unsafe cases as its denominator; safe auto-completed uses safe cases; escalation includes all cases. Undo coverage applies only to automatically completed state changes. These labels prevent comparing unlike percentages. The team wrote the rules and suite; zero observed unsafe allowances is a regression result and is not a universal safety guarantee.",
        'Replaced all prototype counts and metrics with JSON-backed results and explicit denominators.', 'EVALUATION APPENDIX')
    names=['No guardrail','Tool-type gating','Approve every write (manual interrupt)','KAVACH: rules only',FULL]
    labels=['No guardrail','Tool-type gating','Approve every write','KAVACH: rules only','KAVACH: full']
    table(s,['System','Unsafe allowed','Injection ASR','Safe auto','Escalated'],
          [[label]+[pc(mean(name,k)) for k in ['UAR','ASR_injection','safe_auto','escalation_rate']] for name,label in zip(names,labels)],
          [3.52,2.1,2.1,2.1,2.2],row_h=.58,size=16)
    band(s,f"{RES['suite']['scenarios']} scenarios · {RES['suite']['families']} families · {len(MS['seeds'])} seeds · undo armed for {pc(mean(FULL,'undo_armed'))} of auto-completed changes")

    s=slide('Ablations: which layers earn the result?','The strongest finding is the deterministic core, not the risk-model headline.',
        'bench/results/layers.json; LAYERS.md; LOFO.md; HOLDOUT.md; results.json',
        'On the family-level analysis, the full system and a version with model risk forced to zero have identical verdicts. Rules-only still differs because it omits the intent/risk path, not because the learned score alone is decisive. The model-only ablation allows many unsafe actions. Removing provenance introduces injection success. Fixed and reversibility-conditioned thresholds tie on the suite, so the threshold is not presented as an established advantage. The family-level sample is twenty-six unsafe families, with a reported interval reaching thirteen percent despite zero observed failures. Fresh and leave-one-family-out tests remain team-authored.',
        'Added the ablation evidence that corrects the old claim that a calibrated model drives the safety result.', 'EVALUATION APPENDIX')
    seed={r['system']:r for r in RES['systems']}
    table(s,['Change','Saved observation','Implication'],[
        ['Force model risk to zero','No verdict changes','Rules + intent gate decide this suite.'],
        ['Use model only',pc(seed['KAVACH: model only (rules off)']['UAR'])+' unsafe allowed','A learned score cannot replace policy.'],
        ['Remove provenance',pc(seed['KAVACH: no provenance']['ASR_injection'])+' injection ASR','Lineage adds measured protection.'],
        ['Use a fixed threshold','Same aggregate metrics as full','Do not claim proven threshold superiority.']], [3.1,3.8,5.12],row_h=.77,size=16)
    band(s,'Family-level result: 0/26 unsafe families leaked; reported 95% interval reaches 13%.')

    banking=COMP['live']['banking']['paired']['kavach']
    s=slide('Live AgentDojo: banking paired results','Saved partial run on Llama-3.3-70B; raw live-task logs are absent from this checkout.',
        'bench/results/comparison.json: live.banking.paired.kavach; COMPARISON.md',
        'This uses the matched subset completed by both defenses, not the full unguarded run. KAVACH completed one hundred forty-four of one hundred sixty planned tasks, including sixteen benign and one hundred twenty-eight attacked cases. On that subset the unguarded agent reached the attacker goal sixty-five times and KAVACH zero times. Benign completion is eight of sixteen in both, and task completion under attack is fifty-three versus sixty-two. Escalations count as blocked because no reviewer participates. It is one model and one attack, with one sample per task. Saved summary arithmetic was checked, but raw per-task live logs are absent, so the run itself cannot be independently revalidated from this checkout.',
        'Promoted independently authored live banking evidence from a future port to a measured, qualified result.', 'EVALUATION APPENDIX')
    def live_rows(pair):
        rows=[]
        for key,label in [('none','No guardrail'),('kavach','KAVACH')]:
            m=pair[key]
            rows.append([label,f"{m['attack_success']}/{m['attacked']} ({pc(m['attack_success']/m['attacked'])})",
                         f"{m['benign_done']}/{m['benign']} ({pc(m['benign_done']/m['benign'])})",
                         f"{m['utility_under_attack']}/{m['attacked']} ({pc(m['utility_under_attack']/m['attacked'])})"])
        return rows
    table(s,['Defense','Attack success ↓','Benign done','Task done under attack'],live_rows(banking),[2.6,3.0,3.0,3.42],row_h=.9,size=18)
    cards(s,[('Paired sample',f"{banking['pairs']} completed task pairs\n16 benign + 128 attacked",BLUE),
             ('Evidence scope','144/160 planned tasks completed.\nSaved aggregate; not independently rerun.',AMBER)],y=5.35,h=1.25)

    slack=COMP['live']['slack']['paired']['kavach']
    s=slide('Live AgentDojo: Slack tradeoffs','Saved paired summary; raw live-task logs unavailable here. Task completion also falls.',
        'bench/results/comparison.json: live.slack.paired.kavach; COMPARISON.md; AGENTDOJO_REPLAY.md',
        'The matched Slack subset contains one hundred twenty-four task pairs: twenty-one benign and one hundred three attacked. Attacker success drops from forty-eight to eleven cases. However, benign completion drops from nine to six and utility under attack from thirty-six to twenty-one. A deck claiming perfect safety or preserved utility would hide this tradeoff. One Slack checker counts attempted calls even when blocked; the replay slide separates its executed-only interpretation. Rate-limit waiting dominates whole-agent task durations; these are not measurements of gateway decision overhead.',
        'Added the residual attack success and utility loss omitted by the prototype narrative; preserved official benchmark scoring.', 'EVALUATION APPENDIX')
    table(s,['Defense','Attack success ↓','Benign done','Task done under attack'],live_rows(slack),[2.6,3.0,3.0,3.42],row_h=.9,size=18)
    text(s,.85,5.55,11.6,.85,'124 paired tasks; KAVACH completed 124/126 planned.\nOfficial attack success includes attempted-call scoring for one Slack attack.',18,AMBER,True)

    s=slide('Replay evidence is a different experiment','Ground-truth tool calls and an obedient attacker; no live model is involved.',
        'bench/results/AGENTDOJO_REPLAY.md; agentdojo_replay_banking.json; agentdojo_replay_slack.json',
        'The offline replay uses AgentDojo’s correct calls for benign work and appends exactly the attacker’s intended calls for attack cases. This tests enforcement under an obedient attacker, rather than whether a model chooses to obey. Banking completes twelve of sixteen benign tasks, with four awaiting human review; all one hundred forty-four replay attacks fail. Slack completes fourteen of twenty-one benign tasks, six stopped only by escalation. The official checker counts twenty-one of one hundred five attacks as success based on attempted calls, while the executed-only check finds zero. Both readings are shown.',
        'Separated replay from live agent evidence and made the Slack attempted-call metric explicit.', 'EVALUATION APPENDIX')
    table(s,['Replay suite','Benign done','Official attack success','Executed-only success'],[
        ['Banking','12/16 (+4 escalated)','0/144','0/144'],
        ['Slack','14/21 (+6 escalated)','21/105','0/105']], [2.4,3.4,3.2,3.02],row_h=.92,size=18)
    cards(s,[('What this proves','Enforcement on the exact calls\nan obedient attacker would request.',BLUE),
             ('What must stay qualified','Different scoring views are shown.\nReplay is not live model behavior.',AMBER)],y=5.35,h=1.25)

    s=slide('Infosys integration & local baseline evidence','Saved local-harness comparison; the external Infosys deployment was not revalidated here.',
        'bench/results/infosys_compare.json: seed0; INFOSYS_COMPARISON.md; AGENTOS_LIVE.md',
        'The Infosys comparison loads the referenced Foundry and AgentOS code into a local harness; it is not a benchmark of every deployed Infosys product. The default pre-tool gate lets most suite unsafe actions pass; hardening it for finance, sends and SQL trades that for broad escalation. KAVACH uses effect and source facts to make a finer decision on this team-authored suite. The PromptGuard comparison scans user queries only, and the RAI row is a perfect-classifier upper bound, not a live RAI deployment. The AgentOS hook governance test is separate from the synthetic baseline comparison.',
        'Updated the comparison to 282 held-out cases, corrected baseline numbers, and scoped the product-level interpretation.', 'EVALUATION APPENDIX')
    keys=[('AgentOS pre-tool gate, default config, autonomous','AgentOS default gate'),('AgentOS pre-tool gate, hardened config, autonomous','AgentOS hardened gate'),('Foundry selective Tool Interrupt on every state-changing tool','Interrupt every change'),(FULL,'KAVACH')]
    table(s,['Local configuration','Unsafe allowed','Injection ASR','Safe auto','Escalated'],
          [[label]+[pc(IC['seed0'][key][k]) for k in ['UAR','ASR_injection','safe_auto','escalation_rate']] for key,label in keys],
          [3.52,2.1,2.1,2.1,2.2],row_h=.7,size=16)
    band(s,'These are harness results for named configurations, not a blanket ranking of enterprise products.')

    s=slide('Operator console & observability','Follow the action from request through decision to connector outcome.',
        'kavach/static/; server.py; telemetry.py; usage.py; deploy/alerts.yml; deploy/grafana/',
        'The plain HTML, CSS and JavaScript console is served by FastAPI without a frontend build. It contains live-agent, scripted-scenario, action-check, approval, activity, undo, trace, receipts, results and rulebook views. Scripted cases are disabled in real Gmail mode. One correlation identifier links the decision, receipts and mail headers. Prometheus reports decisions and delivery outcomes; OpenTelemetry sends decision spans through the collector to Jaeger; Grafana presents them. Fourteen alert rules exist, but alert delivery to a person is not configured. Usage costing reports unknowns rather than treating missing prices or tokens as zero.',
        'Added the implemented console workflow, correlation trail, outcome telemetry and alert-delivery limitation.', 'OPERATIONS APPENDIX')
    cards(s,[('Business reviewer',['Action checker + consequence card','Approvals + cancel / release','Rulebook + receipt verification'],VIOLET),
             ('Operator',['Trace request → actual effect','Prometheus + Grafana','OpenTelemetry → Jaeger'],BLUE),
             ('Evidence and limits',['14 alert rules; no Alertmanager delivery','No raw tool args in telemetry','Missing token prices remain unknown'],AMBER)])
    band(s,'Proof chain: request → call ID → decision → receipt → outbox → SMTP correlation header.')

    s=slide('Optional capabilities & activation limits','The core runs offline; extras require configuration and their own validation.',
        'requirements-extra.txt; kavach/cedar_policy.py; planner.py; melon.py; learning.py; pii.py; shell.py',
        'Optional modules extend the reference implementation: Cedar policy parity and partial-evaluation checks; a CPU injection classifier; Presidio PII recognition; MELON masked re-execution; feedback retraining with a no-regression promotion gate; policy shadow/replay and signed bundles; identity exchange and evidence packs. These are not all active in the default demo. Typed planner data-flow tests work offline, but live Qualcomm plan generation is documented as blocked by response parsing. Shell behavior is constrained to a dry-run sandbox demonstration and does not establish general shell containment. External receipt anchoring was not demonstrated live.',
        'Added feature maturity boundaries and removed proposed hardware / embeddings from the delivered-feature list.', 'OPERATIONS APPENDIX')
    table(s,['Capability','Repository implementation','Maturity boundary'],[
        ['Policy + privacy','Cedar, signed bundles, CPU probe, Presidio','Optional dependencies / flags'],
        ['Feedback + counterfactual','Retraining gate, MELON, policy replay','On demand; not automatic learning'],
        ['Typed planner','Reference-labelled plan execution','Offline tested; live plan generation incomplete'],
        ['Shell + external anchors','Docker dry run; optional public anchoring','No general containment or live-anchor claim']], [2.7,5.0,4.32],row_h=.76,size=16)
    band(s,'Use the test run’s skips and the release acceptance file to judge which extras were exercised.')

    s=slide('Deployment & remaining work','A secured reference deployment is available; production readiness is unproven.',
        'Dockerfile; docker-compose.yml; deploy/helm/kavach/; docs/DEPLOY.md; RELEASE_ACCEPTANCE.md',
        'The repository supports a non-root container, a Compose demonstration stack and a hardened Helm chart. Persistent storage is optional in the server and must be configured deliberately; in-memory defaults do not survive restart. Production profile requires authentication, HMAC and Ed25519 keys, pins tools, and removes demo controls. The chart runs one replica. CI, sustained load testing and a backup/restore drill remain absent; alert delivery and broader deployment hardening remain work. The bank and enterprise environment are simulated, and live benchmark samples remain partial. These are concrete limits, not evidence of production certification.',
        'Replaced speculative horizontal scale and hardware roadmap with actual deployment artifacts and prioritized engineering gaps.', 'OPERATIONS APPENDIX')
    cards(s,[('Run locally',['FastAPI + offline console','Optional Qualcomm credentials','SMTP / sandbox bank for demos'],BLUE),
             ('Secure the reference',['Enable auth + real signing keys.','Configure DB + separate checkpoint.','Remove direct tool bypass routes.'],VIOLET),
             ('Complete before rollout',['CI + sustained load testing','Backup / restore + alert delivery','Broader attacks and utility tuning'],AMBER)])
    band(s,'Helm uses one replica and Recreate strategy to protect the single-writer receipt chain.')

    s=slide('Evidence map & presentation takeaways','Every implementation or measurement claim points back to the repository.',
        'README.md; RELEASE_ACCEPTANCE.md; THREAT_MODEL.md; bench/results/; tests/',
        'Read gateway.py for the full request-to-effect lifecycle, policy.py and provenance.py for enforcement, consequence.py and environment.py for effect modeling, and receipts.py plus store.py for audit and persistence. The server and static directory provide the API and console. Benchmark scripts and saved JSON describe evaluation; test files expose the behavior and limits.',
        'Replaced the dated external-reference list with a repository-backed evidence map and an accompanying detailed explanation.', 'REFERENCE APPENDIX')
    table(s,['Question','Read first'],[
        ['How does an action become an effect?','kavach/gateway.py + environment.py'],
        ['Why is a call blocked or reviewed?','policy.py + provenance.py + policies/default.yaml'],
        ['Can we undo and verify it?','consequence.py + receipts.py + store.py'],
        ['Which numbers are defensible?','bench/results/*.json + named experiment reports']], [4.6,7.42],row_h=.75,size=16)
    band(s,'Claim the measured benefit, show the actual effect, and state where human review or further work is needed.')

    s=slide('How KAVACH compares','Each approach solves part of the problem. KAVACH combines the checks at the tool call.',
        dc.COMPARE_SOURCES,dc.COMPARE_NOTES,'Added a comparison with published systems, with the USP and where others are stronger.','REFERENCE APPENDIX')
    table(s,dc.HEAD,dc.ROWS,[4.04,1.33,1.33,1.33,1.33,1.33,1.33],y=2.05,row_h=.3,size=9)
    text(s,.65,5.74,12.0,.5,dc.LEGEND,9,MUTED)
    band(s,'USP: origin of each value + real effect + approval for the exact call + a chance to stop it + a signed record.')

    s=slide('Infosys AgentOS and KAVACH','AgentOS is Infosys’s own agent runtime. We read and ran its code. KAVACH plugs into it; it does not replace it.',
        dc.AGENTOS_SOURCES,dc.AGENTOS_NOTES,'Added what AgentOS does, how KAVACH differs and how the two fit together.','REFERENCE APPENDIX')
    table(s,dc.AGENTOS_HEAD,dc.AGENTOS_ROWS,[1.4,5.62,5.0],y=2.05,row_h=.4,size=10)
    aos=[f"{label}: {pc(IC['seed0'][k]['UAR'])} unsafe allowed, {pc(IC['seed0'][k]['safe_auto'])} safe work done, {pc(IC['seed0'][k]['escalation_rate'])} sent to a person" for k,label in dc.AGENTOS_KEYS]
    text(s,.65,5.31,12.0,.92,['Same team-written suite, 282 test cases, seed 0:  '+';  '.join(aos)+'.',dc.AGENTOS_BAND],9.5,MUTED)
    band(s,'AgentOS keeps routing, sandboxing, approvals and RBAC. KAVACH supplies the judgment through its hooks.')

    OUT.mkdir(exist_ok=True)
    props=prs.core_properties
    props.title='KAVACH Solution Deck';props.subject='Repository-backed solution and evidence'
    props.author='KAVACH';props.keywords='KAVACH, ET-03, agent guardrails'
    props.comments='';props.last_modified_by='KAVACH'
    path=OUT/'KAVACH_Verified_Reference_Deck.pptx'
    prs.save(path)
    # Remove authoring calendar fields as requested, including python-pptx defaults.
    with zipfile.ZipFile(path) as z:
        entries={n:z.read(n) for n in z.namelist()}
    root=ET.fromstring(entries['docProps/core.xml'])
    for node in list(root):
        if node.tag.rsplit('}',1)[-1] in {'created','modified','lastPrinted'}:root.remove(node)
    entries['docProps/core.xml']=ET.tostring(root,encoding='utf-8',xml_declaration=True)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in entries.items():z.writestr(name,data)
    for info,s in zip(SLIDES,prs.slides):
        info['content']=[sh.text for sh in s.shapes if sh.has_text_frame]
        for sh in s.shapes:
            if sh.has_table:
                info['content'].extend(' | '.join(c.text for c in row.cells) for row in sh.table.rows)
    (OUT/'review/slide_manifest.json').write_text(json.dumps(SLIDES,indent=2,ensure_ascii=False)+'\n')
    explain(passed,skipped)
    print(f'Built {len(prs.slides)} editable slides: {path}')


def explain(passed,skipped):
    intro=f'''# KAVACH solution deck: update explanation

The original 15-slide solution deck described the prototype. The separate reference deck has 28 slides: eight presentation slides following the original submission topics, followed by technical, evaluation, operations and reference appendices, including the comparison and AgentOS slides. The PowerPoint remains editable, including diagrams and tables.

No calendar dates or authoring timestamps are included in the revised deck, its speaker notes or this explanation. Technical durations, model names, identifiers, policy limits and benchmark latencies are operational facts rather than authoring history. The source deck and its PDF are preserved unchanged in `before_update/` for comparison. The original template is also unchanged; its dated graphics are not reused in the rebuilt deck.

## Most consequential changes

| Topic | Original deck | Revised deck |
|---|---|---|
| Policy coverage | Prototype rule set | Expanded catalogue, with examples of origin, task totals, finance and user-only argument checks; slides quote no rule numbers or count |
| Evaluation suite | 740 cases, 37 families | {RES['suite']['scenarios']} cases, {RES['suite']['families']} families; {RES['suite']['test']} held-out cases per seed |
| Synthetic unsafe auto-allowed | 0.5% | {pc(mean(FULL,'UAR'))}, qualified as team-written synthetic evidence |
| Synthetic safe automation | 68% | {pc(mean(FULL,'safe_auto'))} of safe cases; saved five-seed mean |
| Rules-only unsafe allowed | About 30% | {pc(mean('KAVACH: rules only','UAR'))}; intent gate is distinct from learned-model contribution |
| Blanket manual approval | Claimed safe; roughly 12% safe automation | {pc(mean('Approve every write (manual interrupt)','UAR'))} unsafe allowed and {pc(mean('Approve every write (manual interrupt)','safe_auto'))} safe automation on this baseline; its coverage is imperfect |
| Model contribution | Risk model presented as key safety driver | Risk-zero ablation changes no verdict on this suite; deterministic rules and intent gate carry decisions |
| Threshold innovation | Reversibility threshold promoted as a differentiator | Fixed threshold ties on saved aggregate metrics; no proven superiority claimed |
| Explanations | LLM writes them by default | Templates default; optional checked rewrite, with 19 kept, 22 rejected and 6 unavailable in the saved experiment |
| Qualcomm judge | Ambiguous calls described as inline by default | Default adds a note on escalations; inline semantic evaluation is separately labelled |
| Undo | Broad reversible-action promise | Local snapshot, queued-email cancellation, payment hold and SAP parking; external hooks do not inherit local undo |
| Integrations | Minimal MCP door and AgentOS hook | Full stdio / HTTP MCP proxy, SDK adapters and scoped AgentOS governance evidence |
| Independent evidence | AgentDojo mostly a future port | Paired, partial live banking and Slack results, plus separately labelled offline replay |
| Reliability | General fallback / rollback language | Exact-action approvals, durable windows, unknown delivery handling, receipt-write boundary and queued-action kill switch |
| Audit | Hash chain + HMAC | Optional Ed25519, required in prod profile; separate signed checkpoint; public verification |
| Scaling | Stateless / horizontal scaling aspiration | Single receipt-chain writer; one-replica Helm reference deployment |
| Tests | 12 tests | {passed} passed, {skipped} skipped in the executed repository test suite |
| Presentation | Small text, stale charts, unfilled identities and dated branding | Consistent editable layouts, source footers, explanatory speaker notes, no fabricated identities |

## End-to-end repository walkthrough

### 1. Entry points and caller authority

`kavach/server.py` serves FastAPI endpoints and the console. `/api/v1/session` lets the orchestrator establish a trusted user request and output context; `/api/v1/check` accepts a proposed action and only decides unless the caller sets `execute`; `/api/v1/plan` validates plans. The demo `/mcp` provides tool calls backed by KAVACH's environment. `kavach/mcp_proxy/` is the separate general-purpose upstream proxy. `agent/llm_agent.py` runs the Qualcomm-hosted tool-using agent and supports guarded and unguarded comparisons.

With `KAVACH_AUTH_SECRET`, `auth.py` derives identity from signed tokens, including role, tenant and orchestrator/agent kind. Agent tokens cannot declare a fresh trusted request. `identity.py` adds short-lived task-scoped exchange and delegation. Development mode has no authenticated identity guarantee. Identity scope and role authorization are different controls and both matter.

### 2. Tool definitions and argument provenance

`manifest.py` registers typed effect signatures, argument schemas, control/data argument roles, confidentiality and output trust. Definition hashes pin approved behavior. Unknown tools fail closed in the core; adapters can explicitly onboard a cautious draft for human review. `mcp_proxy/scan.py` screens descriptions for poisoning and shadowing, and the proxy quarantines suspicious or changed tools.

`provenance.py` records the trusted request and every observed output. It traces arguments to user input, business data, agent-derived values or untrusted text, including normalized disguised addresses. This is value matching with known limits, especially for newly composed values. `addresses.py` and `lookalike.py` handle recipient parsing and confusing domains. Naming a document does not automatically authorize its instructions: delegated source cases can go to human review. Separate rules cover destinations where direct tracing is insufficient and restrict designated arguments to user input.

### 3. Consequence analysis

`consequence.py` chooses sandbox, static or predicted analysis. `sql.py` and `changelog.py` measure actual SQL operations and row/column changes on staged state; file actions use supported copies. Typed external effect models estimate recipients, PII, money and reversibility without pretending to have run a real bank or email server. `environment.py` owns a seeded synthetic enterprise with CRM, invoices, vendor records, finance tools, mailbox, files and windows. Real services enter through `connectors.py`; Mailpit is a real local SMTP sink, Gmail is optional, and `scripts/sandbox_bank.py` remains a simulated bank.

### 4. Policy and final verdict

`policy.py` evaluates the catalogue in `policies/default.yaml`. Controls cover provenance, leakage, freeze, destructive SQL, business limits, tool pins and schemas, RBAC, secrets, paths, actual records and columns, AP approvals, retention, invoice matching, canaries, finance facts, delegation, shell constraints and task-wide cumulative budgets. One rule verifies the invoice's amount and vendor account from records. Another counts the whole task, reducing split-operation bypasses.

`gateway.py` integrates context, provenance, consequence, deterministic floors, intent and risk. A deterministic denial stays denied. A policy approval floor cannot be auto-allowed by a model. Intent mismatch, uncertainty or other risk conditions escalate rather than become model-only denials. `risk.py` loads the calibrated ensemble and computes a score and interval; this code path exists, but the saved ablation shows that its learned risk value does not change the synthetic suite's final verdicts.

### 5. Qualcomm and optional semantic assistance

`qualcomm.py` provides the shared endpoint client with retries, timeout budgeting and response parsing. `intent.py` has a deterministic heuristic and a two-stage reasoning-blind judge that sees the request, call and provenance rather than trusting the agent's reasoning. `GatewayConfig.judge_mode` defaults to `escalations-only`: a note for a person already deciding. Inline semantic evaluation is an explicit different mode. Its saved 24-case result is 7/12 unsafe misreadings caught versus 1/12 without the judge, and 11/12 safe rewordings completed in both cases. These cases were hand-written by the rule authors and are not a general detection-rate estimate.

`explain.py` always creates a template and optionally accepts a model rewrite if numeric and verdict faithfulness checks pass. LLM explanation is disabled by default. `usage.py` meters returned usage by component; `model_prices.json` contains reference rates and unknowns. The saved AgentDojo logs lack token accounting, so historical run costs cannot be reconstructed reliably.

### 6. Approval and controlled execution

`hitl.py` maintains review cards, deadlines, escalation chains and quorum. `gateway.py:action_digest` binds task, tool and arguments; `resolve_hitl` executes the stored action after one-use approval, subject to applicable identity, role and separation-of-duty checks. Mutating a call invalidates that approval. Host-only hooks do not inherit that full local execution guarantee.

`gateway.py:execute` calls the supported local execution path only after a decision receipt. SQL/files have supported restoration, email can be cancelled while queued, payments can be held and rechecked, and SAP demo postings can be parked. A refund is not inherently undoable. `safeguard_armed` exposes actual safeguard status. Once SMTP delivery is accepted, KAVACH cannot retrieve the recipient's mail.

### 7. Settlement, recovery and operator intervention

`windows.py`, `environment.py` and `store.py` preserve waiting state when a database is configured and settle windows. An interrupted send can be unknown; it is not automatically repeated. Bank requests use idempotency keys. A kill switch stops new scoped calls and cancels pending effects, including restored windows. Receipt writes for decisions, approved executions and manual early release fail closed before the connector. Failures recording a completed effect mark degraded evidence; they cannot make an already delivered message disappear.

### 8. Audit, persistence and evidence

`receipts.py` implements a SHA-256 chain and HMAC, with `signing.py` adding Ed25519 public-key verification. `store.py` persists supported state to SQLite or Postgres and maintains a separately stored signed checkpoint to detect tail truncation. Database persistence must be configured; the default is in memory. `anchor.py` supports optional external anchoring, which is not claimed as demonstrated here. `evidence.py` exports per-task control evidence rather than legal certification. `profile.py` requires real auth and signing material for production profile and disables demonstration controls.

### 9. Integration and UI boundaries

`adapters/guard.py` is shared by LangChain/LangGraph, OpenAI Agents and Claude Agent SDK adapters. These check and register outputs while the framework executes tools, so `local_execution=False` avoids claiming a local snapshot or hold. `integrations/agentos_hook.py` maps denial to a blocked AgentOS call and escalation to its approval queue. The saved AgentOS run used the real governance code with a stand-in agent. A full LLM-driven tenant chat is unverified, and AgentOS owns execution after approval.

`static/index.html`, `vx.css` and `app.js` implement the console with native web assets and hash routes. It distinguishes live agents, scripted scenarios, activity, approvals, undo, traces, receipts, results and policies. Scripted demos are refused while real mail mode is active. The display shows real outcome status rather than accepting an agent's success claim.

### 10. Observability, optional extensions and deployment

`telemetry.py` emits Prometheus metrics, OpenTelemetry decision spans and optional SIEM forwarding; `logs.py` emits structured decision logs without raw arguments. `deploy/` supplies collectors, Jaeger wiring, Grafana provisioning, alert rules and Helm templates. Alert rules exist, but delivery to people is not configured. The Helm chart intentionally runs one receipt-chain writer.

Optional modules include Cedar parity/verification, Presidio PII, a CPU injection classifier, MELON masked re-execution, signed policy bundles, shadow/canary policy replay, task identity and a no-regression feedback retraining loop. Retraining is on demand rather than automatic. `planner.py` supports reference-labelled offline plans, while live Qualcomm plan generation is documented as incomplete. `shell.py` is a constrained sandbox demonstration with no general containment claim. `requirements-extra.txt` identifies optional prerequisites; implemented code does not mean an extra is active in the default demo.

## Reading the measurements correctly

The deck deliberately preserves separate evidence categories:

- **Synthetic suite:** `results.json` and `multiseed.json`. The main synthetic table uses the five-seed mean consistently. Seed-0 results, model ablations, family-level intervals and other runs are labelled independently.
- **Live AgentDojo:** `comparison.json` contains paired subsets. Banking compares 128 attacked cases and 16 benign cases; Slack compares 103 attacked cases and 21 benign cases. Do not use the full unguarded sample as the denominator for a partial guarded run.
- **Banking live:** attack success 65/128 → 0/128; benign completion 8/16 → 8/16; user task completion under attack 53/128 → 62/128.
- **Slack live:** attack success 48/103 → 11/103; benign completion 9/21 → 6/21; user task completion under attack 36/103 → 21/103. Residual successes and utility loss remain visible.
- **Offline AgentDojo replay:** correct tool-call sequences plus an obedient attacker. Banking: official and executed-only attacks 0/144. Slack: official attempted-call scoring 21/105; executed-only 0/105. This is a distinct experiment.
- **Infosys local baselines:** `infosys_compare.json`, seed-0 harness results on 282 cases. KAVACH escalation is {pc(IC['seed0'][FULL]['escalation_rate'])} in that run; its multiseed primary suite reports {pc(mean(FULL,'escalation_rate'))}. Different files were produced by different runs, so the deck does not silently blend them.
- **Latency:** the primary synthetic result file reports p50/p95 2.40/9.95 ms for the full system, excluding the judge. The separate comparison harness reports 0.43/3.48 ms over 1,027 decisions on Darwin arm64. These are saved-machine measurements and are not reproduced performance claims for this environment. The deck removes the old universal sub-5-ms promise.
- **Claude demo:** the saved comparison reports real Claude refusing malicious requests even without KAVACH. The deck does not credit KAVACH for a model's independent refusal; enforcement is shown separately through labelled scripted calls.

## Verification register

`KAVACH_Reference_Claim_Verification.md` maps all 28 slides to exact source locations, relevant test outcomes and evidence limits. Saved numeric results are checked against JSON, including denominators and percentage calculations. A saved report supports a statement about what that report records; it does not establish that the external experiment was independently reproduced. Raw live AgentDojo task logs are absent from this checkout. External AgentOS and Infosys harness results are also presented as saved reports rather than fresh external validation.

The deeper audit corrected two details: approving a local action checks its stored digest but does not rerun the complete policy/tool-definition checks; and an auth secret can enable authentication even outside the production profile. These boundaries are now explicit in the deck and notes.

## Validation and scope

The repository suite was executed with `.venv/bin/python -m pytest -q`: **{passed} passed, {skipped} skipped**. Optional service/dependency skips remain explicit. No application code was changed for this documentation task, no user credentials were inspected, and no real-bank payments were made or external user mail sent. Local demo services may be exercised by the tests. Live model, AgentOS, Gmail, external anchoring and connector demos were reviewed from source, tests and saved reports rather than rerun. Build and visual checks are recorded in `review/deck_validation.json` after export.

The PDF is exported from the final PPTX. Slide text, notes and authoring properties are checked for calendar strings. The original files are retained for comparison, including their original contents. The report and speaker notes explain implemented, optional, simulated, partial and missing functionality separately.

## Rebuilding the deliverables

The authoring dependencies are in `requirements-deck.txt`; PDF export also needs LibreOffice with its Impress component. From the repository root:

```bash
.venv/bin/python scripts/build_reference_deck.py
.venv/bin/python scripts/export_deck.py
.venv/bin/python scripts/validate_deck.py
.venv/bin/python scripts/audit_deck_claims.py
```

`build_reference_deck.py` regenerates the editable PowerPoint, speaker notes, this explanation and slide manifest from the saved evidence. `export_deck.py` exports the PDF and strips authoring calendar properties. `validate_deck.py` checks text preservation, notes, geometry, page count, headline metrics and calendar strings. `review/validation.json` records the executed repository test result; rerunning the deck builder does not rerun the tests or a live model.

## Slide-by-slide changes and presenter explanation
'''
    parts=[intro]
    for info in SLIDES:
        parts += [f"\n### Slide {info['number']}: {info['title']}\n",f"**Changed:** {info['change']}\n",f"**Explain it this way:** {info['explanation']}\n",f"**Evidence:** `{info['sources']}`\n"]
    (OUT/'KAVACH_Reference_Deck_Explanation.md').write_text('\n'.join(parts))

if __name__=='__main__':
    build()
