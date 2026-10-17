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

    def test_analysis_checkboxes_are_independent_and_do_not_list_combinations(self):
        panel = StudySetupPanel()
        self.assertTrue(panel.pathway.isHidden())
        self.assertEqual(panel.study_source.count(), 2)
        self.assertFalse(panel.redock_ligand.isChecked())
        self.assertIn("recommended", panel.redock_ligand.text())
        panel.redock_ligand.setChecked(True)
        self.assertEqual(panel.values().pathway, "control")
        self.assertEqual(panel.values().site_mode, "ligand")
        panel.predict_with_ligand.setChecked(True)
        panel.pdb_evidence.setChecked(False)
        self.assertTrue(panel.redock_ligand.isChecked())
        panel.redock_ligand.setChecked(False)
        self.assertEqual(panel.values().pathway, "exploratory")
        self.assertEqual(panel.values().site_mode, "ligand")
        self.assertTrue(panel.values().predict_pockets_with_ligand)
        self.assertEqual(panel.values().pdb_pocket_evidence, "off")
        self.assertIn("exploratory", panel.redock_note.text())
        panel.study_source.setCurrentIndex(panel.study_source.findData("reuse"))
        self.assertEqual(panel.values().pathway, "reuse")
        self.assertTrue(panel.redock_ligand.isHidden())
        panel.study_source.setCurrentIndex(panel.study_source.findData("structure"))
        self.assertEqual(panel.values().pathway, "exploratory")
        self.assertTrue(panel.predict_with_ligand.isChecked())
        self.assertFalse(panel.pdb_evidence.isChecked())
        panel.set_locked(True)
        self.assertFalse(panel.redock_ligand.isEnabled())
        self.assertFalse(panel.study_source.isEnabled())
        panel.close()

    def test_initial_site_guidance_does_not_imply_a_final_single_location(self):
        panel = StudySetupPanel()
        self.assertEqual(panel._form.labelForField(panel.site_mode).text(), "Starting point for site review")
        self.assertIn("one or more", panel.site_guidance_note.text())
        self.assertIn("elsewhere", panel.site_guidance_note.text())
        self.assertIn("other structures", panel.site_guidance_note.text())
        self.assertFalse(panel.site_guidance_note.isHidden())
        panel.redock_ligand.setChecked(True)
        self.assertFalse(panel.site_guidance_note.isHidden())
        panel.study_source.setCurrentIndex(panel.study_source.findData("reuse"))
        self.assertTrue(panel.site_guidance_note.isHidden())
        panel.close()

    def test_bound_site_prediction_is_optional_local_and_available_for_controls(self):
        panel = StudySetupPanel()
        panel.site_mode.setCurrentIndex(panel.site_mode.findData("ligand"))
        self.assertFalse(panel.predict_with_ligand.isHidden())
        self.assertFalse(panel.predict_with_ligand.isChecked())
        self.assertEqual(panel.predict_with_ligand.text(), "Also run P2Rank to look for other pockets? (recommended)")
        self.assertIn("recommended when available", panel.pathway.itemText(panel.pathway.findData("control")))
        self.assertIn("recommended", panel.pdb_evidence.text())
        self.assertEqual(panel.pathway.currentData(), "exploratory")
        self.assertTrue(panel.pdb_evidence.isChecked())
        self.assertIn("selectable boxes", panel.predict_with_ligand.toolTip())
        self.assertTrue(panel.pocket_engine.isHidden())
        panel.predict_with_ligand.setChecked(True)
        panel.pdb_evidence.setChecked(False)
        self.assertTrue(panel.pocket_engine.isEnabled())
        self.assertEqual(panel.values().pocket_engine, "p2rank")
        self.assertTrue(panel.values().predict_pockets_with_ligand)
        panel.pocket_engine.setCurrentIndex(panel.pocket_engine.findData("fpocket"))
        self.assertEqual(panel.predict_with_ligand.text(), "Also run fpocket to look for other pockets? (optional fallback)")
        panel.pocket_engine.setCurrentIndex(panel.pocket_engine.findData("p2rank"))
        self.assertEqual(panel.values().pdb_pocket_evidence, "off")
        panel.pathway.setCurrentIndex(panel.pathway.findData("control"))
        self.assertTrue(panel.pocket_engine.isEnabled())
        self.assertFalse(panel.predict_with_ligand.isHidden())
        for enabled in (False, True):
            panel.predict_with_ligand.setChecked(enabled)
            self.assertEqual(panel.values().pathway, "control")
            self.assertEqual(panel.values().site_mode, "ligand")
            self.assertEqual(panel.values().pdb_pocket_evidence, "off")
        panel.set_locked(True)
        self.assertFalse(panel.predict_with_ligand.isEnabled())
        self.assertTrue(panel.predict_with_ligand.isChecked())
        panel.set_locked(False)
        panel.pathway.setCurrentIndex(panel.pathway.findData("reuse"))
        self.assertTrue(panel.predict_with_ligand.isHidden())
        panel.close()

    def test_ad4_has_distinct_fields_and_an_offline_non_authoritative_learning_guide(self):
        from unittest.mock import patch
        with patch('docking_universal.ad4_gpu.available', return_value=True):
            panel = ProtocolFinalizationPanel()
        self.assertEqual(panel.engine.currentData(), 'vina')
        panel.engine.setCurrentIndex(panel.engine.findData('adgpu'))
        self.assertFalse(panel.ad4_runs.isHidden())
        self.assertTrue(panel.exhaustiveness.isHidden())
        self.assertTrue(panel.modes.isHidden())
        self.assertTrue(panel.energy_range.isHidden())
        self.assertIn('not GPU Vina', panel.inline_explanations['engine'].text().replace('—', ' '))
        panel.show_settings_guide('engine')
        self.app.processEvents()
        text = panel._guide_text.toPlainText()
        for phrase in ('not simply', 'desolvation', 'not evidence of stronger', 'Windows',
                       'Linux', 'one-work-item', 'experimental', 'offline', 'ADADELTA'):
            self.assertIn(phrase, text)
        self.assertFalse(panel.approval.isChecked())
        self.assertFalse(panel._settings_guide.isModal())
        panel._settings_guide.close(); panel.close()

    def test_ad4_disables_cpu_tuning_without_overwriting_saved_cpu_choice(self):
        panel = ScreeningSetupPanel()
        panel.cpu.setCurrentIndex(panel.cpu.findData('custom'))
        panel.cpu_count.setValue(12)
        panel.set_engine('adgpu')
        self.assertFalse(panel.cpu.isEnabled())
        self.assertIsNone(panel.cpu_override())
        self.assertIn('not applied', panel.inline_explanations['cpu'].text())
        panel.set_engine('vina')
        self.assertTrue(panel.cpu.isEnabled())
        self.assertEqual(panel.cpu_override(), 12)
        panel.close()

    def test_finalization_explains_every_setting_inline_without_changing_defaults(self):
        from docking_universal.gui.protocol_help import SETTINGS_HELP
        from docking_universal.protocol_finalization import FinalizationSettings
        panel = ProtocolFinalizationPanel()
        defaults = FinalizationSettings()
        self.assertEqual(set(panel.inline_explanations), set(SETTINGS_HELP))
        self.assertEqual(set(panel.help_buttons), set(SETTINGS_HELP))
        self.assertIn('does not dock ligands now', panel.introduction.text())
        self.assertIn('vacuum', panel.inline_explanations['conformers'].text())
        self.assertIn('chemical state', panel.inline_explanations['ph'].text())
        self.assertIn('not clusters', panel.inline_explanations['modes'].text())
        self.assertIn('−7 kcal/mol', panel.inline_explanations['energy_range'].text())
        self.assertEqual(panel.engine.currentData(), defaults.engine)
        for name, setting in (('ph', 'ph'), ('conformers', 'conformers'), ('seeds', 'seed_count'),
                              ('base_seed', 'base_seed'), ('exhaustiveness', 'exhaustiveness'),
                              ('modes', 'num_modes'), ('energy_range', 'energy_range')):
            self.assertEqual(getattr(panel, name).value(), getattr(defaults, setting))
            self.assertTrue(getattr(panel, name).toolTip())
        self.assertFalse(panel.approval.isChecked())
        self.assertIn('up to 15 docking runs', panel.workload_hint.text())
        panel.conformers.setValue(4)
        panel.seeds.setValue(2)
        panel.modes.setValue(9)
        self.assertIn('up to 8 docking runs', panel.workload_hint.text())
        self.assertIn('at most 9 poses', panel.workload_hint.text())
        self.assertFalse(panel.approval.isChecked())
        panel.close()

    def test_settings_guide_is_modeless_reusable_offline_and_has_no_authority(self):
        panel = ProtocolFinalizationPanel()
        finalized, approved = [], []
        panel.finalizeRequested.connect(lambda: finalized.append(True))
        panel.approvalChanged.connect(lambda: approved.append(True))
        panel.help_buttons['energy_range'].click()
        self.app.processEvents()
        guide = panel._settings_guide
        self.assertTrue(guide.isVisible())
        self.assertFalse(guide.isModal())
        text = panel._guide_text.toPlainText()
        self.assertIn('Current setting: 8.0', text)
        for term in ('chemical state', 'repeatability', 'vacuum', 'rigid', 'estimated binding energy',
                     'not an experimental affinity cutoff', 'Opening a reference link is optional'):
            self.assertIn(term, text)
        self.assertGreater(panel._guide_text.verticalScrollBar().value(), 0)
        guide.close()
        panel.seeds.setValue(7)
        panel.help_buttons['seeds'].click()
        self.assertIs(panel._settings_guide, guide)
        self.assertIn('Current setting: 7', panel._guide_text.toPlainText())
        self.assertFalse(finalized)
        self.assertFalse(approved)
        self.assertFalse(panel.approval.isChecked())
        guide.close()
        panel.close()

    def test_screening_clustering_defaults_to_one_point_five_angstrom_and_allows_override(self):
        panel = ScreeningSetupPanel()
        self.assertEqual(panel.cluster_rmsd.value(), 1.5)
        panel.cluster_rmsd.setValue(2.0)
        self.assertEqual(panel.cluster_rmsd.value(), 2.0)

    def test_screening_cpu_default_automatic_custom_and_return_do_not_launch(self):
        panel = ScreeningSetupPanel()
        changed, launched = [], []
        panel.inputsChanged.connect(lambda: changed.append(True))
        panel.runRequested.connect(lambda: launched.append(True))
        self.assertEqual(panel.cpu.currentData(), 'default')
        self.assertIsNone(panel.cpu_override())
        self.assertEqual(panel.cpu_count.value(), 8)
        self.assertTrue(panel.cpu_count.isHidden())
        for term in ('8 threads', 'Automatic', 'Custom', 'More threads can be slower', 'search effort'):
            self.assertIn(term, panel.cpu.toolTip())
        panel.cpu.setCurrentIndex(panel.cpu.findData('automatic'))
        self.assertEqual(panel.cpu_override(), 0)
        self.assertTrue(panel.cpu_count.isHidden())
        panel.cpu.setCurrentIndex(panel.cpu.findData('custom'))
        self.assertFalse(panel.cpu_count.isHidden())
        panel.cpu_count.setValue(12)
        self.assertEqual(panel.cpu_override(), 12)
        panel.cpu.setCurrentIndex(panel.cpu.findData('default'))
        self.assertIsNone(panel.cpu_override())
        self.assertTrue(changed)
        self.assertFalse(launched)
        self.assertFalse(panel.approval.isChecked())
        panel.close()

    def test_screening_controls_explain_groups_without_changing_inputs_or_molecule_view(self):
        panel = ScreeningSetupPanel()
        changed, approved, launched = [], [], []
        panel.inputsChanged.connect(lambda: changed.append(True))
        panel.approvalChanged.connect(lambda: approved.append(True))
        panel.runRequested.connect(lambda: launched.append(True))
        self.assertEqual(set(panel.inline_explanations),
                         {'output', 'analysis', 'cpu', 'representatives', 'cluster_rmsd', 'stop_on_error', 'approval'})
        for key, note in panel.inline_explanations.items():
            self.assertTrue(note.wordWrap())
            self.assertFalse(note.isHidden())
            self.assertEqual(getattr(panel, key).accessibleDescription(), note.text())
        self.assertIn('per compound', panel.inline_explanations['representatives'].text())
        self.assertIn('lowest-energy pose', panel.inline_explanations['representatives'].text())
        self.assertIn('not a compound or total-pose limit', panel.representatives.toolTip())
        for term in ('heavy-atom', 'without realignment', 'not RMSD to an experimental pose'):
            self.assertIn(term, panel.cluster_rmsd.toolTip())
        self.assertEqual(panel.representatives.value(), 3)
        self.assertEqual(panel.cluster_rmsd.value(), 1.5)
        self.assertEqual(panel.analysis.currentData(), 'representatives')
        self.assertFalse(panel.stop_on_error.isChecked())
        self.assertFalse(panel.approval.isChecked())
        self.assertEqual(panel.library_panel.preview.minimumWidth(), 220)
        self.assertFalse(changed or approved or launched)
        panel.close()

    def test_pdb_evidence_option_discloses_internet_and_supports_local_only(self):
        panel = StudySetupPanel()
        self.assertIn('internet required', panel.pdb_evidence.text())
        self.assertIn('protein sequence', panel.pdb_evidence_note.text())
        self.assertEqual(panel.values().pdb_pocket_evidence, 'related-structures')
        panel.pdb_evidence.setChecked(False)
        self.assertEqual(panel.values().pdb_pocket_evidence, 'off')
        self.assertIn('Local-only evidence', panel.pdb_evidence_note.text())
        self.assertIn('downloads are separate', panel.pdb_evidence.toolTip())
        panel.pathway.setCurrentIndex(panel.pathway.findData('control'))
        self.assertFalse(panel.pdb_evidence_note.isHidden())
        self.assertTrue(panel.pdb_evidence.isEnabled())
        self.assertEqual(panel.values().pdb_pocket_evidence, 'off')
        self.assertIn('review sites', panel.prepare_button.text().lower())
        panel.pdb_evidence.setChecked(True)
        self.assertEqual(panel.values().pdb_pocket_evidence, 'related-structures')

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
