"""Prepare redistributable runtime assets, never alter an installed environment.

Inputs are pinned source checkouts and the already accepted binaries. This is a
maintainer operation, not an installer download or scientific validation.
"""
import argparse
import base64
import csv
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import zipfile

PYMOL_COMMIT = '5e8bfca5a7f5dc4d5e7f84fa1d15af707cc86e69'
GPU_COMMIT = 'e63e6f6280ebfad18caa3e8f48afdc269e79e063'
GPU_SHA = '062b5816f8342fa4c2150d65852e83f52940fe2f2cb603710e27527b33a9d02a'
WHEEL_SHA = 'b982c0dd7c7cc260bd909ec1e9f3111cb3c01e7138ab03e62c9e6b36714cfd26'
GRID_COMMIT = '18879446506d1750510e26f8a5344b159533dbae'


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_archive(source, target, commit, git):
    observed = subprocess.check_output([git, '-C', str(source), 'rev-parse', 'HEAD'], text=True).strip()
    if observed != commit:
        raise ValueError(f'Unexpected source commit: {observed}')
    changes = set(filter(None, subprocess.check_output(
        [git, '-C', str(source), 'diff', '--name-only', 'HEAD'], text=True).splitlines()))
    allowed = ({'device/calcMergedEneGra.cl', 'host/src/main.cpp', 'host/inc/stringify.h'}
               if commit == GPU_COMMIT else set())
    if changes - allowed:
        raise ValueError('Unexpected source modifications: ' + ', '.join(sorted(changes - allowed)))
    files = subprocess.check_output([git, '-C', str(source), 'ls-files', '-z']).split(b'\0')
    # Include the actual patched tracked sources, including the generated kernel
    # header. Exclude local runs, build products and Git account metadata.
    with target.open('wb') as raw, gzip.GzipFile(fileobj=raw, mode='wb', mtime=0, filename='') as compressed:
        with tarfile.open(fileobj=compressed, mode='w') as archive:
            for item in sorted(filter(None, files)):
                path = source / os.fsdecode(item)
                info = archive.gettarinfo(str(path), arcname=commit + '/' + os.fsdecode(item))
                info.uid = info.gid = info.mtime = 0
                info.uname = info.gname = ''
                if info.isfile():
                    with path.open('rb') as stream:
                        archive.addfile(info, stream)
                else:
                    archive.addfile(info)


def relocate_wheel(source, target):
    if digest(source) != WHEEL_SHA:
        raise ValueError('Input PyMOL wheel differs from the pinned prototype')
    with tempfile.TemporaryDirectory(prefix='du-wheel-') as folder:
        root = Path(folder)
        with zipfile.ZipFile(source) as wheel:
            wheel.extractall(root)
        tool_env = {**os.environ, 'DEVELOPER_DIR': '/Library/Developer/CommandLineTools'}
        for extension in sorted(root.rglob('*.so')):
            report = subprocess.check_output(['/usr/bin/otool', '-l', str(extension)], env=tool_env, text=True)
            lines = report.splitlines()
            for index, line in enumerate(lines):
                if line.strip() == 'cmd LC_RPATH':
                    path = lines[index + 2].strip().split('path ', 1)[1].rsplit(' (offset', 1)[0]
                    if path.startswith('/'):
                        # Both extension packages are located below site-packages.
                        # Resolve to the new environment's lib, not this machine.
                        levels = len(extension.parent.relative_to(root).parts) + 2
                        relative = '@loader_path/' + '/'.join(['..'] * levels)
                        subprocess.run(['/usr/bin/install_name_tool', '-rpath', path, relative, str(extension)],
                                       env=tool_env, check=True)
            subprocess.run(['/usr/bin/codesign', '--force', '--sign', '-', str(extension)], check=True)
        record = next(root.glob('*.dist-info/RECORD'))
        rows = []
        for path in sorted(root.rglob('*')):
            if path.is_file() and path != record:
                data = path.read_bytes()
                encoded = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).decode().rstrip('=')
                rows.append([path.relative_to(root).as_posix(), 'sha256=' + encoded, str(len(data))])
        rows.append([record.relative_to(root).as_posix(), '', ''])
        with record.open('w', newline='') as stream:
            csv.writer(stream).writerows(rows)
        with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as wheel:
            for path in sorted(root.rglob('*')):
                if path.is_file():
                    info = zipfile.ZipInfo(path.relative_to(root).as_posix(), (2026, 10, 17, 0, 0, 0))
                    info.external_attr = path.stat().st_mode << 16
                    info.compress_type = zipfile.ZIP_DEFLATED
                    wheel.writestr(info, path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('pymol-wheel', 'pymol-source', 'gpu-executable', 'gpu-source', 'autogrid-source', 'autogrid-executable', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--git', default='git')
    args = parser.parse_args()
    if digest(args.gpu_executable) != GPU_SHA:
        raise ValueError('GPU executable is not the accepted build')
    args.output.mkdir(parents=True, exist_ok=False)
    wheel = args.output / args.pymol_wheel.name
    relocate_wheel(args.pymol_wheel, wheel)
    source_archive(args.pymol_source, args.output / 'pymol-source.tar.gz', PYMOL_COMMIT, args.git)
    source_archive(args.gpu_source, args.output / 'autodock-gpu-source.tar.gz', GPU_COMMIT, args.git)
    for source, name in ((args.gpu_executable, 'adgpu_guarded_128'), (args.autogrid_executable, 'autogrid4'),
                         (args.autogrid_source, 'autogrid-source.tar.gz'),
                         (args.pymol_source / 'LICENSE', 'LICENSE-PyMOL'),
                         (args.gpu_source / 'LICENSE', 'LICENSE-AutoDock-GPU'),
                         (args.gpu_source / 'LICENSE_LGPL', 'LICENSE-AutoDock-GPU-LGPL')):
        shutil.copy2(source, args.output / name)
    with tarfile.open(args.autogrid_source) as archive:
        member = next(m for m in archive.getmembers() if m.name.endswith('/COPYING'))
        (args.output / 'LICENSE-AutoGrid').write_bytes(archive.extractfile(member).read())
    manifest = {'schema': 'docking-universal-mac-runtimes-v1', 'system': 'Darwin', 'machine': 'arm64',
        'pymol': {'wheel': wheel.name, 'python': '3.12', 'minimum_macos': '15.0', 'upstream_commit': PYMOL_COMMIT,
                  'upstream_url': 'https://github.com/schrodinger/pymol-open-source',
                  'original_wheel_sha256': WHEEL_SHA, 'change': 'Relative LC_RPATH and ad-hoc signature only; regenerated wheel RECORD'},
        'gpu': {'executable': 'adgpu_guarded_128', 'minimum_macos': '26.2', 'upstream_commit': GPU_COMMIT,
                'upstream_url': 'https://github.com/ccsb-scripps/AutoDock-GPU',
                'changes': 'Local-memory synchronization barrier and rejected Apple one-work-item configuration; see source/patch'},
        'autogrid': {'executable': 'autogrid4', 'version': '4.2.8', 'upstream_commit': GRID_COMMIT,
                     'upstream_url': 'https://github.com/ccsb-scripps/AutoGrid'},
        'files': {p.name: {'sha256': digest(p), 'bytes': p.stat().st_size} for p in sorted(args.output.iterdir())}}
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'asset_bytes': sum(p.stat().st_size for p in args.output.iterdir()), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
