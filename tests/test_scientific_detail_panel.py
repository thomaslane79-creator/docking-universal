import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from docking_universal.gui.qt import QtWidgets
from docking_universal.events import EventType, WorkflowEvent
from docking_universal.gui.scientific_detail import ScientificDetailPanel
from docking_universal.state import StudyState

class ScientificDetailPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.panel = ScientificDetailPanel()
        self.addCleanup(self.panel.close)
        self.state = StudyState("study", "Study", "workflow")
        self.state.events.append(WorkflowEvent(
            "event", 1, EventType.WARNING_RAISED, "Review required",
            explanation="Scientific implication", teaching="Teaching example",
            technical={"command": "local-only"}, data={"path": "/retained"}, mandatory=True,
        ))

    def test_guided_is_default_and_modes_only_change_presentation(self):
        before = self.state.to_dict(); self.panel.render(self.state)
        self.assertEqual(self.panel.mode.currentText(), "Guided")
        self.assertIn("Scientific implication", self.panel.view.toPlainText())
        self.assertNotIn("Teaching example", self.panel.view.toPlainText())
        self.panel.mode.setCurrentText("Teaching"); self.panel.render(self.state)
        self.assertIn("Teaching example", self.panel.view.toPlainText())
        self.assertEqual(self.state.to_dict(), before)

    def test_full_details_open_separately_without_changing_mode_or_study(self):
        self.panel.render(self.state)
        before = self.state.to_dict()
        changes = []
        self.panel.detailChanged.connect(changes.append)
        self.panel.full_details_button.click()
        guide = self.panel._full_details_window
        self.addCleanup(guide.close)
        self.assertTrue(guide.isVisible())
        self.assertFalse(guide.isModal())
        self.assertEqual(self.panel.mode.currentText(), "Guided")
        self.assertNotIn("local-only", self.panel.view.toPlainText())
        self.assertIn("local-only", guide.content.toPlainText())
        self.assertIn("/retained", guide.content.toPlainText())
        guide.close()
        self.state.events[-1].data['path'] = '/updated'
        self.panel.render(self.state)
        self.panel.full_details_button.click()
        self.assertIs(self.panel._full_details_window, guide)
        self.assertIn('/updated', guide.content.toPlainText())
        self.state.events[-1].data['path'] = '/retained'
        self.assertEqual(self.state.to_dict(), before)
        self.assertEqual(changes, [])
        self.assertFalse(hasattr(self.panel, "host_client"))

if __name__ == "__main__": unittest.main()
