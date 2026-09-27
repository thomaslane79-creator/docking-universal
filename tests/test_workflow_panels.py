import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from docking_universal.gui.qt import QtWidgets
from docking_universal.gui.workflow_panels import PreparationProgressPanel, StudySetupPanel, ProtocolFinalizationPanel, ScreeningSetupPanel
from docking_universal.gui.workflow_navigation import WorkflowNavigationController

class WorkflowPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_setup_emits_intention_and_returns_typed_values(self):
        panel = StudySetupPanel(); observed=[]; fetched=[]
        panel.prepareRequested.connect(lambda: observed.append(True))
        panel.fetchInputRequested.connect(lambda: fetched.append(True))
        panel.input_pdb.setText("target.pdb"); panel.output_directory.setText("output"); panel.prepare_button.click()
        panel.fetch_button.click()
        self.assertTrue(observed); self.assertTrue(fetched); self.assertEqual(panel.values().receptor, "target.pdb"); self.assertEqual(panel.values().pocket_engine, "p2rank"); self.assertFalse(hasattr(panel, "host_client"))

    def test_other_panels_have_no_state_or_host_authority(self):
        for panel in (PreparationProgressPanel(), ProtocolFinalizationPanel(), ScreeningSetupPanel()):
            self.assertFalse(hasattr(panel, "store")); self.assertFalse(hasattr(panel, "host_client")); self.assertFalse(hasattr(panel, "viewer_coordinator"))

    def test_preparation_progress_is_distinct_from_setup_and_exposes_retained_work(self):
        panel = PreparationProgressPanel()
        self.assertEqual(panel.progress.format(), "Not started")
        self.assertIn("selected pocket detector", panel.operations.text())
        self.assertTrue(panel.summary.isReadOnly())

    def test_navigation_controller_owns_visibility_only(self):
        a, b = QtWidgets.QDockWidget(), QtWidgets.QDockWidget(); controller=WorkflowNavigationController({"a":a,"b":b})
        controller.activate("b"); self.assertFalse(a.isVisible()); self.assertTrue(b.isVisible())
        controller.activate("central"); self.assertFalse(a.isVisible()); self.assertFalse(b.isVisible())

if __name__ == "__main__": unittest.main()
