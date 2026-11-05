import os
import unittest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from docking_universal.gui.qt import QtWidgets
from docking_universal.gui.workflow_panels import PreparationProgressPanel, StudySetupPanel, ProtocolFinalizationPanel, ScreeningSetupPanel
from docking_universal.gui.workflow_navigation import WorkflowNavigationController

class WorkflowPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def test_explanation_link_is_keyboard_accessible_read_only_and_literal(self):
        from PyQt6.QtTest import QTest
        from docking_universal.gui.qt import QtCore
        from docking_universal.gui.explanations import ExplanationLabel
        summary = 'Source <ligand> & receptor'
        detail = 'Deposited <img src="file:///missing"> is literal data.\n\n' + '\n'.join(
            f'Observation {i}' for i in range(100))
        note = ExplanationLabel(summary, 'Source evidence', detail)
        self.addCleanup(note.close)
        note.resize(500, 70)
        note.show()
        note.setFocus()
        self.app.processEvents()
        QTest.keyClick(note, QtCore.Qt.Key.Key_Return)
        guide = note.explanation_window
        self.assertIsNotNone(guide)
        self.addCleanup(guide.close)
        self.assertTrue(guide.isVisible())
        self.assertFalse(guide.isModal())
        self.assertTrue(guide.content.isReadOnly())
        self.assertFalse(guide.content.openExternalLinks())
        self.assertIn('<img src="file:///missing">', guide.content.toPlainText())
        self.app.processEvents()
        scroll = guide.content.verticalScrollBar()
        scroll.setValue(scroll.maximum() // 2)
        position = scroll.value()
        note.set_content(summary, detail)
        self.assertEqual(scroll.value(), position)
        guide.close()
        note.set_content('Updated source', 'Current source details')
        QTest.mouseClick(note, QtCore.Qt.MouseButton.LeftButton,
            pos=QtCore.QPoint(note.fontMetrics().horizontalAdvance('Updated source ') + 12, note.height() // 2))
        self.assertIs(note.explanation_window, guide)
        self.assertTrue(guide.isVisible())
        self.assertIn('Current source details', guide.content.toPlainText())
        self.assertNotIn('Observation', guide.content.toPlainText())

    def test_deposited_details_remain_readable_for_locked_and_changed_inputs(self):
        panel = StudySetupPanel()
        self.addCleanup(panel.close)
        panel.output_directory.setText('/study')
        panel.set_coordinate_evidence({'source_format': 'mmcif',
            'assemblies': [{'id': '1', 'oligomeric_details': 'dimeric'}]})
        before = panel.values()
        panel.deposited_evidence_details.click()
        guide = panel._deposited_evidence_window
        self.addCleanup(guide.close)
        self.assertIn('dimeric', guide.content.toPlainText())
        self.assertFalse(guide.isModal())
        panel.set_locked(True)
        buttons = guide.findChild(QtWidgets.QDialogButtonBox)
        self.assertTrue(buttons.button(QtWidgets.QDialogButtonBox.StandardButton.Close).isEnabled())
        self.assertEqual(panel.values(), before)
        panel.site_guidance_note.show_explanation()
        self.assertTrue(panel.site_guidance_note.explanation_window.isVisible())
        panel.site_guidance_note.explanation_window.close()
        panel.set_coordinate_evidence({'source_format': 'mmcif',
            'assemblies': [{'id': '2', 'oligomeric_details': 'tetrameric'}]})
        self.assertIn('tetrameric', guide.content.toPlainText())
        self.assertNotIn('dimeric', guide.content.toPlainText())
        panel.set_coordinate_evidence(None)
        self.assertFalse(guide.isVisible())

    def test_duplicate_bound_selector_stays_hidden_for_all_setup_modes(self):
        panel = StudySetupPanel()
        self.addCleanup(panel.close)
        row = panel.ligand_resname.parentWidget()
        identity = dict(resname='ID8', chain_id='B', residue_number='602', insertion_code='', altloc='')
        panel.ligand_resname.addItem('ID8 B:602', identity)
        panel.ligand_resname.setCurrentIndex(0)
        for mode in ('pockets', 'ligand'):
            panel.site_mode.setCurrentIndex(panel.site_mode.findData(mode))
            for redock in (False, True):
                panel.redock_ligand.setChecked(redock)
                self.assertFalse(panel._form.isRowVisible(row))
                self.assertTrue(panel.detect_ligands_button.isHidden() or row.isHidden())
                self.assertEqual(panel.values().ligand_identity, identity)
        panel.set_locked(True)
        self.assertFalse(panel._form.isRowVisible(row))
        self.assertEqual(panel.values().ligand_identity, identity)

    def test_loaded_evidence_button_stays_in_its_row_after_show_and_resize(self):
        panel = StudySetupPanel()
        self.addCleanup(panel.close)
        panel.resize(1000, 1200)
        panel.show()
        self.app.processEvents()
        record = {"source_format": "mmcif", "assemblies": [{"id": "1", "oligomeric_details": "dimeric"}]}
        for width in (1000, 700, 1200):
            with self.subTest(width=width):
                panel.set_coordinate_evidence(record)
                panel.resize(width, 1200)
                self.app.processEvents()
                button = panel.deposited_evidence_details
                self.assertTrue(button.isVisible())
                self.assertTrue(button.isEnabled())
                self.assertGreater(button.height(), 0)
                self.assertLessEqual(button.height(), button.sizeHint().height() + 4)
                self.assertGreater(button.y(), panel.deposited_evidence.geometry().bottom())
                self.assertLess(button.geometry().bottom(), panel.study_source.y())
                self.assertTrue(panel.rect().contains(button.geometry()))
                panel.set_coordinate_evidence(None)
                self.app.processEvents()
                self.assertFalse(button.isVisible())

    def test_evidence_loaded_during_protocol_reuse_stays_hidden_until_structure_setup(self):
        panel = StudySetupPanel()
        self.addCleanup(panel.close)
        panel.resize(1000, 1200)
        panel.show()
        panel.study_source.setCurrentIndex(panel.study_source.findData("reuse"))
        panel.set_coordinate_evidence({"source_format": "mmcif"})
        self.app.processEvents()
        self.assertFalse(panel.deposited_evidence_details.isVisible())
        panel.study_source.setCurrentIndex(panel.study_source.findData("structure"))
        self.app.processEvents()
        button = panel.deposited_evidence_details
        self.assertTrue(button.isVisible())
        self.assertGreater(button.y(), panel.deposited_evidence.geometry().bottom())
        self.assertLess(button.geometry().bottom(), panel.study_source.y())

    def test_native_quickvina_worker_limit_is_visible_without_changing_engine_identity(self):
        from docking_universal.gui.workflow_panels import _quickvina_label
        from unittest.mock import patch
        with patch('docking_universal.gui.workflow_panels.sys.platform', 'win32'):
            self.assertIn('1 CPU worker', _quickvina_label())
        with patch('docking_universal.gui.workflow_panels.sys.platform', 'darwin'):
            self.assertEqual(_quickvina_label(), 'QuickVina-W')
        setup, finalization = StudySetupPanel(), ProtocolFinalizationPanel()
        for combo in (setup.control_engine, finalization.engine):
            self.assertEqual(combo.itemText(combo.findData('qvinaw')), _quickvina_label())
        setup.close(); finalization.close()

    def test_quickvina_cpu_explanation_does_not_rewrite_an_explicit_selection(self):
        from unittest.mock import patch
        panel = ScreeningSetupPanel()
        panel.cpu.setCurrentIndex(panel.cpu.findData('automatic'))
        with patch('docking_universal.gui.workflow_panels.sys.platform', 'win32'):
            panel.set_engine('qvinaw')
            self.assertIn('1 worker', panel.inline_explanations['cpu'].text())
            panel.inline_explanations['cpu'].show_explanation()
            guide = panel.inline_explanations['cpu'].explanation_window
            self.assertIn('heap-corruption', guide.content.toPlainText())
            self.assertEqual(panel.cpu_override(), 0)
            panel.set_engine('vina')
            self.assertEqual(panel.inline_explanations['cpu'].details_text, panel.cpu.toolTip())
            self.assertIn('8 threads', guide.content.toPlainText())
            self.assertNotIn('heap-corruption', guide.content.toPlainText())
            guide.close()
        panel.close()

    def test_control_reproducibility_notice_is_shown_at_the_control_engine_choice(self):
        panel = StudySetupPanel()
        initial = panel.pathway.currentIndex()
        panel.pathway.setCurrentIndex(panel.pathway.findData('control'))
        self.assertTrue(panel._form.isRowVisible(panel.reproducibility_notice))
        self.assertIn('same seed', panel.reproducibility_notice.text())
        panel.reproducibility_notice.show_explanation()
        self.assertIn('API/CLI backends', panel.reproducibility_notice.explanation_window.content.toPlainText())
        panel.reproducibility_notice.explanation_window.close()
        self.assertTrue(panel.reproducibility_notice.wordWrap())
        panel.pathway.setCurrentIndex(initial)
        self.assertFalse(panel._form.isRowVisible(panel.reproducibility_notice))
        panel.close()

    def test_site_review_and_parameterization_are_separate_explicit_actions(self):
        panel = StudySetupPanel()
        panel._coordinate_review_supported = True
        panel._update_mode()
        self.assertEqual(panel.prepare_button.text(), 'Find and review docking regions')
        final = ProtocolFinalizationPanel()
        self.assertTrue(final.prepare_reviewed_button.isHidden())
        observed = []
        final.prepareReviewedRequested.connect(lambda: observed.append(True))
        final.prepare_reviewed_button.click()
        self.assertEqual(observed, [True])
        self.assertIn('never authorizes omission', final.prepare_reviewed_button.toolTip())

    def test_import_warning_is_plain_readable_text_not_a_dictionary_dump(self):
        from docking_universal.gui.workflow_panels import ProtocolImportDialog
        dialog = ProtocolImportDialog({'target': 'Example', 'protocol_type': 'site-guided-exploratory',
            'region_count': 1, 'exploratory_authorization_required': True, 'engine': 'vina',
            'parameters': {}, 'verified_files': 4,
            'receptor_modification_warning': {'severity': 'high', 'summary': 'User <edited> receptor; review the retained changes.',
                                              'prepared_hash': 'not reader-facing data'}})
        warning = dialog.findChild(QtWidgets.QPlainTextEdit, 'protocol_model_change_warning')
        self.assertTrue(warning.isReadOnly())
        self.assertIn('High-severity', warning.toPlainText())
        self.assertIn('User <edited> receptor', warning.toPlainText())
        self.assertNotIn('prepared_hash', warning.toPlainText())
        self.assertNotIn("{'", warning.toPlainText())
        dialog.close()

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
        self.assertIn("exploratory", panel.redock_note.text().lower())
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
        panel.site_guidance_note.show_explanation()
        guidance = panel.site_guidance_note.explanation_window.content.toPlainText()
        self.assertIn("elsewhere", guidance)
        self.assertIn("other structures", guidance)
        panel.site_guidance_note.explanation_window.close()
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

    def test_finalization_summarizes_settings_with_full_guidance_without_changing_defaults(self):
        from docking_universal.gui.protocol_help import SETTINGS_HELP
        from docking_universal.protocol_finalization import FinalizationSettings
        panel = ProtocolFinalizationPanel()
        defaults = FinalizationSettings()
        self.assertEqual(set(panel.inline_explanations), set(SETTINGS_HELP))
        self.assertEqual(set(panel.help_buttons), set(SETTINGS_HELP))
        self.assertIn('does not dock ligands now', panel.introduction.text())
        self.assertIn('starting shapes', panel.inline_explanations['conformers'].text())
        self.assertIn('chemical state', panel.inline_explanations['ph'].text())
        self.assertIn('not clusters', panel.inline_explanations['modes'].text())
        panel.show_settings_guide()
        self.assertIn('vacuum', panel._guide_text.toPlainText())
        self.assertIn('−7 kcal/mol', panel._guide_text.toPlainText())
        panel._settings_guide.close()
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
        self.assertEqual(panel.cluster_preset.currentText(), 'Loose (2.0 Å)')
        panel.close()

    def test_clustering_presets_map_to_numbers_without_launch_or_approval(self):
        panel = ScreeningSetupPanel()
        changed, launched, approved = [], [], []
        panel.inputsChanged.connect(lambda: changed.append(True))
        panel.runRequested.connect(lambda: launched.append(True))
        panel.approvalChanged.connect(lambda: approved.append(True))
        self.assertEqual(panel.cluster_preset.currentText(), 'Default (1.5 Å)')
        for index, value in ((0, 1.0), (2, 2.0), (1, 1.5)):
            panel.cluster_preset.setCurrentIndex(index)
            self.assertEqual(panel.cluster_rmsd.value(), value)
        self.assertTrue(changed)
        self.assertFalse(launched or approved)
        self.assertFalse(panel.approval.isChecked())
        self.assertIn('operating systems', panel.reproducibility_notice.text())
        self.assertIn('same seed', panel.reproducibility_notice.text())
        self.assertTrue(panel.reproducibility_notice.wordWrap())
        self.assertIn('does not regroup completed results', panel.cluster_preset.toolTip())
        panel.close()

    def test_custom_clustering_preserves_number_and_numeric_restore_updates_category(self):
        panel = ScreeningSetupPanel()
        panel.cluster_preset.setCurrentIndex(3)
        self.assertEqual(panel.cluster_rmsd.value(), 1.5)
        for value in (0.1, 1.25, 2.75, 20.0):
            panel.cluster_rmsd.setValue(value)
            self.assertEqual(panel.cluster_preset.currentIndex(), 3)
            self.assertEqual(panel.cluster_rmsd.value(), value)
        for value, index in ((1.0, 0), (1.5, 1), (2.0, 2)):
            panel.cluster_rmsd.setValue(value)
            self.assertEqual(panel.cluster_preset.currentIndex(), index)
        panel.close()

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
            self.assertEqual(getattr(panel, key).accessibleDescription(), note.details_text)
            note.show_explanation()
            self.assertFalse(note.explanation_window.isModal())
            self.assertIn(note.details_text, note.explanation_window.content.toPlainText())
            note.explanation_window.close()
        self.assertIn('per compound', panel.inline_explanations['representatives'].text())
        self.assertIn('Lowest-energy pose', panel.inline_explanations['representatives'].text())
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
        self.assertIn('pause for review', panel.operations.text())
        panel.operations.show_explanation()
        self.assertIn("selected pocket detector", panel.operations.explanation_window.content.toPlainText())
        panel.operations.explanation_window.close()
        self.assertTrue(panel.summary.isReadOnly())

    def test_navigation_controller_owns_visibility_only(self):
        a, b = QtWidgets.QDockWidget(), QtWidgets.QDockWidget(); controller=WorkflowNavigationController({"a":a,"b":b})
        controller.activate("b"); self.assertFalse(a.isVisible()); self.assertTrue(b.isVisible())
        controller.activate("central"); self.assertFalse(a.isVisible()); self.assertFalse(b.isVisible())

if __name__ == "__main__": unittest.main()
