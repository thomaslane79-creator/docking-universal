"""Install only the validated Reduce2/frame/host-progress corrections, with rollback."""
import json
import os
from pathlib import Path
import shutil
import subprocess

from autodock_gpu_trial import ROOT, check_idle, digest


OUT = ROOT / "validation/runs/reduce2-frame-fix-20261017"
DESTINATION = Path("/opt/anaconda3/envs/docking-universal/libexec/docking-universal")
FILES = ("docking-universal-reduce2-receptor.py", "docking-universal-prepare.d/receptor.sh",
         "docking_universal_pocket_evidence.py")


def main():
    qa = json.loads((OUT / "summary.json").read_text())
    assert qa["status"] == "passed" and qa["protected_files_unchanged"]
    check_idle()
    for path, expected in qa["protected_sha256"].items():
        assert digest(path) == expected
    env = dict(os.environ, PYTHONPATH=str(ROOT / "libexec") + ":" + str(ROOT / "tests"),
               DOCKING_UNIVERSAL_PYTHON="/opt/anaconda3/envs/docking-universal/bin/python")
    python = "/opt/anaconda3/envs/docking-universal/bin/python"
    regression = subprocess.run([python, "-m", "unittest", "test_reduce2_native_output", "test_protonation_audit",
                                 "test_native_receptor_input", "test_structure_input", "test_pocket_evidence"],
                                cwd=ROOT, env=env, capture_output=True, text=True, check=True)
    (OUT / "regressions.log").write_text(regression.stdout + regression.stderr)
    for test in ("input_filter", "structural_audits", "failure_diagnosis", "attempt_runner", "input_validation",
                 "command_builders", "preparation_routes"):
        result = subprocess.run(["bash", str(ROOT / f"tests/test_receptor_{test}.sh")],
                                cwd=ROOT, env=env, capture_output=True, text=True, check=True)
        (OUT / f"shell-{test}.log").write_text(result.stdout + result.stderr)
    backup = OUT / "installation-backup"
    backup.mkdir(exist_ok=False)
    record = {"status": "installing", "files": [], "scientific_docking_searches": 0,
              "regression_tests": 44, "shell_suites": 7}

    def publish(source, target):
        temporary = target.with_name(target.name + ".reduce2-frame-new")
        shutil.copy2(source, temporary)
        temporary.replace(target)

    try:
        for relative in FILES:
            source, target, saved = ROOT / "libexec" / relative, DESTINATION / relative, backup / relative
            saved.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(target, saved)
            row = {"relative": relative, "previous_sha256": digest(target), "sha256": digest(source)}
            record["files"].append(row)
            publish(source, target)
            assert digest(target) == row["sha256"]
        installed_out = ROOT / "validation/runs/reduce2-frame-fix-installed-20261017"
        with (OUT / "installed-validation.log").open("w") as log:
            subprocess.run([python, str(ROOT / "validation/validate_reduce2_frame_fix.py"),
                            "--runtime", str(DESTINATION), "--out", str(installed_out)],
                           cwd=ROOT, env=dict(env, PYTHONPATH=str(DESTINATION)), stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        installed = json.loads((installed_out / "summary.json").read_text())
        assert installed["status"] == "passed" and installed["protected_files_unchanged"]
        for path, expected in qa["protected_sha256"].items():
            assert digest(path) == expected
        for row in record["files"]:
            assert digest(DESTINATION / row["relative"]) == row["sha256"]
        record.update(status="installed", installed_preparation_validation=str(installed_out / "summary.json"),
                      original_studies_and_results_unchanged=True)
    except BaseException as error:
        for row in reversed(record["files"]):
            publish(backup / row["relative"], DESTINATION / row["relative"])
        record.update(status="failed", error=str(error), previous_installation_restored=True)
        raise
    finally:
        (OUT / "installation.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
