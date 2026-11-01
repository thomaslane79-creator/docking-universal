import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from docking_universal.application import StudyController
from docking_universal.orchestration import ProtocolWorkflowRunner
from docking_universal.protocol_finalization import FinalizationSettings, request_from_study
from docking_universal.services.preparation_site_issues import for_box, backend_residue_ids, collect_site_issues
from docking_universal.services.site_exploration import read_exploration, sha256
from docking_universal.state import JsonStudyStore

ROOT = Path(__file__).resolve().parents[1]


class PreparationIssueDiagnosticTests(unittest.TestCase):
    def test_backend_lists_and_component_dictionary_retain_exact_author_ids(self):
        text = ("- Residues with alternate location: ['A:634', 'A:667']\n"
                "Template matching failed for: ['B:-2A']\n"
                "RuntimeWarning: Input residues {'C:344': 'NAG', ':345': 'HSQ'} not in residue_templates\n"
                "Expected 4 paddings for (D:6, D:8) with bonds [], but got 0\n")
        self.assertEqual(backend_residue_ids(text), {
            ('A', '634'), ('A', '667'), ('B', '-2A'), ('C', '344'), ('', '345'), ('D', '6'), ('D', '8')})

    def test_unrelated_text_and_executable_diagnostic_fragments_are_not_identities(self):
        text = ("/tmp/A:23/source.py\nUse --wanted_altloc A:55\n"
                "Residues with alternate location: [__import__('os').getpid()]\n"
                "Template matching failed for: ['ALA', 'A:NaN', '/tmp/file:123']\n")
        self.assertEqual(backend_residue_ids(text), set())

    def test_named_altloc_only_error_is_located_without_changing_coordinates(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); (root / 'receptor').mkdir()
            source = root / 'source.pdb'
            data = ('ATOM      1  CA AASN A 667       4.000   0.000   0.000  0.50 20.00           C\n'
                    'ATOM      2  CA BASN A 667       8.000   0.000   0.000  0.50 20.00           C\n')
            source.write_text(data)
            (root / 'receptor/receptor_backend.log').write_text(
                "- Residues with alternate location: ['A:667', 'B:99']\n")
            record = collect_site_issues(root, source)
            self.assertEqual(record['unlocated_residue_ids'], ['B:99'])
            self.assertEqual(len(record['residues']), 1)
            self.assertEqual(len(record['residues'][0]['coordinates']), 2)
            box = {f'center_{a}': 0 for a in 'xyz'} | {f'size_{a}': 10 for a in 'xyz'}
            shown = for_box(record, box)
            self.assertTrue(shown['residues'][0]['inside_box'])
            self.assertFalse(shown['automatic_repairs'])
            self.assertFalse(shown['automatic_exclusions'])
            self.assertFalse(shown['distance_is_permission_to_ignore'])
            self.assertEqual(source.read_text(), data)


