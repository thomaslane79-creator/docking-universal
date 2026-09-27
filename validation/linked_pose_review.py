"""Exercise simultaneous 2D/3D review with the real embedded PyMOL engine."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libexec"))
from docking_universal.gui.qt import QtCore, QtWidgets
from PyQt6 import QtTest
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.study_viewer import StudyViewerCoordinator
from docking_universal.state import JsonStudyStore
from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter, create_embedded_pymol_widget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--diagram", type=Path, required=True)
    parser.add_argument("--second-diagram", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    widget = create_embedded_pymol_widget()
    adapter = EmbeddedPymolAdapter(widget)
    coordinator = StudyViewerCoordinator(adapter)
    window = StudyWindow(JsonStudyStore(args.state_root), args.study,
                         settings=QtCore.QSettings(str(args.output / "settings.ini"), QtCore.QSettings.Format.IniFormat),
                         viewer_coordinator=coordinator, viewer_widget=widget)
    result = {"passed": False}

    def exercise():
        try:
            assert window._present_linked_diagram(args.diagram)
            app.processEvents()
            panel = window.linked_pose_panel
            assert widget.isVisible() and panel.isVisible()
            assert window.pose_split.indexOf(widget) == 0
            before = adapter.cmd.get_view()
            QtTest.QTest.mouseClick(panel.query_image, QtCore.Qt.MouseButton.LeftButton)
            assert adapter.cmd.count_atoms("du_ligand_highlight") == adapter.cmd.count_atoms("du_review_pose") > 0
            assert adapter.cmd.get_view() == before
            assert window._present_linked_diagram(args.second_diagram)
            assert adapter.cmd.get_view() == before
            assert adapter.review_pose == (args.second_diagram.parent.parent / "representative.sdf").resolve()
            for width, height in ((1100, 760), (1440, 900), (1280, 800)):
                window.resize(width, height)
                app.processEvents()
                assert widget.isVisible() and panel.isVisible()
            window.detach_embedded_viewer()
            app.processEvents()
            assert widget.window() is panel.window() is window._detached_structure_window
            window._detached_structure_window.close()
            app.processEvents()
            window.grab().save(str(args.output / "linked-review.png"))
            result.update(passed=True, highlighted_atoms=adapter.cmd.count_atoms("du_review_pose"),
                          objects=adapter.cmd.get_names("objects"))
        except Exception as exc:
            import traceback
            result["error"] = str(exc)
            traceback.print_exc()
        finally:
            window.close()
            adapter.close()
            result["clean_shutdown"] = not adapter.is_alive()
            (args.output / "result.json").write_text(json.dumps(result, indent=2))
            app.quit()

    window.resize(1280, 800)
    window.show()
    QtCore.QTimer.singleShot(1200, exercise)
    app.exec()
    print(json.dumps(result))
    return 0 if result["passed"] and result["clean_shutdown"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
