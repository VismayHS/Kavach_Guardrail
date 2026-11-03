"""Fill the supplied Infosys solution template without replacing its design.

Main submission: the eight template slides, in order, plus three added in the same style: architecture diagram
(docs/diagrams/architecture.png, rendered from architecture.mmd with mermaid-cli), comparison + USP, and AgentOS.
Additional technical material is kept in KAVACH_Verified_Reference_Deck.pptx. Authoring dates are removed; existing official
branding and copyright are preserved. Template helper text is replaced and the
suggested-time labels are emptied, so neither shows on a submitted slide.
"""
import copy
import hashlib
import json
import zipfile
from pathlib import Path
from lxml import etree
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

import deck_compare as dc

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'deliverables'
TEMPLATE=Path('/home/vismay-hs/Hack-AI-Thon_Solution_Presentation_Template.pptx')
FALLBACK=OUT/'template_source.pptx'
EXPECTED='cf3c95de665acf7ea6d19de8da6b617291dbe35a1a411058da860ce66fbc9126'
TEAM={'name':'Team Kavach','college':'PES University, Bengaluru','members':['Vismay H S','Ashwin C H','Dhanush S R']}


def shape(slide,name):
    def walk(shapes):
        for item in shapes:
            if item.name==name:return item
            if item.shape_type==6:
                found=walk(item.shapes)
                if found is not None:return found
        return None
    found=walk(slide.shapes)
    if found is None:raise KeyError(name)
    return found


def put(sh,content,size=None):
    """Change text in the original shape, retaining its placement and font style."""
    tf=sh.text_frame
    p0=tf.paragraphs[0]
    rpr=copy.deepcopy(p0.runs[0]._r.rPr) if p0.runs and p0.runs[0]._r.rPr is not None else None
    placeholder_italic=bool(p0.runs and p0.runs[0].font.italic)
    ppr=copy.deepcopy(p0._p.pPr)
    tf.clear()
    for i,value in enumerate(content if isinstance(content,list) else [content]):
        p=tf.paragraphs[0] if i==0 else tf.add_paragraph()
        if ppr is not None:
            if p._p.pPr is not None:p._p.remove(p._p.pPr)
            p._p.insert(0,copy.deepcopy(ppr))
        r=p.add_run();r.text=value
        if rpr is not None:r._r.insert(0,copy.deepcopy(rpr))
        if size is not None:r.font.size=Pt(size)
        if placeholder_italic:
            r.font.italic=False
            r.font.color.rgb=RGBColor.from_string("1F2937")


def add_like(prs, source, title, subtitle, after):
    """A new slide on the template's own layout and master, with the source slide's title, subtitle and page number."""
    slide = prs.slides.add_slide(source.slide_layout)
    for ph in list(slide.shapes):
        ph._element.getparent().remove(ph._element)
    for name in ('Text 0', 'Text 1', 'Slide Number Placeholder 0'):
        slide.shapes._spTree.append(copy.deepcopy(shape(source, name)._element))
    put(shape(slide, 'Text 0'), title)
    put(shape(slide, 'Text 1'), subtitle)
    ids = prs.slides._sldIdLst
    ids.insert(after, ids[-1])
    return slide


