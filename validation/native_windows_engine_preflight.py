"""Native dependency/hardware evidence for still-disabled Windows engines.

This is NOT docking acceptance. A missing package/device is an explicit blocked
engine result, not a successful docking run. No search or protocol is created.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def opencl_gpu_inventory():
    """Query only installed drivers; do not install/emulate a GPU runtime."""
    try:
        library = ctypes.WinDLL('OpenCL.dll')
    except OSError:
        return {'status': 'driver_not_installed', 'gpu_devices': 0}
    get_platforms, get_devices = library.clGetPlatformIDs, library.clGetDeviceIDs
    get_platforms.argtypes = [ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    get_platforms.restype = ctypes.c_int
    get_devices.argtypes = [ctypes.c_void_p, ctypes.c_ulonglong, ctypes.c_uint,
                           ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_uint)]
    get_devices.restype = ctypes.c_int
    count = ctypes.c_uint()
    code = get_platforms(0, None, ctypes.byref(count))
    if code == -1001:
        return {'status': 'no_opencl_platform', 'gpu_devices': 0, 'returncode': code}
    if code != 0:
        return {'status': 'driver_query_failed', 'returncode': code, 'gpu_devices': 0}
    values = (ctypes.c_void_p * count.value)()
    code = get_platforms(count.value, values, None)
    if code:
        return {'status': 'driver_query_failed', 'returncode': code, 'gpu_devices': 0}
    total, errors = 0, []
    for value in values:
        devices = ctypes.c_uint()
        code = get_devices(value, 4, 0, None, ctypes.byref(devices))  # CL_DEVICE_TYPE_GPU
        if code == 0:
            total += devices.value
        elif code != -1:  # CL_DEVICE_NOT_FOUND is a valid empty inventory
            errors.append(code)
    return {'status': 'queried' if not errors else 'device_query_failed',
            'platforms': count.value, 'gpu_devices': total, 'query_errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--conda', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Windows':
        parser.error('Real native Windows required')
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    status = {'status': 'running', 'system': platform.platform(), 'scope': 'availability and rejection only; no docking acceptance',
              'scientific_searches_started': 0, 'production_engines_enabled': False}
    try:
        env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        result = subprocess.run([str(args.conda), 'search', '--json', '--platform', 'win-64',
            '--override-channels', '-c', 'conda-forge', 'qvina=2.1.0'],
            env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding='utf-8', timeout=600)
        # Dependency JSON contains no coordinates, studies, scores or user files.
        (out / 'qvina-package-query.local.json').write_text(result.stdout, encoding='utf-8')
        packages = json.loads(result.stdout)
        if result.returncode == 0 and packages.get('qvina'):
            status['quickvina_w'] = {'status': 'package_available_not_execution_validated',
                'packages': [{key: p.get(key) for key in ('name', 'version', 'build', 'subdir', 'sha256')}
                             for p in packages['qvina']]}
        elif packages.get('exception_name') == 'PackagesNotFoundError' or packages.get('error', '').startswith('PackagesNotFoundError'):
            status['quickvina_w'] = {'status': 'blocked_no_pinned_win64_package', 'pin': 'qvina=2.1.0',
                                     'channel': 'conda-forge', 'subdir': 'win-64'}
        else:
            raise RuntimeError('Native QuickVina dependency query failed unexpectedly')
        status['opencl'] = opencl_gpu_inventory()
        sys.path.insert(0, str(ROOT / 'libexec'))
        from docking_universal.ad4_gpu import runtime_descriptor
        descriptor = out / 'unaccepted-native-test.json'
        descriptor.write_text(json.dumps({'schema': 'docking-universal-adgpu-runtime-v1',
            'integration_accepted': True, 'executable': str(out / 'must-never-execute.exe')}), encoding='utf-8')
        try:
            runtime_descriptor({'DOCKING_UNIVERSAL_ADGPU_CONFIG': str(descriptor)})
        except ValueError as exc:
            if str(exc) != 'This experimental AD4 build requires Apple-Silicon macOS':
                raise
            status['ad4_gpu'] = {'status': 'blocked_no_accepted_native_windows_build',
                                 'apple_binary_rejected_before_execution': True,
                                 'gpu_hardware_available': status['opencl']['gpu_devices'] > 0}
        else:
            raise AssertionError('Apple-only AD4 configuration was incorrectly accepted on native Windows')
        status['status'] = 'completed_with_blocked_engines'
    except Exception as exc:
        status.update(status='failed', error_type=type(exc).__name__)
    (out / 'summary.json').write_text(json.dumps(status, indent=2) + '\n', encoding='utf-8')
    return 1 if status['status'] == 'failed' else 0


if __name__ == '__main__':
    raise SystemExit(main())
