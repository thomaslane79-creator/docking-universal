"""Read-only real-renderer check of pocket/evidence review before reports exist."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libexec"))
from docking_universal.gui.qt import QtCore, QtWidgets
from PyQt6.QtTest import QTest
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.study_viewer import StudyViewerCoordinator
from docking_universal.state import JsonStudyStore
from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter, create_embedded_pymol_widget


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--study", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    store = JsonStudyStore(args.state_root)
    original = store.path_for(args.study).read_bytes()
    widget = create_embedded_pymol_widget()
    adapter = EmbeddedPymolAdapter(widget)
    viewer = StudyViewerCoordinator(adapter)
    settings = QtCore.QSettings(str(args.out / "window.ini"), QtCore.QSettings.Format.IniFormat)
    window = StudyWindow(store, args.study, settings=settings,
                         viewer_coordinator=viewer, viewer_widget=widget)
    result = {"status": "running", "checks": []}

    def check(name, condition):
        result["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    def exercise():
        try:
            window.workflow_navigation.setCurrentRow(2)
            plot = window.pocket_score_plot
            index = next(i for i, point in enumerate(plot.points) if point[0] == "P2")
            QTest.mouseClick(plot, QtCore.Qt.MouseButton.LeftButton,
                             pos=plot.positions()[index].toPoint())
            check("P2 plot opens embedded engine", adapter.is_alive())
            check("matching table row selected", window.candidates.selectionModel().selectedRows()[0].row() == 1)
            check("interactive tab active", window.review_tabs.currentIndex() == 1)
            check("receptor loaded", adapter.cmd.count_atoms("polymer") > 0)
            observations = window.state.workflow_data["pocket_candidates"][0]["evidence"]["experimental_ligand_evidence"]["observations"]
            ligand = observations[0]["aligned_ligand_pdb"]
            # Exercise the previously broken first-open evidence route too.
            viewer.connected = False
            window.show_evidence_ligand(ligand)
            check("evidence loads without report scene", viewer.connected and viewer.status != "failed")
            evidence_names = [name for name in adapter.cmd.get_names("objects", enabled_only=1)
                              if name.startswith("du_evidence_")]
            check("aligned ligand visible", len(evidence_names) == 1
                  and adapter.cmd.count_atoms(evidence_names[0]) > 0)
            QTest.qWait(400)
            check("nonempty framebuffer", not widget.grabFramebuffer().isNull())
            check("one host window", len([w for w in app.topLevelWidgets() if w.isVisible()]) == 1)
            window.grab().save(str(args.out / "embedded-review.png"))
            result["status"] = "passed"
        except Exception as exc:
            result["status"] = "failed"
            result["error"] = str(exc)
        finally:
            viewer.close()
            check("engine stopped", not adapter.is_alive())
            window.close()
            check("scientific state unchanged", store.path_for(args.study).read_bytes() == original)
            (args.out / "result.json").write_text(json.dumps(result, indent=2))
            app.exit(0 if result["status"] == "passed" else 1)

    window.resize(1200, 800)
    window.show()
    QtCore.QTimer.singleShot(600, exercise)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
