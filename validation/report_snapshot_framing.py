"""Recompose retained three-engine report snapshots without scientific workers."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from unittest.mock import patch


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--compositor', type=Path, required=True,
                        help='Staged installed renderer with only the tested panel-fit correction')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    project = Path(__file__).resolve().parents[1]
    baseline = project / 'validation/runs/mac-all-engine-gui-20261022-native-b'
    runtime = Path('/opt/anaconda3/envs/docking-universal/libexec/docking-universal')
    sys.path.insert(0, str(runtime))
    figures = load('fixed_snapshot_compositor', args.compositor.resolve())
    report = load('installed_snapshot_pdf', runtime / 'docking-universal-pdf-report.py')
    original_run = subprocess.run
    source_files = {str(p): digest(p) for engine in ('vina', 'qvinaw', 'adgpu')
                    for p in (baseline / engine / 'screen').rglob('*') if p.is_file()}
    record = dict(status='running', scientific_searches=0, plip_recomputations=0,
                  cases=[], compositor=str(args.compositor.resolve()))

    def retained_only(command, *a, **kw):
        if len(command) > 1 and Path(str(command[1])).name == 'docking-universal-report-figures.py':
            return subprocess.CompletedProcess(command, 0, 'Retained figures reused; snapshot panels already recomposed', '')
        if list(command) == [sys.executable, '-c', 'from pymol import cmd; print(cmd.get_version()[0])']:
            return original_run(command, *a, **kw)
        if list(command) in ([str(Path(sys.executable).resolve().parent / 'obabel'), '-V'],
                             [str(Path(sys.executable).resolve().parent / 'node'), '--version'], ['node', '--version']):
            return original_run(command, *a, **kw)
        raise AssertionError('Unexpected external worker in render-only check: ' + str(command))

    try:
        for engine in ('vina', 'qvinaw', 'adgpu'):
            root = out / engine
            study = root / 'screen'
            shutil.copytree(baseline / engine / 'screen', study)
            panels = []
            for compound in sorted((study / 'compounds').iterdir()):
                analysis = compound / 'pose_analysis'
                rows = figures.cluster_rows(analysis)[:3]
                if not rows:
                    raise ValueError('Missing retained representatives')
                output = study / 'report' / (compound.name + '_top3_3d_snapshots.png')
                if not figures.combine_cluster_snapshots(analysis, rows, output):
                    raise AssertionError('Snapshot composition failed')
                panels.append(str(output))
            if len(panels) != 2:
                raise AssertionError('Expected both compound panels')
            original_pdf = next(p for p in (study / 'report').glob('*docking_report.pdf'))
            pdf = root / (engine + '-corrected-report.pdf')
            with patch.object(report.subprocess, 'run', side_effect=retained_only), \
                 patch.object(sys, 'argv', ['pdf-report', str(study), '--out', str(pdf)]):
                report.main()
            def pdf_text(path):
                return original_run(['/opt/homebrew/bin/pdftotext', '-layout', str(path), '-'],
                                    capture_output=True, text=True, check=True).stdout
            if ''.join(pdf_text(original_pdf).split()) != ''.join(pdf_text(pdf).split()):
                raise AssertionError('Report text or numerical values changed during image-only correction')
            original_run(['/opt/homebrew/bin/pdftoppm', '-scale-to', '1500', '-png', str(pdf),
                          str(root / 'page')], capture_output=True, check=True)
            record['cases'].append(dict(engine=engine, status='passed', pdf=str(pdf),
                                        panels=panels, report_text_and_values_unchanged=True))
        if any(digest(path) != value for path, value in source_files.items()):
            raise AssertionError('Original completed acceptance results changed')
        record.update(status='passed_awaiting_visual_review', original_files_hash_verified=len(source_files))
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
        raise
    finally:
        (out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')


if __name__ == '__main__':
    main()
