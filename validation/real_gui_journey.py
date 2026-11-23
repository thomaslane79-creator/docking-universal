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
        if state.jobs and state.jobs[-1].status.value in {"failed", "cancelled", "interrupted"}:
            raise RuntimeError(f"{label} failed: {state.jobs[-1].error}")
        time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {label}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    receptor = parser.add_mutually_exclusive_group(required=True)
    receptor.add_argument("--receptor", type=Path)
    receptor.add_argument("--pdb-id")
    parser.add_argument("--ligand", type=Path)
    parser.add_argument("--protocol-only", action="store_true", help="Stop after verifying the portable protocol")
    parser.add_argument("--scientific-python", type=Path, required=True)
    parser.add_argument("--host-script", type=Path, required=True)
    parser.add_argument("--study-id", default="real-gui-validation")
    parser.add_argument("--study-name", default="Real GUI validation")
    parser.add_argument("--case-id", default="C1")
    parser.add_argument("--selected-pocket", action="append", help="Region ID; repeat to review multiple regions (default P1)")
    parser.add_argument("--control-ligand", help="Exact deposited instance as RESNAME:CHAIN:RESIDUE")
    parser.add_argument("--engine", "--control-engine", choices=("vina", "qvinaw", "adgpu"), default="vina")
    parser.add_argument("--control-tier", default="repeatability")
    parser.add_argument("--control-timeout", type=float, default=3600,
                        help="Seconds to wait for control docking, rendering and report registration")
    parser.add_argument("--approve-test-component", action="append", default=[],
                        help="In this isolated test only, permit the named public definition and its validated template review")
    parser.add_argument("--allow-no-evidence", action="store_true")
    parser.add_argument("--offline-evidence", action="store_true")
    parser.add_argument("--smoke", action="store_true", help="Use a small exploratory search to check the software path")
    parser.add_argument("--snapshots", action="store_true", help="Save numbered GUI screenshots for the walkthrough")
    parser.add_argument("--review-snapshot", action="store_true", help="Reopen a finished study and capture its results without docking again")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.ligand is None and not args.protocol_only:
        parser.error("--ligand is required unless --protocol-only is selected")
    if args.control_timeout <= 0:
        parser.error("--control-timeout must be positive")
    if args.review_snapshot and not (args.resume and args.snapshots):
        parser.error("--review-snapshot requires --resume and --snapshots")
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=args.resume)
    state_root = root / "state"
    study_id = args.study_id
    requested_regions = set(args.selected_pocket or ["P1"])
    approved_components = set(args.approve_test_component)
    if approved_components:
        os.environ["DOCKING_UNIVERSAL_COMPONENT_CACHE"] = str(root / "component-cache")
        os.environ["DOCKING_UNIVERSAL_CCD_CACHE"] = str(root / "ccd-cache")
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    def record_message(_parent, title, message, *args, **kwargs):
        print(f"{title}: {message}", flush=True)
        return QtWidgets.QMessageBox.StandardButton.Cancel

    def review_dialog(dialog):
        if approved_components and dialog.detailedText():
            detail = json.loads(dialog.detailedText())
            components = detail.get("components", [])
            definitions = [detail.get(key) for key in ("ccd", "geostd") if detail.get(key)]
            if definitions and all(
                item.get("schema_name") in {"docking-universal-ccd-network-disclosure", "docking-universal-network-disclosure"}
                and 0 < len(item.get("component_ids", []))
                and set(item["component_ids"]) <= approved_components
                for item in definitions
            ):
                label = "Download listed definitions"
            elif detail.get("schema_name") == "docking-universal-meeko-template-bridge" and components and all(
                item.get("status") == "candidate_validated" and item.get("component_id") in approved_components
                for item in components
            ):
                label = "Use validated local template"
            else:
                label = None
            button = next((button for button in dialog.buttons() if button.text() == label), None)
            if button is not None:
                print(f"Isolated test review: {label}: {dialog.text()}", flush=True)
                button.click()
                return dialog.result()
        raise RuntimeError(f"{dialog.windowTitle()}: {dialog.text()} (manual review required)")

    message_patches = [
        patch.object(QtWidgets.QMessageBox, name, side_effect=record_message)
        for name in ("information", "warning", "critical")
    ]
    message_patches.append(patch.object(QtWidgets.QMessageBox, "exec", review_dialog))
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
        snapshots = []
        if args.snapshots:
            (root / "snapshots").mkdir(exist_ok=True)
            window.resize(1680, 1050)
            window.show()

        def snapshot(name, number=None):
            if not args.snapshots:
                return
            app.processEvents()
            path = root / "snapshots" / f"{number or len(snapshots) + 1:02d}-{name}.png"
            if not window.grab().save(str(path)):
                raise RuntimeError(f"Could not save GUI screenshot: {path}")
            snapshots.append(str(path.relative_to(root)))

        def snapshot_results():
            if not args.snapshots:
                return
            window.refresh()
            window.resizeDocks([window.screening_results_dock], [680], QtCore.Qt.Orientation.Horizontal)
            if not window.screening_results.rowCount():
                raise RuntimeError("No screened compound is available for Results Review")
            window.screening_results.selectRow(0)
            app.processEvents()
            if not window.cluster_comparison.rowCount():
                raise RuntimeError("No pose cluster is available for Results Review")
            window.cluster_comparison.selectRow(0)
            snapshot("results-review", number=5)

        if args.review_snapshot:
            if store.load(study_id).workflow_data.get("latest_screening_status") != "completed":
                raise RuntimeError("Results capture requires a completed screening run")
            snapshot_results()
            window.close()
            return 0

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
            window.study_setup_panel.pdb_evidence.setChecked(not args.offline_evidence)
            if args.control_ligand:
                window.study_pathway.setCurrentIndex(window.study_pathway.findData("control"))
                window.detect_bound_ligands(quiet=True)
                matches = []
                for index in range(window.ligand_resname.count()):
                    identity = window.ligand_resname.itemData(index)
                    if isinstance(identity, dict) and ":".join(str(identity.get(key, "")) for key in (
                        "resname", "chain_id", "residue_number",
                    )) == args.control_ligand:
                        matches.append(index)
                if len(matches) != 1:
                    raise RuntimeError(f"Expected one exact deposited ligand: {args.control_ligand}")
                window.ligand_resname.setCurrentIndex(matches[0])
                engine = window.control_engine.findData(args.engine)
                if engine < 0:
                    raise RuntimeError(f"Control engine is unavailable: {args.engine}")
                window.control_engine.setCurrentIndex(engine)
                tier = window.control_tier.findData(args.control_tier)
                if tier < 0:
                    raise RuntimeError(f"Unknown control tier: {args.control_tier}")
                window.control_tier.setCurrentIndex(tier)
            snapshot("study-setup")
            window.start_preparation()
            if not store.load(study_id).jobs:
                raise RuntimeError(f"Preparation did not start: {window.statusBar().currentMessage()}")
            state = wait_for(app, window, store, study_id, lambda s: bool(s.pending_decisions), "pocket evidence and review")
        candidates = state.workflow_data.get("pocket_candidates", [])
        rows = [index for index, item in enumerate(candidates) if item["id"] in requested_regions]
        selected_regions = [candidates[index]["id"] for index in rows]
        if set(selected_regions) != requested_regions:
            raise RuntimeError(f"Requested regions {sorted(requested_regions)} not all available")
        window.candidates.clearSelection()
        for row in rows:
            window.candidates.selectionModel().select(
                window.candidates.model().index(row, 0),
                QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows,
            )
        app.processEvents()
        evidence_rows = window.pocket_evidence_panel.table.rowCount()
        evidence_heading = window.pocket_evidence_panel.heading.text()
        snapshot("docking-region-review")
        if evidence_rows < 1 and not (args.allow_no_evidence or args.offline_evidence):
            raise RuntimeError(
                f"{', '.join(selected_regions)} reached GUI review without experimental observations"
            )
        if state.pending_decisions:
            window.rationale.setText(
                "Real GUI validation: selected " + ", ".join(selected_regions)
                + " after reviewing pocket and deposited-ligand evidence"
            )
            window.approve_selected_regions()
            state = wait_for(
                app, window, store, study_id,
                lambda s: s.selected_pocket_ids == selected_regions and not window._pocket_approval_pending,
                "docking region approval",
            )
        if state.selected_pocket_ids != selected_regions:
            raise RuntimeError(f"Unexpected approved regions: {state.selected_pocket_ids}")
        if (state.workflow_data.get("study_setup") or {}).get("explore_sites_first"):
            if state.workflow_data.get("receptor_parameterization_status") == "not_started":
                window.refresh()
                if not window.protocol_finalization_panel.prepare_reviewed_button.isEnabled():
                    raise RuntimeError(window.finalization_status.text())
                window.protocol_finalization_panel.prepare_reviewed_button.click()
            state = wait_for(
                app, window, store, study_id,
                lambda s: s.workflow_data.get("receptor_parameterization_status") == "completed",
                "reviewed receptor preparation",
            )
        if not any(a.kind == "protocol_bundle" for a in state.artifacts):
            window.refresh()
            if not args.control_ligand:
                engine = window.protocol_engine.findData(args.engine)
                if engine < 0:
                    raise RuntimeError(f"Protocol engine is unavailable: {args.engine}")
                window.protocol_engine.setCurrentIndex(engine)
                window.final_output_directory.setText(str(root / "protocol"))
                window.exploratory_approval.setChecked(True)
                if args.smoke:
                    window.protocol_conformers.setValue(1)
                    window.protocol_seeds.setValue(1)
                    window.protocol_exhaustiveness.setValue(4)
            if not window.finalize_button.isEnabled():
                raise RuntimeError(window.finalization_status.text())
            snapshot("protocol-settings")
            window.start_protocol_finalization()
            if args.control_ligand:
                state = wait_for(
                    app, window, store, study_id,
                    lambda s: bool(s.workflow_data.get("latest_control_status")),
                    "control validation", timeout=args.control_timeout,
                )
                if state.workflow_data.get("latest_control_status") != "approved":
                    job_error = state.jobs[-1].error if state.jobs else None
                    detail = f": {job_error}" if job_error else ""
                    raise RuntimeError(f"Control did not earn approval; screening was not started{detail}")
            state = wait_for(
                app, window, store, study_id,
                lambda s: any(a.kind == "protocol_bundle" for a in s.artifacts), "protocol finalization",
            )
        if args.protocol_only:
            bundle = next(a for a in state.artifacts if a.kind == "protocol_bundle")
            report = next(a for a in state.artifacts if a.kind in {"final_report", "control_report"})
            for artifact in (bundle, report):
                if not Path(artifact.path).is_file():
                    raise RuntimeError(f"Protocol artifact is missing: {artifact.path}")
            result = {"case_id": args.case_id, "status": "passed", "protocol_only": True,
                      "selected_pockets": state.selected_pocket_ids, "snapshots": snapshots,
                      "protocol_bundle": bundle.path, "final_report": report.path}
            (root / "acceptance_record.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
            window.close()
            return 0
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
        snapshot("screening-workload")
        app.processEvents()
        window.start_screening()
        state = wait_for(
            app, window, store, study_id,
            lambda s: Path(str(s.workflow_data.get("latest_screening_output", ""))).resolve() == screen_root,
            "screening",
        )
        if state.workflow_data.get("latest_screening_status") != "completed":
            raise RuntimeError("The screening output was retained but the run did not complete")
        snapshot_results()
        manifests = list(screen_root.glob(
            "compounds/*/pose_analysis/cluster_*/interactions/representative_plip2d.manifest.json"
        ))
        renderer_policies = sorted({
            json.loads(path.read_text()).get("renderer_policy") or json.loads(path.read_text()).get("schema_name")
            for path in manifests
        })
        evidence_artifact = next((a for a in state.artifacts if a.kind == "pocket_evidence"), None)
        evidence = json.loads(Path(evidence_artifact.path).read_text()) if evidence_artifact else {}
        summary = {
            "schema_name": "docking-universal-gui-acceptance-record",
            "schema_version": 1,
            "case_id": args.case_id,
            "status": "passed", "study_id": study_id,
            "receptor_input": str(source_path),
            "screening_input": str(args.ligand.resolve()),
            "control_engine": (state.workflow_data.get("study_setup") or {}).get("engine") if args.control_ligand else None,
            "screening_engine": window._screening_plan.get("engine") if window._screening_plan else args.engine,
            "approved_test_components": sorted(approved_components),
            "smoke_settings": args.smoke,
            "snapshots": snapshots,
            "selected_pockets": state.selected_pocket_ids,
            "gui_evidence_heading": evidence_heading,
            "gui_evidence_rows": evidence_rows,
            "pdb_evidence_status": "off" if args.offline_evidence else evidence.get("status"),
            "pdb_observations": len(evidence.get("evidence", [])),
            "pose_renderer_policies": renderer_policies,
            "protocol_bundle": next(a.path for a in state.artifacts if a.kind == "protocol_bundle"),
            "final_report": next(a.path for a in state.artifacts if a.kind in {"final_report", "control_report"}),
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
