"""Native PowerShell bootstrap and actual Qt window/host startup acceptance.

Only status metadata is uploaded by CI. Synthetic fragments and screenshots
stay on the runner; this is not full preparation/report/PyMOL/GPU acceptance.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def installation_diagnostic(text, limit=8000):
    """Keep the root error as well as context, never Conda's environment dump.

    Used only when installation fails before any scientific fixture is created.
    Later study/engine/viewer logs must never enter the uploaded status record.
    """
    text = text.split("  environment variables:", 1)[0]
    if len(text) <= limit:
        return text
    marker = "\n[dependency diagnostic excerpt]\n"
    head = min(1000, limit // 4)
    return text[:head] + marker + text[-(limit - head - len(marker)):]


def persistent_runtime_configuration():
    """Observe only PATH/default-Python registry keys; never export values."""
    import winreg
    values = {}
    for label, hive, key, name in (
        ("user_path", winreg.HKEY_CURRENT_USER, "Environment", "Path"),
        ("machine_path", winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment", "Path"),
    ):
        try:
            with winreg.OpenKey(hive, key) as handle:
                values[label] = winreg.QueryValueEx(handle, name)
        except FileNotFoundError:
            values[label] = None
    for label, hive in (("user_python", winreg.HKEY_CURRENT_USER), ("machine_python", winreg.HKEY_LOCAL_MACHINE)):
        try:
            with winreg.OpenKey(hive, r"Software\Python\PythonCore") as handle:
                values[label] = tuple(sorted(winreg.EnumKey(handle, index) for index in range(winreg.QueryInfoKey(handle)[0])))
        except FileNotFoundError:
            values[label] = None
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--conda", type=Path)
    parser.add_argument("--without-prerequisites", action="store_true")
    parser.add_argument("--with-scientific", action="store_true", help="Default installer plus installed-code scientific acceptance")
    args = parser.parse_args()
    if platform.system() != "Windows":
        parser.error("Real native Windows required")
    if args.without_prerequisites == bool(args.conda):
        parser.error("Choose exactly one of --conda or --without-prerequisites")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    status = {"status": "running", "system": platform.platform(), "checks": [],
              "scientific_preparation_reports_pymol_gpu_accepted": False,
              "no_prerequisites_path": args.without_prerequisites,
              "scientific_install_requested": args.with_scientific,
              "pristine_consumer_vm": False}
    try:
        persistent_before = persistent_runtime_configuration()
        destination = out / "Native Ω runtime with spaces"
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "install-windows.ps1"),
                   "-Destination", str(destination), "-AcceptDevelopmentPreview"]
        if not args.with_scientific:
            command.append("-BootstrapOnly")
        installer_environment = dict(os.environ)
        if args.without_prerequisites:
            # This driver uses setup-python, but the actual PowerShell child
            # sees OS tools only. Do not remove/rename hosted runner software.
            system = Path(os.environ["SystemRoot"]) / "System32"
            installer_environment["PATH"] = os.pathsep.join(map(str, [system, system / "WindowsPowerShell/v1.0"]))
            for key in list(installer_environment):
                if key.upper().startswith(("CONDA", "PYTHON", "_CE_")):
                    installer_environment.pop(key)
            check = subprocess.run([*command[:4], "-Command",
                "if ((Get-Command python,python3,conda -ErrorAction SilentlyContinue)) { exit 1 }; exit 0"],
                env=installer_environment, capture_output=True, timeout=30)
            if check.returncode:
                raise ValueError("Test environment still exposes Python/Conda")
            status["checks"].append("python_and_conda_absent_from_installer_child_path")
        else:
            command.extend(["-CondaExe", str(args.conda)])
        existing = out / "Do not overwrite"
        existing.mkdir()
        sentinel = existing / "study-sentinel.txt"
        sentinel.write_bytes(b"preserve existing user data")
        refused = command.copy()
        refused[refused.index("-Destination") + 1] = str(existing)
        rejected = subprocess.run(refused, env=installer_environment, capture_output=True, timeout=30)
        if rejected.returncode == 0 or sentinel.read_bytes() != b"preserve existing user data" or {p.name for p in existing.iterdir()} != {sentinel.name}:
            raise ValueError("Installer did not reject an existing target before mutation")
        status["checks"].append("existing_destination_rejected_before_download_or_mutation")
        with (out / "install.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, env=installer_environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=2700)
        status["checks"].append("native_powershell_fresh_bootstrap")
        installed = json.loads((destination / "bootstrap-status.json").read_text(encoding="utf-8"))
        if installed["status"] != ("scientific_dependencies_installed" if args.with_scientific else "bootstrap_installed"):
            raise ValueError("Bootstrap did not reach its explicit installed state")
        status["package_manager_mode"] = installed.get("package_manager", {}).get("mode")
        if args.without_prerequisites:
            if status["package_manager_mode"] != "application_owned":
                raise ValueError("No-prerequisites installation reused a foreign package manager")
            status["checks"].append("checksum_pinned_private_miniforge_installed_without_existing_conda")
        if persistent_runtime_configuration() != persistent_before:
            raise ValueError("Installer changed persistent PATH or default-Python registry configuration")
        status["checks"].append("persistent_path_and_python_registration_unchanged")
        host = destination / "runtimes/host/python.exe"
        gui = destination / "runtimes/gui/python.exe"
        app = destination / "app"
        entry = app / "docking-universal-native.py"
        configuration = json.loads((app / "native-preview.json").read_text(encoding="utf-8"))
        scientific_python = destination / configuration["scientific_python"] if args.with_scientific else host
        for launcher in (destination / "bin/docking-universal.ps1", destination / "bin/docking-universal.cmd"):
            if launcher.suffix == ".ps1":
                invoke = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher), "version"]
            else:
                # cmd is tested only at the human-facing launcher boundary;
                # application/engine invocations never route paths through it.
                invoke = [os.environ["COMSPEC"], "/d", "/c", str(launcher), "version"]
            result = subprocess.run(invoke, capture_output=True, text=True, timeout=30, check=True)
            if "native Windows preview" not in result.stdout:
                raise ValueError("Native public launcher did not dispatch the installed entry point")
        status["checks"].append("powershell_and_cmd_public_launchers")
        if subprocess.run([str(host), str(entry), "check-install", "--full"], capture_output=True, timeout=30).returncode != 1:
            raise ValueError("Preview incorrectly claimed a full scientific installation")
        status["checks"].append("full_install_claim_rejected")
        # Real installed host, not a fake JSON peer. Unsupported methods must
        # fail before registering a job or changing scientific state.
        probe = subprocess.run([str(scientific_python), str(ROOT / "validation/native_windows_host_probe.py"),
                                "--app", str(app), "--out", str(out / "host-probe"),
                                *(["--scientific"] if args.with_scientific else [])],
                               capture_output=True, text=True, encoding="utf-8", timeout=60, check=True)
        status["host"] = json.loads(probe.stdout)
        status["checks"].append("installed_unicode_host_and_fail_before_mutation")
        environment = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        environment.pop("PYTHONPATH", None)
        environment.pop("PYTHONHOME", None)
        # The normal installed dispatcher starts the actual Qt desktop and its
        # isolated host, captures its own window, and closes both normally.
        # Settings are runner-only; no user workstation data is involved.
        screenshot = out / "native-window.png"
        with (out / "desktop.log").open("w", encoding="utf-8") as log:
            subprocess.run([str(host), str(entry), "desktop", "--study", "native-test",
                            "--create-name", "Native Ω startup acceptance", "--screenshot", str(screenshot)],
                           env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=90)
        if not screenshot.is_file() or screenshot.stat().st_size < 10000:
            raise ValueError("Native Qt window did not render a nonempty capture")
        status["checks"].append("actual_installed_qt_desktop_and_host_startup")
        # Run the prepared-input adapter test using the INSTALLED Python/module
        # and pinned executable, not the repository's direct adapter path.
        subprocess.run([str(scientific_python), str(ROOT / "validation/native_windows_vina.py"), "--out", str(out / "vina"),
                        "--installed-entry", str(entry), "--engine", str(destination / "engines/vina.exe")],
                       env=environment, check=True, timeout=240)
        status["vina"] = json.loads((out / "vina/summary.json").read_text(encoding="utf-8"))
        status["checks"].append("installed_native_vina_exact_same_seed_repeat")
        if args.with_scientific:
            # Mask the parent's scientific and source-checkout paths too.
            # The installed dispatcher must reconstruct its owned runtime.
            environment.update(installer_environment)
            for key in ("PYTHONHOME", "PYTHONPATH"):
                environment.pop(key, None)
            with (out / "scientific-workflow.local.log").open("w", encoding="utf-8") as log:
                subprocess.run([str(scientific_python), str(ROOT / "validation/native_scientific_workflow.py"),
                    "--application-root", str(app), "--out", str(out / "installed-scientific")],
                    env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1800)
            status["checks"].append("installed_public_dispatch_preparation_screening_reports_and_local_interactions")
            status["installed_scientific_workflow"] = "passed"
            with (out / "desktop-workflow.local.log").open("w", encoding="utf-8") as log:
                fixtures = out / "installed-scientific/Public inputs — native Unicode"
                subprocess.run([str(gui), str(ROOT / "validation/native_windows_desktop_workflow.py"),
                    "--app", str(app), "--out", str(out / "desktop-workflow"),
                    "--structure", str(fixtures / "2R8N.cif"),
                    "--ligand", str(fixtures / "synthetic_carbamate.sdf")],
                    env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1500)
            status["checks"].append("installed_real_qt_buttons_scientific_host_review_finalize_screen_cancel_reopen")
            status["installed_desktop_workflow"] = "passed"
        status["status"] = "passed"
    except Exception as exc:
        status.update(status="failed", error=str(exc))
        # Installer logs contain dependency/setup diagnostics only: this occurs
        # before any study or synthetic docking input is created. Keep this
        # narrow, so later engine/desktop logs can never leak pose coordinates.
        if "native_powershell_fresh_bootstrap" not in status["checks"]:
            status["installer_diagnostics"] = {}
            receipt = destination / ".bootstrap/scientific-setup/scientific-install.json"
            if receipt.is_file():
                dependency_status = json.loads(receipt.read_text(encoding="utf-8"))
                status["scientific_dependency_setup"] = {key: dependency_status.get(key) for key in ("status", "error", "steps", "imports", "startup_diagnostics")}
            for path in (out / "install.log", destination / "bootstrap.log",
                         destination / ".bootstrap/manager-install.log", destination / ".bootstrap/manager-install.stderr.log",
                         destination / ".bootstrap/manager-status.json"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8", errors="replace")
                    # Conda's failure report appends an environment-variable
                    # dump; retain the preceding traceback, not that dump.
                    status["installer_diagnostics"][path.name] = installation_diagnostic(text)
    (out / "summary.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
