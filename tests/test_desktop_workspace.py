import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from docking_universal.application import StudyController
from docking_universal.decisions import DecisionOption, DecisionRequired
from docking_universal.gui.desktop import QT_IMPORT_ERROR, StudyWindow, _failure_summary
from docking_universal.models import ArtifactRecord, Job, JobStatus, PocketCandidate
from docking_universal.state import JsonStudyStore


@unittest.skipIf(QT_IMPORT_ERROR is not None, "selected Qt 6 binding is unavailable")
class DesktopWorkspaceTests(unittest.TestCase):
    def test_cluster_plip_batch_reuses_saved_representatives(self):
        from types import SimpleNamespace
        from docking_universal.gui.qt import QtWidgets
        from unittest.mock import Mock
        button, status, progress = QtWidgets.QPushButton(), QtWidgets.QLabel(), QtWidgets.QProgressBar()
        root = self.root / 'analysis'
        poses = [(root, SimpleNamespace(cluster_id=1, pose_id=2, energy_kcal_per_mol=-2.0)),
                 (root, SimpleNamespace(cluster_id=1, pose_id=3, energy_kcal_per_mol=-3.0)),
                 (root, SimpleNamespace(cluster_id=2, pose_id=4, energy_kcal_per_mol=-1.0))]
        saved_path = self.root / 'saved.png'
        saved_path.write_bytes(b'saved')
        saved = [SimpleNamespace(analysis_root=root, cluster_id=1, pose_id=3, diagram=saved_path),
                 SimpleNamespace(analysis_root=root, cluster_id=2, pose_id=4, diagram=saved_path)]
        with patch.object(self.window, 'batch_plip_main', button, create=True), \
             patch.object(self.window, 'batch_plip_status', status, create=True), \
             patch.object(self.window, 'batch_plip_progress', progress, create=True), \
             patch.object(self.window, '_selected_screening_compound', return_value=self.root), \
             patch.object(self.window, 'host_controller', SimpleNamespace(available=True)), \
             patch.object(self.window.results_model, 'poses', return_value=poses), \
             patch.object(self.window.results_model, 'cluster_interactions', return_value=saved):
            self.window._toggle_cluster_plip_batch()
        self.assertIn('2 of 2 processed', status.text())
        self.assertIn('0 remaining', status.text())
        self.assertEqual(progress.value(), 2)
        self.assertIn('finished', status.text())

    def test_cluster_plip_batch_reports_disconnect_without_claiming_completion(self):
        from types import SimpleNamespace
        from docking_universal.gui.qt import QtWidgets
        button, status, progress = QtWidgets.QPushButton(), QtWidgets.QLabel(), QtWidgets.QProgressBar()
        batch = {'queue': [], 'total': 3, 'done': 1, 'failed': 0, 'job': 'active',
                 'current': (self.root, 5, 2), 'starting': False, 'stopped': True}
        with patch.object(self.window, 'batch_plip_main', button, create=True), \
             patch.object(self.window, 'batch_plip_status', status, create=True), \
             patch.object(self.window, 'batch_plip_progress', progress, create=True), \
             patch.object(self.window, 'host_controller', SimpleNamespace(available=False)), \
             patch.object(self.window, '_cluster_plip_batch', batch, create=True):
            self.window._advance_cluster_plip_batch()
            self.assertIsNone(self.window._cluster_plip_batch)
        self.assertIn('2 remaining', status.text())
        self.assertIn('current calculation status unknown', status.text())

    def test_screening_report_follows_selected_compound_run(self):
        first, second = self.root / 'run1', self.root / 'run2'
        for root in (first, second):
            (root / 'report').mkdir(parents=True)
            (root / 'report' / 'result.pdf').write_bytes(b'pdf')
            self.window.state.artifacts.append(ArtifactRecord(root.name, 'screening_report', str(root / 'report' / 'result.pdf')))
        compound = second / 'compounds' / 'ligand'
        actions = self.window.open_screen_report_button.menu().actions()
        with patch.object(self.window, '_selected_screening_compound', return_value=compound), \
             patch.object(self.window, '_open_path') as opened:
            actions[0].trigger()
        opened.assert_called_once_with(second / 'report' / 'result.pdf')
        with patch.object(self.window, '_selected_screening_compound', return_value=compound), \
             patch.object(self.window, '_open_or_export_report') as export:
            actions[2].trigger()
        export.assert_called_once_with(second / 'report' / 'result.pdf', 'high-resolution')

    def test_dock_more_opens_screening_with_unused_output_folder(self):
        existing = self.root / 'screen'
        existing.mkdir()
        (self.root / 'screen_2').mkdir()
        self.window.screen_output.setText(str(existing))
        self.window.screening_setup_panel.another_run_button.setEnabled(True)
        self.window.screening_setup_panel.another_run_button.click()
        self.assertEqual(self.window.screen_output.text(), str(self.root / 'screen_3'))
        self.assertIn('New run ready', self.window.screening_setup_panel.another_run_notice.text())
        self.assertIn(str(self.root / 'screen_3'), self.window.screening_setup_panel.another_run_notice.text())
        self.assertEqual(self.window._workflow_target, 'locked_protocol_screening_dock')
        self.assertTrue(existing.is_dir())

    def test_hidden_2d_displays_pose_without_starting_plip(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.qt import QtWidgets
        toggle = QtWidgets.QCheckBox()
        toggle.setChecked(False)
        adapter = SimpleNamespace(show_multiple_review_poses=Mock())
        analysis = self.root / 'analysis'
        host = SimpleNamespace(available=True, start_pose_interaction=Mock())
        with patch.object(self.window, 'show_2d_interactions', toggle, create=True), \
             patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter, connected=True)), \
             patch.object(self.window, 'host_controller', host), \
             patch.object(self.window.results_model, 'cached_pose_diagram', return_value=None):
            self.window._request_pose_interaction(analysis, 42, 1, '-8', False)
        adapter.show_multiple_review_poses.assert_called_once_with([(analysis, 42)])
        host.start_pose_interaction.assert_not_called()
        toggle.close()

    def test_reopening_2d_requests_the_current_single_pose(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        panel = SimpleNamespace(show=Mock(), hide=Mock())
        with patch.object(self.window, 'viewer_widget', object()), \
             patch.object(self.window, 'linked_pose_panel', panel, create=True), \
             patch.object(self.window, '_cluster_comparison_selected') as select:
            self.window.pose_review_mode.setCurrentIndex(self.window.pose_review_mode.findData('clusters'))
            self.window._toggle_2d_interactions(False)
            panel.hide.assert_called_once()
            self.window._toggle_2d_interactions(True)
            select.assert_called_once()
            panel.show.assert_called_once()

    def test_reopen_restores_previously_reviewed_library(self):
        import json
        from types import SimpleNamespace
        source = self.root / 'library.sdf'
        source.write_text('retained')
        selection = {'fingerprint': 'verified', 'record_ids': ['record-1'], 'name_overrides': {'record-1': 'pyronaridine'}}
        self.window.screen_ligands.setText(str(source))
        key = self.window._form_settings_group() + '/screen/library_selection'
        self.window.settings.setValue(key, json.dumps({'source': str(source), 'selection': selection}))
        self.window._library_restore_attempted = False
        with patch.object(self.window, 'host_controller', SimpleNamespace(available=True)), \
             patch.object(self.window, 'read_screening_library') as read:
            self.window._restore_screening_library_if_needed()
            read.assert_called_once_with(column_mapping=None, restore_selection=selection)
            self.window._restore_screening_library_if_needed()
            read.assert_called_once()

    def test_refresh_does_not_reload_a_manually_read_screening_library(self):
        from types import SimpleNamespace
        source = self.root / 'library.sdf'
        source.write_text('example')
        self.window.screen_ligands.setText(str(source))
        self.window._library_restore_attempted = False
        library = {'fingerprint': 'reviewed', 'records': [{
            'record_id': 'first', 'name': 'Example', 'source_record': 1, 'source': str(source),
            'formula': 'C', 'formal_charge': 0, 'valid': True, 'error': '',
        }]}
        with patch.object(self.window, 'host_controller', SimpleNamespace(available=True)), \
             patch.object(self.window, '_read_library_async',
                          side_effect=lambda operation, callback: callback(library, None)) as read, \
             patch.object(self.window, '_update_screening_controls'):
            self.window.read_screening_library()
            self.window._restore_screening_library_if_needed()
            read.assert_called_once()
        self.assertIs(self.window.screening_setup_panel.library_panel.library, library)

    def test_older_screening_restores_only_verified_records_and_display_name(self):
        import json
        from types import SimpleNamespace
        source = self.root / 'old-library.sdf'
        source.write_text('source')
        study = self.root / 'old-screen'
        (study / 'inputs').mkdir(parents=True)
        (study / 'report').mkdir()
        manifest = study / 'compounds' / '107771' / 'screen_manifest.json'
        manifest.parent.mkdir(parents=True)
        manifest.write_text('{}')
        (study / 'inputs' / 'compound_library_inventory.json').write_text(json.dumps({'compounds': [{
            'compound_id': '107771', 'record_id': 'record1', 'source': str(source),
            'source_sha256': 'verified-hash', 'compound_name': '107771'}]}))
        (study / 'report' / 'compound_display_names.json').write_text(json.dumps({'names': {'107771': 'pyronaridine'}}))
        self.window.state.artifacts.append(ArtifactRecord('old-screen', 'screening_compound_manifest', str(manifest)))
        self.window.screen_ligands.setText(str(source))
        self.window.settings.remove(self.window._form_settings_group() + '/screen/library_selection')
        self.window._library_restore_attempted = False
        library = {'fingerprint': 'current', 'records': [{'record_id': 'record1', 'source': str(source),
            'source_sha256': 'verified-hash', 'name': '107771', 'source_record': 1,
            'formula': 'C', 'formal_charge': 0, 'valid': True, 'error': ''}]}
        with patch.object(self.window, 'host_controller', SimpleNamespace(available=True)), \
             patch.object(self.window, '_read_library_async', side_effect=lambda operation, callback: callback(library, None)), \
             patch.object(self.window, '_update_screening_controls'):
            self.assertIsNotNone(self.window._retained_screening_library(str(source)))
            self.window._restore_screening_library_if_needed()
        panel = self.window.screening_setup_panel.library_panel
        self.assertEqual(panel.selection()['record_ids'], ['record1'])
        self.assertEqual(panel.selection()['name_overrides']['record1'], 'pyronaridine')

        self.window.settings.remove(self.window._form_settings_group() + '/screen/library_selection')
        self.window._library_restore_attempted = False
        changed = {**library, 'fingerprint': 'changed', 'records': [{**library['records'][0], 'source_sha256': 'different'}]}
        with patch.object(self.window, 'host_controller', SimpleNamespace(available=True)), \
             patch.object(self.window, '_read_library_async', side_effect=lambda operation, callback: callback(changed, None)), \
             patch.object(self.window, '_update_screening_controls'):
            self.window._restore_screening_library_if_needed()
        self.assertEqual(panel.selection()['record_ids'], [])
        self.assertIn('changed since', self.window.screening_status.text())

    def test_screening_report_opens_corrected_display_copy(self):
        import json
        from unittest.mock import patch
        folder = self.root / 'screen-report'
        folder.mkdir()
        original = folder / 'original.pdf'
        corrected = folder / 'corrected.pdf'
        original.write_bytes(b'original')
        corrected.write_bytes(b'corrected')
        (folder / 'compound_display_names.json').write_text(json.dumps({'corrected_report': corrected.name}))
        self.window.state.artifacts.append(ArtifactRecord('screen-report', 'screening_report', str(original)))
        with patch.object(self.window, '_open_path') as opened:
            self.window.open_screening_report()
            opened.assert_called_once_with(corrected)

    def test_default_study_folder_timestamps_only_collisions(self):
        from datetime import datetime
        from docking_universal.gui.desktop import _available_study_folder

        now = datetime(2026, 11, 22, 15, 46, 52)
        folder = _available_study_folder(self.root, '6E2P', now)
        self.assertEqual(folder, self.root / '6E2P_2026-11-22')
        folder.mkdir()
        timestamped = _available_study_folder(self.root, '6E2P', now)
        self.assertEqual(timestamped, self.root / '6E2P_2026-11-22_154652')
        timestamped.mkdir()
        self.assertEqual(_available_study_folder(self.root, '6E2P', now).name,
                         '6E2P_2026-11-22_154652_2')

    def test_structure_id_suggests_folder_and_respects_manual_selection(self):
        from docking_universal.gui.qt import QtCore

        with patch.object(QtCore.QStandardPaths, 'writableLocation', return_value=str(self.root)):
            self.window.output_directory.clear()
            self.window.input_pdb.setText('6E2P')
            suggested = Path(self.window.output_directory.text())
            self.assertEqual(suggested.parent, self.root)
            self.assertTrue(suggested.name.startswith('6E2P_'))
            self.window.output_directory.setText(str(self.root / 'chosen'))
            self.window.input_pdb.setText('2R8N')
            self.assertEqual(self.window.output_directory.text(), str(self.root / 'chosen'))

    def test_report_button_identifies_control_and_protocol_reports(self):
        state = self.store.load('desktop')
        control = self.root / 'control.pdf'
        control.write_bytes(b'control')
        state.artifacts.append(ArtifactRecord('control', 'control_report', str(control)))
        self.store.save(state)
        self.window.refresh()
        self.assertEqual(self.window.open_final_report_button.text(), 'Open control report')
        protocol = self.root / 'protocol.pdf'
        protocol.write_bytes(b'protocol')
        state = self.store.load('desktop')
        state.artifacts.append(ArtifactRecord('protocol', 'final_report', str(protocol)))
        self.store.save(state)
        self.window.refresh()
        self.assertEqual(self.window.open_final_report_button.text(), 'Open protocol report')

    def test_control_start_keeps_interface_responsive_and_blocks_duplicate_start(self):
        import threading
        from unittest.mock import Mock
        from PyQt6.QtTest import QTest
        gate = threading.Event()
        host = Mock(available=True)
        host.start_control_validation.side_effect = lambda *args: gate.wait(3)
        self.window.protocol_finalization_panel._control_mode = True
        with patch.object(self.window, 'host_controller', host), patch.object(self.window, 'refresh'):
            try:
                self.window.start_protocol_finalization()
                self.assertTrue(self.window._starting_control)
                self.assertIn('Starting known-ligand control', self.window.feedback_heading.text())
                self.assertFalse(self.window.finalize_button.isEnabled())
                self.window.start_protocol_finalization()
                QTest.qWait(50)
                host.start_control_validation.assert_called_once()
                gate.set()
                for _ in range(40):
                    if not self.window._starting_control:
                        break
                    QTest.qWait(50)
                self.assertFalse(self.window._starting_control)
            finally:
                gate.set()

    def test_control_retry_uses_responsive_start_and_retains_retry_flag(self):
        import threading
        from unittest.mock import Mock
        from PyQt6.QtTest import QTest
        gate = threading.Event()
        host = Mock(available=True)
        host.start_control_validation.side_effect = lambda *args: gate.wait(3)
        self.window.state.jobs[-1].stage = 'control_validation'
        with patch.object(self.window, 'host_controller', host), patch.object(self.window, 'refresh'):
            try:
                self.window.retry_site_detection()
                self.assertTrue(self.window._starting_control)
                self.assertIn('Restarting known-ligand control', self.window.feedback_heading.text())
                QTest.qWait(50)
                host.start_control_validation.assert_called_once_with({'retry': True}, self.window.state.revision)
                gate.set()
                for _ in range(40):
                    if not self.window._starting_control:
                        break
                    QTest.qWait(50)
                self.assertFalse(self.window._starting_control)
            finally:
                gate.set()

    def test_verified_input_ligand_offers_2d_interactions(self):
        panel = self.window.pocket_evidence_panel
        observation = {'entry': 'Input', 'ligand': 'ID8 B:602', 'source': 'input_structure',
                       'source_ligand_id': 'input/ID8/B/602', 'aligned_ligand_pdb': '/tmp/input.pdb'}
        with patch('docking_universal.services.evidence_interactions.evidence_inputs', return_value={}):
            panel.set_candidate({'id': 'B1', 'evidence': {
                'input_ligand_evidence': {'observation_count': 1, 'observations': [observation]}}})
            panel.table.selectRow(0)
            self.assertTrue(panel.render_2d_button.isEnabled())
    def test_failed_linked_sugar_render_stops_progress_and_explains_failure(self):
        from PyQt6.QtTest import QTest
        from unittest.mock import Mock
        self.window.linked_pose_panel = Mock()
        source = self.root / 'linked.pdb'
        line = list(' ' * 80)
        line[:6] = 'LINK  '
        line[47:50] = 'NAG'
        line[51:52] = 'C'
        line[52:57] = '   2 '
        source.write_text(''.join(line) + '\n')
        cache = self.root / 'failure-cache'
        cache.mkdir()
        (cache / 'worker.log').write_text('ValueError: Deposited ligand atoms do not match CCD chemistry; interaction rendering stopped\n')
        record = {'cache': str(cache), 'source': str(source), 'entry': '5F19',
                  'ligand': 'NAG', 'chain': 'C', 'residue': '2'}
        self.window._show_evidence_render_progress(record)
        self.window._evidence_2d_finished(record, 1)
        self.assertIsNone(self.window._evidence_2d_progress)
        self.assertIsNone(self.window._evidence_2d_progress_timer)
        dialog = self.window._evidence_2d_error_dialog
        self.assertIn('covalently linked', dialog.text())
        self.assertFalse(dialog.isModal())
        QTest.qWait(1100)
        self.assertTrue(dialog.isVisible())
        dialog.accept()

    def test_site_list_divider_keeps_resized_height_on_refresh(self):
        state = self.store.load('desktop')
        self.window.state = state
        self.window.show()
        self.window.review_splitter.show()
        self.window.candidates.show()
        self.window.review_splitter.setSizes([300, 300])
        self.application.processEvents()
        before = self.window.review_splitter.sizes()
        self.window._size_candidate_table()
        self.application.processEvents()
        self.assertEqual(self.window.review_splitter.sizes(), before)
        self.assertGreater(self.window.candidates.maximumHeight(), 300)

    def test_evidence_only_site_shows_one_supporting_observation_and_fixed_controls(self):
        from unittest.mock import Mock
        state = self.store.load('desktop')
        state.workflow_data['pocket_candidates'] = [{'id': 'L1', 'label': 'L1', 'rank': 1,
            'summary': '', 'evidence': {'kind': 'ligand_defined', 'geometry': {
                'center_x': 0, 'center_y': 0, 'center_z': 0,
                'size_x': 20, 'size_y': 20, 'size_z': 20},
                'experimental_ligand_evidence': {'observation_count': 1, 'observations': [
                    {'entry': '1ABC', 'ligand': 'NAG', 'aligned_ligand_pdb': '/tmp/nag.pdb'}]}}}]
        self.window.state = state
        self.window._render_candidates(state)
        viewer = Mock(connected=True)
        with patch.object(self.window, 'viewer_coordinator', viewer), \
             patch.object(self.window, '_ensure_pocket_space'), patch.object(self.window, '_show_embedded_viewer'):
            self.window._candidate_highlight_changed()
        panel = self.window.pocket_evidence_panel
        self.assertFalse(panel.supporting_toggle.isChecked())
        self.assertEqual(panel._selected_paths(), [])
        panel.supporting_toggle.setChecked(True)
        self.assertEqual(panel.table.item(0, 0).text(), 'supporting component')
        self.assertEqual(panel.evidence_title.text(), 'Supporting components')
        self.assertIn('1 supporting component', panel.heading.text())
        self.assertTrue(self.window.pocket_evidence_actions.isAncestorOf(panel.render_2d_button))
        self.assertTrue(self.window.pocket_evidence_actions.isAncestorOf(panel.supporting_toggle))
        self.assertTrue(self.window.pocket_evidence_actions.isAncestorOf(panel.note))
        self.assertFalse(panel.isAncestorOf(panel.render_2d_button))
        self.assertFalse(panel.isAncestorOf(panel.note))
        self.assertTrue(self.window.pocket_evidence_page.isAncestorOf(self.window.pocket_graph_area))
        self.assertFalse(panel.isAncestorOf(self.window.pocket_graph_area))

    def test_detached_site_approval_uses_same_selection_and_note(self):
        from unittest.mock import Mock
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        state = self.store.load('desktop')
        self.window.state = state
        self.window._render_candidates(state)
        host = Mock(available=True)
        with patch.object(self.window, 'host_controller', host), patch.object(self.window, 'refresh'):
            panel = FullPyMOLStudyPanel(self.window)
            try:
                self.assertIn('P1', panel.approval_selection.text())
                self.assertTrue(panel.approve_regions.isEnabled())
                panel.approval_note.setText('Reviewed in full viewer')
                self.assertEqual(self.window.rationale.text(), 'Reviewed in full viewer')
                host.resolve_pockets.assert_not_called()
                panel.approve_regions.click()
                from PyQt6.QtTest import QTest
                QTest.qWait(50)
                host.resolve_pockets.assert_called_once_with(
                    state.pending_decisions[0].id, ['P1'], 'Reviewed in full viewer', state.revision)
            finally:
                panel.dispose()
                panel.close()

    def test_site_approval_keeps_ui_responsive_and_prevents_duplicate_requests(self):
        import threading
        from unittest.mock import Mock
        from PyQt6.QtTest import QTest
        state = self.store.load('desktop')
        self.window.state = state
        self.window._render_candidates(state)
        release = threading.Event()
        host = Mock(available=True)
        host.resolve_pockets.side_effect = lambda *args: release.wait(2)
        with patch.object(self.window, 'host_controller', host), patch.object(self.window, 'refresh'):
            self.window.approve_selected_regions()
            self.assertTrue(self.window._pocket_approval_pending)
            self.assertTrue(self.window._pocket_approval_progress.isVisible())
            self.window.approve_selected_regions()
            self.assertEqual(host.resolve_pockets.call_count, 1)
            release.set()
            for _ in range(30):
                QTest.qWait(20)
                if not self.window._pocket_approval_pending:
                    break
            self.assertFalse(self.window._pocket_approval_pending)

    def test_detached_site_list_selects_multiple_and_approves_exactly_those(self):
        import copy
        from unittest.mock import Mock
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.qt import QtCore
        state = self.store.load('desktop')
        second = copy.deepcopy(state.workflow_data['pocket_candidates'][0])
        second['id'] = second['label'] = 'P2'
        second['rank'] = 2
        state.workflow_data['pocket_candidates'].append(second)
        self.window.state = state
        self.window._render_candidates(state)
        viewer = Mock(connected=True)
        host = Mock(available=True)
        with patch.object(self.window, 'viewer_coordinator', viewer), patch.object(self.window, 'host_controller', host), \
             patch.object(self.window, '_ensure_pocket_space'), patch.object(self.window, 'refresh'):
            panel = FullPyMOLStudyPanel(self.window)
            try:
                self.assertTrue(panel.regions.isHidden())
                self.assertTrue(panel.tabs.tabBar().isHidden())
                panel.site_list.item(1).setSelected(True)
                self.assertEqual({item.data(QtCore.Qt.ItemDataRole.UserRole) for item in panel.site_list.selectedItems()}, {'P1', 'P2'})
                self.assertIn('P1, P2', panel.approval_selection.text())
                viewer.show_candidates.assert_called_with(state, ['P1', 'P2'])
                panel.approve_regions.click()
                from PyQt6.QtTest import QTest
                QTest.qWait(50)
                host.resolve_pockets.assert_called_once_with(state.pending_decisions[0].id, ['P1', 'P2'], '', state.revision)
                panel.site_list.item(0).setSelected(False)
                self.assertEqual([item.data(QtCore.Qt.ItemDataRole.UserRole) for item in panel.site_list.selectedItems()], ['P2'])
                viewer.show_candidate.assert_called_with(state, 'P2')
            finally:
                panel.dispose()
                panel.close()

    def test_grouped_site_displays_the_named_prediction_cavity(self):
        from unittest.mock import Mock
        state = self.store.load('desktop')
        state.workflow_data['pocket_candidates'] = [
            {'id': 'B1', 'label': 'B1', 'rank': 1, 'summary': '', 'evidence': {
                'site_group': {'representative_id': 'B1', 'members': [],
                               'member_ids': ['P2', 'P11', 'B1']}}},
            {'id': 'P3', 'label': 'P3', 'rank': 2, 'summary': '', 'evidence': {}},
        ]
        self.window.state = state
        self.window._render_candidates(state)
        adapter = Mock()
        adapter.show_pocket_space.return_value = ['du_pocket_space_2', 'du_pocket_space_11']
        self.window.viewer_coordinator = Mock(adapter=adapter)
        self.window.candidates.selectRow(0)
        self.window._apply_pocket_space({'counts': {'2': 550, '11': 154, '3': 4}})
        self.assertEqual(adapter.show_pocket_space.call_args.args[1], [2])
        self.assertIn('P2', self.window.viewer_status.text())
        self.window.candidates.selectRow(1)
        self.window._apply_pocket_space({'counts': {'2': 550, '11': 154, '3': 4}})
        self.assertEqual(adapter.show_pocket_space.call_args.args[1], [3])
        from docking_universal.gui.qt import QtCore
        selection = self.window.candidates.selectionModel()
        selection.select(self.window.candidates.model().index(0, 0),
            QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)
        self.window.viewer_coordinator.show_candidates.assert_called_with(state, ['B1', 'P3'])
        self.window._apply_pocket_space({'counts': {'2': 550, '11': 154, '3': 4}})
        self.assertEqual(adapter.show_pocket_space.call_args.args[1], [2, 3])
        self.assertEqual(set(adapter.show_pocket_space.call_args.args[2]), {2, 3})

    def test_selected_predicted_pocket_displays_only_its_own_space(self):
        from unittest.mock import Mock
        state = self.store.load('desktop')
        state.workflow_data['pocket_candidates'] = [{'id': 'P5', 'label': 'P5', 'rank': 1,
            'summary': '', 'evidence': {'site_group': {'representative_id': 'P5', 'members': [],
                                                         'member_ids': ['P5', 'P16', 'P18']}}}]
        self.window.state = state
        self.window._render_candidates(state)
        adapter = Mock()
        adapter.show_pocket_space.return_value = ['du_pocket_space_5']
        self.window.viewer_coordinator = Mock(adapter=adapter)
        self.window.candidates.selectRow(0)
        self.window._apply_pocket_space({'counts': {'5': 10, '16': 10, '18': 10}})
        self.assertEqual(adapter.show_pocket_space.call_args.args[1], [5])

    def test_compact_and_full_graph_keep_selection_and_retained_candidates(self):
        from docking_universal.gui.qt import QtCore
        from PyQt6.QtTest import QTest
        state = self.store.load('desktop')
        candidates = [{'id': f'P{i}', 'label': f'P{i}', 'rank': i, 'summary': '',
                       'evidence': {'score': 11 - i}} for i in range(1, 11)]
        candidates[7]['evidence']['experimental_ligand_evidence'] = {'observation_count': 1}
        state.workflow_data['pocket_candidates'] = candidates
        before = self.store.path_for('desktop').read_bytes()
        self.window.state = state
        self.window._render_candidates(state)
        self.assertEqual(len(self.window.pocket_score_plot.points), 5)
        self.assertEqual(len(self.window.full_pocket_score_plot.points), 10)
        self.assertIn('1 other site has possible ligand evidence', self.window.pocket_graph_summary.text())
        self.assertGreaterEqual(self.window.full_pocket_score_plot.grab().width(),
                                self.window.full_pocket_score_plot.minimumWidth())
        self.window.show_full_pocket_graph()
        self.application.processEvents()
        full = self.window.full_pocket_score_plot
        target = next(i for i, point in enumerate(full.points) if point[0] == 'P9')
        QTest.mouseClick(full, QtCore.Qt.MouseButton.LeftButton, pos=full.positions()[target].toPoint())
        self.assertEqual(self.window.pocket_score_plot.selected, 'P9')
        self.assertNotIn('P9', [p[0] for p in self.window.pocket_score_plot.points])
        self.assertEqual(self.window.show_selected_site_button.text(), 'Add selected site')
        self.assertIn('Selected: P9', self.window.pocket_graph_summary.text())
        self.window.show_selected_site_button.click()
        self.assertIn('P9', [p[0] for p in self.window.pocket_score_plot.points])
        self.assertEqual(self.window.show_selected_site_button.text(), 'Remove selected site')
        self.window._select_plotted_candidate('P1')
        self.assertIn('P9', [p[0] for p in self.window.pocket_score_plot.points])
        self.window._select_plotted_candidate('P9')
        self.assertEqual(self.window.show_selected_site_button.text(), 'Remove selected site')
        self.window.show_selected_site_button.click()
        self.assertNotIn('P9', [p[0] for p in self.window.pocket_score_plot.points])
        self.assertEqual(full.selected, 'P9')
        self.assertEqual(self.store.path_for('desktop').read_bytes(), before)
        self.window.full_pocket_graph_dialog.close()

    def test_review_transition_shows_loading_until_review_or_failure(self):
        from docking_universal.models import CompletionStatus
        state = self.store.load('desktop')
        state.jobs = [Job(id='prep', stage='preparation_and_pocket_detection', status=JobStatus.COMPLETED)]
        state.decisions = []
        state.selected_pocket_ids = []
        state.workflow_data['next_stage'] = 'pocket_review'
        state.completion_status = CompletionStatus.RUNNING
        self.window._update_workflow_progress(state)
        self.assertEqual(self.window.feedback_heading.text(), 'Preparing docking-site review')
        self.assertFalse(self.window.running_indicator.isHidden())
        self.assertIn('collecting related-structure evidence', self.window.feedback_text.text())
        state.workflow_data['pdb_pocket_evidence_progress'] = {'phase': 'checking', 'completed': 10, 'total': 100, 'entry': '1ABC'}
        self.window._update_workflow_progress(state)
        self.assertIn('10 of 100', self.window.feedback_text.text())
        self.assertFalse(self.window.stop_pdb_search_button.isHidden())
        state.completion_status = CompletionStatus.FAILED
        self.window._update_workflow_progress(state)
        self.assertTrue(self.window.running_indicator.isHidden())

    def test_progress_updates_do_not_restyle_the_running_indicator(self):
        state = self.store.load('desktop')
        state.jobs = [Job(id='prep', stage='preparation_and_pocket_detection', status=JobStatus.RUNNING)]
        self.window._update_workflow_progress(state)
        with patch.object(self.window.feedback_card, 'setStyleSheet', wraps=self.window.feedback_card.setStyleSheet) as style:
            state.jobs[0].progress_message = 'Another line of progress'
            self.window._update_workflow_progress(state)
            style.assert_not_called()

    def test_existing_failed_preparation_shows_its_own_retained_diagnosis(self):
        from types import SimpleNamespace
        log = self.root / 'preparation.stdout.log'
        log.write_text('ERROR: Receptor preparation failure category: Unsupported element\n'
                       'Detected detail: Element Co is unsupported.\n')
        artifact = SimpleNamespace(kind='job_stdout_log', path=str(log), metadata={'job_id': 'job-1'})
        state = SimpleNamespace(artifacts=[artifact])
        job = Job(id='job-1', stage='preparation_and_pocket_detection', status=JobStatus.FAILED, error='failed')
        self.assertIn('Element Co is unsupported', _failure_summary(state, job))
        job.id = 'another-job'
        self.assertNotIn('Element Co', _failure_summary(state, job))

    def test_reviewed_receptor_failure_uses_the_matching_attempt_diagnosis(self):
        from types import SimpleNamespace
        receptor = self.root / 'receptor'
        receptor.mkdir()
        (receptor / 'receptor_failure_diagnosis.txt').write_text(
            'Receptor preparation failure category: Preparation backend valence-validation error\n')
        state = SimpleNamespace(artifacts=[], workflow_data={'receptor_preparation_attempts': [
            {'request_id': 'attempt-1', 'root': str(self.root)},
        ]})
        job = Job(id='job-1', stage='receptor_parameterization', request_id='attempt-1',
                  status=JobStatus.FAILED, error='failed')
        self.assertIn('valence-validation error', _failure_summary(state, job))
        job.request_id = 'attempt-2'
        self.assertNotIn('valence-validation error', _failure_summary(state, job))

    def test_failed_site_detection_exposes_revisioned_retry_only_when_supported(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        StudyController(self.store).create_study('failed-site-study', 'Failed site')
        state = self.store.load('failed-site-study')
        state.workflow_data['study_setup'] = {'explore_sites_first': True}
        state.jobs.append(Job(id='failed-site', stage='site_exploration', status=JobStatus.FAILED))
        self.store.save(state)
        client = SimpleNamespace(runtime={'retry_site_exploration_supported': True},
                                 connected=True, request=Mock(return_value={}))
        window = StudyWindow(self.store, 'failed-site-study', settings=self.settings, host_client=client)
        self.addCleanup(window.close)
        window.refresh()
        self.assertFalse(window.retry_site_button.isHidden())
        self.assertTrue(window.retry_site_button.isEnabled())
        revision = window.state.revision
        window.retry_site_button.click()
        client.request.assert_called_once_with('failed-site-study', 'retry_site_exploration', {}, expected_revision=revision)
        client.runtime.clear()
        window.refresh()
        self.assertTrue(window.retry_site_button.isHidden())

    def test_failed_screening_retry_uses_the_recorded_host_request(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        StudyController(self.store).create_study('failed-screen-study', 'Failed screen')
        state = self.store.load('failed-screen-study')
        state.jobs.append(Job(id='screen-job', stage='screening', status=JobStatus.FAILED,
                              request_id='screen-request'))
        state.workflow_data['restartable_stage_requests'] = [
            {'stage': 'screening', 'request_id': 'screen-request', 'payload': {}}]
        self.store.save(state)
        client = SimpleNamespace(runtime={'retry_recorded_stage_supported': True},
                                 connected=True, request=Mock(return_value={}))
        window = StudyWindow(self.store, 'failed-screen-study', settings=self.settings, host_client=client)
        self.addCleanup(window.close)
        self.assertFalse(window.retry_site_button.isHidden())
        self.assertEqual(window.retry_site_button.text(), 'Restart screening')
        revision = window.state.revision
        window.retry_site_button.click()
        from PyQt6.QtTest import QTest
        for _ in range(100):
            if not getattr(window, '_starting_screening', False): break
            QTest.qWait(20)
        client.request.assert_called_once_with('failed-screen-study', 'retry_recorded_stage', {}, expected_revision=revision)

    def test_inspector_has_both_input_components_and_screening_records_in_one_list(self):
        from tests.test_molecule_inspection import component_fixture
        from rdkit import Chem
        from docking_universal.services.ligand_library import inspect_ligand_library
        source, _ = component_fixture(self.root)
        compounds = self.root / 'inspection-compounds.sdf'
        compounds.write_text(Chem.MolToMolBlock(Chem.MolFromSmiles('CCN')) + '\n$$$$\n')
        library_panel = self.window.screening_setup_panel.library_panel
        library_panel.library = inspect_ligand_library(compounds)
        library_panel._selected_ids = {'prior-scientific-selection'}
        self.window.input_pdb.setText(str(source))
        original = self.store.path_for('desktop').read_bytes()
        panel = self.window.molecule_inspector
        self.assertEqual(panel.choices.count(), 4)
        panel.choices.setCurrentIndex(1)
        selected = panel.choices.currentData()
        self.assertEqual(selected['chain'], 'A')
        self.assertIsNotNone(panel.picture.picture)
        self.window.preview_molecule_2d()
        dialog = self.window._input_preview_dialog
        self.assertIs(dialog.inspector, panel)
        self.assertEqual(panel.choices.currentData(), selected)
        self.assertIn('requires the embedded', panel.three_d_message.text())
        self.assertTrue(panel.picture.isVisibleTo(dialog))
        self.assertTrue(panel.three_d_page.isVisibleTo(dialog))
        panel.choices.setCurrentIndex(3)
        self.assertEqual(panel.choices.currentData()['origin'], 'library')
        self.assertIsNotNone(panel.picture.picture)
        self.assertEqual(library_panel._selected_ids, {'prior-scientific-selection'})
        self.assertEqual(self.store.path_for('desktop').read_bytes(), original)
        dialog.close()

    def test_2d_inspection_needs_no_receptor_or_viewer_and_does_not_change_study(self):
        self.assertIsNone(self.window.viewer_widget)
        original = self.store.path_for('desktop').read_bytes()
        panel = self.window.molecule_inspector
        panel.smiles.setText('CCO')
        panel.draw_smiles()
        self.assertIsNotNone(panel.picture.picture)
        self.assertEqual(self.store.path_for('desktop').read_bytes(), original)
        self.assertIsNone(self.window._input_preview_dialog)

    def test_screening_preview_excludes_bound_components_and_restores_setup_list(self):
        from tests.test_molecule_inspection import component_fixture
        from rdkit import Chem
        from docking_universal.services.ligand_library import inspect_ligand_library
        source, _ = component_fixture(self.root)
        compounds = self.root / 'screening-preview.sdf'
        compounds.write_text(Chem.MolToMolBlock(Chem.MolFromSmiles('CCN')) + '\n$$$$\n')
        library = self.window.screening_setup_panel.library_panel
        library.library = inspect_ligand_library(compounds)
        library._selected_ids = {'retained-selection'}
        self.window.input_pdb.setText(str(source))
        panel = self.window.molecule_inspector
        bound = next(i for i in range(panel.choices.count()) if panel.choices.itemData(i).get('chain') == 'A')
        panel.choices.setCurrentIndex(bound)
        original = panel.entry_key(panel.choices.currentData())
        study_before = self.store.path_for('desktop').read_bytes()
        identifier = library.library['records'][0]['record_id']
        self.window.preview_library_both(identifier)
        dialog = self.window._input_preview_dialog
        self.assertIsNotNone(dialog)
        self.assertEqual(panel.title.text(), 'Screening compounds')
        self.assertEqual(panel.choices.count(), 1)
        self.assertEqual(panel.choices.currentData()['origin'], 'library')
        self.assertTrue(panel.reference_button.isHidden())
        self.assertTrue(panel.source_bar.isHidden())
        self.assertEqual(library._selected_ids, {'retained-selection'})
        self.assertEqual(self.store.path_for('desktop').read_bytes(), study_before)
        dialog.close()
        self.assertEqual(panel.entry_key(panel.choices.currentData()), original)
        self.assertTrue(any(panel.choices.itemData(i).get('origin') == 'input' for i in range(panel.choices.count())))

    def test_input_preview_borrows_one_viewer_and_restores_without_mutating_study(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.qt import QtWidgets

        StudyController(self.store).create_study('input-preview', 'Input preview')
        adapter = SimpleNamespace(begin_input_preview=Mock(), end_input_preview=Mock(), focus_input_preview=Mock())
        viewer = SimpleNamespace(adapter=adapter, backend_name='Embedded PyMOL',
                                 backend_kind='embedded', connected=False,
                                 report_view_available=False, status='disconnected',
                                 last_error=None, refresh_health=lambda: False)
        widget = QtWidgets.QFrame()
        window = StudyWindow(self.store, 'input-preview', settings=self.settings,
                             viewer_coordinator=viewer, viewer_widget=widget)
        self.addCleanup(window.close)
        source = self.root / 'input-preview.pdb'
        source.write_text('ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 10.00           C\n')
        original = self.store.path_for('input-preview').read_bytes()
        window.show()
        self.assertFalse(window.study_setup_panel.preview_input_button.isEnabled())
        window.input_pdb.setText(str(source))
        self.assertTrue(window.study_setup_panel.preview_input_button.isEnabled())
        for fail in (False, True):
            adapter.begin_input_preview.side_effect = ValueError('bad structure') if fail else None
            with patch.object(QtWidgets.QMessageBox, 'warning'):
                window.preview_input_structure()
            self.application.processEvents()
            dialog = window._input_preview_dialog
            self.assertTrue(dialog.isVisible())
            if not fail:
                self.assertIs(widget.parentWidget(), dialog.inspector.three_d_page)
            else:
                self.assertIn('bad structure', dialog.inspector.three_d_message.text())
            dialog.close()
            self.application.processEvents()
            self.assertIsNone(window._input_preview_dialog)
            self.assertIs(widget.parentWidget(), window.pose_split)
            self.assertIs(window.molecule_inspector.parentWidget(), window.study_setup_panel.molecule_preview_slot)
            self.assertEqual(self.store.path_for('input-preview').read_bytes(), original)
        self.assertEqual(adapter.begin_input_preview.call_count, 2)
        self.assertEqual(adapter.end_input_preview.call_count, 2)
        window.input_pdb.setText(str(self.root / 'missing.cif'))
        self.assertFalse(window.study_setup_panel.preview_input_button.isEnabled())

    def test_inline_reference_action_selects_exact_instance_and_retains_redocking_choice(self):
        from docking_universal.services.molecule_inspection import inspection_preview
        from tests.test_molecule_inspection import component_fixture
        from types import SimpleNamespace
        from unittest.mock import Mock
        source, _ = component_fixture(self.root)
        StudyController(self.store).create_study('reference-selection', 'Reference selection')
        def inspect(_study, operation, payload):
            self.assertEqual(operation, 'molecule_inspection')
            return {'result': {'preview': inspection_preview(payload['entry'], payload['mode'])}}

        client = SimpleNamespace(runtime={}, connected=True, request=Mock(side_effect=inspect))
        window = StudyWindow(self.store, 'reference-selection', settings=self.settings, host_client=client)
        self.addCleanup(window.close)
        window.input_pdb.setText(str(source))
        window.output_directory.setText(str(self.root / 'reference-output'))
        original = self.store.path_for('reference-selection').read_bytes()
        source_bytes = source.read_bytes()
        inspector = window.molecule_inspector
        for redock in (False, True):
            window.study_setup_panel.redock_ligand.setChecked(redock)
            index = next(i for i in range(inspector.choices.count()) if inspector.choices.itemData(i).get('chain') == 'B')
            inspector.choices.setCurrentIndex(index)
            self.assertTrue(inspector.reference_button.isEnabled())
            inspector.reference_button.click()
            self.assertEqual(window.study_setup_panel.redock_ligand.isChecked(), redock)
            self.assertEqual(window.site_mode.currentData(), 'ligand')
            values = window.study_setup_panel.values()
            self.assertEqual(values.ligand_identity, {'resname': 'LIG', 'chain_id': 'B', 'residue_number': '102', 'insertion_code': '', 'altloc': ''})
            self.assertIn('reference: LIG B:102', inspector.title.text())
            self.assertFalse(window.study_setup_panel._form.isRowVisible(window.ligand_resname.parentWidget()))
            self.assertEqual(values.pathway, 'control' if redock else 'exploratory')
            self.assertEqual(self.store.path_for('reference-selection').read_bytes(), original)
            self.assertEqual(source.read_bytes(), source_bytes)
        self.assertTrue(client.request.called)
        self.assertEqual({call.args[1] for call in client.request.call_args_list}, {'molecule_inspection'})
        window.close()
        reopened = StudyWindow(self.store, 'reference-selection', settings=self.settings, host_client=client)
        self.addCleanup(reopened.close)
        self.assertEqual(reopened.study_setup_panel.ligand_identity()['chain_id'], 'B')
        self.assertEqual(reopened.study_setup_panel.ligand_identity()['residue_number'], '102')
        with patch.object(reopened, 'prepare_geostd_library', return_value=str(self.root)), \
             patch.object(reopened.host_controller, 'start_control_validation') as start:
            reopened._submit_preparation()
            self.assertEqual(start.call_count, 1)
            payload = start.call_args.args[0]
            self.assertEqual((payload['ligand_resname'], payload['ligand_chain_id'], payload['ligand_residue_number']), ('LIG', 'B', '102'))
        source.write_text('changed after selecting reference')
        from docking_universal.gui.qt import QtWidgets
        with patch.object(QtWidgets.QMessageBox, 'warning') as warning, \
             patch.object(reopened.host_controller, 'start_control_validation') as start:
            reopened._submit_preparation()
            warning.assert_called_once()
            start.assert_not_called()

    def test_3d_pick_syncs_exact_instance_without_committing_and_rejects_invalid_picks(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.qt import QtCore, QtWidgets
        from tests.test_molecule_inspection import component_fixture

        class ViewerWidget(QtWidgets.QFrame):
            inputMoleculePicked = QtCore.pyqtSignal(dict)

        source, _ = component_fixture(self.root)
        StudyController(self.store).create_study('3d-pick', 'Native molecule picks')
        adapter = SimpleNamespace(begin_input_preview=Mock(return_value={'object_name': 'preview_1'}),
                                  end_input_preview=Mock(), focus_input_preview=Mock(),
                                  enable_input_preview_picking=Mock())
        coordinator = SimpleNamespace(adapter=adapter, backend_name='Embedded PyMOL', backend_kind='embedded',
                                      connected=False, report_view_available=False, status='disconnected',
                                      last_error=None, refresh_health=lambda: False)
        widget = ViewerWidget()
        window = StudyWindow(self.store, '3d-pick', settings=self.settings,
                             viewer_coordinator=coordinator, viewer_widget=widget)
        self.addCleanup(window.close)
        window.input_pdb.setText(str(source))
        window.preview_input_structure()
        inspector = window.molecule_inspector
        inspector.choices.setCurrentIndex(0)  # Full structure with all bound components.
        entry = next(inspector.choices.itemData(i) for i in range(inspector.choices.count())
                     if inspector.choices.itemData(i).get('chain') == 'B')
        initial_reference = window.study_setup_panel.ligand_identity()
        initial_state = self.store.path_for('3d-pick').read_bytes()
        picked = dict(object='preview_1', name=entry['resname'], chain=entry['chain'],
                      number=entry['resi'], segment=entry['segment'])
        for invalid in (dict(picked, object='other_scene'), dict(picked, chain='X'),
                        dict(picked, number='102A'), dict(picked, segment='other_subchain'),
                        dict(picked, name='HOH'), dict(picked, name='ALA')):
            previous = inspector.choices.currentData()
            widget.inputMoleculePicked.emit(invalid)
            self.assertEqual(inspector.choices.currentData(), previous)
        widget.inputMoleculePicked.emit(picked)
        self.assertEqual(inspector.choices.currentData(), entry)
        self.assertIsNotNone(inspector.picture.picture)
        self.assertTrue(inspector.reference_button.isEnabled())
        self.assertEqual(window.study_setup_panel.ligand_identity(), initial_reference)
        self.assertEqual(self.store.path_for('3d-pick').read_bytes(), initial_state)
        visible = [inspector.choices.itemData(i) for i in range(inspector.choices.count())
                   if inspector.choices.itemData(i).get('kind') == 'component']
        adapter.focus_input_preview.assert_called_with(entry, show_receptor=True, preserve_view=True,
                                                      show_all_components=True, visible_components=visible)
        inspector.choices.setCurrentIndex(1)
        adapter.focus_input_preview.assert_called_with(inspector.choices.currentData(), show_receptor=True,
                                                      preserve_view=False, show_all_components=False,
                                                      visible_components=visible)
        adapter.enable_input_preview_picking.assert_called_once()
        inspector.choices.setCurrentIndex(0)
        source.write_text('input changed since preview opened')
        widget.inputMoleculePicked.emit(picked)
        self.assertEqual(inspector.choices.currentIndex(), 0)
        self.assertIn('structure changed', inspector.three_d_message.text())
        self.assertFalse(inspector._borrowed)
        adapter.end_input_preview.assert_called_once()
        window._input_preview_dialog.close()
        widget.inputMoleculePicked.emit(picked)
        self.assertEqual(inspector.choices.currentIndex(), 0)

    def test_supporting_only_input_has_one_reveal_toggle_and_retains_explicit_reference(self):
        import gemmi
        from tests.test_molecule_inspection import component_fixture
        source, _ = component_fixture(self.root)
        structure = gemmi.read_structure(str(source))
        for chain in structure[0]:
            chain[0].name = 'BOG'
        source.write_text(structure.make_mmcif_document().as_string())
        StudyController(self.store).create_study('display-filter', 'Supporting components')
        window = StudyWindow(self.store, 'display-filter', settings=self.settings)
        self.addCleanup(window.close)
        before = self.store.path_for('display-filter').read_bytes()
        window.input_pdb.setText(str(source))
        inspector = window.molecule_inspector
        self.assertEqual(inspector.choices.count(), 1)
        self.assertEqual(inspector.choices.currentData()['kind'], 'whole')
        self.assertIn('2 hidden', inspector.all_components.text())
        self.assertFalse(inspector.reference_button.isEnabled())
        inspector.all_components.setChecked(True)
        self.assertEqual(inspector.choices.count(), 3)
        inspector.choices.setCurrentIndex(2)
        self.assertEqual(inspector.choices.currentData()['chain'], 'B')
        inspector.reference_button.click()
        identity = window.study_setup_panel.ligand_identity()
        self.assertEqual((identity['resname'], identity['chain_id']), ('BOG', 'B'))
        inspector.all_components.setChecked(False)
        self.assertEqual(inspector.choices.count(), 1)
        self.assertEqual(window.study_setup_panel.ligand_identity(), identity)
        window._sync_inspected_reference()
        self.assertTrue(inspector.all_components.isChecked())
        self.assertEqual(inspector.choices.currentData()['chain'], 'B')
        self.assertEqual(self.store.path_for('display-filter').read_bytes(), before)

    def test_reference_action_rejects_nonbound_locked_and_stale_entries(self):
        from tests.test_molecule_inspection import component_fixture
        from docking_universal.gui.qt import QtWidgets
        source, _ = component_fixture(self.root)
        StudyController(self.store).create_study('reference-guards', 'Reference guards')
        window = StudyWindow(self.store, 'reference-guards', settings=self.settings)
        self.addCleanup(window.close)
        window.input_pdb.setText(str(source))
        inspector = window.molecule_inspector
        entry = next(inspector.choices.itemData(i) for i in range(inspector.choices.count()) if inspector.choices.itemData(i).get('chain') == 'B')
        initial = window.study_setup_panel.values()
        with patch.object(QtWidgets.QMessageBox, 'warning') as warning:
            window.use_inspected_reference({'origin': 'smiles', 'kind': 'compound', 'smiles': 'CCO'})
            window.study_setup_panel.set_locked(True)
            window.use_inspected_reference(entry)
            window.study_setup_panel.set_locked(False)
            source.write_text('changed source')
            window.use_inspected_reference(entry)
            self.assertEqual(warning.call_count, 3)
        self.assertEqual(window.study_setup_panel.values(), initial)

    def test_site_only_approval_cannot_enable_finalization_and_failure_keeps_review(self):
        from unittest.mock import Mock
        controller = StudyController(self.store)
        state = self.store.load('desktop')
        controller.resolve_decision('desktop', state.pending_decisions[0].id, ('P1',),
            actor='test-scientist', expected_revision=state.revision)
        state = self.store.load('desktop')
        state.workflow_data['study_setup'] = {'explore_sites_first': True}
        state.workflow_data['receptor_parameterization_status'] = 'not_started'
        self.store.save(state)
        from docking_universal.gui.qt import QtWidgets
        host = Mock(available=True)
        with patch.object(self.window, 'host_controller', host):
            self.window.exploratory_approval.setChecked(True)
            self.window.refresh()
            self.assertFalse(self.window.finalize_button.isEnabled())
            self.assertTrue(self.window.protocol_finalization_panel.prepare_reviewed_button.isEnabled())
            host.prepare_reviewed_receptor.side_effect = RuntimeError('Host rejected the preparation request.')
            with patch.object(QtWidgets.QMessageBox, 'critical'):
                self.window.prepare_reviewed_receptor()
            self.assertIn('Host rejected the preparation request', self.window.feedback_text.text())
            state = self.store.load('desktop')
            state.workflow_data['receptor_parameterization_status'] = 'failed'
            self.store.save(state)
            self.window.refresh()
            self.assertFalse(self.window.finalize_button.isEnabled())
            self.assertFalse(self.window.protocol_finalization_panel.prepare_reviewed_button.isEnabled())
            self.assertEqual(self.window.candidates.rowCount(), 1)
            self.assertIn('approved regions are saved', self.window.finalization_status.text())
            self.assertEqual(self.window.protocol_finalization_panel.review_model_button.text(),
                             'Review preparation failure and model options…')

    def test_native_control_candidate_uses_capability_instead_of_unconditional_disable(self):
        from types import SimpleNamespace
        from docking_universal.windows_desktop import CAPABILITIES
        runtime = {**CAPABILITIES, 'known_ligand_control_supported': True,
                   'supported_site_modes': ['pockets', 'ligand']}
        self.window.host_client = SimpleNamespace(runtime=runtime, connected=False)
        self.window._apply_runtime_capabilities()
        panel = self.window.study_setup_panel
        panel.set_locked(False)
        self.assertTrue(panel.redock_ligand.isEnabled())
        index = self.window.study_pathway.findData('control')
        self.assertTrue(self.window.study_pathway.model().item(index).isEnabled())
        self.window.study_pathway.setCurrentIndex(index)
        self.assertTrue(panel.predict_with_ligand.isEnabled())
        self.window.host_client = None

    def test_native_fresh_study_button_submits_preparation_without_a_viewer(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.windows_desktop import CAPABILITIES
        StudyController(self.store).create_study('fresh-native', 'Fresh native fixture')
        client = SimpleNamespace(runtime=CAPABILITIES, connected=True, request=Mock())
        window = StudyWindow(self.store, 'fresh-native', settings=self.settings, host_client=client)
        try:
            source = self.root / 'fixture.pdb'
            source.write_text('ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 10.00           C\n')
            window.input_pdb.setText(str(source))
            window.output_directory.setText(str(self.root / 'native-output'))
            self.assertTrue(window.start_preparation_button.isEnabled())
            with patch.object(window, 'prepare_geostd_library', return_value=str(self.root)):
                window.start_preparation_button.click()
            self.assertEqual(client.request.call_args.args[1], 'start_receptor_preparation')
            self.assertEqual(client.request.call_args.args[2]['site_mode'], 'pockets')
        finally:
            window.close()

    def test_native_capabilities_keep_unaccepted_methods_disabled_after_refresh(self):
        from types import SimpleNamespace
        from docking_universal.windows_desktop import CAPABILITIES
        self.window.host_client = SimpleNamespace(runtime=CAPABILITIES, connected=False)
        self.window._apply_runtime_capabilities()
        panel = self.window.study_setup_panel
        panel.set_locked(False)
        self.assertFalse(panel.redock_ligand.isEnabled())
        self.assertFalse(panel.redock_ligand.isChecked())
        self.assertFalse(panel.predict_with_ligand.isEnabled())
        for combo, values in ((self.window.protocol_engine, {"vina"}),
                              (self.window.control_engine, {"vina"}),
                              (self.window.site_mode, {"pockets"}),
                              (self.window.pocket_engine, {"auto", "p2rank"})):
            self.assertEqual({combo.itemData(i) for i in range(combo.count())
                              if combo.model().item(i).isEnabled()}, values)
        self.assertFalse(self.window.study_pathway.model().item(self.window.study_pathway.findData("control")).isEnabled())
        index = self.window.protocol_engine.findData('adgpu')
        if index >= 0:
            self.window.protocol_engine.setCurrentIndex(index)
            self.window._apply_runtime_capabilities()
            self.assertEqual(self.window.protocol_engine.currentData(), 'adgpu')
        else:
            self.assertEqual(self.window.protocol_engine.currentData(), 'vina')
        self.window.host_client = None

    def test_screening_cpu_choice_reaches_launch_payload_without_changing_state(self):
        from unittest.mock import Mock
        from PyQt6.QtTest import QTest
        original = self.store.path_for('desktop').read_bytes()
        for mode, expected in (('default', None), ('automatic', 0), ('custom', 12)):
            panel = self.window.screening_setup_panel
            panel.cpu.setCurrentIndex(panel.cpu.findData(mode))
            panel.cpu_count.setValue(12)
            self.window._screening_plan = {'compound_count': 1}
            host = Mock(available=True)
            with patch.object(self.window, 'host_controller', host), \
                    patch.object(self.window, 'refresh'):
                self.window.start_screening()
                for _ in range(100):
                    if not getattr(self.window, '_starting_screening', False): break
                    QTest.qWait(20)
            payload = host.start_screening.call_args.args[0]
            if expected is None:
                self.assertNotIn('cpu', payload)
            else:
                self.assertEqual(payload['cpu'], expected)
            self.assertEqual(payload['cluster_rmsd'], 1.5)
            self.assertEqual(payload['representatives'], 3)
            self.assertEqual(self.store.path_for('desktop').read_bytes(), original)

    def test_clustering_presets_send_the_exact_numeric_launch_value(self):
        from unittest.mock import Mock
        from PyQt6.QtTest import QTest
        original = self.store.path_for('desktop').read_bytes()
        panel = self.window.screening_setup_panel
        for index, expected in ((0, 1.0), (1, 1.5), (2, 2.0), (3, 1.25)):
            panel.cluster_preset.setCurrentIndex(index)
            if index == 3:
                panel.cluster_rmsd.setValue(expected)
            self.window._screening_plan = {'compound_count': 1}
            host = Mock(available=True)
            with patch.object(self.window, 'host_controller', host), patch.object(self.window, 'refresh'):
                self.window.start_screening()
                for _ in range(100):
                    if not getattr(self.window, '_starting_screening', False): break
                    QTest.qWait(20)
            self.assertEqual(host.start_screening.call_args.args[0]['cluster_rmsd'], expected)
            self.assertEqual(self.store.path_for('desktop').read_bytes(), original)

    def test_clustering_category_restores_from_saved_numeric_cutoff_without_study_mutation(self):
        original = self.store.path_for('desktop').read_bytes()
        for value, index in ((1.0, 0), (2.0, 2), (1.25, 3), (1.5, 1)):
            self.window.screen_cluster_rmsd.setValue(value)
            self.window.close()
            self.window = StudyWindow(self.store, 'desktop', settings=self.settings)
            self.assertEqual(self.window.screen_cluster_rmsd.value(), value)
            self.assertEqual(self.window.screening_setup_panel.cluster_preset.currentIndex(), index)
            self.assertEqual(self.store.path_for('desktop').read_bytes(), original)
            self.assertFalse(self.window.screen_exploratory_approval.isChecked())

    def test_expanded_pose_mode_clears_cluster_contacts_and_forces_reloading_on_return(self):
        from unittest.mock import Mock
        self.window._linked_pose_active = True
        self.window.viewer_coordinator = Mock()
        adapter = self.window.viewer_coordinator.adapter
        self.window.cluster_contact_controls = Mock()
        self.window.pose_review_mode.setCurrentIndex(self.window.pose_review_mode.findData('all_poses'))
        self.assertFalse(self.window._linked_pose_active)
        adapter.clear_linked_contacts.assert_called()
        self.window.cluster_contact_controls.hide.assert_called()

    def test_screening_duration_stays_visible_after_completion_and_reopen(self):
        state = self.store.load('desktop')
        state.jobs.append(Job('timed-screen', 'screening', JobStatus.COMPLETED,
                              started_at='2026-10-14T23:35:48.274031Z',
                              finished_at='2026-10-14T23:47:57.349705Z'))
        self.store.save(state)
        original = self.store.path_for('desktop').read_bytes()
        self.window.refresh()
        label = self.window.screening_setup_panel.elapsed
        self.assertFalse(label.isHidden())
        self.assertIn('Total run time 12:09', label.text())
        self.assertIn('analysis and reporting', label.text())
        self.window.close()
        self.window = StudyWindow(self.store, 'desktop', settings=self.settings)
        self.assertIn('Total run time 12:09', self.window.screening_setup_panel.elapsed.text())
        self.assertEqual(self.store.path_for('desktop').read_bytes(), original)

    def test_ligand_file_picker_accepts_mol_and_keeps_the_selected_path(self):
        selected = str(self.root / "ligand.MOL")
        with patch("docking_universal.gui.desktop.QtWidgets.QFileDialog.getOpenFileName",
                   return_value=(selected, "MOL molecules")) as picker:
            self.window.choose_screen_ligand_file()
        self.assertIn("*.mol", picker.call_args.args[3])
        self.assertIn("*.sdf", picker.call_args.args[3])
        self.assertEqual(self.window.screen_ligands.text(), selected)

    def _running_finalization_fixture(self):
        from datetime import datetime, timedelta, timezone
        from docking_universal.models import CompletionStatus
        state = self.store.load('desktop')
        state.decisions = []
        state.selected_pocket_ids = ['P1']
        state.jobs = [Job('finalization-test', 'final_report', JobStatus.RUNNING,
                         started_at=(datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(),
                         progress_message='Rendering report figures…')]
        state.completion_status = CompletionStatus.RUNNING
        self.store.save(state)

    def test_show_starts_real_polling_and_completion_is_seen_without_manual_refresh(self):
        from docking_universal.gui.qt import QtCore
        from docking_universal.models import CompletionStatus
        from PyQt6.QtTest import QTest
        self._running_finalization_fixture()
        self.window.refresh_timer.setInterval(20)
        self.window.show()
        QTest.qWait(80)
        self.assertTrue(self.window.refresh_timer.isActive())
        self.assertTrue(self.window.running_indicator.isVisibleTo(self.window))
        self.assertIn('Rendering report figures', self.window.feedback_text.text())
        state = self.store.load('desktop')
        bundle, report = self.root / 'ready.duprotocol', self.root / 'report.pdf'
        bundle.write_bytes(b'fixture bundle')
        report.write_bytes(b'fixture report')
        state.jobs[-1].status = JobStatus.COMPLETED
        state.completion_status = CompletionStatus.COMPLETED
        state.artifacts.extend([ArtifactRecord('bundle', 'protocol_bundle', str(bundle)),
                                ArtifactRecord('report', 'final_report', str(report))])
        self.store.save(state)
        original = self.store.path_for('desktop').read_bytes()
        # The host/state changes; no window.refresh() is called here.
        QTest.qWait(100)
        self.assertEqual(self.window.state.revision, state.revision)
        self.assertIn('Status: completed', self.window.summary.text())
        self.assertFalse(self.window.running_indicator.isVisibleTo(self.window))
        self.assertTrue(self.window.open_final_report_button.isEnabled())
        self.assertTrue(self.window.open_bundle_location_button.isEnabled())
        self.assertEqual(self.store.path_for('desktop').read_bytes(), original)
        self.window.hide()
        QTest.qWait(50)
        self.assertFalse(self.window.refresh_timer.isActive())
        self.window.show()
        QTest.qWait(40)
        self.assertTrue(self.window.refresh_timer.isActive())

    def test_unchanged_poll_updates_elapsed_without_rebuilding_views_or_writing_state(self):
        from datetime import datetime, timedelta, timezone
        from PyQt6.QtTest import QTest
        self._running_finalization_fixture()
        self.window.show()
        QTest.qWait(50)
        initial = self.window.running_elapsed.text()
        original = self.store.path_for('desktop').read_bytes()
        with patch('docking_universal.gui.desktop.datetime', wraps=datetime) as clock, \
                patch.object(self.window, '_render_candidates') as candidates, \
                patch.object(self.window, '_render_screening_results') as results:
            clock.now.return_value = datetime.now(timezone.utc) + timedelta(seconds=4)
            self.window._poll_refresh()
            self.assertNotEqual(initial, self.window.running_elapsed.text())
            candidates.assert_not_called()
            results.assert_not_called()
        self.assertEqual(self.store.path_for('desktop').read_bytes(), original)
        # Finish only the disposable fixture so tearDown never asks to cancel.
        state = self.store.load('desktop')
        state.jobs[-1].status = JobStatus.COMPLETED
        self.store.save(state)

    def test_progress_only_poll_updates_status_without_rebuilding_tables(self):
        self._running_finalization_fixture()
        self.window.refresh()
        self.store.update('desktop', lambda state: setattr(state.jobs[-1], 'progress_message', 'Writing next figure…'))
        with patch.object(self.window, '_render_candidates') as candidates, \
             patch.object(self.window, '_render_screening_results') as results:
            self.window._refresh_polled_state()
            candidates.assert_not_called()
            results.assert_not_called()
            self.assertIn('Writing next figure', self.window.feedback_text.text())
        self.store.update('desktop', lambda state: setattr(state.jobs[-1], 'status', JobStatus.COMPLETED))
        with patch.object(self.window, '_render_candidates') as candidates:
            self.window._refresh_polled_state()
            candidates.assert_called_once()

    def test_poll_does_not_wait_on_native_ray_lock_or_redraw_during_export(self):
        from types import SimpleNamespace
        self.window.viewer_widget = SimpleNamespace(_du_ray_export_active=True)
        try:
            with patch.object(self.window, '_refresh_viewer_lifecycle') as health, \
                    patch.object(self.window.session, 'refresh') as state_poll:
                self.window._refresh_polled_state()
                health.assert_not_called()
                state_poll.assert_not_called()
        finally:
            self.window.viewer_widget = None

    def test_control_figure_names_and_overlay_scene_preserve_roles(self):
        self.assertEqual(self.window._report_asset_label(Path('control_lowest_rmsd_plip2d.png')),
                         'Control interactions — global lowest-RMSD pose')
        self.assertEqual(self.window._report_asset_label(Path('control_energy_rank_2_plip2d.png')),
                         'Control interactions — energy rank 2')
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            scene = root / 'control_panel_B_overlay.pse'
            scene.write_text('retained scene')
            self.assertEqual(self.window._scene_for_report_asset(root / 'control_panels_AB.png'), scene.resolve())

    @classmethod
    def setUpClass(cls):
        from docking_universal.gui.qt import QtWidgets
        cls.application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        from docking_universal.gui.qt import QtCore
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.store = JsonStudyStore(self.root / "runs")
        controller = StudyController(self.store)
        controller.create_study("desktop", "Desktop study")
        controller.start_simulated_pocket_review("desktop", [
            PocketCandidate("P1", "Pocket 1", 1, "box-1", "Highest geometric rank", {"score": 0.7}),
        ])
        self.settings = QtCore.QSettings(str(self.root / "window.ini"), QtCore.QSettings.IniFormat)
        self.window = StudyWindow(self.store, "desktop", settings=self.settings)

    def tearDown(self):
        state = self.store.load('desktop')
        for job in state.jobs:
            if job.id == 'finalization-test' and job.status == JobStatus.RUNNING:
                job.status = JobStatus.COMPLETED
                self.store.save(state)
        self.window.close()
        self.temporary.cleanup()

    def test_required_detail_and_decision_remain_visible(self):
        self.window.show()
        self.application.processEvents()
        self.assertEqual(self.window.detail.currentText(), "Guided")
        self.assertTrue(self.window.feedback_card.isVisibleTo(self.window))
        self.assertIn("Scientific decision required", self.window.feedback_heading.text())
        self.assertIn("review the evidence", self.window.feedback_text.text().lower())
        self.assertTrue(self.window.logs_dock.isHidden())
        self.assertTrue(self.window.reports_dock.isHidden())
        self.assertFalse(self.window.decision_banner.isVisibleTo(self.window))
        self.assertTrue(self.window.decision_synopsis_button.isEnabled())
        self.window.detail.setCurrentText("Concise")
        self.assertIn("DECISION REQUIRED", self.window.decision_banner.text())
        self.assertEqual(self.window.candidates.rowCount(), 1)

    def test_static_figure_browser_absent_before_and_after_approval(self):
        from docking_universal.gui.qt import QtWidgets
        state = self.store.load('desktop')
        for approved in (False, True):
            if approved:
                StudyController(self.store).resolve_decision('desktop', state.pending_decisions[0].id, ('P1',), actor='test user')
                self.window.refresh()
            self.assertEqual(self.window.review_tabs.count(), 1)
            self.assertEqual(self.window.review_tabs.tabText(0), 'Interactive structure')
            self.assertIsNone(self.window.findChild(QtWidgets.QWidget, 'decision_figure_choice'))
            self.assertIsNone(self.window.findChild(QtWidgets.QWidget, 'decision_figure_view'))
            self.assertIsNone(self.window.findChild(QtWidgets.QWidget, 'decision_figure_full_screen'))
            self.assertEqual(self.window.approve_button.isEnabled(), False)  # no host supplied

    def test_live_image_exports_remain_without_report_figure_export(self):
        from docking_universal.gui.qt import QtGui
        menu = self.window.save_image.menu()
        menu.aboutToShow.emit()
        labels = [action.text() for action in menu.actions()]
        self.assertEqual(len(labels), 4)
        self.assertFalse(any('report figure' in label.lower() for label in labels))
        self.assertFalse(menu.actions()[0].isEnabled())
        self.assertFalse(menu.actions()[1].isEnabled())
        self.assertTrue(menu.actions()[2].isEnabled())
        self.assertFalse(menu.actions()[3].isEnabled())
        figure = self.root / 'interaction.png'
        image = QtGui.QImage(800, 600, QtGui.QImage.Format.Format_ARGB32)
        image.fill(QtGui.QColor('white'))
        image.save(str(figure))
        original = figure.read_bytes()
        self.window.interaction_diagram_choice.addItem('Exact selected 2D', str(figure))
        self.window._interaction_source_pixmap = QtGui.QPixmap(str(figure))
        self.assertEqual(self.window._export_diagram_path(), figure)
        payload = self.window._export_selected_diagram()
        self.assertEqual(payload.image.size(), image.size())
        with self.assertRaises(ValueError):
            payload.save(figure)
        payload.save(self.root / 'exported.png')
        self.assertEqual(original, figure.read_bytes())

    def test_detached_contact_switches_are_shown_for_docked_poses_and_return_to_workspace(self):
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.cluster_contacts import ClusterContactControls
        from docking_universal.gui.qt import QtWidgets
        from docking_universal.viewer.plip_contacts import STYLES
        from unittest.mock import Mock
        original = self.store.path_for('desktop').read_bytes()
        host = QtWidgets.QWidget()
        self.window.live_layout = QtWidgets.QVBoxLayout(host)
        controls = ClusterContactControls(Mock())
        self.window.live_layout.addWidget(controls)
        self.window.cluster_contact_controls = controls
        self.window._linked_pose_active = True
        controls.set_contacts({'hydrogen_bond': STYLES['hydrogen_bond']}, [])
        panel = FullPyMOLStudyPanel(self.window)
        try:
            for tab in (0, 1):
                panel.tabs.setCurrentIndex(tab)
                self.assertFalse(panel.tabs.isAncestorOf(controls))
                self.assertEqual(controls.isHidden(), tab == 0)
                self.assertTrue(controls.types.buttons['hydrogen_bond'].isChecked())
            panel.dispose()
            self.assertIs(controls.parent(), host)
            self.assertEqual(self.store.path_for('desktop').read_bytes(), original)
        finally:
            panel.close()
            host.close()

    def test_background_refresh_preserves_an_open_detached_selector_highlight(self):
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.qt import QtWidgets
        choice = QtWidgets.QComboBox()
        records = [('First compound','first'),('Second compound','second')]
        FullPyMOLStudyPanel._copy_choice(choice, records, None)
        choice.showPopup()
        choice.view().setCurrentIndex(choice.model().index(1,0))
        FullPyMOLStudyPanel._copy_choice(choice, records, None)
        self.assertEqual(choice.view().currentIndex().row(), 1)
        self.assertEqual(choice.currentIndex(), -1)  # hover is not a commitment
        choice.hidePopup()
        choice.close()

    def test_background_refresh_keeps_the_selected_cluster_instead_of_returning_to_first(self):
        from docking_universal.gui.qt import QtCore
        from docking_universal.gui.results_model import ClusterInteraction
        from unittest.mock import patch
        choices = [ClusterInteraction(self.root/'first.png', self.root, '1', 'primary', 1, -8, 2),
                   ClusterInteraction(self.root/'second.png', self.root, '2', 'primary', 2, -7, 3)]
        original = self.store.path_for('desktop').read_bytes()
        with patch.object(self.window, '_selected_screening_compound', return_value=self.root/'compound'), \
             patch.object(self.window.results_model, 'cluster_interactions', return_value=choices), \
             patch.object(self.window, '_pose_review_mode_changed'):
            self.window._screening_result_selection_changed()
            choice = self.window.interaction_diagram_choice
            blocker = QtCore.QSignalBlocker(choice)
            choice.setCurrentIndex(1)
            del blocker
            self.window._screening_result_selection_changed()
            self.assertEqual(choice.currentData(), str(self.root/'second.png'))
        self.assertEqual(self.store.path_for('desktop').read_bytes(), original)

    def test_walkthrough_is_optional_modeless_and_available_in_both_interfaces(self):
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.qt import QtWidgets
        panel = self.window.pocket_evidence_panel
        panel.set_viewer_presentation(embedded=True)
        self.assertIsNone(panel._guide_window)
        panel.guide_button.click()
        guide = panel._guide_window
        self.assertTrue(guide.isVisible())
        self.assertFalse(guide.isModal())
        text = guide.findChild(QtWidgets.QTextBrowser).toPlainText()
        self.assertIn("Click again to remove", text)
        self.assertIn("not all residue–residue interactions", text)
        guide.close()
        panel.guide_button.click()
        self.assertIs(panel._guide_window, guide)
        guide.close()
        browser = FullPyMOLStudyPanel(self.window)
        try:
            browser.evidence.guide_button.click()
            full_guide = browser.evidence._guide_window
            self.assertIn("Return to Docking Universal", full_guide.findChild(QtWidgets.QTextBrowser).toPlainText())
            browser.dispose()
            self.assertFalse(full_guide.isVisible())
            self.assertEqual(self.store.load("desktop").selected_pocket_ids, [])
        finally:
            browser.close()

    def test_experimental_2d_action_requires_one_exact_observation(self):
        panel = self.window.pocket_evidence_panel
        panel.interactionsRequested.disconnect(self.window.render_evidence_interactions)
        observations = [
            {"source_ligand_id": "1ABC/LIG/A/9", "aligned_ligand_pdb": "first.pdb"},
            {"source_ligand_id": "1ABC/LIG/B/9", "aligned_ligand_pdb": "second.pdb"},
        ]
        panel.set_candidate({"id": "P1", "evidence": {
            "experimental_ligand_evidence": {"observations": observations},
        }})
        def resolve(observation):
            if not observation:
                raise ValueError("Select one observation")
            return {}
        requested = []
        panel.interactionsRequested.connect(requested.append)
        with patch("docking_universal.services.evidence_interactions.evidence_inputs", side_effect=resolve):
            panel.table.selectRow(0)
            self.assertTrue(panel.render_2d_button.isEnabled())
            panel.render_2d_button.click()
            self.assertEqual(requested, [observations[0]])
            panel.table.selectAll()
            self.assertFalse(panel.render_2d_button.isEnabled())
            panel.rendering_2d = True
            panel.table.clearSelection()
            panel.table.selectRow(1)
            self.assertFalse(panel.render_2d_button.isEnabled())

    def test_old_experimental_cache_updates_drawing_only_without_repeating_plip(self):
        from unittest.mock import Mock
        from docking_universal.gui.qt import QtCore, QtWidgets
        from docking_universal.gui.linked_pose_review import LinkedPosePanel
        cache = self.root / 'evidence-cache'
        (cache/'plip').mkdir(parents=True)
        for name in ('ligand.sdf','receptor.pdb','plip/report.xml','result.json'):
            (cache/name).write_text('retained')
        record = dict(cache=str(cache),entry='2R5P',ligand='MK1',chain='A',residue='1',aligned='retained.pdb')
        host = Mock()
        host.python_executable = '/scientific/python'
        host._environment.return_value = {}
        self.window.host_client = host
        self.window.viewer_widget = QtWidgets.QWidget()
        self.window.linked_pose_panel = LinkedPosePanel(self.window)
        with patch('docking_universal.services.evidence_interactions.evidence_inputs',return_value=record), \
                patch('docking_universal.services.evidence_interactions.evidence_diagram_current',return_value=False), \
                patch.object(self.window,'_show_evidence_render_progress'), \
                patch.object(QtCore.QProcess,'start') as start, \
                patch.object(QtWidgets.QMessageBox,'warning') as warning:
            self.window.render_evidence_interactions({})
            warning.assert_not_called()
            start.assert_called_once()
            self.assertIn('--diagram-only', start.call_args.args[1])
        self.assertTrue(json.loads((cache/'request.json').read_text())['diagram_only'])

    def test_live_observation_selection_needs_no_load_button_but_companion_keeps_it(self):
        from docking_universal.gui.pocket_evidence import PocketEvidencePanel
        panel = PocketEvidencePanel()
        panel.set_viewer_presentation(embedded=True)
        changes, launches = [], []
        panel.selectionChanged.connect(changes.append)
        panel.ligandsRequested.connect(launches.append)
        candidate = {"id": "P1", "evidence": {"experimental_ligand_evidence": {
            "observations": [{"aligned_ligand_pdb": "one.pdb"}, {"aligned_ligand_pdb": "two.pdb"}],
        }}}
        panel.set_candidate(candidate)
        self.assertTrue(panel.compare_button.isHidden())
        panel.table.selectAll()
        self.assertEqual(changes[-1], ["one.pdb", "two.pdb"])
        panel.set_candidate(candidate)
        self.assertTrue(panel.compare_button.isHidden())
        panel.table.clearSelection()
        self.assertEqual(changes[-1], [])
        panel.set_viewer_presentation(embedded=False)
        self.assertFalse(panel.compare_button.isHidden())
        panel.table.selectRow(1)
        panel.compare_button.click()
        self.assertEqual(launches, [["two.pdb"]])
        panel.close()

    def test_obstruction_details_are_optional_modeless_and_include_recorded_distances(self):
        from docking_universal.gui.qt import QtWidgets
        from docking_universal.gui.pocket_evidence import PocketEvidencePanel
        panel = PocketEvidencePanel()
        panel.set_candidate({'id': 'P1', 'evidence': {'conformational_site_evidence': {
            'status': 'conformationally_incompatible',
            'occluding_residues': [{'name': 'ASP', 'chain': 'A', 'number': '30'}],
            'observations': [{'residue': {'name': 'ASP', 'chain': 'A', 'number': '30'}, 'ligands': [{
                'source_ligand_id': '2R5P/MK1/B/902', 'consistent_with_side_chain_occlusion': True,
                'current_side_chain_minimum_distance_angstrom': 1.75,
                'bound_side_chain_minimum_distance_angstrom': 2.5}]}]}}})
        self.assertIsNone(panel._obstruction_details_window)
        panel.obstruction_details_button.click()
        dialog = panel._obstruction_details_window
        self.assertFalse(dialog.isModal())
        text = dialog.findChild(QtWidgets.QTextBrowser).toPlainText()
        for expected in ('below 2.0', '0.5', '1.75', '2.5', '2R5P/MK1/B/902', 'not list all changed'):
            self.assertIn(expected, text)
        panel.obstruction_details_button.click()
        self.assertIs(panel._obstruction_details_window, dialog)
        panel.set_candidate({'id': 'P2', 'evidence': {}})
        self.assertIsNone(panel._obstruction_details_window)
        panel.close()

    def test_embedded_boxed_residue_centers_without_opening_review(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        residue = {'name': 'TYR', 'chain': 'B', 'number': '385'}
        adapter = Mock()
        with patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter)), \
             patch.object(self.window, 'linked_pose_panel', SimpleNamespace(status=Mock()), create=True), \
             patch.object(self.window, '_open_interaction_review') as opened:
            self.window._center_linked_residue(residue)
        adapter.center_contact_residue.assert_called_once_with(residue)
        opened.assert_not_called()

    def test_embedded_diagram_click_centers_without_opening_review(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        view = SimpleNamespace(ligand=self.root / 'pose.sdf')
        adapter = Mock()
        adapter.review_pose = view.ligand.resolve()
        with patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter, connected=True)), \
             patch.object(self.window, 'linked_pose_panel', SimpleNamespace(status=Mock()), create=True), \
             patch.object(self.window, '_open_interaction_review') as opened:
            self.window._center_linked_pose_view(view)
        adapter.center_review_ligand.assert_called_once_with()
        opened.assert_not_called()

    def test_experimental_diagram_opens_matched_source_pair_not_aligned_overlay(self):
        from docking_universal.gui.linked_pose_review import PoseView
        view = PoseView(self.root / "aligned.pdb", self.root / "original.pdb",
                        self.root / "diagram.png", self.root / "report.xml", "Deposited ligand")
        self.window._evidence_2d_view = view
        with patch.object(self.window, "_open_interaction_review", return_value=True) as paired:
            self.assertTrue(self.window._highlight_linked_ligand(view))
        paired.assert_called_once_with(view)

    def test_full_pymol_browser_mirrors_evidence_multiselection(self):
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        observations = [
            {"entry": "1ABC", "ligand": "LIG", "aligned_ligand_pdb": "first.pdb"},
            {"entry": "1ABC", "ligand": "LIG", "aligned_ligand_pdb": "second.pdb"},
        ]
        candidate = self.window.state.workflow_data["pocket_candidates"][0]
        candidate["evidence"]["experimental_ligand_evidence"] = {"observations": observations}
        self.window.pocket_evidence_panel.set_candidate(candidate)
        browser = FullPyMOLStudyPanel(self.window)
        try:
            browser.evidence.table.selectAll()
            self.assertEqual(self.window.pocket_evidence_panel._selected_paths(), ["first.pdb", "second.pdb"])
            browser.evidence.table.clearSelection()
            browser.evidence.table.selectRow(1)
            self.assertEqual(self.window.pocket_evidence_panel._selected_paths(), ["second.pdb"])
            self.window.pocket_evidence_panel.table.selectAll()
            self.assertEqual(browser.evidence._selected_paths(), ["first.pdb", "second.pdb"])
            self.assertTrue(browser.evidence.render_2d_button.isHidden())
        finally:
            browser.dispose()
            browser.close()

    def test_full_pymol_obstruction_is_selectable_and_highlights_exact_residue(self):
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.qt import QtCore
        from unittest.mock import Mock
        residue = {"name": "ASP", "number": "30", "chain": "A"}
        candidate = self.window.state.workflow_data["pocket_candidates"][0]
        candidate["evidence"]["conformational_site_evidence"] = {
            "status": "conformationally_incompatible", "occluding_residues": [residue],
        }
        adapter = Mock()
        self.window.viewer_coordinator = Mock(adapter=adapter, connected=True, status='connected', report_view_available=False)
        browser = FullPyMOLStudyPanel(self.window)
        try:
            warning = browser.evidence.warning
            self.assertEqual(warning.verticalScrollBarPolicy(), QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.assertTrue(warning.textInteractionFlags() & QtCore.Qt.TextInteractionFlag.TextSelectableByMouse)
            warning.selectAll()
            self.assertIn("ASP30A", warning.textCursor().selectedText())
            self.assertEqual(browser.highlight_obstruction_button.text(), "Highlight ASP30A")
            browser.highlight_obstruction_button.click()
            adapter.highlight_obstruction_residues.assert_called_once_with([residue])
            self.assertIn("Camera unchanged", browser.status.text())
            self.assertEqual(self.store.load("desktop").selected_pocket_ids, [])
            candidate["evidence"]["conformational_site_evidence"] = {}
            browser.refresh()
            self.assertTrue(browser.highlight_obstruction_button.isHidden())
        finally:
            browser.dispose()
            browser.close()

    def test_full_pymol_second_click_hides_ligand_in_both_panels_and_viewer(self):
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.qt import QtCore, QtWidgets
        from PyQt6.QtTest import QTest
        from unittest.mock import Mock
        candidate = self.window.state.workflow_data['pocket_candidates'][0]
        candidate['evidence']['input_ligand_evidence'] = {'observations': [
            {'entry': 'Input', 'ligand': 'GNP A:200', 'source': 'input_structure',
             'aligned_ligand_pdb': 'input.pdb'},
            {'entry': 'Input', 'ligand': 'BME A:202', 'source': 'input_structure',
             'aligned_ligand_pdb': 'support.pdb'}]}
        self.window.pocket_evidence_panel.set_candidate(candidate)
        self.window.viewer_coordinator = Mock(connected=True)
        browser = FullPyMOLStudyPanel(self.window)
        browser.show()
        from docking_universal.models import record_to_dict
        QtWidgets.QApplication.processEvents()
        before = record_to_dict(self.store.load('desktop'))
        try:
            self.window.pocket_evidence_panel.supporting_toggle.setChecked(True)
            browser.evidence.supporting_toggle.setChecked(True)
            table = browser.evidence.table
            first = table.visualItemRect(table.item(0, 2)).center()
            second = table.visualItemRect(table.item(1, 2)).center()
            QTest.mouseClick(table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=first)
            self.assertEqual(self.window.pocket_evidence_panel._selected_paths(), ['input.pdb'])
            self.window.viewer_coordinator.sync_evidence_ligands.assert_called_with(['input.pdb'])
            QTest.mouseClick(table.viewport(), QtCore.Qt.MouseButton.LeftButton,
                             QtCore.Qt.KeyboardModifier.ControlModifier, pos=second)
            self.assertEqual(browser.evidence._selected_paths(), ['input.pdb', 'support.pdb'])
            QTest.mouseClick(table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=first)
            self.assertEqual(self.window.pocket_evidence_panel._selected_paths(), ['support.pdb'])
            self.window.viewer_coordinator.sync_evidence_ligands.assert_called_with(['support.pdb'])
            QTest.mouseClick(table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=second)
            self.assertEqual(browser.evidence._selected_paths(), [])
            self.assertEqual(self.window.pocket_evidence_panel._selected_paths(), [])
            self.window.viewer_coordinator.sync_evidence_ligands.assert_called_with([])
            self.assertEqual(record_to_dict(self.store.load('desktop')), before)
        finally:
            browser.dispose()
            browser.close()

    def test_full_pymol_exposes_existing_paired_review_for_retained_diagram(self):
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        diagram = self.root / 'retained.png'
        diagram.write_bytes(b'retained diagram')
        self.window._current_interaction_diagram = diagram
        with patch.object(self.window, 'open_selected_interaction_diagram') as open_pair:
            browser = FullPyMOLStudyPanel(self.window)
            try:
                self.assertTrue(browser.paired_review.isEnabled())
                browser.paired_review.click()
                open_pair.assert_called_once_with()
                diagram.unlink()
                browser.refresh()
                self.assertFalse(browser.paired_review.isEnabled())
            finally:
                browser.dispose()
                browser.close()

    def test_paired_review_returns_to_detached_pymol(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.qt import QtCore, QtWidgets
        from docking_universal.gui.linked_pose_review import LinkedPosePanel
        from PyQt6.QtTest import QTest
        class Pair(QtWidgets.QDialog):
            def __init__(self, view, panel, viewer, adapter, parent):
                super().__init__(parent)
                self.view = view
                self.button = QtWidgets.QPushButton('Return to workspace', self)
            def dispose(self):
                pass
        viewer = QtWidgets.QWidget()
        panel = LinkedPosePanel()
        panel.set_pose = Mock()
        split = QtWidgets.QSplitter()
        split.addWidget(viewer)
        split.addWidget(panel)
        adapter = SimpleNamespace(begin_interaction_review=Mock(return_value={}), end_interaction_review=Mock())
        detached = SimpleNamespace(_du_full_pymol=True)
        def close_detached():
            self.window._detached_structure_window = None
        view = SimpleNamespace(label='Pose', diagram=self.root / 'diagram.png')
        with patch.object(self.window, 'viewer_widget', viewer), \
             patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter, connected=True)), \
             patch.object(self.window, 'linked_pose_panel', panel, create=True), \
             patch.object(self.window, 'pose_split', split, create=True), \
             patch.object(self.window, '_detached_structure_window', detached), \
             patch.object(self.window, '_return_detached_structure', side_effect=close_detached), \
             patch.object(self.window, '_sync_residue_highlight_actions'), \
             patch.object(self.window, '_ensure_pocket_space'), \
             patch.object(self.window, 'open_full_pymol') as reopen, \
             patch('docking_universal.gui.interaction_review_window.InteractionReviewWindow', Pair):
            self.assertTrue(self.window._open_interaction_review(view))
            pair = self.window._paired_interaction_window
            self.assertEqual(pair.button.text(), 'Return to PyMOL')
            pair.close()
            QTest.qWait(10)
            reopen.assert_called_once()
        split.close()

    def test_main_evidence_panel_highlights_recorded_residue_without_detaching(self):
        from unittest.mock import Mock
        residue = {"name": "ASP", "number": "30", "chain": "A"}
        candidate = self.window.state.workflow_data["pocket_candidates"][0]
        candidate["evidence"]["conformational_site_evidence"] = {
            "status": "conformationally_incompatible", "occluding_residues": [residue],
        }
        panel = self.window.pocket_evidence_panel
        panel.set_viewer_presentation(embedded=True)
        panel.set_candidate(candidate)
        adapter = Mock()
        self.window.viewer_coordinator = Mock(adapter=adapter, connected=True, status='connected', report_view_available=False)
        self.window.viewer_widget = object()
        try:
            self.assertFalse(panel.highlight_obstruction_button.isHidden())
            self.assertEqual(panel.highlight_obstruction_button.text(), "Highlight ASP30A")
            with patch.object(self.window, "_show_embedded_viewer") as show:
                panel.highlight_obstruction_button.click()
            adapter.highlight_obstruction_residues.assert_called_once_with([residue])
            show.assert_called_once()
            self.assertIn("Camera unchanged", self.window.statusBar().currentMessage())
            self.assertIsNone(self.window._detached_structure_window)
            self.assertEqual(self.store.load("desktop").selected_pocket_ids, [])
            panel.set_candidate({"id": "P2", "evidence": {}})
            self.assertTrue(panel.highlight_obstruction_button.isHidden())
            self.assertFalse(panel.highlight_row.isHidden())
        finally:
            self.window.viewer_widget = None

    def test_full_pymol_browser_region_uses_existing_navigation_without_approval(self):
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        candidate = dict(self.window.state.workflow_data["pocket_candidates"][0], id="P2", label="Pocket 2")
        self.window.state.workflow_data["pocket_candidates"].append(candidate)
        browser = FullPyMOLStudyPanel(self.window)
        try:
            with patch.object(self.window, "_select_plotted_candidate") as select:
                browser.regions.setCurrentIndex(browser.regions.findData("P2"))
                select.assert_called_once_with("P2")
            self.assertEqual(self.store.load("desktop").selected_pocket_ids, [])
        finally:
            browser.dispose()
            browser.close()

    def test_detached_sites_replace_selection_and_can_be_cleared(self):
        from PyQt6.QtTest import QTest
        from docking_universal.gui.qt import QtCore
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        candidate = self.window.state.workflow_data['pocket_candidates'][0]
        self.window.state.workflow_data['pocket_candidates'] = [dict(candidate, id='P1'), dict(candidate, id='P2')]
        self.window.candidates.setRowCount(2)
        with patch.object(self.window, '_candidate_highlight_changed'):
            browser = FullPyMOLStudyPanel(self.window)
            try:
                browser.show()
                viewport = browser.site_list.viewport()
                first = browser.site_list.visualItemRect(browser.site_list.item(0)).center()
                second = browser.site_list.visualItemRect(browser.site_list.item(1)).center()
                QTest.mouseClick(viewport, QtCore.Qt.MouseButton.LeftButton, pos=first)
                QTest.mouseClick(viewport, QtCore.Qt.MouseButton.LeftButton, pos=second)
                self.assertEqual([item.data(QtCore.Qt.ItemDataRole.UserRole) for item in browser.site_list.selectedItems()], ['P2'])
                QTest.mouseClick(viewport, QtCore.Qt.MouseButton.LeftButton, QtCore.Qt.KeyboardModifier.ControlModifier, first)
                self.assertEqual(len(browser.site_list.selectedItems()), 2)
                browser.clear_sites.click()
                self.assertEqual(browser.site_list.selectedItems(), [])
            finally:
                browser.dispose()
                browser.close()

    def test_detached_site_clears_previous_ligand_and_hides_pose_contacts(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter
        cmd = SimpleNamespace(get_names=Mock(return_value=['receptor', 'du_evidence_old', 'du_review_pose', 'du_multi_pose_1']),
                              disable=Mock(), hide=Mock())
        adapter = SimpleNamespace(cmd=cmd, widget=SimpleNamespace(update=Mock()), clear_linked_contacts=Mock())
        adapter.clear_site_review_overlays = lambda: EmbeddedPymolAdapter.clear_site_review_overlays(adapter)
        with patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter, connected=False)), \
             patch.object(self.window, '_update_candidate_review_action'), \
             patch.object(self.window, 'open_selected_candidate_review'):
            browser = FullPyMOLStudyPanel(self.window)
            try:
                browser.site_list.setCurrentRow(0)
                browser._site_list_selected()
                cmd.disable.assert_any_call('du_evidence_old')
                cmd.disable.assert_any_call('du_review_pose')
                cmd.disable.assert_any_call('du_multi_pose_1')
                self.assertNotIn('receptor', [item.args[0] for item in cmd.disable.call_args_list])
                adapter.clear_linked_contacts.assert_called()
                if browser.contact_controls is not None:
                    self.assertTrue(browser.contact_controls.isHidden())
            finally:
                browser.dispose()
                browser.close()

    def test_evidence_double_click_selects_and_centers_that_ligand(self):
        from PyQt6.QtTest import QSignalSpy
        from docking_universal.gui.qt import QtCore, QtWidgets
        from docking_universal.gui.pocket_evidence import PocketEvidencePanel
        panel = PocketEvidencePanel()
        panel.table.setRowCount(1)
        for column in range(panel.table.columnCount()):
            item = QtWidgets.QTableWidgetItem('ligand')
            item.setData(QtCore.Qt.ItemDataRole.UserRole, '/tmp/example.pdb')
            panel.table.setItem(0, column, item)
        spy = QSignalSpy(panel.ligandCenterRequested)
        panel._request_ligand(panel.table.item(0, 1))
        self.assertEqual(list(spy[0]), ['/tmp/example.pdb'])
        self.assertEqual(panel._selected_paths(), ['/tmp/example.pdb'])
        panel.close()

    def test_pocket_table_and_graph_clicks_center_the_same_region(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        candidate = self.window.state.workflow_data['pocket_candidates'][0]
        candidate.setdefault('evidence', {})['geometry'] = {'center_x': 2, 'center_y': 3, 'center_z': 4}
        adapter = SimpleNamespace(center_pocket=Mock(side_effect=ValueError('Grid pending')),
                                  center_review_point=Mock())
        with patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter, connected=True)), \
             patch.object(self.window, '_candidate_highlight_changed'):
            self.window.pocket_pan_toggle.setChecked(False)
            self.assertFalse(self.window.smooth_site_pan.isChecked())
            self.window._select_plotted_candidate(candidate['id'])
            adapter.center_review_point.assert_called_once_with([2, 3, 4], animate=False)
            self.window._center_clicked_candidate(self.window.candidates.item(0, 0))
            self.assertEqual(adapter.center_review_point.call_count, 2)

    def test_detached_pocket_center_respects_animation_setting(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        adapter = SimpleNamespace(center_pocket=Mock())
        candidate = dict(self.window.state.workflow_data['pocket_candidates'][0], id='P35', label='P35')
        self.window.state.workflow_data['pocket_candidates'] = [candidate]
        with patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter)):
            browser = FullPyMOLStudyPanel(self.window)
            try:
                browser.animate_center.setChecked(False)
                from docking_universal.gui.qt import QtCore
                with QtCore.QSignalBlocker(browser.site_list):
                    browser.site_list.item(0).setSelected(True)
                browser._center_site(browser.site_list.item(0))
                adapter.center_pocket.assert_called_with(35, animate=False)
                browser.animate_center.setChecked(True)
                browser._center_site(browser.site_list.item(0))
                adapter.center_pocket.assert_called_with(35, animate=True)
            finally:
                browser.dispose()
                browser.close()

    def test_detached_pose_center_uses_animation_toggle(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.qt import QtCore, QtWidgets
        adapter = SimpleNamespace(center_displayed_pose=Mock())
        table = self.window.pose_results
        table.setRowCount(1)
        for col in range(table.columnCount()):
            item = QtWidgets.QTableWidgetItem('1')
            item.setData(QtCore.Qt.ItemDataRole.UserRole, ('/tmp/analysis', 1))
            table.setItem(0, col, item)
        with patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter, connected=False)), \
             patch.object(self.window, '_expanded_pose_selection_changed'):
            browser = FullPyMOLStudyPanel(self.window)
            try:
                browser.result_mode.setCurrentIndex(browser.result_mode.findData('all_poses'))
                browser.poses.selectRow(0)
                browser.animate_pose_center.setChecked(False)
                browser._center_pose(browser.poses.item(0, 0))
                adapter.center_displayed_pose.assert_called_with(0, animate=False)
                self.assertFalse(self.window.smooth_site_pan.isChecked())
                browser.animate_pose_center.setChecked(True)
                browser._center_pose(browser.poses.item(0, 0))
                adapter.center_displayed_pose.assert_called_with(0, animate=True)
            finally:
                browser.dispose()
                browser.close()

    def test_detached_pose_selection_does_not_center_camera(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        adapter = SimpleNamespace(show_linked_interactions=Mock(return_value=({}, [])),
                                  center_review_ligand=Mock(), center_review_point=Mock())
        coordinator = SimpleNamespace(adapter=adapter, connected=True)
        view = SimpleNamespace(ligand=str(self.root / 'site_2' / 'pose.sdf'), label='Pose')
        panel = SimpleNamespace(status=SimpleNamespace(setText=Mock()))
        controls = SimpleNamespace(set_contacts=Mock())
        with patch.object(self.window, 'viewer_coordinator', coordinator), \
             patch.object(self.window, '_detached_structure_window', object(), create=True), \
             patch.object(self.window, 'linked_pose_panel', panel, create=True), \
             patch.object(self.window, 'cluster_contact_controls', controls, create=True), \
             patch.object(self.window, '_show_embedded_viewer'):
            self.assertTrue(self.window._highlight_linked_ligand(view, highlight=False))
        adapter.show_linked_interactions.assert_called_once_with(view, focus_on_new_receptor=False)
        adapter.center_review_ligand.assert_not_called()
        adapter.center_review_point.assert_not_called()

    def test_full_pymol_distinguishes_predicted_pocket_from_optional_box(self):
        from functools import partial
        from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.qt import QtCore
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        candidate = dict(self.window.state.workflow_data['pocket_candidates'][0], id='P2', label='P2')
        ligand_site = dict(candidate, id='L1', label='L1', evidence={'kind': 'ligand_defined'})
        self.window.state.workflow_data['pocket_candidates'] = [candidate, ligand_site]
        cmd = SimpleNamespace(get_names=Mock(return_value=['du_box']), enable=Mock(), disable=Mock(), hide=Mock())
        adapter = SimpleNamespace(cmd=cmd, widget=SimpleNamespace(update=Mock()))
        adapter.set_site_review_visibility = partial(EmbeddedPymolAdapter.set_site_review_visibility, adapter)
        with patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter)):
            browser = FullPyMOLStudyPanel(self.window)
            try:
                with QtCore.QSignalBlocker(browser.site_list):
                    browser.site_list.item(0).setSelected(True)
                browser._update_box_visibility()
                cmd.disable.assert_called_with('du_box')
                browser.box_toggle.setChecked(True)
                cmd.enable.assert_called_with('du_box')
                browser.box_toggle.setChecked(False)
                with QtCore.QSignalBlocker(browser.site_list):
                    browser.site_list.clearSelection()
                    browser.site_list.item(1).setSelected(True)
                browser._update_box_visibility()
                cmd.disable.assert_called_with('du_box')
                browser.box_toggle.setChecked(True)
                cmd.enable.assert_called_with('du_box')
            finally:
                browser.dispose()
                browser.close()

    def test_main_review_box_toggle_keeps_the_selected_candidate(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.qt import QtCore
        adapter = SimpleNamespace(set_site_review_visibility=Mock())
        coordinator = SimpleNamespace(adapter=adapter, connected=True)
        table = self.window.candidates
        with QtCore.QSignalBlocker(table.selectionModel()), QtCore.QSignalBlocker(table):
            table.selectRow(0)
        with patch.object(self.window, 'viewer_coordinator', coordinator):
            self.assertFalse(self.window.site_box_toggle.isChecked())
            self.window.site_box_toggle.setChecked(True)
            adapter.set_site_review_visibility.assert_called_once_with(has_selection=True, show_boxes=True)
            self.assertEqual([row.row() for row in table.selectionModel().selectedRows()], [0])
            self.window.site_box_toggle.setChecked(False)
            adapter.set_site_review_visibility.assert_called_with(has_selection=True, show_boxes=False)

    def test_show_all_pockets_keeps_region_selection_and_box_toggle_independent(self):
        from types import SimpleNamespace
        from unittest.mock import Mock

        adapter = SimpleNamespace(show_pocket_space=Mock(return_value=['surface']))
        manifest = {'counts': {'8': 3, '1': 10, '27': 4}}
        with patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter, connected=True)), \
             patch.object(self.window, '_ensure_pocket_space'), patch.object(self.window, '_show_embedded_viewer'):
            self.window.candidates.clearSelection()
            self.assertFalse(self.window.all_pockets_toggle.isChecked())
            self.window.all_pockets_toggle.setChecked(True)
            self.window._apply_pocket_space(manifest)
            self.assertEqual(adapter.show_pocket_space.call_args.args[1], [1, 8, 27])
            self.assertFalse(self.window.candidates.selectionModel().hasSelection())
            self.assertFalse(self.window.site_box_toggle.isChecked())

    def test_detached_navigation_does_not_activate_main_window(self):
        from docking_universal.gui.qt import QtWidgets
        self.window.viewer_widget = object()
        self.window._detached_structure_window = QtWidgets.QDialog(self.window)
        self.window.review_tabs.addTab(QtWidgets.QWidget(), "Interactive structure")
        with patch.object(self.window, "raise_") as raise_main, patch.object(self.window, "activateWindow") as activate_main:
            self.window._show_embedded_viewer()
            raise_main.assert_not_called()
            activate_main.assert_not_called()
        self.window._detached_structure_window.close()
        self.window._detached_structure_window = None
        self.window.viewer_widget = None

    def test_full_pymol_browser_routes_exact_pose_to_existing_table(self):
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.qt import QtCore, QtWidgets
        table = self.window.pose_results
        table.itemSelectionChanged.disconnect(self.window._expanded_pose_selection_changed)
        identity = (str(self.root / "analysis"), 7)
        table.setRowCount(1)
        for column, value in enumerate(("7", "2", "-6.5 kcal/mol", "yes", "17", "conf1", "1")):
            item = QtWidgets.QTableWidgetItem(value)
            item.setData(QtCore.Qt.ItemDataRole.UserRole, identity)
            table.setItem(0, column, item)
        browser = FullPyMOLStudyPanel(self.window)
        try:
            browser.result_mode.setCurrentIndex(browser.result_mode.findData('all_poses'))
            with patch.object(self.window, '_expanded_pose_selection_changed') as display:
                browser.poses.selectRow(0)
                display.assert_called_once()
            self.assertEqual(self.window.pose_review_mode.currentData(), "all_poses")
            self.assertEqual(table.selectionModel().selectedRows()[0].row(), 0)
            self.assertEqual(table.item(0, 0).data(QtCore.Qt.ItemDataRole.UserRole), identity)
        finally:
            browser.dispose()
            browser.close()

    def test_full_pymol_browser_shows_and_selects_cluster_representatives(self):
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.qt import QtCore, QtWidgets
        table = self.window.cluster_comparison
        table.setSortingEnabled(False)
        table.setRowCount(1)
        identity = {'analysis': str(self.root / 'analysis'), 'cluster_id': 3}
        for column in range(table.columnCount()):
            item = QtWidgets.QTableWidgetItem('Saved' if column == 8 else str(column + 1))
            if column == 0:
                item.setData(QtCore.Qt.ItemDataRole.UserRole, identity)
            table.setItem(0, column, item)
        browser = FullPyMOLStudyPanel(self.window)
        try:
            self.assertEqual(browser.result_mode.currentData(), 'clusters')
            self.assertEqual(browser.poses.item(0, 8).text(), 'Saved')
            with patch.object(self.window, '_cluster_comparison_selected') as display:
                browser.poses.selectRow(0)
                display.assert_called_once()
            self.assertEqual(table.item(table.selectionModel().selectedRows()[0].row(), 0).data(QtCore.Qt.ItemDataRole.UserRole), identity)
        finally:
            browser.dispose()
            browser.close()

    def test_detached_plip_status_shows_failure_and_offers_retry(self):
        from unittest.mock import Mock
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.qt import QtCore, QtWidgets
        table = self.window.cluster_comparison
        table.setSortingEnabled(False)
        table.setRowCount(1)
        for col in range(table.columnCount()):
            item = QtWidgets.QTableWidgetItem(str(col))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, {'analysis': str(self.root), 'cluster_id': 1})
            table.setItem(0, col, item)
        browser = FullPyMOLStudyPanel(self.window)
        try:
            with QtCore.QSignalBlocker(browser.poses):
                browser.poses.selectRow(0)
            self.window._current_interaction_diagram = None
            self.window.interaction_diagram_view.setText('Pose 3 interaction analysis could not start: another workflow is running')
            browser._update_plip_status()
            self.assertIn('could not start', browser.plip_status.text())
            self.assertTrue(browser.calculate_plip.isEnabled())
            with patch.object(browser, '_pose_selected', Mock()) as retry:
                browser.calculate_plip.click()
                retry.assert_called_once()
            self.window.interaction_diagram_view.setText('Generating PLIP interactions for pose 3…')
            browser._update_plip_status()
            self.assertFalse(browser.plip_progress.isHidden())
        finally:
            browser.dispose()
            browser.close()

    def test_selected_ligand_sites_show_each_retained_representative(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        first, second = self.root / 'first.pdb', self.root / 'second.pdb'
        first.write_text('END\n')
        second.write_text('END\n')
        candidates = [
            {'id': 'L1', 'evidence': {'kind': 'ligand_defined', 'input_ligand_reference': str(first)}},
            {'id': 'L2', 'evidence': {'kind': 'ligand_defined', 'input_ligand_reference': str(second)}},
        ]
        coordinator = SimpleNamespace(sync_evidence_ligands=Mock())
        with patch.object(self.window, 'viewer_coordinator', coordinator):
            self.window._show_selected_site_ligands(candidates)
        coordinator.sync_evidence_ligands.assert_called_once_with([str(first.resolve()), str(second.resolve())])

    def test_ligand_label_mode_clears_and_does_not_restore_amino_acid_labels(self):
        from unittest.mock import Mock
        from docking_universal.gui.cluster_contacts import ClusterContactControls
        adapter = Mock()
        controls = ClusterContactControls(adapter)
        controls.residues = [{'name': 'ALA', 'chain': 'A', 'number': '1'}]
        ligand_handler = Mock()
        controls.set_ligand_label_mode(True, ligand_handler)
        adapter.set_review_labels_visible.assert_called_once_with(controls.residues, False)
        controls.labels.setChecked(True)
        ligand_handler.assert_called_once_with(True)
        adapter.set_review_labels_visible.assert_called_once()
        controls.close()

    def test_empty_docked_diagram_refresh_preserves_evidence_render(self):
        from docking_universal.gui.linked_pose_review import LinkedPosePanel
        self.window.linked_pose_panel = LinkedPosePanel(self.window)
        self.window.viewer_widget = object()
        panel = self.window.linked_pose_panel
        self.window._evidence_2d_record = {"aligned": "selected.pdb"}
        panel.show_loading("Rendering selected evidence…")
        self.window._show_selected_interaction_diagram()
        self.assertEqual(panel.query_image.text(), "Rendering selected evidence…")
        self.assertTrue(panel.compare.isHidden())
        self.assertTrue(panel.details.isHidden())
        self.assertTrue(panel.export_button.isHidden())
        self.assertIn("Calculating", panel.status.text())
        self.window.viewer_widget = None

    def test_feedback_text_stays_readable_with_dark_window_palette(self):
        from docking_universal.gui.qt import QtGui
        palette = self.window.palette()
        palette.setColor(QtGui.QPalette.ColorRole.WindowText, QtGui.QColor("white"))
        palette.setColor(QtGui.QPalette.ColorRole.Window, QtGui.QColor("#303030"))
        self.window.setPalette(palette)
        self.window.show()
        self.window.refresh()
        self.application.processEvents()
        for label in (self.window.feedback_heading, self.window.feedback_text):
            self.assertEqual(
                label.palette().color(QtGui.QPalette.ColorRole.WindowText).name(), "#172b3a",
            )

    def test_preparation_shows_activity_before_submission(self):
        self.window.host_client = object()
        self.window.show()
        observed = []
        def submit():
            observed.append(self.window.feedback_heading.text())
            self.assertTrue(self.window.running_indicator.isVisibleTo(self.window))
            self.assertFalse(self.window.start_preparation_button.isEnabled())
            self.assertGreaterEqual(self.window.running_indicator.height(), 20)
        with patch.object(self.window, "_submit_preparation", side_effect=submit):
            self.window.start_preparation()
        self.assertEqual(len(observed), 1)
        self.assertIn("STARTING", observed[0])
        self.assertFalse(self.window.running_indicator.isVisibleTo(self.window))

    def test_toolbar_diagnostic_actions_toggle_docked_nonoverlapping_panels(self):
        self.window.show()
        self.window.resize(1100, 700)
        self.application.processEvents()
        for action, dock in (
            (self.window.scientific_detail_action, self.window.workflow_detail_dock),
            (self.window.logs_action, self.window.logs_dock),
            (self.window.artifacts_action, self.window.reports_dock),
        ):
            self.assertTrue(dock.isHidden())
            action.trigger()
            self.application.processEvents()
            self.assertFalse(dock.isHidden())
            self.assertFalse(dock.isFloating())
            action.trigger()
            self.application.processEvents()
            self.assertTrue(dock.isHidden())

    def test_scientific_workflow_toggle_survives_refresh_and_tracks_close_and_focus(self):
        from docking_universal.gui.qt import QtWidgets
        self.window.show()
        self.application.processEvents()
        action = self.window.workflow_action
        dock = self.window.workflow_navigation_dock
        self.assertEqual(action.text(), "Scientific workflow")
        self.assertTrue(action.isChecked())
        self.assertTrue(dock.features() & QtWidgets.QDockWidget.DockWidgetClosable)
        current_row = self.window.workflow_navigation.currentRow()
        original_size = self.window.size()
        original_revision = self.store.load("desktop").revision
        action.trigger()
        self.window.refresh()
        self.application.processEvents()
        self.assertTrue(dock.isHidden())
        self.assertFalse(action.isChecked())
        action.trigger()
        self.application.processEvents()
        self.assertFalse(dock.isHidden())
        self.assertTrue(action.isChecked())
        self.assertFalse(dock.isFloating())
        dock.close()
        self.application.processEvents()
        self.assertFalse(action.isChecked())
        action.trigger()
        self.window.focus_canvas_action.setChecked(True)
        self.application.processEvents()
        self.assertFalse(action.isChecked())
        self.window.focus_canvas_action.setChecked(False)
        self.application.processEvents()
        self.assertTrue(action.isChecked())
        self.assertEqual(self.window.workflow_navigation.currentRow(), current_row)
        self.assertEqual(self.window.size(), original_size)
        self.assertEqual(self.store.load("desktop").revision, original_revision)

    def test_pose_renderer_readiness_is_always_visible_in_results_panel(self):
        self.assertTrue(self.window.poseedit_runtime_status.text())
        self.assertIn("GUI Qt 6.", self.window.runtime_status.text())
        self.assertIn("scientific host Python", self.window.runtime_status.text())
        if self.window.poseedit_runtime["status"] == "available":
            self.assertIn("ready", self.window.poseedit_runtime_status.text().lower())
        else:
            for component in self.window.poseedit_runtime["missing"]:
                self.assertIn(component, self.window.poseedit_runtime_status.text())

    def test_decision_figure_names_select_only_useful_report_composites(self):
        self.assertEqual(
            self.window._report_asset_label(Path("cavity_panels_AB.png")),
            "Pocket ranking and structural evidence",
        )
        self.assertEqual(
            self.window._report_asset_label(Path("5362440_selected_interactions_ABC.png")),
            "Top-pose interaction diagrams",
        )
        self.assertEqual(
            self.window._report_asset_label(Path("cavity_panel_A_selection.png")),
            "Pocket scores and ranking — Panel A",
        )

    def test_only_3d_figures_offer_their_matching_pymol_scene(self):
        report = self.root / "report"
        report.mkdir()
        figure = report / "pocket_evidence_site_1_AB.png"
        scene = report / "pocket_evidence_site_1_AB.pse"
        figure.write_bytes(b"figure")
        scene.write_bytes(b"scene")
        self.assertEqual(self.window._scene_for_report_asset(figure), scene.resolve())

        two_d = report / "compound_selected_interactions_ABC.png"
        two_d.write_bytes(b"figure")
        self.assertIsNone(self.window._scene_for_report_asset(two_d))

        top_three = report / "compound_top3_3d_snapshots.png"
        top_three.write_bytes(b"figure")
        sources = []
        for letter in "ABC":
            source = report / f"pose_{letter}.png"
            source.write_bytes(b"image")
            source.with_suffix(".pse").write_bytes(b"scene")
            sources.append(str(source))
        top_three.with_suffix(".manifest.json").write_text(json.dumps({"sources": sources}))
        scenes = self.window._scenes_for_report_asset(top_three)
        self.assertEqual([label for label, _path in scenes], ["Panel A", "Panel B", "Panel C"])

        interaction_manifest = report / "compound_top3_3d_snapshots.manifest.json"
        interaction_manifest.write_text(json.dumps({"sources": sources}))
        interaction_scenes = self.window._scenes_for_report_asset(two_d)
        self.assertEqual(
            interaction_scenes,
            [("Panel A", Path(sources[0]).with_suffix(".pse").resolve()),
             ("Panel B", Path(sources[1]).with_suffix(".pse").resolve()),
             ("Panel C", Path(sources[2]).with_suffix(".pse").resolve())],
        )

    def test_static_figures_remain_on_disk_but_not_in_gui_file_view(self):
        for name in ('protocol', 'screening'):
            directory = self.root / name
            directory.mkdir()
            (directory / 'cavity_panel_A_selection.png').write_bytes(b'retained')
        pdf = self.root / 'report.pdf'
        pdf.write_bytes(b'retained report')
        self.store.update('desktop', lambda state: state.artifacts.extend([
            ArtifactRecord('protocol-pocket', 'final_report_figure', str(self.root/'protocol/cavity_panel_A_selection.png')),
            ArtifactRecord('screening-pocket', 'screening_report_figure', str(self.root/'screening/cavity_panel_A_selection.png')),
            ArtifactRecord('report', 'final_report', str(pdf)),
        ]))
        before = self.store.path_for('desktop').read_bytes()
        with patch('docking_universal.gui.desktop.QtGui.QPixmap', side_effect=AssertionError('Static image decoded')):
            self.window.refresh()
        listed = [self.window.report_list.item(i).data(256) for i in range(self.window.report_list.count())]
        self.assertIn(str(pdf), listed)
        self.assertFalse(any(str(path).endswith('.png') for path in listed))
        self.assertEqual(self.window.structure_scene_choice.count(), 0)
        self.assertEqual(before, self.store.path_for('desktop').read_bytes())
        self.assertEqual((self.root/'protocol/cavity_panel_A_selection.png').read_bytes(), b'retained')

    def test_only_interactive_surface_occupies_central_review(self):
        self.assertEqual(self.window.review_tabs.count(), 1)
        self.assertTrue(self.window.review_tabs.tabBar().isHidden())
        self.assertIs(self.window.review_splitter.widget(1), self.window.candidates)
        self.assertGreater(self.window.candidates.maximumHeight(), 125)

    def test_candidate_review_opens_retained_structure_without_report_figure(self):
        class Viewer:
            backend_kind = "embedded"
            backend_name = "Embedded PyMOL"
            connected = False
            report_view_available = False
            status = "disconnected"

            def open(self, state):
                self.connected = True
                self.opened_study = state.study_id

            def show_candidate(self, state, candidate_id):
                self.candidate_id = candidate_id

        viewer = Viewer()
        self.window.viewer_coordinator = viewer
        self.window._update_candidate_review_action()
        self.assertTrue(self.window.candidate_review_button.isEnabled())
        self.window.open_selected_candidate_review()
        self.assertEqual(viewer.opened_study, "desktop")
        self.assertEqual(viewer.candidate_id, "P1")
        self.assertIn("reviewing P1", self.window.viewer_status.text())

    def test_active_embedded_navigation_does_not_reactivate_window(self):
        from docking_universal.gui.qt import QtWidgets
        widget = QtWidgets.QFrame()
        self.window.viewer_widget = widget
        self.window.review_tabs.addTab(QtWidgets.QWidget(), "Interactive structure")
        self.window.review_tabs.setCurrentWidget(self.window.live_page)
        with patch.object(self.window, "isActiveWindow", return_value=True), \
             patch.object(self.window, "raise_") as raise_window, \
             patch.object(self.window, "activateWindow") as activate:
            self.window._show_embedded_viewer()
            self.window._show_embedded_viewer()
            raise_window.assert_not_called()
            activate.assert_not_called()

    def test_evidence_warning_changes_keep_graph_and_table_in_place(self):
        panel = self.window.pocket_evidence_panel
        self.window.show()
        warning_candidate = {"id": "P1", "evidence": {
            "conformational_site_evidence": {
                "box_decision_warning": "A deposited ligand conflicts with the receptor. " * 12,
            },
        }}
        geometry = []
        for candidate in (warning_candidate, {"id": "P2", "evidence": {}}, warning_candidate):
            panel.set_candidate(candidate)
            self.application.processEvents()
            geometry.append((panel.table.geometry(), self.window.pocket_score_plot.geometry()))
        self.assertEqual(geometry[0], geometry[1])
        self.assertEqual(geometry[1], geometry[2])
        self.assertTrue(panel.warning_scroll.isVisibleTo(self.window))
        self.assertFalse(panel.warning.hasHeightForWidth())
        self.assertEqual(panel.warning.minimumHeight(), panel.warning.maximumHeight())

    def test_evidence_message_does_not_resize_text_viewport(self):
        from docking_universal.gui.qt import QtCore
        panel = self.window.pocket_evidence_panel
        self.window.show()
        self.application.processEvents()
        sizes = []
        for status in ("conformationally_incompatible", "not_evaluated",
                       "reviewed_no_geometric_incompatibility", "conformationally_incompatible"):
            panel.set_candidate({"id": "P1", "evidence": {
                "conformational_site_evidence": {"status": status}}})
            self.application.processEvents()
            sizes.append((self.window.size(), panel.size(), panel.warning.size()))
        self.assertTrue(all(size == sizes[0] for size in sizes))
        self.assertEqual(panel.verticalScrollBarPolicy(), QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)

    def test_unchanged_refresh_does_not_replace_candidate_or_evidence_items(self):
        self.window.refresh()
        item = self.window.candidates.item(0, 0)
        panel = self.window.pocket_evidence_panel
        with patch.object(panel, "_render_candidate", wraps=panel._render_candidate) as render:
            self.window.refresh()
            self.window.refresh()
            render.assert_not_called()
        self.assertIs(self.window.candidates.item(0, 0), item)

    def test_candidate_evidence_update_is_one_paint_transaction(self):
        panel = self.window.pocket_evidence_panel
        with patch.object(panel, "_render_candidate", wraps=panel._render_candidate) as render:
            candidate = {"id": "P2", "evidence": {}}
            panel.set_candidate(candidate)
            panel.set_candidate(candidate)
            render.assert_called_once()
        self.assertTrue(panel.updatesEnabled())

    def test_evidence_headers_do_not_shift_between_populated_and_empty_candidates(self):
        panel = self.window.pocket_evidence_panel
        candidate = {"id": "P1", "evidence": {"experimental_ligand_evidence": {
            "observations": [{"evidence_class": "close_structural_homolog",
                              "entry": "2R8N", "ligand": "MK1", "ca_rmsd_angstrom": 1.23}],
        }}}
        widths = []
        for value in (candidate, {"id": "P2", "evidence": {}}, candidate):
            panel.set_candidate(value)
            self.application.processEvents()
            widths.append([panel.table.columnWidth(i) for i in range(6)])
        self.assertEqual(widths[0], widths[1])
        self.assertEqual(widths[1], widths[2])

    def test_clicking_partly_visible_candidate_does_not_reposition_text(self):
        from docking_universal.gui.qt import QtCore, QtWidgets
        from docking_universal.gui.navigation_table import NavigationTable
        from PyQt6.QtTest import QTest
        table = NavigationTable(12, 2)
        table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectionBehavior.SelectRows)
        table.setVerticalScrollMode(QtWidgets.QAbstractItemView.ScrollMode.ScrollPerPixel)
        for row in range(12):
            table.setItem(row, 0, QtWidgets.QTableWidgetItem(f"P{row + 1}"))
        table.resize(400, 120)
        table.show()
        self.application.processEvents()
        table.verticalScrollBar().setValue(12)
        before = table.verticalScrollBar().value()
        item = table.item(0, 0)
        visible = table.visualItemRect(item).intersected(table.viewport().rect())
        self.assertFalse(visible.isEmpty())
        QTest.mouseClick(table.viewport(), QtCore.Qt.MouseButton.LeftButton, pos=visible.center())
        self.application.processEvents()
        self.assertEqual(table.verticalScrollBar().value(), before)
        table.scrollTo(table.model().index(11, 0))
        self.assertGreater(table.verticalScrollBar().value(), before)
        table.close()

    def test_evidence_opens_structure_without_a_retained_report_scene(self):
        from unittest.mock import Mock
        viewer = Mock()
        viewer.connected = False
        viewer.status = "disconnected"
        viewer.backend_kind = "embedded"
        viewer.open.side_effect = lambda state: setattr(viewer, "connected", True)
        self.window.viewer_coordinator = viewer
        self.window._selected_structure_scene = None
        with patch.object(self.window, "open_visual_review") as report_route:
            self.window.show_evidence_ligand("aligned-one.pdb")
            viewer.open.assert_called_once_with(self.window.state)
            viewer.show_evidence_ligand.assert_called_once_with("aligned-one.pdb", None)
            report_route.assert_not_called()
            viewer.connected = False
            viewer.open.reset_mock()
            self.window.show_evidence_ligands(["aligned-one.pdb", "aligned-two.pdb"])
            viewer.open.assert_called_once_with(self.window.state)
            viewer.show_evidence_ligands.assert_called_once_with(
                ["aligned-one.pdb", "aligned-two.pdb"], None,
            )
            report_route.assert_not_called()

    def test_plot_click_selects_candidate_and_loads_3d_without_report(self):
        from PyQt6.QtTest import QTest
        from docking_universal.gui.qt import QtCore

        class Viewer:
            backend_kind = "embedded"
            backend_name = "Embedded PyMOL"
            connected = False
            report_view_available = False
            status = "disconnected"

            def open(self, state):
                self.connected = True

            def show_candidate(self, state, candidate_id):
                self.candidate_id = candidate_id

        state = self.window.state
        state.workflow_data["pocket_candidates"].append({
            "id": "P2", "rank": 2, "evidence": {"score": 0.4},
        })
        self.window._render_candidates(state)
        viewer = Viewer()
        self.window.viewer_coordinator = viewer
        plot = self.window.pocket_score_plot
        QTest.mouseClick(plot, QtCore.Qt.MouseButton.LeftButton,
                         pos=plot.positions()[1].toPoint())
        self.assertTrue(viewer.connected)
        self.assertEqual(viewer.candidate_id, "P2")
        self.assertEqual(self.window.candidates.selectionModel().selectedRows()[0].row(), 1)
        self.assertEqual(plot.selected, "P2")
        self.assertEqual(state.selected_pocket_ids, [])

    def test_site_review_keeps_pose_controls_out_of_the_viewport_layout(self):
        from docking_universal.gui.qt import QtWidgets
        from unittest.mock import Mock

        viewer = Mock(connected=True, status='connected', report_view_available=False)
        window = StudyWindow(self.store, 'desktop', settings=self.settings,
                             viewer_coordinator=viewer, viewer_widget=QtWidgets.QFrame())
        self.addCleanup(window.close)
        window._workflow_target = 'central'
        window._update_stage_review_visibility()
        self.assertTrue(window.pose_review_controls.isHidden())
        controls = window.pymol_controls.layout()
        self.assertEqual(controls.getItemPosition(controls.indexOf(window.detach_viewer_button))[0], 0)
        self.assertEqual(controls.itemAtPosition(0, 2).layout().indexOf(window.all_pockets_toggle), 0)
        window._workflow_target = 'screening_results_dock'
        window._update_stage_review_visibility()
        self.assertFalse(window.pose_review_controls.isHidden())

    def test_results_opens_2d_3d_from_only_one_control(self):
        from docking_universal.gui.qt import QtWidgets
        from unittest.mock import Mock

        viewer = Mock(connected=True, status='connected', report_view_available=False)
        window = StudyWindow(self.store, 'desktop', settings=self.settings,
                             viewer_coordinator=viewer, viewer_widget=QtWidgets.QFrame())
        self.addCleanup(window.close)
        window._activate_workflow_target('screening_results_dock')
        window.show()
        self.application.processEvents()
        self.assertFalse(window.open_interaction_diagram_button.isHidden())
        window.linked_pose_panel.show()
        self.application.processEvents()
        self.assertTrue(window.open_interaction_diagram_button.isHidden())
        window.linked_pose_panel.hide()
        self.application.processEvents()
        self.assertFalse(window.open_interaction_diagram_button.isHidden())

    def test_initial_embedded_review_loads_the_already_selected_p1_once(self):
        from docking_universal.gui.qt import QtWidgets
        from unittest.mock import Mock
        receptor = self.root / "receptor.pdb"
        receptor.write_text("END\n")
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord("receptor", "prepared_receptor_structure", str(receptor), "retained-hash"))
        state.workflow_data["pocket_candidates"][0]["evidence"]["geometry"] = {
            **{f"center_{axis}": 0 for axis in "xyz"},
            **{f"size_{axis}": 20 for axis in "xyz"},
        }
        self.store.save(state)
        viewer = Mock(connected=False, status="disconnected", report_view_available=False)
        viewer.open.side_effect = lambda _state: setattr(viewer, "connected", True)
        viewer.refresh_health.return_value = True
        window = StudyWindow(self.store, "desktop", settings=self.settings,
                             viewer_coordinator=viewer, viewer_widget=QtWidgets.QFrame())
        try:
            self.assertEqual(window.candidates.selectionModel().selectedRows()[0].row(), 0)
            viewer.open.assert_not_called()
            window.show()
            self.application.processEvents()
            viewer.open.assert_called_once_with(window.state)
            viewer.show_candidate.assert_called_once_with(window.state, "P1")
            self.assertEqual(window.state.selected_pocket_ids, [])
            window.refresh()
            window.refresh()
            self.application.processEvents()
            self.assertEqual(viewer.show_candidate.call_count, 1)
            # Even re-entering the tab must not overwrite an existing camera.
            window._review_mode_changed(0)
            window._review_mode_changed(0)
            self.application.processEvents()
            self.assertEqual(viewer.show_candidate.call_count, 1)
            # An explicit click on the default row also works if initialization
            # had been delayed (there is no itemSelectionChanged signal).
            viewer.connected = False
            window.candidates.itemClicked.emit(window.candidates.item(0, 0))
            self.application.processEvents()
            self.assertEqual(viewer.open.call_count, 2)
            self.assertEqual(viewer.show_candidate.call_args.args[1], "P1")
        finally:
            window.close()

    def test_initial_candidate_review_does_not_autolaunch_companion(self):
        from unittest.mock import Mock
        viewer = Mock(connected=False, status='disconnected', report_view_available=False)
        self.window.viewer_coordinator = viewer
        self.window.show()
        self.window._schedule_initial_candidate_review()
        self.application.processEvents()
        viewer.open.assert_not_called()

    def test_embedded_viewer_gets_a_real_central_tab_and_controls(self):
        from docking_universal.gui.qt import QtWidgets

        class Viewer:
            backend_name = "Embedded PyMOL"
            connected = False
            report_view_available = False
            status = "disconnected"
            last_error = None

            def refresh_health(self):
                return False

        widget = QtWidgets.QFrame()
        widget.setObjectName("real_embedded_viewport")
        window = StudyWindow(
            self.store, "desktop", settings=self.settings,
            viewer_coordinator=Viewer(), viewer_widget=widget,
        )
        try:
            self.assertEqual(window.review_tabs.count(), 1)
            self.assertEqual(window.review_tabs.tabText(0), "Interactive structure")
            self.assertIs(widget.parentWidget(), window.pose_split)
            window.review_tabs.setCurrentWidget(window.live_page)
            self.application.processEvents()
            self.assertTrue(window.pymol_controls.isVisibleTo(window))
            self.assertFalse(window.workspace_context.isVisibleTo(window))
            self.assertFalse(window.central_selection_status.isVisibleTo(window))
            self.assertFalse(window.viewer_status.isVisibleTo(window))
            self.assertGreaterEqual(
                window.candidates.maximumHeight(),
                window.candidates.horizontalHeader().height()
                + window.candidates.verticalHeader().defaultSectionSize(),
            )
            self.assertTrue(window.structure_scene_choice.isHidden())
            self.assertTrue(window.scene_choice_label.isHidden())
            self.assertTrue(window.candidate_review_button.isHidden())
            self.assertTrue(window.viewer_button.isHidden())
            self.assertTrue(window.detach_viewer_button.isVisibleTo(window))
            self.assertTrue(window.open_pose_session_button.isHidden())
            self.assertTrue(window.sync_pose_button.isHidden())
            self.assertTrue(window.smooth_site_pan.isChecked())
            self.assertFalse(window.smooth_site_pan.isHidden())
            self.assertEqual(
                window.sync_pose_button.text(),
                "Show selected pose in interactive structure",
            )
            self.assertTrue(window.pocket_evidence_panel.compare_button.isHidden())
            self.assertIn("click again to hide it", window.pocket_evidence_panel.note.text())
            visible_pymol_buttons = [
                button.text()
                for button in window.findChildren(QtWidgets.QPushButton)
                if button.isVisibleTo(window) and "PyMOL" in button.text()
            ]
            self.assertEqual(visible_pymol_buttons, ["Detach PyMOL"])
            self.assertNotIn("separate window", window.structural_view.text())
            self.assertIn("Embedded PyMOL configured", window.runtime_status.text())

            window.detach_embedded_viewer()
            self.application.processEvents()
            detached = window._detached_structure_window
            self.assertIsNotNone(detached)
            self.assertTrue(detached.isMaximized())
            self.assertFalse(detached.isFullScreen())
            self.assertIs(widget.window(), detached)
            self.assertIs(window.linked_pose_panel.parentWidget(), window.pose_split)
            window.linked_pose_panel.detach_diagram()
            self.application.processEvents()
            self.assertIsNone(window._detached_structure_window)
            self.assertIs(widget.parentWidget(), window.pose_split)
            self.assertIsNotNone(window.linked_pose_panel._detached_window)
            window.detach_embedded_viewer()
            self.application.processEvents()
            self.assertIsNone(window.linked_pose_panel._detached_window)
            self.assertIs(window.linked_pose_panel.parentWidget(), window.pose_split)
            detached = window._detached_structure_window
            detached.close()
            self.application.processEvents()
            self.assertIsNone(window._detached_structure_window)
            self.assertIs(widget.parentWidget(), window.pose_split)
        finally:
            window.close()

    def test_widget_without_viewer_backend_is_rejected(self):
        from docking_universal.gui.qt import QtWidgets

        with self.assertRaisesRegex(ValueError, "requires a viewer coordinator"):
            StudyWindow(
                self.store, "desktop", settings=self.settings,
                viewer_widget=QtWidgets.QFrame(),
            )

    def test_embedded_evidence_selection_never_lowers_the_gui(self):
        class Adapter:
            backend_kind = "embedded"

        class Viewer:
            backend_kind = "embedded"
            backend_name = "Embedded PyMOL"
            connected = True
            adapter = Adapter()

            def sync_evidence_ligands(self, paths):
                self.paths = paths

        viewer = Viewer()
        self.window.viewer_coordinator = viewer
        self.window.viewer_widget = object()
        with patch.object(self.window, "_send_windows_back") as lowered:
            self.window.sync_evidence_selection(["one.pdb", "two.pdb"])
        lowered.assert_not_called()
        self.assertEqual(viewer.paths, ["one.pdb", "two.pdb"])
        self.assertIn("Embedded PyMOL synchronized", self.window.viewer_status.text())

    def test_scene_menu_distinguishes_sites_and_compounds(self):
        from types import SimpleNamespace
        report = self.root / 'scene-menu'
        report.mkdir()
        scenes = [report / f'pocket_evidence_site_{site}_AB.pse' for site in (1, 2)]
        for scene in scenes:
            scene.touch()
        state = SimpleNamespace(artifacts=[
            SimpleNamespace(path=str(scene), kind='report_view_session') for scene in scenes
        ], workflow_data={})
        self.window._refresh_structure_scenes(state)
        labels = [self.window.structure_scene_choice.itemText(i)
                  for i in range(self.window.structure_scene_choice.count())]
        self.assertEqual(labels, ['Deposited-ligand site evidence — Site 1',
                                  'Deposited-ligand site evidence — Site 2'])

    def test_embedded_scene_dropdown_loads_scene_without_leaving_structure_tab(self):
        from docking_universal.gui.qt import QtWidgets

        report = self.root / "report"
        report.mkdir()
        first_figure = report / "cavity_panels_AB.png"
        first_scene = report / "cavity_panel_B_structure.pse"
        second_figure = report / "cavity_selected_box.png"
        second_scene = report / "cavity_selected_box.pse"
        two_d_figure = report / "compound_selected_interactions_ABC.png"
        for path in (first_figure, first_scene, second_figure, second_scene, two_d_figure):
            path.write_bytes(b"retained")
        state = self.store.load("desktop")
        state.artifacts.extend([
            ArtifactRecord("fig-1", "final_report_figure", str(first_figure)),
            ArtifactRecord("fig-2", "final_report_figure", str(second_figure)),
            ArtifactRecord("fig-3", "final_report_figure", str(two_d_figure)),
        ])
        self.store.save(state)

        class Viewer:
            backend_kind = "embedded"
            backend_name = "Embedded PyMOL"
            connected = True
            report_view_available = True
            report_view_name = "initial"
            status = "connected"
            last_error = None

            def refresh_health(self):
                return True

            def open_scene(self, path):
                self.opened = Path(path)
                self.report_view_name = self.opened.stem

        viewer = Viewer()
        widget = QtWidgets.QFrame()
        window = StudyWindow(
            self.store, "desktop", settings=self.settings,
            viewer_coordinator=viewer, viewer_widget=widget,
        )
        try:
            self.assertEqual(window.structure_scene_choice.count(), 2)
            window.review_tabs.setCurrentWidget(window.live_page)
            window.structure_scene_choice.setCurrentIndex(1)
            self.application.processEvents()
            self.assertEqual(viewer.opened, second_scene.resolve())
            self.assertEqual(window.review_tabs.currentIndex(), 0)
            self.assertEqual(window.review_tabs.count(), 1)
        finally:
            window.close()

    def test_static_image_open_is_blocked_but_report_open_remains(self):
        image = self.root / 'report-panel.png'
        image.write_bytes(b'retained image')
        report = self.root / 'report.pdf'
        report.write_bytes(b'retained report')
        with patch('docking_universal.gui.desktop.QtGui.QDesktopServices.openUrl', return_value=True) as opened, \
                patch('docking_universal.gui.desktop.QtWidgets.QMessageBox.information') as message:
            self.window._open_path(image)
            opened.assert_not_called()
            message.assert_called_once()
            self.window._open_path(report)
            opened.assert_called_once()

    def test_scientific_host_failure_is_visible_and_reconnectable(self):
        class Host:
            connected = False
            runtime = {}

            def __init__(self):
                self.restarts = 0

            def restart(self):
                self.restarts += 1
                self.connected = True
                self.runtime = {
                    "python_version": "3.9.23",
                    "conda_environment": "docking-universal",
                }

        host = Host()
        self.window.host_client = host
        self.window.refresh()
        self.assertTrue(self.window.reconnect_services_button.isVisibleTo(self.window))
        self.assertIn("SCIENTIFIC HOST DISCONNECTED", self.window.runtime_status.text())
        self.assertFalse(self.window.host_controller.available)

        self.window.reconnect_scientific_host()
        self.assertEqual(host.restarts, 1)
        self.assertTrue(self.window.host_controller.available)
        self.assertFalse(self.window.reconnect_services_button.isVisibleTo(self.window))
        self.assertIn("docking-universal", self.window.runtime_status.text())

    def test_panels_are_floatable_without_redundant_window_fullscreen_action(self):
        from docking_universal.gui.qt import QtWidgets
        docks = self.window.findChildren(QtWidgets.QDockWidget)
        self.assertGreaterEqual(len(docks), 5)
        self.assertIsNotNone(self.window.findChild(QtWidgets.QDockWidget, "pocket_evidence_dock"))
        self.assertIsNotNone(self.window.findChild(QtWidgets.QDockWidget, "study_setup_dock"))
        self.assertTrue(all(dock.features() & QtWidgets.QDockWidget.DockWidgetFloatable for dock in docks))
        self.assertNotIn("Full Screen", [action.text() for action in self.window.view_toolbar.actions()])
        self.assertFalse(any(action.shortcut().toString() == "F11" for action in self.window.view_toolbar.actions()))

    def test_saved_files_use_plain_language_and_keep_existing_dock_toggle(self):
        self.assertEqual(self.window.artifacts_action.text(), "Study files")
        self.assertEqual(self.window.reports_dock.windowTitle(), "Reports and Study Files")
        self.assertEqual(self.window.preparation_progress_panel.artifacts_button.text(), "Show study files")
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord("example", "prepared_receptor_structure", str(self.root / "receptor.pdb"), "hash"))
        self.window._render_artifacts(state)
        item = self.window.report_list.item(self.window.report_list.count() - 1)
        self.assertIn("Prepared receptor structure", item.text())
        self.assertNotIn("artifact", item.toolTip().lower())

    def test_study_menu_exposes_new_and_open_actions(self):
        self.assertEqual(self.window.current_study_action.text(), "Current: desktop")
        self.assertEqual(self.window.new_study_action.text(), "New study…")
        self.assertEqual(self.window.open_study_action.text(), "Open study…")

    def test_retained_setup_replaces_draft_values_and_is_read_only(self):
        receptor = self.root / "retained.pdb"
        receptor.write_text("ATOM\n")
        state = self.store.load("desktop")
        state.workflow_data["study_setup"] = {
            "input_pdb": str(receptor.resolve()),
            "working_directory": str((self.root / "retained-output").resolve()),
            "site_mode": "ligand",
            "ligand_resname": "LIG",
            "ligand_chain_id": "B",
            "ligand_residue_number": "201",
            "ligand_insertion_code": "A",
            "ligand_altloc": "B",
            "pocket_engine": "p2rank",
            "pdb_pocket_evidence": "related-structures",
        }
        self.store.save(state)
        self.window.refresh()
        self.assertEqual(self.window.input_pdb.text(), str(receptor.resolve()))

        self.assertEqual(self.window.study_setup_panel.ligand_value(), "LIG")
        self.assertEqual(
            self.window.study_setup_panel.ligand_identity()["chain_id"], "B"
        )
        self.assertFalse(self.window.input_pdb.isEnabled())
        self.assertFalse(self.window.output_directory.isEnabled())
        self.assertFalse(self.window.start_preparation_button.isEnabled())

    def test_failed_pdb_lookup_is_visible_after_poll_without_changing_candidates(self):
        state = self.store.load('desktop')
        state.workflow_data['pdb_pocket_evidence'] = {
            'mode': 'related-structures', 'status': 'unavailable', 'detail': 'DNS lookup failed'}
        self.store.save(state)
        self.window.refresh()
        label = self.window.pocket_evidence_panel.lookup_status
        self.assertFalse(label.isHidden())
        self.assertIn('PDB search failed', label.text())
        self.assertIn('does not mean none exists', label.text())
        self.assertNotIn('no qualifying observations', label.text())
        self.assertIn('DNS lookup failed', label.toolTip())
        before = label.text()
        self.window.refresh()
        self.assertEqual(label.text(), before)
        label.show_explanation()
        self.assertIn('DNS lookup failed', label.explanation_window.content.toPlainText())
        label.explanation_window.close()
        # A successful empty search is a different visible result, with no stale failure.
        state = self.store.load('desktop')
        state.workflow_data['pdb_pocket_evidence'] = {
            'mode': 'related-structures', 'status': 'completed', 'coverage': {'observation_count': 0}}
        self.store.save(state)
        self.window.refresh()
        self.assertIn('PDB search completed', label.text())
        self.assertIn('no qualifying observations', label.text())
        self.assertNotIn('DNS lookup failed', label.toolTip())
        self.assertNotIn('search failed', label.text())

    def test_older_completed_study_recovers_setup_from_retained_artifacts(self):
        receptor = self.root / "legacy-source.pdb"
        receptor.write_text("ATOM\n")
        preparation_root = self.root / "legacy-work" / "legacy_receptor_prep"
        state = self.store.load("desktop")
        state.jobs.insert(0, Job(
            id="legacy-preparation", stage="preparation_and_pocket_detection",
            status=JobStatus.COMPLETED,
        ))
        state.artifacts.append(ArtifactRecord(
            "legacy-source", "source_receptor_structure", str(receptor.resolve())
        ))
        state.workflow_data["preparation_root"] = str(preparation_root.resolve())
        state.workflow_data.pop("study_setup", None)
        self.store.save(state)
        self.window.refresh()
        self.assertEqual(self.window.input_pdb.text(), str(receptor.resolve()))
        self.assertEqual(
            self.window.output_directory.text(), str(preparation_root.parent.resolve())
        )
        self.assertIn("predates the setup record", self.window.study_setup_panel.lock_notice.text())
        self.assertFalse(self.window.input_pdb.isEnabled())

    def test_workspace_shell_has_persistent_navigation_and_structural_center(self):
        from docking_universal.gui.qt import QtWidgets
        self.assertGreaterEqual(self.window.minimumWidth(), 1100)
        self.assertGreaterEqual(self.window.minimumHeight(), 700)
        self.assertEqual(self.window.workspace_heading.text(), "Structural Review")
        self.assertEqual(self.window.structural_view.objectName(), "central_structural_review")
        self.assertEqual(self.window.workflow_navigation.count(), 6)
        self.assertTrue(
            self.window.workflow_navigation_dock.features()
            & QtWidgets.QDockWidget.DockWidgetClosable
        )

        initial_window_size = self.window.size()
        initial_center_width = self.window.centralWidget().width()

        self.window.workflow_navigation.setCurrentRow(0)
        self.assertIs(
            self.window.workflow_stage_stack.currentWidget(),
            self.window.study_setup_panel,
        )
        self.window.workflow_navigation.setCurrentRow(1)
        self.assertIs(
            self.window.workflow_stage_stack.currentWidget(),
            self.window.preparation_progress_panel,
        )
        self.assertIsNot(
            self.window.preparation_progress_panel,
            self.window.study_setup_panel,
        )

        self.window.workflow_navigation.setCurrentRow(3)
        self.application.processEvents()
        self.assertEqual(self.window.study_setup_dock.windowTitle(), "Finalize Protocol")
        self.assertTrue(self.window.stage_form_scroll.isVisibleTo(self.window))
        self.assertTrue(self.window.study_setup_dock.isHidden())
        self.assertTrue(self.window.protocol_finalization_dock.isHidden())
        self.assertIs(
            self.window.workflow_stage_stack.currentWidget(),
            self.window.protocol_finalization_panel,
        )
        self.assertIs(
            self.window.right_review_stack.currentWidget(),
            self.window.right_review_blank,
        )
        self.assertTrue(self.window.pocket_evidence_dock.isHidden())
        self.assertTrue(self.window.screening_results_dock.isHidden())
        self.assertEqual(self.window.size(), initial_window_size)
        self.assertGreaterEqual(self.window.centralWidget().width(), initial_center_width)

        self.window.workflow_navigation.setCurrentRow(4)
        self.application.processEvents()
        self.assertEqual(self.window.study_setup_dock.windowTitle(), "Screen Ligands")
        self.assertEqual(self.window.size(), initial_window_size)
        self.assertGreaterEqual(self.window.centralWidget().width(), initial_center_width)
        self.assertIs(
            self.window.workflow_stage_stack.currentWidget(),
            self.window.screening_setup_panel,
        )
        self.assertTrue(self.window.screening_dock.isHidden())

        self.window.workflow_navigation.setCurrentRow(2)
        self.application.processEvents()
        self.assertEqual(self.window.study_setup_dock.windowTitle(), "Review and Decide")
        self.assertEqual(self.window.size(), initial_window_size)
        self.assertTrue(self.window.stage_form_scroll.isHidden())
        self.assertTrue(self.window.study_setup_dock.isHidden())
        self.assertFalse(self.window.protocol_finalization_dock.isVisibleTo(self.window))
        self.assertFalse(self.window.screening_dock.isVisibleTo(self.window))
        self.assertIs(
            self.window.workflow_stage_stack.currentWidget(),
            self.window.workflow_stage_blank,
        )
        self.assertIs(
            self.window.right_review_stack.currentWidget(),
            self.window.pocket_evidence_page,
        )
        self.assertFalse(self.window.pocket_evidence_dock.isHidden())
        self.assertTrue(self.window.screening_results_dock.isHidden())

        self.window.workflow_navigation.setCurrentRow(5)
        self.application.processEvents()
        self.assertEqual(self.window.study_setup_dock.windowTitle(), "Results Review")
        self.assertFalse(self.window.pocket_evidence_dock.isHidden())
        self.assertTrue(self.window.screening_results_dock.isHidden())
        self.assertIs(
            self.window.right_review_stack.currentWidget(),
            self.window.results_review_panel,
        )

    def test_rapid_stage_switching_does_not_reflow_or_stall_the_workspace(self):
        initial_window_size = self.window.size()
        initial_center_geometry = self.window.centralWidget().geometry()

        for _cycle in range(25):
            for row in (0, 3, 4, 2, 5, 1):
                self.window.workflow_navigation.setCurrentRow(row)
                self.application.processEvents()
                self.assertEqual(self.window.size(), initial_window_size)
                self.assertEqual(
                    self.window.centralWidget().geometry(), initial_center_geometry,
                )

        self.assertEqual(self.window.workflow_navigation.currentRow(), 1)

    def test_canvas_focus_mode_reclaims_side_panel_space_and_is_reversible(self):
        self.window.focus_canvas_action.setChecked(True)
        self.application.processEvents()
        self.assertTrue(self.window.workflow_navigation_dock.isHidden())
        self.assertTrue(self.window.study_setup_dock.isHidden())
        self.assertTrue(self.window.pocket_evidence_dock.isHidden())
        self.assertEqual(self.window.focus_canvas_action.text(), "Show workflow panels")

        self.window.focus_canvas_action.setChecked(False)
        self.application.processEvents()
        self.assertFalse(self.window.workflow_navigation_dock.isHidden())
        self.assertFalse(self.window.study_setup_dock.isHidden())
        self.assertFalse(self.window.pocket_evidence_dock.isHidden())
        self.assertEqual(self.window.focus_canvas_action.text(), "Focus canvas")

    def test_workflow_navigation_exposes_next_scientific_action(self):
        from docking_universal.gui.qt import QtCore

        self.assertIn("Scientific decision required", self.window.next_required_action.text())
        self.assertTrue(self.window.workflow_navigation.item(2).text().startswith("●"))
        self.assertTrue(self.window.workflow_navigation.item(1).text().startswith("✓"))
        self.assertFalse(
            self.window.workflow_navigation.item(3).flags()
            & QtCore.Qt.ItemFlag.ItemIsEnabled
        )
        self.assertIn("waiting for your decision", self.window.active_stage_status.text())
        self.assertTrue(self.window.active_stage_progress.isHidden())

        # A refresh within the same scientific phase must not pull the user
        # away from an earlier retained stage they chose to inspect.
        self.window.workflow_navigation.setCurrentRow(1)
        self.window.refresh()
        self.assertEqual(self.window.workflow_navigation.currentRow(), 1)

        self.window.logs_dock.hide()
        self.window.show_complete_logs_button.click()
        self.assertFalse(self.window.logs_dock.isHidden())

        state = self.store.load("desktop")
        decision = state.pending_decisions[0]
        StudyController(self.store).resolve_decision(
            "desktop", decision.id, ("P1",), actor="test user",
            rationale="Selected after reviewing the retained evidence.",
            expected_revision=state.revision,
        )
        self.window.refresh()
        self.assertIn("finalize the report", self.window.next_required_action.text())
        self.assertTrue(self.window.workflow_navigation.item(2).text().startswith("✓"))
        self.assertTrue(self.window.workflow_navigation.item(3).text().startswith("●"))
        self.assertTrue(
            self.window.workflow_navigation.item(3).flags()
            & QtCore.Qt.ItemFlag.ItemIsEnabled
        )
        self.assertEqual(self.window.workflow_navigation.currentRow(), 3)

        bundle = self.root / "desktop.duprotocol"
        bundle.write_text("test bundle")
        self.store.update(
            "desktop",
            lambda updated: updated.artifacts.append(
                ArtifactRecord("bundle", "protocol_bundle", str(bundle))
            ),
        )
        self.window.refresh()
        self.assertIn("Protocol finalized", self.window.next_required_action.text())
        self.assertTrue(self.window.workflow_navigation.item(3).text().startswith("✓"))
        self.assertTrue(self.window.workflow_navigation.item(4).text().startswith("●"))
        self.assertTrue(
            self.window.workflow_navigation.item(4).flags()
            & QtCore.Qt.ItemFlag.ItemIsEnabled
        )

    def test_results_review_stays_in_workspace_without_detach_control(self):
        from docking_universal.gui.qt import QtWidgets
        self.assertIsNone(self.window.results_review_panel.findChild(QtWidgets.QPushButton, 'detach_results_review_button'))
        self.assertFalse(any(action.text() == 'Detach Results Review' for action in self.window.view_toolbar.actions()))
        self.assertFalse(self.window.screening_results_dock.isFloating())

    def test_draft_forms_restore_but_scientific_approvals_do_not(self):
        receptor = self.root / "draft receptor.pdb"
        receptor.write_text("ATOM\n")
        self.window.input_pdb.setText(str(receptor))
        self.window.output_directory.setText(str(self.root / "preparation"))
        self.window.pocket_engine.setCurrentIndex(
            self.window.pocket_engine.findData("fpocket")
        )
        self.window.final_output_directory.setText(str(self.root / "protocol"))
        self.window.protocol_ph.setValue(6.8)
        self.window.protocol_seeds.setValue(7)
        self.window.screen_ligands.setText(str(self.root / "ligands.sdf"))
        self.window.screen_output.setText(str(self.root / "screen"))
        self.window.screen_stop_on_error.setChecked(True)
        self.window.exploratory_approval.setChecked(True)
        self.window.screen_exploratory_approval.setChecked(True)
        self.window._screening_plan = {"compound_count": 99}
        self.window.close()

        self.window = StudyWindow(self.store, "desktop", settings=self.settings)
        self.assertEqual(self.window.input_pdb.text(), str(receptor))
        self.assertEqual(self.window.output_directory.text(), str(self.root / "preparation"))
        self.assertEqual(self.window.pocket_engine.currentData(), "fpocket")
        self.assertEqual(self.window.final_output_directory.text(), str(self.root / "protocol"))
        self.assertEqual(self.window.protocol_ph.value(), 6.8)
        self.assertEqual(self.window.protocol_seeds.value(), 7)
        self.assertEqual(self.window.screen_ligands.text(), str(self.root / "ligands.sdf"))
        self.assertEqual(self.window.screen_output.text(), str(self.root / "screen"))
        self.assertTrue(self.window.screen_stop_on_error.isChecked())
        self.assertFalse(self.window.exploratory_approval.isChecked())
        self.assertFalse(self.window.screen_exploratory_approval.isChecked())
        self.assertIsNone(self.window._screening_plan)

    def test_unanalysed_cluster_selects_lowest_energy_retained_pose(self):
        from types import SimpleNamespace
        from docking_universal.gui.qt import QtCore, QtWidgets
        compound = self.root / 'compound'
        analysis = compound / 'pose_analysis'
        row = {'energy_rank': '4', 'cluster_id': '7', 'site': 'primary site',
               'analysis': str(analysis), 'best_energy_kcal_per_mol': '-8.0'}
        poses = [(analysis, SimpleNamespace(cluster_id=7, pose_id=5, energy_kcal_per_mol=-7.0)),
                 (analysis, SimpleNamespace(cluster_id=7, pose_id=8, energy_kcal_per_mol=-8.0))]
        table = self.window.pose_results
        table.setRowCount(2)
        for index, (_root, pose) in enumerate(poses):
            item = QtWidgets.QTableWidgetItem(str(pose.pose_id))
            item.setData(QtCore.Qt.ItemDataRole.UserRole, (str(analysis), pose.pose_id))
            table.setItem(index, 0, item)
            table.setItem(index, 1, QtWidgets.QTableWidgetItem(str(pose.cluster_id)))
        with patch.object(self.window.results_model, 'cluster_comparison', return_value=(row,)), \
             patch.object(self.window.results_model, 'poses', return_value=poses), \
             patch.object(self.window, '_selected_screening_compound', return_value=compound), \
             patch.object(self.window, '_request_pose_interaction') as request, \
             QtCore.QSignalBlocker(table):
            self.window._populate_cluster_comparison(compound)
            self.window.cluster_comparison.selectRow(0)
            request.assert_called_once_with(analysis, 8, 7, '-8 kcal/mol', False)
            self.assertEqual(self.window.pose_review_mode.currentData(), 'clusters')
            self.assertEqual(self.window.session.selection.cluster_id, 7)
            self.assertIsNone(self.window.session.selection.pose_id)
            self.window._pose_review_mode_changed()
            self.assertEqual(self.window.pose_review_mode.currentData(), 'clusters')

    def test_uncached_pose_displays_before_interaction_analysis(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.results_controller import PoseLoadDecision
        analysis = self.root / 'analysis'
        adapter = SimpleNamespace(show_multiple_review_poses=Mock())
        coordinator = SimpleNamespace(adapter=adapter, connected=True)
        decision = PoseLoadDecision(('compound', 'site', 42), analysis, 'host_unavailable')
        with patch.object(self.window, 'viewer_widget', object()), \
             patch.object(self.window, 'viewer_coordinator', coordinator), \
             patch.object(self.window, 'linked_pose_panel', SimpleNamespace(clear_pose=Mock()), create=True), \
             patch.object(self.window.results_controller, 'select_pose', return_value=decision), \
             patch.object(self.window, 'begin_pose_interaction_loading', return_value=decision.key):
            self.window._request_pose_interaction(analysis, 42, 3, '-8.0', False)
        adapter.show_multiple_review_poses.assert_called_once_with([(analysis, 42)])

    def test_uncached_pose_requests_plip_worker(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        analysis = self.root / 'analysis'
        host = SimpleNamespace(available=True, start_pose_interaction=Mock(return_value={'result': {'job_id': 'job'}}))
        class Task:
            def __init__(self):
                self.finished = SimpleNamespace(connect=lambda callback: None)
            def start(self, operation):
                operation()
        with patch.object(self.window, 'host_controller', host), \
             patch.object(self.window, 'poseedit_runtime', {'status': 'available'}), \
             patch('docking_universal.gui.ligand_library_panel.LibraryReadTask', Task):
            self.window._request_pose_interaction(analysis, 42, 3, '-8.0', False)
        host.start_pose_interaction.assert_called_once_with(analysis, 42, self.window.state.revision)

    def test_automatic_plip_can_be_disabled_and_manually_requested(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        analysis = self.root / 'analysis'
        host = SimpleNamespace(available=True, start_pose_interaction=Mock())
        class Task:
            def __init__(self):
                self.finished = SimpleNamespace(connect=lambda callback: None)
            def start(self, operation):
                operation()
        with patch.object(self.window, 'host_controller', host), \
             patch.object(self.window, 'poseedit_runtime', {'status': 'available'}), \
             patch.object(self.window, '_auto_plip_enabled', False, create=True), \
             patch('docking_universal.gui.ligand_library_panel.LibraryReadTask', Task):
            self.window._request_pose_interaction(analysis, 42, 3, '-8.0', False)
            host.start_pose_interaction.assert_not_called()
            self.assertIn('Automatic PLIP calculation is off', self.window.interaction_diagram_view.text())
            self.window._request_pose_interaction(analysis, 42, 3, '-8.0', False, force_plip=True)
            host.start_pose_interaction.assert_called_once()

    def test_pose_waits_and_retries_when_plip_worker_busy(self):
        from types import SimpleNamespace
        analysis = self.root / 'analysis'
        class Task:
            def __init__(self):
                self.finished = SimpleNamespace(connect=self.connect)
            def connect(self, callback):
                self.callback = callback
            def start(self, operation):
                self.callback(None, 'Study example already has an active stage: pose_interaction')
            def deleteLater(self):
                pass
        host = SimpleNamespace(available=True)
        with patch.object(self.window, 'host_controller', host), \
             patch.object(self.window, 'poseedit_runtime', {'status': 'available'}), \
             patch('docking_universal.gui.ligand_library_panel.LibraryReadTask', Task), \
             patch('docking_universal.gui.desktop.QtCore.QTimer.singleShot') as schedule:
            self.window._request_pose_interaction(analysis, 42, 3, '-8.0', False)
            self.assertIn('will start automatically', self.window.interaction_diagram_view.text())
            self.assertEqual(schedule.call_args.args[0], 2000)

    def test_detached_pose_selection_displays_later_retained_poses(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        from docking_universal.gui.results_controller import PoseLoadDecision
        from docking_universal.gui.qt import QtCore, QtWidgets
        analysis = self.root / 'analysis'
        table = self.window.pose_results
        table.setSortingEnabled(False)
        table.setRowCount(3)
        for row, pose in enumerate((8, 9, 100)):
            for col in range(table.columnCount()):
                item = QtWidgets.QTableWidgetItem(str(pose if col == 0 else 1))
                item.setData(QtCore.Qt.ItemDataRole.UserRole, (str(analysis), pose))
                table.setItem(row, col, item)
        adapter = SimpleNamespace(show_multiple_review_poses=Mock())
        coordinator = SimpleNamespace(adapter=adapter, connected=True)
        def decision(**kwargs):
            pose = kwargs['pose_id']
            return PoseLoadDecision(('compound', 'site', pose), analysis, 'host_unavailable')
        with patch.object(self.window, 'viewer_widget', object()), \
             patch.object(self.window, 'viewer_coordinator', coordinator), \
             patch.object(self.window, 'linked_pose_panel', SimpleNamespace(clear_pose=Mock()), create=True), \
             patch.object(self.window.results_controller, 'select_pose', side_effect=decision), \
             patch.object(self.window, 'begin_pose_interaction_loading', side_effect=lambda *key: key):
            browser = FullPyMOLStudyPanel(self.window)
            try:
                browser.result_mode.setCurrentIndex(browser.result_mode.findData('all_poses'))
                for pose in (8, 9, 100):
                    row = next(i for i in range(browser.poses.rowCount()) if int(browser.poses.item(i, 0).text()) == pose)
                    browser.poses.selectRow(row)
                    adapter.show_multiple_review_poses.assert_called_with([(analysis, pose)])
            finally:
                browser.dispose()
                browser.close()

    def test_cluster_comparison_highlights_lowest_energy_across_sites(self):
        rows = (
            {'energy_rank': '1', 'cluster_id': '1', 'site': 'site_1', 'best_energy_kcal_per_mol': '-7.5'},
            {'energy_rank': '1', 'cluster_id': '2', 'site': 'site_2', 'best_energy_kcal_per_mol': '-9.1'},
        )
        with patch.object(self.window.results_model, 'cluster_comparison', return_value=rows):
            self.window._populate_cluster_comparison(self.root)
        table = self.window.cluster_comparison
        self.assertFalse(table.item(0, 0).font().bold())
        self.assertTrue(table.item(1, 0).font().bold())
        self.assertIn('Lowest docking energy', table.item(1, 0).toolTip())

    def test_cluster_numeric_sort_orders_values_numerically(self):
        from docking_universal.gui.qt import QtCore
        rows = tuple({'energy_rank': str(rank), 'cluster_id': str(rank), 'site': 'primary site',
                      'best_energy_kcal_per_mol': str(score), 'analysis': '/tmp/analysis'}
                     for rank, score in [(2, -7.0), (10, -10.0), (1, -9.0)])
        with patch.object(self.window.results_model, 'cluster_comparison', return_value=rows):
            self.window._populate_cluster_comparison(self.root)
        table = self.window.cluster_comparison
        table.sortItems(0, QtCore.Qt.SortOrder.AscendingOrder)
        self.assertEqual([table.item(i, 0).text() for i in range(3)], ['1', '2', '10'])
        table.sortItems(3, QtCore.Qt.SortOrder.AscendingOrder)
        self.assertEqual([table.item(i, 3).text() for i in range(3)], ['-10.0', '-9.0', '-7.0'])

    def test_multiple_clusters_overlay_representatives_and_hide_2d(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from docking_universal.gui.qt import QtCore, QtWidgets
        compound = self.root / 'compound'
        analysis = compound / 'pose_analysis'
        rows = tuple({'energy_rank': str(i), 'cluster_id': str(i), 'site': 'primary site',
                      'best_energy_kcal_per_mol': str(-i), 'analysis': str(analysis)} for i in (1, 2))
        poses = [(analysis, SimpleNamespace(cluster_id=i, pose_id=i + 10, energy_kcal_per_mol=-i)) for i in (1, 2)]
        viewer = QtWidgets.QWidget()
        linked = QtWidgets.QWidget()
        adapter = SimpleNamespace(show_multiple_review_poses=Mock())
        with patch.object(self.window.results_model, 'cluster_comparison', return_value=rows), \
             patch.object(self.window.results_model, 'poses', return_value=poses), \
             patch.object(self.window, '_selected_screening_compound', return_value=compound), \
             patch.object(self.window, 'viewer_widget', viewer), \
             patch.object(self.window, 'linked_pose_panel', linked, create=True), \
             patch.object(self.window, 'viewer_coordinator', SimpleNamespace(adapter=adapter)):
            table = self.window.cluster_comparison
            self.window._populate_cluster_comparison(compound)
            with QtCore.QSignalBlocker(table):
                for index in range(2):
                    table.selectionModel().select(table.model().index(index, 0),
                        QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)
            self.window._cluster_comparison_selected()
            adapter.show_multiple_review_poses.assert_called_once_with([(analysis, 11), (analysis, 12)])
            self.assertTrue(self.window.linked_pose_panel.isHidden())

    def test_multiple_individual_poses_are_sent_together(self):
        from docking_universal.gui.qt import QtCore, QtWidgets
        analysis = self.root / 'compound/pose_analysis'
        table = self.window.pose_results
        table.setSortingEnabled(False)
        table.setRowCount(2)
        with QtCore.QSignalBlocker(table):
            for row, pose_id in enumerate((3, 9)):
                item = QtWidgets.QTableWidgetItem(str(pose_id))
                item.setData(QtCore.Qt.ItemDataRole.UserRole, (str(analysis), pose_id))
                table.setItem(row, 0, item)
                table.setItem(row, 1, QtWidgets.QTableWidgetItem('1'))
                table.selectionModel().select(table.model().index(row, 0),
                    QtCore.QItemSelectionModel.SelectionFlag.Select | QtCore.QItemSelectionModel.SelectionFlag.Rows)
        with patch.object(self.window, '_show_multiple_result_poses') as display:
            self.window.pose_review_mode.setCurrentIndex(self.window.pose_review_mode.findData('all_poses'))
            self.window._expanded_pose_selection_changed()
            display.assert_called_once_with([(str(analysis), 3), (str(analysis), 9)])

    def test_saved_on_demand_diagram_is_safe_to_synchronize(self):
        from docking_universal.gui.qt import QtCore
        compound = self.root / 'compound'
        analysis = compound / 'pose_analysis'
        cache = analysis / 'pose_interactions' / 'pose_0042'
        cache.mkdir(parents=True)
        diagram = cache / 'interaction_diagram.png'
        diagram.write_bytes(b'png')
        self.window.state.artifacts.append(ArtifactRecord(
            'cached-pose', 'pose_interaction_diagram', str(diagram),
            metadata={'analysis_root': str(analysis), 'pose_id': 42, 'cluster_id': 7, 'score': -8.0}))
        choice = self.window.interaction_diagram_choice
        with QtCore.QSignalBlocker(choice):
            choice.clear()
            choice.addItem('On-demand cluster 7', str(diagram))
        self.window.session.select_cluster(compound, analysis, 7, site='primary site')
        self.assertEqual(choice.currentData(), str(diagram))
        with patch.object(self.window, '_selected_screening_compound', return_value=compound):
            self.window._show_selected_interaction_diagram()
        self.assertEqual(self.window.session.selection.cluster_id, 7)

    def test_results_review_shows_the_shared_nonapproval_selection(self):
        compound = self.root / "screen/compounds/ligand_a"
        analysis = compound / "pose_analysis"
        self.window.session.select_pose(
            compound, analysis, 3, 6, site="primary site",
        )
        self.application.processEvents()

        status = self.window.results_session_status.text()
        self.assertIn("ligand_a", status)
        self.assertIn("primary site", status)
        self.assertIn("cluster 3", status)
        self.assertIn("pose 6", status)
        self.assertIn("ligand_a", self.window.central_selection_status.text())
        self.assertIn("pose 6", self.window.central_selection_status.text())

    def test_status_message_does_not_follow_navigation_to_another_stage(self):
        self.window._activate_workflow_target('study_setup_dock')
        self.window.statusBar().showMessage('Choose the ligand that defines the site.')
        self.window._activate_workflow_target('screening_results_dock')
        self.assertEqual(self.window.statusBar().currentMessage(), '')
        self.assertEqual(self.store.load("desktop").approvals, [])

    def test_candidate_table_summarizes_nested_evidence_without_dumping_json(self):
        from docking_universal.gui.qt import QtWidgets

        state = self.store.load("desktop")
        state.workflow_data["pocket_candidates"] = [{
            "id": "P1", "label": "P1", "rank": 1,
            "summary": "individual p2rank pocket box",
            "evidence": {
                "automation_eligible": True,
                "detector": "p2rank",
                "conformational_site_evidence": {
                    "status": "conformationally_incompatible",
                    "occluding_residues": [{"name": "ASP", "number": 30, "chain": "A"}],
                },
                "experimental_ligand_evidence": {
                    "observation_count": 17,
                    "pdb_entry_count": 15,
                    "evidence_class_counts": {
                        "exact_sequence_match": 4,
                        "close_structural_homolog": 13,
                    },
                    "observations": [{
                        "aligned_ligand_pdb": "/private/path/that/must/not/appear.pdb",
                        "entry": "2R5P", "ligand": "MK1",
                    }],
                },
            },
        }]
        self.store.save(state)
        self.window.refresh()

        displayed = self.window.candidates.item(0, 3).text()
        self.assertEqual(
            displayed,
            "Possible ligand obstruction: ASP30A · 17 possible ligand observations; details incomplete",
        )
        self.assertNotIn("automation_eligible", displayed)
        self.assertNotIn("observations", displayed.replace("possible ligand observations", ""))
        self.assertNotIn("/private/path", displayed)

        evidence_item = self.window.candidates.item(0, 3)
        self.window._show_candidate_evidence_details(evidence_item)
        self.application.processEvents()
        self.assertEqual(len(self.window._candidate_evidence_dialogs), 1)
        dialog = self.window._candidate_evidence_dialogs[0]
        self.assertTrue(dialog.isVisible())
        complete_text = dialog.findChild(QtWidgets.QPlainTextEdit).toPlainText()
        self.assertIn("aligned_ligand_pdb", complete_text)
        self.assertIn("/private/path/that/must/not/appear.pdb", complete_text)
        dialog.close()

    def test_pymol_failure_becomes_reconnectable_shared_state(self):
        class Viewer:
            connected = False
            report_view_available = False
            status = "disconnected"
            last_error = None

            def __init__(self):
                self.reconnects = 0
                self.opens = 0

            def open_scene(self, _scene):
                self.opens += 1
                if self.opens == 1:
                    self.status = "failed"
                    self.last_error = "viewer exited"
                    raise RuntimeError("viewer exited")
                self.connected = True
                self.report_view_available = True
                self.status = "connected"
                self.report_view_name = "selected_figure"

            def reconnect(self, _state):
                self.reconnects += 1
                self.connected = True
                self.status = "connected"

        viewer = Viewer()
        self.window.viewer_coordinator = viewer
        scene = self.root / "selected_figure.pse"
        scene.write_bytes(b"scene")
        self.window._selected_structure_scene = scene
        with patch("docking_universal.gui.qt.QtWidgets.QMessageBox.critical"):
            self.window.open_visual_review()
        self.assertEqual(self.window.session.viewer.lifecycle, "failed")
        self.assertEqual(self.window.viewer_button.text(), "Reconnect PyMOL")

        self.window.open_visual_review()
        self.assertEqual(viewer.reconnects, 1)
        self.assertEqual(self.window.session.viewer.lifecycle, "connected")
        self.assertTrue(self.window.session.viewer.connected)

    def test_refresh_and_layout_do_not_rewrite_scientific_state(self):
        before = self.store.path_for("desktop").read_bytes()
        self.window.refresh()
        self.window.close()
        after = self.store.path_for("desktop").read_bytes()
        self.assertEqual(after, before)

    def test_artifact_rows_retain_the_exact_openable_path(self):
        state = self.store.load("desktop")
        path = self.root / "scientific-record.json"
        path.write_text("{}\n")
        artifact = ArtifactRecord("record", "scientific_record", str(path))
        state.artifacts.append(artifact)
        self.store.save(state)
        self.window.refresh()
        matching = [
            self.window.report_list.item(index)
            for index in range(self.window.report_list.count())
            if artifact.path in self.window.report_list.item(index).text()
        ]
        self.assertEqual(len(matching), 1)
        from docking_universal.gui.qt import QtCore
        self.assertEqual(matching[0].data(QtCore.Qt.UserRole), artifact.path)

    def test_decision_synopsis_and_complete_report_are_both_available(self):
        from docking_universal.gui.qt import QtGui
        report = self.root / "preliminary-pocket-review.pdf"
        report.write_bytes(b"%PDF-1.4\n%%EOF\n")
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "pocket-review-report", "preliminary_report", str(report),
            description="Complete pocket-review synopsis",
        ))
        self.store.save(state)
        self.window.refresh()
        self.assertTrue(self.window.decision_synopsis_button.isEnabled())
        self.assertTrue(self.window.full_synopsis_button.isEnabled())
        with patch.object(QtGui.QDesktopServices, "openUrl", return_value=True) as opened:
            self.window.show_full_synopsis_report()
        self.assertEqual(Path(opened.call_args.args[0].toLocalFile()).resolve(), report.resolve())

    def test_preparation_intervention_is_presented_as_its_own_required_action(self):
        state = self.store.load("desktop")
        state.decisions = [DecisionRequired(
            id="histidine-review", kind="select_histidine_template",
            prompt="Choose the justified histidine state for A:57",
            detected="Meeko could not distinguish the deposited state.",
            why_stopped="The choice changes the receptor model.",
            consequences=("The selected template will be retained.",),
            options=(DecisionOption("HIE_CURRENT", "HIE", "Proton on NE2"),),
            changes_molecular_model=True,
            continuation={
                "action": "continue_stage",
                "checkpoint": "rerun_preparation_with_histidine_template",
            },
        )]
        state.jobs[0].stage = "preparation_and_pocket_detection"
        state.jobs[0].status = JobStatus.WAITING_FOR_DECISION
        self.store.save(state)

        self.window.refresh()

        self.assertEqual(
            self.window.decision_synopsis_button.text(), "Review preparation decision…",
        )
        self.assertFalse(self.window.approve_button.isEnabled())
        self.assertIn(
            "required molecular-model decision",
            self.window.preparation_progress_panel.status.text(),
        )

    def test_table_selection_is_only_a_proposal_until_approval_button(self):
        class FakeHost:
            def __init__(self, store):
                self.store = store
                self.calls = []

            def request(self, study_id, operation, payload, *, expected_revision):
                self.calls.append((study_id, operation, payload, expected_revision))
                controller = StudyController(self.store)
                controller.resolve_decision(
                    study_id, payload["decision_id"], tuple(payload["selections"]),
                    actor=payload["actor"], rationale=payload["rationale"],
                    expected_revision=expected_revision,
                )
                return {"status": "applied"}

        host = FakeHost(self.store)
        self.window.host_client = host
        self.window.refresh()
        self.window.candidates.selectRow(0)
        self.assertEqual(self.store.load("desktop").approvals, [])
        self.window.rationale.setText("Reviewed in required structure view")
        self.window.approve_button.click()
        from PyQt6.QtTest import QTest
        for _ in range(50):
            if not self.window._pocket_approval_pending:
                break
            QTest.qWait(20)
        self.assertFalse(self.window._pocket_approval_pending)
        self.assertEqual(len(host.calls), 1)
        state = self.store.load("desktop")
        self.assertEqual(state.selected_pocket_ids, ["P1"])
        self.assertEqual(state.approvals[0].rationale, "Reviewed in required structure view")

    def test_completed_preparation_cannot_be_restarted_from_setup_panel(self):
        state = self.store.load("desktop")
        state.jobs[0].stage = "preparation_and_pocket_detection"
        state.jobs[0].status = JobStatus.COMPLETED
        state.decisions.clear()
        self.store.save(state)
        self.window.host_client = object()
        self.window.refresh()
        self.assertFalse(self.window.start_preparation_button.isEnabled())

    def test_setup_panel_submits_only_explicit_noninteractive_options(self):
        class FakeHost:
            def __init__(self):
                self.calls = []

            def request(self, study_id, operation, payload, *, expected_revision):
                self.calls.append((study_id, operation, payload, expected_revision))
                return {"status": "applied"}

        controller = StudyController(self.store)
        controller.create_study("setup", "Setup study")
        receptor = self.root / "input receptor.pdb"
        receptor.write_text("ATOM\n")
        host = FakeHost()
        from docking_universal.gui.qt import QtCore
        settings = QtCore.QSettings(str(self.root / "setup.ini"), QtCore.QSettings.IniFormat)
        window = StudyWindow(self.store, "setup", settings=settings, host_client=host)
        try:
            window.input_pdb.setText(str(receptor))
            window.output_directory.setText(str(self.root / "output directory"))
            window.detail.setCurrentText("Teaching")
            window.start_preparation()
            self.assertEqual(len(host.calls), 1)
            study_id, operation, payload, revision = host.calls[0]
            self.assertEqual((study_id, operation), ("setup", "start_receptor_preparation"))
            self.assertEqual(payload["site_mode"], "pockets")
            self.assertEqual(payload["max_pockets"], 0)
            self.assertEqual(payload["feedback_level"], "verbose")
            self.assertIsNone(payload["meeko_template_file"])
            self.assertEqual(revision, self.store.load("setup").revision)
            self.assertNotIn("command", payload)
        finally:
            window.close()

    def test_finalization_requires_approval_and_submits_locked_gui_settings(self):
        class FakeHost:
            def __init__(self):
                self.calls = []

            def request(self, study_id, operation, payload, *, expected_revision):
                self.calls.append((study_id, operation, payload, expected_revision))
                return {"status": "applied"}

        controller = StudyController(self.store)
        state = self.store.load("desktop")
        decision = state.pending_decisions[0]
        controller.resolve_decision("desktop", decision.id, ("P1",), actor="scientist")
        state = self.store.load("desktop")
        state.workflow_data["preparation_root"] = str(self.root / "Target_receptor_prep")
        self.store.save(state)
        host = FakeHost()
        self.window.host_client = host
        self.window.refresh()
        self.assertFalse(self.window.finalize_button.isEnabled())
        self.window.exploratory_approval.setChecked(True)
        self.assertTrue(self.window.finalize_button.isEnabled())
        self.window.protocol_engine.setCurrentIndex(1)
        self.window.protocol_ph.setValue(6.8)
        self.window.protocol_conformers.setValue(7)
        self.window.protocol_seeds.setValue(4)
        self.window.protocol_base_seed.setValue(99001)
        self.window.protocol_exhaustiveness.setValue(32)
        self.window.finalize_button.click()
        from PyQt6.QtTest import QTest
        for _ in range(100):
            if not getattr(self.window, '_starting_protocol', False):
                break
            QTest.qWait(20)
        self.assertFalse(self.window._starting_protocol)
        self.assertEqual(len(host.calls), 1)
        study_id, operation, payload, revision = host.calls[0]
        self.assertEqual((study_id, operation), ("desktop", "start_protocol_finalization"))
        self.assertTrue(payload["exploratory_use_approved"])
        self.assertEqual(payload["engine"], "qvinaw")
        self.assertEqual(payload["ph"], 6.8)
        self.assertEqual(payload["conformers"], 7)
        self.assertEqual(payload["seed_count"], 4)
        self.assertEqual(payload["base_seed"], 99001)
        self.assertEqual(payload["exhaustiveness"], 32)
        self.assertEqual(revision, self.store.load("desktop").revision)

    def test_completed_bundle_disables_duplicate_finalization_and_remains_openable(self):
        bundle = self.root / "target.duprotocol"
        bundle.write_bytes(b"bundle")
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "final-protocol-bundle", "protocol_bundle", str(bundle), description="Portable protocol",
        ))
        self.store.save(state)
        self.window.host_client = object()
        self.window.exploratory_approval.setChecked(True)
        self.window.refresh()
        self.assertFalse(self.window.finalize_button.isEnabled())
        self.assertIn(str(bundle), self.window.finalization_status.text())
        self.assertTrue(self.window.open_bundle_location_button.isEnabled())

    def test_screening_preview_is_required_before_locked_run(self):
        window = self.window
        class FakeHost:
            def __init__(self):
                self.calls = []
                self.exploratory_required = True

            def request(self, study_id, operation, payload, *, expected_revision=None):
                self.calls.append((study_id, operation, payload, expected_revision))
                if operation == "screening_plan":
                    return {"result": {"plan": {
                        "protocol_type": "site-guided-exploratory", "engine": "vina",
                        "compound_count": 2, "conformers_per_compound": 3,
                        "independent_seed_count": 5, "docking_site_count": 2,
                        "jobs_per_compound": 30, "total_docking_jobs": 60,
                        "exploratory_authorization_required": self.exploratory_required, "parameters": {},
                    }}}
                if operation == 'start_screening':
                    self.submission_feedback = (window.feedback_heading.text(),
                                                window._stage_submission_in_progress,
                                                window.start_screening_button.isEnabled())
                return {"status": "applied"}

        bundle = self.root / "target.duprotocol"
        bundle.write_bytes(b"bundle")
        ligands = self.root / "ligands.sdf"
        ligands.write_text("one\n$$$$\ntwo\n$$$$\n")
        controller = StudyController(self.store)
        pending = self.store.load("desktop").pending_decisions[0]
        controller.resolve_decision("desktop", pending.id, ("P1",), actor="scientist")
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "final-protocol-bundle", "protocol_bundle", str(bundle), description="Portable protocol",
        ))
        self.store.save(state)
        host = FakeHost()
        self.window.host_client = host
        self.window.screen_ligands.setText(str(ligands))
        self.window.screen_output.setText(str(self.root / "screen"))
        self.window.refresh()
        self.assertFalse(self.window.start_screening_button.isEnabled())
        self.window.preview_screening()
        self.assertIn("60 sequential docking searches", self.window.screening_status.text())
        self.assertIn("docking has not started", self.window.screening_status.text())
        self.assertFalse(self.window.screening_setup_panel.inline_explanations['approval'].isHidden())
        self.assertFalse(self.window.start_screening_button.isEnabled())
        self.window.screen_exploratory_approval.setChecked(True)
        self.assertTrue(self.window.start_screening_button.isEnabled())
        self.window.start_screening_button.click()
        from PyQt6.QtTest import QTest
        for _ in range(100):
            if not getattr(self.window, '_starting_screening', False):
                break
            QTest.qWait(20)
        self.assertFalse(self.window._starting_screening)
        self.assertEqual(host.calls[-1][1], "start_screening")
        self.assertEqual(host.calls[-1][2]["analysis"], "representatives")
        self.assertTrue(host.calls[-1][2]["exploratory_use_approved"])
        self.assertEqual(host.submission_feedback, ('STARTING — Screening selected compounds', True, False))
        self.assertFalse(self.window._stage_submission_in_progress)
        host.exploratory_required = False
        self.window.preview_screening()
        self.assertTrue(self.window.screen_exploratory_approval.isHidden())
        self.assertTrue(self.window.screening_setup_panel.inline_explanations['approval'].isHidden())

    def test_leaving_results_defers_plip_presentation_without_stopping_batch(self):
        from types import SimpleNamespace

        result = SimpleNamespace(name='first', path=self.root / 'first', status='complete',
                                 site_count=1, planned_jobs=1, best_score=-7,
                                 scoring_function='Vina', cluster_count=1)
        batch = {'queue': [], 'job': 'current-plip', 'starting': False, 'stopped': False}
        with patch.object(self.window.results_model, 'compounds', return_value=[result]), \
             patch.object(self.window, '_screening_result_selection_changed') as present, \
             patch.object(self.window.results_controller, 'completed_artifact', return_value=None) as completed:
            self.window._activate_workflow_target('screening_results_dock')
            self.window._render_screening_results(self.window.state)
            self.window._cluster_plip_batch = batch
            present.reset_mock()
            self.window._activate_workflow_target('central')
            self.window._render_screening_results(self.window.state)
            self.window._refresh_pending_pose_interaction(self.window.state)
            present.assert_not_called()
            completed.assert_not_called()
            self.assertIs(self.window._cluster_plip_batch, batch)
            self.assertFalse(batch['stopped'])
            self.window._activate_workflow_target('screening_results_dock')
            present.assert_called_once_with()
            completed.assert_called_once_with(self.window.state)
            self.assertEqual(self.window._selected_screening_compound(), result.path)

    def test_results_review_loads_first_compound_and_preserves_later_selection(self):
        from types import SimpleNamespace

        results = [
            SimpleNamespace(name=name, path=self.root / name, status='complete',
                            site_count=1, planned_jobs=1, best_score=-7,
                            scoring_function='Vina', cluster_count=1)
            for name in ('first', 'second')
        ]
        with patch.object(self.window.results_model, 'compounds', return_value=results):
            self.window._render_screening_results(self.window.state)
            self.assertIsNone(self.window._selected_screening_compound())
            self.window._activate_workflow_target('screening_results_dock')
            self.assertEqual(self.window._selected_screening_compound(), results[0].path)
            self.window.screening_results.selectRow(1)
            self.window._render_screening_results(self.window.state)
            self.assertEqual(self.window._selected_screening_compound(), results[1].path)

    def test_screening_results_show_scores_as_review_outputs(self):
        compound = self.root / "screen/compounds/ligand_a"
        analysis = compound / "pose_analysis"
        analysis.mkdir(parents=True)
        manifest = compound / "screen_manifest.json"
        manifest.write_text(json.dumps({
            "completion_status": "EXPLORATORY_NO_CONTROL",
            "docking_site_count": 2, "docking_job_count": 30,
        }))
        scores = compound / "all_scores.csv"
        scores.write_text("affinity\n-6.5\n-7.2\n")
        clusters = analysis / "cluster_summary.csv"
        clusters.write_text("cluster_id,count\n1,4\n2,2\n")
        session = analysis / "representative_browser.pse"
        session.write_bytes(b"pse")
        interactions = analysis / "cluster_001/interactions"
        interactions.mkdir(parents=True)
        diagram = interactions / "representative_plip2d.png"
        from docking_universal.gui.qt import QtGui
        image = QtGui.QImage(80, 60, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        self.assertTrue(image.save(str(diagram)))
        diagram.with_suffix('.manifest.json').write_text('{"schema_name": "docking-universal-poseedit-render", "renderer_policy": "approved-poseedit-local-v1"}')
        report = self.root / "screen/report/screen.pdf"
        report.parent.mkdir(parents=True)
        report.write_bytes(b"%PDF-1.4\n%%EOF\n")
        state = self.store.load("desktop")
        state.artifacts.extend([
            ArtifactRecord("screen-manifest", "screening_compound_manifest", str(manifest)),
            ArtifactRecord("screen-scores", "screening_scores", str(scores)),
            ArtifactRecord("screen-report", "screening_report", str(report)),
            ArtifactRecord("screen-plip2d", "screening_interaction_diagram", str(diagram)),
        ])
        self.store.save(state)
        self.window.refresh()
        self.assertEqual(self.window.screening_results.rowCount(), 1)
        values = [self.window.screening_results.item(0, column).text() for column in range(7)]
        self.assertEqual(values, ["ligand_a", "EXPLORATORY_NO_CONTROL", "2", "30", "-7.2", "Not recorded", "2"])
        self.assertTrue(self.window.open_screen_report_button.isEnabled())
        self.window.screening_results.selectRow(0)
        self.assertEqual(self.window.interaction_diagram_choice.count(), 1)
        self.assertIn("Energy rank ? · Cluster 001", self.window.interaction_diagram_choice.currentText())
        self.assertTrue(self.window.open_interaction_diagram_button.isEnabled())
        with patch.object(QtGui.QDesktopServices, "openUrl", return_value=True) as opened:
            self.window.open_selected_pose_session()
        self.assertEqual(Path(opened.call_args.args[0].toLocalFile()).resolve(), session.resolve())
        with patch('docking_universal.gui.desktop.pose_view') as verified, \
                patch.object(self.window, '_open_interaction_review') as linked, \
                patch.object(QtGui.QDesktopServices, 'openUrl') as opened:
            self.window.open_selected_interaction_diagram()
        verified.assert_called_once_with(diagram)
        linked.assert_called_once_with(verified.return_value)
        opened.assert_not_called()

    def test_pose_interaction_loading_clears_old_image_and_rejects_stale_completion(self):
        from docking_universal.gui.qt import QtGui

        first = self.root / "pose-1.png"
        second = self.root / "pose-2.png"
        for path, color in ((first, "red"), (second, "blue")):
            image = QtGui.QImage(40, 40, QtGui.QImage.Format_RGB32)
            image.fill(QtGui.QColor(color))
            self.assertTrue(image.save(str(path)))
        old_key = self.window.begin_pose_interaction_loading("ligand", "site_1", 1)
        self.assertTrue(self.window.interaction_diagram_view.pixmap().isNull())
        self.assertIsNone(self.window._interaction_source_pixmap)
        self.assertIn("pose 1", self.window.interaction_diagram_view.text())
        new_key = self.window.begin_pose_interaction_loading("ligand", "site_1", 2)
        self.assertFalse(self.window.complete_pose_interaction_loading(old_key, first))
        self.assertIn("pose 2", self.window.interaction_diagram_view.text())
        self.assertTrue(self.window.complete_pose_interaction_loading(new_key, second))
        self.assertFalse(self.window.interaction_diagram_view.pixmap().isNull())
        self.window.interaction_zoom.setCurrentText("100%")
        self.assertEqual(self.window.interaction_diagram_view.pixmap().size().width(), 40)
        self.window.interaction_zoom.setCurrentText("200%")
        self.assertEqual(self.window.interaction_diagram_view.pixmap().size().width(), 80)

    def test_failed_pose_interaction_clears_loading_in_both_panels(self):
        from unittest.mock import Mock
        from types import SimpleNamespace
        self.window._pose_interaction_job_id = 'pose-job'
        self.window.viewer_widget = Mock()
        self.window.linked_pose_panel = Mock()
        job = Job(id='pose-job', stage='pose_interaction', status=JobStatus.FAILED, error='renderer stopped')
        with patch.object(self.window.results_controller, 'completed_artifact', return_value=None):
            self.window._refresh_pending_pose_interaction(SimpleNamespace(jobs=[job]))
        self.assertIn('renderer stopped', self.window.interaction_diagram_view.text())
        self.assertIn('renderer stopped', self.window.linked_pose_panel.clear_pose.call_args.args[0])
        self.assertIsNone(self.window._pose_interaction_job_id)

    def test_cluster_representative_shows_embedded_2d_panel(self):
        from unittest.mock import Mock
        from docking_universal.gui.qt import QtWidgets
        viewer = Mock(connected=True, status='connected', report_view_available=False)
        window = StudyWindow(self.store, 'desktop', settings=self.settings,
                             viewer_coordinator=viewer, viewer_widget=QtWidgets.QWidget())
        try:
            view = Mock()
            with patch('docking_universal.gui.desktop.pose_view', return_value=view), \
                 patch('docking_universal.gui.desktop.control_view', return_value=None), \
                 patch.object(window.linked_pose_panel, 'set_pose') as set_pose, \
                 patch.object(window, '_highlight_linked_ligand', return_value=True):
                self.assertTrue(window._present_linked_diagram(self.root / 'cluster.png'))
            set_pose.assert_called_once_with(view, None)
            self.assertFalse(window.linked_pose_panel.isHidden())
        finally:
            window.close()

    def test_cluster_synopsis_orders_representatives_by_retained_energy_rank(self):
        from docking_universal.gui.qt import QtGui

        compound = self.root / "screen/compounds/ligand_a"
        analysis = compound / "pose_analysis"
        analysis.mkdir(parents=True)
        manifest = compound / "screen_manifest.json"
        manifest.write_text(json.dumps({"completion_status": "retained"}))
        (analysis / "cluster_summary.csv").write_text(
            "energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count\n"
            "1,2,-9.2,12\n"
            "2,3,-9.0,8\n"
            "3,1,-8.8,5\n"
        )
        diagrams = []
        for cluster_id in (1, 2, 3):
            interactions = analysis / f"cluster_{cluster_id:03d}/interactions"
            interactions.mkdir(parents=True)
            diagram = interactions / "representative_plip2d.png"
            image = QtGui.QImage(40, 30, QtGui.QImage.Format_RGB32)
            image.fill(QtGui.QColor("white"))
            self.assertTrue(image.save(str(diagram)))
            diagram.with_suffix('.manifest.json').write_text('{"schema_name": "docking-universal-poseedit-render", "renderer_policy": "approved-poseedit-local-v1"}')
            diagrams.append(diagram)
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "screen-manifest", "screening_compound_manifest", str(manifest),
        ))
        for index, diagram in enumerate(diagrams):
            state.artifacts.append(ArtifactRecord(
                f"screen-plip2d-{index}", "screening_interaction_diagram", str(diagram),
            ))
        self.store.save(state)

        self.window.refresh()
        self.window.screening_results.selectRow(0)

        labels = [
            self.window.interaction_diagram_choice.itemText(index)
            for index in range(self.window.interaction_diagram_choice.count())
        ]
        self.assertEqual(len(labels), 3)
        self.assertIn("Energy rank 1 · Cluster 002 · primary site · -9.2 kcal/mol", labels[0])
        self.assertIn("Energy rank 2 · Cluster 003 · primary site · -9.0 kcal/mol", labels[1])
        self.assertIn("Energy rank 3 · Cluster 001 · primary site · -8.8 kcal/mol", labels[2])
        self.assertEqual(
            Path(self.window.interaction_diagram_choice.currentData()), diagrams[1],
        )

    def test_expanded_pose_review_lists_every_retained_pose_and_clears_cluster_image(self):
        compound = self.root / "screen/compounds/ligand_a"
        analysis = compound / "pose_analysis"
        analysis.mkdir(parents=True)
        manifest = compound / "screen_manifest.json"
        manifest.write_text(json.dumps({"completion_status": "retained"}))
        (analysis / "all_poses.sdf").write_text("retained fixture\n")
        (analysis / "receptor.pdb").write_text("END\n")
        (analysis / "pose_inventory.csv").write_text(
            "pose_id,cluster_id,selected_cluster,seed,conformer,model,energy_kcal_per_mol,source\n"
            "1,2,yes,101,state_a,1,-8.1,poses.pdbqt\n"
            "2,2,no,102,state_a,2,-7.7,poses.pdbqt\n"
            "3,5,yes,103,state_b,1,-7.2,poses.pdbqt\n"
        )
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "screen-manifest", "screening_compound_manifest", str(manifest),
        ))
        self.store.save(state)
        self.window.refresh()
        self.window.screening_results.selectRow(0)
        self.window.pose_review_mode.setCurrentIndex(1)
        self.assertEqual(self.window.pose_results.rowCount(), 3)
        values = [self.window.pose_results.item(0, column).text() for column in range(7)]
        self.assertEqual(values, ["1", "2", "-8.1 kcal/mol", "yes", "101", "state_a", "1"])
        self.assertFalse(self.window.interaction_diagram_choice.isVisibleTo(self.window))
        self.window.pose_results.selectRow(1)
        self.assertIn("Pose 2 selected", self.window.interaction_diagram_view.text())
        self.assertTrue(self.window.interaction_diagram_view.pixmap().isNull())
        self.window.pose_cluster_filter.setCurrentIndex(
            self.window.pose_cluster_filter.findData(5)
        )
        self.assertTrue(self.window.pose_results.isRowHidden(0))
        self.assertFalse(self.window.pose_results.isRowHidden(2))
        self.window.pose_cluster_filter.setCurrentIndex(0)
        self.window.pose_results.selectRow(1)
        self.window.refresh()
        selected = self.window.pose_results.selectionModel().selectedRows()
        self.assertEqual(len(selected), 1)
        self.assertEqual(self.window.pose_results.item(selected[0].row(), 0).text(), "2")

    def test_expanded_pose_cache_hit_opens_the_exact_pose_diagram(self):
        from docking_universal.gui.qt import QtGui

        compound = self.root / "screen/compounds/ligand_a"
        analysis = compound / "pose_analysis"
        cache = analysis / "pose_interactions/pose_0001"
        cache.mkdir(parents=True)
        manifest = compound / "screen_manifest.json"
        manifest.write_text(json.dumps({"completion_status": "retained"}))
        (analysis / "all_poses.sdf").write_text("retained fixture\n")
        (analysis / "receptor.pdb").write_text("END\n")
        (analysis / "pose_inventory.csv").write_text(
            "pose_id,cluster_id,selected_cluster,seed,conformer,model,energy_kcal_per_mol,source\n"
            "1,2,yes,101,state_a,1,-8.1,poses.pdbqt\n"
        )
        diagram = cache / "interaction_diagram.png"
        (cache / "pose.sdf").write_text("pose\n")
        image = QtGui.QImage(80, 60, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("white"))
        self.assertTrue(image.save(str(diagram)))
        diagram.with_suffix('.manifest.json').write_text('{"schema_name": "docking-universal-poseedit-render", "renderer_policy": "approved-poseedit-local-v1"}')
        state = self.store.load("desktop")
        state.artifacts.append(ArtifactRecord(
            "screen-manifest", "screening_compound_manifest", str(manifest),
        ))
        self.store.save(state)
        self.window.refresh()
        class Viewer:
            connected = True

            def __init__(self):
                self.calls = []

            def show_pose(self, analysis_root, pose_id):
                self.calls.append((Path(analysis_root), pose_id))

        viewer = Viewer()
        self.window.viewer_coordinator = viewer
        self.window.screening_results.selectRow(0)
        self.window.pose_review_mode.setCurrentIndex(1)
        self.window.pose_results.selectRow(0)
        self.assertEqual(self.window._current_interaction_diagram, diagram)
        self.assertEqual(viewer.calls, [(analysis, 1)])
        self.assertIn("retained pose 1", self.window.viewer_status.text())
        with patch('docking_universal.gui.desktop.pose_view') as verified, \
                patch.object(self.window, '_open_interaction_review') as linked, \
                patch.object(QtGui.QDesktopServices, 'openUrl') as opened:
            self.window.open_selected_interaction_diagram()
        verified.assert_called_once_with(diagram)
        linked.assert_called_once_with(verified.return_value)
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()
