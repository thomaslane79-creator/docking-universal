"""Bounded Mac installation acceptance in a fresh independent Miniforge prefix.

Does not update the working app, reuse its environments, or change HOME. Native
scene and engine checks are separate, using only this script's recorded prefix.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP_URL = 'https://github.com/conda-forge/miniforge/releases/download/26.7.2-0/Miniforge3-MacOSX-arm64.sh'
BOOTSTRAP_SHA = 'd70bfa2e97afcda96927c9b9ca0e2316cb7750e4ce651c94388267cbe9588711'
NAMES = ('docking-universal', 'docking-universal-gui-next', 'docking-universal-pymol-next',
         'docking-universal-vina', 'docking-universal-qvinaw')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def isolated_environment(sandbox):
    prefix = sandbox / 'miniforge'
    env = dict(os.environ)
    for name in list(env):
        if name.startswith(('CONDA_', 'DOCKING_UNIVERSAL_', 'PYTHON', 'MEEKO_', 'VINA_', 'QT_', 'DYLD_')):
            env.pop(name)
    env.pop('CONDARC', None)
    env.update(PATH=str(prefix / 'bin') + ':/usr/bin:/bin:/usr/sbin:/sbin',
        CONDARC=str(sandbox / 'condarc'), CONDA_ENVS_PATH=str(prefix / 'envs'),
        CONDA_PKGS_DIRS=str(prefix / 'pkgs'), CONDA_REGISTER_ENVS='false',
        DOCKING_UNIVERSAL_CONDA=str(prefix / 'bin/conda'), DOCKING_UNIVERSAL_INSTALL_RETRIES='1',
        npm_config_cache=str(sandbox / 'npm-cache'), PIP_CACHE_DIR=str(sandbox / 'pip-cache'),
        PYTHONNOUSERSITE='1', MPLCONFIGDIR=str(sandbox / 'matplotlib'))
    return env


def protected_files():
    paths = set()
    for path in (Path.home() / 'Library/Application Support/Docking Universal/studies').glob('*/application_state.json'):
        state = json.loads(path.read_text())
        if any(job.get('status') in ('queued', 'running') for job in state.get('jobs', [])):
            raise RuntimeError('A study has an active scientific calculation; stop before installation validation')
        paths.add(path)
    for name in NAMES:
        paths.update((Path('/opt/anaconda3/envs') / name / 'conda-meta').glob('*.json'))
    paths.update(Path('/opt/anaconda3/envs/docking-universal/libexec/docking-universal').rglob('*.py'))
    for path in (Path('/opt/anaconda3/bin/docking-universal'), Path.home() / '.condarc',
                 Path.home() / '.conda/environments.txt', Path.home() / '.config/docking-universal/adgpu.json',
                 Path('/opt/anaconda3/envs/docking-universal/share/docking-universal/desktop-python')):
        if path.is_file():
            paths.add(path)
    return {str(path): digest(path) for path in sorted(paths)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--git', default='git')
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    sandbox = Path(tempfile.mkdtemp(prefix='du-native-', dir='/private/tmp'))
    prefix = sandbox / 'miniforge'; source = sandbox / 'source'
    started = time.monotonic()
    record = {'status': 'running', 'sandbox': str(sandbox), 'conda_prefix': str(prefix),
              'source_snapshot': str(source), 'pid': os.getpid(), 'steps': [],
              'scientific_approvals': 0, 'docking_searches': 0,
              'scope': 'Fresh five environments and installer --with-gpu on this Mac, not a new OS/VM'}
    protected = protected_files()
    (out / 'protected-sha256.json').write_text(json.dumps(protected, indent=2) + '\n')
    environment = isolated_environment(sandbox)
    (sandbox / 'condarc').write_text(json.dumps({'channels': ['conda-forge'], 'channel_priority': 'strict',
        'envs_dirs': [str(prefix / 'envs')], 'pkgs_dirs': [str(prefix / 'pkgs')],
        'auto_activate_base': False, 'register_envs': False, 'auto_update_conda': False}))

    def save():
        record['elapsed_seconds'] = round(time.monotonic() - started, 1)
        (out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')

    def run(name, command, timeout=180, env=None):
        record['phase'] = name; log = out / (name + '.log')
        row = {'name': name, 'command': list(map(str, command)), 'log': str(log), 'status': 'running'}
        record['steps'].append(row); save(); began = time.monotonic()
        with log.open('w') as stream:
            child = subprocess.Popen(list(map(str, command)), cwd=sandbox, env=env or environment,
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
            record['child_pid'] = child.pid; save()
            try:
                code = child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                os.killpg(child.pid, signal.SIGTERM)
                try: child.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(child.pid, signal.SIGKILL); child.wait()
                raise TimeoutError(f'{name} exceeded {timeout} seconds; no silent restart')
        row.update(status='passed' if code == 0 else 'failed', exit_code=code,
                   elapsed_seconds=round(time.monotonic() - began, 1))
        record.pop('child_pid', None); save()
        if code:
            raise RuntimeError(f'{name} exited {code}; see {log}')
        return log.read_text()

    save()
    try:
        # Frozen snapshot of the tracked checkpoint plus explicit local changes;
        # no ignored studies, runs, caches or dependencies from installed envs.
        archive = sandbox / 'source.tar'
        subprocess.run([args.git, '-C', str(ROOT), 'archive', 'HEAD', '-o', str(archive)], check=True)
        source.mkdir()
        with tarfile.open(archive) as package:
            package.extractall(source)
        changed = subprocess.check_output([args.git, '-C', str(ROOT), 'diff', '--name-only', '-z']).split(b'\0')
        added = subprocess.check_output([args.git, '-C', str(ROOT), 'ls-files', '--others', '--exclude-standard', '-z']).split(b'\0')
        import shutil
        for item in filter(None, changed + added):
            relative = Path(os.fsdecode(item)); original = ROOT / relative
            if original.is_file():
                target = source / relative; target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, target)
            elif (source / relative).is_file():
                (source / relative).unlink()
        record['source_hashes'] = {str(p.relative_to(source)): digest(p) for p in sorted(source.rglob('*')) if p.is_file()}
        run('download-miniforge', ['/usr/bin/curl', '-fsSL', BOOTSTRAP_URL, '-o', sandbox / 'Miniforge.sh'])
        if digest(sandbox / 'Miniforge.sh') != BOOTSTRAP_SHA:
            raise RuntimeError('Miniforge checksum mismatch')
        run('bootstrap-miniforge', ['/bin/bash', sandbox / 'Miniforge.sh', '-b', '-p', prefix], 300)
        conda = prefix / 'bin/conda'
        info = json.loads(run('conda-isolation', [conda, 'info', '--json']))
        if Path(info['root_prefix']).resolve() != prefix.resolve():
            raise RuntimeError('Wrong Conda root')
        for folder in info['envs_dirs']:
            if Path(folder).resolve() != (prefix / 'envs').resolve() and any((Path(folder) / n).exists() for n in NAMES):
                raise RuntimeError('Conda could resolve working environments; stop')
        listing = run('conda-environments', [conda, 'env', 'list'])
        if any(line.split() and line.split()[0] in NAMES for line in listing.splitlines()):
            raise RuntimeError('Fresh installer sees an existing named app environment')
        run('installer-with-gpu', ['/bin/bash', source / 'install.sh', '--with-gpu'], 1800)
        public = prefix / 'bin/docking-universal'
        for name, arguments in (('public-version', ['--version']), ('check-install', ['check-install', '--full']),
                                ('desktop-help', ['desktop', '--help']),
                                ('smoke', ['validate', 'smoke', '--out', str(sandbox / 'smoke')])):
            run(name, [public, *arguments], 180)
        main_prefix = prefix / 'envs/docking-universal'
        check_env = dict(environment, PYTHONPATH=str(main_prefix / 'libexec/docking-universal'))
        # No configuration override or user HOME config needed: sys.prefix must
        # resolve the freshly installed descriptor, not the working installation.
        probe = 'import json; from docking_universal.ad4_gpu import runtime_descriptor; print(json.dumps(runtime_descriptor()))'
        runtime = json.loads(run('prefix-gpu-discovery', [main_prefix / 'bin/python', '-c', probe], env=check_env))
        if not Path(runtime['executable']).is_relative_to(main_prefix):
            raise RuntimeError('GPU discovery escaped the fresh prefix')
        record.update(status='completed', gpu_runtime=runtime,
            native_receipt=json.loads((main_prefix / 'share/docking-universal/native-runtime-install.json').read_text()))
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
    finally:
        record['protected_files_checked'] = len(protected)
        record['protected_files_changed'] = [p for p, value in protected.items() if not Path(p).is_file() or digest(p) != value]
        if record['protected_files_changed']:
            record.update(status='failed', error='Protected working files changed')
        record.pop('child_pid', None); save()
    print(json.dumps({k: record.get(k) for k in ('status', 'phase', 'error', 'elapsed_seconds', 'protected_files_changed')}))
    return 0 if record['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
