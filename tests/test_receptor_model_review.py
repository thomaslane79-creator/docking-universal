"""Exact review boundaries; all models in these tests are synthetic fixtures."""
import json
from pathlib import Path
import tempfile
import unittest

from docking_universal.services.receptor_model_review import preview_changes, write_model
from docking_universal.services.site_exploration import sha256
from docking_universal.protocol_finalization import FinalizationSettings, request_from_study
import tests.test_site_first_workflow as site_tests


def atom(serial, name, residue='ASN', number=10, altloc='', xyz=(0, 0, 0), occupancy=1, record='ATOM'):
    return (f'{record:<6}{serial:5d} {name:>4}{altloc:1}{residue:>3} A{number:4d}    '
            f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}{occupancy:6.2f}{20:6.2f}          {name[0]:>2}\n')


class ReceptorModelReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'Target.pdb'
        self.source.write_text(atom(1, 'N') + atom(2, 'CA') + atom(3, 'CB', altloc='A', occupancy=.6)
                               + atom(4, 'CB', altloc='B', xyz=(2, 3, 4), occupancy=.4)
                               + atom(5, 'C1', 'NAG', 100, record='HETATM')
                               + 'CONECT    2    3    4    5\nEND\n')
        self.before = sha256(self.source)
        self.nag = dict(resname='NAG', chain='A', number='100', insertion_code='')
        self.asn = dict(resname='ASN', chain='A', number='10', insertion_code='', altloc='B')

    def preview(self, choices=None):
        return preview_changes(self.source, choices or {'exclusions': [], 'alternate_locations': []},
                               context={'original_input_sha256': self.before, 'selected_regions': ['box-hash']})

    def test_inspection_does_not_choose_locations_write_files_or_hide_incomplete_backbone(self):
        record, derivative = self.preview()
        self.assertEqual(derivative, self.source.read_bytes())
        self.assertEqual(record['changes'], [])
        self.assertEqual(record['residue_inventory'][0]['missing_backbone_atom_names'], ['C', 'O'])
        self.assertEqual([a['altloc'] for a in record['residue_inventory'][0]['alternate_locations']], ['A', 'B'])
        self.assertEqual(len(list(self.root.iterdir())), 1)

    def test_exact_changes_keep_shared_atoms_coordinates_and_only_selected_location(self):
        record, derivative = self.preview({'exclusions': [self.nag], 'alternate_locations': [self.asn]})
        text = derivative.decode()
        self.assertNotIn('NAG', text)
        self.assertNotIn('CONECT    2    3', text)
        self.assertIn('CONECT    2    4', text)
        lines = [line for line in text.splitlines() if line.startswith('ATOM  ')]
        self.assertEqual(len(lines), 3)
        self.assertTrue(all(line[16] == ' ' for line in lines))
        cb = next(line for line in lines if line[12:16].strip() == 'CB')
        self.assertEqual(tuple(float(cb[i:i+8]) for i in (30, 38, 46)), (2, 3, 4))
        self.assertEqual(record['new_atoms_generated'], 0)
        self.assertEqual(sha256(self.source), self.before)

    def test_wrong_or_conflicting_choices_do_not_modify_input(self):
        cases = [{'exclusions': [dict(self.nag, chain='B')]},
                 {'alternate_locations': [dict(self.asn, altloc='C')]},
                 {'alternate_locations': [self.asn, self.asn]},
                 {'exclusions': [self.nag, self.nag]},
                 {'exclusions': [{k: self.asn[k] for k in self.nag}], 'alternate_locations': [self.asn]},
                 {'allow_bad_res': True}]
        for choices in cases:
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                self.preview(choices)
        self.assertEqual(sha256(self.source), self.before)

    def test_protein_exclusion_is_high_severity_and_all_protein_exclusion_is_refused(self):
        self.source.write_text(self.source.read_text().replace('END\n', atom(6, 'CA', 'GLY', 11) + 'END\n'))
        key = {k: self.asn[k] for k in self.nag}
        record, _ = self.preview({'exclusions': [key]})
        self.assertEqual(record['severity'], 'high')
        self.assertEqual(record['changes'][0]['removed_standard_amino_acids'], 1)
        with self.assertRaisesRegex(ValueError, 'all protein'):
            self.preview({'exclusions': [key, dict(resname='GLY', chain='A', number='11', insertion_code='')]})

    def test_new_model_requires_explicit_approval_and_never_overwrites(self):
        record, data = self.preview({'exclusions': [self.nag]})
        out = self.root / 'approved'
        with self.assertRaises(ValueError):
            write_model(out, 'Target.pdb', record, data, actor='', rationale='why')
        self.assertFalse(out.exists())
        model, approved = write_model(out, 'Target.pdb', record, data, actor='scientist', rationale='Explicit fixture review')
        self.assertEqual(sha256(model), record['model_input_sha256'])
        self.assertEqual(approved['status'], 'approved_changes_not_parameterized')
        with self.assertRaises(FileExistsError):
            write_model(out, 'Target.pdb', record, data, actor='scientist', rationale='why')

    def test_preview_binds_input_and_site_context(self):
        choices = {'exclusions': [self.nag]}
        first, _ = self.preview(choices)
        other, _ = preview_changes(self.source, choices, context={'selected_regions': ['different-box']})
        self.assertNotEqual(first['preview_sha256'], other['preview_sha256'])
        self.source.write_text(self.source.read_text() + 'REMARK changed\n')
        changed, _ = self.preview(choices)
        self.assertNotEqual(first['preview_sha256'], changed['preview_sha256'])

    def test_missing_atom_inventory_distinguishes_backbone_from_sidechains(self):
        from types import SimpleNamespace
        from docking_universal.services.preparation_atom_inventory import missing_atom_inventory
        class Residue:
            name = 'LYS'; id = '224'; insertionCode = ''; chain = SimpleNamespace(id='A')
        inventory = missing_atom_inventory({Residue(): [SimpleNamespace(name=n) for n in ('CA', 'C', 'O', 'CB', 'NZ')]})
        self.assertEqual(inventory[0]['missing_backbone_atom_names'], ['C', 'CA', 'O'])
        self.assertEqual(inventory[0]['missing_other_atom_names'], ['CB', 'NZ'])


