#!/usr/bin/env python3
"""Open the Docking Universal dockable scientific-workflow workspace."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from docking_universal.gui.desktop import StudyWindow, require_qt
from docking_universal.state import JsonStudyStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--fullscreen", action="store_true")
    args = parser.parse_args()
    require_qt()
    from PyQt5 import QtWidgets
    application = QtWidgets.QApplication.instance() or QtWidgets.QApplication(sys.argv)
    window = StudyWindow(JsonStudyStore(args.state_root), args.study)
    window.showFullScreen() if args.fullscreen else window.show()
    return application.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
