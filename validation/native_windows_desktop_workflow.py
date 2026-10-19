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
        import docking_universal
        if not Path(docking_universal.__file__).resolve().is_relative_to(app):
            raise GateError("GUI acceptance imported checkout code instead of installed application")
        from docking_universal.windows_scientific_runtime import scientific_environment
        from docking_universal.native_entrypoint import isolated_environment
        configuration = json.loads((app / "native-preview.json").read_text(encoding="utf-8"))
        scientific, inherited, _receipt = scientific_environment(app, configuration, os.environ)
        # GUI Qt6 DLLs first. The real host client constructs the separate
        # scientific Qt5/DLL environment for its Python 3.9 child.
        os.environ.clear(); os.environ.update(isolated_environment(Path(sys.prefix), inherited))
        os.environ.update(MPLCONFIGDIR=str(out / "matplotlib-cache"), XDG_CACHE_HOME=str(out / "cache"))
        os.environ.pop("QT_QPA_PLATFORM", None)
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
        if not client.runtime.get("native_scientific_preview") or client.runtime.get("supported_engines") != ["vina"]:
            raise GateError("Installed host did not advertise the bounded native workflow")
        client.request("desktop-fixture", "create_study", {"name": "Disposable public Qt fixture Ω"})
        settings = QtCore.QSettings(str(out / "desktop.ini"), QtCore.QSettings.Format.IniFormat)

        def open_window(study="desktop-fixture"):
            result = StudyWindow(store, study, settings=settings, host_client=client)
            result.show(); application.processEvents()
            return result

        def wait_for(predicate, *, study="desktop-fixture", seconds=300):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                application.processEvents()
                if dialogs or callback_errors:
                    raise GateError("Qt action raised a failure dialog or callback exception; detail retained locally")
                state = store.load(study)
                if any(job.status.value == "failed" for job in state.jobs):
                    raise GateError("Scientific desktop job failed; scientific diagnostics retained locally")
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
            if enabled != {"vina"}:
                raise GateError("Qt form offers an unaccepted native engine")
        stage("unsupported_methods_rejected_without_state_mutation", rejection_gate)
        inputs = out / "Inputs Ω 日本語"; inputs.mkdir()
        structure = inputs / "2R8N.cif"; shutil.copyfile(args.structure, structure)
        ligand = inputs / "synthetic_carbamate.sdf"; shutil.copyfile(args.ligand, ligand)

        def prepare():
            window.input_pdb.setText(str(structure))
            window.output_directory.setText(str(out / "Preparation Ω"))
            window.study_setup_panel.pdb_evidence.setChecked(False)
            window.start_preparation_button.click()
            state = wait_for(lambda s: any(d.kind == "select_pockets" for d in s.pending_decisions))
            if state.selected_pocket_ids or state.approvals:
                raise GateError("Preparation implicitly approved a docking region")
            if state.workflow_data["study_setup"].get("pdb_pocket_evidence") != "off":
                raise GateError("Local-only evidence choice was not retained")
            status["candidate_count"] = window.candidates.rowCount()
        stage("qt_mmcif_preparation_to_explicit_site_review", prepare)

        def reopen():
            nonlocal window
            prior = store.path_for("desktop-fixture").read_bytes()
            window.close(); application.processEvents()
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
            status["completed_job_count"] = sum(j.status.value == "completed" for j in state.jobs)
        stage("qt_compound_selection_preview_screening_and_results", screen)
        stage("completed_screen_survives_window_and_host_restart", reopen)

        def cancel():
            nonlocal window
            window.close(); application.processEvents()
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
        window.close(); window = None; application.processEvents()
        reader = client._reader
        client.close()
        if reader.is_alive():
            raise GateError("Scientific host reader survived normal desktop close")
        with ApplicationHostLease(root):
            pass
        status.update(status="passed", gui_qt=QtCore.qVersion(), gui_python=platform.python_version(),
                      host_python=client.python_executable.name, lease_released=True,
                      fixture_approval_only=True, failure_dialog_count=len(dialogs))
    except BaseException as exc:
        status.update(status="failed", error_type=type(exc).__name__,
                      error=str(exc) if isinstance(exc, GateError) else "Desktop acceptance raised an exception; full detail retained locally",
                      locations=[{"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                                 for frame in traceback.extract_tb(exc.__traceback__)],
                      callback_error_types=callback_errors, failure_dialog_count=len(dialogs))
        (out / "exception.local.log").write_text(traceback.format_exc(), encoding="utf-8")
    finally:
        if client:
            client.close()
        # The host's owned Job has now stopped all work; do not prompt to
        # cancel in cleanup, or manipulate persisted job state to hide failure.
        if window:
            window.hide()
    save()
    print(json.dumps(status))
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
