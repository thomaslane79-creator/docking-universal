"""Native Windows bootstrap entry point, not a complete scientific installer.

Launch Python directly with argument lists. Never pass scientific paths through
cmd.exe, a batch-file dispatcher, Bash, WSL, or the launching terminal's Python.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from .runtime_layout import executable_directories


PREVIEW_NOTICE = (
    "Native Windows development preview: desktop/host startup and prepared-input "
    "Vina only. Native preparation, full screening/reports and PyMOL/GPU acceptance "
    "are unfinished. Do not use this preview as a validated scientific installation."
)


def isolated_environment(prefix: Path, inherited=None) -> dict[str, str]:
    environment = dict(os.environ if inherited is None else inherited)
    for key in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
        environment.pop(key, None)
    environment["PYTHONIOENCODING"] = "utf-8"
    environment["PYTHONUTF8"] = "1"
    environment["PATH"] = os.pathsep.join(
        [str(path) for path in executable_directories(prefix, windows=True) if path.is_dir()]
        + [environment.get("PATH", "")]
    )
    return environment


def launch_command(app: Path, configuration: dict, arguments: list[str]):
    """Return a shell-free command; unsupported workflows fail before mutation."""
    command, *options = arguments
    root = app.parent
    host = root / configuration["host_python"]
    gui = root / configuration["gui_python"]
    if command == "desktop":
        environment = isolated_environment(gui.parent)
        # A fresh, preview-only study root avoids opening production studies by
        # accident. An explicit --state-root remains the user's choice.
        defaults = ["--host-python", str(host), "--viewer-backend", "none",
                    "--state-root", str(root / "preview-studies")]
        return [str(gui), str(app / "docking-universal-desktop.py"), *defaults, *options], environment
    environment = isolated_environment(host.parent)
    environment["DOCKING_UNIVERSAL_PYTHON"] = str(host)
    if command == "runtime-inventory":
        if configuration.get("package_manager_conda"):
            # Private manager discovery is local to this inventory child, not
            # a persistent PATH change or fallback to somebody else's Conda.
            environment["PATH"] = str(Path(configuration["package_manager_conda"]).parent) + os.pathsep + environment["PATH"]
        return [str(host), str(app / "docking-universal-runtime-inventory.py"), *options], environment
    if command == "dock":
        # This preview provides exactly one verified CPU engine, not an AD4 or
        # QuickVina protocol substitution. Do not override an explicit choice.
        prohibited = ("--engine", "--engine-command", "--engine-env", "--vina-backend")
        if any(value.split("=", 1)[0] in prohibited for value in options):
            raise ValueError("The native preview dock command uses only its pinned Vina 1.2.7 CLI; engine overrides are not supported")
        engine = root / configuration["vina_executable"]
        if hashlib.sha256(engine.read_bytes()).hexdigest() != configuration["vina_sha256"]:
            raise ValueError("Pinned native Vina checksum no longer matches; no docking was started")
        return [str(host), str(app / "docking_universal_dock.py"), *options,
                "--engine", "vina", "--engine-command", str(engine), "--vina-backend", "cli"], environment
    raise ValueError(f"'{command}' is not available in the native Windows bootstrap yet. No scientific stage was started.")


def main(arguments=None, *, app: Path | None = None) -> int:
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    app = app or Path(__file__).resolve().parents[1]
    command = arguments[0] if arguments else "help"
    if command in {"help", "--help", "-h"}:
        print(PREVIEW_NOTICE)
        print("Commands: version, check-install, runtime-inventory, desktop, dock")
        return 0
    if command in {"version", "--version", "-V"}:
        print("Docking Universal " + (app / "VERSION").read_text(encoding="utf-8").strip() + " (native Windows preview)")
        return 0
    print(PREVIEW_NOTICE, file=sys.stderr)
    try:
        configuration = json.loads((app / "native-preview.json").read_text(encoding="utf-8"))
        if configuration.get("schema") != "docking-universal-native-preview-v1":
            raise ValueError("Unrecognized native installation record")
        if command == "check-install":
            if arguments[1:] not in ([], ["--full"]):
                raise ValueError("Usage: check-install [--full]")
            for key in ("host_python", "gui_python", "vina_executable"):
                if not (app.parent / configuration[key]).is_file():
                    raise ValueError(f"Missing preview runtime: {key}")
            engine = app.parent / configuration["vina_executable"]
            if hashlib.sha256(engine.read_bytes()).hexdigest() != configuration["vina_sha256"]:
                raise ValueError("Pinned native Vina checksum mismatch")
            print("Bootstrap files: present. Full scientific installation: NOT COMPLETE.")
            return 1 if "--full" in arguments else 0
        command_line, environment = launch_command(app, configuration, arguments)
        return subprocess.call(command_line, env=environment, shell=False)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
