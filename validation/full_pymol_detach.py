"""Exercise full upstream PyMOL around the real production embedded engine."""
import argparse
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libexec"))
from docking_universal.application import StudyController
from docking_universal.state import JsonStudyStore
from docking_universal.models import PocketCandidate
from docking_universal.gui.qt import QtCore, QtWidgets
from PyQt6.QtTest import QTest
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.study_viewer import StudyViewerCoordinator
from docking_universal.viewer.embedded_pymol import create_embedded_pymol_widget, EmbeddedPymolAdapter


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    temporary = TemporaryDirectory()
    store = JsonStudyStore(Path(temporary.name) / "state")
    controller = StudyController(store)
    controller.create_study("validation", "Isolated full PyMOL validation")
    controller.start_simulated_pocket_review("validation", [PocketCandidate("P1", "P1", 1, "box", "validation", {})])
    widget = create_embedded_pymol_widget()
    adapter = EmbeddedPymolAdapter(widget)
    window = StudyWindow(store, "validation", viewer_widget=widget,
        viewer_coordinator=StudyViewerCoordinator(adapter),
        settings=QtCore.QSettings(str(Path(temporary.name) / "window.ini"), QtCore.QSettings.Format.IniFormat))
    window.show()
    window.review_tabs.setCurrentWidget(window.live_page)
    result = {"checks": []}

    def check(name, condition):
        result["checks"].append({"name": name, "passed": bool(condition)})
        if not condition:
            raise AssertionError(name)

    def exercise():
        try:
            from pmg_qt import pymol_qt_gui
            factory = pymol_qt_gui.PyMOLGLWidget
            adapter.launch()
            receptor = Path(__file__).resolve().parents[1] / "examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb"
            widget.cmd.load(str(receptor), "receptor")
            widget.cmd.hide("everything")
            widget.cmd.show("cartoon", "receptor")
            widget.cmd.color("gray70", "receptor")
            widget.cmd.select("surface_region", "receptor and resi 25-35")
            widget.cmd.show("surface", "surface_region")
            widget.cmd.set("transparency", 0.35, "receptor")
            widget.cmd.zoom("receptor", buffer=8)
            observations = []
            for number in (300, 301):
                ligand = Path(temporary.name) / f"GOL_{number}.pdb"
                widget.cmd.save(str(ligand), f"receptor and resn GOL and resi {number}")
                observations.append({"entry": "2R8N", "ligand": "GOL", "source_ligand_id": f"2R8N/GOL/A/{number}",
                    "aligned_ligand_pdb": str(ligand), "evidence_class": "exact_sequence_match"})
            state = store.load("validation")
            # Offline-status fixture: no public lookup or sequence upload occurs here.
            state.workflow_data["pdb_pocket_evidence"] = {
                "mode": "related-structures", "status": "unavailable",
                "detail": "Simulated offline validation fixture",
            }
            for identity, rank, x in (("P1", 1, 45), ("P2", 2, 50)):
                candidate = {"id": identity, "label": identity, "rank": rank, "summary": "Validation region", "evidence": {
                    "geometry": {"center_x": x, "center_y": 43, "center_z": -23, "size_x": 20, "size_y": 20, "size_z": 20},
                    "experimental_ligand_evidence": {"observations": observations, "observation_count": 2}}}
                if identity == "P1":
                    # UI/identity fixture, not a calculated obstruction finding.
                    candidate["evidence"]["conformational_site_evidence"] = {
                        "status": "conformationally_incompatible",
                        "box_decision_warning": "Validation warning fixture",
                        "occluding_residues": [{"name": "ASP", "number": "30", "chain": "A"}],
                    }
                    state.workflow_data["pocket_candidates"][0] = candidate
                else:
                    state.workflow_data["pocket_candidates"].append(candidate)
            store.save(state)
            window.viewer_coordinator.connected = True
            window.refresh()
            camera = tuple(widget.cmd.get_view())
            engine = widget.cmd._COb
            names = widget.cmd.get_names("objects")
            revision = store.load("validation").revision
            for iteration in range(3):
                widget.cmd.turn('y', 17)
                widget.cmd.move('x', 2)
                camera = tuple(widget.cmd.get_view())
                if iteration == 0:
                    widget.cmd.clip('slab', 2, 'receptor')
                    camera = tuple(widget.cmd.get_view())
                window.detach_viewer_button.click()
                app.processEvents()
                full = window._detached_structure_window
                QTest.qWait(150)
                check(f"cycle {iteration}: genuine full upstream shell", isinstance(full, pymol_qt_gui.PyMOLQtGUI))
                check("opens maximized without native fullscreen", full.isMaximized() and not full.isFullScreen())
                result.setdefault('console_dimensions', []).append({
                    'actual': full.ext_window.height(), 'minimum': full.ext_window.minimumSizeHint().height(),
                    'contents_minimum': full.ext_window.widget().minimumSizeHint().height(),
                    'contents_hint': full.ext_window.widget().sizeHint().height(),
                    'controls_expanded': full.quick_controls_toggle.isChecked(),
                })
                check("command area opens at minimum usable height",
                      full.ext_window.height() <= full.ext_window.minimumSizeHint().height() + 8)
                check("native shortcut buttons start collapsed", not full.quick_controls_toggle.isChecked())
                compact_height = full.ext_window.height()
                full.quick_controls_toggle.click()
                app.processEvents()
                check("native shortcut controls expand on demand", full.quick_controls_toggle.isChecked()
                      and full.ext_window.height() > compact_height + 30)
                full.quick_controls_toggle.click()
                app.processEvents()
                progress_function = widget.cmd.get_progress
                try:
                    widget.cmd.get_progress = lambda: 0.5  # UI-only progress fixture
                    full.update_progress()
                    app.processEvents()
                    check("native calculation reveals Abort even with shortcuts collapsed",
                          full.abortbutton.isVisible() and full.quick_controls_toggle.isChecked())
                finally:
                    widget.cmd.get_progress = progress_function
                    full.update_progress()
                    full.quick_controls_toggle.setChecked(False)
                    app.processEvents()
                full.resizeDocks([full.ext_window], [compact_height + 60], QtCore.Qt.Orientation.Vertical)
                app.processEvents()
                check("command area remains expandable", full.ext_window.height() > compact_height + 30)
                full.compact_command_area()
                app.processEvents()
                check("same engine and viewport", full.pymolwidget is widget and widget.cmd._COb is engine)
                opened_camera = tuple(widget.cmd.get_view())
                check("objects and framing preserved", names == widget.cmd.get_names("objects")
                      and camera[:15] == opened_camera[:15] and camera[17] == opened_camera[17])
                check("full PyMOL opening only widens clipping", opened_camera[15] <= camera[15]
                      and opened_camera[16] >= camera[16])
                widget.cmd.clip('atoms', 6, 'enabled')
                needed = tuple(widget.cmd.get_view())
                check("full PyMOL starts with entire geometry unclipped", opened_camera[15] <= needed[15]
                      and opened_camera[16] >= needed[16])
                widget.cmd.set_view(opened_camera)
                camera = opened_camera
                check("native constructor factory restored", pymol_qt_gui.PyMOLGLWidget is factory)
                check("command line and menus available", full.lineedit is not None and "Setting" in full.menudict)
                check("object controls enabled", widget.cmd.get_setting_int("internal_gui") == 1)
                if iteration == 0:
                    from unittest.mock import patch
                    from docking_universal.gui.qt import QtGui
                    image_menu = next(a.menu() for a in full.menuBar().actions() if a.text() == 'Save image…')
                    action = next(a for a in image_menu.actions() if a.text() == 'Current 3D view — OpenGL PNG…')
                    destination = args.output / 'full-pymol-custom.png'
                    export_camera = tuple(widget.cmd.get_view())
                    with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(str(destination), 'PNG image (*.png)')), \
                            patch.object(QtWidgets.QMessageBox, 'warning') as warning:
                        action.trigger()
                    check('full image export reports no error', not warning.called)
                    exported = QtGui.QImage(str(destination))
                    check('full PyMOL save action produces a valid native PNG', not exported.isNull())
                    check('full export retains camera, native controls and one engine',
                          tuple(widget.cmd.get_view()) == export_camera
                          and widget.cmd.get_setting_int('internal_gui') == 1 and widget.cmd._COb is engine)
                    ray_action = next(a for a in image_menu.actions() if a.text() == 'Ray-traced 3D PNG…')
                    ray_destination = args.output / 'full-pymol-ray.png'
                    with patch.object(QtWidgets.QFileDialog, 'getSaveFileName', return_value=(str(ray_destination), 'PNG image (*.png)')), \
                            patch.object(QtWidgets.QMessageBox, 'warning') as ray_warning:
                        ray_action.trigger()
                    ray_image = QtGui.QImage(str(ray_destination))
                    check('full optional ray menu produces a valid CPU-rendered PNG',
                          not ray_warning.called and not ray_image.isNull()
                          and json.loads(ray_image.text('Docking Universal export'))['rendering'] == 'ray_traced')
                    check('full ray export retains camera, native controls and one engine',
                          tuple(widget.cmd.get_view()) == export_camera
                          and widget.cmd.get_setting_int('internal_gui') == 1 and widget.cmd._COb is engine)
                check("embedded click restrictions removed", widget._du_full_interface)
                window.open_full_pymol()
                check("repeat launch reuses shell", window._detached_structure_window is full)
                full.lineedit.setText("select user_selection, receptor")
                full.doPrompt()
                check("real command console selects atoms", widget.cmd.count_atoms("user_selection") > 0)
                full.showNormal()
                app.processEvents()
                check("maximized window can return to normal size", not full.isMaximized() and not full.isFullScreen())
                for w, h in ((720, 520), (1200, 850), (900, 650)):
                    full.resize(w, h)
                    app.processEvents()
                if iteration == 0:
                    browser = full.study_panel
                    check("study navigation dock available", full.study_dock.isVisible() and browser.regions.count() == 2)
                    check("offline lookup warning visible in main and detached interfaces",
                          window.pocket_evidence_panel.lookup_status.isVisible()
                          and browser.evidence.lookup_status.isVisible()
                          and "PDB lookup unavailable" in browser.evidence.lookup_status.text()
                          and browser.evidence.lookup_status.text() == window.pocket_evidence_panel.lookup_status.text())
                    check("lookup warning wraps without truncation in narrow study dock",
                          browser.evidence.lookup_status.height() >= browser.evidence.lookup_status.heightForWidth(
                              browser.evidence.lookup_status.width()))
                    browser.regions.setCurrentIndex(browser.regions.findData("P2"))
                    check("candidate navigation does not erase lookup warning",
                          "PDB lookup unavailable" in browser.evidence.lookup_status.text())
                    check("detached region updates live box", "du_box" in widget.cmd.get_names("objects"))
                    box_data = widget.cmd.get_session('du_box', partial=1, cache=0, compress=0)['names'][0][5][2][0][0][1]
                    check("selected box keeps all twelve edges at restrained radius", len(box_data) == 12 * 14
                          and all(abs(box_data[i+7] - .22) < .00001 for i in range(0, len(box_data), 14)))
                    changed = tuple(widget.cmd.get_view())
                    check("detached region preserves framing and only widens clipping", camera[:15] == changed[:15]
                          and camera[17] == changed[17] and changed[15] <= camera[15] and changed[16] >= camera[16])
                    camera = changed
                    browser.evidence.table.selectAll()
                    enabled = [name for name in widget.cmd.get_names("objects", enabled_only=1) if name.startswith("du_evidence_")]
                    check("detached multi-evidence loads both ligands", len(enabled) == 2)
                    browser.evidence.table.clearSelection()
                    browser.evidence.table.selectRow(1)
                    enabled = [name for name in widget.cmd.get_names("objects", enabled_only=1) if name.startswith("du_evidence_")]
                    check("detached selection hides other ligand", len(enabled) == 1)
                    check("detached evidence keeps camera", camera == tuple(widget.cmd.get_view()))
                    check("selection does not approve region", store.load("validation").selected_pocket_ids == [])
                    browser.regions.setCurrentIndex(browser.regions.findData("P1"))
                    check("compact warning has no scrollbar symbol", browser.evidence.warning.verticalScrollBarPolicy() == QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
                    browser.evidence.warning.selectAll()
                    check("warning text can be selected", "ASP30A" in browser.evidence.warning.textCursor().selectedText())
                    colors = []
                    widget.cmd.iterate("receptor", "colors.append(color)", space={"colors": colors})
                    widget.cmd.show("sticks", "receptor and chain A and resi 30 and name CA")
                    previous_sticks = widget.cmd.count_atoms("receptor and rep sticks")
                    existing_selections = widget.cmd.get_names("selections", enabled_only=1)
                    browser.highlight_obstruction_button.click()
                    selected_atoms = widget.cmd.get_model("receptor and rep sticks").atom
                    check("warning shows exactly ASP30A sticks", bool(selected_atoms) and all(
                        atom.chain == "A" and atom.resn == "ASP" and atom.resi == "30" for atom in selected_atoms))
                    check("no persistent residue atom-selection overlay", "du_obstruction" not in widget.cmd.get_names("selections"))
                    check("existing native user selections unchanged", existing_selections == widget.cmd.get_names("selections", enabled_only=1))
                    colors_after = []
                    widget.cmd.iterate("receptor", "colors.append(color)", space={"colors": colors_after})
                    check("highlight preserves camera and protein colors", camera == tuple(widget.cmd.get_view())
                          and colors == colors_after)
                    check("both interfaces show the active toggle", browser.highlight_obstruction_button.isChecked()
                          and window.pocket_evidence_panel.highlight_obstruction_button.isChecked())
                    browser.highlight_obstruction_button.click()
                    check("detached second click preserves existing user sticks", widget.cmd.count_atoms("receptor and rep sticks") == previous_sticks
                          and "du_obstruction" not in widget.cmd.get_names("selections"))
                    check("both interfaces clear the toggle", not browser.highlight_obstruction_button.isChecked()
                          and not window.pocket_evidence_panel.highlight_obstruction_button.isChecked())
                    check("detached toggle off preserves camera", camera == tuple(widget.cmd.get_view()))
                    browser.highlight_obstruction_button.click()
                    browser.evidence.guide_button.click()
                    check("walkthrough available in full PyMOL", browser.evidence._guide_window.isVisible()
                          and not browser.evidence._guide_window.isModal())
                    browser.evidence._guide_window.close()
                    full.study_dock.hide()
                    check("study dock can collapse", not full.study_dock.isVisible())
                    full.study_dock.show()
                    full.open_props_dialog()
                    app.processEvents()
                    check("native properties panel opens", full.props_panel is not None)
                    full.props_panel.close()
                    full.open_builder_panel()
                    app.processEvents()
                    check("native molecular builder opens", full.builder is not None)
                    full.builder.close()
                    full.grab().save(str(args.output / "full-pymol.png"))
                if iteration == 1:
                    widget.cmd.do("quit")
                else:
                    full.close()
                app.processEvents()
                check("close returns live viewport", window._detached_structure_window is None and widget.parentWidget() is window.pose_split)
                check("engine survives return", adapter.is_alive())
                check("embedded restrictions restored", not widget._du_full_interface and widget.cmd.get_setting_int("internal_gui") == 0)
                camera = tuple(widget.cmd.get_view())
                names = widget.cmd.get_names("objects")
            check("study scientific revision unchanged", store.load("validation").revision == revision)
            window.open_full_pymol()
            app.processEvents()
            window.close()
            app.processEvents()
            check("host shutdown closes full shell", window._detached_structure_window is None)
            adapter.close()
            check("single engine clean shutdown", not adapter.is_alive())
            result["status"] = "passed"
        except Exception as exc:
            import traceback
            result.update(status="failed", error=str(exc), traceback=traceback.format_exc())
        finally:
            if window._detached_structure_window is not None:
                window._detached_structure_window.close()
            if adapter.is_alive():
                adapter.close()
            (args.output / "verification.json").write_text(json.dumps(result, indent=2))
            app.exit(0 if result["status"] == "passed" else 1)

    QtCore.QTimer.singleShot(700, exercise)
    code = app.exec()
    temporary.cleanup()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
