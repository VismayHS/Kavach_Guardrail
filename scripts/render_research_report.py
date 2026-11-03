"""Render the local research report to a readable PDF without authoring timestamps.

Uses the existing Playwright Chromium installation and pypdf. The Markdown is the
source; headings, simple tables, links, lists, quotes and code blocks are supported.
"""
import html
import argparse
import re
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright
from pypdf import PdfReader,PdfWriter

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'deliverables/research'

def inline(s):
    safe=html.escape(s)
    safe=re.sub(r'\[([^\]]+)\]\(([^)]+)\)',r'<a href="\2">\1</a>',safe)
    safe=re.sub(r'`([^`]+)`',r'<code>\1</code>',safe)
    safe=re.sub(r'\*\*([^*]+)\*\*',r'<strong>\1</strong>',safe)
    return safe

def markup(source):
    lines=source.splitlines();out=[];i=0
    while i<len(lines):
        line=lines[i]
        if not line.strip():i+=1;continue
        if line.startswith('```'):
            block=[];i+=1
            while i<len(lines) and not lines[i].startswith('```'):block.append(lines[i]);i+=1
            out.append('<pre>'+html.escape('\n'.join(block))+'</pre>');i+=1;continue
        if line.startswith('|'):
            rows=[]
            while i<len(lines) and lines[i].startswith('|'):
                cells=[c.strip() for c in lines[i].strip().strip('|').split('|')]
                if not all(re.fullmatch(r':?-+:?',c) for c in cells):rows.append(cells)
                i+=1
            table_class=' class="compact"' if len(rows)<=4 else ''
            out.append('<table'+table_class+'><thead><tr>'+''.join('<th>'+inline(c)+'</th>' for c in rows[0])+'</tr></thead><tbody>')
            out.extend('<tr>'+''.join('<td>'+inline(c)+'</td>' for c in r)+'</tr>' for r in rows[1:]);out.append('</tbody></table>');continue
        if line.startswith('#'):
            level=len(line)-len(line.lstrip('#'));out.append(f'<h{level}>'+inline(line[level:].strip())+f'</h{level}>');i+=1;continue
        if line.startswith('> '):out.append('<blockquote>'+inline(line[2:])+'</blockquote>');i+=1;continue
        if line.startswith('- ') or re.match(r'^\d+\. ',line):
            ordered=bool(re.match(r'^\d+\. ',line));tag='ol' if ordered else 'ul';out.append('<'+tag+'>')
            while i<len(lines) and ((ordered and re.match(r'^\d+\. ',lines[i])) or (not ordered and lines[i].startswith('- '))):
                value=re.sub(r'^\d+\. ','',lines[i]) if ordered else lines[i][2:]
                out.append('<li>'+inline(value)+'</li>');i+=1
            out.append('</'+tag+'>');continue
        para=[line];i+=1
        while i<len(lines) and lines[i].strip() and not lines[i].startswith(('#','|','- ','> ','```')):
            para.append(lines[i]);i+=1
        out.append('<p>'+inline(' '.join(para))+'</p>')
    return '\n'.join(out)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--stem',default='KAVACH_USP_Research')
    parser.add_argument('--title',default='KAVACH: USP and Infosys Gap Research')
    args=parser.parse_args()
    text=(OUT/f'{args.stem}.md').read_text()
    style='''@page{size:A4;margin:17mm 15mm}body{font:10.5pt/1.48 "Noto Sans",sans-serif;color:#1c2433}h1{font-size:24pt;color:#472f8a;line-height:1.2}h2{font-size:16pt;color:#472f8a;margin-top:25pt;break-after:avoid}h3{font-size:12pt;margin-top:17pt;break-after:avoid}p,li{orphans:3;widows:3}a{color:#00639c;text-decoration:none;overflow-wrap:anywhere}code{font:9pt/1.4 monospace;overflow-wrap:anywhere}table{border-collapse:collapse;width:100%;margin:14pt 0;font-size:9pt}th,td{border:1px solid #d8dbd3;text-align:left;vertical-align:top;padding:6pt;overflow-wrap:anywhere}th{background:#efebf8;color:#472f8a}thead{display:table-header-group}th:first-child,td:first-child{min-width:64px}tr{break-inside:avoid}blockquote{margin:14pt 0;padding:10pt 13pt;border-left:4pt solid #5b3fa8;background:#f4f3f8}pre{font:8.7pt/1.35 monospace;background:#f4f5f2;padding:12pt;white-space:pre-wrap;break-inside:avoid}li{margin-bottom:5pt}'''
    style+='table.compact{break-inside:avoid}'
    document='<!doctype html><html><head><meta charset="utf-8"><title>'+html.escape(args.title)+'</title><style>'+style+'</style></head><body>'+markup(text)+'</body></html>'
    (OUT/f'{args.stem}.html').write_text(document)
    with tempfile.TemporaryDirectory(prefix='kavach-research-pdf-') as folder:
        raw=Path(folder)/'raw.pdf'
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            page=browser.new_page();page.set_content(document,wait_until='networkidle');page.pdf(path=str(raw),format='A4',print_background=True,prefer_css_page_size=True);browser.close()
        reader=PdfReader(raw);writer=PdfWriter();writer.append_pages_from_reader(reader)
        writer.add_metadata({'/Title':args.title,'/Author':'Team Kavach','/Subject':'Official source review and local evidence'})
        with (OUT/f'{args.stem}.pdf').open('wb') as f:writer.write(f)
        print('Rendered',len(reader.pages),'pages')

if __name__=='__main__':main()
