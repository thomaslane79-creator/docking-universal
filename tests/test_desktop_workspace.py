import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.application import StudyController
from docking_universal.gui.desktop import QT_IMPORT_ERROR, StudyWindow
from docking_universal.models import PocketCandidate
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
        self.assertGreaterEqual(len(docks), 4)
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


if __name__ == "__main__":
    unittest.main()
