"""Build and register the upstream Qt Cocoa accessibility repair.

The native plugin stays in an app-owned directory. Conda's Qt libraries and
original plugin are never replaced. Registration pins the exact libraries used
to build it; startup rejects a stale or modified runtime before loading code.
Only the already reproduced Apple-Silicon Qt 6.11.2 profile is supported here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from uuid import uuid4

SCHEMA = 'docking-universal-cocoa-accessibility-v1'
LIBRARIES = ('lib/libQt6Core.6.dylib', 'lib/libQt6Gui.6.dylib')


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def specification():
    return json.loads(Path(__file__).with_name('data').joinpath('qt-cocoa-accessibility.json').read_text())


def runtime_root(prefix):
    return Path(prefix) / 'share/docking-universal/qt-cocoa-accessibility'


def verified_plugin_root(prefix, qt_version, *, system=None, machine=None):
    """No Qt import: also testable on Windows/Linux with synthetic assets."""
    if (system or platform.system()) != 'Darwin':
        return None
    prefix = Path(prefix).resolve()
    root = runtime_root(prefix)
    manifest = root / 'runtime.json'
    if not root.exists():
        return None
    try:
        record = json.loads(manifest.read_text())
        spec = specification()
        if (record['schema'] != SCHEMA or record['qt_version'] != qt_version
                or qt_version != spec['qt_version']
                or record['architecture'] != (machine or platform.machine())
                or record['architecture'] != spec['architecture']
                or Path(record['qt_prefix']).resolve() != prefix
                or record['source_commit'] != spec['qt_source']['commit']
                or record['patch_commit'] != spec['patch']['commit']
                or set(record['libraries']) != set(LIBRARIES)):
            raise ValueError('runtime identity does not match this Qt installation')
        plugin = root / 'plugins/platforms/libqcocoa.dylib'
        if plugin.is_symlink() or sha256(plugin) != record['plugin_sha256']:
            raise ValueError('Cocoa plugin checksum changed')
        for name in LIBRARIES:
            if sha256(prefix / name) != record['libraries'][name]:
                raise ValueError('Qt library changed: ' + name)
        return root / 'plugins'
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError('Docking Universal Cocoa accessibility repair is stale or damaged: '
                           + str(exc) + '. Re-run the installer to rebuild it for this GUI runtime.') from exc


def _download(record, destination):
    destination = Path(destination)
    if not destination.exists():
        partial = destination.with_suffix(destination.suffix + '.partial')
        with urllib.request.urlopen(record['url'], timeout=90) as response, partial.open('wb') as output:
            shutil.copyfileobj(response, output)
        if sha256(partial) != record['sha256']:
            raise ValueError('Downloaded source checksum mismatch: ' + destination.name)
        partial.replace(destination)
    if sha256(destination) != record['sha256']:
        raise ValueError('Cached source checksum mismatch: ' + destination.name)


def _verified_sources(archive, destination, included, allowed_changes=None):
    """Extract regular source files and verify cached files against the archive.

    The only allowed cached modifications are the two pinned upstream fixes.
    Verify all Cocoa build inputs, not just the downloaded archive's checksum.
    """
    allowed_changes = allowed_changes or {}
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            relative = '/'.join(Path(member.name).parts[1:])
            if not any(relative.startswith(part) for part in included) or not member.isfile():
                continue
            path = destination / member.name
            if not path.resolve().is_relative_to(destination.resolve()):
                raise ValueError('Source archive path escapes its destination')
            data = bundle.extractfile(member).read()
            expected = hashlib.sha256(data).hexdigest()
            if path.exists():
                if sha256(path) not in {expected, *allowed_changes.get(relative, ())}:
                    raise ValueError('Cached build source changed: ' + relative)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)


def _run(command, log, *, environment=None):
    with Path(log).open('w') as output:
        try:
            subprocess.run([str(value) for value in command], env=environment,
                           stdout=output, stderr=subprocess.STDOUT, check=True)
        except subprocess.CalledProcessError as exc:
            raise RuntimeError('Cocoa repair step failed; inspect ' + str(Path(log).resolve())) from exc


def build(prefix, output, *, install=False, jobs=4):
    spec = specification()
    prefix, output = Path(prefix).resolve(), Path(output).resolve()
    if platform.system() != 'Darwin' or platform.machine() != spec['architecture']:
        raise ValueError('This Cocoa repair build supports Apple-Silicon macOS only')
    if sys.version_info < (3, 12):
        raise ValueError('Build this plugin with the GUI environment Python 3.12 or newer')
    version = subprocess.check_output([prefix/'bin/python', '-I', '-c',
        'from PyQt6.QtCore import qVersion; print(qVersion())'], text=True).strip()
    if version != spec['qt_version']:
        raise ValueError('The backport requires Qt ' + spec['qt_version'] + '; found ' + version)
    if not shutil.which('xcrun') or subprocess.run(['xcrun', '--find', 'clang++'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise ValueError('Apple Command Line Tools are required to build the Cocoa repair. Install them with xcode-select --install, then run the installer again.')
    output.mkdir(parents=True, exist_ok=True)
    print('Checking pinned Qt sources and the upstream accessibility repair…', flush=True)
    libraries = {name: sha256(prefix/name) for name in LIBRARIES}
    qt_archive = output/'qtbase-6.11.2.tar.gz'
    vk_archive = output/'vulkan-headers-1.4.328.tar.gz'
    patch = output/'upstream-accessibility.patch'
    for record, path in ((spec['qt_source'], qt_archive), (spec['vulkan_headers'], vk_archive), (spec['patch'], patch)):
        _download(record, path)
    _verified_sources(qt_archive, output, ('src/plugins/platforms/cocoa/', 'LICENSES/'),
                      spec['patch']['source_files'])
    _verified_sources(vk_archive, output, ('include/', 'LICENSE'))
    source = output/('qtbase-'+spec['qt_source']['commit'])
    vk_source = output/('Vulkan-Headers-'+spec['vulkan_headers']['commit'])
    original = [sha256(source/name) for name in spec['patch']['source_files']]
    patched = [values[1] for values in spec['patch']['source_files'].values()]
    if original != patched:
        if original != [values[0] for values in spec['patch']['source_files'].values()]:
            raise ValueError('Partially applied or unexpected Cocoa source changes')
        parts = patch.read_text().split('diff --git ')[1:]
        parts = [value for value in parts if value.startswith('a/src/plugins/platforms/cocoa/')]
        if len(parts) != 2:
            raise ValueError('Unexpected upstream Cocoa patch file count')
        filtered = output/'cocoa-only-accessibility.patch'
        filtered.write_text(''.join('diff --git '+value for value in parts))
        _run(['/usr/bin/patch', '--batch', '-p1', '-i', filtered, '-d', source], output/'patch.log')
    if [sha256(source/name) for name in spec['patch']['source_files']] != patched:
        raise ValueError('Upstream accessibility patch output did not match its pinned sources')
    tools = output/'build-tools'
    cmake = tools/'cmake/data/bin/cmake'
    ninja = tools/'bin/ninja'
    if not cmake.exists() or not ninja.exists():
        print('Installing CMake and Ninja in the private build cache…', flush=True)
        _run([sys.executable, '-m', 'pip', 'install', '--no-deps', '--target', tools,
              'cmake=='+spec['build_tools']['cmake'], 'ninja=='+spec['build_tools']['ninja']], output/'build-tools.log')
    if (spec['build_tools']['cmake'] not in subprocess.check_output([cmake, '--version'], text=True)
            or subprocess.check_output([ninja, '--version'], text=True).strip() != spec['build_tools']['ninja_reported_version']):
        raise ValueError('Unexpected cached CMake/Ninja version')
    project = output/'cocoa-project'; project.mkdir(exist_ok=True)
    # Bracket-quoted CMake paths preserve spaces and do not expand variables.
    (project/'CMakeLists.txt').write_text('''cmake_minimum_required(VERSION 3.22)
project(DockingUniversalQtCocoa VERSION 6.11.2 LANGUAGES C CXX OBJCXX)
set(QT_FIND_PRIVATE_MODULES TRUE)
find_package(Qt6 6.11.2 EXACT REQUIRED COMPONENTS Core Gui BuildInternals)
qt_prepare_standalone_project()
qt_set_language_standards()
set(QT_QPA_PLATFORMS cocoa)
foreach(framework Foundation AppKit Carbon CoreServices CoreVideo IOKit IOSurface Metal QuartzCore UniformTypeIdentifiers)
    find_library(FW${framework} ${framework} REQUIRED)
endforeach()
add_subdirectory([=['''+str(source/'src/plugins/platforms/cocoa')+''']=] cocoa)
target_include_directories(QCocoaIntegrationPlugin SYSTEM PRIVATE "${QT_BUILD_INTERNALS_RELOCATABLE_INSTALL_PREFIX}/include")
target_include_directories(QCocoaIntegrationPlugin SYSTEM PRIVATE [=['''+str(vk_source/'include')+''']=])
''')
    environment = dict(os.environ, PATH=str(tools/'bin')+os.pathsep+str(prefix/'bin')+os.pathsep+os.environ.get('PATH',''))
    configuration = [cmake, '-S', project, '-B', output/'build', '-G', 'Ninja',
        '-DCMAKE_PREFIX_PATH='+str(prefix), '-DCMAKE_INSTALL_PREFIX='+str(output/'stage'),
        '-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0', '-DCMAKE_OSX_ARCHITECTURES=arm64', '-DCMAKE_BUILD_TYPE=Release',
        '-DQT_NO_XCODE_MIN_VERSION_CHECK=ON', '-DQT_SKIP_AUTO_PLUGIN_INCLUSION=ON', '-DQT_GENERATE_SBOM=OFF']
    # The command-line SDK/compiler suffices for this plugin. Keep Qt's SDK
    # minimum/maximum checks and warnings; only the full-Xcode version probe is skipped.
    print('Configuring and compiling the Mac window component; logs: ' + str(output), flush=True)
    _run(configuration, output/'configure.log', environment=environment)
    _run([cmake, '--build', output/'build', '--target', 'QCocoaIntegrationPlugin', '--parallel', str(jobs)], output/'build.log', environment=environment)
    plugin = output/'build/lib/qt6/plugins/platforms/libqcocoa.dylib'
    _run(['codesign', '--verify', '--verbose=2', plugin], output/'codesign.log')
    if libraries != {name: sha256(prefix/name) for name in LIBRARIES}:
        raise ValueError('Qt libraries changed during the build')
    record = {'schema': SCHEMA, 'qt_version': version, 'architecture': spec['architecture'],
              'qt_prefix': str(prefix), 'plugin_sha256': sha256(plugin), 'libraries': libraries,
              'source_commit': spec['qt_source']['commit'], 'patch_commit': spec['patch']['commit'],
              'source_receipts': spec, 'sdk_version': subprocess.check_output(['xcrun','--show-sdk-version'], text=True).strip(),
              'scope': 'Cocoa accessibility repair; no scientific method or receptor change'}
    (output/'runtime.json').write_text(json.dumps(record, indent=2)+'\n')
    if install:
        root = runtime_root(prefix); root.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.cocoa-runtime-', dir=root.parent))
        backup = None
        try:
            target = temporary/'plugins/platforms/libqcocoa.dylib';target.parent.mkdir(parents=True)
            shutil.copy2(plugin, target)
            for name in ('LGPL-3.0-only.txt', 'GPL-3.0-only.txt'):
                shutil.copy2(source/'LICENSES'/name, temporary/name)
            shutil.copy2(patch, temporary/'upstream-accessibility.patch')
            shutil.copy2(project/'CMakeLists.txt', temporary/'BuildRecipe.cmake')
            (temporary/'runtime.json').write_text(json.dumps(record, indent=2)+'\n')
            if root.exists():
                backup = root.with_name(root.name+'-previous-'+uuid4().hex[:12])
                root.replace(backup)
            try:
                temporary.replace(root)
            except OSError:
                if backup is not None and not root.exists():
                    backup.replace(root)
                raise
        finally:
            if temporary.exists():shutil.rmtree(temporary)
        verified_plugin_root(prefix, version)
        print('Registered the verified Cocoa repair in ' + str(root), flush=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', type=Path, default=Path(sys.prefix))
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--install', action='store_true')
    parser.add_argument('--jobs', type=int, default=4)
    args = parser.parse_args()
    if args.jobs < 1 or args.jobs > 8:
        parser.error('Use one to eight compiler processes')
    result = build(args.prefix, args.build_root, install=args.install, jobs=args.jobs)
    print(json.dumps({'qt_version':result['qt_version'],'plugin_sha256':result['plugin_sha256'],'installed':args.install}))


if __name__ == '__main__':
    main()
