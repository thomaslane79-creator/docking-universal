"""Native Windows CPU adapter check, not complete application acceptance.

Downloads only the pinned official executable. Synthetic fixtures are generated
on the runner. No study data, structural files or pose outputs are uploaded.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != 'Windows':
        parser.error('This validation must run natively on Windows, not a mocked platform or WSL')
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    asset = json.loads((ROOT / 'dependencies/vina-windows.json').read_text())
    state = {'status': 'running', 'system': platform.platform(), 'python': sys.executable,
             'scope': 'Synthetic prepared-input CPU adapter only; no native installer/preparation/GUI/GPU acceptance',
             'asset': asset, 'runs': []}
    try:
        with urllib.request.urlopen(asset['url'], timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != asset['sha256'] or data[:2] != b'MZ':
            raise ValueError('Official Windows Vina asset checksum/format mismatch')
        executable = out / asset['filename']; executable.write_bytes(data)
        version = subprocess.check_output([str(executable), '--version'], text=True, timeout=20).strip()
        if version != 'AutoDock Vina v1.2.7':
            raise ValueError('Native executable version does not match the pinned method')
        # Deliberately nonbiological prepared carbon fragments exercise native
        # execution only, not meaningful receptor chemistry or affinity.
        inputs = out / 'prepared inputs with spaces'; inputs.mkdir()
        receptor = inputs / 'receptor.pdbqt'
        receptor.write_text('ATOM      1  C   SYN A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n')
        ligands = inputs / 'ligands'; ligands.mkdir()
        (ligands / 'fragment.pdbqt').write_text('ROOT\n'
            'ATOM      1  C1  SYN A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n'
            'ATOM      2  C2  SYN A   1       1.500   0.000   0.000  1.00  0.00     0.000 C \n'
            'ENDROOT\nTORSDOF 0\n')
        box = inputs / 'box.conf'
        box.write_text('center_x = 0\ncenter_y = 0\ncenter_z = 0\nsize_x = 10\nsize_y = 10\nsize_z = 10\n')
        outputs = []
        for repeat in range(2):
            target = out / ('repeat ' + str(repeat))
            command = [sys.executable, str(ROOT / 'libexec/docking_universal_dock.py'),
                '--engine', 'vina', '--engine-command', str(executable), '--vina-backend', 'cli',
                '--receptor', str(receptor), '--ligands', str(ligands), '--config', str(box), '--out', str(target),
                '--seed', '41001', '--cpu', '1', '--exhaustiveness', '1', '--num-modes', '3']
            env = dict(os.environ, DOCKING_UNIVERSAL_PYTHON=sys.executable)
            with (out / f'adapter-{repeat}.log').open('w') as stream:
                subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=90)
            result = target / 'fragment_vina.pdbqt'
            content = result.read_bytes(); outputs.append(content)
            energies = [float(line.split()[3]) for line in content.decode().splitlines()
                        if line.startswith('REMARK VINA RESULT:')]
            if not energies or not all(math.isfinite(value) for value in energies):
                raise ValueError('Native CPU adapter did not retain finite Vina results')
            state['runs'].append({'repeat': repeat, 'poses': len(energies),
                'output_sha256': hashlib.sha256(content).hexdigest()})
        if outputs[0] != outputs[1]:
            raise ValueError('Same-seed native CPU synthetic repeats differ')
        state.update(status='passed', exact_same_seed_repeat=True, native_version=version)
    except BaseException as exc:
        state.update(status='failed', error=str(exc))
    (out / 'summary.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({k: state.get(k) for k in ('status', 'error', 'native_version', 'exact_same_seed_repeat')}))
    return 0 if state['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
