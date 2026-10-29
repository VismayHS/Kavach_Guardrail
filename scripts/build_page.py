"""Build the shareable blueprint page (docs/KAVACH_Blueprint.html) from the markdown docs + results."""
import base64, io, json, re
from pathlib import Path
import markdown
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
MS = json.loads((ROOT / "bench/results/multiseed.json").read_text())
RES = json.loads((ROOT / "bench/results/results.json").read_text())


def data_uri(path, max_w=1800, jpeg=False):
    im = Image.open(path).convert("RGB")
    if im.width > max_w:
        im = im.resize((max_w, int(im.height * max_w / im.width)), Image.LANCZOS)
    buf = io.BytesIO()
    if jpeg:
        im.save(buf, "JPEG", quality=82, optimize=True); mime = "image/jpeg"
    else:
        im.save(buf, "PNG", optimize=True); mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def md(text):
    html = markdown.markdown(text, extensions=["tables", "fenced_code", "sane_lists"])
    html = html.replace("<table>", '<div class="tw"><table>').replace("</table>", "</table></div>")
    html = html.replace("<pre>", '<div class="cw"><pre>').replace("</pre>", "</pre></div>")
    return html


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40]


def sections(html, prefix):
    toc = []
    def rep(m):
        lvl, inner = m.group(1), m.group(2)
        text = re.sub("<[^>]+>", "", inner)
        sid = prefix + slug(text)
        if lvl == "2":
            toc.append((sid, text))
        return f'<h{lvl} id="{sid}">{inner}</h{lvl}>'
    return re.sub(r"<h([23])>(.*?)</h\1>", rep, html), toc


bp = (ROOT / "docs/BLUEPRINT.md").read_text()
au = (ROOT / "docs/AUDIT_OF_EXISTING_DOCS.md").read_text()
bp = bp.split("\n", 2)[2]                      # drop H1 + H3 subtitle (page header replaces them)
au = au.split("\n", 1)[1]
bp = bp.replace("![Architecture](img/architecture.png)", f'<figure><img src="{data_uri(ROOT/"docs/img/architecture.png")}" alt="KAVACH architecture: agent, eight gateway stages, allow / escalate / deny outcomes"></figure>')
bp = bp.replace("![Decision procedure](img/decision_flow.png)", f'<figure><img src="{data_uri(ROOT/"docs/img/decision_flow.png")}" alt="Decision procedure, first match wins"></figure>')
bp = bp.replace("**Results:** see `bench/results/RESULTS.md`",
                f'<figure><img src="{data_uri(ROOT/"bench/results/pareto.png", 1100)}" alt="Pareto chart: friction vs unsafe actions auto-allowed"></figure>\n\n**Results:** see `bench/results/RESULTS.md`')
bp = bp.replace("## 12. Demo script", f'<figure><img src="{data_uri(ROOT/"docs/img/dash_injection.png", 1500, jpeg=True)}" alt="KAVACH dashboard: injected email exfiltration denied by rule R1"><figcaption>Dashboard: the injected send is denied by R1; the recipient traces to msg-4471.</figcaption></figure>\n\n## 12. Demo script')
au_html, au_toc = sections(md(au), "a-")
bp_html, bp_toc = sections(md(bp), "b-")

rows = ""
for name, m in MS["systems"].items():
    hl = ' class="hl"' if name == "KAVACH (full)" else ""
    rows += (f"<tr{hl}><td>{name}</td><td>{m['UAR']['mean']*100:.1f}%</td><td>{m['ASR_injection']['mean']*100:.1f}%</td>"
             f"<td>{m['safe_auto']['mean']*100:.1f}%</td><td>{m['escalation_rate']['mean']*100:.1f}%</td></tr>")
full = MS["systems"]["KAVACH (full)"]
lat = next(s for s in RES["systems"] if s["system"] == "KAVACH (full)")
toc_html = ('<p class="tl">Audit of current docs</p>' + "".join(f'<a href="#{i}">{t}</a>' for i, t in au_toc) +
            '<p class="tl">Blueprint</p>' + "".join(f'<a href="#{i}">{t}</a>' for i, t in bp_toc))

