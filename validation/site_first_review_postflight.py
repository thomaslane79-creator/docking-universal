"""Verify retained real P2Rank preparation without repeating it or approving sites."""
import json
import sys
from pathlib import Path
import hashlib

from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.state import JsonStudyStore


def main():
    output = Path(sys.argv[1]).resolve()
    runtime = Path(sys.argv[2]).resolve()
    prior = json.loads((output / "summary.json").read_text())
    digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert all(digest(path) == value for path, value in prior["protected_sha256"].items())
    store = JsonStudyStore(output / "state")
    state = store.load("site-first-control")
    before = digest(store.path_for(state.study_id))
    setup = state.workflow_data["study_setup"]
    assert setup["predict_pockets_with_ligand"] and setup["pdb_pocket_evidence"] == "off"
    assert state.pending_decisions and not state.approvals and not state.selected_pocket_ids
    assert not any(job.stage == "control_validation" for job in state.jobs)
    assert all(job.status.value == "completed" or
               (job.stage == "pocket_review" and job.status.value == "waiting_for_decision") for job in state.jobs)
    cavity = Path(state.workflow_data["preparation_root"]) / "cavity"
    assert not (cavity / "pdb_site_evidence/pdb_ligand_site_evidence.json").exists()
    detection = json.loads((cavity / "pocket_detection_provenance.json").read_text())
    assert detection["engine"] == "p2rank" and detection["retained_count"] > 0
    candidates = state.workflow_data["pocket_candidates"]
    bound = next(row for row in candidates if row["evidence"].get("source") == "input_bound_ligand"
                 or row["evidence"].get("input_bound_ligand"))
    assert any(row["evidence"].get("detector") == "p2rank" for row in candidates)
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    settings = QtCore.QSettings(str(output / "window.ini"), QtCore.QSettings.Format.IniFormat)
    with ApplicationHostClient(store.root, runtime / "docking-universal-application-host.py",
        python_executable="/opt/anaconda3/envs/docking-universal/bin/python") as host:
        window = StudyWindow(store, state.study_id, host_client=host, settings=settings)
        window.resize(1400, 920)
        window.show(); app.processEvents(); window.refresh(); app.processEvents()
        assert window.study_setup_panel.predict_with_ligand.isChecked()
        assert not window.study_setup_panel.predict_with_ligand.isEnabled()
        assert not window.finalize_button.isEnabled()
        window.grab().save(str(output / "review-before-control.png"))
        window.close()
    assert before == digest(store.path_for(state.study_id))
    result = {"status": "passed", "original_harness_status": prior["status"],
              "original_harness_error": prior.get("error"), "preparation_repeated": False,
              "scientific_approvals": 0, "scientific_docking_searches": 0,
              "lookup": "off", "pocket_detection": detection, "region_labels": [r["id"] for r in candidates],
              "bound_site_label": bound["id"], "reopened_without_state_mutation": True,
              "protected_files_unchanged": True}
    (output / "review_validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
