"""Targeted installation of reviewed site-first controls and optional P2Rank.

Keep recoverable backups. Native acceptance prepares a new isolated study but
never approves a site, performs a control, or runs ligand docking.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess

from autodock_gpu_trial import ROOT, check_idle, digest


OUT = ROOT / "validation/runs/site-first-control-20261017_b"
DESTINATION = Path("/opt/anaconda3/envs/docking-universal/libexec/docking-universal")
FILES = (
    "docking_universal/orchestration.py", "docking_universal/protocol_finalization.py",
    "docking_universal/services/control_review.py", "docking_universal/services/finalization.py",
    "docking_universal/gui/workflow_panels.py", "docking_universal/gui/desktop.py",
    "docking_universal/services/preparation.py", "docking_universal/services/pocket_review.py",
    "docking_universal/pocket_metadata.py", "docking_universal_pocket_evidence.py",
    "docking-universal-run.py", "docking-universal-control",
    "docking-universal-reviewed-control-inputs.py", "docking-universal-pdf-report.py",
)


def main():
    qa = json.loads((OUT / "summary.json").read_text())
    prediction = json.loads((ROOT / "validation/runs/bound-ligand-p2rank-20261017/review_validation.json").read_text())
    assert qa["status"] == "passed" and qa["protected_files_unchanged"]
    assert prediction["status"] == "passed" and prediction["preparation_repeated"] is False
    for name in ("scientific-regressions-install-ready", "gui-regressions-final", "retained-engine-regressions"):
        text = (OUT / (name + ".log")).read_text()
        assert "\nOK\n" in text and "FAILED (" not in text, name
    check_idle()
    for path, expected in qa["protected_sha256"].items():
        assert digest(path) == expected
    backup = OUT / "installation-backup"
    backup.mkdir(exist_ok=False)
    record = {"status": "installing", "files": [], "scientific_docking_searches": 0,
              "scientific_approvals": 0}

    def publish(source, target):
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(target.name + ".site-review-new")
        shutil.copy2(source, temporary)
        temporary.replace(target)

    try:
        for relative in FILES:
            source, target, saved = ROOT / "libexec" / relative, DESTINATION / relative, backup / relative
            row = {"relative": relative, "previous_sha256": digest(target) if target.is_file() else None,
                   "sha256": digest(source)}
            if target.is_file():
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
            record["files"].append(row)
            publish(source, target)
            assert digest(target) == row["sha256"]
        installed_out = ROOT / "validation/runs/site-first-control-installed-20261017"
        environment = dict(os.environ, PYTHONPATH=str(DESTINATION) + ":" + str(ROOT / "validation"),
            PATH="/opt/anaconda3/envs/docking-universal/bin:/opt/anaconda3/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
            DOCKING_UNIVERSAL_PYTHON="/opt/anaconda3/envs/docking-universal/bin/python")
        with (OUT / "installed-validation.log").open("w") as log:
            subprocess.run(["/opt/anaconda3/envs/docking-universal-gui-next/bin/python",
                str(ROOT / "validation/site_first_control_gui.py"), "--runtime", str(DESTINATION),
                "--out", str(installed_out), "--predict-with-ligand"],
                cwd=ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=700)
        installed = json.loads((installed_out / "summary.json").read_text())
        assert installed["status"] == "passed" and installed["protected_files_unchanged"]
        assert installed["scientific_approvals"] == installed["scientific_docking_searches"] == 0
        for row in record["files"]:
            assert digest(DESTINATION / row["relative"]) == row["sha256"]
            assert digest(ROOT / "libexec" / row["relative"]) == row["sha256"]
        for path, expected in qa["protected_sha256"].items():
            assert digest(path) == expected
        record.update(status="installed", installed_validation=str(installed_out / "summary.json"),
                      original_studies_and_results_unchanged=True)
    except BaseException as error:
        for row in reversed(record["files"]):
            target = DESTINATION / row["relative"]
            if row["previous_sha256"] is not None:
                publish(backup / row["relative"], target)
            elif target.is_file() and digest(target) == row["sha256"]:
                target.unlink()
        record.update(status="failed", error=str(error), previous_installation_restored=True)
        raise
    finally:
        (OUT / "installation.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