def grid(slide, rows, x, y, widths, row_h, size, first_left=True, marks=False, highlight=None):
    """A native, editable table in the template's colours."""
    t = slide.shapes.add_table(len(rows), len(widths), Inches(x), Inches(y), Inches(sum(widths)), Inches(row_h * len(rows))).table
    for j, w in enumerate(widths):
        t.columns[j].width = Inches(w)
    for i, row in enumerate(rows):
        t.rows[i].height = Inches(row_h)
        for j, value in enumerate(row):
            c = t.cell(i, j)
            c.margin_left = c.margin_right = Inches(.06)
            c.margin_top = c.margin_bottom = Inches(.02)
            c.vertical_anchor = MSO_ANCHOR.MIDDLE
            c.fill.solid()
            c.fill.fore_color.rgb = RGBColor.from_string('0B3C6F' if i == 0 else 'F1ECFB' if i == highlight else 'FFFFFF' if i % 2 else 'F4F7FA')
            tf = c.text_frame
            tf.text = value
            para = tf.paragraphs[0]
            para.alignment = PP_ALIGN.LEFT if (j == 0 and first_left) or not marks else PP_ALIGN.CENTER
            run = para.runs[0] if para.runs else para.add_run()
            run.font.size = Pt(size)
            run.font.bold = i == 0 or i == highlight or (marks and j > 0 and value != '—') or (not marks and j == 0)
            colour = 'FFFFFF' if i == 0 else '1F2937'
            if marks and i and j:
                colour = {'—': '94A3B8', 'Partly': 'B45309'}.get(value, '1F6B45')
            run.font.color.rgb = RGBColor.from_string(colour)
    return t


def note_box(slide, x, y, w, h, value, size=10.5, fill='F8FAFC', edge='CBD5E1', colour='1F2937', bold=False):
    box = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    box.fill.solid(); box.fill.fore_color.rgb = RGBColor.from_string(fill)
    box.line.color.rgb = RGBColor.from_string(edge); box.shadow.inherit = False
    tf = box.text_frame; tf.word_wrap = True; tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = Inches(.1); tf.margin_top = tf.margin_bottom = Inches(.03)
    tf.text = value
    run = tf.paragraphs[0].runs[0]
    tf.paragraphs[0].alignment = PP_ALIGN.LEFT
    run.font.size = Pt(size); run.font.bold = bold; run.font.color.rgb = RGBColor.from_string(colour)
    return box


def strip_authoring_dates(path):
    with zipfile.ZipFile(path) as z:items={n:z.read(n) for n in z.namelist()}
    with zipfile.ZipFile(TEMPLATE if TEMPLATE.exists() else FALLBACK) as original:
        for name in original.namelist():
            if name.startswith(('ppt/slideMasters/','ppt/slideLayouts/','ppt/theme/','ppt/media/')):
                items[name]=original.read(name)
    root=etree.fromstring(items['docProps/core.xml'])
    for child in list(root):
        if etree.QName(child).localname in {'created','modified','lastPrinted'}:root.remove(child)
    items['docProps/core.xml']=etree.tostring(root,xml_declaration=True,encoding='UTF-8',standalone=True)
    with zipfile.ZipFile(path,'w',zipfile.ZIP_DEFLATED) as z:
        for n,data in items.items():z.writestr(n,data)


