"""Isolated native Windows Qt6/PyMOL build and real-viewer validation.

Only summary.json may leave the runner. No installer/engine capability is enabled.
The archive is the same pinned upstream source already retained for the Mac build.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--conda', required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != 'Windows':
        parser.error('A real native Windows interpreter is required')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    status = {'status': 'running', 'system': platform.platform(), 'steps': [],
              'production_viewer_enabled': False, 'gpu_accepted': False,
              'scope': 'isolated source-built Qt6 viewer, not installed desktop or consumer GPU acceptance'}
    environment = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8', QT_API='pyqt6')
    for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_QPA_PLATFORM', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        environment.pop(key, None)

    def save():
        (out / 'summary.json').write_text(json.dumps(status, indent=2) + '\n', encoding='utf-8')

    def run(name, command, *, cwd=None, timeout=1200):
        item = {'name': name, 'status': 'running'}
        status['steps'].append(item); save()
        started = time.monotonic()
        with (out / (name + '.local.log')).open('w', encoding='utf-8') as log:
            result = subprocess.run(list(map(str, command)), env=environment, cwd=cwd,
                                    stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=timeout)
        item.update(status='passed' if result.returncode == 0 else 'failed',
                    returncode=result.returncode, seconds=round(time.monotonic() - started, 3)); save()
        if result.returncode:
            raise RuntimeError('Validation stage failed: ' + name)

    save()
    try:
        manifest = json.loads((ROOT / 'dependencies/runtime/macos-arm64/manifest.json').read_text(encoding='utf-8'))
        archive = ROOT / 'dependencies/runtime/macos-arm64/pymol-source.tar.gz'
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != manifest['files'][archive.name]['sha256']:
            raise ValueError('Pinned upstream PyMOL source checksum mismatch')
        status['pymol_source'] = {'upstream_commit': manifest['pymol']['upstream_commit'], 'sha256': digest,
                                  'source_changes': False,
                                  'options': {'libxml': 'no', 'use-msgpackc': 'no', 'vmd-plugins': 'no'}}
        sys.path.insert(0, str(ROOT / 'libexec'))
        from docking_universal.windows_scientific_install import extract_p2rank
        # This safety-checked extractor strips one root and rejects traversal,
        # links/devices before creating any directory; it is archive-independent.
        source = out / 'pymol-source'
        extract_p2rank(archive, source)
        prefix = out / 'viewer'
        run('fresh_qt6_build_dependencies', [args.conda, 'env', 'create', '--yes', '--prefix', prefix,
                                             '--file', ROOT / 'environments/windows-viewer-validation.yml'])
        python = prefix / 'python.exe'
        environment.update(CONDA_PREFIX=str(prefix))
        from docking_universal.runtime_layout import executable_directories
        environment['PATH'] = os.pathsep.join([*(str(p) for p in executable_directories(prefix, windows=True)), environment.get('PATH', '')])
        run('build_pinned_pymol', [python, '-m', 'pip', 'wheel', '--no-deps', '--no-build-isolation',
            '--wheel-dir', out / 'wheels', '--config-settings', 'libxml=no', '--config-settings', 'use-msgpackc=no',
            '--config-settings', 'vmd-plugins=no', '.'], cwd=source, timeout=1800)
        wheels = list((out / 'wheels').glob('pymol-*.whl'))
        if len(wheels) != 1:
            raise ValueError('Expected exactly one newly built PyMOL wheel')
        status['wheel'] = {'name': wheels[0].name, 'sha256': hashlib.sha256(wheels[0].read_bytes()).hexdigest()}
        run('install_candidate_wheel', [python, '-m', 'pip', 'install', '--no-deps', wheels[0]])
        spec = importlib.util.spec_from_file_location('native_install', ROOT / 'tools/install_native_windows.py')
        installer = importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
        app = out / 'Application Ω 日本語 with spaces' / 'app'
        hashes = installer.copy_application(ROOT, app)
        status['copied_application_files'] = len(hashes)
        run('real_qt6_opengl_detach_return_export', [python, ROOT / 'validation/native_viewer_probe.py',
                                                   '--app', app, '--out', out / 'viewer-probe'], timeout=180)
        probe = json.loads((out / 'viewer-probe/summary.json').read_text(encoding='utf-8'))
        if probe['status'] != 'passed':
            raise ValueError('Real viewer probe did not finish successfully')
        status.update(status='passed', viewer=probe)
    except Exception as exc:
        status.update(status='failed', error_type=type(exc).__name__,
                      code_locations=[{'file': Path(f.filename).name, 'function': f.name, 'line': f.lineno}
                                      for f in traceback.extract_tb(exc.__traceback__)[-4:]])
        # Build logs precede any structure and contain only compiler diagnostics.
        # Never include the later real-viewer log or exported molecular images.
        if any(s['name'] == 'build_pinned_pymol' and s['status'] == 'failed' for s in status['steps']):
            lines = (out / 'build_pinned_pymol.local.log').read_text(encoding='utf-8', errors='replace').splitlines()
            status['compiler_errors'] = [line for line in lines if 'error ' in line.lower() or 'error:' in line.lower()][-12:]
        probe = out / 'viewer-probe/summary.json'
        if probe.is_file():
            status['viewer'] = json.loads(probe.read_text(encoding='utf-8'))
    save()
    return 0 if status['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
