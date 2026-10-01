import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.application import StudyController
from docking_universal.decisions import DecisionOption, DecisionRequired
from docking_universal.gui.desktop import QT_IMPORT_ERROR, StudyWindow
from docking_universal.models import ArtifactRecord, Job, JobStatus, PocketCandidate
from docking_universal.state import JsonStudyStore


@unittest.skipIf(QT_IMPORT_ERROR is not None, "selected Qt 6 binding is unavailable")
class DesktopWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from docking_universal.gui.qt import QtWidgets
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        from docking_universal.gui.qt import QtCore
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JsonStudyStore(self.root / "runs")
        controller = StudyController(self.store)
        controller.create_study("desktop", "Desktop study")
        controller.start_simulated_pocket_review("desktop", [
            PocketCandidate("P1", "Pocket 1", 1, "box-1", "Highest geometric rank", {"score": 0.7}),
        ])
        self.settings = QtCore.QSettings(str(self.root / "window.ini"), QtCore.QSettings.IniFormat)
        self.window = StudyWindow(self.store, "desktop", settings=self.settings)

    def tearDown(self):
        self.window.close()
        self.temporary.cleanup()

    def test_required_detail_and_decision_remain_visible(self):
        self.window.show()
        self.application.processEvents()
        self.assertEqual(self.window.detail.currentText(), "Guided")
        self.assertTrue(self.window.feedback_card.isVisibleTo(self.window))
        self.assertIn("Scientific decision required", self.window.feedback_heading.text())
        self.assertIn("review the evidence", self.window.feedback_text.text().lower())
        self.assertTrue(self.window.logs_dock.isHidden())
        self.assertTrue(self.window.reports_dock.isHidden())
        self.assertTrue(self.window.decision_banner.isVisibleTo(self.window))
        self.window.detail.setCurrentText("Concise")
        self.assertIn("DECISION REQUIRED", self.window.decision_banner.text())
        self.assertEqual(self.window.candidates.rowCount(), 1)

    def test_toolbar_diagnostic_actions_toggle_docked_nonoverlapping_panels(self):
        self.window.show()
        self.window.resize(1100, 700)
        self.application.processEvents()
        for action, dock in (
            (self.window.selections_action, self.window.selection_dock),
            (self.window.logs_action, self.window.logs_dock),
            (self.window.artifacts_action, self.window.reports_dock),
        ):
            self.assertTrue(dock.isHidden())
            action.trigger()
            self.application.processEvents()
            self.assertFalse(dock.isHidden())
            self.assertFalse(dock.isFloating())
            action.trigger()
            self.application.processEvents()
            self.assertTrue(dock.isHidden())

    def test_pose_renderer_readiness_is_always_visible_in_results_panel(self):
        self.assertTrue(self.window.poseedit_runtime_status.text())
        self.assertIn("GUI Qt 6.", self.window.runtime_status.text())
        self.assertIn("scientific host Python", self.window.runtime_status.text())
        if self.window.poseedit_runtime["status"] == "available":
            self.assertIn("ready", self.window.poseedit_runtime_status.text().lower())
        else:
            for component in self.window.poseedit_runtime["missing"]:
                self.assertIn(component, self.window.poseedit_runtime_status.text())

    def test_decision_figure_names_select_only_useful_report_composites(self):
        self.assertEqual(
            self.window._decision_figure_label(Path("cavity_panels_AB.png")),
            "Pocket ranking and structural evidence",
        )
        self.assertEqual(
            self.window._decision_figure_label(Path("5362440_selected_interactions_ABC.png")),
            "Top-pose interaction diagrams",
        )
        self.assertEqual(
            self.window._decision_figure_label(Path("cavity_panel_A_selection.png")),
            "Pocket scores and ranking — Panel A",
        )
        pocket_explanation = self.window._decision_figure_explanation(
            "Pocket scores and ranking — Panel A"
        )
        self.assertIn("higher values", pocket_explanation)
        self.assertIn("not binding affinities", pocket_explanation)
        docking_explanation = self.window._decision_figure_explanation(
            "Docking scores and cluster distribution"
        )
        self.assertIn("More negative", docking_explanation)
        self.assertIn("not measured affinity", docking_explanation)
        composite_explanation = self.window._decision_figure_explanation(
            "Top-pose interaction diagrams"
        )
        self.assertIn("Panel A:", composite_explanation)
        self.assertIn("Panel B:", composite_explanation)
        self.assertIn("Panel C:", composite_explanation)
        pocket_composite = self.window._decision_figure_explanation(
            "Pocket ranking and structural evidence"
        )
        self.assertIn("Panel A:", pocket_composite)
        self.assertIn("Panel B:", pocket_composite)
        ligand_composite = self.window._decision_figure_explanation(
            "Deposited-ligand site evidence"
        )
        self.assertIn("Panel A:", ligand_composite)
        self.assertIn("Panel B:", ligand_composite)
        panel_cards = self.window._decision_figure_explanation_sections(
            "Top-pose interaction diagrams"
        )
        self.assertEqual(
            [heading for heading, _body in panel_cards],
            ["Panel A", "Panel B", "Panel C", "Key"],
        )

    def test_only_3d_figures_offer_their_matching_pymol_scene(self):
        report = self.root / "report"
        report.mkdir()
        figure = report / "pocket_evidence_site_1_AB.png"
        scene = report / "pocket_evidence_site_1_AB.pse"
        figure.write_bytes(b"figure")
        scene.write_bytes(b"scene")
        self.assertEqual(self.window._scene_for_decision_figure(figure), scene.resolve())

        two_d = report / "compound_selected_interactions_ABC.png"
        two_d.write_bytes(b"figure")
        self.assertIsNone(self.window._scene_for_decision_figure(two_d))

        top_three = report / "compound_top3_3d_snapshots.png"
        top_three.write_bytes(b"figure")
        sources = []
        for letter in "ABC":
            source = report / f"pose_{letter}.png"
            source.write_bytes(b"image")
            source.with_suffix(".pse").write_bytes(b"scene")
            sources.append(str(source))
        top_three.with_suffix(".manifest.json").write_text(json.dumps({"sources": sources}))
        scenes = self.window._scenes_for_decision_figure(top_three)
        self.assertEqual([label for label, _path in scenes], ["Panel A", "Panel B", "Panel C"])

        interaction_manifest = report / "compound_top3_3d_snapshots.manifest.json"
        interaction_manifest.write_text(json.dumps({"sources": sources}))
        interaction_scenes = self.window._scenes_for_decision_figure(two_d)
        self.assertEqual(
            interaction_scenes,
            [("Panel A", Path(sources[0]).with_suffix(".pse").resolve()),
             ("Panel B", Path(sources[1]).with_suffix(".pse").resolve()),
             ("Panel C", Path(sources[2]).with_suffix(".pse").resolve())],
        )

    def test_duplicate_report_figure_names_are_presented_once(self):
        for directory in (self.root / "protocol", self.root / "screening"):
            directory.mkdir()
            (directory / "cavity_panel_A_selection.png").write_bytes(b"retained")
        self.store.update(
            "desktop",
            lambda state: state.artifacts.extend([
                ArtifactRecord(
                    "protocol-pocket", "final_report_figure",
                    str(self.root / "protocol" / "cavity_panel_A_selection.png"),
                ),
                ArtifactRecord(
                    "screening-pocket", "screening_report_figure",
                    str(self.root / "screening" / "cavity_panel_A_selection.png"),
                ),
            ]),
        )
        self.window.refresh()
        labels = [
            self.window.decision_figure_choice.itemText(index)
            for index in range(self.window.decision_figure_choice.count())
        ]
        self.assertEqual(labels.count("Pocket scores and ranking — Panel A"), 1)

    def test_decision_figures_reclaim_live_pymol_control_space(self):
        self.window.review_tabs.setCurrentIndex(0)
        self.assertTrue(self.window.pymol_controls.isHidden())
        self.assertLessEqual(self.window.candidates.maximumHeight(), 125)

    def test_candidate_review_opens_retained_structure_without_report_figure(self):
        class Viewer:
            backend_kind = "embedded"
            backend_name = "Embedded PyMOL"
            connected = False
            report_view_available = False
            status = "disconnected"

            def open(self, state):
                self.connected = True
                self.opened_study = state.study_id

            def show_candidate(self, state, candidate_id):
                self.candidate_id = candidate_id

        viewer = Viewer()
        self.window.viewer_coordinator = viewer
        self.window._update_candidate_review_action()
        self.assertTrue(self.window.candidate_review_button.isEnabled())
        self.window.open_selected_candidate_review()
        self.assertEqual(viewer.opened_study, "desktop")
        self.assertEqual(viewer.candidate_id, "P1")
        self.assertIn("reviewing P1", self.window.viewer_status.text())

    def test_embedded_viewer_gets_a_real_central_tab_and_controls(self):
        from docking_universal.gui.qt import QtWidgets

        class Viewer:
            backend_name = "Embedded PyMOL"
            connected = False
            report_view_available = False
            status = "disconnected"
            last_error = None

            def refresh_health(self):
                return False

        widget = QtWidgets.QFrame()
        widget.setObjectName("real_embedded_viewport")
        window = StudyWindow(
            self.store, "desktop", settings=self.settings,
            viewer_coordinator=Viewer(), viewer_widget=widget,
        )
        try:
            self.assertEqual(window.review_tabs.count(), 2)
            self.assertEqual(window.review_tabs.tabText(1), "Interactive structure")
            self.assertIs(widget.parentWidget(), window.pose_split)
            window.review_tabs.setCurrentIndex(1)
            self.application.processEvents()
            self.assertTrue(window.pymol_controls.isVisibleTo(window))
            self.assertFalse(window.workspace_context.isVisibleTo(window))
            self.assertFalse(window.central_selection_status.isVisibleTo(window))
            self.assertFalse(window.viewer_status.isVisibleTo(window))
            self.assertEqual(window.candidates.maximumHeight(), 82)
            self.assertTrue(window.viewer_button.isHidden())
            self.assertTrue(window.detach_viewer_button.isVisibleTo(window))
            self.assertTrue(window.open_pose_session_button.isHidden())
            self.assertEqual(
                window.sync_pose_button.text(),
                "Show selected pose in interactive structure",
            )
            self.assertEqual(
                window.pocket_evidence_panel.compare_button.text(),
                "Show selected observations in interactive structure",
            )
            self.assertIn("interactive structure view", window.pocket_evidence_panel.note.text())
            visible_pymol_buttons = [
                button.text()
                for button in window.findChildren(QtWidgets.QPushButton)
                if button.isVisibleTo(window) and "PyMOL" in button.text()
            ]
            self.assertEqual(visible_pymol_buttons, [])
            self.assertNotIn("separate window", window.structural_view.text())
            self.assertIn("Embedded PyMOL configured", window.runtime_status.text())

            window.detach_embedded_viewer()
            self.application.processEvents()
            detached = window._detached_structure_window
            self.assertIsNotNone(detached)
            self.assertTrue(detached.isFullScreen())
            self.assertIs(widget.window(), detached)
            detached.close()
            self.application.processEvents()
            self.assertIsNone(window._detached_structure_window)
            self.assertIs(widget.parentWidget(), window.pose_split)
        finally:
            window.close()

    def test_widget_without_viewer_backend_is_rejected(self):
        from docking_universal.gui.qt import QtWidgets

        with self.assertRaisesRegex(ValueError, "requires a viewer coordinator"):
            StudyWindow(
                self.store, "desktop", settings=self.settings,
                viewer_widget=QtWidgets.QFrame(),
            )

    def test_embedded_evidence_selection_never_lowers_the_gui(self):
        class Adapter:
            backend_kind = "embedded"

        class Viewer:
            backend_kind = "embedded"
            backend_name = "Embedded PyMOL"
            connected = True
            adapter = Adapter()

            def sync_evidence_ligands(self, paths):
                self.paths = paths

        viewer = Viewer()
        self.window.viewer_coordinator = viewer
        self.window.viewer_widget = object()
        with patch.object(self.window, "_send_windows_back") as lowered:
            self.window.sync_evidence_selection(["one.pdb", "two.pdb"])
        lowered.assert_not_called()
        self.assertEqual(viewer.paths, ["one.pdb", "two.pdb"])
        self.assertIn("Embedded PyMOL synchronized", self.window.viewer_status.text())

    def test_embedded_scene_dropdown_loads_scene_without_leaving_structure_tab(self):
        from docking_universal.gui.qt import QtWidgets

        report = self.root / "report"
        report.mkdir()
        first_figure = report / "cavity_panels_AB.png"
        first_scene = report / "cavity_panel_B_structure.pse"
        second_figure = report / "cavity_selected_box.png"
        second_scene = report / "cavity_selected_box.pse"
        two_d_figure = report / "compound_selected_interactions_ABC.png"
        for path in (first_figure, first_scene, second_figure, second_scene, two_d_figure):
            path.write_bytes(b"retained")
        state = self.store.load("desktop")
        state.artifacts.extend([
            ArtifactRecord("fig-1", "final_report_figure", str(first_figure)),
            ArtifactRecord("fig-2", "final_report_figure", str(second_figure)),
            ArtifactRecord("fig-3", "final_report_figure", str(two_d_figure)),
        ])
        self.store.save(state)

        class Viewer:
            backend_kind = "embedded"
            backend_name = "Embedded PyMOL"
            connected = True
            report_view_available = True
            report_view_name = "initial"
            status = "connected"
            last_error = None

            def refresh_health(self):
                return True

            def open_scene(self, path):
                self.opened = Path(path)
                self.report_view_name = self.opened.stem

        viewer = Viewer()
        widget = QtWidgets.QFrame()
        window = StudyWindow(
            self.store, "desktop", settings=self.settings,
            viewer_coordinator=viewer, viewer_widget=widget,
        )
        try:
            self.assertEqual(window.scene_figure_choice.count(), 2)
            window.review_tabs.setCurrentIndex(1)
            report_selection = window.decision_figure_choice.currentData()
            window.scene_figure_choice.setCurrentIndex(1)
            self.application.processEvents()
            self.assertEqual(viewer.opened, second_scene.resolve())
            self.assertEqual(window.review_tabs.currentIndex(), 1)
            self.assertEqual(window.decision_figure_choice.currentData(), report_selection)
        finally:
            window.close()

    def test_decision_figure_supports_native_zoom_and_full_screen(self):
        from docking_universal.gui.qt import QtGui, QtWidgets

        self.window.decision_figure_choice.addItem(
            "Top-pose interaction diagrams", "not-used-by-this-viewer-test"
        )
        self.window._decision_figure_pixmap = QtGui.QPixmap(1600, 1200)
        self.window._set_decision_figure_zoom(1.0)
        self.assertEqual(self.window.figure_zoom_status.text(), "100%")
        self.assertEqual(self.window.decision_figure_view.pixmap().width(), 1600)
        self.window._change_decision_figure_zoom(1.25)
        self.assertEqual(self.window.figure_zoom_status.text(), "125%")

        self.window._show_figure_full_screen()
        self.application.processEvents()
        self.assertTrue(self.window._figure_full_screen_dialog.isFullScreen())
        cards = self.window._figure_full_screen_guidance.findChildren(
            QtWidgets.QFrame, "full_screen_figure_explanation_card"
        )
        self.assertEqual(len(cards), 4)
        self.window._figure_full_screen_dialog.close()

    def test_scientific_host_failure_is_visible_and_reconnectable(self):
        class Host:
            connected = False
            runtime = {}

            def __init__(self):
                self.restarts = 0

            def restart(self):
                self.restarts += 1
                self.connected = True
                self.runtime = {
                    "python_version": "3.9.23",
                    "conda_environment": "docking-universal",
                }

        host = Host()
        self.window.host_client = host
        self.window.refresh()
        self.assertTrue(self.window.reconnect_services_button.isVisibleTo(self.window))
        self.assertIn("SCIENTIFIC HOST DISCONNECTED", self.window.runtime_status.text())
        self.assertFalse(self.window.host_controller.available)

        self.window.reconnect_scientific_host()
        self.assertEqual(host.restarts, 1)
        self.assertTrue(self.window.host_controller.available)
        self.assertFalse(self.window.reconnect_services_button.isVisibleTo(self.window))
        self.assertIn("docking-universal", self.window.runtime_status.text())

    def test_panels_are_floatable_and_fullscreen_is_reversible(self):
        from docking_universal.gui.qt import QtWidgets
        docks = self.window.findChildren(QtWidgets.QDockWidget)
        self.assertGreaterEqual(len(docks), 5)
        self.assertIsNotNone(self.window.findChild(QtWidgets.QDockWidget, "pocket_evidence_dock"))
        self.assertIsNotNone(self.window.findChild(QtWidgets.QDockWidget, "study_setup_dock"))
        self.assertTrue(all(dock.features() & QtWidgets.QDockWidget.DockWidgetFloatable for dock in docks))
        self.window.showFullScreen()
        self.application.processEvents()
        self.assertTrue(self.window.isFullScreen())
        self.window.toggle_full_screen()
        self.application.processEvents()
        self.assertFalse(self.window.isFullScreen())

    def test_study_menu_exposes_new_and_open_actions(self):
        self.assertEqual(self.window.current_study_action.text(), "Current: desktop")
        self.assertEqual(self.window.new_study_action.text(), "New study…")
        self.assertEqual(self.window.open_study_action.text(), "Open study…")

    def test_retained_setup_replaces_draft_values_and_is_read_only(self):
        receptor = self.root / "retained.pdb"
        receptor.write_text("ATOM\n")
        state = self.store.load("desktop")
        state.workflow_data["study_setup"] = {
            "input_pdb": str(receptor.resolve()),
            "working_directory": str((self.root / "retained-output").resolve()),
            "site_mode": "ligand",
            "ligand_resname": "LIG",
            "ligand_chain_id": "B",
            "ligand_residue_number": "201",
            "ligand_insertion_code": "A",
            "ligand_altloc": "B",
            "pocket_engine": "p2rank",
            "pdb_pocket_evidence": "related-structures",
        }
        self.store.save(state)
        self.window.refresh()
        self.assertEqual(self.window.input_pdb.text(), str(receptor.resolve()))
        self.assertEqual(self.window.study_setup_panel.ligand_value(), "LIG")
        self.assertEqual(
            self.window.study_setup_panel.ligand_identity()["chain_id"], "B"
        )
        self.assertFalse(self.window.input_pdb.isEnabled())
        self.assertFalse(self.window.output_directory.isEnabled())
        self.assertFalse(self.window.start_preparation_button.isEnabled())

    def test_older_completed_study_recovers_setup_from_retained_artifacts(self):
        receptor = self.root / "legacy-source.pdb"
        receptor.write_text("ATOM\n")
        preparation_root = self.root / "legacy-work" / "legacy_receptor_prep"
        state = self.store.load("desktop")
        state.jobs.insert(0, Job(
            id="legacy-preparation", stage="preparation_and_pocket_detection",
            status=JobStatus.COMPLETED,
        ))
        state.artifacts.append(ArtifactRecord(
            "legacy-source", "source_receptor_structure", str(receptor.resolve())
        ))
        state.workflow_data["preparation_root"] = str(preparation_root.resolve())
        state.workflow_data.pop("study_setup", None)
        self.store.save(state)
        self.window.refresh()
        self.assertEqual(self.window.input_pdb.text(), str(receptor.resolve()))
        self.assertEqual(
            self.window.output_directory.text(), str(preparation_root.parent.resolve())
        )
        self.assertIn("predates the setup record", self.window.study_setup_panel.lock_notice.text())
        self.assertFalse(self.window.input_pdb.isEnabled())

    def test_workspace_shell_has_persistent_navigation_and_structural_center(self):
        from docking_universal.gui.qt import QtWidgets
        self.assertGreaterEqual(self.window.minimumWidth(), 1100)
        self.assertGreaterEqual(self.window.minimumHeight(), 700)
        self.assertEqual(self.window.workspace_heading.text(), "Structural Review")
        self.assertEqual(self.window.structural_view.objectName(), "central_structural_review")
        self.assertEqual(self.window.workflow_navigation.count(), 6)
        self.assertFalse(
            self.window.workflow_navigation_dock.features()
            & QtWidgets.QDockWidget.DockWidgetClosable
        )

        initial_window_size = self.window.size()
        initial_center_width = self.window.centralWidget().width()

        self.window.workflow_navigation.setCurrentRow(0)
        self.assertIs(
            self.window.workflow_stage_stack.currentWidget(),
            self.window.study_setup_panel,
        )
        self.window.workflow_navigation.setCurrentRow(1)
        self.assertIs(
            self.window.workflow_stage_stack.currentWidget(),
            self.window.preparation_progress_panel,
        )
        self.assertIsNot(
            self.window.preparation_progress_panel,
            self.window.study_setup_panel,
        )

        self.window.workflow_navigation.setCurrentRow(3)
        self.application.processEvents()
        self.assertEqual(self.window.study_setup_dock.windowTitle(), "Finalize Protocol")
        self.assertTrue(self.window.study_setup_dock.isVisibleTo(self.window))
        self.assertTrue(self.window.protocol_finalization_dock.isHidden())
        self.assertIs(
            self.window.workflow_stage_stack.currentWidget(),
            self.window.protocol_finalization_panel,
        )
        self.assertIs(
            self.window.right_review_stack.currentWidget(),
            self.window.right_review_blank,
        )
        self.assertFalse(self.window.pocket_evidence_dock.isHidden())
        self.assertTrue(self.window.screening_results_dock.isHidden())
        self.assertEqual(self.window.size(), initial_window_size)
        self.assertEqual(self.window.centralWidget().width(), initial_center_width)

        self.window.workflow_navigation.setCurrentRow(4)
        self.application.processEvents()
        self.assertEqual(self.window.study_setup_dock.windowTitle(), "Screen Ligands")
        self.assertEqual(self.window.size(), initial_window_size)
        self.assertEqual(self.window.centralWidget().width(), initial_center_width)
        self.assertIs(
            self.window.workflow_stage_stack.currentWidget(),
            self.window.screening_setup_panel,
        )
        self.assertTrue(self.window.screening_dock.isHidden())

        self.window.workflow_navigation.setCurrentRow(2)
        self.application.processEvents()
        self.assertEqual(self.window.study_setup_dock.windowTitle(), "Review and Decide")
        self.assertEqual(self.window.size(), initial_window_size)
        self.assertEqual(self.window.centralWidget().width(), initial_center_width)
        self.assertTrue(self.window.study_setup_dock.isVisibleTo(self.window))
        self.assertFalse(self.window.protocol_finalization_dock.isVisibleTo(self.window))
        self.assertFalse(self.window.screening_dock.isVisibleTo(self.window))
        self.assertIs(
            self.window.workflow_stage_stack.currentWidget(),
            self.window.workflow_stage_blank,
        )
        self.assertIs(
            self.window.right_review_stack.currentWidget(),
            self.window.pocket_evidence_panel,
        )
        self.assertFalse(self.window.pocket_evidence_dock.isHidden())
        self.assertTrue(self.window.screening_results_dock.isHidden())

        self.window.workflow_navigation.setCurrentRow(5)
        self.application.processEvents()
        self.assertEqual(self.window.study_setup_dock.windowTitle(), "Results Review")
        self.assertFalse(self.window.pocket_evidence_dock.isHidden())
        self.assertTrue(self.window.screening_results_dock.isHidden())
        self.assertIs(
            self.window.right_review_stack.currentWidget(),
            self.window.results_review_panel,
        )

    def test_rapid_stage_switching_does_not_reflow_or_stall_the_workspace(self):
        initial_window_size = self.window.size()
        initial_center_geometry = self.window.centralWidget().geometry()

        for _cycle in range(25):
            for row in (0, 3, 4, 2, 5, 1):
                self.window.workflow_navigation.setCurrentRow(row)
                self.application.processEvents()
                self.assertEqual(self.window.size(), initial_window_size)
                self.assertEqual(
                    self.window.centralWidget().geometry(), initial_center_geometry,
                )

        self.assertEqual(self.window.workflow_navigation.currentRow(), 1)

    def test_canvas_focus_mode_reclaims_side_panel_space_and_is_reversible(self):
        self.window.focus_canvas_action.setChecked(True)
        self.application.processEvents()
        self.assertTrue(self.window.workflow_navigation_dock.isHidden())
        self.assertTrue(self.window.study_setup_dock.isHidden())
        self.assertTrue(self.window.pocket_evidence_dock.isHidden())
        self.assertEqual(self.window.focus_canvas_action.text(), "Show workflow panels")

        self.window.focus_canvas_action.setChecked(False)
        self.application.processEvents()
        self.assertFalse(self.window.workflow_navigation_dock.isHidden())
        self.assertFalse(self.window.study_setup_dock.isHidden())
        self.assertFalse(self.window.pocket_evidence_dock.isHidden())
        self.assertEqual(self.window.focus_canvas_action.text(), "Focus canvas")

    def test_workflow_navigation_exposes_next_scientific_action(self):
        from docking_universal.gui.qt import QtCore

        self.assertIn("Scientific decision required", self.window.next_required_action.text())
        self.assertTrue(self.window.workflow_navigation.item(2).text().startswith("●"))
        self.assertTrue(self.window.workflow_navigation.item(1).text().startswith("✓"))
        self.assertFalse(
            self.window.workflow_navigation.item(3).flags()
            & QtCore.Qt.ItemFlag.ItemIsEnabled
        )
        self.assertIn("waiting for your decision", self.window.active_stage_status.text())
        self.assertTrue(self.window.active_stage_progress.isHidden())

        # A refresh within the same scientific phase must not pull the user
        # away from an earlier retained stage they chose to inspect.
        self.window.workflow_navigation.setCurrentRow(1)
        self.window.refresh()
        self.assertEqual(self.window.workflow_navigation.currentRow(), 1)

        self.window.logs_dock.hide()
        self.window.show_complete_logs_button.click()
        self.assertFalse(self.window.logs_dock.isHidden())

        state = self.store.load("desktop")
        decision = state.pending_decisions[0]
        StudyController(self.store).resolve_decision(
            "desktop", decision.id, ("P1",), actor="test user",
            rationale="Selected after reviewing the retained evidence.",
            expected_revision=state.revision,
        )
        self.window.refresh()
        self.assertIn("finalize the report", self.window.next_required_action.text())
        self.assertTrue(self.window.workflow_navigation.item(2).text().startswith("✓"))
        self.assertTrue(self.window.workflow_navigation.item(3).text().startswith("●"))
        self.assertTrue(
            self.window.workflow_navigation.item(3).flags()
            & QtCore.Qt.ItemFlag.ItemIsEnabled
        )
        self.assertEqual(self.window.workflow_navigation.currentRow(), 3)

        bundle = self.root / "desktop.duprotocol"
        bundle.write_text("test bundle")
        self.store.update(
            "desktop",
            lambda updated: updated.artifacts.append(
                ArtifactRecord("bundle", "protocol_bundle", str(bundle))
            ),
        )
        self.window.refresh()
        self.assertIn("Protocol finalized", self.window.next_required_action.text())
        self.assertTrue(self.window.workflow_navigation.item(3).text().startswith("✓"))
        self.assertTrue(self.window.workflow_navigation.item(4).text().startswith("●"))
        self.assertTrue(
            self.window.workflow_navigation.item(4).flags()
            & QtCore.Qt.ItemFlag.ItemIsEnabled
        )

    def test_results_review_explicitly_detaches_and_redocks_without_state_change(self):
        before = self.store.path_for("desktop").read_bytes()
        dock = self.window.screening_results_dock
        self.assertEqual(dock.windowTitle(), "Results Review")
        self.assertFalse(dock.isFloating())

        self.window.detach_results_review()
        self.application.processEvents()

        self.assertTrue(dock.isFloating())
        self.assertEqual(dock.windowTitle(), "Docking Universal — Results Review")
        self.assertEqual(self.window.results_window_button.text(), "Return to workspace")
        self.assertEqual(self.store.path_for("desktop").read_bytes(), before)

        self.window.redock_results_review()
        self.application.processEvents()

        self.assertFalse(dock.isFloating())
        self.assertEqual(self.window.results_window_button.text(), "Detach review")
        self.assertEqual(self.store.path_for("desktop").read_bytes(), before)

    def test_draft_forms_restore_but_scientific_approvals_do_not(self):
        receptor = self.root / "draft receptor.pdb"
        receptor.write_text("ATOM\n")
        self.window.input_pdb.setText(str(receptor))
        self.window.output_directory.setText(str(self.root / "preparation"))
        self.window.pocket_engine.setCurrentIndex(
            self.window.pocket_engine.findData("fpocket")
        )
        self.window.final_output_directory.setText(str(self.root / "protocol"))
        self.window.protocol_ph.setValue(6.8)
        self.window.protocol_seeds.setValue(7)
        self.window.screen_ligands.setText(str(self.root / "ligands.sdf"))
        self.window.screen_output.setText(str(self.root / "screen"))
        self.window.screen_stop_on_error.setChecked(True)
        self.window.exploratory_approval.setChecked(True)
        self.window.screen_exploratory_approval.setChecked(True)
        self.window._screening_plan = {"compound_count": 99}
        self.window.close()

        self.window = StudyWindow(self.store, "desktop", settings=self.settings)
        self.assertEqual(self.window.input_pdb.text(), str(receptor))
        self.assertEqual(self.window.output_directory.text(), str(self.root / "preparation"))
        self.assertEqual(self.window.pocket_engine.currentData(), "fpocket")
        self.assertEqual(self.window.final_output_directory.text(), str(self.root / "protocol"))
        self.assertEqual(self.window.protocol_ph.value(), 6.8)
        self.assertEqual(self.window.protocol_seeds.value(), 7)
        self.assertEqual(self.window.screen_ligands.text(), str(self.root / "ligands.sdf"))
        self.assertEqual(self.window.screen_output.text(), str(self.root / "screen"))
        self.assertTrue(self.window.screen_stop_on_error.isChecked())
        self.assertFalse(self.window.exploratory_approval.isChecked())
        self.assertFalse(self.window.screen_exploratory_approval.isChecked())
        self.assertIsNone(self.window._screening_plan)

    def test_results_review_shows_the_shared_nonapproval_selection(self):
        compound = self.root / "screen/compounds/ligand_a"
        analysis = compound / "pose_analysis"
        self.window.session.select_pose(
            compound, analysis, 3, 6, site="primary site",
        )
        self.application.processEvents()

        status = self.window.results_session_status.text()
        self.assertIn("ligand_a", status)
        self.assertIn("primary site", status)
        self.assertIn("cluster 3", status)
        self.assertIn("pose 6", status)
        self.assertIn("ligand_a", self.window.central_selection_status.text())
        self.assertIn("pose 6", self.window.central_selection_status.text())
        self.assertEqual(self.store.load("desktop").approvals, [])

    def test_candidate_table_summarizes_nested_evidence_without_dumping_json(self):
        from docking_universal.gui.qt import QtWidgets

        state = self.store.load("desktop")
        state.workflow_data["pocket_candidates"] = [{
            "id": "P1", "label": "P1", "rank": 1,
            "summary": "individual p2rank pocket box",
            "evidence": {
                "automation_eligible": True,
                "detector": "p2rank",
                "conformational_site_evidence": {
                    "status": "conformationally_incompatible",
                    "occluding_residues": [{"name": "ASP", "number": 30, "chain": "A"}],
                },
                "experimental_ligand_evidence": {
                    "observation_count": 17,
                    "pdb_entry_count": 15,
                    "evidence_class_counts": {
                        "exact_sequence_match": 4,
                        "close_structural_homolog": 13,
                    },
                    "observations": [{
                        "aligned_ligand_pdb": "/private/path/that/must/not/appear.pdb",
                        "entry": "2R5P", "ligand": "MK1",
                    }],
                },
            },
        }]
        self.store.save(state)
        self.window.refresh()

        displayed = self.window.candidates.item(0, 3).text()
        self.assertEqual(
            displayed,
            "Rotamer conflict: ASP30A · 17 ligand observations / 15 PDBs "
            "(4 exact; 13 homolog)",
        )
        self.assertNotIn("automation_eligible", displayed)
        self.assertNotIn("observations", displayed.replace("ligand observations", ""))
        self.assertNotIn("/private/path", displayed)

        evidence_item = self.window.candidates.item(0, 3)
        self.window._show_candidate_evidence_details(evidence_item)
        self.application.processEvents()
        self.assertEqual(len(self.window._candidate_evidence_dialogs), 1)
        dialog = self.window._candidate_evidence_dialogs[0]
        self.assertTrue(dialog.isVisible())
        complete_text = dialog.findChild(QtWidgets.QPlainTextEdit).toPlainText()
        self.assertIn("aligned_ligand_pdb", complete_text)
        self.assertIn("/private/path/that/must/not/appear.pdb", complete_text)
        dialog.close()

    def test_pymol_failure_becomes_reconnectable_shared_state(self):
        class Viewer:
            connected = False
            report_view_available = False
            status = "disconnected"
            last_error = None

            def __init__(self):
                self.reconnects = 0
                self.opens = 0

            def open_scene(self, _scene):
                self.opens += 1
                if self.opens == 1:
                    self.status = "failed"
                    self.last_error = "viewer exited"
                    raise RuntimeError("viewer exited")
                self.connected = True
                self.report_view_available = True
                self.status = "connected"
                self.report_view_name = "selected_figure"

            def reconnect(self, _state):
                self.reconnects += 1
                self.connected = True
                self.status = "connected"

        viewer = Viewer()
        self.window.viewer_coordinator = viewer
        scene = self.root / "selected_figure.pse"
        scene.write_bytes(b"scene")
        self.window._selected_figure_scene = scene
        with patch("docking_universal.gui.qt.QtWidgets.QMessageBox.critical"):
            self.window.open_visual_review()
        self.assertEqual(self.window.session.viewer.lifecycle, "failed")
        self.assertEqual(self.window.viewer_button.text(), "Reconnect PyMOL")

        self.window.open_visual_review()
        self.assertEqual(viewer.reconnects, 1)
        self.assertEqual(self.window.session.viewer.lifecycle, "connected")
        self.assertTrue(self.window.session.viewer.connected)

    def test_refresh_and_layout_do_not_rewrite_scientific_state(self):
        before = self.store.path_for("desktop").read_bytes()
        self.window.refresh()
        self.window.close()
        after = self.store.path_for("desktop").read_bytes()
        self.assertEqual(after, before)

    def test_artifact_rows_retain_the_exact_openable_path(self):
        state = self.store.load("desktop")
        path = self.root / "scientific-record.json"
        path.write_text("{}\n")
        artifact = ArtifactRecord("record", "scientific_record", str(path))
        state.artifacts.append(artifact)
        self.store.save(state)
        self.window.refresh()
        matching = [
            self.window.report_list.item(index)
            for index in range(self.window.report_list.count())
            if artifact.path in self.window.report_list.item(index).text()
        ]
        self.assertEqual(len(matching), 1)
        from docking_universal.gui.qt import QtCore
        self.assertEqual(matching[0].data(QtCore.Qt.UserRole), artifact.path)

    def test_decision_synopsis_and_complete_report_are_both_available(self):
        from docking_universal.gui.qt import QtGui
        report = self.root / "preliminary-pocket-review.pdf"
        report.write_bytes(b"%PDF-1.4\n%%EOF\n")
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "pocket-review-report", "preliminary_report", str(report),
            description="Complete pocket-review synopsis",
        ))
        self.store.save(state)
        self.window.refresh()
        self.assertTrue(self.window.decision_synopsis_button.isEnabled())
        self.assertTrue(self.window.full_synopsis_button.isEnabled())
        with patch.object(QtGui.QDesktopServices, "openUrl", return_value=True) as opened:
            self.window.show_full_synopsis_report()
        self.assertEqual(opened.call_args.args[0].toLocalFile(), str(report.resolve()))

    def test_preparation_intervention_is_presented_as_its_own_required_action(self):
        state = self.store.load("desktop")
        state.decisions = [DecisionRequired(
            id="histidine-review", kind="select_histidine_template",
            prompt="Choose the justified histidine state for A:57",
            detected="Meeko could not distinguish the deposited state.",
            why_stopped="The choice changes the receptor model.",
            consequences=("The selected template will be retained.",),
            options=(DecisionOption("HIE_CURRENT", "HIE", "Proton on NE2"),),
            changes_molecular_model=True,
            continuation={
                "action": "continue_stage",
                "checkpoint": "rerun_preparation_with_histidine_template",
            },
        )]
        state.jobs[0].stage = "preparation_and_pocket_detection"
        state.jobs[0].status = JobStatus.WAITING_FOR_DECISION
        self.store.save(state)

        self.window.refresh()

        self.assertEqual(
            self.window.decision_synopsis_button.text(), "Review preparation decision…",
        )
        self.assertFalse(self.window.approve_button.isEnabled())
        self.assertIn(
            "required molecular-model decision",
            self.window.preparation_progress_panel.status.text(),
        )

    def test_table_selection_is_only_a_proposal_until_approval_button(self):
        class FakeHost:
            def __init__(self, store):
                self.store = store
                self.calls = []

            def request(self, study_id, operation, payload, *, expected_revision):
                self.calls.append((study_id, operation, payload, expected_revision))
                controller = StudyController(self.store)
                controller.resolve_decision(
                    study_id, payload["decision_id"], tuple(payload["selections"]),
                    actor=payload["actor"], rationale=payload["rationale"],
                    expected_revision=expected_revision,
                )
                return {"status": "applied"}

        host = FakeHost(self.store)
        self.window.host_client = host
        self.window.refresh()
        self.window.candidates.selectRow(0)
        self.assertEqual(self.store.load("desktop").approvals, [])
        self.window.rationale.setText("Reviewed in required structure view")
        self.window.approve_button.click()
        self.assertEqual(len(host.calls), 1)
        state = self.store.load("desktop")
        self.assertEqual(state.selected_pocket_ids, ["P1"])
        self.assertEqual(state.approvals[0].rationale, "Reviewed in required structure view")

    def test_completed_preparation_cannot_be_restarted_from_setup_panel(self):
        state = self.store.load("desktop")
        state.jobs[0].stage = "preparation_and_pocket_detection"
        state.jobs[0].status = JobStatus.COMPLETED
        state.decisions.clear()
        self.store.save(state)
        self.window.host_client = object()
        self.window.refresh()
        self.assertFalse(self.window.start_preparation_button.isEnabled())

    def test_setup_panel_submits_only_explicit_noninteractive_options(self):
        class FakeHost:
            def __init__(self):
                self.calls = []

            def request(self, study_id, operation, payload, *, expected_revision):
                self.calls.append((study_id, operation, payload, expected_revision))
                return {"status": "applied"}

        controller = StudyController(self.store)
        controller.create_study("setup", "Setup study")
        receptor = self.root / "input receptor.pdb"
        receptor.write_text("ATOM\n")
        host = FakeHost()
        from docking_universal.gui.qt import QtCore
        settings = QtCore.QSettings(str(self.root / "setup.ini"), QtCore.QSettings.IniFormat)
        window = StudyWindow(self.store, "setup", settings=settings, host_client=host)
        try:
            window.input_pdb.setText(str(receptor))
            window.output_directory.setText(str(self.root / "output directory"))
            window.detail.setCurrentText("Teaching")
            window.start_preparation()
            self.assertEqual(len(host.calls), 1)
            study_id, operation, payload, revision = host.calls[0]
            self.assertEqual((study_id, operation), ("setup", "start_receptor_preparation"))
            self.assertEqual(payload["site_mode"], "pockets")
            self.assertEqual(payload["feedback_level"], "verbose")
            self.assertIsNone(payload["meeko_template_file"])
            self.assertEqual(revision, self.store.load("setup").revision)
            self.assertNotIn("command", payload)
        finally:
            window.close()

    def test_finalization_requires_approval_and_submits_locked_gui_settings(self):
        class FakeHost:
            def __init__(self):
                self.calls = []

            def request(self, study_id, operation, payload, *, expected_revision):
                self.calls.append((study_id, operation, payload, expected_revision))
                return {"status": "applied"}

        controller = StudyController(self.store)
        state = self.store.load("desktop")
        decision = state.pending_decisions[0]
        controller.resolve_decision("desktop", decision.id, ("P1",), actor="scientist")
        state = self.store.load("desktop")
        state.workflow_data["preparation_root"] = str(self.root / "Target_receptor_prep")
        self.store.save(state)
        host = FakeHost()
        self.window.host_client = host
        self.window.refresh()
        self.assertFalse(self.window.finalize_button.isEnabled())
        self.window.exploratory_approval.setChecked(True)
        self.assertTrue(self.window.finalize_button.isEnabled())
        self.window.protocol_engine.setCurrentIndex(1)
        self.window.protocol_ph.setValue(6.8)
        self.window.protocol_conformers.setValue(7)
        self.window.protocol_seeds.setValue(4)
        self.window.protocol_base_seed.setValue(99001)
        self.window.protocol_exhaustiveness.setValue(32)
        self.window.finalize_button.click()
        self.assertEqual(len(host.calls), 1)
        study_id, operation, payload, revision = host.calls[0]
        self.assertEqual((study_id, operation), ("desktop", "start_protocol_finalization"))
        self.assertTrue(payload["exploratory_use_approved"])
        self.assertEqual(payload["engine"], "qvinaw")
        self.assertEqual(payload["ph"], 6.8)
        self.assertEqual(payload["conformers"], 7)
        self.assertEqual(payload["seed_count"], 4)
        self.assertEqual(payload["base_seed"], 99001)
        self.assertEqual(payload["exhaustiveness"], 32)
        self.assertEqual(revision, self.store.load("desktop").revision)

    def test_completed_bundle_disables_duplicate_finalization_and_remains_openable(self):
        bundle = self.root / "target.duprotocol"
        bundle.write_bytes(b"bundle")
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "final-protocol-bundle", "protocol_bundle", str(bundle), description="Portable protocol",
        ))
        self.store.save(state)
        self.window.host_client = object()
        self.window.exploratory_approval.setChecked(True)
        self.window.refresh()
        self.assertFalse(self.window.finalize_button.isEnabled())
        self.assertIn(str(bundle), self.window.finalization_status.text())
        self.assertTrue(self.window.open_bundle_location_button.isEnabled())

    def test_screening_preview_is_required_before_locked_run(self):
        class FakeHost:
            def __init__(self):
                self.calls = []

            def request(self, study_id, operation, payload, *, expected_revision=None):
                self.calls.append((study_id, operation, payload, expected_revision))
                if operation == "screening_plan":
                    return {"result": {"plan": {
                        "protocol_type": "site-guided-exploratory", "engine": "vina",
                        "compound_count": 2, "conformers_per_compound": 3,
                        "independent_seed_count": 5, "docking_site_count": 2,
                        "jobs_per_compound": 30, "total_docking_jobs": 60,
                        "exploratory_authorization_required": True, "parameters": {},
                    }}}
                return {"status": "applied"}

        bundle = self.root / "target.duprotocol"
        bundle.write_bytes(b"bundle")
        ligands = self.root / "ligands.sdf"
        ligands.write_text("one\n$$$$\ntwo\n$$$$\n")
        controller = StudyController(self.store)
        pending = self.store.load("desktop").pending_decisions[0]
        controller.resolve_decision("desktop", pending.id, ("P1",), actor="scientist")
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "final-protocol-bundle", "protocol_bundle", str(bundle), description="Portable protocol",
        ))
        self.store.save(state)
        host = FakeHost()
        self.window.host_client = host
        self.window.screen_ligands.setText(str(ligands))
        self.window.screen_output.setText(str(self.root / "screen"))
        self.window.refresh()
        self.assertFalse(self.window.start_screening_button.isEnabled())
        self.window.preview_screening()
        self.assertIn("60 sequential docking jobs", self.window.screening_status.text())
        self.assertFalse(self.window.start_screening_button.isEnabled())
        self.window.screen_exploratory_approval.setChecked(True)
        self.assertTrue(self.window.start_screening_button.isEnabled())
        self.window.start_screening_button.click()
        self.assertEqual(host.calls[-1][1], "start_screening")
        self.assertEqual(host.calls[-1][2]["analysis"], "representatives")
        self.assertTrue(host.calls[-1][2]["exploratory_use_approved"])

    def test_screening_results_show_scores_as_review_outputs(self):
        compound = self.root / "screen/compounds/ligand_a"
        analysis = compound / "pose_analysis"
        analysis.mkdir(parents=True)
        manifest = compound / "screen_manifest.json"
        manifest.write_text(json.dumps({
            "completion_status": "EXPLORATORY_NO_CONTROL",
            "docking_site_count": 2, "docking_job_count": 30,
        }))
        scores = compound / "all_scores.csv"
        scores.write_text("affinity\n-6.5\n-7.2\n")
        clusters = analysis / "cluster_summary.csv"
        clusters.write_text("cluster_id,count\n1,4\n2,2\n")
        session = analysis / "representative_browser.pse"
        session.write_bytes(b"pse")
        interactions = analysis / "cluster_001/interactions"
        interactions.mkdir(parents=True)
        diagram = interactions / "representative_plip2d.png"
        from docking_universal.gui.qt import QtGui
        image = QtGui.QImage(80, 60, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        self.assertTrue(image.save(str(diagram)))
        report = self.root / "screen/report/screen.pdf"
        report.parent.mkdir(parents=True)
        report.write_bytes(b"%PDF-1.4\n%%EOF\n")
        state = self.store.load("desktop")
        state.artifacts.extend([
            ArtifactRecord("screen-manifest", "screening_compound_manifest", str(manifest)),
            ArtifactRecord("screen-scores", "screening_scores", str(scores)),
            ArtifactRecord("screen-report", "screening_report", str(report)),
            ArtifactRecord("screen-plip2d", "screening_interaction_diagram", str(diagram)),
        ])
        self.store.save(state)
        self.window.refresh()
        self.assertEqual(self.window.screening_results.rowCount(), 1)
        values = [self.window.screening_results.item(0, column).text() for column in range(6)]
        self.assertEqual(values, ["ligand_a", "EXPLORATORY_NO_CONTROL", "2", "30", "-7.2", "2"])
        self.assertTrue(self.window.open_screen_report_button.isEnabled())
        self.window.screening_results.selectRow(0)
        self.assertEqual(self.window.interaction_diagram_choice.count(), 1)
        self.assertIn("Energy rank ? · Cluster 001", self.window.interaction_diagram_choice.currentText())
        self.assertTrue(self.window.open_interaction_diagram_button.isEnabled())
        with patch.object(QtGui.QDesktopServices, "openUrl", return_value=True) as opened:
            self.window.open_selected_pose_session()
        self.assertEqual(opened.call_args.args[0].toLocalFile(), str(session.resolve()))
        with patch.object(QtGui.QDesktopServices, "openUrl", return_value=True) as opened:
            self.window.open_selected_interaction_diagram()
        self.assertEqual(opened.call_args.args[0].toLocalFile(), str(diagram.resolve()))

    def test_pose_interaction_loading_clears_old_image_and_rejects_stale_completion(self):
        from docking_universal.gui.qt import QtGui

        first = self.root / "pose-1.png"
        second = self.root / "pose-2.png"
        for path, color in ((first, "red"), (second, "blue")):
            image = QtGui.QImage(40, 40, QtGui.QImage.Format_RGB32)
            image.fill(QtGui.QColor(color))
            self.assertTrue(image.save(str(path)))
        old_key = self.window.begin_pose_interaction_loading("ligand", "site_1", 1)
        self.assertTrue(self.window.interaction_diagram_view.pixmap().isNull())
        self.assertIsNone(self.window._interaction_source_pixmap)
        self.assertIn("pose 1", self.window.interaction_diagram_view.text())
        new_key = self.window.begin_pose_interaction_loading("ligand", "site_1", 2)
        self.assertFalse(self.window.complete_pose_interaction_loading(old_key, first))
        self.assertIn("pose 2", self.window.interaction_diagram_view.text())
        self.assertTrue(self.window.complete_pose_interaction_loading(new_key, second))
        self.assertFalse(self.window.interaction_diagram_view.pixmap().isNull())
        self.window.interaction_zoom.setCurrentText("100%")
        self.assertEqual(self.window.interaction_diagram_view.pixmap().size().width(), 40)
        self.window.interaction_zoom.setCurrentText("200%")
        self.assertEqual(self.window.interaction_diagram_view.pixmap().size().width(), 80)

    def test_cluster_synopsis_orders_representatives_by_retained_energy_rank(self):
        from docking_universal.gui.qt import QtGui

        compound = self.root / "screen/compounds/ligand_a"
        analysis = compound / "pose_analysis"
        analysis.mkdir(parents=True)
        manifest = compound / "screen_manifest.json"
        manifest.write_text(json.dumps({"completion_status": "retained"}))
        (analysis / "cluster_summary.csv").write_text(
            "energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count\n"
            "1,2,-9.2,12\n"
            "2,3,-9.0,8\n"
            "3,1,-8.8,5\n"
        )
        diagrams = []
        for cluster_id in (1, 2, 3):
            interactions = analysis / f"cluster_{cluster_id:03d}/interactions"
            interactions.mkdir(parents=True)
            diagram = interactions / "representative_plip2d.png"
            image = QtGui.QImage(40, 30, QtGui.QImage.Format_RGB32)
            image.fill(QtGui.QColor("white"))
            self.assertTrue(image.save(str(diagram)))
            diagrams.append(diagram)
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "screen-manifest", "screening_compound_manifest", str(manifest),
        ))
        for index, diagram in enumerate(diagrams):
            state.artifacts.append(ArtifactRecord(
                f"screen-plip2d-{index}", "screening_interaction_diagram", str(diagram),
            ))
        self.store.save(state)

        self.window.refresh()
        self.window.screening_results.selectRow(0)

        labels = [
            self.window.interaction_diagram_choice.itemText(index)
            for index in range(self.window.interaction_diagram_choice.count())
        ]
        self.assertEqual(len(labels), 3)
        self.assertIn("Energy rank 1 · Cluster 002 · primary site · -9.2 kcal/mol", labels[0])
        self.assertIn("Energy rank 2 · Cluster 003 · primary site · -9.0 kcal/mol", labels[1])
        self.assertIn("Energy rank 3 · Cluster 001 · primary site · -8.8 kcal/mol", labels[2])
        self.assertEqual(
            Path(self.window.interaction_diagram_choice.currentData()), diagrams[1],
        )

    def test_expanded_pose_review_lists_every_retained_pose_and_clears_cluster_image(self):
        compound = self.root / "screen/compounds/ligand_a"
        analysis = compound / "pose_analysis"
        analysis.mkdir(parents=True)
        manifest = compound / "screen_manifest.json"
        manifest.write_text(json.dumps({"completion_status": "retained"}))
        (analysis / "all_poses.sdf").write_text("retained fixture\n")
        (analysis / "receptor.pdb").write_text("END\n")
        (analysis / "pose_inventory.csv").write_text(
            "pose_id,cluster_id,selected_cluster,seed,conformer,model,energy_kcal_per_mol,source\n"
            "1,2,yes,101,state_a,1,-8.1,poses.pdbqt\n"
            "2,2,no,102,state_a,2,-7.7,poses.pdbqt\n"
            "3,5,yes,103,state_b,1,-7.2,poses.pdbqt\n"
        )
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "screen-manifest", "screening_compound_manifest", str(manifest),
        ))
        self.store.save(state)
        self.window.refresh()
        self.window.screening_results.selectRow(0)
        self.window.pose_review_mode.setCurrentIndex(1)
        self.assertEqual(self.window.pose_results.rowCount(), 3)
        values = [self.window.pose_results.item(0, column).text() for column in range(7)]
        self.assertEqual(values, ["1", "2", "-8.1 kcal/mol", "yes", "101", "state_a", "1"])
        self.assertFalse(self.window.interaction_diagram_choice.isVisibleTo(self.window))
        self.window.pose_results.selectRow(1)
        self.assertIn("Pose 2 selected", self.window.interaction_diagram_view.text())
        self.assertTrue(self.window.interaction_diagram_view.pixmap().isNull())
        self.window.pose_cluster_filter.setCurrentIndex(
            self.window.pose_cluster_filter.findData(5)
        )
        self.assertTrue(self.window.pose_results.isRowHidden(0))
        self.assertFalse(self.window.pose_results.isRowHidden(2))
        self.window.pose_cluster_filter.setCurrentIndex(0)
        self.window.refresh()
        selected = self.window.pose_results.selectionModel().selectedRows()
        self.assertEqual(len(selected), 1)
        self.assertEqual(self.window.pose_results.item(selected[0].row(), 0).text(), "2")

    def test_expanded_pose_cache_hit_opens_the_exact_pose_diagram(self):
        from docking_universal.gui.qt import QtGui

        compound = self.root / "screen/compounds/ligand_a"
        analysis = compound / "pose_analysis"
        cache = analysis / "pose_interactions/pose_0001"
        cache.mkdir(parents=True)
        manifest = compound / "screen_manifest.json"
        manifest.write_text(json.dumps({"completion_status": "retained"}))
        (analysis / "all_poses.sdf").write_text("retained fixture\n")
        (analysis / "receptor.pdb").write_text("END\n")
        (analysis / "pose_inventory.csv").write_text(
            "pose_id,cluster_id,selected_cluster,seed,conformer,model,energy_kcal_per_mol,source\n"
            "1,2,yes,101,state_a,1,-8.1,poses.pdbqt\n"
        )
        diagram = cache / "interaction_diagram.png"
        (cache / "pose.sdf").write_text("pose\n")
        image = QtGui.QImage(80, 60, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        self.assertTrue(image.save(str(diagram)))
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "screen-manifest", "screening_compound_manifest", str(manifest),
        ))
        self.store.save(state)
        self.window.refresh()
        class Viewer:
            connected = True

            def __init__(self):
                self.calls = []

            def show_pose(self, analysis_root, pose_id):
                self.calls.append((Path(analysis_root), pose_id))

        viewer = Viewer()
        self.window.viewer_coordinator = viewer
        self.window.screening_results.selectRow(0)
        self.window.pose_review_mode.setCurrentIndex(1)
        self.window.pose_results.selectRow(0)
        self.assertEqual(self.window._current_interaction_diagram, diagram)
        self.assertEqual(viewer.calls, [(analysis, 1)])
        self.assertIn("retained pose 1", self.window.viewer_status.text())
        with patch.object(QtGui.QDesktopServices, "openUrl", return_value=True) as opened:
            self.window.open_selected_interaction_diagram()
        self.assertEqual(opened.call_args.args[0].toLocalFile(), str(diagram.resolve()))


if __name__ == "__main__":
    unittest.main()
