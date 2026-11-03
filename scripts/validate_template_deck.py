"""Verify that the submission fills the actual eight-slide Infosys template."""
import hashlib
import json
import re
import unicodedata
import zipfile
from pathlib import Path
from lxml import etree
from pptx import Presentation
from pypdf import PdfReader

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'deliverables'
SOURCE=Path('/home/vismay-hs/Hack-AI-Thon_Solution_Presentation_Template.pptx')
EXPECTED='cf3c95de665acf7ea6d19de8da6b617291dbe35a1a411058da860ce66fbc9126'

def walk(shapes):
    for sh in shapes:
        yield sh
        if sh.shape_type==6:yield from walk(sh.shapes)

def design(sh):
    node=sh._element.find("{http://schemas.openxmlformats.org/presentationml/2006/main}spPr")
    return etree.tostring(node) if node is not None else None

def norm(s):return re.sub(r'[^a-z0-9]','',unicodedata.normalize('NFKC',s).lower())

def main():
    source=SOURCE if SOURCE.exists() else OUT/'template_source.pptx'
    deck=OUT/'KAVACH_Solution_Deck.pptx'
    a=Presentation(source);b=Presentation(deck);pdf=PdfReader(OUT/'KAVACH_Solution_Deck.pdf')
    manifest=json.loads((OUT/'review/template_slide_manifest.json').read_text())
    tests=json.loads((OUT/'review/validation.json').read_text())
    checks=[];failures=[]
    def check(label,ok):
        checks.append({'check':label,'passed':bool(ok)})
        if not ok:failures.append(label)
    check('Actual supplied template SHA-256 matches',hashlib.sha256(source.read_bytes()).hexdigest()==EXPECTED)
    added=[m for m in manifest if m.get('added')]
    check('Eight template slides plus three added, and matching PDF pages',len(a.slides)==8 and len(added)==3 and len(b.slides)==len(pdf.pages)==len(manifest)==11)
    check('Slide dimensions identical',(a.slide_width,a.slide_height)==(b.slide_width,b.slide_height))
    with zipfile.ZipFile(source) as za,zipfile.ZipFile(deck) as zb:
        for prefix in ['ppt/media/','ppt/slideMasters/','ppt/slideLayouts/','ppt/theme/']:
            names=[n for n in za.namelist() if n.startswith(prefix)]
            check(prefix+' identical to supplied template',all(n in zb.namelist() and za.read(n)==zb.read(n) for n in names))
        core=etree.fromstring(zb.read('docProps/core.xml'))
        check('No added authoring calendar metadata',not core.xpath('//*[local-name()="created" or local-name()="modified" or local-name()="lastPrinted"]'))
    originals=iter(a.slides)
    for i,(filled,page,info) in enumerate(zip(b.slides,pdf.pages,manifest),1):
        if info.get('added'):
            rendered=norm(page.extract_text())
            lookup={s.name:s for s in filled.shapes}
            check(f'Slide {i}: added slide keeps the template title style and has its title',lookup['Text 0'].text==info['title'])
            words=[s.text_frame.text for s in filled.shapes if s.has_text_frame]+[c.text for s in filled.shapes if s.has_table for r in s.table.rows for c in r.cells]
            check(f'Slide {i}: added slide text appears in PDF',all(norm(w) in rendered for w in words if norm(w) and not w.isdigit()))
            check(f'Slide {i}: source-backed notes present','Evidence:' in filled.notes_slide.notes_text_frame.text)
            continue
        orig=next(originals)
        original=list(walk(orig.shapes));output=list(walk(filled.shapes));lookup={s.name:s for s in output}
        check(f'Slide {i}: original shape count preserved',len(original)==len(output))
        check(f'Slide {i}: original names, positions and sizes preserved',all((x.name,x.left,x.top,x.width,x.height)==(y.name,y.left,y.top,y.width,y.height) for x,y in zip(original,output)))
        check(f'Slide {i}: shape design properties preserved',all(design(x)==design(y) for x,y in zip(original,output)))
        if info['title'] not in ('KAVACH','DEMO'):check(f'Slide {i}: original required title preserved',lookup['Text 0'].text==next(s.text for s in original if s.name=='Text 0'))
        changed=set(info['fields'])|({'Shape 25'} if i==4 else set())
        check(f'Slide {i}: untouched labels preserved',all(x.text==y.text for x,y in zip(original,output) if x.has_text_frame and x.name not in changed))
        check(f'Slide {i}: no unfilled template placeholders',not any(re.search(r'\[(?:TEAM NAME|College|Name |Problem statement|UNO Q|Paste|Primary|Business|What |One |Our |User,|UI,|Model,|Dashboard|Languages|Why |How |Classification|Data/source|Accuracy|Time saved|Feature|Better|Usability|More users|Performance|Monitoring|Authentication|Privacy|Safety)',s.text) for s in output if s.has_text_frame))
        rendered=norm(page.extract_text())
        for name in changed:
            text=lookup[name].text
            check(f'Slide {i}: {name} filled text appears in PDF',norm(text) in rendered)
        check(f'Slide {i}: source-backed notes present','Evidence:' in filled.notes_slide.notes_text_frame.text)
        check(f'Slide {i}: no added work dates/timestamps',not re.search(r'\b20\d{2}\b|\b\d{1,2}:\d{2}\b',' '.join(str(v) for v in info['fields'].values())+info['notes']))
    check('Team details match user input',manifest[1]['fields']['Text 6']=='Team Kavach' and manifest[1]['fields']['Text 10']=='PES University, Bengaluru' and manifest[1]['fields']['Text 13']=='Vismay H S • Ashwin C H • Dhanush S R')
    check('Local test count retained',tests['tests']['passed']==521 and tests['tests']['skipped']==14)
    check('No rule IDs or rule ranges in slides or notes',not any(re.search(r'\bR\d+\b|_r\d+_',i['notes']+' '+i['evidence']+' '+str(i['fields']),re.I) for i in manifest))
    pics=sum(s.shape_type==13 for sl,m in zip(b.slides,manifest) if m.get('added') for s in sl.shapes)
    check('Exactly one diagram image added',pics==1)
    check('No template helper text left',not any(s.has_text_frame and re.search(r'SUGGESTED TIME|^Show the main|^Demonstrate meaningful|^Present a credible|WHAT TO SAY',s.text) for sl in b.slides for s in walk(sl.shapes)))
    check('No PDF authoring dates',not any(k in pdf.metadata for k in ['/CreationDate','/ModDate']))
    report={'template_sha256':EXPECTED,'submission_slides':11,'template_slides':8,'added_slides':3,'reference_slides':28,'authoring_dates_added':False,'original_template_branding_retained':True,'checks':checks,'failures':failures}
    (OUT/'review/template_validation.json').write_text(json.dumps(report,indent=2)+'\n')
    doc=['# KAVACH submission verification','',
      f'Template fidelity and filled-content checks: {len(checks)-len(failures)}/{len(checks)} passed. The main submission fills the supplied eight-slide Infosys template and adds three slides in its style; the 28-slide redesign is a separate reference deck.','',
      '## Template fidelity','',
      '- Original source: `/home/vismay-hs/Hack-AI-Thon_Solution_Presentation_Template.pptx`.',
      '- Template checksum: `'+EXPECTED+'`.',
      '- All eight template slides kept in order; dimensions, shape identities, positions, sizes and graphics retained. Three slides added: architecture diagram, comparison with USP, AgentOS.',
      '- All master, layout, theme and media package parts are byte-identical to the supplied template.',
      '- Team fields use the user-provided details; no identities were guessed.',
      '- No added work dates or authoring timestamps. Template branding is unchanged; helper text is replaced and suggested-time labels are emptied, with their shapes left in place.',
      '- The original DEMO divider is retained; the demonstration procedure is in its speaker notes.',
      '- Edited content is checked for presence in the exported PDF; source-backed notes are included.','',
      '## Claim evidence','',
      'The repository test result is 521 passed and 14 skipped. The detailed reference audit has 118 passing numeric-consistency/source checks. These do not independently reproduce external experiments. The primary submission retains only scoped implementation, test and synthetic/semantic findings, with sources in notes. Optional capabilities, simulations and production gaps remain qualified.','',
      'For exact source locations and per-test outcomes, read `KAVACH_Reference_Claim_Verification.md`, `review/claim_audit.json` and `review/test_results.json`.','']
    for item in manifest:doc.extend([f'### Slide {item["slide"]}: {item["title"]}','','**Sources:** '+item['evidence'],'',item['notes'],''])
    if failures:doc.extend(['## Failed checks','']+['- '+x for x in failures])
    (OUT/'KAVACH_Claim_Verification.md').write_text('\n'.join(doc)+'\n')
    print(f'{len(checks)-len(failures)}/{len(checks)} template/content checks passed')
    if failures:
        print('\n'.join(failures));raise SystemExit(1)

if __name__=='__main__':main()
