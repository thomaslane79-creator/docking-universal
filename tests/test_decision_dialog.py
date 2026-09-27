import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.decisions import DecisionOption, DecisionRequired
from docking_universal.gui.decision_dialog import DecisionDialog
from docking_universal.gui.qt import QtCore, QtWidgets


class DecisionDialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings = QtCore.QSettings(
            str(Path(self.temporary.name) / "settings.ini"), QtCore.QSettings.IniFormat,
        )
        self.decision = DecisionRequired(
            id="decision-1", kind="select_pockets", prompt="Choose a region",
            detected="Two candidates were retained",
            why_stopped="The region controls the searched space.",
            consequences=("The approved geometry is recorded.",),
            options=(
                DecisionOption("P1", "Pocket 1", "Highest-ranked candidate", True),
                DecisionOption("P2", "Pocket 2", "Alternative candidate"),
            ),
            maximum_selections=2,
            payload={"candidate_ids": ["P1", "P2"]},
            presentation={
                "guided": "<ol><li>Compare the retained evidence.</li></ol>",
                "background": "Ranks organize candidates but do not prove relevance.",
                "technical": "Artifact hashes bind approval to geometry.",
            },
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_detail_preference_is_saved_without_saving_an_answer(self):
        dialog = DecisionDialog(
            self.decision, settings=self.settings, selected=("P1",),
            allow_approval=True,
        )
        dialog.detail_level.setCurrentIndex(dialog.detail_level.findData("technical"))
        dialog.reject()
        self.assertEqual(self.settings.value(DecisionDialog.SETTINGS_KEY), "technical")
        self.assertNotIn("P1", self.settings.allKeys())

        reopened = DecisionDialog(self.decision, settings=self.settings)
        self.assertEqual(reopened.detail_level.currentData(), "technical")
        self.assertEqual(reopened.selected_values(), ())

    def test_selected_values_respect_the_decision_contract(self):
        dialog = DecisionDialog(
            self.decision, settings=self.settings, selected=("P1", "P2"),
            allow_approval=True,
        )
        self.assertEqual(dialog.selected_values(), ("P1", "P2"))
        self.decision.validate_response(dialog.selected_values())

    def test_guided_level_shows_how_to_review_without_preselecting_an_answer(self):
        dialog = DecisionDialog(
            self.decision, settings=self.settings, allow_approval=True,
        )
        self.assertEqual(dialog.detail_level.currentData(), "guided")
        self.assertIn("How to review this decision", dialog.detail.toPlainText())
        self.assertIn("Compare the retained evidence", dialog.detail.toPlainText())
        self.assertEqual(dialog.selected_values(), ())


if __name__ == "__main__":
    unittest.main()
