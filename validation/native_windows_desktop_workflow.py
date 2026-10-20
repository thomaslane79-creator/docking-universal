"""Exercise installed Qt buttons and the real scientific host on native Windows.

All approvals here apply ONLY to a disposable public/synthetic fixture. Upload
summary.json only: no structures, scientific logs, screenshots or reports.
Interactive PyMOL and other engines are separate, unaccepted gates.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time
import traceback


class GateError(RuntimeError):
    """Static diagnostic safe to include in the status-only CI artifact."""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--structure", type=Path, required=True)
    parser.add_argument("--ligand", type=Path, required=True)
    parser.add_argument('--engine', choices=('vina', 'qvinaw'), default='vina')
    args = parser.parse_args()
    if platform.system() != "Windows":
        parser.error("Native Windows and a real Qt window are required")
    app, out = args.app.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    sys.path.insert(0, str(app))
    status = {"status": "running", "native_windows": True, "steps": [],
              "interactive_pymol_accepted": False, "gpu_accepted": False,
              "scope": "installed Qt-to-host exploratory P2Rank/Vina fixture workflow, not docking accuracy"}
    client = window = None
    dialogs, callback_errors = [], []

    def save():
        (out / "summary.json").write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

    def stage(name, action):
        item = {"name": name, "status": "running"}
        status["steps"].append(item); save()
        started = time.monotonic()
        try:
            result = action()
        except BaseException:
            item.update(status="failed", seconds=round(time.monotonic() - started, 3)); save()
            raise
        item.update(status="passed", seconds=round(time.monotonic() - started, 3)); save()
        return result

    try:
        if args.engine == 'qvinaw':
            os.environ['DOCKING_UNIVERSAL_QVINAW_ACCEPTANCE'] = '1'
        import docking_universal
        if not Path(docking_universal.__file__).resolve().is_relative_to(app):
            raise GateError("GUI acceptance imported checkout code instead of installed application")
        from docking_universal.windows_scientific_runtime import scientific_environment
        from docking_universal.native_entrypoint import isolated_environment
        configuration = json.loads((app / "native-preview.json").read_text(encoding="utf-8"))
        status['interactive_pymol_accepted'] = bool(configuration.get('viewer_supported'))
        scientific, inherited, _receipt = scientific_environment(app, configuration, os.environ)
        # GUI Qt6 DLLs first. The real host client constructs the separate
        # scientific Qt5/DLL environment for its Python 3.9 child.
        os.environ.clear(); os.environ.update(isolated_environment(Path(sys.prefix), inherited))
        os.environ.update(MPLCONFIGDIR=str(out / "matplotlib-cache"), XDG_CACHE_HOME=str(out / "cache"))
        os.environ.pop("QT_QPA_PLATFORM", None)
        with_viewer = bool(configuration.get('viewer_candidate_installed'))
        if with_viewer:
            from docking_universal.windows_viewer_runtime import activate_installed_viewer
            activate_installed_viewer(app)
        from docking_universal.gui.qt import QtCore, QtWidgets
        from docking_universal.gui.desktop import StudyWindow
        from docking_universal.gui.host_client import ApplicationHostClient, ApplicationHostError
        from docking_universal.host import ApplicationHostLease
        from docking_universal.state import JsonStudyStore
        application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        application.setQuitOnLastWindowClosed(False)

        def callback_error(kind, value, tb):
            callback_errors.append(kind.__name__)
            with (out / "qt-callback.local.log").open("a", encoding="utf-8") as stream:
                traceback.print_exception(kind, value, tb, file=stream)
        sys.excepthook = callback_error

        def dialog(_parent, title, message, *_args, **_kwargs):
            dialogs.append(title)
            with (out / "dialogs.local.log").open("a", encoding="utf-8") as stream:
                stream.write(title + "\n" + message + "\n")
            return QtWidgets.QMessageBox.StandardButton.Ok
        # Capture failures rather than letting modal error dialogs hang CI.
        # No confirmation/approval dialog is accepted by this interception.
        QtWidgets.QMessageBox.critical = staticmethod(dialog)
        QtWidgets.QMessageBox.warning = staticmethod(dialog)
        root = out / "Studies Ω 日本語"
        store = JsonStudyStore(root)
        client = ApplicationHostClient(root, app / "docking-universal-application-host.py",
                                       python_executable=scientific, timeout_seconds=30)
        stage("owned_scientific_host_startup", client.start)
        expected_engines = ['vina', 'qvinaw'] if args.engine == 'qvinaw' or configuration.get('qvinaw_supported') else ['vina']
        if not client.runtime.get("native_scientific_preview") or client.runtime.get("supported_engines") != expected_engines:
            raise GateError("Installed host did not advertise the bounded native workflow")
        client.request("desktop-fixture", "create_study", {"name": "Disposable public Qt fixture Ω"})
        settings = QtCore.QSettings(str(out / "desktop.ini"), QtCore.QSettings.Format.IniFormat)

        def open_window(study="desktop-fixture"):
            viewer = widget = None
            if with_viewer:
                from docking_universal.viewer.embedded_pymol import create_embedded_pymol_widget, EmbeddedPymolAdapter
                from docking_universal.gui.study_viewer import StudyViewerCoordinator
                widget = create_embedded_pymol_widget()
                viewer = StudyViewerCoordinator(EmbeddedPymolAdapter(widget))
            result = StudyWindow(store, study, settings=settings, host_client=client,
                                viewer_coordinator=viewer, viewer_widget=widget)
            result.show(); application.processEvents()
            return result

        def close_window():
            if window is not None:
                window.close(); application.processEvents()
                if window.viewer_coordinator is not None:
                    window.viewer_coordinator.close()
                if window.viewer_widget is not None:
                    window.viewer_widget.deleteLater()
                application.processEvents()

        def wait_for(predicate, *, study="desktop-fixture", seconds=300):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                application.processEvents()
                if dialogs or callback_errors:
                    raise GateError("Qt action raised a failure dialog or callback exception; detail retained locally")
                state = store.load(study)
                if state.completion_status.value == "failed":
                    raise GateError("Scientific desktop orchestration failed; diagnostics retained locally")
                if any(job.status.value == "failed" for job in state.jobs):
                    raise GateError("Scientific desktop job failed; scientific diagnostics retained locally")
                if any(d.kind != "select_pockets" for d in state.pending_decisions):
                    raise GateError("Native preparation stopped for an unaccepted scientific intervention; decision preserved")
                if predicate(state):
                    window.refresh()
                    return state
                time.sleep(.05)
            raise GateError("Desktop fixture exceeded its bounded stage deadline; no restart was attempted")

        window = open_window()

        def rejection_gate():
            prior = store.path_for("desktop-fixture").read_bytes()
            for operation, payload in (("start_control_validation", {}),
                ("start_receptor_preparation", {"pocket_engine": "fpocket"}),
                ("start_receptor_preparation", {"preparation_backend": "adfr"}),
                ("start_protocol_finalization", {"engine": "adgpu"})):
                try:
                    client.request("desktop-fixture", operation, payload,
                                   expected_revision=store.load("desktop-fixture").revision)
                except ApplicationHostError:
                    pass
                else:
                    raise GateError("Unsupported native method was unexpectedly accepted")
                if store.path_for("desktop-fixture").read_bytes() != prior:
                    raise GateError("Unsupported native request mutated the fixture study")
            if window.study_setup_panel.redock_ligand.isEnabled():
                raise GateError("Unaccepted native control remains enabled in the Qt form")
            enabled = {window.protocol_engine.itemData(i) for i in range(window.protocol_engine.count())
                       if window.protocol_engine.model().item(i).isEnabled()}
            if enabled != set(expected_engines):
                raise GateError("Qt form offers an unaccepted native engine")
        stage("unsupported_methods_rejected_without_state_mutation", rejection_gate)
        inputs = out / "Inputs Ω 日本語"; inputs.mkdir()
        structure = inputs / "2R8N.cif"; shutil.copyfile(args.structure, structure)
        ligand = inputs / "synthetic_carbamate.sdf"; shutil.copyfile(args.ligand, ligand)

        def prepare():
            window.input_pdb.setText(str(structure))
            window.output_directory.setText(str(out / "Preparation Ω"))
            window.study_setup_panel.pdb_evidence.setChecked(False)
            if not window.start_preparation_button.isEnabled():
                raise GateError("Fresh native preparation button is disabled before submission")
            window.start_preparation_button.click()
            state = wait_for(lambda s: any(d.kind == "select_pockets" for d in s.pending_decisions))
            if state.selected_pocket_ids or state.approvals:
                raise GateError("Preparation implicitly approved a docking region")
            if state.workflow_data["study_setup"].get("pdb_pocket_evidence") != "off":
                raise GateError("Local-only evidence choice was not retained")
            status["candidate_count"] = window.candidates.rowCount()
        stage("qt_mmcif_preparation_to_explicit_site_review", prepare)

        def visual_review():
            from PyQt6.QtTest import QTest
            wait_for(lambda _s: window.viewer_coordinator.connected, seconds=30)
            adapter = window.viewer_coordinator.adapter
            if adapter.cmd.count_atoms() < 100:
                raise GateError('Installed PyMOL initial candidate scene is blank')
            frame = window.viewer_widget.grabFramebuffer()
            if frame.isNull():
                raise GateError('Installed PyMOL did not render the actual prepared receptor')
            camera, engine = tuple(adapter.cmd.get_view())[:9], window.viewer_widget.pymol
            window.detach_viewer_button.click(); QTest.qWait(400)
            detached = window._detached_structure_window
            if detached is None or not getattr(detached, '_du_full_pymol', False):
                raise GateError('Actual full-PyMOL detach button did not open its window')
            if window.viewer_widget.pymol is not engine or not hasattr(detached, 'study_panel'):
                raise GateError('Detached viewer did not retain its engine and study evidence controls')
            detached.close(); QTest.qWait(300)
            if window._detached_structure_window is not None:
                raise GateError('Detached PyMOL did not return its viewport')
            if max(abs(a-b) for a,b in zip(camera, adapter.cmd.get_view()[:9])) > 1e-5:
                raise GateError('Detached PyMOL changed the receptor orientation')
            status['installed_viewer_graphics'] = dict(zip(('vendor','renderer','version'), adapter.cmd.get_renderer()))
        if with_viewer:
            stage('installed_initial_pocket_scene_and_full_pymol_detach_return', visual_review)

        def reopen():
            nonlocal window
            prior = store.path_for("desktop-fixture").read_bytes()
            close_window()
            client.restart()
            window = open_window()
            if store.path_for("desktop-fixture").read_bytes() != prior:
                raise GateError("Reopening a retained study changed scientific state or reran a job")
        stage("pending_review_survives_window_and_host_restart", reopen)

        def approve():
            window.candidates.selectRow(0)
            window.rationale.setText("CI fixture only: inspect installed workflow, not scientific validation")
            window.approve_button.click()
            wait_for(lambda s: bool(s.selected_pocket_ids) and not s.pending_decisions, seconds=30)
        stage("explicit_qt_fixture_region_approval", approve)

        def finalize():
            window.final_output_directory.setText(str(out / "Protocol Ω"))
            window.protocol_engine.setCurrentIndex(window.protocol_engine.findData(args.engine))
            for field, value in ((window.protocol_ph, 7.4), (window.protocol_conformers, 1),
                (window.protocol_seeds, 1), (window.protocol_base_seed, 41001),
                (window.protocol_exhaustiveness, 1), (window.protocol_modes, 3), (window.protocol_energy_range, 8)):
                field.setValue(value)
            window.exploratory_approval.setChecked(True)
            window.finalize_button.click()
            state = wait_for(lambda s: not s.active_job and any(a.kind == "protocol_bundle" for a in s.artifacts))
            report = next(Path(a.path) for a in state.artifacts if a.kind == "final_report")
            if not report.read_bytes().startswith(b"%PDF-") or not window.open_final_report_button.isEnabled():
                raise GateError("Qt finalization did not retain an accessible protocol PDF")
            from docking_universal.services.protocol_import import inspect_protocol_bundle
            bundle = next(a.path for a in state.artifacts if a.kind == 'protocol_bundle')
            if inspect_protocol_bundle(bundle)['engine'] != args.engine:
                raise GateError('Final protocol did not retain the explicitly selected engine')
        stage("qt_protocol_finalization_pdf_and_bundle", finalize)

        def screen():
            window.screen_ligands.setText(str(ligand))
            window.screen_output.setText(str(out / "Screen Ω"))
            panel = window.screening_setup_panel.library_panel
            panel.read_button.click()
            wait_for(lambda _s: panel.library is not None and not panel.loading, seconds=120)
            if len(panel.library["records"]) != 1 or not panel.library["records"][0]["valid"]:
                raise GateError("Scientific host library reader did not return the synthetic fixture")
            panel.table.item(0, 0).setCheckState(QtCore.Qt.CheckState.Checked)
            window.preview_screening_button.click()
            if not window._screening_plan or window._screening_plan["total_docking_jobs"] != 1:
                raise GateError("Qt workload preview did not preserve the one-job fixture protocol")
            window.screen_exploratory_approval.setChecked(True)
            window.start_screening_button.click()
            state = wait_for(lambda s: not s.active_job and any(a.kind == "screening_report" for a in s.artifacts), seconds=600)
            kinds = {a.kind for a in state.artifacts}
            if not {"screening_pose_clusters", "screening_interaction_record", "screening_interaction_diagram"} <= kinds:
                raise GateError("Qt screen did not register clusters and local interaction evidence")
            if not all(Path(a.path).is_file() for a in state.artifacts):
                raise GateError("A registered fixture artifact is missing after screening")
            manifests = list((out / 'Screen Ω').rglob('run_manifest.tsv'))
            if not manifests or any('engine\t' + args.engine + '\n' not in p.read_text(encoding='utf-8') for p in manifests):
                raise GateError('Screening substituted or failed to record the selected engine')
            status['screening_engine'] = args.engine
            status["completed_job_count"] = sum(j.status.value == "completed" for j in state.jobs)
        stage("qt_compound_selection_preview_screening_and_results", screen)

        def paired_review():
            import hashlib
            from PyQt6.QtTest import QTest
            from docking_universal.gui.linked_pose_review import pose_view
            from docking_universal.gui.image_export import capture_pymol_image, diagram_export
            state = store.load('desktop-fixture')
            views = [pose_view(Path(a.path)) for a in state.artifacts if a.kind == 'screening_interaction_diagram']
            view = next((item for item in views if item is not None), None)
            if view is None or view.coordinate_kind != 'docked':
                raise GateError('No exact docked-pose interaction view was retained')
            original = hashlib.sha256(view.diagram.read_bytes()).hexdigest()
            if not window._open_interaction_review(view):
                raise GateError('Actual paired 2D/3D window could not open')
            QTest.qWait(500)
            popup = window._paired_interaction_window
            adapter = window.viewer_coordinator.adapter
            if popup is None or adapter.cmd.count_atoms('du_review_pose') == 0:
                raise GateError('Paired window did not load the matching docked ligand')
            for action in popup.contact_type_actions.values():
                action.setChecked(False); action.setChecked(True)
            if popup._residues:
                popup.labels.setChecked(True)
                if not adapter.has_review_residue_labels():
                    raise GateError('Paired residue-label option did not label contacting residues')
                popup.labels.setChecked(False)
                if adapter.has_review_residue_labels():
                    raise GateError('Paired residue labels did not toggle off')
                popup.clicked_residue(popup._residues[0])
            popup.clicked_ligand()
            if capture_pymol_image(window.viewer_widget).isNull() or diagram_export(view).image.isNull():
                raise GateError('Current 3D or retained 2D image export is empty')
            if hashlib.sha256(view.diagram.read_bytes()).hexdigest() != original:
                raise GateError('Interactive visibility changes modified the retained 2D image')
            popup.close(); QTest.qWait(300)
            if window._paired_interaction_window is not None:
                raise GateError('Paired 2D/3D viewport did not return normally')
        if with_viewer:
            stage('installed_docked_pose_linked_2d_3d_labels_contacts_and_exports', paired_review)
        stage("completed_screen_survives_window_and_host_restart", reopen)

        def cancel():
            nonlocal window
            close_window()
            client.request("cancel-fixture", "create_study", {"name": "Disposable cancellation fixture"})
            window = open_window("cancel-fixture")
            window.input_pdb.setText(str(structure))
            window.output_directory.setText(str(out / "Cancelled preparation Ω"))
            window.study_setup_panel.pdb_evidence.setChecked(False)
            window.start_preparation_button.click()
            state = wait_for(lambda s: s.active_job and s.active_job.process_id, study="cancel-fixture", seconds=60)
            pid = state.active_job.process_id
            window.cancel_job_button.click()
            state = wait_for(lambda s: not s.active_job, study="cancel-fixture", seconds=45)
            if not state.jobs or state.jobs[-1].status.value != "cancelled" or state.approvals:
                raise GateError("Qt cancellation did not retain an unapproved cancelled job")
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
            kernel.OpenProcess.restype = wintypes.HANDLE
            handle = kernel.OpenProcess(0x00100000, False, pid)
            if handle:
                kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
                kernel.CloseHandle.argtypes = [wintypes.HANDLE]
                try:
                    if kernel.WaitForSingleObject(handle, 5000) != 0:
                        raise GateError("Cancelled preparation process remained alive")
                finally:
                    kernel.CloseHandle(handle)
        stage("qt_cancellation_reaps_owned_process_without_approval", cancel)
        close_window(); window = None; application.processEvents()
        reader = client._reader
        client.close()
        if reader.is_alive():
            raise GateError("Scientific host reader survived normal desktop close")
        with ApplicationHostLease(root):
            pass
        status.update(status="passed", gui_qt=QtCore.qVersion(), gui_python=platform.python_version(),
                      host_python=client.python_executable.name, lease_released=True,
                      fixture_approval_only=True, failure_dialog_count=len(dialogs),
                      installed_interactive_viewer_fixture_passed=with_viewer)
    except BaseException as exc:
        status.update(status="failed", error_type=type(exc).__name__,
                      error=str(exc) if isinstance(exc, GateError) else "Desktop acceptance raised an exception; full detail retained locally",
                      locations=[{"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                                 for frame in traceback.extract_tb(exc.__traceback__)],
                      callback_error_types=callback_errors, failure_dialog_count=len(dialogs))
        (out / "exception.local.log").write_text(traceback.format_exc(), encoding="utf-8")
        if 'store' in locals():
            status['study_states'] = [{
                'completion_status': s.completion_status.value,
                'jobs': [{'stage': j.stage, 'status': j.status.value,
                          'progress_phase': j.progress_phase,
                          'process_identity_recorded': j.process_id is not None} for j in s.jobs],
                'pending_kinds': [d.kind for d in s.pending_decisions],
                'orchestration_errors': [{'type': e.technical.get('error_type'),
                                          'locations': e.technical.get('error_locations', [])} for e in s.events
                                         if e.technical.get('component') == 'ProtocolWorkflowRunner'],
            } for s in store.list_studies()]
        exceptions, locations = set(), []
        native_steps, service_markers = [], []
        for path in out.rglob('*.log'):
            for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
                for step in ('p2rank_version', 'native-receptor', 'reduce2', 'receptor_backend',
                             'pdbfixer', 'receptor_after_pdbfixer', 'ccd_audit', 'p2rank'):
                    if line.strip() == 'Running ' + step:
                        native_steps.append(step)
                for marker in ('verifying runtime', 'starting preparation'):
                    if line.strip() == 'Native preparation service: ' + marker:
                        service_markers.append(marker)
                match = re.match(r'^(\w*(?:Error|Exception)):', line)
                if match:
                    exceptions.add(match.group(1))  # type only, never message/coordinates
                match = re.match(r'\s*File "([^"]+)", line (\d+), in ([\w<>]+)', line)
                if match:
                    locations.append({'file': Path(match.group(1)).name,
                                      'line': int(match.group(2)), 'function': match.group(3)})
        status['runtime_exception_types'] = sorted(exceptions)
        status['native_step_markers'] = native_steps
        status['native_service_markers'] = service_markers
        status['runtime_traceback_locations'] = locations[-16:]
        status['preparation_attempts'] = []
        for path in out.rglob('native-preparation.json'):
            record = json.loads(path.read_text(encoding='utf-8'))
            status['preparation_attempts'].append({'status': record.get('status'),
                'steps': [{key: item.get(key) for key in ('step', 'returncode', 'accepted')}
                          for item in record.get('attempts', [])]})
    finally:
        if client:
            client.close()
        # The host's owned Job has now stopped all work; do not prompt to
        # cancel in cleanup, or manipulate persisted job state to hide failure.
        if window:
            window.hide()
            if window.viewer_coordinator is not None:
                window.viewer_coordinator.close()
    save()
    print(json.dumps(status))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
