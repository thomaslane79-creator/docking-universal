"""Keep pinned PLIP/OpenBabel I/O local and independent of Windows filenames.

PLIP writes protonated PDBs through OpenBabel's filename API. Relative ASCII
filenames avoid its narrow Windows path boundary, even when the working
directory itself contains Unicode. No structure text or analysis flag changes.
"""
from __future__ import annotations

from pathlib import Path
import platform
import shutil
import sys

from docking_universal.tool_commands import locate_script_tool, script_command


def plip_invocation(executable: str, source: Path, output: Path, *flags: str):
    if platform.system() != "Windows":
        return [executable, "-f", str(source), *flags, "-o", str(output)], None
    # The output is already a fresh, owned directory. Do not use a global
    # temporary folder, change process-wide cwd, or round-trip the structure.
    staged = output / "plip_input.pdb"
    if staged.exists():
        raise FileExistsError("Refusing to overwrite a staged PLIP input")
    shutil.copyfile(source, staged)
    if executable == "plip":
        command = [sys.executable, "-m", "plip.plipcmd"]
    else:
        # Explicit custom executables remain authoritative. Literal .py tools
        # use the scientific interpreter, never Windows file associations.
        resolved = locate_script_tool(executable) or executable
        command = script_command(resolved)
    return [*command, "-f", staged.name, *flags, "-o", "."], output
