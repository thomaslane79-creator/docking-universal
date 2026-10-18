"""Isolated native Windows bootstrap; never overwrites another installation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def copy_application(source: Path, target: Path) -> dict[str, str]:
    """Copy code/bundled assets only, never a checkout, studies or node_modules."""
    source = source.resolve()
    files = sorted((source / "libexec").glob("*.py"))
    package = source / "libexec/docking_universal"
    files += sorted(path for path in package.rglob("*") if path.is_file()
                    and not {"node_modules", "__pycache__", ".git"}.intersection(path.parts)
                    and (path.suffix == ".py" or path.is_relative_to(package / "data/geostd")
                         or path.is_relative_to(package / "gui/assets/branding")
                         or path.is_relative_to(package / "poseedit_renderer/assets")
                         or (path.parent == package / "poseedit_renderer"
                             and path.suffix in {".cjs", ".mjs", ".json", ".md"})))
    if any(path.is_symlink() or any(parent.is_symlink() for parent in path.parents if parent != source.parent)
           for path in files):
        raise ValueError("Application staging refuses symlinks")
    target.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for source_file in files:
        relative = source_file.relative_to(source / "libexec")
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_file, destination)
        hashes[relative.as_posix()] = hashlib.sha256(destination.read_bytes()).hexdigest()
    for name in ("VERSION", "LICENSE"):
        shutil.copyfile(source / name, target / name)
        hashes[name] = hashlib.sha256((target / name).read_bytes()).hexdigest()
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--conda", required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("This preview requires native x64 Windows, not an emulated platform")
    destination = args.destination.resolve()
    # A fresh directory is mandatory. Failed/old installs are inspectable and
    # never removed automatically; reruns use another destination.
    destination.mkdir(parents=True, exist_ok=False)
    record = {"status": "installing", "scope": "native Windows bootstrap only; scientific stages unfinished",
              "system": platform.platform(), "steps": []}
    try:
        prefixes = {}
        with (destination / "bootstrap.log").open("w", encoding="utf-8") as log:
            for role in ("host", "gui"):
                prefixes[role] = destination / "runtimes" / role
                print(f"Creating isolated native {role} runtime…", flush=True)
                subprocess.run([str(args.conda), "env", "create", "--yes", "--prefix", str(prefixes[role]),
                                "--file", str(ROOT / f"environments/windows-bootstrap-{role}.yml")],
                               stdout=log, stderr=subprocess.STDOUT, check=True)
                record["steps"].append(f"{role}_environment_created")
        app = destination / "app"
        record["application_sha256"] = copy_application(ROOT, app)
        asset = json.loads((ROOT / "dependencies/vina-windows.json").read_text(encoding="utf-8"))
        print("Downloading checksum-pinned official Windows Vina 1.2.7…", flush=True)
        with urllib.request.urlopen(asset["url"], timeout=60) as response:
            binary = response.read()
        if hashlib.sha256(binary).hexdigest() != asset["sha256"] or binary[:2] != b"MZ":
            raise ValueError("Official Windows Vina checksum/format mismatch")
        engine = destination / "engines/vina.exe"
        engine.parent.mkdir()
        engine.write_bytes(binary)
        (engine.parent / "provenance.json").write_text(json.dumps(asset, indent=2) + "\n", encoding="utf-8")
        configuration = {"schema": "docking-universal-native-preview-v1", "host_python": "runtimes/host/python.exe",
                         "gui_python": "runtimes/gui/python.exe", "vina_executable": "engines/vina.exe",
                         "vina_sha256": asset["sha256"], "scientific_stages_supported": False}
        (app / "native-preview.json").write_text(json.dumps(configuration, indent=2) + "\n", encoding="utf-8")
        launchers = destination / "bin"
        launchers.mkdir()
        (launchers / "docking-universal.cmd").write_text(
            '@echo off\n"%~dp0..\\runtimes\\host\\python.exe" "%~dp0..\\app\\docking-universal-native.py" %*\nexit /b %errorlevel%\n', encoding="utf-8")
        (launchers / "docking-universal.ps1").write_text(
            "$ErrorActionPreference = 'Stop'\n"
            "& (Join-Path $PSScriptRoot '../runtimes/host/python.exe') (Join-Path $PSScriptRoot '../app/docking-universal-native.py') @args\n"
            "exit $LASTEXITCODE\n", encoding="utf-8")
        subprocess.run([str(prefixes["host"] / "python.exe"), str(app / "docking-universal-native.py"), "check-install"], check=True)
        record["status"] = "bootstrap_installed"
        print(f"Native bootstrap installed in {destination}. Full scientific installation is NOT complete.")
    except Exception as exc:
        record.update(status="failed", error=str(exc))
        print(f"Native bootstrap failed: {exc}", file=sys.stderr)
    (destination / "bootstrap-status.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return 0 if record["status"] == "bootstrap_installed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
