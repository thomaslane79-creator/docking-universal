import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.workspace_controller import WorkspaceWindowController


class WorkspaceWindowControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings = QtCore.QSettings(
            str(Path(self.temporary.name) / "workspace.ini"), QtCore.QSettings.IniFormat,
        )
        self.window = QtWidgets.QMainWindow()
        self.calls = []
        self.controller = WorkspaceWindowController(
            self.window, self.settings, lambda: self.calls.append("refresh"),
        )

    def tearDown(self):
        self.controller.closed()
        self.window.close()
        self.temporary.cleanup()

    def test_polling_occurs_only_while_workspace_is_visible(self):
        self.controller.shown()
        self.assertTrue(self.controller.timer.isActive())
        self.controller.poll()
        self.assertEqual(self.calls, [])
        self.assertFalse(self.controller.timer.isActive())
        self.window.show()
        self.controller.shown()
        self.controller.poll()
        self.assertEqual(self.calls, ["refresh"])

    def test_geometry_and_dock_layout_round_trip_without_scientific_state(self):
        self.window.resize(777, 555)
        dock = QtWidgets.QDockWidget("Evidence", self.window)
        dock.setObjectName("evidence")
        self.window.addDockWidget(QtCore.Qt.RightDockWidgetArea, dock)
        self.controller.save_layout()
        self.window.resize(300, 200)
        self.controller.restore_layout()
        self.assertEqual(self.window.size().width(), 777)
        self.assertEqual(self.window.size().height(), 555)

    def test_incompatible_pre_stack_dock_layout_is_not_restored(self):
        self.settings.setValue("window/layout", b"obsolete-layout")
        self.settings.setValue(
            "window/layout_version", WorkspaceWindowController.LAYOUT_VERSION - 1,
        )
        restored = []
        original = self.window.restoreState
        self.window.restoreState = lambda value: restored.append(value)
        try:
            self.controller.restore_layout()
        finally:
            self.window.restoreState = original
        self.assertEqual(restored, [])


if __name__ == "__main__":
    unittest.main()
