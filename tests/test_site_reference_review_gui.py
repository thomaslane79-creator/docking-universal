import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from docking_universal.gui.qt import QtWidgets
from docking_universal.gui.workflow_panels import ProtocolImportDialog
from docking_universal.gui.pocket_evidence import PocketEvidencePanel


class ReferenceWarningGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_import_warning_is_separate_readonly_and_does_not_grant_authority(self):
        preview = dict(target='Fixture', protocol_type='site-guided-exploratory', region_count=1,
            exploratory_authorization_required=True, engine='vina', parameters={}, verified_files=3,
            site_reference_warning='Incomplete reference; CCD-derived screening chemistry; not a control.')
        dialog = ProtocolImportDialog(preview)
        self.addCleanup(dialog.close)
        warning = dialog.findChild(QtWidgets.QPlainTextEdit, 'protocol_site_reference_warning')
        self.assertTrue(warning.isReadOnly())
        self.assertIn('Incomplete reference', warning.toPlainText())
        self.assertIsNone(dialog.findChild(QtWidgets.QPlainTextEdit, 'protocol_model_change_warning'))
        self.assertEqual(dialog.result(), QtWidgets.QDialog.DialogCode.Rejected)

    def test_box_context_displays_warning_without_receptor_changes(self):
        panel = PocketEvidencePanel(); self.addCleanup(panel.close)
        panel.set_candidate({'id': 'B1', 'label': 'B1', 'evidence': {
            'reviewed_incomplete_reference': {'warning': 'Incomplete reference 5/23; no atoms filled in.'}}})
        self.assertFalse(panel.preparation_issues.isHidden())
        self.assertIn('5/23', panel.preparation_issues.toPlainText())
        self.assertNotIn('Distances', panel.preparation_issues.toPlainText())
        panel.set_candidate(None)
        self.assertTrue(panel.preparation_issues.isHidden())


if __name__ == '__main__':
    unittest.main()
