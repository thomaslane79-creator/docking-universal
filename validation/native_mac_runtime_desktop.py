"""Launch the installed workspace with isolated Qt preferences and study root."""
import argparse
import json
import os
from pathlib import Path
import runpy
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prefix', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    main_prefix = args.prefix / 'envs/docking-universal'
    runtime = main_prefix / 'libexec/docking-universal'
    config = main_prefix / 'share/docking-universal/adgpu/runtime.json'
    sys.path.insert(0, str(runtime))
    os.environ['DOCKING_UNIVERSAL_ADGPU_CONFIG'] = str(config)
    from docking_universal.gui.qt import QtCore
    from docking_universal.ad4_gpu import runtime_descriptor
    descriptor = runtime_descriptor()
    if not Path(descriptor['executable']).is_relative_to(main_prefix):
        raise ValueError('GUI resolved a GPU outside the fresh scientific prefix')
    QtCore.QSettings.setDefaultFormat(QtCore.QSettings.Format.IniFormat)
    for scope in (QtCore.QSettings.Scope.UserScope, QtCore.QSettings.Scope.SystemScope):
        QtCore.QSettings.setPath(QtCore.QSettings.Format.IniFormat, scope, str(args.out / 'qt-settings'))
    (args.out / 'runtime-probe.json').write_text(json.dumps(descriptor, indent=2) + '\n')
    sys.argv = [str(runtime / 'docking-universal-desktop.py'), '--state-root', str(args.out / 'studies'),
        '--study', 'fresh-native-launch', '--create-name', 'Fresh native installation acceptance',
        '--viewer-backend', 'embedded', '--host-python', str(main_prefix / 'bin/python'),
        '--pymol', str(args.prefix / 'envs/docking-universal-pymol-next/bin/pymol'),
        '--screenshot', str(args.out / 'workspace.png')]
    runpy.run_path(sys.argv[0], run_name='__main__')


if __name__ == '__main__':
    main()
