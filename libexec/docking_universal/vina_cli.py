"""Byte-preserving path transport for the pinned native Windows Vina CLI."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile

PATH_FLAGS = {'--receptor': 'receptor.pdbqt', '--ligand': 'ligand.pdbqt',
              '--config': 'box.conf', '--out': 'pose.pdbqt'}


def needs_native_transport(arguments, *, windows=None):
    if not (os.name == 'nt' if windows is None else windows):
        return False
    return any(arguments[index] in PATH_FLAGS and not str(arguments[index + 1]).isascii()
               for index in range(len(arguments) - 1))


def run_native_vina(command, arguments, *, environment, log, staging_root=None):
    """Resolve/copy inputs before search; never retry or alter a scientific flag.

    CreateProcess receives the original pinned executable. Its data arguments
    are short ASCII names in a private local working directory. Input/config
    bytes and output pose bytes are not decoded, rewritten or re-optimized.
    """
    arguments = list(map(str, arguments))
    sources = {flag: Path(arguments[arguments.index(flag) + 1]).resolve() for flag in PATH_FLAGS}
    root = staging_root or environment.get('DOCKING_UNIVERSAL_NATIVE_STAGING_ROOT')
    parent = Path(root or tempfile.gettempdir()).resolve()
    if not str(parent).isascii():
        raise ValueError('Native Vina requires an ASCII local staging folder; no search was started')
    parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='du-vina-', dir=parent) as temporary:
        work = Path(temporary)
        for flag, name in PATH_FLAGS.items():
            arguments[arguments.index(flag) + 1] = name
            if flag != '--out':
                shutil.copyfile(sources[flag], work / name)
        completed = subprocess.run([*map(str, command), *arguments], cwd=work,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=dict(environment))
        output = work / PATH_FLAGS['--out']
        if output.is_file():
            shutil.copyfile(output, sources['--out'])
        return completed
