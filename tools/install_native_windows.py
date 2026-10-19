"""Isolated native Windows bootstrap; never overwrites another installation."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def reserve_destination(destination: Path, conda: Path, *, owned_manager: bool,
                        executing_python: Path | None = None, asset: dict | None = None,
                        manager_root: Path | None = None) -> dict:
    if not owned_manager:
        destination.mkdir(parents=True, exist_ok=False)
        return {"mode": "explicit_existing_conda"}
    # Only the PowerShell-created bootstrap may precede Python's installer.
    # Never make exist_ok=True a general way to overwrite an old installation.
    if not destination.is_dir() or {p.name for p in destination.iterdir()} != {".bootstrap"}:
        raise ValueError("Owned-manager handoff requires only its fresh bootstrap directory")
    bootstrap = destination / ".bootstrap"
    if bootstrap.resolve().parent != destination.resolve():
        raise ValueError("Private manager escaped its owned installation directory")
    record = json.loads((bootstrap / "manager-status.json").read_text(encoding="utf-8"))
    identity = record.get("install_id", "")
    if manager_root is None or not re.fullmatch(r"[0-9a-f]{32}", identity):
        raise ValueError("Private manager provenance lacks its fresh installation identity")
    prefix = manager_root / identity
    if prefix.resolve().parent != manager_root.resolve():
        raise ValueError("Private manager escaped its owned manager root")
    expected_conda = prefix / "Scripts/conda.exe"
    expected_python = prefix / "python.exe"
    if (conda.resolve() != expected_conda.resolve() or
            (executing_python or Path(sys.executable)).resolve() != expected_python.resolve() or
            not expected_conda.is_file() or not expected_python.is_file()):
        raise ValueError("Owned-manager handoff requires its exact private Python/Conda")
    asset = asset or json.loads((ROOT / "dependencies/miniforge-windows.json").read_text(encoding="utf-8"))
    if record.get("status") != "installed" or record.get("asset") != asset or Path(record.get("private_prefix", "")).resolve() != prefix.resolve():
        raise ValueError("Private manager provenance is incomplete or changed")
    owner = json.loads((prefix / "docking-universal-owner.json").read_text(encoding="utf-8"))
    if (owner.get("schema") != "docking-universal-private-manager-v1" or
            Path(owner.get("installation", "")).resolve() != destination.resolve() or
            owner.get("install_id") != identity or owner.get("sha256") != asset["sha256"]):
        raise ValueError("Private manager owner does not match this installation")
    if hashlib.sha256((bootstrap / asset["filename"]).read_bytes()).hexdigest() != asset["sha256"]:
        raise ValueError("Private manager installer checksum mismatch")
    return {"mode": "application_owned", "prefix": str(prefix), "install_id": identity, "asset": asset}


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
    for name in ("environment.yml", "dependencies/vina-windows.json", "dependencies/p2rank.json"):
        original = source / name
        if original.is_file():
            destination = target / "installation-assets" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(original, destination)
            hashes["installation-assets/" + name] = hashlib.sha256(destination.read_bytes()).hexdigest()
    return hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", required=True, type=Path)
    parser.add_argument("--conda", required=True, type=Path)
    parser.add_argument("--owned-manager", action="store_true", help="Validated handoff from the fresh PowerShell bootstrap only")
    parser.add_argument("--manager-root", type=Path)
    parser.add_argument("--bootstrap-only", action="store_true", help="Transport-only acceptance; skip scientific dependencies explicitly")
    args = parser.parse_args()
    if platform.system() != "Windows" or platform.machine().lower() not in {"amd64", "x86_64"}:
        parser.error("This preview requires native x64 Windows, not an emulated platform")
    destination = args.destination.resolve()
    if not args.bootstrap_only and not args.owned_manager and not str(destination).isascii():
        parser.error("The expert existing-Conda scientific path needs an ASCII destination for pinned Java 17. Use the default private-manager installer to keep a Unicode application folder. Nothing was installed.")
    # A fresh directory is mandatory. Failed/old installs are inspectable and
    # never removed automatically; reruns use another destination.
    manager = reserve_destination(destination, args.conda, owned_manager=args.owned_manager, manager_root=args.manager_root)
    record = {"status": "installing", "scope": "native Windows bootstrap only; scientific stages unfinished",
              "system": platform.platform(), "steps": [], "package_manager": manager}
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
                         "vina_sha256": asset["sha256"], "package_manager_conda": str(args.conda.resolve()),
                         "scientific_stages_supported": False}
        if not args.bootstrap_only:
            sys.path.insert(0, str(app))
            from docking_universal.windows_scientific_install import install_scientific_runtime
            # The pinned Windows Java 17 launcher cannot locate java.dll from
            # a non-ASCII installation prefix (native acceptance 114ec66).
            # Keep its entire unchanged scientific environment under OUR fresh
            # private manager identity, never a foreign user's Conda base.
            science_prefix = ((Path(manager["prefix"]) / "runtimes/scientific")
                              if manager["mode"] == "application_owned" else destination / "runtimes/scientific")
            if manager["mode"] == "application_owned":
                configuration["scientific_manager"] = {key: manager[key] for key in ("prefix", "install_id", "asset")}
            receipt = install_scientific_runtime(conda=args.conda, prefix=science_prefix,
                app=app, source_assets=app / "installation-assets", work=destination / ".bootstrap/scientific-setup")
            receipt_path = destination / ".bootstrap/scientific-setup/scientific-install.json"
            configuration.update(scientific_python=str(science_prefix / "python.exe"),
                                 scientific_dependencies_installed=True,
                                 scientific_receipt=str(receipt_path.relative_to(destination).as_posix()),
                                 scientific_receipt_sha256=hashlib.sha256(receipt_path.read_bytes()).hexdigest())
            from docking_universal.windows_desktop import WORKFLOW
            configuration["scientific_desktop_workflow"] = WORKFLOW
            record["scientific_dependencies"] = {key: receipt.get(key) for key in ("status", "imports", "steps", "scientific_gui_enabled", "interactive_viewer_accepted", "gpu_accepted")}
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
        record["status"] = "bootstrap_installed" if args.bootstrap_only else "scientific_dependencies_installed"
        print(f"Native preview installed in {destination}. " + ("Scientific dependencies were explicitly skipped." if args.bootstrap_only else
              "Scientific dependencies are installed; full desktop/viewer acceptance is NOT complete."))
    except Exception as exc:
        record.update(status="failed", error=str(exc))
        print(f"Native bootstrap failed: {exc}", file=sys.stderr)
    (destination / "bootstrap-status.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return 0 if record["status"] in {"bootstrap_installed", "scientific_dependencies_installed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
