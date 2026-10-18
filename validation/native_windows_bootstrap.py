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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--conda", required=True, type=Path)
    args = parser.parse_args()
    if platform.system() != "Windows":
        parser.error("Real native Windows required")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    status = {"status": "running", "system": platform.platform(), "checks": [],
              "scientific_preparation_reports_pymol_gpu_accepted": False}
    try:
        destination = out / "Native Ω runtime with spaces"
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ROOT / "install-windows.ps1"),
                   "-Destination", str(destination), "-CondaExe", str(args.conda), "-AcceptDevelopmentPreview"]
        with (out / "install.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=1200)
        status["checks"].append("native_powershell_fresh_bootstrap")
        installed = json.loads((destination / "bootstrap-status.json").read_text(encoding="utf-8"))
        if installed["status"] != "bootstrap_installed":
            raise ValueError("Bootstrap did not reach its explicit installed state")
        host = destination / "runtimes/host/python.exe"
        gui = destination / "runtimes/gui/python.exe"
        app = destination / "app"
        entry = app / "docking-universal-native.py"
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
        # Real installed host, not a fake JSON peer. No scientific job may be
        # registered when the unported preparation stage is requested.
        probe = subprocess.run([str(host), str(ROOT / "validation/native_windows_host_probe.py"),
                                "--app", str(app), "--out", str(out / "host-probe")],
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
        subprocess.run([str(host), str(ROOT / "validation/native_windows_vina.py"), "--out", str(out / "vina"),
                        "--installed-entry", str(entry), "--engine", str(destination / "engines/vina.exe")],
                       env=environment, check=True, timeout=240)
        status["vina"] = json.loads((out / "vina/summary.json").read_text(encoding="utf-8"))
        status["checks"].append("installed_native_vina_exact_same_seed_repeat")
        status["status"] = "passed"
    except Exception as exc:
        status.update(status="failed", error=str(exc))
        # Installer logs contain dependency/setup diagnostics only: this occurs
        # before any study or synthetic docking input is created. Keep this
        # narrow, so later engine/desktop logs can never leak pose coordinates.
        if not status["checks"]:
            status["installer_diagnostics"] = {}
            for path in (out / "install.log", out / "Native Ω runtime with spaces/bootstrap.log"):
                if path.is_file():
                    text = path.read_text(encoding="utf-8", errors="replace")
                    # Conda's failure report appends an environment-variable
                    # dump; retain the preceding traceback, not that dump.
                    text = text.split("  environment variables:", 1)[0]
                    status["installer_diagnostics"][path.name] = text[:8000]
    (out / "summary.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(status))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
