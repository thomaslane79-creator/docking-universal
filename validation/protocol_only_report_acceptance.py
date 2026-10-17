"""Check standalone Vina/AD4 protocol reports without rerunning science."""
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from unittest.mock import patch

from autodock_gpu_trial import check_idle, digest
from report_sync_acceptance import MODULES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'validation/runs/protocol-only-reports-20261017_b'
SOURCES = {
    'vina': ROOT / 'validation/runs/report-target-identity-20261014.iUnTOs/retained-copy',
    'adgpu': ROOT / 'validation/runs/adgpu-integration-20261016/gui-ready/protocol',
}


def main():
    check_idle()
    OUT.mkdir(exist_ok=False)
    record = {'status': 'running', 'scientific_searches': 0, 'reports': {}}
    summary = OUT / 'summary.json'
    env = {**os.environ,
           'PATH': '/opt/anaconda3/envs/docking-universal/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin',
           'PYTHONPATH': str(ROOT / 'libexec') + ':' + str(ROOT / 'tests'),
           'MPLCONFIGDIR': str(OUT / 'matplotlib')}
    summary.write_text(json.dumps(record, indent=2) + '\n')
    try:
        tests = subprocess.run([sys.executable, '-m', 'unittest', *MODULES], env=env,
                               capture_output=True, text=True)
        (OUT / 'regressions.log').write_text(tests.stdout + '\n' + tests.stderr)
        record['regression_tests'] = int(re.search(r'Ran (\d+) tests', tests.stderr)[1])
        if tests.returncode:
            raise RuntimeError('Report/protocol regression failed; see regressions.log')
        spec = importlib.util.spec_from_file_location('protocol_only_pdf', ROOT / 'libexec/docking-universal-pdf-report.py')
        report = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(report)
        run = subprocess.run
        for engine, source in SOURCES.items():
            before = {str(path): digest(path) for path in source.rglob('*') if path.is_file()}
            study = OUT / engine
            shutil.copytree(source, study)
            pdf = study / 'report' / f'2R8N-{engine}-protocol-report.pdf'
            reused = []

            def retained_figures(command, *args, **kwargs):
                if len(command) > 1 and Path(str(command[1])).name == 'docking-universal-report-figures.py':
                    reused.append(command)
                    return subprocess.CompletedProcess(command, 0, 'Accepted pocket figures reused', '')
                return run(command, *args, **kwargs)

            with patch.object(sys, 'argv', [str(spec.origin), str(study), '--out', str(pdf)]), \
                    patch.object(report.subprocess, 'run', side_effect=retained_figures):
                report.main()
            text = run(['/opt/homebrew/bin/pdftotext', str(pdf), '-'],
                       capture_output=True, text=True, check=True).stdout
            normalized = ' '.join(text.split())
            for phrase in ('Reusable Exploratory Protocol', 'Source species: Human immunodeficiency virus 1',
                           'no screening ligands have been docked', 'No docking or interaction analysis was performed',
                           'Selected P2Rank score 2.49', 'Selected P2Rank probability 0.069'):
                assert phrase in normalized, (engine, phrase)
            for phrase in ('Ligand docking results', 'Best docking score', 'Independent-seed support',
                           'Population / max generations', 'Local iterations', 'Input limits',
                           'recorded in the protocol-selection report'):
                assert phrase not in text, (engine, phrase)
            settings = normalized.split('Configured docking protocol', 1)[1].split('Exploratory pocket configuration', 1)[0]
            assert 'Scoring function' not in settings
            if engine == 'adgpu':
                for phrase in ('AutoDock-GPU', 'AD4 estimated binding energies', 'Genetic runs per repeat',
                               'Heuristic evaluation cap', 'actual AD4 grid: 26.25 x 26.25 x 26.25'):
                    assert phrase in normalized, phrase
                assert 'Exhaustiveness' not in text and 'Modes per job' not in text
            else:
                for phrase in ('AutoDock Vina', 'Vina estimated binding energies', 'Exhaustiveness',
                               'Modes per job', 'Energy range'):
                    assert phrase in normalized, phrase
                assert 'Genetic runs per repeat' not in text and 'actual AD4 grid' not in text
            assert len(reused) == 1
            assert all(digest(Path(path)) == sha for path, sha in before.items())
            (OUT / f'{engine}-report.txt').write_text(text)
            record['reports'][engine] = {
                'pdf': str(pdf), 'sha256': digest(pdf), 'original_files_unchanged': len(before),
                'retained_figures_reused': True, 'visual_review': 'pending',
            }
        record['status'] = 'passed'
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
        raise
    finally:
        summary.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
