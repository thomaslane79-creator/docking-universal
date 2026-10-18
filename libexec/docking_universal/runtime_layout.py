"""Explicit native Conda layouts; never infer Windows prefixes as Unix bin/."""
from __future__ import annotations

import os
from pathlib import Path


def prefix_for_python(executable: Path | str, *, windows: bool | None = None) -> Path:
    path = Path(executable)
    windows = os.name == "nt" if windows is None else windows
    return path.parent if windows else path.parent.parent


def executable_directories(prefix: Path | str, *, windows: bool | None = None) -> list[Path]:
    root = Path(prefix)
    windows = os.name == "nt" if windows is None else windows
    if windows:
        return [root, root / "Scripts", root / "Library/bin", root / "Library/lib/jvm/bin"]
    return [root / "bin", root / "lib/jvm/bin"]
