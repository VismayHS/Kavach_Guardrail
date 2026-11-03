"""Export the solution deck using LibreOffice Impress and remove authoring dates.

Requires LibreOffice with Impress support, python-pptx and pypdf.
Usage: .venv/bin/python scripts/export_deck.py [--office-binary /path/to/soffice]
"""
import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'deliverables'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--office-binary', default=shutil.which('libreoffice') or shutil.which('soffice'))
    args = parser.parse_args()
    if not args.office_binary:
        raise SystemExit('LibreOffice with Impress support is required for the PDF export.')
    for name, title in [('KAVACH_Solution_Deck', 'KAVACH Solution Deck'),
                        ('KAVACH_Verified_Reference_Deck', 'KAVACH Reference Deck')]:
        with tempfile.TemporaryDirectory(prefix='kavach-deck-export-') as folder:
            temp = Path(folder)
            run = subprocess.run([args.office_binary, f'-env:UserInstallation={(temp / "profile").as_uri()}',
                                  '--headless', '--convert-to', 'pdf', '--outdir', folder,
                                  str(OUT / f'{name}.pptx')], capture_output=True, text=True, timeout=120)
            exported = temp / f'{name}.pdf'
            if run.returncode or not exported.exists():
                raise SystemExit('PDF export failed. Check that Impress is installed.\n' + run.stdout + run.stderr)
            reader = PdfReader(exported)
            writer = PdfWriter()
            writer.append_pages_from_reader(reader)
            writer.add_metadata({'/Title': title, '/Author': 'KAVACH',
                                 '/Subject': 'Repository-backed solution and evidence'})
            with (OUT / f'{name}.pdf').open('wb') as stream:
                writer.write(stream)
            print(f'{name}: exported {len(reader.pages)} pages with no authoring calendar properties.')

if __name__ == '__main__':
    main()
