import os
from pathlib import Path
import unittest
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from docking_universal.gui.desktop import QT_IMPORT_ERROR, StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
import test_protocol_import


@unittest.skipIf(QT_IMPORT_ERROR is not None, 'Qt unavailable')
class GuiProtocolImportTests(unittest.TestCase):
    def setUp(self):
        from docking_universal.gui.qt import QtWidgets, QtCore
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        self.fixture = test_protocol_import.ProtocolImportTests()
        self.fixture.setUp()
        self.client = ApplicationHostClient(self.fixture.store.root,
            Path(__file__).parents[1] / 'libexec/docking-universal-application-host.py',
            python_executable='/opt/anaconda3/envs/docking-universal/bin/python')
        self.client.start()
        self.settings = QtCore.QSettings(str(self.fixture.root / 'window.ini'), QtCore.QSettings.Format.IniFormat)
        self.window = StudyWindow(self.fixture.store, 'fresh', host_client=self.client, settings=self.settings)

    def tearDown(self):
        self.window.close()
        self.client.close()
        self.fixture.tearDown()

    def test_import_requires_review_and_reopens_locked_without_synthetic_preparation(self):
        from docking_universal.gui.qt import QtCore, QtWidgets
        from docking_universal.gui.workflow_panels import ProtocolImportDialog
        panel = self.window.study_setup_panel
        panel.pathway.setCurrentIndex(panel.pathway.findData('reuse'))
        self.assertFalse(panel.protocol_bundle.parentWidget().isHidden())
        self.assertTrue(panel.input_pdb.parentWidget().isHidden())
        self.assertEqual(panel.prepare_button.text(), 'Review and import protocol')
        panel.protocol_bundle.setText(str(self.fixture.bundle))
        with patch.object(ProtocolImportDialog, 'exec', return_value=QtWidgets.QDialog.DialogCode.Rejected):
            panel.prepare_button.click()
        self.assertFalse(self.fixture.store.load('fresh').artifacts)
        with patch.object(ProtocolImportDialog, 'exec', return_value=QtWidgets.QDialog.DialogCode.Accepted):
            panel.prepare_button.click()
        state = self.fixture.store.load('fresh')
        self.assertEqual(len(state.artifacts), 1)
        self.assertFalse(state.jobs)
        self.assertFalse(self.window.screen_exploratory_approval.isChecked())
        self.assertFalse(panel.review_protocol_button.isHidden())
        self.assertTrue(panel.review_protocol_button.isEnabled())
        self.assertFalse(panel.prepare_button.isEnabled())
        for row in (1, 2, 3):
            self.assertFalse(self.window.workflow_navigation.item(row).flags() & QtCore.Qt.ItemFlag.ItemIsEnabled)
        self.assertTrue(self.window.workflow_navigation.item(4).flags() & QtCore.Qt.ItemFlag.ItemIsEnabled)
        self.fixture.bundle.unlink()
        with patch.object(ProtocolImportDialog, 'exec', return_value=QtWidgets.QDialog.DialogCode.Rejected) as dialog:
            panel.review_protocol_button.click()
            dialog.assert_called_once()
        self.window.close()
        self.client.close()
        self.client.start()
        self.window = StudyWindow(self.fixture.store, 'fresh', host_client=self.client, settings=self.settings)
        self.assertEqual(self.window.study_pathway.currentData(), 'reuse')
        self.assertTrue(Path(self.window.study_setup_panel.protocol_bundle.text()).is_file())
        self.assertFalse(self.window.screen_exploratory_approval.isChecked())

    def test_review_dialog_is_readonly_and_does_not_approve_screening(self):
        from docking_universal.gui.qt import QtWidgets
        from docking_universal.gui.workflow_panels import ProtocolImportDialog
        dialog = ProtocolImportDialog(self.fixture.preview)
        labels = ' '.join(label.text() for label in dialog.findChildren(QtWidgets.QLabel))
        self.assertIn('has not passed', labels)
        self.assertIn('does not prepare', labels)
        table = dialog.findChild(QtWidgets.QTableWidget)
        self.assertEqual(table.editTriggers(), QtWidgets.QAbstractItemView.EditTrigger.NoEditTriggers)
        self.assertFalse(self.fixture.store.load('fresh').artifacts)
        dialog.close()


if __name__ == '__main__':
    unittest.main()
