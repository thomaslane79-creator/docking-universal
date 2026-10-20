"""Owned Qt6 PyMOL and process-local software graphics; no system driver changes.

Initialize before importing Qt/PyMOL. An integrity or setup failure is explicit:
never try the known-crashing default graphics path or another installation.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

PROFILE = 'pymol-qt6-mesa26-software-v1'
_handles = []
_active_receipt = None


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def owned_gui_python(app, configuration):
    root = Path(app).parent.resolve()
    if configuration.get('scientific_manager'):
        from .windows_scientific_runtime import owned_scientific_python
        science = owned_scientific_python(Path(app), configuration)
        expected = science.parent.parent / 'gui/python.exe'
    else:
        expected = root / 'runtimes/gui/python.exe'
    selected = (root / configuration['gui_python']).resolve()
    if selected != expected.resolve() or not selected.is_file():
        raise ValueError('Viewer interpreter escaped its exact owned runtime or is missing')
    return selected


def viewer_record(app, configuration=None, *, executing_python=None):
    app = Path(app).resolve()
    configuration = configuration if configuration is not None else json.loads((app / 'native-preview.json').read_text(encoding='utf-8'))
    if not configuration.get('viewer_profile'):
        return None
    if configuration['viewer_profile'] != PROFILE:
        raise ValueError('Unsupported Windows viewer profile; no graphics fallback was attempted')
    python = owned_gui_python(app, configuration)
    if Path(executing_python or sys.executable).resolve() != python:
        raise ValueError('Viewer must use the exact installation-owned GUI Python')
    receipt = (app.parent / configuration['viewer_receipt']).resolve()
    if not receipt.is_relative_to(app.parent) or digest(receipt) != configuration['viewer_receipt_sha256']:
        raise ValueError('Viewer installation receipt changed or escaped its installation')
    record = json.loads(receipt.read_text(encoding='utf-8'))
    if (record.get('status') != 'installed' or record.get('profile') != PROFILE
            or Path(record['python']).resolve() != python):
        raise ValueError('Viewer installation is incomplete or its interpreter changed')
    prefix = python.parent
    for relative, expected in record['files'].items():
        path = (prefix / relative).resolve()
        if not path.is_relative_to(prefix) or digest(path) != expected:
            raise ValueError('A pinned viewer library changed or escaped its owned prefix')
    dll = (prefix / record['opengl_dll']).resolve()
    if record['opengl_dll'] not in record['files'] or not dll.is_relative_to(prefix):
        raise ValueError('Viewer graphics library is not covered by the owned receipt')
    return record, dll


def activate_installed_viewer(app, configuration=None, *, executing_python=None):
    """Keep both DLL handles alive for this GUI process only."""
    global _active_receipt
    selected = viewer_record(app, configuration, executing_python=executing_python)
    if selected is None:
        return None
    record, dll = selected
    if _active_receipt is not None:
        if _active_receipt != str(dll):
            raise ValueError('A different viewer installation is already loaded in this process')
        return record
    if 'PyQt6.QtGui' in sys.modules or 'pymol._cmd' in sys.modules:
        raise ValueError('Owned Windows graphics must initialize before Qt/PyMOL imports')
    if os.name != 'nt':
        raise ValueError('The Windows viewing runtime cannot load on another platform')
    prefix = Path(record['python']).resolve().parent
    # Native extension dependencies also belong to this GUI prefix. Python
    # 3.8+ Windows DLL discovery does not reliably use the inherited PATH alone.
    for directory in (prefix, prefix / 'Library/bin'):
        if directory.is_dir():
            _handles.append(os.add_dll_directory(str(directory)))
    _handles.append(os.add_dll_directory(str(dll.parent)))
    _handles.append(ctypes.WinDLL(str(dll)))
    os.environ.update(QT_API='pyqt6', QT_OPENGL='desktop', QT_OPENGL_DLL=str(dll),
                      GALLIUM_DRIVER='llvmpipe', LIBGL_ALWAYS_SOFTWARE='1',
                      DOCKING_UNIVERSAL_VIEWER_GRAPHICS='software')
    _active_receipt = str(dll)
    return record


def install_viewer_runtime(*, gui, app, source_assets, work, environment=None):
    """Install prebuilt code + two pinned graphics DLLs into a fresh owned GUI.

    This is never called on a working/user-selected environment. Source/compiler
    tools are not required. No deployment .cmd, registry or system install runs.
    """
    gui, app, source_assets, work = map(Path, (gui, app, source_assets, work))
    if work.exists() or (gui / 'share/docking-universal-viewer').exists():
        raise FileExistsError('Viewer installation requires fresh owned audit/graphics directories')
    assets = source_assets / 'dependencies/runtime/windows-x64'
    manifest = json.loads((assets / 'manifest.json').read_text(encoding='utf-8'))
    if manifest['profile'] != PROFILE:
        raise ValueError('Viewer manifest profile changed')
    wheel = assets / manifest['wheel']['name']
    if digest(wheel) != manifest['wheel']['sha256']:
        raise ValueError('Pinned Windows PyMOL wheel checksum mismatch')
    with zipfile.ZipFile(wheel) as package:
        paths = package.namelist()
        critical = [p for p in paths if p.startswith('pymol/_cmd.') and p.endswith('.pyd')]
        if len(critical) != 1:
            raise ValueError('Pinned wheel does not contain one native PyMOL extension')
    work.mkdir(parents=True)
    from .native_entrypoint import isolated_environment
    env = isolated_environment(gui, os.environ if environment is None else environment)
    python = gui / 'python.exe'

    def run(name, command):
        with (work / (name + '.log')).open('wb') as log:
            subprocess.run(list(map(str, command)), env=env, stdin=subprocess.DEVNULL,
                           stdout=log, stderr=subprocess.STDOUT, check=True, timeout=900)

    run('install_pinned_pymol_wheel', [python, '-m', 'pip', 'install', '--no-deps', wheel])
    mesa = manifest['mesa']
    with urllib.request.urlopen(mesa['url'], timeout=120) as response:
        data = response.read()
    if hashlib.sha256(data).hexdigest() != mesa['sha256']:
        raise ValueError('Pinned private graphics archive checksum mismatch')
    archive = work / mesa['filename']; archive.write_bytes(data)
    candidates = []
    for file in (gui / 'conda-meta').glob('7zip-*.json'):
        metadata = json.loads(file.read_text(encoding='utf-8'))
        candidates.extend(gui / p for p in metadata['files'] if Path(p).name.lower() == '7z.exe')
    if len(candidates) != 1 or not candidates[0].is_file():
        raise ValueError('Owned runtime lacks its declared private archive extractor')
    destination = gui / 'share/docking-universal-viewer'
    destination.mkdir(parents=True)
    # Exact allowlist from a checksum-verified upstream archive. Never extract
    # or execute its system-wide/per-application deployment scripts or OpenCL.
    names = list(mesa['libraries'])
    if set(names) != {'x64/opengl32.dll', 'x64/libgallium_wgl.dll'}:
        raise ValueError('Unexpected private graphics extraction plan')
    run('extract_private_graphics_libraries', [candidates[0], 'x', '-y', '-o' + str(destination), archive, *names])
    files = {}
    for name, expected in mesa['libraries'].items():
        path = destination / name
        if digest(path) != expected:
            raise ValueError('Private graphics library does not match its pinned hash')
        files[path.relative_to(gui).as_posix()] = expected
    for name in [critical[0], 'pmg_qt/pymol_gl_widget.py', 'pmg_qt/pymol_qt_gui.py', 'pymol/__init__.py']:
        path = gui / 'Lib/site-packages' / name
        files[path.relative_to(gui).as_posix()] = digest(path)
    shutil.copyfile(assets / 'LICENSE-PyMOL', destination / 'LICENSE-PyMOL')
    (destination / 'provenance.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    receipt = {'status': 'installed', 'profile': PROFILE, 'python': str(python.resolve()),
        'graphics': 'CPU software rendering; not GPU docking or system driver replacement',
        'wheel': manifest['wheel'], 'files': files,
        'opengl_dll': 'share/docking-universal-viewer/x64/opengl32.dll'}
    (work / 'viewer-install.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    return receipt
