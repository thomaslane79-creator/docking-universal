"""Compare an unaccepted host rebuild with retained synthetic installation runs.

No runtime acceptance/configuration is written. Same-current-host equivalence is
not evidence that older operating-system GPU drivers behave identically.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'libexec'))
from docking_universal.ad4_gpu import Ad4Settings, native_arguments, assemble_results


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build', required=True, type=Path)
    parser.add_argument('--fixture', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    build = json.loads(args.build.read_text())
    fixture = json.loads((args.fixture / 'summary.json').read_text())
    state = {'status': 'running', 'integration_accepted': False, 'production_installed': False,
        'scope': 'Candidate/reference equivalence on this host; older OS GPU acceptance still required',
        'candidate_sha256': build['executable_sha256'], 'runs': []}
    try:
        candidate = Path(build['executable'])
        if digest(candidate) != build['executable_sha256'] or fixture['status'] != 'passed':
            raise ValueError('Candidate changed or reference fixture did not pass')
        reference = args.fixture / 'repeat-0/butane_adgpu.pdbqt'
        if digest(reference) != fixture['runs'][0]['output_sha256']:
            raise ValueError('Reference output changed')
        template = args.fixture / 'ligands/butane.pdbqt'
        maps = (args.fixture / 'repeat-0/ad4_maps/receptor.maps.fld').resolve()
        state['input_sha256'] = {str(p): digest(p) for p in [template, *maps.parent.glob('receptor.*')] if p.is_file()}
        for repeat in range(2):
            folder = out / f'repeat-{repeat}'; folder.mkdir()
            shutil.copyfile(template, folder / 'ligand.pdbqt')
            command = native_arguments(candidate, maps, Ad4Settings(), 41001)
            with (folder / 'run.log').open('w') as log:
                subprocess.run(command, cwd=folder, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
            normalized = folder / 'normalized.pdbqt'
            record = assemble_results(folder, template, normalized, Ad4Settings())
            identical = normalized.read_bytes() == reference.read_bytes()
            state['runs'].append({'repeat': repeat, 'pose_count': len(record['poses']),
                'normalized_sha256': digest(normalized), 'exact_reference_match': identical})
            if not identical:
                raise ValueError('Candidate output differs from retained accepted-build output on this host')
        if any(digest(p) != h for p, h in state['input_sha256'].items()):
            raise ValueError('Retained input/map files changed')
        state['status'] = 'passed_on_current_host_only'
    except BaseException as exc:
        state.update(status='failed', error=str(exc))
    (out / 'summary.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps(state, indent=2))
    return 0 if state['status'] == 'passed_on_current_host_only' else 1


if __name__ == '__main__':
    raise SystemExit(main())
