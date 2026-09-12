#!/usr/bin/env python3
"""Open the Docking Universal dockable scientific-workflow workspace."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from docking_universal.gui.desktop import StudyWindow, require_qt
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.gui.study_viewer import StudyViewerCoordinator
from docking_universal.state import JsonStudyStore
from docking_universal.viewer.pymol_adapter import PymolAdapter


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--create-name", help="create the named study if --study does not exist")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--pymol", type=Path, help="explicit PyMOL executable for required structural review")
    args = parser.parse_args()
    require_qt()
    from PyQt5 import QtWidgets
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    host_script = Path(__file__).with_name("docking-universal-application-host.py")
    pymol = args.pymol or shutil.which("pymol")
    viewer = None
    if pymol:
        viewer = StudyViewerCoordinator(PymolAdapter(
            pymol,
            Path(__file__).with_name("docking-universal-pymol-spike-bridge.py"),
            args.state_root / args.study / "viewer-logs",
        ))
    with ApplicationHostClient(args.state_root, host_script) as host:
        store = JsonStudyStore(args.state_root)
        if not store.path_for(args.study).is_file():
            if not args.create_name:
                parser.error("the requested study does not exist; provide --create-name to create it")
            host.request(args.study, "create_study", {"name": args.create_name})
        window = StudyWindow(
            store, args.study,
            host_client=host, viewer_coordinator=viewer,
        )
        try:
            window.showFullScreen() if args.fullscreen else window.show()
            return application.exec_()
        finally:
            if viewer:
                viewer.close()


if __name__ == "__main__":
    raise SystemExit(main())
