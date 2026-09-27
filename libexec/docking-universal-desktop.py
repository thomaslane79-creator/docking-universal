#!/usr/bin/env python3
"""Open the Docking Universal dockable scientific-workflow workspace."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path)
    parser.add_argument("--study")
    parser.add_argument("--create-name", help="create the named study if --study does not exist")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--detach", action="store_true", help="run the GUI independently of the launching terminal")
    parser.add_argument(
        "--screenshot", type=Path,
        help="capture only the rendered Docking Universal window, then exit",
    )
    parser.add_argument("--pymol", type=Path, help="explicit PyMOL executable for required structural review")
    parser.add_argument(
        "--viewer-backend", choices=("auto", "embedded", "companion", "none"), default="auto",
        help="structural-viewer backend; auto prefers embedded PyMOL when importable",
    )
    parser.add_argument(
        "--host-python", type=Path,
        help="Python executable for the isolated scientific application host",
    )
    args = parser.parse_args()
    if args.detach:
        child_args = [arg for arg in sys.argv[1:] if arg != "--detach"]
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), *child_args],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        return 0
    from docking_universal.gui.desktop import StudyWindow, require_qt
    from docking_universal.gui.qt import QtCore, QtGui, QtWidgets
    from docking_universal.gui.branding import application_icon_path
    from docking_universal.gui.host_client import ApplicationHostClient
    from docking_universal.gui.study_viewer import StudyViewerCoordinator
    from docking_universal.gui.study_launcher import choose_study
    from docking_universal.state import JsonStudyStore
    from docking_universal.viewer.pymol_adapter import PymolAdapter

    require_qt()
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    application.setApplicationName("Docking Universal")
    application.setWindowIcon(QtGui.QIcon(str(application_icon_path())))
    state_root = args.state_root or (
        Path(QtCore.QStandardPaths.writableLocation(
            QtCore.QStandardPaths.StandardLocation.AppLocalDataLocation
        )) / "studies"
    )
    host_script = Path(__file__).with_name("docking-universal-application-host.py")
    with ApplicationHostClient(
        state_root, host_script, python_executable=args.host_python,
    ) as host:
        store = JsonStudyStore(state_root)
        study_id = args.study
        if study_id and not store.path_for(study_id).is_file():
            if not args.create_name:
                parser.error("the requested study does not exist; provide --create-name to create it")
            host.request(study_id, "create_study", {"name": args.create_name})
        if not study_id:
            study_id = choose_study(store, host)
            if not study_id:
                return 0
        pymol = args.pymol or shutil.which("pymol")
        use_embedded = args.viewer_backend == "embedded"
        if args.viewer_backend == "auto":
            try:
                import pymol as _embedded_pymol  # noqa: F401
                from pmg_qt.pymol_gl_widget import PyMOLGLWidget as _EmbeddedWidget  # noqa: F401
            except ImportError:
                use_embedded = False
            else:
                use_embedded = True
        active = {"window": None, "viewer": None}

        def create_viewer(selected_study_id):
            if use_embedded:
                from docking_universal.viewer.embedded_pymol import (
                    EmbeddedPymolAdapter, create_embedded_pymol_widget,
                )
                widget = create_embedded_pymol_widget()
                return StudyViewerCoordinator(EmbeddedPymolAdapter(widget)), widget
            if args.viewer_backend != "none" and pymol:
                return StudyViewerCoordinator(PymolAdapter(
                    pymol,
                    Path(__file__).with_name("docking-universal-pymol-spike-bridge.py"),
                    state_root / selected_study_id / "viewer-logs",
                )), None
            return None, None

        def show_study(selected_study_id):
            previous_window = active["window"]
            previous_viewer = active["viewer"]
            if previous_window is not None:
                previous_window.hide()
            if previous_viewer is not None:
                previous_viewer.close()
            viewer, viewer_widget = create_viewer(selected_study_id)
            window = StudyWindow(
                store, selected_study_id,
                host_client=host, viewer_coordinator=viewer, viewer_widget=viewer_widget,
            )
            active["window"] = window
            active["viewer"] = viewer
            window.studySwitchRequested.connect(show_study)
            window.showFullScreen() if args.fullscreen else window.showMaximized()
            if previous_window is not None:
                previous_window.close()
                previous_window.deleteLater()
            return window

        window = show_study(study_id)
        try:
            if args.screenshot:
                screenshot = args.screenshot.resolve()
                screenshot.parent.mkdir(parents=True, exist_ok=True)

                def capture_window() -> None:
                    image = window.grab()
                    if not image.save(str(screenshot)):
                        application.exit(1)
                        return
                    application.quit()

                QtCore.QTimer.singleShot(1200, capture_window)
            return application.exec()
        finally:
            if active["viewer"]:
                active["viewer"].close()


if __name__ == "__main__":
    raise SystemExit(main())