def build():
    template=TEMPLATE if TEMPLATE.exists() else FALLBACK
    assert hashlib.sha256(template.read_bytes()).hexdigest()==EXPECTED,'Unexpected template; inspect before using.'
    prs=Presentation(template)
    assert len(prs.slides)==8
    ms=json.loads((ROOT/'bench/results/multiseed.json').read_text())
    live=json.loads((ROOT/'bench/results/comparison.json').read_text())['live']
    bank=live['banking']['paired']['kavach'];slack=live['slack']['paired']['kavach']
    val=json.loads((OUT/'review/validation.json').read_text())
    safe=f"{100*ms['systems']['KAVACH (full)']['safe_auto']['mean']:.1f}%"
    unsafe=f"{100*ms['systems']['KAVACH (full)']['UAR']['mean']:.1f}%"
    tests=f"{val['tests']['passed']} passed; {val['tests']['skipped']} skipped"
    infosys=json.loads((ROOT/'bench/results/infosys_compare.json').read_text())['seed0']
    updates={
      1:{'TextBox 1':(['KAVACH','','Solution Presentation · ET-03'],None)},
      2:{'Text 3':('',None),'Text 6':(TEAM['name'],None),'Text 10':(TEAM['college'],None),
         'Text 13':(' • '.join(TEAM['members']),12),
         'Text 19':('ET-03 · Agentic AI Guardrail Validator',11),
         'Text 22':('Qualcomm Cloud AI Playground',11)},
      3:{'Text 7':('Check whether an AI agent’s planned action is safe, authorized, explainable and reversible before it runs.',16),
         'Text 10':('Enterprise agent owners, AP / finance reviewers and auditors.',11),
         'Text 13':('A wrong tool call can leak data, redirect money or damage records.',11),
         'Text 16':('Tool permissions alone do not show where an argument came from or which records will change.',11),
         'Text 19':('A poisoned email asks the agent to send customer data to an outside address. KAVACH blocks that call.',11),
         'Text 22':('Complete legitimate work; stop unauthorized calls before execution; explain the decision and actual safeguard.',11)},
      4:{'Text 3':('',None),'Text 7':('KAVACH checks an agent’s proposed tool call before it can change enterprise data or send information.',12),
         'Text 12':('User request, caller role, tool + arguments, and prior tool outputs.',12),
         'Text 18':('Trace sources → stage or predict impact → apply policy rules → check intent and risk.',12),
         'Text 24':('Allow, allow with safeguard, escalate or deny; explanation + receipt.',12),
         'Text 30':('RESULTS',8.5),
         'Text 31':(f"AgentDojo, independent benchmark, paired subset: banking attacks {bank['kavach']['attack_success']}/{bank['kavach']['attacked']} with KAVACH vs {bank['none']['attack_success']}/{bank['none']['attacked']} without; Slack {slack['kavach']['attack_success']}/{slack['kavach']['attacked']} vs {slack['none']['attack_success']}/{slack['none']['attacked']}, but benign tasks fell from {slack['none']['benign_done']}/{slack['none']['benign']} to {slack['kavach']['benign_done']}/{slack['kavach']['benign']}. Own synthetic suite: {safe} safe work completed, {unsafe} unsafe allowed.",10.5)},
      5:{'Text 1':('One decision engine; what KAVACH can guarantee depends on who executes the tool.',None),'Text 3':('',None),
         'Text 7':(['Agent / orchestrator','Reviewer console'],11.5),
         'Text 11':(['FastAPI gateway','Provenance + policy rules'],11),
         'Text 15':(['Sandbox / typed effects','Risk + advisory Qualcomm judge'],11),
         'Text 19':(['Decision + receipt','Owned execution / human review'],11),
         'Text 22':('Python, FastAPI, SQLite, vanilla JS, YAML, scikit-learn; optional MCP and signing extras.',11),
         'Text 25':('Deterministic rules retain authority. Templates explain decisions; models can add caution.',11),
         'Text 28':(f'{tests}. Tested: approval binding, delivery recovery and receipt integrity.',10.5),
         'Text 31':('BOUNDARY',8.5),
         'Text 32':('Demo MCP / local gateway can execute with holds or snapshots. REST checks (by default), MCP proxy and SDK hooks decide while an external host executes; they do not inherit KAVACH-owned undo.',11)},
      6:{'Text 1':('Rules decide. AI reads meaning a keyword check misses, and can only add caution.',None),'Text 3':('',None),
         'Text 7':('Agentic workflow + calibrated risk + optional LLM semantic review',14),
         'Text 10':('Argument lineage + consequence evidence + exact-action approval',11),
         'Text 13':('Risk scores support review. Default Qualcomm judge adds notes on escalations; explanations use templates.',11),
         'Text 16':('User request + call + source labels; risk ensemble; two-stage Llama judge on Qualcomm.',11),
         'Text 19':('Models cannot relax policy. Risk-zero ablation changed no suite verdicts. Optional rewrites are checked.',11),
         'Text 22':('Live inline test: 7/12 semantic misreadings caught vs 1/12 heuristic; safe work 11/12 in both.',11),
         'Text 25':('EVIDENCE',8.5),
         'Text 26':('Rules and the intent gate carry the synthetic-suite decisions. The learned score is supporting evidence. The 24 semantic cases are hand-written; 7/12 in two clean live runs, 6/12 in a third with other jobs competing for the service.',11)},
      7:{'Text 1':('What works now, what comes next, and the safeguards already in place.',None),'Text 3':('',None),
         'Text 9':('Add CI, load tests and backup / restore drills.',11),
         'Text 12':('Complete wider paired attack evaluations; tune false escalations.',11),
         'Text 15':('Validate reviewer usability and accessibility beyond the demo.',11),
         'Text 20':('Single receipt-chain writer; Helm defaults to one replica.',11),
         'Text 23':('Judge advises escalations; allowed calls avoid that model latency.',11),
         'Text 26':('Prometheus / Grafana exist; alert delivery remains to be configured.',11),
         'Text 31':('Signed caller identity and role checks when auth is configured.',11),
         'Text 34':('Secrets broker; tool arguments omitted from telemetry.',11),
         'Text 37':('Digest-bound approvals, kill switch and tamper-evident receipts.',11),
         'Text 43':('NOW / NEXT',8.5),
         'Text 44':('Implemented: guarded workflows and recovery controls. Next: deployment validation. Demo company and bank are simulated; production readiness is unproven.',10.5)},
      8:{},
    }
    narratives={
      1:('Introduce KAVACH as an action firewall between an agent and tools. It evaluates source, effect and authority before controlled execution.','README.md; kavach/gateway.py; THREAT_MODEL.md'),
      2:('We are Team Kavach, working on ET-03, Agentic AI Guardrail Validator, on the Qualcomm Cloud AI Playground. This is a software solution: no hardware is involved.','README.md'),
      3:('The statement on the slide is a summary of ET-03. The poisoned-email example is implemented in the repository: the destination comes from the email, not the user, so the provenance rule refuses the call. Do not present a model’s independent refusal as KAVACH enforcement.','THREAT_MODEL.md; tests/test_trace.py; tests/test_invoice_demo.py'),
      4:('Register tool outputs, trace proposed arguments, stage SQL/files or predict external effects, apply deterministic floors and then evaluate intent/risk. Only deterministic controls deny outright. AgentDojo is the evidence we did not write ourselves: a saved paired run on Llama-3.3-70B, one model and one attack with one sample per task, comparing only tasks both defenses finished (144 banking, 124 Slack). An escalation counts as a block because no reviewer takes part. Say the Slack cost out loud: fewer attacks succeed, and fewer benign tasks finish. Suite metrics are five-seed means on the team-written synthetic suite of 940 scenarios / 47 families, not a universal safety rate. Unknown tools fail closed in the core; configured adapters can onboard cautious drafts for review.','kavach/gateway.py; provenance.py; consequence.py; policy.py; bench/results/comparison.json; bench/results/COMPARISON.md; bench/results/multiseed.json'),
      5:('The REST /api/v1/check endpoint is decision-only by default: it executes, and can arm undo, only when the caller sets execute to true. The demo MCP/local gateway path can control effects; the full MCP proxy and SDK wrappers forward permitted calls to an external executor. The test run has 521 passes and 14 skips; optional SDK/AgentDojo/PII/shell/probe tests have documented skips. Approval checks the stored digest but does not repeat the full policy/tool-definition check. Auth depends on a configured secret; the production profile requires actual keys.','kavach/server.py; gateway.py; adapters/guard.py; tests/'),
      6:('The learned risk score is a supporting signal: forcing it to zero changed no saved synthetic-suite verdicts. The server’s default judge mode is escalations-only, adding a reviewer note; the separate inline semantic test, run live, caught 7/12 unsafe misreadings versus 1/12 heuristic, with 11/12 safe rewordings completed in both modes, at about 5 s per check. Two clean runs gave 7/12 and a third, with other jobs competing for the service, gave 6/12. We wrote the cases ourselves, so this is not a general detection rate. Templates are default explanations; optional LLM rewrites must pass number and verdict checks. No measured benefit is attributed to the reversibility threshold, which ties a fixed-threshold baseline.','kavach/gateway.py; intent.py; explain.py; bench/results/layers.json; semantic.json'),
      7:('Distinguish present controls from future work. Persistence must be configured. The reference Helm chart has one replica and Recreate strategy for the single-writer chain. CI, sustained load, backup/restore drills and delivery of alerts to people remain incomplete in the recorded release acceptance. General production readiness and general shell containment are not established. External AgentOS governance and benchmark findings are saved reports, not fresh external validation.','RELEASE_ACCEPTANCE.md; docs/DEPLOY.md; profile.py; deploy/helm/kavach/; telemetry.py'),
      8:('Demo sequence: (1) queue a legitimate email and prove delivery once in Mailpit, or cancel before delivery; (2) show a poisoned-email call denied by the provenance rule and trace that the connector never ran; (3) read invoice INV-101 and vendor record, refuse a substituted account, request human approval and show the sandbox ledger; (4) optionally demonstrate recovery or kill-switch cancellation. For real Gmail, start scripts/gmail_up.sh instead (scripted stories switch off there): asked to summarise a poisoned email and do what it asks, Llama tried to send to the address in the email, KAVACH refused it and Gmail was never called; asked only to summarise, neither Llama nor Claude obeyed in our runs, so say that this depends on the model. Label REAL agent, SCRIPTED calls and REPLAY distinctly. A model may refuse the malicious request itself. The bank is simulated; Mailpit is a real local SMTP sink. Further numeric details are in the separate reference deck.','DEMO.md; docs/LIVE_DEMO.md; scripts/gmail_up.sh; tests/test_gmail.py; tests/test_trace.py; tests/test_invoice_demo.py; bench/results/CLAUDE_WITH_WITHOUT.md'),
    }
    for number,fields in updates.items():
        for name,(value,size) in fields.items():put(shape(prs.slides[number-1],name),value,size)
    cover=shape(prs.slides[0],"TextBox 1").text_frame
    cover.paragraphs[0].runs[0].font.size=Pt(60)
    cover.paragraphs[2].runs[0].font.size=Pt(28)
    # The template supplies this differentiator panel as an empty existing shape.
    # Fill its text area without adding/moving any shape or obscuring its label.
    panel=shape(prs.slides[3],'Shape 25')
    panel.text_frame.margin_top=Inches(.33)
    panel.text_frame.margin_bottom=Inches(.02)
    panel.text_frame.margin_left=Inches(.16)
    put(panel,'Not a text filter or allow-list: KAVACH checks where each value came from and what the call would change, then ties approval to that exact call.',10.5)
    template_slides=list(prs.slides)
    manifest=[]
    info={}
    for number,slide in enumerate(template_slides,1):
        narrative,sources=narratives[number]
        slide.notes_slide.notes_text_frame.text=narrative+'\n\nEvidence: '+sources
        info[slide.slide_id]={'title':shape(slide,'Text 0').text if number in range(2,8) else 'KAVACH' if number==1 else 'DEMO','evidence':sources,'notes':narrative,'fields':{n:v[0] for n,v in updates[number].items()}}
    arch_slide=template_slides[4]
    # The three added slides, placed right after the template slide each one extends.
    arch=add_like(prs,arch_slide,'System Architecture','Every tool call passes through five stages. What KAVACH can guarantee depends on who runs the tool.',5)
    pic=arch.shapes.add_picture(str(ROOT/'docs/diagrams/architecture.png'),Inches(.5),Inches(1.08),width=Inches(12.3))
    pic._element.nvPicPr.cNvPr.set('descr','Architecture flowchart: agent, way in, KAVACH gateway stages, what the verdict does, proof and control.')
    for i,(head,body) in enumerate([('Rules sit outside the model','a hijacked agent can’t talk its way past them, and AI can only add caution.'),
                                    ('Receipt before action','no durable record, no action. Each receipt is signed and chained.'),
                                    ('One engine, many ways in','holds and undo apply when KAVACH runs the tool; when a host runs it, those stay the host’s job.')]):
        note_box(arch,.5+i*4.15,5.3,4.0,.92,f'{head}: {body}',10.5)
    arch_notes=('Walk left to right. An agent proposes a tool call; it reaches KAVACH through /mcp, where KAVACH also runs the tool, or through the proxy, REST check, SDK adapters or AgentOS hooks, where the host runs it. The gateway first checks the kill switch, then traces each argument, works out the effect, applies the deterministic rules and adds intent and risk. The verdict and signed receipt come before anything runs. Only rules and the kill switch can deny; models can only add caution. By default the Qualcomm judge adds a note on escalated calls.')
    arch_src='kavach/gateway.py; provenance.py; consequence.py; policy.py; receipts.py; server.py; docs/diagrams/architecture.mmd'
    arch.notes_slide.notes_text_frame.text=arch_notes+'\n\nEvidence: '+arch_src
    comp=add_like(prs,arch_slide,'How KAVACH Compares','Each approach solves part of the problem. KAVACH combines the checks at the tool call.',7)
    grid(comp,[dc.HEAD]+dc.ROWS,.5,1.02,[4.2,1.35,1.35,1.35,1.35,1.35,1.35],.335,9.5,marks=True,highlight=len(dc.ROWS))
    note_box(comp,.5,4.68,12.3,.68,dc.USP,11,fill='F1ECFB',edge='5B3FA8',bold=True)
    note_box(comp,.5,5.42,12.3,.86,dc.LEGEND,9)
    comp.notes_slide.notes_text_frame.text=dc.COMPARE_NOTES+'\n\nEvidence: '+dc.COMPARE_SOURCES
    aos=add_like(prs,arch_slide,'Infosys AgentOS and KAVACH','AgentOS is Infosys’s own agent runtime. We read and ran its code. KAVACH plugs into it; it does not replace it.',8)
    grid(aos,[dc.AGENTOS_HEAD]+dc.AGENTOS_ROWS,.5,1.02,[1.3,3.5,3.5],.56,10)
    pc=lambda v:f'{100*v:.1f}%'
    measured=[['Same suite, 282 test cases','Unsafe allowed','Safe work done','Sent to a person']]+[[label,pc(infosys[k]['UAR']),pc(infosys[k]['safe_auto']),pc(infosys[k]['escalation_rate'])] for k,label in dc.AGENTOS_KEYS]
    grid(aos,measured,8.95,1.02,[1.3,.85,.85,.85],.5,9.5,highlight=3)
    note_box(aos,8.95,3.1,3.85,1.84,'Hardening the AgentOS gate stops the injection attacks (0% success), but sends most actions to a person, which risks approval fatigue. On this suite KAVACH asks far less often, because it knows each call’s origin and effect. Suite written by our team, seed 0; Infosys gate code loaded and run locally.',10)
    note_box(aos,.5,5.05,12.3,1.2,dc.AGENTOS_BAND,10.5,fill='F1ECFB',edge='5B3FA8')
    aos.notes_slide.notes_text_frame.text=dc.AGENTOS_NOTES+'\n\nEvidence: '+dc.AGENTOS_SOURCES
    for slide,title,notes,src,fields in [(arch,'System Architecture',arch_notes,arch_src,{'cells':'diagram'}),(comp,'How KAVACH Compares',dc.COMPARE_NOTES,dc.COMPARE_SOURCES,{'usp':dc.USP}),(aos,'Infosys AgentOS and KAVACH',dc.AGENTOS_NOTES,dc.AGENTOS_SOURCES,{'band':dc.AGENTOS_BAND})]:
        info[slide.slide_id]={'title':title,'added':True,'evidence':src,'notes':notes,'fields':fields}
    for number,slide in enumerate(prs.slides,1):
        manifest.append({'slide':number,**info[slide.slide_id]})
    props=prs.core_properties;props.title='KAVACH Solution Presentation';props.author='Team Kavach';props.last_modified_by='Team Kavach';props.comments=''
    path=OUT/'KAVACH_Solution_Deck.pptx';prs.save(path);strip_authoring_dates(path)
    (OUT/'review/template_slide_manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
    explanation(manifest,tests,safe,unsafe)
    print(f'Filled original Infosys template: {len(prs.slides)} slides (8 template + 3 added); original shape geometry and branding retained.')


def explanation(manifest,tests,safe,unsafe):
    lines=['# KAVACH solution deck: template correction and content changes','',
      'The main `KAVACH_Solution_Deck.pptx` now fills the actual eight-slide Infosys template supplied at `/home/vismay-hs/Hack-AI-Thon_Solution_Presentation_Template.pptx`. Three slides are added in the template’s style: the architecture diagram, the comparison with USP, and AgentOS. The earlier redesign followed the template’s subjects but did not follow its layouts exactly. That redesign is retained separately as `KAVACH_Verified_Reference_Deck.pptx` and `.pdf`; it is not the template submission.','',
      'The official template’s slide order, slide sizes, headings, shape positions, logos, colours, original images and branding are preserved. On template slides only content fields, related speaker notes and authoring metadata are changed. Template helper text is replaced with real subtitles and the suggested-time labels are emptied, with their shapes left in place; no work dates or authoring timestamps are added. The demo divider remains the original DEMO slide, with the verified demonstration script in its speaker notes.','',
      'Team information was supplied by the user: Team Kavach; PES University, Bengaluru; Vismay H S, Ashwin C H and Dhanush S R. These details are not inferred from git or fabricated.','',
      '## Content compared with the original solution deck','',
      '- Rule catalogue expanded; slides no longer quote rule numbers or a rule count. Synthetic suite: 740 / 37 → 940 scenarios / 47 families.',
      f'- Saved synthetic safe automation: 68% → {safe}; unsafe auto-allowed: 0.5% → {unsafe}. Both revised rates are explicitly limited to the team-authored synthetic suite.',
      '- Learned model: supporting signal; risk-zero ablation changes no suite verdict. Default judge: escalation advice; template explanations default.',
      '- Undo: operation-specific local snapshots, holds or parking, not a blanket promise. REST check is decision-only by default; external proxy/SDK execution does not inherit local undo.',
      '- Approval: bound to the stored task, tool and arguments, one-use and expiring. Full policy/tool-definition checks are not repeated at approval time.',
      f'- Validation: {tests}; per-test outcomes and skip reasons retained. Optional features and unproven production readiness remain qualified.',
      '- Future work: CI, load/restore tests, alert delivery and broader evaluations; no unsupported hardware or horizontal-scaling claim.',
      '- AgentDojo headline counts are on slide 4; full live benchmarking stays in the separate reference deck, labelled saved aggregate evidence. Raw live-task logs are absent here, so those external runs were not independently revalidated.','',
      '## Slide-by-slide explanation','']
    for item in manifest:
        lines.extend([f'### Slide {item["slide"]}: {item["title"]}','',item['notes'],'','**Evidence:** '+item['evidence'], ''])
    lines.extend(['## Review artifacts','',
      '- `KAVACH_Claim_Verification.md`: submission-template fidelity and eight-slide claim register.',
      '- `KAVACH_Reference_Deck_Explanation.md`: detailed repository walkthrough and reference deck explanation.',
      '- `KAVACH_Reference_Claim_Verification.md`: detailed reference source audit and numeric checks.',
      '- `review/test_results.json`: test outcomes and skip reasons.',
      '- `before_update/`: unchanged original solution deck and its generator.','',
      '## Rebuild','', '```bash','.venv/bin/python scripts/build_deck.py','.venv/bin/python scripts/export_deck.py','.venv/bin/python scripts/validate_template_deck.py','```',''])
    (OUT/'KAVACH_Deck_Update_Explanation.md').write_text('\n'.join(lines))

if __name__=='__main__':build()
