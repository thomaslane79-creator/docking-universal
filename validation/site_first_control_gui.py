"""Real GUI/host download and fresh ligand lookup; stop before any approval/search."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.state import JsonStudyStore


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, default=ROOT / "libexec")
    parser.add_argument("--out", type=Path, default=ROOT / "validation/runs/site-first-control-20261017")
    parser.add_argument("--predict-with-ligand", action="store_true")
    parser.add_argument("--offline-evidence", action="store_true")
    args = parser.parse_args()
    library = Path.home() / "Library/Application Support/Docking Universal/studies"
    states = list(library.glob("*/application_state.json"))
    if not states:
        raise RuntimeError("Cannot verify the main study library is idle")
    for path in states:
        state = json.loads(path.read_text())
        if any(job.get("status") in {"queued", "running"} for job in state.get("jobs", [])):
            raise RuntimeError("Another scientific calculation is active: " + str(path.parent))
    args.out.mkdir(exist_ok=False)
    protected = json.loads((ROOT / "validation/runs/reduce2-frame-fix-installed-20261017/summary.json").read_text())["protected_sha256"]
    assert all(digest(path) == value for path, value in protected.items())
    record = {"status": "running", "pid": os.getpid(), "runtime": str(args.runtime), "scientific_docking_searches": 0,
              "scientific_approvals": 0, "protected_sha256": protected,
              "predict_pockets_with_ligand": args.predict_with_ligand, "offline_evidence": args.offline_evidence}
    def save():
        (args.out / "summary.json").write_text(json.dumps(record, indent=2) + "\n")
    save()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    store = JsonStudyStore(args.out / "state")
    settings = QtCore.QSettings(str(args.out / "window.ini"), QtCore.QSettings.Format.IniFormat)
    messages = []
    def unexpected(*values, **kwargs):
        # Never raise through a PyQt slot (which aborts the interpreter), and
        # never grant an unexpected chemistry/download approval automatically.
        messages.append(str(values[1:]))
        return QtWidgets.QMessageBox.StandardButton.Cancel
    window = None
    try:
        with ApplicationHostClient(store.root, args.runtime / "docking-universal-application-host.py",
            python_executable="/opt/anaconda3/envs/docking-universal/bin/python", timeout_seconds=30) as host, \
            patch.object(QtWidgets.QMessageBox, "warning", side_effect=unexpected), \
            patch.object(QtWidgets.QMessageBox, "critical", side_effect=unexpected), \
            patch.object(QtWidgets.QMessageBox, "exec", side_effect=unexpected):
            host.request("site-first-control", "create_study", {"name": "2R5P site-first control lookup check"})
            window = StudyWindow(store, "site-first-control", host_client=host, settings=settings)
            window.resize(1400, 920)
            window.show()
            window.output_directory.setText(str(args.out / "study"))
            window.input_pdb.setText("2R5P")
            record["phase"] = "Fresh RCSB mmCIF download"
            save()
            source = window.fetch_input_pdb()
            if not source:
                raise RuntimeError("RCSB structure acquisition did not complete")
            record.update(source=str(source), source_sha256=digest(source))
            save()
            window.study_pathway.setCurrentIndex(window.study_pathway.findData("control"))
            window.detect_bound_ligands(quiet=True)
            index = next((i for i in range(window.ligand_resname.count())
                if isinstance(window.ligand_resname.itemData(i), dict)
                and window.ligand_resname.itemData(i).get("resname") == "MK1"
                and window.ligand_resname.itemData(i).get("chain_id") == "B"
                and str(window.ligand_resname.itemData(i).get("residue_number")) == "902"), None)
            if index is None:
                raise RuntimeError("Expected exact MK1 B:902 instance not available; no substitute selected")
            window.ligand_resname.setCurrentIndex(index)
            assert window.study_setup_panel.pdb_evidence.isEnabled()
            assert not window.study_setup_panel.pdb_evidence.isHidden()
            window.study_setup_panel.pdb_evidence.setChecked(not args.offline_evidence)
            window.study_setup_panel.predict_with_ligand.setChecked(args.predict_with_ligand)
            window.pocket_engine.setCurrentIndex(window.pocket_engine.findData("p2rank"))
            window.start_preparation_button.click()
            if messages or not store.load("site-first-control").jobs:
                raise RuntimeError("Preparation did not start: " + str(messages))
            started = time.monotonic()
            while True:
                app.processEvents()
                window.refresh()
                state = store.load("site-first-control")
                if any(job.status.value in {"failed", "cancelled", "interrupted"} for job in state.jobs):
                    raise RuntimeError("Preparation/evidence stage failed: " + str(state.jobs[-1].error))
                record.update(phase=state.active_job.stage if state.active_job else "coordinator registration",
                              elapsed_seconds=time.monotonic() - started)
                save()
                if state.pending_decisions:
                    break
                if time.monotonic() - started > 600:
                    raise TimeoutError("Preparation/lookup exceeded ten minutes; retained state is not called complete")
                time.sleep(.2)
            assert not any(job.stage == "control_validation" for job in state.jobs)
            assert not state.approvals and not state.selected_pocket_ids
            assert not (args.out / "study/control").exists()
            evidence = state.workflow_data.get("pdb_pocket_evidence", {"mode": "off"})
            data = json.loads(Path(evidence["record"]).read_text()) if evidence.get("record") else {}
            if args.offline_evidence:
                assert evidence["mode"] == "off" and not data
            else:
                assert data["status"] == "completed", data
                assert data["candidate_entries"] and data["evidence"]
                assert "2R5P" not in data["candidate_entries"]
                assert not any(row.get("entry") == "2R5P" for row in data["evidence"])
                assert "2R5P" in data["query"]["input_reference_entries_excluded"]
            if args.predict_with_ligand:
                provenance = json.loads((Path(state.workflow_data["preparation_root"]) / "cavity/pocket_detection_provenance.json").read_text())
                assert provenance["engine"] == "p2rank"
                assert any(row["evidence"].get("source") == "input_bound_ligand" or row["evidence"].get("input_bound_ligand")
                           for row in state.workflow_data["pocket_candidates"])
                assert any(row["evidence"].get("detector") == "p2rank" for row in state.workflow_data["pocket_candidates"])
                record["pocket_detection"] = provenance
                bound_evidence = next((row["evidence"] for row in state.workflow_data["pocket_candidates"]
                    if row["evidence"].get("source") == "input_bound_ligand"), None)
                if bound_evidence:
                    assert not bound_evidence.get("experimental_ligand_evidence")
            record.update(evidence_record=evidence.get("record"), candidate_entry_count=len(data.get("candidate_entries", [])),
                          ligand_observation_count=len(data.get("evidence", [])),
                          region_labels=[row["label"] for row in state.workflow_data["pocket_candidates"]],
                          lookup_coverage=evidence.get("coverage"),
                          study_state=str(store.path_for("site-first-control")))
            before_reopen = digest(store.path_for("site-first-control"))
            window._activate_workflow_target("central")
            app.processEvents()
            window.grab().save(str(args.out / "review-before-control.png"))
            window.close()
            window = StudyWindow(store, "site-first-control", host_client=host, settings=settings)
            window.show()
            window.refresh()
            app.processEvents()
            assert digest(store.path_for("site-first-control")) == before_reopen
            assert window.study_pathway.currentData() == "control"
            assert window.study_setup_panel.predict_with_ligand.isChecked() == args.predict_with_ligand
            assert not window.study_setup_panel.pdb_evidence.isHidden()
            assert not window.finalize_button.isEnabled()
            record.update(status="passed", phase="waiting for user site approval; no redocking",
                          reopened_without_state_mutation=True)
    except BaseException as error:
        record.update(status="failed", error=str(error))
        raise
    finally:
        if window is not None:
            window.close()
        record["protected_files_unchanged"] = all(digest(path) == value for path, value in protected.items())
        save()
    print(json.dumps({key: record[key] for key in ("status", "candidate_entry_count", "ligand_observation_count",
                                                  "region_labels", "scientific_docking_searches", "protected_files_unchanged")}, indent=2))


if __name__ == "__main__":
    main()
