"""Rebuild a PDF-only presentation revision from retained, unchanged figures."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=ROOT/'validation/runs/adgpu-integration-20261016/gui-ready/screen-source')
    parser.add_argument('--run-directory',type=Path,default=ROOT/'validation/runs/report-protocol-options-20261016')
    parser.add_argument('--output',type=Path,default=ROOT/'output/pdf/2R8N-docking-report-protocol-options.pdf')
    parser.add_argument('--compact-results',action='store_true')
    parser.add_argument('--score-beside-result',action='store_true')
    args = parser.parse_args()
    source = args.source.resolve()
    destination = args.run_directory.resolve()
    destination.mkdir(exist_ok=False)
    study = destination / 'study'
    study.mkdir()
    before = {str(path): digest(path) for path in source.rglob('*') if path.is_file()}
    for path in source.iterdir():
        if path.name == 'report':
            shutil.copytree(path, study / path.name, ignore=shutil.ignore_patterns('*.pdf'))
        else:
            (study / path.name).symlink_to(path, target_is_directory=path.is_dir())
    spec = importlib.util.spec_from_file_location('protocol_options_report', ROOT / 'libexec/docking-universal-pdf-report.py')
    report = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(report)
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Report revision already exists')
    run = subprocess.run
    reused = []

    def retained_figures(command, *args, **kwargs):
        if len(command) > 1 and Path(command[1]).name == 'docking-universal-report-figures.py':
            # The production builder regenerates composite figures. This
            # presentation-only check explicitly reuses accepted figures.
            reused.append(command)
            return subprocess.CompletedProcess(command, 0, 'Retained figures reused', '')
        return run(command, *args, **kwargs)

    with patch.object(sys, 'argv', [str(spec.origin), str(study), '--out', str(output)]), \
            patch.object(report.subprocess, 'run', side_effect=retained_figures):
        report.main()
    assert len(reused) == 1
    assert all(digest(Path(path)) == value for path, value in before.items())
    text = run(['/opt/homebrew/bin/pdftotext', str(output), '-'], text=True, capture_output=True, check=True).stdout
    section = text.split('Configured docking protocol', 1)[1].split('Ligand docking results', 1)[0]
    for option in ('Docking program', 'Ligand preparation pH', 'Starting shapes per chemical state',
                   'Independent repeats per shape', 'Starting random seed',
                   'Genetic runs per repeat', 'Heuristic evaluation cap'):
        assert option in section, option
    for excluded in ('Approval provenance', 'Protocol creation date', 'Population', 'Local iterations',
                     'Saved poses', 'Input limits', 'actual AD4 grid', 'gasteiger', 'MMFF94'):
        assert excluded not in section, excluded
    assert 'actual AD4 grid' in text and '26.25' in text
    if args.compact_results:
        for excluded in ('Independent-seed support','Conformer support','Selected representatives'):
            assert excluded not in text, excluded
        assert 'Distinct pose clusters' in text
    if args.score_beside_result:
        assert 'Scoring function' not in section
        assert text.count('Scoring function') == 3
        assert 'Best docking score Scoring function' in ' '.join(text.split())
    result = {'status': 'passed', 'pdf': str(output), 'pdf_sha256': digest(output),
              'only_selectable_protocol_options': True, 'original_study_files_unchanged': len(before),
              'figures_reused': True, 'scientific_searches': 0, 'visual_review': 'pending'}
    (destination / 'summary.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
