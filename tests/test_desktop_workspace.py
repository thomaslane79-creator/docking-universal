import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.application import StudyController
from docking_universal.gui.desktop import QT_IMPORT_ERROR, StudyWindow
from docking_universal.models import ArtifactRecord, JobStatus, PocketCandidate
from docking_universal.state import JsonStudyStore


@unittest.skipIf(QT_IMPORT_ERROR is not None, "selected Qt 5 binding is unavailable")
class DesktopWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PyQt5 import QtWidgets
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        from PyQt5 import QtCore
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
        self.assertTrue(self.window.decision_banner.isVisibleTo(self.window))
        self.window.detail.setCurrentText("Concise")
        self.assertIn("DECISION REQUIRED", self.window.decision_banner.text())
        self.assertEqual(self.window.candidates.rowCount(), 1)

    def test_panels_are_floatable_and_fullscreen_is_reversible(self):
        from PyQt5 import QtWidgets
        docks = self.window.findChildren(QtWidgets.QDockWidget)
        self.assertGreaterEqual(len(docks), 5)
        self.assertIsNotNone(self.window.findChild(QtWidgets.QDockWidget, "study_setup_dock"))
        self.assertTrue(all(dock.features() & QtWidgets.QDockWidget.DockWidgetFloatable for dock in docks))
        self.window.showFullScreen()
        self.application.processEvents()
        self.assertTrue(self.window.isFullScreen())
        self.window.toggle_full_screen()
        self.application.processEvents()
        self.assertFalse(self.window.isFullScreen())

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
        from PyQt5 import QtCore
        self.assertEqual(matching[0].data(QtCore.Qt.UserRole), artifact.path)

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
        from PyQt5 import QtCore
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
            self.assertEqual(revision, self.store.load("setup").revision)
            self.assertNotIn("command", payload)
        finally:
            window.close()


if __name__ == "__main__":
    unittest.main()