class ReviewedModelWorkflowTests(unittest.TestCase):
    setUp = site_tests.SiteFirstWorkflowTests.setUp
    wait = site_tests.SiteFirstWorkflowTests.wait
    explore = site_tests.SiteFirstWorkflowTests.explore
    approve = site_tests.SiteFirstWorkflowTests.approve

    def ready(self):
        self.source.write_text(self.source.read_text().replace('END\n', atom(3, 'C1', 'NAG', 200, record='HETATM') + 'END\n'))
        return self.approve(self.explore())

    def payload(self, state):
        choices = {'exclusions': [dict(resname='NAG', chain='A', number='200', insertion_code='')],
                   'alternate_locations': []}
        preview = self.runner.preview_receptor_changes('test', choices, expected_revision=state.revision)
        return dict(choices=choices, preview_sha256=preview['preview_sha256'], actor='scientist',
                    rationale='Exact synthetic component reviewed for exploratory testing')

    def test_reviewed_derivative_binds_history_and_preserves_original_boxes_authority(self):
        state = self.ready(); before = sha256(self.source)
        boxes = {a.path: sha256(a.path) for a in state.artifacts if a.kind == 'docking_box'}
        payload = self.payload(state)
        self.runner.prepare_reviewed_receptor('test', request_id='changed', expected_revision=state.revision,
                                              model_changes=payload)
        done = self.wait(lambda s: s.workflow_data.get('receptor_parameterization_status') == 'completed')
        history_path = Path(next(a.path for a in done.artifacts if a.kind == 'receptor_model_history'))
        history = json.loads(history_path.read_text())
        self.assertEqual(history['original_input_sha256'], before)
        self.assertEqual(history['prepared_receptor_sha256'], next(a.sha256 for a in done.artifacts if a.kind == 'prepared_receptor'))
        self.assertEqual(history['changes'][0]['actor'], 'scientist')
        self.assertEqual({p: sha256(p) for p in boxes}, boxes)
        self.assertEqual(sha256(self.source), before)
        self.assertEqual(done.approvals, state.approvals)
        request = request_from_study(done, FinalizationSettings(), self.root / 'final', exploratory_use_approved=True)
        self.assertEqual(request.source_structure, self.source.resolve())
        self.assertNotEqual(request.preparation_root, self.root / 'work/Target_receptor_prep')
        from docking_universal.services.preparation_site_issues import candidate_with_model_change_review
        candidate = done.workflow_data['pocket_candidates'][0]
        decorated = candidate_with_model_change_review(done, candidate)
        self.assertNotIn('receptor_model_review', candidate['evidence'])
        box_review = decorated['evidence']['receptor_model_review']
        self.assertEqual(box_review['status'], 'prepared_with_reviewed_model_changes')
        self.assertEqual(box_review['residues'][0]['residue'], 'NAG')
        self.assertIn('NAG A:200', box_review['warning'])
        self.assertTrue(self.runner.prepare_reviewed_receptor('test', request_id='changed',
            expected_revision=done.revision, model_changes=payload)['replayed'])
        history_path.write_text(history_path.read_text() + ' ')
        unverified = candidate_with_model_change_review(done, candidate)['evidence']['receptor_model_review']
        self.assertEqual(unverified['status'], 'model_change_evidence_unverified')
        with self.assertRaisesRegex(ValueError, 'changed'):
            request_from_study(done, FinalizationSettings(), self.root / 'bad-final', exploratory_use_approved=True)

    def test_wrong_preview_no_change_or_missing_approval_never_creates_attempt(self):
        state = self.ready(); good = self.payload(state)
        for patch in ({'preview_sha256': '0' * 64}, {'actor': ''}, {'rationale': ''}, {'choices': {'exclusions': []}}):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.runner.prepare_reviewed_receptor('test', request_id='bad', expected_revision=state.revision,
                                                      model_changes={**good, **patch})
        self.assertFalse((self.root / 'work/.docking-universal-reviewed-models').exists())
        self.assertEqual(len(self.store.load('test').jobs), len(state.jobs))

    def test_explicit_changed_attempt_retains_the_original_failure(self):
        state = self.ready()
        self.engine.write_text('#!/bin/sh\nmkdir -p Target_receptor_prep/receptor\n'
                              'printf "original failure\\n" > Target_receptor_prep/run.log\nexit 1\n')
        self.runner.prepare_reviewed_receptor('test', request_id='original', expected_revision=state.revision)
        failed = self.wait(lambda s: s.workflow_data.get('receptor_parameterization_status') == 'failed')
        original = self.root / 'work/Target_receptor_prep/run.log'; original_hash = sha256(original)
        self.engine.write_text('#!/bin/sh\nset -eu\n'
            'test "$DOCKING_UNIVERSAL_REVIEWED_MODEL_ONLY" = 1\n'
            'test "$DOCKING_UNIVERSAL_PDBFIXER" = off\n'
            'test "$DOCKING_UNIVERSAL_PREP_BACKEND" = meeko\n'
            'root=Target_receptor_prep\nmkdir -p "$root/receptor"\ncp "$1" "$root/receptor/Target.pdb"\n'
            'printf "prepared\\n" > "$root/receptor/Target.pdbqt"\nprintf "new attempt\\n" > "$root/run.log"\n')
        self.runner.prepare_reviewed_receptor('test', request_id='changed', expected_revision=failed.revision,
                                              model_changes=self.payload(failed))
        done = self.wait(lambda s: s.workflow_data.get('receptor_parameterization_status') == 'completed')
        self.assertEqual(sha256(original), original_hash)
        self.assertEqual([j.status.value for j in done.jobs if j.stage == 'receptor_parameterization'], ['failed', 'completed'])
        self.assertEqual(len(done.workflow_data['receptor_preparation_attempts']), 2)


if __name__ == '__main__':
    unittest.main()
