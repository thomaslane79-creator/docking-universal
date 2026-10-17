"""Validate fresh pocket-review initialization with one genuine PyMOL engine."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libexec"))
from docking_universal.application import StudyController
from docking_universal.models import ArtifactRecord, PocketCandidate
from docking_universal.state import JsonStudyStore
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.study_viewer import StudyViewerCoordinator
from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter, create_embedded_pymol_widget
from PyQt6.QtTest import QTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    with TemporaryDirectory() as temporary:
        store = JsonStudyStore(Path(temporary) / "state")
        controller = StudyController(store)
        controller.create_study("initial", "Isolated initial scene validation")
        candidates = []
        for identity, rank, x in (("P1", 1, 45), ("P2", 2, 50)):
            evidence = {
                "geometry": {"center_x": x, "center_y": 43, "center_z": -23,
                             "size_x": 20, "size_y": 20, "size_z": 20},
            }
            if identity == "P1":
                # UI identity fixture; this is not a calculated scientific finding.
                evidence["conformational_site_evidence"] = {
                    "status": "conformationally_incompatible",
                    "occluding_residues": [{"name": "ASP", "number": "30", "chain": "A"}],
                }
            candidates.append(PocketCandidate(identity, identity, rank, "box", "Validation region", evidence))
        controller.start_simulated_pocket_review("initial", candidates)
        state = store.load("initial")
        receptor = Path(__file__).resolve().parents[1] / "examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb"
        state.artifacts.append(ArtifactRecord("receptor", "prepared_receptor_structure", str(receptor),
                                             hashlib.sha256(receptor.read_bytes()).hexdigest()))
        store.save(state)
        original = store.path_for("initial").read_bytes()
        widget = create_embedded_pymol_widget()
        adapter = EmbeddedPymolAdapter(widget)
        coordinator = StudyViewerCoordinator(adapter)
        window = StudyWindow(store, "initial", viewer_widget=widget, viewer_coordinator=coordinator,
                             settings=QtCore.QSettings(str(Path(temporary) / "window.ini"), QtCore.QSettings.Format.IniFormat))
        result = {"checks": []}

        def check(name, condition):
            result["checks"].append({"name": name, "passed": bool(condition)})
            if not condition:
                raise AssertionError(name)

        def exercise():
            try:
                check("only interactive review remains", window.review_tabs.count() == 1
                      and window.review_tabs.currentWidget() is window.live_page)
                check("static figure viewer is absent", window.findChild(QtWidgets.QWidget, 'decision_figure_view') is None)
                check("initial P1 loads without another candidate click", coordinator.connected and adapter.is_alive())
                check("whole protein is present", adapter.cmd.count_atoms("du_receptor and polymer") > 0)
                check("P1 box is present", "du_box" in adapter.cmd.get_names("objects"))
                check("P1 remains highlighted", window.candidates.selectionModel().selectedRows()[0].row() == 0)
                engine = adapter.cmd._COb
                camera = tuple(adapter.cmd.get_view())
                panel = window.pocket_evidence_panel
                check("live review has no redundant observation-load button", panel.compare_button.isHidden())
                check("main residue highlight action is available", panel.highlight_obstruction_button.isVisible())
                colors = []
                adapter.cmd.iterate("du_receptor", "colors.append(color)", space={"colors": colors})
                adapter.cmd.show("sticks", "du_receptor and chain A and resi 30 and name CA")
                previous_sticks = adapter.cmd.count_atoms("du_receptor and rep sticks")
                panel.highlight_obstruction_button.click()
                atoms = adapter.cmd.get_model("du_receptor and rep sticks").atom
                check("main button shows exactly ASP30A sticks", bool(atoms) and all(
                    atom.chain == "A" and atom.resn == "ASP" and atom.resi == "30" for atom in atoms))
                check("main button leaves no atom-selection overlay", "du_obstruction" not in adapter.cmd.get_names("selections"))
                after_colors = []
                adapter.cmd.iterate("du_receptor", "colors.append(color)", space={"colors": after_colors})
                check("main highlight preserves camera and colors", camera == tuple(adapter.cmd.get_view()) and colors == after_colors)
                check("main highlight does not detach or relaunch", window._detached_structure_window is None and adapter.cmd._COb is engine)
                check("button displays highlight state", panel.highlight_obstruction_button.isChecked())
                panel.highlight_obstruction_button.click()
                check("second click clears only the app highlight", "du_obstruction" not in adapter.cmd.get_names("selections")
                      and adapter.cmd.count_atoms("du_receptor and rep sticks") == previous_sticks)
                check("toggle off preserves camera", camera == tuple(adapter.cmd.get_view()))
                check("toggle off updates button", not panel.highlight_obstruction_button.isChecked())
                panel.highlight_obstruction_button.click()
                window.refresh()
                check("polling retains highlight state", panel.highlight_obstruction_button.isChecked())
                panel.guide_button.click()
                check("optional walkthrough is modeless", panel._guide_window.isVisible() and not panel._guide_window.isModal())
                panel._guide_window.close()
                item = window.candidates.item(0, 0)
                QTest.mouseClick(window.candidates.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                 pos=window.candidates.visualItemRect(item).center())
                QTest.qWait(100)
                check("clicking already selected P1 leaves loaded view stable", tuple(adapter.cmd.get_view()) == camera)
                window.refresh()
                window.refresh()
                QTest.qWait(1100)
                check("polling does not reload or recenter camera", tuple(adapter.cmd.get_view()) == camera)
                for row in (1, 0):
                    item = window.candidates.item(row, 0)
                    QTest.mouseClick(window.candidates.viewport(), QtCore.Qt.MouseButton.LeftButton,
                                     pos=window.candidates.visualItemRect(item).center())
                    QTest.qWait(100)
                    check(f"row {row} uses the original engine", adapter.cmd._COb is engine)
                    check(f"row {row} shows only an available highlight action", panel.highlight_obstruction_button.isVisible() == (row == 0))
                check("no second PyMOL window", len([w for w in app.topLevelWidgets() if w.isVisible()]) == 1)
                workflow_row = window.workflow_navigation.currentRow()
                window_size = window.size()
                window.workflow_action.trigger()
                window.refresh()
                QTest.qWait(100)
                check("workflow hides and stays hidden during refresh", window.workflow_navigation_dock.isHidden()
                      and not window.workflow_action.isChecked())
                window.workflow_action.trigger()
                QTest.qWait(100)
                check("workflow toggle restores docked panel", window.workflow_navigation_dock.isVisible()
                      and not window.workflow_navigation_dock.isFloating() and window.workflow_action.isChecked())
                check("workflow toggle keeps stage and window size", window.workflow_navigation.currentRow() == workflow_row
                      and window.size() == window_size)
                check("workflow toggle does not reload PyMOL", adapter.cmd._COb is engine)
                check("nonempty framebuffer", not widget.grabFramebuffer().isNull())
                window.grab().save(str(args.output / "initial-review.png"))
                check("viewing does not modify scientific study", store.path_for("initial").read_bytes() == original)
                result["status"] = "passed"
            except Exception as exc:
                import traceback
                result.update(status="failed", error=str(exc), traceback=traceback.format_exc())
            finally:
                window.close()
                adapter.close()
                (args.output / "verification.json").write_text(json.dumps(result, indent=2))
                app.exit(0 if result["status"] == "passed" else 1)

        window.show()
        QtCore.QTimer.singleShot(700, exercise)
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