page = f"""<title>KAVACH Blueprint</title>
<meta name="claude:viewport-fit-sides" content="cover">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700;800&family=Source+Sans+3:ital,wght@0,400;0,600;0,700;1,400&family=JetBrains+Mono:wght@400;600&display=swap">
<style>
/* layout: masthead with measured verdict strip, then sticky contents rail + reading column */
:root {{
  --bg:#f7f6f2; --paper:#ffffff; --ink:#18202e; --muted:#5d6676; --line:#e2e0d8;
  --accent:#9a5b13; --accent-soft:#f4e9da; --navy:#13294b;
  --ok:#2f7d4f; --warn:#b26a12; --bad:#b83a32; --code:#f1efe9;
  --f-display:"Archivo", "Helvetica Neue", Arial, sans-serif;
  --f-body:"Source Sans 3", "Segoe UI", system-ui, sans-serif;
  --f-mono:"JetBrains Mono", ui-monospace, Menlo, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg:#12151b; --paper:#191d25; --ink:#e7e9ee; --muted:#9aa3b2; --line:#2a303c;
  --accent:#e0a35a; --accent-soft:#2b241b; --navy:#a9c2ea; --ok:#5fbf86; --warn:#e2a24c; --bad:#ef7a6f; --code:#20252f; color-scheme:dark }} }}
:root[data-theme="dark"] {{
  --bg:#12151b; --paper:#191d25; --ink:#e7e9ee; --muted:#9aa3b2; --line:#2a303c;
  --accent:#e0a35a; --accent-soft:#2b241b; --navy:#a9c2ea; --ok:#5fbf86; --warn:#e2a24c; --bad:#ef7a6f; --code:#20252f; color-scheme:dark }}
* {{ box-sizing:border-box }}
body {{ background:var(--bg); color:var(--ink); font:17px/1.6 var(--f-body);
  padding-left:max(16px, env(safe-area-inset-left, 0px)); padding-right:max(16px, env(safe-area-inset-right, 0px)) }}
.wrap {{ max-width:1180px; margin:0 auto; padding-block:28px 64px }}
header.mast {{ border-bottom:2px solid var(--ink); padding-bottom:18px; margin-bottom:22px }}
.eyebrow {{ font:600 12px/1 var(--f-mono); letter-spacing:.12em; text-transform:uppercase; color:var(--accent) }}
h1 {{ font:800 clamp(34px,6vw,58px)/1.02 var(--f-display); margin:10px 0 8px; letter-spacing:-.01em; text-wrap:balance; color:var(--navy) }}
.lede {{ font-size:19px; max-width:62ch; margin:0; color:var(--ink) }}
.lede b {{ color:var(--accent) }}
.strip {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:1px; background:var(--line); border:1px solid var(--line); margin:22px 0 8px }}
.strip div {{ background:var(--paper); padding:14px 16px }}
.strip b {{ display:block; font:700 28px/1.1 var(--f-display); font-variant-numeric:tabular-nums }}
.strip span {{ font-size:13.5px; line-height:1.4; display:block; color:var(--muted) }}
.note {{ font-size:13.5px; color:var(--muted); margin:0 0 6px }}
.grid {{ display:grid; grid-template-columns:230px minmax(0,1fr); gap:40px; align-items:start }}
nav.toc {{ position:sticky; top:calc(env(safe-area-inset-top, 0px) + 16px); max-height:calc(100vh - 32px); overflow:auto; font-size:14px; border-left:2px solid var(--line); padding-left:14px }}
nav.toc .tl {{ font:600 11px/1 var(--f-mono); letter-spacing:.1em; text-transform:uppercase; color:var(--muted); margin:16px 0 8px }}
nav.toc a {{ display:block; color:var(--ink); text-decoration:none; padding:3px 0; line-height:1.3; overflow-wrap:anywhere }}
nav.toc a:hover, nav.toc a:focus-visible {{ color:var(--accent); outline:none; text-decoration:underline }}
main {{ min-width:0 }}
.part {{ background:var(--paper); border:1px solid var(--line); padding:8px clamp(16px,3vw,36px) 28px; margin-bottom:28px }}
.part > .ph {{ font:700 13px/1 var(--f-mono); letter-spacing:.12em; text-transform:uppercase; color:var(--accent); margin:22px 0 0 }}
h2 {{ font:700 26px/1.2 var(--f-display); margin:34px 0 10px; color:var(--navy); text-wrap:balance; scroll-margin-top:16px }}
h3 {{ font:700 19px/1.3 var(--f-display); margin:24px 0 6px; scroll-margin-top:16px }}
p, li {{ max-width:72ch }}
a {{ color:var(--accent) }}
blockquote {{ margin:16px 0; padding:10px 16px; border-left:3px solid var(--accent); background:var(--accent-soft) }}
blockquote p {{ margin:4px 0 }}
code {{ font:13.5px var(--f-mono); background:var(--code); padding:1px 5px; border-radius:3px }}
.cw {{ overflow-x:auto; margin:12px 0 }}
pre {{ background:var(--code); padding:14px 16px; margin:0; font:12.5px/1.5 var(--f-mono); border:1px solid var(--line) }}
pre code {{ background:none; padding:0; font-size:12.5px }}
.tw {{ overflow-x:auto; margin:12px 0 18px }}
table {{ border-collapse:collapse; width:100%; font-size:14.5px; font-variant-numeric:tabular-nums }}
th {{ text-align:left; font:600 12.5px/1.3 var(--f-body); text-transform:uppercase; letter-spacing:.05em; color:var(--muted); border-bottom:2px solid var(--ink); padding:8px 10px }}
td {{ border-bottom:1px solid var(--line); padding:8px 10px; vertical-align:top }}
tr.hl td {{ background:var(--accent-soft); font-weight:700 }}
figure {{ margin:18px 0; background:#fff; border:1px solid var(--line); padding:8px }}
figure img {{ display:block; width:100%; height:auto }}
figcaption {{ font-size:13px; color:#5d6676; padding:6px 4px 0 }}
hr {{ border:0; border-top:1px solid var(--line); margin:28px 0 }}
@media (max-width:900px) {{ .grid {{ grid-template-columns:1fr }} nav.toc {{ position:static; max-height:none; border-left:0; padding-left:0; border-top:1px solid var(--line) }} }}
@media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior:auto !important }} }}
html {{ scroll-behavior:smooth }}
</style>
<div class="wrap">
<header class="mast">
  <div class="eyebrow">ET-03 · Agentic AI Guardrail Validator · Infosys IGNITE ENG NEXT 2026</div>
  <h1>KAVACH Blueprint</h1>
  <p class="lede">A pre-execution action firewall for AI agents. It measures what an action will <b>actually do</b>, traces <b>where every argument came from</b>, and decides with <b>calibrated confidence</b> whether to allow, allow with undo, ask a human or block. The LLM never makes the decision.</p>
  <div class="strip">
    <div><b>{full['UAR']['mean']*100:.1f}%</b><span>unsafe actions auto-allowed (rules alone: {MS['systems']['KAVACH: rules only']['UAR']['mean']*100:.0f}%)</span></div>
    <div><b>{full['ASR_injection']['mean']*100:.0f}%</b><span>prompt-injection attacks that succeeded</span></div>
    <div><b>{full['safe_auto']['mean']*100:.0f}%</b><span>safe actions done with no human (approve-every-write: {MS['systems']['Approve every write (manual interrupt)']['safe_auto']['mean']*100:.0f}%)</span></div>
    <div><b>{lat['latency_p50_ms']:.1f} ms</b><span>median decision time without the LLM (p95 {lat['latency_p95_ms']:.1f} ms)</span></div>
  </div>
  <p class="note">Mean of {len(MS['seeds'])} seeds on a held-out split of {RES['suite']['scenarios']} synthetic labelled scenarios ({RES['suite']['families']} families). Not comparable with numbers published on AgentDojo or AmPermBench. Code and deck: github.com/VismayHS/Kavach_Guardrail</p>
</header>
<div class="grid">
<nav class="toc" aria-label="Contents">{toc_html}</nav>
<main>
<section class="part"><p class="ph">Part 1 · Where the team stands</p>{au_html}</section>
<section class="part"><p class="ph">Part 2 · What to build and why</p>
<h2 id="b-results-table">All systems at a glance</h2>
<div class="tw"><table><thead><tr><th>System</th><th>Unsafe auto-allowed</th><th>Injection ASR</th><th>Safe auto-completed</th><th>Escalation</th></tr></thead><tbody>{rows}</tbody></table></div>
{bp_html}</section>
</main></div></div>
"""
out = ROOT / "docs" / "KAVACH_Blueprint.html"
out.write_text(page)
print(out, round(len(page) / 1e6, 2), "MB")
