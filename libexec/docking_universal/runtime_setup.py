"""Install pinned optional native runtimes into explicit Conda prefixes only.

No user configuration, study, scientific setting, or working environment is
discovered or modified by this helper. The bundled engine's acceptance is build
specific, not a claim that a new target has passed a pose-recovery control.
"""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys

from .ad4_gpu import PINNED_ENGINE_SHA256


def version_tuple(value):
    return tuple(int(part) for part in value.split('.')[:2])


def require_platform(minimum):
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        raise ValueError('Bundled native runtimes require Apple-Silicon macOS; other platforms retain the companion viewer')
    if version_tuple(platform.mac_ver()[0]) < version_tuple(minimum):
        raise ValueError(f'This pinned native runtime requires macOS {minimum} or newer')


def verified_manifest(assets):
    manifest = json.loads((assets / 'manifest.json').read_text())
    if manifest.get('schema') != 'docking-universal-mac-runtimes-v1':
        raise ValueError('Unrecognized native-runtime manifest')
    for name, record in manifest['files'].items():
        if Path(name).name != name:
            raise ValueError('Unsafe native-runtime asset path')
        data = (assets / name).read_bytes()
        if len(data) != record['bytes'] or hashlib.sha256(data).hexdigest() != record['sha256']:
            raise ValueError(f'Native-runtime asset checksum mismatch: {name}')
    engine = manifest['gpu']['executable']
    if manifest['files'][engine]['sha256'] != PINNED_ENGINE_SHA256:
        raise ValueError('Runtime manifest does not contain the accepted GPU build')
    return manifest


def apple_gpu_devices():
    """Check device availability without launching a search or compiling kernels."""
    library = ctypes.CDLL('/System/Library/Frameworks/OpenCL.framework/OpenCL')
    uint, handle, size = ctypes.c_uint, ctypes.c_void_p, ctypes.c_size_t
    library.clGetPlatformIDs.argtypes = [uint, ctypes.POINTER(handle), ctypes.POINTER(uint)]
    library.clGetDeviceIDs.argtypes = [handle, ctypes.c_ulonglong, uint, ctypes.POINTER(handle), ctypes.POINTER(uint)]
    library.clGetDeviceInfo.argtypes = [handle, uint, size, ctypes.c_void_p, ctypes.POINTER(size)]
    count = uint()
    if library.clGetPlatformIDs(0, None, ctypes.byref(count)) != 0 or count.value == 0:
        raise ValueError('Apple OpenCL platform is unavailable; GPU runtime was not activated')
    platforms = (handle * count.value)()
    if library.clGetPlatformIDs(count, platforms, None) != 0:
        raise ValueError('Cannot read OpenCL platforms')
    devices = []
    for item in platforms:
        number = uint()
        if library.clGetDeviceIDs(item, 4, 0, None, ctypes.byref(number)) != 0:
            continue
        identifiers = (handle * number.value)()
        if library.clGetDeviceIDs(item, 4, number, identifiers, None) != 0:
            continue
        for device in identifiers:
            name = ctypes.create_string_buffer(1024)
            if library.clGetDeviceInfo(device, 0x102B, len(name), name, None) == 0:
                devices.append(name.value.decode('utf-8', errors='replace'))
    if not devices or 'Apple' not in devices[0]:
        raise ValueError('The first OpenCL GPU is not an available Apple GPU; runtime was not activated')
    return devices


def atomic_json(path, record):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.partial')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(path)


