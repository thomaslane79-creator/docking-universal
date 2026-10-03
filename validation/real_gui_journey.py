#!/usr/bin/env python3
"""Drive one real installed GUI workflow offscreen and retain an audit summary."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.state import JsonStudyStore


def wait_for(app, window, store, study_id, predicate, label, timeout=900):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        window.refresh()
        state = store.load(study_id)
        if predicate(state):
            return state
        if state.jobs and state.jobs[-1].status.value == "failed":
            raise RuntimeError(f"{label} failed: {state.jobs[-1].error}")
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {label}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    receptor = parser.add_mutually_exclusive_group(required=True)
    receptor.add_argument("--receptor", type=Path)
    receptor.add_argument("--pdb-id")
    parser.add_argument("--ligand", type=Path, required=True)
    parser.add_argument("--scientific-python", type=Path, required=True)
    parser.add_argument("--host-script", type=Path, required=True)
    parser.add_argument("--study-id", default="real-gui-validation")
    parser.add_argument("--study-name", default="Real GUI validation")
    parser.add_argument("--case-id", default="C1")
    parser.add_argument("--selected-pocket", default="P1")
    parser.add_argument("--allow-no-evidence", action="store_true")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=args.resume)
    state_root = root / "state"
    study_id = args.study_id
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    message_patches = [
        patch.object(
            QtWidgets.QMessageBox, name,
            return_value=QtWidgets.QMessageBox.StandardButton.Ok,
        )
        for name in ("information", "warning", "critical")
    ]
    for message_patch in message_patches:
        message_patch.start()
    settings = QtCore.QSettings(str(root / "window.ini"), QtCore.QSettings.Format.IniFormat)
    with ApplicationHostClient(
        state_root, args.host_script, python_executable=args.scientific_python,
        timeout_seconds=30,
    ) as host:
        store = JsonStudyStore(state_root)
        if not args.resume:
            host.request(study_id, "create_study", {"name": args.study_name})
        window = StudyWindow(store, study_id, settings=settings, host_client=host)
        if args.resume:
            state = store.load(study_id)
        else:
            window.output_directory.setText(str(root / "preparation"))
            if args.pdb_id:
                window.input_pdb.setText(args.pdb_id)
                downloaded = window.fetch_input_pdb()
                if not downloaded:
                    raise RuntimeError(f"GUI download of {args.pdb_id} failed")
                source_path = Path(downloaded)
            else:
                source_path = args.receptor.resolve()
                window.input_pdb.setText(str(source_path))
                window.refresh_input_coordinate_evidence()
            if not source_path.is_file():
                raise FileNotFoundError(source_path)
            window.pocket_engine.setCurrentIndex(window.pocket_engine.findData("p2rank"))
            window.study_setup_panel.pdb_evidence.setChecked(True)
            window.start_preparation()
            state = wait_for(app, window, store, study_id, lambda s: bool(s.pending_decisions), "pocket evidence and review")
        candidates = state.workflow_data.get("pocket_candidates", [])
        selected_row = next(
            i for i, item in enumerate(candidates)
            if item["id"] == args.selected_pocket
        )
        window.candidates.selectRow(selected_row)
        app.processEvents()
        evidence_rows = window.pocket_evidence_panel.table.rowCount()
        evidence_heading = window.pocket_evidence_panel.heading.text()
        if evidence_rows < 1 and not args.allow_no_evidence:
            raise RuntimeError(
                f"{args.selected_pocket} reached GUI review without experimental observations"
            )
        if state.pending_decisions:
            window.rationale.setText(
                "Real GUI validation: selected " + args.selected_pocket
                + " after reviewing pocket and deposited-ligand evidence"
            )
            window.approve_selected_regions()
            state = wait_for(
                app, window, store, study_id,
                lambda s: s.selected_pocket_ids == [args.selected_pocket]
                or not s.pending_decisions,
                args.selected_pocket + " approval",
            )
        if state.selected_pocket_ids != [args.selected_pocket]:
            raise RuntimeError(f"Unexpected approved regions: {state.selected_pocket_ids}")
        if not any(a.kind == "protocol_bundle" for a in state.artifacts):
            window.final_output_directory.setText(str(root / "protocol"))
            window.exploratory_approval.setChecked(True)
            window.start_protocol_finalization()
            state = wait_for(
                app, window, store, study_id,
                lambda s: any(a.kind == "protocol_bundle" for a in s.artifacts), "protocol finalization",
            )
        window.refresh()
        app.processEvents()
        screen_root = root / "screen"
        retry = 1
        while screen_root.exists():
            screen_root = root / f"screen_retry{retry}"
            retry += 1
        window.screen_ligands.setText(str(args.ligand.resolve()))
        window.screen_output.setText(str(screen_root))
        window.preview_screening()
        if not window._screening_plan:
            raise RuntimeError("GUI did not accept the SDF screening preview")
        window.screen_exploratory_approval.setChecked(True)
        app.processEvents()
        window.start_screening()
        started = store.load(study_id)
        if not any(job.stage == "screening" for job in started.jobs) and not started.workflow_data.get("latest_screening_output"):
            raise RuntimeError(
                "GUI did not start SDF screening after an accepted preview; "
                f"screening status: {window.screening_status.text()}"
            )
        state = wait_for(
            app, window, store, study_id,
            lambda s: Path(str(s.workflow_data.get("latest_screening_output", ""))).resolve() == screen_root,
            "screening",
        )
        manifests = list(screen_root.glob(
            "compounds/*/pose_analysis/cluster_*/interactions/representative_plip2d.manifest.json"
        ))
        renderer_policies = sorted({
            json.loads(path.read_text()).get("renderer_policy") or json.loads(path.read_text()).get("schema_name")
            for path in manifests
        })
        evidence_artifact = next(a for a in state.artifacts if a.kind == "pocket_evidence")
        evidence = json.loads(Path(evidence_artifact.path).read_text())
        summary = {
            "schema_name": "docking-universal-gui-acceptance-record",
            "schema_version": 1,
            "case_id": args.case_id,
            "status": "passed", "study_id": study_id,
            "receptor_input": str(source_path),
            "screening_input": str(args.ligand.resolve()),
            "selected_pockets": state.selected_pocket_ids,
            "gui_evidence_heading": evidence_heading,
            "gui_evidence_rows": evidence_rows,
            "pdb_evidence_status": evidence.get("status"),
            "pdb_observations": len(evidence.get("evidence", [])),
            "pose_renderer_policies": renderer_policies,
            "protocol_bundle": next(a.path for a in state.artifacts if a.kind == "protocol_bundle"),
            "final_report": next(a.path for a in state.artifacts if a.kind == "final_report"),
            "screening_report": next(
                a.path for a in reversed(state.artifacts)
                if a.kind == "screening_report" and screen_root in Path(a.path).resolve().parents
            ),
        }
        (root / "validation_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        (root / "acceptance_record.json").write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary, indent=2))
        window.close()
    for message_patch in reversed(message_patches):
        message_patch.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
