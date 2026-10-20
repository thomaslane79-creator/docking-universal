"""Exact owned Windows QuickVina package; activation follows installed acceptance."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

PROFILE = 'qvinaw-2.1.0-win64-he453025-8-v1'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def record(app, configuration):
    app = Path(app).resolve()
    if not configuration.get('qvinaw_candidate_installed'):
        return None
    root = app.parent
    receipt = (root / configuration['qvinaw_receipt']).resolve()
    if not receipt.is_relative_to(root) or digest(receipt) != configuration['qvinaw_receipt_sha256']:
        raise ValueError('Owned QuickVina installation receipt changed or escaped its installation')
    item = json.loads(receipt.read_text(encoding='utf-8'))
    if configuration.get('scientific_manager'):
        from .windows_scientific_runtime import owned_scientific_python
        prefix = owned_scientific_python(app, configuration).parent.parent / 'qvinaw'
    else:
        prefix = root / 'runtimes/qvinaw'
    executable = Path(item['executable']).resolve()
    if (item.get('status') != 'installed' or item.get('profile') != PROFILE
            or Path(item['prefix']).resolve() != prefix.resolve() or not executable.is_relative_to(prefix.resolve())
            or digest(executable) != item['executable_sha256']):
        raise ValueError('Owned QuickVina executable identity changed; no engine fallback was attempted')
    return item


def supported_engines(configuration, environment):
    # The environment exception is used only by the isolated acceptance driver
    # before promotion. Normal launchers never set it or approve any study.
    enabled = configuration.get('qvinaw_candidate_installed') and (
        configuration.get('qvinaw_supported') or environment.get('DOCKING_UNIVERSAL_QVINAW_ACCEPTANCE') == '1')
    return ('vina', 'qvinaw') if enabled else ('vina',)


def engine_environment(environment, command, *, windows=None):
    """Conda DLL priority for this engine child only, never the chemistry host."""
    if not (os.name == 'nt' if windows is None else windows) or not environment.get('DOCKING_UNIVERSAL_QVINAW_RUNTIME'):
        return environment
    prefix = Path(environment['DOCKING_UNIVERSAL_QVINAW_RUNTIME']).resolve()
    if not Path(command[0]).resolve().is_relative_to(prefix):
        raise ValueError('QuickVina executable escaped its owned engine runtime')
    from .runtime_layout import executable_directories
    selected = dict(environment)
    selected['PATH'] = os.pathsep.join([*(str(p) for p in executable_directories(prefix, windows=True)), environment.get('PATH', '')])
    return selected


def install(*, conda, prefix, app, source_assets, work):
    prefix, app, source_assets, work = map(Path, (prefix, app, source_assets, work))
    if prefix.exists() or work.exists():
        raise FileExistsError('QuickVina installation requires fresh owned runtime/audit directories')
    pin = json.loads((source_assets / 'dependencies/qvinaw-windows.json').read_text(encoding='utf-8'))
    work.mkdir(parents=True)
    with (work / 'install.log').open('wb') as log:
        subprocess.run([str(conda), 'create', '--yes', '--prefix', str(prefix), '--override-channels',
            '-c', pin['channel'], '{name}={version}={build}'.format(**pin)],
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
    packages = list((prefix / 'conda-meta').glob('qvina-*.json'))
    if len(packages) != 1:
        raise ValueError('Ambiguous installed QuickVina package')
    package = json.loads(packages[0].read_text(encoding='utf-8'))
    if any(package.get(key) != pin[key] for key in ('name', 'version', 'build', 'subdir', 'sha256')):
        raise ValueError('Installed QuickVina package differs from its exact native pin')
    binaries = [prefix / name for name in package['files'] if Path(name).name.lower() == 'qvinaw.exe']
    if len(binaries) != 1 or digest(binaries[0]) != pin['executable_sha256']:
        raise ValueError('Installed QuickVina binary differs from the native-tested executable')
    item = {'status': 'installed', 'profile': PROFILE, 'prefix': str(prefix.resolve()),
            'executable': str(binaries[0].resolve()), 'executable_sha256': pin['executable_sha256'], 'package': pin}
    (work / 'qvinaw-install.json').write_text(json.dumps(item, indent=2) + '\n', encoding='utf-8')
    return item
