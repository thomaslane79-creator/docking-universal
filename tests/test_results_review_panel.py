import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.gui.results_review import QT_IMPORT_ERROR, ResultsReviewPanel


@unittest.skipIf(QT_IMPORT_ERROR is not None, "selected Qt 5 binding is unavailable")
class ResultsReviewPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from docking_universal.gui.qt import QtWidgets
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_component_owns_review_widgets_but_no_scientific_services(self):
        panel = ResultsReviewPanel({"status": "available", "missing": []})
        try:
            self.assertEqual(panel.objectName(), "results_review_panel")
            self.assertEqual(panel.review_mode.count(), 2)
            self.assertEqual(panel.pose_results.columnCount(), 7)
            self.assertIn("do not establish affinity", panel.findChild(
                type(panel.session_status), "results_scientific_warning",
            ).text())
            self.assertFalse(hasattr(panel, "host_client"))
            self.assertFalse(hasattr(panel, "viewer_coordinator"))
            self.assertFalse(hasattr(panel, "store"))
        finally:
            panel.close()

    def test_missing_renderer_is_visible_without_disabling_retained_review(self):
        panel = ResultsReviewPanel({
            "status": "unavailable", "missing": ["node", "chromium"],
        })
        try:
            self.assertIn("node", panel.renderer_status.text())
            self.assertIn("chromium", panel.renderer_status.text())
            self.assertTrue(panel.screening_results.isEnabled())
            self.assertTrue(panel.diagram_choice.isEnabled())
        finally:
            panel.close()


if __name__ == "__main__":
    unittest.main()
