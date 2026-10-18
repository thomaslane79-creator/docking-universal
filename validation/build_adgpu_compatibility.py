"""Build an older-target candidate without accepting or installing that engine.

Reuses the distributed pinned patched source, 128 OpenCL work items and serial
host profile. The deployment target applies to the host executable, not to the
OpenCL driver. Native testing on the older OS is still required.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'libexec'))
from docking_universal.runtime_setup import verified_manifest


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--minimum-macos', default='15.0', choices=['15.0'])
    parser.add_argument('--developer-dir', type=Path)
    args = parser.parse_args()
    if platform.system() != 'Darwin' or platform.machine() != 'arm64':
        parser.error('This candidate build requires an Apple-Silicon Mac')
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    assets = ROOT / 'dependencies/runtime/macos-arm64'
    manifest = verified_manifest(assets)
    state = {'status': 'building', 'production_installed': False, 'integration_accepted': False,
        'requested_minimum_macos': args.minimum_macos, 'build_os': platform.mac_ver()[0],
        'source_archive_sha256': manifest['files']['autodock-gpu-source.tar.gz']['sha256'],
        'upstream_commit': manifest['gpu']['upstream_commit'], 'scientific_settings_changed': False,
        'docking_jobs': 0, 'required_next': 'Run native loading and GPU checks on the actual older OS before activation'}
    def save():
        (out / 'build.json').write_text(json.dumps(state, indent=2) + '\n')
    save()
    try:
        with tarfile.open(assets / 'autodock-gpu-source.tar.gz') as archive:
            for member in archive.getmembers():
                if member.issym() or member.islnk() or not (out / member.name).resolve().is_relative_to(out):
                    raise ValueError('Unsafe source-archive member')
            archive.extractall(out)
        source = out / manifest['gpu']['upstream_commit']
        kernel = source / 'device/calcMergedEneGra.cl'
        header = source / 'host/inc/stringify.h'
        state['kernel_sha256'] = digest(kernel)
        state['generated_kernel_header_before_sha256'] = digest(header)
        developer = (str(args.developer_dir) if args.developer_dir else os.environ.get('DEVELOPER_DIR'))
        if not developer:
            tools = Path('/Library/Developer/CommandLineTools')
            developer = str(tools) if tools.is_dir() else subprocess.check_output(
                ['/usr/bin/xcode-select', '-p'], text=True).strip()
        env = dict(os.environ, DEVELOPER_DIR=developer, MACOSX_DEPLOYMENT_TARGET=args.minimum_macos)
        state['developer_dir'] = developer
        sdk = subprocess.check_output(['/usr/bin/xcrun', '--show-sdk-path'], env=env, text=True).strip()
        frameworks = Path(sdk) / 'System/Library/Frameworks'
        command = ['/usr/bin/make', 'odock', 'DEVICE=OCLGPU', 'NUMWI=128', 'OVERLAP=OFF',
            'CPP=/usr/bin/clang++', 'GIT_VERSION=v1.6-dirty',
            'OPT=-O3 -mmacosx-version-min=' + args.minimum_macos,
            'GPU_INCLUDE_PATH=' + str(frameworks / 'OpenCL.framework/Headers'),
            'GPU_LIBRARY_PATH=' + str(frameworks)]
        state['command'] = command; save()
        with (out / 'build.log').open('w') as stream:
            subprocess.run(command, cwd=source, env=env, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, timeout=300)
        executable = source / 'bin/autodock_gpu_128wi'
        load_commands = subprocess.check_output(['/usr/bin/otool', '-l', str(executable)], env=env, text=True)
        minimum = re.search(r'\bminos\s+([\d.]+)', load_commands)
        if not minimum or minimum.group(1) != args.minimum_macos:
            raise ValueError('Executable deployment target does not match the request')
        state['generated_kernel_header_after_sha256'] = digest(header)
        if state['generated_kernel_header_before_sha256'] != state['generated_kernel_header_after_sha256']:
            raise ValueError('Generated kernel changed during the host-only rebuild')
        state.update(status='candidate_built_not_accepted', executable=str(executable), executable_sha256=digest(executable),
            recorded_minimum_macos=minimum.group(1), linked_libraries=subprocess.check_output(
                ['/usr/bin/otool', '-L', str(executable)], env=env, text=True))
        smoke = subprocess.run([str(executable), '--help'], capture_output=True, text=True, timeout=20)
        (out / 'native-help.log').write_text(smoke.stdout + smoke.stderr)
        if smoke.returncode or 'AutoDock-GPU version:' not in smoke.stdout:
            raise ValueError('Native executable loading/help smoke test failed')
        state['native_help_load_passed'] = True
        state['native_gpu_search_tested'] = False
    except BaseException as exc:
        state.update(status='failed', error=str(exc))
    save(); print(json.dumps(state, indent=2))
    return 0 if state['status'] == 'candidate_built_not_accepted' else 1


if __name__ == '__main__':
    raise SystemExit(main())
