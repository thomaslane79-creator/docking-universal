"""Unchanged Meeko exporter with native literal/Unicode file transport."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from .tool_commands import script_command


def export_sdf(exporter, pdbqt, destination, *, windows=None, runner=None):
    runner = subprocess.run if runner is None else runner
    windows = os.name == 'nt' if windows is None else windows
    if not windows:
        return runner(script_command(exporter, pdbqt, '-s', destination), capture_output=True, text=True)
    # Pinned Meeko creates an RDKit filename writer internally. Use its same
    # executable/options on ASCII files, then copy its output bytes unchanged.
    staging = os.environ.get('DOCKING_UNIVERSAL_NATIVE_STAGING_ROOT')
    if staging:
        Path(staging).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='du-meeko-export-', dir=staging) as temporary:
        if not str(temporary).isascii():
            raise ValueError('Native Meeko export needs an ASCII staging folder; no export was started')
        source, output = Path(temporary) / 'input.pdbqt', Path(temporary) / 'output.sdf'
        shutil.copyfile(pdbqt, source)
        result = runner(script_command(exporter, source, '-s', output), capture_output=True, text=True)
        if result.returncode == 0:
            if not output.is_file() or not output.stat().st_size:
                raise RuntimeError('Meeko returned success without a nonempty new SDF; previous output was not reused')
            shutil.copyfile(output, destination)
        return result
