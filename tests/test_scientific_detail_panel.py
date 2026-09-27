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

    def test_show_full_details_selects_technical_and_exposes_retained_context(self):
        self.panel.full_details_button.click(); self.panel.render(self.state)
        self.assertEqual(self.panel.mode.currentText(), "Technical")
        self.assertIn("local-only", self.panel.view.toPlainText())
        self.assertIn("/retained", self.panel.view.toPlainText())
        self.assertFalse(hasattr(self.panel, "host_client"))

if __name__ == "__main__": unittest.main()
