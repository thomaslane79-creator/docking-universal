"""Run an explicitly located Python tool without Windows file associations."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys


def locate_script_tool(name: str, *, path: str | None = None) -> str | None:
    found = shutil.which(name, path=path)
    if found or os.name != "nt" or Path(name).name != name:
        return found
    # Some scientific wheels install a literal script rather than a PE entry
    # point. PATHEXT need not contain .PY; do not require global associations.
    for parent in (path or os.environ.get("PATH", "")).split(os.pathsep):
        candidate = Path(parent) / name
        if candidate.is_file():
            return str(candidate)
    return None


def script_command(executable: str | Path, *arguments: str | Path) -> list[str]:
    original = str(executable)
    if os.name != "nt":
        # In particular keep './tool': removing './' would search PATH and
        # could execute a different program instead of the explicitly chosen one.
        return [original, *(str(value) for value in arguments)]
    executable = Path(original)
    if executable.suffix.lower() in {".bat", ".cmd"}:
        raise ValueError("Scientific commands must not pass coordinates through a Windows command shell")
    prefix = [sys.executable, original] if executable.suffix.lower() == ".py" else [original]
    return [*prefix, *(str(value) for value in arguments)]
