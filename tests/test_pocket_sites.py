import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from docking_universal.application import StudyController
from docking_universal.decisions import DecisionOption, DecisionRequired
from docking_universal.models import ArtifactRecord, Job, JobStatus, CompletionStatus
from docking_universal.pocket_sites import (project_pending_site_review, site_group_summary,
    preview_site_expansion, apply_site_expansion, site_review_presentation)
from docking_universal.protocol_finalization import approved_regions_from_study
from docking_universal.state import JsonStudyStore

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

class PocketSiteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.store = JsonStudyStore(self.root / 'state')
        self.controller = StudyController(self.store)
        self.controller.create_study('sites', 'Site grouping')

    def pending(self, boxes, *, ligand=None):
        state = self.store.load('sites')
        candidates = []
        for rank, (identity, center, size) in enumerate(boxes, 1):
            path = self.root / (identity + '.conf')
            path.write_text(''.join(f'center_{axis} = {value}\n' for axis, value in zip('xyz', center))
                            + ''.join(f'size_{axis} = {size}\n' for axis in 'xyz'))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            state.artifacts.append(ArtifactRecord(identity, 'docking_box', str(path), digest))
            evidence = {'source': 'input_bound_ligand'} if identity == 'B1' else {
                'detector': 'p2rank', 'score': 11.8 / rank}
            candidates.append(dict(id=identity, label=identity, rank=rank,
                                   box_artifact_id=identity, summary=identity + ' source', evidence=evidence))
        if ligand:
            path = self.root / 'input.pdb'
            path.write_text(''.join(
                f'HETATM{i:5d}  C{i:<2} GNP A 200    {x:8.3f}{0.:8.3f}{0.:8.3f}  1.00 20.00           C\n'
                for i, x in enumerate(ligand, 1)))
            state.artifacts.append(ArtifactRecord('input', 'bound_ligand', str(path),
                                                  hashlib.sha256(path.read_bytes()).hexdigest()))
        state.workflow_data['pocket_candidates'] = candidates
        state.workflow_data['pocket_review_source'] = {'candidate_count': len(candidates)}
        state.jobs.append(Job('review', 'pocket_review', JobStatus.WAITING_FOR_DECISION))
        state.decisions.append(DecisionRequired('choose', 'select_pockets', 'Choose', '', '', (),
            tuple(DecisionOption(c['id'], c['label'], c['summary']) for c in candidates),
            artifact_ids=tuple(a.id for a in state.artifacts), maximum_selections=len(candidates),
            payload={'candidate_ids': [c['id'] for c in candidates]}))
        state.completion_status = CompletionStatus.WAITING_FOR_DECISION
        state.current_stage = 'pocket_review'
        self.store.save(state)
        return self.store.load('sites')

    def test_same_complete_ligand_is_one_exact_box_with_all_scores_and_sources(self):
        state = self.pending([('P1', (0., 0., .5156), 26), ('B1', (0., 0., 0.), 26),
                              ('P2', (50., 0., 0.), 26)], ligand=(-1., 1.))
        original = copy.deepcopy(state.to_dict())
        projected = project_pending_site_review(state)
        self.assertEqual([c['id'] for c in projected.workflow_data['pocket_candidates']], ['B1', 'P2'])
        candidate = projected.workflow_data['pocket_candidates'][0]
        group = candidate['evidence']['site_group']
        self.assertEqual(group['member_ids'], ['P1', 'B1'])
        self.assertEqual(group['members'][0]['evidence']['score'], 11.8)
        self.assertNotIn('score', candidate['evidence'])
        self.assertEqual(group['members'][1]['geometry']['center_z'], 0.)
        self.assertIn('p2rank score 11.8', site_group_summary(group))
        self.assertEqual(state.to_dict(), original)
        self.assertEqual(self.store.load('sites').to_dict(), original)

    def test_complete_input_ligand_rule_does_not_require_near_identical_boxes(self):
        state = self.pending([('P1', (5., 0., 0.), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        result = project_pending_site_review(state)
        self.assertEqual(len(result.workflow_data['pocket_candidates']), 1)
        relationship = result.workflow_data['pocket_candidates'][0]['evidence']['site_group']['relationships'][0]
        self.assertLess(min(relationship['overlap_fractions']), .95)
        self.assertEqual(relationship['reason'], 'both_boxes_contain_all_experimental_ligands')

    def test_overlap_percentage_does_not_define_a_site_without_experimental_ligands(self):
        state = self.pending([('P1', (0., 0., 0.), 26), ('P2', (.9, 0., 0.), 26),
                              ('P3', (1.8, 0., 0.), 26), ('P4', (50., 0., 0.), 100)])
        result = project_pending_site_review(state)
        self.assertEqual([c['id'] for c in result.workflow_data['pocket_candidates']], ['P1', 'P2', 'P3', 'P4'])

    def related_ligand(self, state, candidate_id, values):
        path = self.root / (candidate_id + '-ligand.pdb')
        path.write_text(''.join(
            f'HETATM{i:5d}  C{i:<2} LIG B 601    {x:8.3f}{0.:8.3f}{0.:8.3f}  1.00 20.00           C\n'
            for i, x in enumerate(values, 1)))
        state.artifacts.append(ArtifactRecord(candidate_id + '-ligand', 'aligned_ligand', str(path),
                                              hashlib.sha256(path.read_bytes()).hexdigest()))
        candidate = next(c for c in state.workflow_data['pocket_candidates'] if c['id'] == candidate_id)
        candidate['evidence']['experimental_ligand_evidence'] = {'observations': [{
            'entry': '1ABC' if candidate_id == 'P1' else '2ABC', 'ligand': 'LIG',
            'source_ligand_id': candidate_id + '/LIG/B/601', 'evidence_class': 'exact_sequence_match',
            'aligned_ligand_pdb': str(path)}], 'observation_count': 1}
        return path

    def two_ligand_sites(self):
        state = self.pending([('P1', (0., 0., 0.), 26), ('P2', (8., 0., 0.), 26)])
        self.related_ligand(state, 'P1', (0., 1.))
        self.related_ligand(state, 'P2', (13.2, 13.5))
        self.store.save(state)
        return self.store.load('sites')

    def test_both_experimental_ligands_fully_fit_both_boxes_even_with_much_less_overlap(self):
        state = self.pending([('P1', (0., 0., 0.), 26), ('P2', (10., 0., 0.), 26)])
        self.related_ligand(state, 'P1', (1., 2.))
        self.related_ligand(state, 'P2', (7., 8.))
        result = project_pending_site_review(state)
        candidates = result.workflow_data['pocket_candidates']
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]['evidence']['experimental_ligand_evidence']['observation_count'], 2)
        group = candidates[0]['evidence']['site_group']
        self.assertEqual(len(group['ligands']), 2)
        self.assertLess(min(group['relationships'][0]['overlap_fractions']), .65)

    def test_one_related_ligand_can_group_both_boxes_when_assigned_to_one(self):
        state = self.pending([('P1', (0., 0., 0.), 26), ('P2', (8., 0., 0.), 26)])
        self.related_ligand(state, 'P1', (1., 2.))
        result = project_pending_site_review(state)
        self.assertEqual(len(result.workflow_data['pocket_candidates']), 1)
        group = result.workflow_data['pocket_candidates'][0]['evidence']['site_group']
        self.assertEqual(group['member_ids'], ['P1', 'P2'])
        self.assertEqual(group['relationships'][0]['reason'], 'both_boxes_contain_all_experimental_ligands')

    def test_partial_ligand_containment_remains_explicit_and_preview_writes_nothing(self):
        state = self.two_ligand_sites()
        self.assertEqual(len(project_pending_site_review(state).workflow_data['pocket_candidates']), 2)
        before = self.store.path_for('sites').read_bytes()
        preview = preview_site_expansion(state, ['P1', 'P2'], 'P1')
        self.assertEqual(preview['geometry']['size_x'], 30.5)
        self.assertEqual(preview['face_extensions']['x']['upper_extension_angstrom'], 4.5)
        self.assertEqual(preview['geometry']['size_y'], 26.)
        self.assertEqual(self.store.path_for('sites').read_bytes(), before)
        self.assertFalse((self.store.path_for('sites').parent / 'site-boxes').exists())

    def test_expansion_keeps_original_sources_then_requires_normal_region_approval(self):
        state = self.two_ligand_sites()
        originals = {a.path: Path(a.path).read_bytes() for a in state.artifacts}
        preview = preview_site_expansion(state, ['P1', 'P2'], 'P1')
        receipt = apply_site_expansion(self.controller, 'sites', ['P1', 'P2'], 'P1', preview['preview_sha256'],
            'Both observed ligands occupy the same pocket', 'scientist', state.revision, 'once')
        staged = self.store.load('sites')
        self.assertEqual([c['id'] for c in staged.workflow_data['pocket_candidates']], ['E1'])
        self.assertEqual(staged.selected_pocket_ids, [])
        self.assertEqual(staged.approvals, [])
        self.assertFalse(receipt['grants_approval'])
        self.assertEqual([o.value for o in staged.pending_decisions[0].options], ['E1'])
        self.assertTrue(all(Path(path).read_bytes() == content for path, content in originals.items()))
        self.controller.resolve_decision('sites', 'choose', ('E1',), actor='scientist')
        approved = self.store.load('sites')
        regions, _ = approved_regions_from_study(approved)
        self.assertEqual(float(regions[0]['geometry']['size_x']), 30.5)
        self.assertEqual(regions[0]['site_group']['member_ids'], ['P1', 'P2'])
        self.assertNotIn('pocket_prediction', regions[0])
        replay = apply_site_expansion(self.controller, 'sites', ['P1', 'P2'], 'P1', preview['preview_sha256'],
            'Both observed ligands occupy the same pocket', 'scientist', state.revision, 'once')
        self.assertEqual(replay, receipt)

    def test_expansion_cannot_approve_changed_ligands_stale_revision_or_missing_reason(self):
        state = self.two_ligand_sites()
        preview = preview_site_expansion(state, ['P1', 'P2'], 'P1')
        before = self.store.path_for('sites').read_bytes()
        with self.assertRaisesRegex(ValueError, 'Record why'):
            apply_site_expansion(self.controller, 'sites', ['P1', 'P2'], 'P1', preview['preview_sha256'],
                '', 'scientist', state.revision)
        ligand = next(a for a in state.artifacts if a.kind == 'aligned_ligand')
        Path(ligand.path).write_text('changed\n')
        with self.assertRaisesRegex(ValueError, 'no hash-verified'):
            apply_site_expansion(self.controller, 'sites', ['P1', 'P2'], 'P1', preview['preview_sha256'],
                'shared pocket', 'scientist', state.revision)
        self.assertEqual(self.store.path_for('sites').read_bytes(), before)

    def test_host_preview_apply_and_restart_replay_use_one_revisioned_boundary(self):
        from docking_universal.host import CommandDispatcher
        from docking_universal.viewer.messages import Command
        state = self.two_ligand_sites()
        dispatcher = CommandDispatcher(self.controller, 'session')
        before = self.store.path_for('sites').read_bytes()
        command = Command('sites', 'session', 'preview', 'preview_site_expansion',
                          {'candidate_ids': ['P1', 'P2'], 'base_id': 'P1'}, state.revision)
        response = dispatcher.dispatch(command)
        self.assertEqual(response.status, 'applied', response.error)
        self.assertEqual(self.store.path_for('sites').read_bytes(), before)
        preview = response.result['preview']
        apply_command = Command('sites', 'session', 'apply', 'apply_site_expansion',
            {'candidate_ids': ['P1', 'P2'], 'base_id': 'P1', 'preview_sha256': preview['preview_sha256'],
             'rationale': 'Both ligands occupy the same pocket'}, state.revision)
        applied = dispatcher.dispatch(apply_command)
        self.assertEqual(applied.status, 'applied', applied.error)
        replay = CommandDispatcher(self.controller, 'session').dispatch(apply_command)
        self.assertEqual(replay.status, 'applied', replay.error)
        self.assertEqual(len(self.store.load('sites').workflow_data['site_expansion_history']), 1)

    def test_ligand_grouping_does_not_join_distinct_sites_through_an_intermediate_box(self):
        state = self.pending([('P1', (0., 0., 0.), 10), ('P2', (2., 0., 0.), 10), ('P3', (4., 0., 0.), 10)])
        self.related_ligand(state, 'P1', (-2., -1.5))
        self.related_ligand(state, 'P2', (2., 2.5))
        self.related_ligand(state, 'P3', (6., 6.5))
        result = project_pending_site_review(state)
        self.assertEqual([c['id'] for c in result.workflow_data['pocket_candidates']], ['P1', 'P3'])
        self.assertEqual(result.workflow_data['pocket_candidates'][0]['evidence']['site_group']['member_ids'], ['P1', 'P2'])

    def test_input_and_related_ligands_stay_distinct_in_one_grouped_site(self):
        state = self.pending([('P1', (0., 0., .5156), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        self.related_ligand(state, 'P1', (2., 3.))
        result = project_pending_site_review(state)
        candidate = result.workflow_data['pocket_candidates'][0]
        self.assertEqual(candidate['id'], 'B1')
        self.assertEqual(candidate['evidence']['experimental_ligand_evidence']['observation_count'], 1)
        self.assertEqual(len(candidate['evidence']['site_group']['ligands']), 2)
        from docking_universal.services.pocket_review import candidate_with_input_ligand_evidence
        decorated = candidate_with_input_ligand_evidence(result, candidate)
        self.assertEqual(decorated['evidence']['input_ligand_evidence']['observation_count'], 1)

    def test_group_merges_all_related_observations_and_input_without_counting_shared_evidence_twice(self):
        from docking_universal.services.pocket_review import candidate_with_input_ligand_evidence
        state = self.pending([('P1', (0., 0., .5156), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        self.related_ligand(state, 'P1', (2., 3.))
        self.related_ligand(state, 'B1', (4., 5.))
        candidates = state.workflow_data['pocket_candidates']
        shared = copy.deepcopy(candidates[0]['evidence']['experimental_ligand_evidence']['observations'][0])
        candidates[1]['evidence']['experimental_ligand_evidence']['observations'].append(shared)
        before = copy.deepcopy(state.to_dict())
        grouped = project_pending_site_review(state)
        self.assertEqual(len(grouped.workflow_data['pocket_candidates']), 1)
        candidate = candidate_with_input_ligand_evidence(grouped, grouped.workflow_data['pocket_candidates'][0])
        evidence = candidate['evidence']
        self.assertEqual(evidence['input_ligand_evidence']['observation_count'], 1)
        related = evidence['experimental_ligand_evidence']
        self.assertEqual(related['observation_count'], 2)
        self.assertEqual(related['pdb_entry_count'], 2)
        self.assertEqual(len({o['source_ligand_id'] for o in related['observations']}), 2)
        self.assertEqual(len(evidence['site_group']['ligands']), 3)
        self.assertEqual(state.to_dict(), before)

    def test_group_preserves_source_conformation_comparisons_and_obstruction_warning(self):
        from docking_universal.services.pocket_review import candidate_with_input_ligand_evidence
        state = self.pending([('P1', (0., 0., .5156), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        self.related_ligand(state, 'P1', (2., 3.))
        candidate = state.workflow_data['pocket_candidates'][0]
        residue = dict(name='LYS', chain='A', number='33')
        observation = dict(entry='1ABC', alignment_id='1ABC_A_to_A', residue=residue,
            ligands=[dict(source_ligand_id='P1/LIG/B/601', consistent_with_side_chain_occlusion=True)])
        candidate['evidence']['conformational_site_evidence'] = dict(
            observations=[observation], observation_count=1, status='conformationally_incompatible',
            box_decision_warning='Retained side-chain obstruction', occluding_residues=[residue])
        state.workflow_data['pocket_candidates'][1]['evidence']['conformational_site_evidence'] = copy.deepcopy(candidate['evidence']['conformational_site_evidence'])
        grouped = project_pending_site_review(state)
        evidence = grouped.workflow_data['pocket_candidates'][0]['evidence']
        self.assertEqual(evidence['conformational_site_evidence']['observation_count'], 1)
        self.assertEqual(evidence['conformational_site_evidence']['occluding_residues'], [residue])
        # Reopen a group saved before comparison merging was added.
        del evidence['conformational_site_evidence']
        shown = candidate_with_input_ligand_evidence(grouped, grouped.workflow_data['pocket_candidates'][0])
        self.assertEqual(shown['evidence']['conformational_site_evidence']['status'], 'conformationally_incompatible')
        self.assertNotIn('conformational_site_evidence', evidence)

    def test_nested_boxes_and_boundary_tolerance_do_not_create_false_duplicates(self):
        state = self.pending([('P1', (0., 0., 0.), 4), ('B1', (0., 0., 0.), 2)], ligand=(-1.1, 1.1))
        self.assertIs(project_pending_site_review(state), state)

    def test_different_receptor_states_cannot_merge(self):
        state = self.pending([('P1', (0., 0., 0.), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        state.workflow_data['pocket_candidates'][1]['evidence']['receptor_state_id'] = 'HID'
        self.assertIs(project_pending_site_review(state), state)

    def test_unverified_or_invalid_box_cannot_justify_consolidation(self):
        state = self.pending([('P1', (0., 0., 0.), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        Path(state.artifacts[0].path).write_text('center_x = nan\n')
        self.assertIs(project_pending_site_review(state), state)
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.controller.resolve_decision('sites', 'choose', ('P1',), actor='scientist')

    def test_old_pending_reopen_and_explicit_approval_seal_same_geometry_and_sources(self):
        state = self.pending([('P1', (0., 0., .5156), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        before = self.store.path_for('sites').read_bytes()
        decision = self.controller.get_decision('sites', 'choose')
        self.assertEqual([o.value for o in decision.options], ['B1'])
        self.assertEqual(self.store.path_for('sites').read_bytes(), before)
        with self.assertRaisesRegex(ValueError, 'Unknown decision option'):
            self.controller.resolve_decision('sites', 'choose', ('P1',), actor='scientist')
        self.assertEqual(self.store.path_for('sites').read_bytes(), before)
        approval = self.controller.resolve_decision('sites', 'choose', ('B1',), actor='scientist',
                                                     expected_revision=state.revision)
        approved = self.store.load('sites')
        regions, _ = approved_regions_from_study(approved)
        self.assertEqual(approved.selected_pocket_ids, ['B1'])
        self.assertEqual(regions[0]['box_sha256'], state.artifacts[1].sha256)
        self.assertEqual(regions[0]['site_group'], approval.evidence['site_groups'][0])
        self.assertEqual(len(approved.workflow_data['pocket_site_grouping']['original_candidates']), 2)
        self.assertIs(project_pending_site_review(approved), approved)

    def test_already_approved_study_is_not_rewritten(self):
        state = self.pending([('P1', (0., 0., 0.), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        state.selected_pocket_ids = ['B1']
        self.assertIs(project_pending_site_review(state), state)

    def test_historical_view_groups_duplicates_but_keeps_exact_original_approval(self):
        from unittest.mock import patch
        for chosen in ('P1', 'B1'):
            with self.subTest(approved=chosen):
                self.store = JsonStudyStore(self.root / chosen)
                self.controller = StudyController(self.store)
                self.controller.create_study('sites', 'Historical site view')
                state = self.pending([('P1', (0., 0., .5156), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
                # Reproduce a pre-grouping approval, not a newly grouped decision.
                with patch('docking_universal.pocket_sites.project_pending_site_review', side_effect=lambda s: s):
                    self.controller.resolve_decision('sites', 'choose', (chosen,), actor='historical-user')
                approved = self.store.load('sites')
                regions, approval = approved_regions_from_study(approved)
                before = self.store.path_for('sites').read_bytes()
                shown = site_review_presentation(approved)
                candidates = shown.workflow_data['pocket_candidates']
                self.assertEqual([c['id'] for c in candidates], [chosen])
                self.assertIn('site_group_presentation', candidates[0]['evidence'])
                self.assertNotIn('site_group', candidates[0]['evidence'])
                self.assertEqual(approved_regions_from_study(shown), (regions, approval))
                self.assertEqual(shown.approvals, approved.approvals)
                self.assertEqual(shown.decisions, approved.decisions)
                self.assertEqual(self.store.path_for('sites').read_bytes(), before)

    def test_grouped_summary_retains_every_detector_score_with_its_source(self):
        from docking_universal.pocket_sites import site_prediction_text
        group = {'members': [
            {'id': 'P1', 'evidence': {'detector': 'p2rank', 'score': 11.85}},
            {'id': 'P2', 'pocket_prediction': {'detector': 'p2rank', 'score': 8.4}},
            {'id': 'B1', 'evidence': {'source': 'input_bound_ligand'}},
        ]}
        self.assertEqual(site_prediction_text(group), 'P2Rank 11.85 (P1); P2Rank 8.4 (P2)')

    def test_two_historically_approved_calculation_boxes_remain_identifiable(self):
        state = self.pending([('P1', (0., 0., .5156), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        state.decisions.clear()
        state.selected_pocket_ids = ['P1', 'B1']
        self.assertIs(site_review_presentation(state), state)

    def test_tampered_group_source_is_rejected_before_approval(self):
        state = self.pending([('P1', (0., 0., .5156), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        grouped = project_pending_site_review(state)
        self.store.save(grouped)
        Path(state.artifacts[0].path).write_text('changed source\n')
        before = self.store.path_for('sites').read_bytes()
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.controller.resolve_decision('sites', 'choose', ('B1',), actor='scientist')
        self.assertEqual(self.store.path_for('sites').read_bytes(), before)


class PocketSiteGuiTests(unittest.TestCase):
    def test_desktop_expansion_keeps_viewport_interactive_and_cancel_does_not_apply(self):
        try:
            from docking_universal.gui.qt import QtCore, QtWidgets
        except ImportError as exc:
            self.skipTest(str(exc))
        from docking_universal.gui.desktop import StudyWindow
        from types import SimpleNamespace
        from unittest.mock import Mock
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        fixture = PocketSiteTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        state = fixture.two_ligand_sites()
        settings = QtCore.QSettings(str(fixture.root / 'preferences.ini'), QtCore.QSettings.Format.IniFormat)
        window = StudyWindow(fixture.store, 'sites', settings=settings)
        apply = Mock()
        window.host_controller = SimpleNamespace(available=True,
            preview_site_expansion=lambda ids, base, revision: preview_site_expansion(state, ids, base),
            apply_site_expansion=apply)
        try:
            window.candidates.selectAll()
            window.combine_sites_button.click()
            dialog = window._site_expansion_dialog
            self.assertIsNotNone(dialog)
            self.assertFalse(dialog.isModal())
            self.assertTrue(window.isEnabled())
            dialog.reject()
            self.assertIsNone(window._site_expansion_dialog)
            apply.assert_not_called()
            window.candidates.selectAll()
            window.combine_sites_button.click()
            dialog = window._site_expansion_dialog
            dialog.rationale.setText('Both observed ligands identify one site')
            preview = dialog.preview
            dialog.use_box.click()
            apply.assert_called_once_with(preview, 'Both observed ligands identify one site', state.revision)
            self.assertIsNone(window._site_expansion_dialog)
        finally:
            window.close(); app.processEvents()

    def test_expansion_dialog_previews_exact_geometry_and_requires_a_reason(self):
        try:
            from docking_universal.gui.qt import QtWidgets
        except ImportError as exc:
            self.skipTest(str(exc))
        from docking_universal.gui.site_expansion import SiteExpansionDialog
        from unittest.mock import Mock
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        fixture = PocketSiteTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        state = fixture.two_ligand_sites()
        before = fixture.store.path_for('sites').read_bytes()
        show = Mock()
        dialog = SiteExpansionDialog(['P1', 'P2'], lambda base: preview_site_expansion(state, ['P1', 'P2'], base), show)
        try:
            self.assertFalse(dialog.use_box.isEnabled())
            self.assertEqual(dialog.geometry_table.item(0, 4).text(), '30.500')
            dialog.show_box.click()
            show.assert_called_once_with(dialog.preview['geometry'], 'P1')
            dialog.rationale.setText('Both bound ligands mark one pocket')
            self.assertTrue(dialog.use_box.isEnabled())
            dialog.base.setCurrentIndex(1)
            self.assertEqual(dialog.preview['base_id'], 'P2')
            self.assertEqual(dialog.geometry_table.item(0, 4).text(), '26.000')
            dialog.reject()
            self.assertEqual(fixture.store.path_for('sites').read_bytes(), before)
        finally:
            dialog.close(); app.processEvents()

    def test_same_protein_observations_are_included_in_the_compact_summary(self):
        try:
            from docking_universal.gui.desktop import StudyWindow
            from docking_universal.gui.qt import QtWidgets
        except ImportError as exc:
            self.skipTest(str(exc))
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        summary, _ = StudyWindow._candidate_evidence_digest({'id': 'B1'}, {
            'experimental_ligand_evidence': {'observation_count': 7, 'pdb_entry_count': 7,
                'evidence_class_counts': {'same_protein': 7}}})
        self.assertIn('7 same protein', summary)

    def test_completed_existing_run_table_plot_and_detached_selector_group_without_reapproval(self):
        from unittest.mock import patch
        try:
            from docking_universal.gui.qt import QtCore, QtWidgets
        except ImportError as exc:
            self.skipTest(str(exc))
        from docking_universal.gui.desktop import StudyWindow
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        fixture = PocketSiteTests(); fixture.setUp(); self.addCleanup(fixture.doCleanups)
        fixture.pending([('P1', (0., 0., .5156), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        with patch('docking_universal.pocket_sites.project_pending_site_review', side_effect=lambda s: s):
            fixture.controller.resolve_decision('sites', 'choose', ('B1',), actor='historical-user')
        before = fixture.store.path_for('sites').read_bytes()
        regions = approved_regions_from_study(fixture.store.load('sites'))
        settings = QtCore.QSettings(str(fixture.root / 'history.ini'), QtCore.QSettings.Format.IniFormat)
        window = StudyWindow(fixture.store, 'sites', settings=settings)
        browser = FullPyMOLStudyPanel(window)
        try:
            self.assertEqual(window.candidates.rowCount(), 1)
            self.assertEqual([point[:2] for point in window.pocket_score_plot.points], [('B1', 11.8)])
            self.assertEqual(window.pocket_score_plot.score_sources, {'B1': 'P1'})
            self.assertIn('P2Rank 11.8 (P1)', window.candidates.item(0, 3).text())
            self.assertEqual(browser.regions.count(), 1)
            self.assertEqual(approved_regions_from_study(window.state), regions)
            self.assertEqual(fixture.store.path_for('sites').read_bytes(), before)
        finally:
            browser.dispose(); browser.close(); window.close(); app.processEvents()

    def test_reopened_plot_table_and_detached_selector_show_one_site_without_writes(self):
        try:
            from docking_universal.gui.qt import QtCore, QtWidgets
        except ImportError as exc:
            self.skipTest(str(exc))
        from docking_universal.gui.desktop import StudyWindow
        from docking_universal.gui.full_pymol_study import FullPyMOLStudyPanel
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        fixture = PocketSiteTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.pending([('P1', (0., 0., .5156), 26), ('B1', (0., 0., 0.), 26)], ligand=(-1., 1.))
        before = fixture.store.path_for('sites').read_bytes()
        settings = QtCore.QSettings(str(fixture.root / 'preferences.ini'), QtCore.QSettings.Format.IniFormat)
        window = StudyWindow(fixture.store, 'sites', settings=settings)
        browser = FullPyMOLStudyPanel(window)
        try:
            self.assertEqual(window.candidates.rowCount(), 1)
            self.assertEqual([point[:2] for point in window.pocket_score_plot.points], [('B1', 11.8)])
            self.assertEqual(window.pocket_score_plot.score_sources, {'B1': 'P1'})
            self.assertIn('P2Rank 11.8 (P1)', window.candidates.item(0, 3).text())
            self.assertEqual(window.pocket_score_plot.evidence_counts['B1'], 1)
            self.assertEqual(browser.regions.count(), 1)
            self.assertEqual([o.value for o in window.state.pending_decisions[0].options], ['B1'])
            window._show_candidate_evidence_details(window.candidates.item(0, 3))
            sources = window._candidate_evidence_dialogs[-1].findChild(QtWidgets.QPlainTextEdit, 'site_sources')
            self.assertIn('p2rank score 11.8', sources.toPlainText())
            self.assertIn('unchanged B1 box', sources.toPlainText())
            self.assertEqual(fixture.store.path_for('sites').read_bytes(), before)
        finally:
            browser.dispose()
            browser.close()
            window.close()
            app.processEvents()


if __name__ == '__main__':
    unittest.main()
