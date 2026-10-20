"""Prepared-input native QuickVina-W execution, not GUI/receptor acceptance.

Nonbiological synthetic fragments only; output structures and logs stay local.
No native installer/host capability is enabled by this validation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--conda', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Windows':
        parser.error('Native Windows required')
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    state = {'status': 'running', 'system': platform.platform(), 'runs': [],
             'scope': 'isolated prepared-input adapter, not receptor/report/GUI or accuracy acceptance',
             'production_engine_enabled': False}
    env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
    for key in ('PYTHONHOME', 'PYTHONPATH'):
        env.pop(key, None)
    try:
        pin = json.loads((ROOT / 'dependencies/qvina-windows-validation.json').read_text(encoding='utf-8'))
        prefix = out / 'engine'
        with (out / 'dependency-install.local.log').open('wb') as log:
            subprocess.run([str(args.conda), 'create', '--yes', '--prefix', str(prefix),
                '--override-channels', '-c', pin['channel'],
                '{name}={version}={build}'.format(**pin)], env=env, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)
        files = list((prefix / 'conda-meta').glob('qvina-*.json'))
        if len(files) != 1:
            raise ValueError('Ambiguous QuickVina package identity')
        package = json.loads(files[0].read_text(encoding='utf-8'))
        if any(package.get(key) != pin[key] for key in ('name', 'version', 'build', 'subdir', 'sha256')):
            raise ValueError('Installed native QuickVina package differs from validation pin')
        state['package'] = pin
        candidates = [prefix / name for name in package['files'] if Path(name).name.lower() == 'qvinaw.exe']
        if len(candidates) != 1 or not candidates[0].is_file():
            raise ValueError('Pinned package lacks an unambiguous native qvinaw.exe')
        executable = candidates[0]
        state['executable_sha256'] = hashlib.sha256(executable.read_bytes()).hexdigest()
        sys.path.insert(0, str(ROOT / 'libexec'))
        from docking_universal.runtime_layout import executable_directories
        env['PATH'] = os.pathsep.join([*(str(p) for p in executable_directories(prefix, windows=True)), env.get('PATH', '')])
        version = subprocess.check_output([str(executable), '--version'], env=env, text=True, timeout=20).strip()
        if not version.startswith('QuickVina-W 1.1'):
            raise ValueError('Package executable is not the expected QuickVina-W method')
        state['version'] = version
        inputs = out / 'Synthetic inputs with spaces'; inputs.mkdir()
        receptor = inputs / 'receptor.pdbqt'
        receptor.write_text('ATOM      1  C   SYN A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n', encoding='utf-8')
        ligands = inputs / 'ligands'; ligands.mkdir()
        ligand = ligands / 'fragment.pdbqt'
        ligand.write_text('ROOT\n'
            'ATOM      1  C1  SYN A   1       0.000   0.000   0.000  1.00  0.00     0.000 C \n'
            'ATOM      2  C2  SYN A   1       1.500   0.000   0.000  1.00  0.00     0.000 C \n'
            'ENDROOT\nTORSDOF 0\n', encoding='utf-8')
        box = inputs / 'box.conf'
        box.write_text('center_x = 0\ncenter_y = 0\ncenter_z = 0\nsize_x = 10\nsize_y = 10\nsize_z = 10\n', encoding='utf-8')

        def invoke(name, rec, ligdir, config):
            target = out / name
            command = [sys.executable, str(ROOT / 'libexec/docking_universal_dock.py'), '--engine', 'qvinaw',
                '--engine-command', str(executable), '--receptor', str(rec), '--ligands', str(ligdir),
                '--config', str(config), '--out', str(target), '--seed', '41001', '--cpu', '1',
                '--exhaustiveness', '1', '--num-modes', '3']
            with (out / (name + '.local.log')).open('wb') as log:
                result = subprocess.run(command, env=env, stdin=subprocess.DEVNULL, stdout=log,
                                        stderr=subprocess.STDOUT, timeout=90)
            return result.returncode, target

        outputs = []
        for repeat in range(2):
            code, target = invoke('repeat-' + str(repeat), receptor, ligands, box)
            if code != 0:
                raise RuntimeError('Native QuickVina-W ASCII prepared-input adapter failed')
            content = (target / 'fragment_qvinaw.pdbqt').read_bytes()
            energies = [float(line.split()[3]) for line in content.decode().splitlines() if line.startswith('REMARK VINA RESULT:')]
            if not energies or not all(map(math.isfinite, energies)):
                raise ValueError('No finite QuickVina-W result')
            outputs.append(content)
            state['runs'].append({'repeat': repeat, 'poses': len(energies), 'output_sha256': hashlib.sha256(content).hexdigest()})
        if outputs[0] != outputs[1]:
            raise ValueError('Native QuickVina-W same-seed repeats differ')
        state['exact_same_seed_repeat'] = True
        unicode = out / 'Inputs Ω 日本語'; unicode.mkdir()
        unicode_ligands = unicode / 'ligands'; unicode_ligands.mkdir()
        for original, target in ((receptor, unicode / receptor.name), (box, unicode / box.name),
                                 (ligand, unicode_ligands / ligand.name)):
            shutil.copyfile(original, target)
        code, target = invoke('unicode-result', unicode / receptor.name, unicode_ligands, unicode / box.name)
        output = target / 'fragment_qvinaw.pdbqt'
        state['unicode_paths'] = {'returncode': code, 'output_created': output.is_file(),
            'exact_ascii_output': code == 0 and output.is_file() and output.read_bytes() == outputs[0]}
        state['status'] = 'passed_prepared_input_gate' if state['unicode_paths']['exact_ascii_output'] else 'completed_with_unicode_failure'
    except Exception as exc:
        state.update(status='failed', error_type=type(exc).__name__)
    (out / 'summary.json').write_text(json.dumps(state, indent=2) + '\n', encoding='utf-8')
    return 0 if state['status'] == 'passed_prepared_input_gate' else 1


if __name__ == '__main__':
    raise SystemExit(main())