class SiteFirstWorkflowTests(unittest.TestCase):
    def setUp(self):
        if os.name == 'nt':
            self.skipTest('This fixture exercises the POSIX preparation script; native Windows has separate workflow gates')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'Target.pdb'
        self.source.write_text(
            'ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 10.00           C\n'
            'HETATM    2  C1  BEN A 100       1.000   2.000   3.000  1.00 10.00           C\nEND\n')
        self.store = JsonStudyStore(self.root / 'state')
        self.controller = StudyController(self.store)
        self.controller.create_study('test', 'Test')
        self.engine = self.root / 'bin/docking-universal-prepare'
        self.engine.parent.mkdir()
        self.engine.write_text('#!/bin/sh\nset -eu\n'
            'test "$DOCKING_UNIVERSAL_PARAMETERIZATION_ONLY" = 1\n'
            'root=Target_receptor_prep\nmkdir -p "$root/receptor" "$root/cavity"\n'
            'cp "$1" "$root/receptor/Target.pdb"\n'
            'printf "prepared\\n" > "$root/receptor/Target.pdbqt"\n'
            'printf "complete\\n" > "$root/run.log"\n')
        self.engine.chmod(0o755)
        (self.engine.parent / 'docking-universal-explore-sites.py').symlink_to(
            ROOT / 'libexec/docking-universal-explore-sites.py')
        self.runner = ProtocolWorkflowRunner(self.controller, self.engine)
        self.addCleanup(self.runner.shutdown)

    def wait(self, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            state = self.store.load('test')
            if predicate(state):
                return state
            time.sleep(.02)
        self.fail('Timed out: ' + repr(self.store.load('test')))

    def explore(self):
        self.runner.start_preparation('test', {
            'input_pdb': str(self.source), 'working_directory': str(self.root / 'work'),
            'site_mode': 'ligand', 'ligand_resname': 'BEN', 'ligand_chain_id': 'A',
            'ligand_residue_number': '100', 'pdb_pocket_evidence': 'off',
            'explore_sites_first': True,
        }, request_id='explore', expected_revision=self.store.load('test').revision)
        return self.wait(lambda s: bool(s.pending_decisions))

    def approve(self, state):
        decision = state.pending_decisions[0]
        self.controller.resolve_decision('test', decision.id, ('B1',), actor='scientist',
                                         expected_revision=state.revision)
        return self.store.load('test')

    def test_review_precedes_parameterization_and_does_not_authorize_docking(self):
        before = sha256(self.source)
        state = self.explore()
        self.assertEqual(state.jobs[0].stage, 'site_exploration')
        self.assertEqual(state.workflow_data['receptor_parameterization_status'], 'not_started')
        self.assertFalse(any(a.kind == 'prepared_receptor' for a in state.artifacts))
        self.assertFalse((self.root / 'work/Target_receptor_prep').exists())
        self.assertEqual(sha256(self.source), before)
        state = self.approve(state)
        with self.assertRaisesRegex(ValueError, 'not parameterized'):
            request_from_study(state, FinalizationSettings(), self.root / 'final', exploratory_use_approved=True)

    def test_preparation_preserves_reviewed_boxes_and_does_not_predict_again(self):
        state = self.approve(self.explore())
        boxes = {a.path: sha256(a.path) for a in state.artifacts if a.kind == 'docking_box'}
        self.runner.prepare_reviewed_receptor('test', request_id='parameterize', expected_revision=state.revision)
        done = self.wait(lambda s: s.workflow_data.get('receptor_parameterization_status') == 'completed')
        self.assertEqual([j.stage for j in done.jobs], ['site_exploration', 'pocket_review', 'receptor_parameterization'])
        self.assertEqual(done.selected_pocket_ids, state.selected_pocket_ids)
        self.assertEqual(len(done.approvals), len(state.approvals))
        self.assertEqual({p: sha256(p) for p in boxes}, boxes)
        self.assertTrue(any(a.kind == 'prepared_receptor' for a in done.artifacts))
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            self.runner.prepare_reviewed_receptor('test', request_id='duplicate', expected_revision=done.revision)

    def test_failure_keeps_box_review_without_automatic_retry(self):
        self.engine.write_text('#!/bin/sh\nmkdir -p Target_receptor_prep/receptor\n'
            'printf "residue_key=\047A:1\047 failed\\n" > Target_receptor_prep/receptor/receptor.log\nexit 1\n')
        state = self.approve(self.explore())
        self.runner.prepare_reviewed_receptor('test', request_id='failed', expected_revision=state.revision)
        failed = self.wait(lambda s: s.workflow_data.get('receptor_parameterization_status') == 'failed')
        self.assertEqual(failed.selected_pocket_ids, state.selected_pocket_ids)
        evidence = failed.workflow_data['pocket_candidates'][0]['evidence']['receptor_preparation_review']
        self.assertFalse(evidence['automatic_exclusions'])
        self.assertTrue(evidence['residues'][0]['inside_box'])
        self.assertTrue(any(a.kind == 'preparation_diagnostic' and a.path.endswith('receptor.log')
                            for a in failed.artifacts))
        self.assertTrue(Path(failed.workflow_data['receptor_parameterization_attempt_root']).is_dir())
        self.assertIsNone(failed.active_job)
        with self.assertRaisesRegex(ValueError, 'already attempted'):
            self.runner.prepare_reviewed_receptor('test', request_id='retry', expected_revision=failed.revision)

    def test_input_mutation_invalidates_site_review(self):
        state = self.approve(self.explore())
        self.source.write_text(self.source.read_text() + 'REMARK changed\n')
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.runner.prepare_reviewed_receptor('test', request_id='bad', expected_revision=state.revision)

    def test_no_preparation_before_explicit_site_approval(self):
        state = self.explore()
        with self.assertRaisesRegex(ValueError, 'Review and approve'):
            self.runner.prepare_reviewed_receptor('test', request_id='early', expected_revision=state.revision)

    def test_failed_or_external_coordinate_record_rejected(self):
        state = self.explore()
        root = Path(state.workflow_data['site_exploration_root'])
        record_path = root / 'site_exploration.json'
        record = json.loads(record_path.read_text())
        record['prediction_receptor'] = str(self.source)
        record_path.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'inside'):
            read_exploration(root)

    def test_box_distance_is_not_center_distance_or_permission(self):
        record = {'residues': [{'chain': 'A', 'number': '1', 'residue': 'GLU',
                                'coordinates': [(9, 0, 0), (15, 0, 0)]}]}
        box = dict(center_x=0, center_y=0, center_z=0, size_x=20, size_y=20, size_z=20)
        result = for_box(record, box)
        self.assertEqual(result['residues'][0]['minimum_distance_to_box_angstrom'], 0)
        self.assertFalse(result['distance_is_permission_to_ignore'])
        box['center_x'] = -5
        self.assertEqual(for_box(record, box)['residues'][0]['minimum_distance_to_box_angstrom'], 4)


if __name__ == '__main__':
    unittest.main()
