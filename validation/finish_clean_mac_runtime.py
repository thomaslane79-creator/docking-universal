"""Run bounded native checks strictly inside a completed fresh installation."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from clean_install_mac_runtime import isolated_environment

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installation', required=True, type=Path)
    parser.add_argument('--attempt', default='')
    parser.add_argument('--reuse-viewer', action='store_true')
    args = parser.parse_args()
    out = args.installation.resolve()
    original = json.loads((out / 'summary.json').read_text())
    if original['status'] != 'completed':
        raise ValueError('Fresh installation is not completed')
    if args.attempt and not all(c.isalnum() or c == '-' for c in args.attempt):
        raise ValueError('Attempt name must be alphanumeric with optional hyphens')
    suffix = '-' + args.attempt if args.attempt else ''
    summary_path = out / ('native-acceptance' + suffix + '.json')
    if summary_path.exists():
        raise ValueError('Native acceptance already attempted; do not duplicate jobs')
    prefix = Path(original['conda_prefix'])
    sandbox = Path(original['sandbox'])
    scientific = prefix / 'envs/docking-universal'
    runtime = scientific / 'libexec/docking-universal'
    gui = prefix / 'envs/docking-universal-gui-next'
    env = isolated_environment(sandbox)
    record = {'status': 'running', 'steps': [], 'installation': str(out / 'summary.json'),
              'scientific_approvals': 0, 'biological_docking_jobs': 0, 'synthetic_gpu_jobs': 2}

    def save():
        summary_path.write_text(json.dumps(record, indent=2) + '\n')

    def run(name, command, timeout=120):
        row = {'name': name, 'status': 'running', 'command': list(map(str, command))}
        record['steps'].append(row); save(); started = time.monotonic()
        with (out / (name + '.log')).open('w') as stream:
            process = subprocess.Popen(list(map(str, command)), env=env, cwd=sandbox,
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                code = process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGTERM)
                try: process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL); process.wait()
                raise TimeoutError(name + ' exceeded bounded native-check time')
        row.update(status='passed' if code == 0 else 'failed', exit_code=code,
                   elapsed_seconds=round(time.monotonic() - started, 2)); save()
        if code:
            raise RuntimeError(name + ' failed; see its retained log')

    save()
    try:
        for relative in ('docking_universal/ad4_gpu.py', 'docking_universal/runtime_setup.py',
                         'docking_universal/viewer/embedded_pymol.py', 'docking_universal/viewer/full_pymol.py'):
            if digest(runtime / relative) != digest(ROOT / 'libexec' / relative):
                raise ValueError('Fresh installed implementation differs from current source: ' + relative)
        if args.reuse_viewer:
            prior = out / 'native-viewer/summary.json'
            if json.loads(prior.read_text())['status'] != 'passed':
                raise ValueError('Prior native viewer did not pass')
            record['retained_viewer_acceptance'] = {'path': str(prior), 'sha256': digest(prior)}
        else:
            run('native-viewer' + suffix, [gui / 'bin/python', ROOT / 'validation/native_mac_runtime_viewer.py',
                '--runtime', runtime, '--out', out / ('native-viewer' + suffix)])
        run('native-gpu' + suffix, [scientific / 'bin/python', ROOT / 'validation/native_mac_runtime_gpu.py',
            '--runtime', runtime, '--out', out / ('native-gpu' + suffix)], 420)
        record['status'] = 'passed'
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
    finally:
        protected = json.loads((out / 'protected-sha256.json').read_text())
        record['protected_files_checked'] = len(protected)
        record['protected_files_changed'] = [p for p, value in protected.items() if not Path(p).is_file() or digest(p) != value]
        if record['protected_files_changed']:
            record.update(status='failed', error='Working files changed during native checks')
        save()
    print(json.dumps(record, indent=2))
    return 0 if record['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
