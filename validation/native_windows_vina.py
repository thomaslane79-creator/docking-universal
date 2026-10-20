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
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--installed-entry', type=Path, help='test a staged native dispatcher instead of the source adapter')
    parser.add_argument('--engine', type=Path, help='reuse an already installed, checksum-verified official executable')
    args = parser.parse_args()
    if platform.system() != 'Windows':
        parser.error('This validation must run natively on Windows, not a mocked platform or WSL')
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    asset = json.loads((ROOT / 'dependencies/vina-windows.json').read_text())
    state = {'status': 'running', 'system': platform.platform(), 'python': sys.executable,
             'scope': 'Synthetic prepared-input CPU adapter only; no native installer/preparation/GUI/GPU acceptance',
             'asset': asset, 'runs': []}
    try:
        if args.engine:
            data = args.engine.read_bytes()
        else:
            with urllib.request.urlopen(asset['url'], timeout=60) as response:
                data = response.read()
        if hashlib.sha256(data).hexdigest() != asset['sha256'] or data[:2] != b'MZ':
            raise ValueError('Official Windows Vina asset checksum/format mismatch')
        executable = args.engine.resolve() if args.engine else out / asset['filename']
        if not args.engine:
            executable.write_bytes(data)
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
            dispatcher = ([sys.executable, str(args.installed_entry), 'dock'] if args.installed_entry else
                [sys.executable, str(ROOT / 'libexec/docking_universal_dock.py'),
                 '--engine', 'vina', '--engine-command', str(executable), '--vina-backend', 'cli'])
            command = [*dispatcher,
                '--receptor', str(receptor), '--ligands', str(ligands), '--config', str(box), '--out', str(target),
                '--seed', '41001', '--cpu', '1', '--exhaustiveness', '1', '--num-modes', '3']
            # Match the installed native entry point's UTF-8 process contract;
            # redirected Windows stdout otherwise uses the ANSI code page.
            env = dict(os.environ, DOCKING_UNIVERSAL_PYTHON=sys.executable,
                       PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
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
        unicode_inputs = out / 'Inputs Ω 日本語'; unicode_inputs.mkdir()
        unicode_receptor = unicode_inputs / receptor.name
        unicode_box = unicode_inputs / box.name
        unicode_ligands = unicode_inputs / 'Ligands Ω'; unicode_ligands.mkdir()
        unicode_ligand = unicode_ligands / 'fragment Ω.pdbqt'
        for source, target in ((receptor, unicode_receptor), (box, unicode_box),
                               (ligands / 'fragment.pdbqt', unicode_ligand)):
            shutil.copyfile(source, target)
        # Diagnose the pinned binary itself, never call a raw failure success.
        raw_output = unicode_inputs / 'raw Ω.pdbqt'
        with (out / 'raw-unicode-vina.local.log').open('wb') as stream:
            raw = subprocess.run([str(executable), '--receptor', str(unicode_receptor),
                '--ligand', str(unicode_ligand), '--config', str(unicode_box), '--out', str(raw_output),
                '--seed', '41001', '--cpu', '1', '--exhaustiveness', '1', '--num_modes', '3'],
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, timeout=60)
        state['raw_unicode_cli'] = {'returncode': raw.returncode,
            'output_created': raw_output.is_file(),
            'exact_ascii_output': raw_output.is_file() and raw_output.read_bytes() == outputs[0]}
        unicode_target = out / 'Results Ω 日本語'
        command = [*dispatcher, '--receptor', str(unicode_receptor), '--ligands', str(unicode_ligands),
            '--config', str(unicode_box), '--out', str(unicode_target), '--seed', '41001',
            '--cpu', '1', '--exhaustiveness', '1', '--num-modes', '3']
        with (out / 'unicode-adapter.local.log').open('wb') as stream:
            subprocess.run(command, env=env, stdin=subprocess.DEVNULL, stdout=stream,
                           stderr=subprocess.STDOUT, check=True, timeout=90)
        if (unicode_target / 'fragment Ω_vina.pdbqt').read_bytes() != outputs[0]:
            raise ValueError('Unicode native transport changed complete Vina pose output')
        state['unicode_paths_exact_ascii_output'] = True
        state.update(status='passed', exact_same_seed_repeat=True, native_version=version,
                     installed_dispatcher=bool(args.installed_entry))
    except BaseException as exc:
        state.update(status='failed', error=str(exc))
        state['runtime_exception_types'] = sorted({match.group(1) for path in out.glob('*.log')
            for line in path.read_text(encoding='utf-8', errors='replace').splitlines()
            for match in [re.match(r'^(\w*(?:Error|Exception)):', line)] if match})
    (out / 'summary.json').write_text(json.dumps(state, indent=2) + '\n')
    print(json.dumps({k: state.get(k) for k in ('status', 'error', 'native_version', 'exact_same_seed_repeat')}))
    return 0 if state['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
