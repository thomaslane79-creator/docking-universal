import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from docking_universal.gui.qt import QtCore, QtWidgets
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
        self.box_review_pending = False
        def preview(choices):
            self.calls.append(choices)
            return {'choices': choices, 'changes': [{'description': 'Exact synthetic model change'}],
                    'severity': self.severity, 'preview_sha256': 'a' * 64, 'removed_atom_count': 1,
                    'box_review_pending': self.box_review_pending,
                    'selected_box_review': [] if self.box_review_pending else [{'label': 'B1', 'residues': [{'residue': 'NAG', 'chain': 'A', 'number': '1',
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

    def test_guidance_suggests_an_available_method_and_keeps_tool_names_under_advanced(self):
        self.dialog.close()
        self.initial.update(preparation_backend='meeko', available_preparation_backends=['meeko', 'adfr'],
            recovery_guidance={'summary': 'Standard preparation cannot process cobalt.',
                'next_step': 'Try the alternative method without removing components.',
                'recommended_backend': 'adfr', 'last_backend': 'meeko', 'details': 'Meeko rejected Co. ADFRsuite is a candidate, not a guarantee.'})
        callback = self.dialog._preview_callback
        def preview(choices):
            record = callback(choices)
            record['changes'][0]['kind'] = 'preparation_method_change'
            return record
        self.dialog = ReceptorModelReviewDialog(self.initial, preview)
        self.assertTrue(self.dialog.backend_controls.isHidden())
        self.assertEqual(self.dialog.preparation_backend.currentData(), 'adfr')
        self.assertIn('Alternative preparation', self.dialog.method_summary.text())
        self.assertNotIn('ADFR', self.dialog.method_summary.text())
        self.assertEqual(self.dialog.exclusions.toPlainText(), '')
        self.assertEqual(self.calls, [])
        self.assertFalse(self.dialog.prepare_button.isEnabled())
        self.dialog.preview_button.click()
        self.assertIn('Keep structure', self.dialog.prepare_button.text())
        self.dialog.rationale.setText('Keep all components and test the suggested compatible method')
        self.dialog.acknowledge.setChecked(True)
        self.assertTrue(self.dialog.prepare_button.isEnabled())
        self.assertEqual(self.dialog.approved_change()[0]['preparation_backend'], 'adfr')
        self.assertEqual(self.dialog.approved_change()[0]['exclusions'], [])
        self.dialog.advanced_backend_toggle.click()
        self.assertFalse(self.dialog.backend_controls.isHidden())
        self.dialog.preparation_backend.setCurrentIndex(self.dialog.preparation_backend.findData('meeko'))
        self.assertFalse(self.dialog.prepare_button.isEnabled())

    def test_unavailable_suggestion_and_already_tried_method_are_explained(self):
        self.dialog.close()
        guidance = {'summary': 'Preparation stopped.', 'next_step': 'Review the remaining issues.',
                    'recommended_backend': 'adfr', 'last_backend': 'adfr', 'details': 'Retained attempt failed charge checks.'}
        self.initial.update(preparation_backend='meeko', available_preparation_backends=['meeko'], recovery_guidance=guidance)
        self.dialog = ReceptorModelReviewDialog(self.initial, self.dialog._preview_callback)
        self.assertEqual(self.dialog.preparation_backend.currentData(), 'meeko')
        self.assertIn('unavailable', self.dialog.method_summary.text())
        self.dialog.close()
        self.initial.update(preparation_backend='adfr', available_preparation_backends=['meeko', 'adfr'])
        self.dialog = ReceptorModelReviewDialog(self.initial, self.dialog._preview_callback)
        self.assertIn('already tried', self.dialog.method_summary.text())
        self.assertFalse(self.dialog.prepare_button.isEnabled())

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

    def test_backend_choice_is_explicit_and_requires_new_preview(self):
        self.dialog.close()
        self.initial['available_preparation_backends'] = ['meeko', 'adfr']
        self.dialog = ReceptorModelReviewDialog(self.initial, self.dialog._preview_callback)
        self.addCleanup(self.dialog.close)
        self.assertEqual(self.dialog.preparation_backend.currentData(), 'meeko')
        self.assertNotIn('preparation_backend', self.dialog.choices())
        self.dialog.exclusions.setPlainText('NAG A 1')
        self.dialog.preview_button.click()
        self.dialog.rationale.setText('Exact component and backend reviewed')
        self.dialog.acknowledge.setChecked(True)
        self.assertTrue(self.dialog.prepare_button.isEnabled())
        self.dialog.preparation_backend.setCurrentIndex(1)
        self.assertFalse(self.dialog.prepare_button.isEnabled())
        self.assertFalse(self.dialog.acknowledge.isChecked())
        self.assertEqual(self.dialog.choices()['preparation_backend'], 'adfr')
        self.dialog.preview_button.click()
        self.assertEqual(self.calls[-1]['preparation_backend'], 'adfr')
        self.dialog.acknowledge.setChecked(True)
        self.assertEqual(self.dialog.approved_change()[0]['preparation_backend'], 'adfr')

    def test_unavailable_backend_cannot_be_selected_or_submitted(self):
        self.assertFalse(self.dialog.preparation_backend.model().item(1).isEnabled())
        self.dialog.preparation_backend.setCurrentIndex(1)
        self.dialog.preview_button.click()
        self.assertEqual(self.calls, [])
        self.assertIn('unavailable', self.dialog.details.toPlainText())

    def test_failed_preparation_preview_discloses_pending_box_without_default_exclusions(self):
        self.dialog.close()
        self.box_review_pending = True
        self.initial.update(box_review_pending=True, review_stage='failed_preparation')
        self.initial['residue_inventory'].append({'resname': 'COH', 'chain': 'A', 'number': '602',
            'insertion_code': '', 'label': 'COH A:602', 'missing_backbone_atom_names': [], 'alternate_locations': []})
        self.dialog = ReceptorModelReviewDialog(self.initial, self.dialog._preview_callback)
        self.addCleanup(self.dialog.close)
        self.assertEqual(self.dialog.choices()['exclusions'], [])
        self.assertFalse(self.dialog.box_review_notice.isHidden())
        self.assertNotIn('distances', self.dialog.preview_button.text())
        self.dialog.exclusions.setPlainText('NAG A 1')
        self.dialog.preview_button.click()
        self.assertIn('Docking box not available yet', self.dialog.details.toPlainText())
        self.assertIn('flagged when the box is generated', self.dialog.details.toPlainText())
        self.assertNotIn('COH', str(self.calls))
        self.assertFalse(self.dialog.prepare_button.isEnabled())
        self.assertFalse(self.dialog.candidate_toggle.isHidden())
        self.assertTrue(self.dialog.sidechain_candidate.parentWidget().isHidden())
        self.dialog.candidate_toggle.click()
        self.assertFalse(self.dialog.sidechain_candidate.parentWidget().isHidden())

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


class FailedPreparationReviewExposureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        from docking_universal.application import StudyController
        from docking_universal.gui.desktop import StudyWindow
        from docking_universal.models import Job, JobStatus
        from docking_universal.state import JsonStudyStore
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.pdb'
        self.source.write_text('ATOM      1  CA  ALA A   1       1.000   2.000   3.000  1.00 20.00           C\n')
        self.store = JsonStudyStore(self.root / 'studies')
        StudyController(self.store).create_study('failed-control', 'Failed control fixture')
        state = self.store.load('failed-control')
        state.workflow_data['study_setup'] = dict(input_pdb=str(self.source),
            input_structure_sha256='a' * 64, working_directory=str(self.root / 'work'),
            pathway='control', site_review_first=True, site_mode='ligand',
            ligand_resname='ID8', ligand_chain_id='B', ligand_residue_number='602')
        state.jobs = [Job('failed-prep', 'preparation_and_pocket_detection', JobStatus.FAILED,
                          error='Unsupported receptor element')]
        self.store.save(state)
        self.host = SimpleNamespace(connected=True, request=Mock(), runtime={
            'failed_preparation_model_review_supported': True,
            'reviewed_receptor_changes_supported': True,
            'reviewed_receptor_preparation_backends': ['meeko', 'adfr']})
        settings = QtCore.QSettings(str(self.root / 'window.ini'), QtCore.QSettings.IniFormat)
        self.window = StudyWindow(self.store, 'failed-control', settings=settings, host_client=self.host)
        self.addCleanup(self.close_window)

    def close_window(self):
        from docking_universal.models import JobStatus
        state = self.store.load('failed-control')
        for job in state.jobs:
            if job.status == JobStatus.RUNNING:
                job.status = JobStatus.CANCELLED
        self.store.save(state)
        self.window.close()

    def test_failed_control_exposes_review_while_retained_setup_stays_locked(self):
        original = self.store.path_for('failed-control').read_bytes()
        button = self.window.study_setup_panel.review_failed_button
        self.assertFalse(button.isHidden())
        self.assertTrue(button.isEnabled())
        self.assertFalse(self.window.input_pdb.isEnabled())
        self.assertEqual(self.window.study_pathway.currentData(), 'control')
        self.assertTrue(self.window.protocol_finalization_panel.review_model_button.isHidden())
        self.assertEqual(self.store.path_for('failed-control').read_bytes(), original)
        self.host.request.assert_not_called()

    def test_running_pending_completed_or_protocol_locked_study_cannot_use_recovery(self):
        from docking_universal.decisions import DecisionOption, DecisionRequired
        from docking_universal.models import ArtifactRecord, Job, JobStatus
        def reset():
            state = self.store.load('failed-control')
            state.jobs = [Job('failed-prep', 'preparation_and_pocket_detection', JobStatus.FAILED)]
            state.decisions = []
            state.artifacts = []
            self.store.save(state)
        state = self.store.load('failed-control')
        state.jobs.append(Job('active', 'control_validation', JobStatus.RUNNING))
        self.store.save(state); self.window.refresh()
        self.assertFalse(self.window.study_setup_panel.review_failed_button.isEnabled())
        reset()
        state = self.store.load('failed-control')
        state.decisions.append(DecisionRequired('d', 'review', 'Review?', 'Detected', 'Stopped', (),
            (DecisionOption('stop', 'Stop', 'Keep stopped'),)))
        self.store.save(state); self.window.refresh()
        self.assertFalse(self.window.study_setup_panel.review_failed_button.isEnabled())
        reset()
        state = self.store.load('failed-control')
        state.jobs[0].status = JobStatus.COMPLETED
        self.store.save(state); self.window.refresh()
        self.assertTrue(self.window.study_setup_panel.review_failed_button.isHidden())
        reset()
        state = self.store.load('failed-control')
        state.artifacts.append(ArtifactRecord('locked', 'protocol_bundle', '/retained/protocol.duprotocol'))
        self.store.save(state); self.window.refresh()
        self.assertTrue(self.window.study_setup_panel.review_failed_button.isHidden())

    def test_unsupported_windows_host_does_not_offer_failed_recovery(self):
        from docking_universal.windows_desktop import CAPABILITIES
        self.host.runtime = dict(CAPABILITIES)
        self.window._apply_runtime_capabilities()
        self.window.refresh()
        self.assertTrue(self.window.study_setup_panel.review_failed_button.isHidden())

    def test_cancel_only_inspects_and_explicit_approval_forwards_exact_choices(self):
        preview = {'residue_inventory': [], 'box_review_pending': True, 'review_stage': 'failed_preparation'}
        original = self.store.path_for('failed-control').read_bytes()
        choices = {'exclusions': [dict(resname='NAG', chain='B', number='607', insertion_code='')],
                   'alternate_locations': [], 'preparation_backend': 'adfr'}
        with patch.object(self.window.host_controller, 'preview_receptor_changes', return_value=preview) as inspect, \
             patch.object(self.window.host_controller, 'prepare_receptor_changes') as prepare, \
             patch('docking_universal.gui.receptor_model_review.ReceptorModelReviewDialog') as dialog:
            dialog.return_value.exec.return_value = QtWidgets.QDialog.DialogCode.Rejected
            self.window.study_setup_panel.review_failed_button.click()
            inspect.assert_called_once_with({'exclusions': [], 'alternate_locations': []}, self.window.state.revision)
            prepare.assert_not_called()
            self.assertEqual(dialog.call_args.args[0]['available_preparation_backends'], ['meeko', 'adfr'])
            dialog.return_value.exec.return_value = QtWidgets.QDialog.DialogCode.Accepted
            dialog.return_value.approved_change.return_value = (choices, 'b' * 64, 'Exact fixture review')
            self.window.study_setup_panel.review_failed_button.click()
            prepare.assert_called_once_with(choices, 'b' * 64, 'Exact fixture review', self.window.state.revision)
        self.assertEqual(self.store.path_for('failed-control').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