def install(assets, scientific_prefix, gui_prefix, *, gpu=False):
    manifest = verified_manifest(assets)
    require_platform(manifest['pymol']['minimum_macos'])
    if gpu:
        require_platform(manifest['gpu']['minimum_macos'])
        devices = apple_gpu_devices()
    # Prefixes come explicitly from this invocation of Conda, never a registry
    # search, HOME config, or the prototype's registered Python.
    for prefix in (scientific_prefix, gui_prefix):
        if not (prefix / 'conda-meta').is_dir() or not (prefix / 'bin/python').is_file():
            raise ValueError(f'Not an explicit installed Conda prefix: {prefix}')
    gui_python = gui_prefix / 'bin/python'
    version = subprocess.check_output([str(gui_python), '-I', '-c',
        'import sys; print("%s.%s" % sys.version_info[:2])'], text=True).strip()
    if version != manifest['pymol']['python']:
        raise ValueError('Embedded PyMOL wheel requires Python 3.12 in the GUI prefix')
    subprocess.run([str(gui_python), '-I', '-m', 'pip', 'install', '--no-index', '--no-deps',
                    '--force-reinstall', str(assets / manifest['pymol']['wheel'])], check=True)
    probe = subprocess.check_output([str(gui_python), '-I', '-c',
        'import json,pymol,pymol._cmd,PyQt6.QtCore; '
        'print(json.dumps({"pymol_extension":pymol._cmd.__file__,"qt":PyQt6.QtCore.QT_VERSION_STR}))'], text=True)
    imported = json.loads(probe)
    if not Path(imported['pymol_extension']).resolve().is_relative_to(gui_prefix.resolve()):
        raise ValueError('Embedded PyMOL import escaped the requested GUI environment')
    shared = scientific_prefix / 'share/docking-universal'
    shared.mkdir(parents=True, exist_ok=True)
    # Register only after imports succeed. Never replace an intentional custom
    # desktop registration from an existing installation.
    registration = shared / 'desktop-python'
    if not registration.exists() or registration.read_text().strip() == str(gui_python):
        registration.write_text(str(gui_python) + '\n')
    receipt = {'schema': 'docking-universal-native-install-v1', 'embedded_pymol': imported,
               'manifest_sha256': hashlib.sha256((assets / 'manifest.json').read_bytes()).hexdigest(),
               'gpu_installed_by_this_run': gpu}
    if gpu:
        target = shared / 'adgpu'
        target.mkdir(parents=True, exist_ok=True)
        for key in ('gpu', 'autogrid'):
            name = manifest[key]['executable']
            temporary = target / (name + '.partial')
            shutil.copyfile(assets / name, temporary)
            temporary.chmod(0o755)
            temporary.replace(target / name)
        # Preserve complete corresponding sources and notices next to binaries.
        for name in manifest['files']:
            if name.endswith('.tar.gz') or name.startswith('LICENSE-'):
                shutil.copyfile(assets / name, target / name)
        shutil.copyfile(assets / 'manifest.json', target / 'manifest.json')
        record = {'schema': 'docking-universal-adgpu-runtime-v1', 'integration_accepted': True,
            'validation_only': False, 'executable': str(target / manifest['gpu']['executable']),
            'autogrid_executable': str(target / manifest['autogrid']['executable']),
            'autogrid_sha256': manifest['files'][manifest['autogrid']['executable']]['sha256'],
            'minimum_macos': manifest['gpu']['minimum_macos'], 'opencl_devices_at_install': devices,
            'acceptance_record': 'docs/ad4-gpu-guide.md; docs/mac-runtime-packaging.md',
            'scope': 'Pinned previously accepted experimental dry rigid-receptor Apple OpenCL 128-work-item build; installation device check is not a target control'}
        atomic_json(target / 'runtime.json', record)
        receipt['gpu'] = record
    atomic_json(shared / 'native-runtime-install.json', receipt)
    print('Embedded PyMOL installed in GUI environment.' +
          (' Optional experimental AD4 GPU and AutoGrid installed; Vina remains the default.' if gpu else ' GPU installation not requested.'))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--scientific-prefix', type=Path, required=True)
    parser.add_argument('--gui-prefix', type=Path, required=True)
    parser.add_argument('--with-gpu', action='store_true')
    args = parser.parse_args()
    try:
        install(args.assets.resolve(), args.scientific_prefix.resolve(), args.gui_prefix.resolve(), gpu=args.with_gpu)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'Native runtime installation failed: {exc}\nNo scientific settings or user study approvals were changed.\n')


if __name__ == '__main__':
    main()
