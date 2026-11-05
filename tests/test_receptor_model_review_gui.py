import os
import unittest
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from docking_universal.gui.qt import QtWidgets
from docking_universal.gui.receptor_model_review import ReceptorModelReviewDialog
from docking_universal.gui.workflow_panels import ProtocolFinalizationPanel


class ReceptorModelReviewGuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.calls = []
        self.initial = {'residue_inventory': [{'resname': 'ASN', 'chain': 'A', 'number': '10', 'insertion_code': '',
            'label': 'ASN A:10', 'missing_backbone_atom_names': [],
            'alternate_locations': [{'altloc': 'A', 'occupancy_min': .6, 'occupancy_max': .6},
                                    {'altloc': 'B', 'occupancy_min': .4, 'occupancy_max': .4}]}]}
        self.severity = 'warning'
        def preview(choices):
            self.calls.append(choices)
            return {'choices': choices, 'changes': [{'description': 'Exact synthetic model change'}],
                    'severity': self.severity, 'preview_sha256': 'a' * 64, 'removed_atom_count': 1,
                    'selected_box_review': [{'label': 'B1', 'residues': [{'residue': 'NAG', 'chain': 'A', 'number': '1',
                        'inside_box': False, 'minimum_distance_to_box_angstrom': 13.44}]}]}
        self.dialog = ReceptorModelReviewDialog(self.initial, preview)
        self.addCleanup(self.dialog.close)

    def test_initial_choices_and_approval_are_empty(self):
        self.assertEqual(self.dialog.choices(), {'exclusions': [], 'alternate_locations': []})
        self.assertFalse(self.dialog.prepare_button.isEnabled())
        self.assertEqual(self.calls, [])
        note = self.dialog.findChildren(QtWidgets.QLabel)[0]
        self.assertIn('not recommended', note.text())
        note.show_explanation()
        self.assertIn('No missing residues', note.explanation_window.content.toPlainText())
        note.explanation_window.close()

    def test_exact_choices_preview_and_rationale_are_required_before_accept(self):
        self.dialog.exclusions.setPlainText('NAG A 1\nNAG B 1')
        self.dialog.preview_button.click()
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.dialog.prepare_button.isEnabled())
        self.dialog.rationale.setText('Review of the exact exploratory exclusions')
        self.dialog.acknowledge.setChecked(True)
        choices, fingerprint, why = self.dialog.approved_change()
        self.assertEqual(len(choices['exclusions']), 2)
        self.assertEqual(fingerprint, 'a' * 64)
        self.assertIn('exploratory', why)
        self.assertIn('13.44 Å', self.dialog.details.toPlainText())

    def test_changing_any_choice_invalidates_the_previous_preview(self):
        self.dialog.exclusions.setPlainText('NAG A 1')
        self.dialog.preview_button.click()
        self.dialog.rationale.setText('Reviewed')
        self.dialog.acknowledge.setChecked(True)
        self.assertTrue(self.dialog.prepare_button.isEnabled())
        self.dialog.alternates.cellWidget(0, 2).setCurrentIndex(2)
        self.assertFalse(self.dialog.prepare_button.isEnabled())
        self.assertFalse(self.dialog.acknowledge.isChecked())
        with self.assertRaises(ValueError):
            self.dialog.approved_change()

    def test_standard_amino_acid_exclusion_needs_additional_acknowledgement(self):
        self.severity = 'high'
        self.dialog.exclusions.setPlainText('ASN A 10')
        self.dialog.preview_button.click()
        self.dialog.rationale.setText('Explicit structural review')
        self.dialog.acknowledge.setChecked(True)
        self.assertFalse(self.dialog.prepare_button.isEnabled())
        self.dialog.protein_acknowledge.setChecked(True)
        self.assertTrue(self.dialog.prepare_button.isEnabled())

    def test_invalid_identity_is_reported_without_calling_host_or_mutation(self):
        self.dialog.exclusions.setPlainText('all NAG')
        self.dialog.preview_button.click()
        self.assertEqual(self.calls, [])
        self.assertIn('Preview stopped', self.dialog.details.toPlainText())
        self.assertFalse(self.dialog.prepare_button.isEnabled())

    def test_cancel_has_no_model_authority_and_finalization_action_is_initially_hidden(self):
        self.dialog.reject()
        self.assertEqual(self.calls, [])
        panel = ProtocolFinalizationPanel()
        self.addCleanup(panel.close)
        self.assertTrue(panel.review_model_button.isHidden())
        self.assertIn('previous failures', panel.review_model_button.toolTip())

    def test_candidate_selection_requires_fresh_review_and_does_not_generate_atoms(self):
        self.dialog.sidechain_candidate.setText('/local/reviewed-candidate.json')
        self.assertEqual(self.calls, [])
        self.dialog.preview_button.click()
        self.assertEqual(self.calls[0]['sidechain_candidate'], '/local/reviewed-candidate.json')
        self.dialog.rationale.setText('Exact generated atoms and original observations reviewed')
        self.dialog.acknowledge.setChecked(True)
        self.assertTrue(self.dialog.prepare_button.isEnabled())
        self.dialog.sidechain_candidate.setText('/local/another-candidate.json')
        self.assertFalse(self.dialog.prepare_button.isEnabled())
        self.assertFalse(self.dialog.acknowledge.isChecked())


if __name__ == '__main__':
    unittest.main()
