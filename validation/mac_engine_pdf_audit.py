"""Read-only report inspection after installed Mac engine GUI acceptance.

Render new PDFs locally for visual review; never regenerate reports or searches.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    args = parser.parse_args()
    root = args.run.resolve()
    summary = json.loads((root / 'summary.json').read_text())
    if summary['status'] != 'passed':
        raise ValueError('All three GUI cases must pass before final PDF audit')
    out = root / 'pdf-audit'
    out.mkdir(exist_ok=False)
    checks = []
    project = Path(__file__).resolve().parents[1]
    previous = project / 'validation/runs/mac-gui-doc-sync-20261022'
    protected = json.loads((previous / 'protected-before.json').read_text())
    installed = json.loads((previous / 'summary.json').read_text())['changed_application_files']
    expected = dict(protected)
    expected.update({path: row['after'] for path, row in installed.items()})
    model_source = project / 'libexec/docking_universal/gui/results_model.py'
    model_installed = '/opt/anaconda3/envs/docking-universal/libexec/docking-universal/docking_universal/gui/results_model.py'
    expected[model_installed] = hashlib.sha256(model_source.read_bytes()).hexdigest()
    mismatches = []
    for path, wanted in expected.items():
        current = hashlib.sha256(Path(path).read_bytes()).hexdigest() if Path(path).is_file() else None
        if current != wanted:
            mismatches.append(path)
    if mismatches:
        raise AssertionError('Unexpected protected-file changes: ' + str(mismatches))
    for case in summary['cases']:
        for kind in ('protocol_report', 'screening_report'):
            pdf = Path(case[kind])
            info = subprocess.run(['/opt/homebrew/bin/pdfinfo', str(pdf)], capture_output=True,
                                  text=True, check=True).stdout
            text = subprocess.run(['/opt/homebrew/bin/pdftotext', '-layout', str(pdf), '-'],
                                  capture_output=True, text=True, check=True).stdout
            if 'kcal/mol' not in text or ('AD4' if case['engine'] == 'adgpu' else 'Vina') not in text:
                raise AssertionError('Missing engine/units in ' + str(pdf))
            pages = int(next(line.split(':', 1)[1] for line in info.splitlines() if line.startswith('Pages:')))
            size = next(line for line in info.splitlines() if line.startswith('Page size:'))
            dims = size.split(':', 1)[1].split('pts')[0].strip().split(' x ')
            if float(dims[0]) >= float(dims[1]):
                raise AssertionError('Report is not portrait: ' + str(pdf))
            stem = case['engine'] + '-' + kind
            subprocess.run(['/opt/homebrew/bin/pdftoppm', '-scale-to', '1100', '-png', str(pdf),
                            str(out / stem)], capture_output=True, check=True)
            (out / (stem + '.txt')).write_text(text)
            checks.append(dict(engine=case['engine'], kind=kind, pdf=str(pdf), pages=pages,
                               portrait=True, units_and_model=True,
                               sha256=hashlib.sha256(pdf.read_bytes()).hexdigest()))
    record = dict(status='automated_checks_passed_visual_review_required', reports=checks,
                  protected_entries=len(expected), unexpected_protected_changes=mismatches,
                  missing_entries=[p for p in expected if not Path(p).is_file()],
                  installed_reader_matches_source=True)
    (out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
