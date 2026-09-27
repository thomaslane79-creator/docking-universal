import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.application import StudyController
from docking_universal.gui.qt import QtWidgets
from docking_universal.gui.study_launcher import StudyLauncherDialog, study_id_from_name
from docking_universal.state import JsonStudyStore


class Host:
    def __init__(self, controller):
        self.controller = controller
        self.calls = []

    def request(self, study_id, operation, payload):
        self.calls.append((study_id, operation, payload))
        if operation == "create_study":
            self.controller.create_study(
                study_id, payload["name"], payload.get("workflow", "site_guided_protocol")
            )
        return {"status": "applied"}


class StudyLauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.store = JsonStudyStore(Path(self.temporary.name) / "studies")
        self.controller = StudyController(self.store)
        self.host = Host(self.controller)

    def tearDown(self):
        self.temporary.cleanup()

    def test_lists_persisted_studies_and_opens_exact_identity(self):
        self.controller.create_study("older", "Older study")
        self.controller.create_study("newer", "Newer study")
        dialog = StudyLauncherDialog(self.store, self.host)
        self.assertEqual(dialog.studies.rowCount(), 2)
        matching = [
            row for row in range(dialog.studies.rowCount())
            if dialog.studies.item(row, 0).text() == "Newer study"
        ]
        dialog.studies.selectRow(matching[0])
        dialog.open_selected()
        self.assertEqual(dialog.selected_study_id, "newer")

    def test_create_uses_safe_unique_identity_and_application_host(self):
        self.controller.create_study("Kinase-screen", "Existing")
        dialog = StudyLauncherDialog(self.store, self.host)
        dialog.study_name.setText("Kinase screen")
        dialog.create_study()
        self.assertEqual(dialog.selected_study_id, "Kinase-screen-2")
        self.assertEqual(self.host.calls[0][1], "create_study")
        self.assertEqual(self.store.load("Kinase-screen-2").name, "Kinase screen")

    def test_name_conversion_never_creates_an_invalid_or_empty_id(self):
        self.assertEqual(study_id_from_name(" AChE: donepezil "), "AChE-donepezil")
        self.assertEqual(study_id_from_name("***"), "study")

    def test_new_and_open_menu_modes_show_only_the_relevant_action(self):
        create = StudyLauncherDialog(self.store, self.host, mode="create")
        self.assertTrue(create.studies.isHidden())
        self.assertTrue(create.open_button.isHidden())
        self.assertFalse(create.create_button.isHidden())
        opened = StudyLauncherDialog(self.store, self.host, mode="open")
        self.assertTrue(opened.create_button.isHidden())
        self.assertTrue(opened.create_group.isHidden())


if __name__ == "__main__":
    unittest.main()
