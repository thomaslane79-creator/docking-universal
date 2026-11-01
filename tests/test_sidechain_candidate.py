"""Synthetic exact-addition candidates, never molecular approval fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from docking_universal.services.receptor_model_review import preview_changes
from docking_universal.services.sidechain_candidate import SCHEMA
from docking_universal.services.site_exploration import sha256
from tests.test_receptor_model_review import atom
from tests import test_receptor_model_review as review_tests


def fixture(root, parent):
    model = root / 'candidate.pdb'
    model.write_bytes(parent.replace(b'END\n', (atom(50, 'CG', 'ASP', 29, xyz=(1.5, 3, 0))
        + atom(51, 'OD1', 'ASP', 29, xyz=(.4, 3.6, 0))
        + atom(52, 'OD2', 'ASP', 29, xyz=(2.6, 3.6, 0)) + 'END\n').encode()))
    import hashlib
    record = {'schema_name': SCHEMA, 'schema_version': 1,
        'parent_sha256': hashlib.sha256(parent).hexdigest(), 'model_file': model.name, 'model_sha256': sha256(model),
        'generated_atoms': [dict(resname='ASP', chain='A', number='29', insertion_code='', atom_name=n, element=n[0])
                            for n in ('CG', 'OD1', 'OD2')],
        'generator': dict(method='Exact fixture additions', software='Synthetic test, no molecular generation',
                          seed=41001, script_sha256='1' * 64, approval_sha256='2' * 64, audit_sha256='3' * 64)}
    path = root / 'candidate.json'
    path.write_text(json.dumps(record))
    return path, model, record


def backbone():
    return (atom(10, 'N', 'ASP', 29) + atom(11, 'CA', 'ASP', 29, xyz=(1.45, 0, 0))
            + atom(12, 'C', 'ASP', 29, xyz=(2.8, 0, 0)) + atom(13, 'O', 'ASP', 29, xyz=(3.8, 0, 0))
            + atom(14, 'CB', 'ASP', 29, xyz=(1.5, 1.5, 0)))


class SidechainCandidateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.pdb'
        self.source.write_bytes(('REMARK original evidence\n' + backbone()
                                + atom(15, 'C1', 'NAG', 200, record='HETATM', xyz=(9, 9, 9)) + 'END\n').encode())
        self.choices = {'exclusions': [dict(resname='NAG', chain='A', number='200', insertion_code='')]}
        _, parent = preview_changes(self.source, self.choices, context={})
        self.receipt, self.model, self.record = fixture(self.root, parent)
        self.choices['sidechain_candidate'] = str(self.receipt)

    def preview(self):
        return preview_changes(self.source, self.choices, context={'selected_regions': ['exact-box']})

    def edit_model(self, transform):
        self.model.write_bytes(transform(self.model.read_text()).encode())
        self.record['model_sha256'] = sha256(self.model)
        self.receipt.write_text(json.dumps(self.record))

    def test_exact_additions_preserve_exclusions_original_records_and_generation_provenance(self):
        before = sha256(self.source)
        preview, model = self.preview()
        self.assertEqual(model, self.model.read_bytes())
        self.assertEqual([c['kind'] for c in preview['changes']], ['component_exclusion', 'sidechain_reconstruction'])
        self.assertEqual(preview['new_atoms_generated'], 3)
        change = preview['changes'][-1]
        self.assertEqual(change['modeled_heavy_atoms'], 3)
        self.assertEqual(change['generator'], self.record['generator'])
        self.assertEqual(change['candidate_receipt_sha256'], sha256(self.receipt))
        self.assertEqual(sha256(self.source), before)
        self.assertEqual(len(list(self.root.iterdir())), 3)

    def test_wrong_parent_model_or_receipt_fields_cannot_create_authority(self):
        original = copy.deepcopy(self.record)
        for change in ({'parent_sha256': '0' * 64}, {'model_sha256': '0' * 64},
                       {'model_file': '../candidate.pdb'}, {'allow_bad_res': True}, {'generator': {}},
                       {'generated_atoms': []}):
            self.receipt.write_text(json.dumps({**original, **change}))
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.preview()

    def test_changed_observed_coordinates_metadata_deletions_and_extra_atoms_are_rejected(self):
        original = self.model.read_text()
        for transform in (lambda text: text.replace('REMARK original evidence', 'REMARK changed evidence'),
                          lambda text: text.replace('   1.450', '   1.460'),
                          lambda text: ''.join(l for l in text.splitlines(keepends=True) if l[12:16].strip() != 'N'),
                          lambda text: text.replace('END\n', atom(53, 'H1', 'ASP', 29) + 'END\n')):
            self.model.write_text(original)
            self.edit_model(transform)
            with self.assertRaises(ValueError):
                self.preview()

    def test_backbone_unknown_atom_and_element_changes_are_rejected(self):
        original = copy.deepcopy(self.record)
        for patch in ({'atom_name': 'OXT', 'element': 'O'}, {'atom_name': 'CA', 'element': 'C'},
                      {'resname': 'XXX'}, {'atom_name': 'FAKE'}, {'element': 'N'}):
            self.record = copy.deepcopy(original)
            self.record['generated_atoms'][0].update(patch)
            self.receipt.write_text(json.dumps(self.record))
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                self.preview()

    def test_gross_overlap_duplicate_serial_and_nonfinite_coordinates_are_rejected(self):
        original = self.model.read_text()
        for transform in (lambda text: text.replace('   3.000', '   1.500'),
                          lambda text: text.replace('ATOM     50', 'ATOM     10'),
                          lambda text: text.replace('   3.000', '     nan')):
            self.model.write_text(original)
            self.edit_model(transform)
            with self.assertRaises(ValueError):
                self.preview()

    def test_missing_backbone_or_unresolved_target_location_cannot_be_filled(self):
        original = self.source.read_text()
        for edit in (lambda text: ''.join(l for l in text.splitlines(keepends=True) if l[12:16].strip() != 'N'),
                     lambda text: text.replace('  CB ASP', '  CBAASP')):
            # Rebind both hashes so this exercises the scientific inventory guard.
            text = edit(original)
            self.source.write_text(text)
            _, parent = preview_changes(self.source, {'exclusions': self.choices['exclusions']}, context={})
            self.receipt, self.model, self.record = fixture(self.root, parent)
            with self.assertRaises(ValueError):
                self.preview()

    def prior_model(self):
        import shutil
        path = self.root / 'earlier-model.pdb'
        shutil.copyfile(self.model, path)
        self.record['prior_model'] = dict(file=path.name, sha256=sha256(path), audit_sha256='4' * 64,
                                         regenerated_atoms=[self.record['generated_atoms'][0]])
        self.receipt.write_text(json.dumps(self.record))
        return path

    def test_reconstruction_chain_keeps_full_count_prior_hash_and_exact_regeneration_subset(self):
        path = self.prior_model()
        preview, _ = self.preview(); change = preview['changes'][-1]
        self.assertEqual(change['modeled_heavy_atoms'], 3)
        self.assertEqual(change['regenerated_heavy_atoms'], 1)
        self.assertEqual(change['retained_modeled_heavy_atoms'], 2)
        self.assertEqual(change['prior_model_sha256'], sha256(path))
        self.assertIn('3 modeled', change['description'])
        self.assertIn('2 retained unchanged', change['description'])

    def test_unapproved_changes_to_previously_modeled_atoms_or_changed_prior_are_refused(self):
        path = self.prior_model()
        self.edit_model(lambda text: text.replace('   3.600', '   3.700'))
        with self.assertRaisesRegex(ValueError, 'outside the approved'):
            self.preview()
        path.write_text(path.read_text() + 'REMARK changed\n')
        with self.assertRaisesRegex(ValueError, 'hash changed'):
            self.preview()


class SidechainWorkflowTests(unittest.TestCase):
    setUp = review_tests.ReviewedModelWorkflowTests.setUp
    wait = review_tests.ReviewedModelWorkflowTests.wait
    explore = review_tests.ReviewedModelWorkflowTests.explore
    approve = review_tests.ReviewedModelWorkflowTests.approve
    ready = review_tests.ReviewedModelWorkflowTests.ready
    payload = review_tests.ReviewedModelWorkflowTests.payload
    def test_native_host_path_binds_modeling_and_prior_exclusion_to_prepared_receptor(self):
        self.source.write_text(self.source.read_text().replace('END\n', backbone() + 'END\n'))
        state = self.ready()
        payload = self.payload(state)
        _, parent = preview_changes(self.source, payload['choices'], context={})
        receipt, model, _ = fixture(self.root, parent)
        payload['choices']['sidechain_candidate'] = str(receipt)
        preview = self.runner.preview_receptor_changes('test', payload['choices'], expected_revision=state.revision)
        payload['preview_sha256'] = preview['preview_sha256']
        reviewed = {r['residue'] for b in preview['selected_box_review'] for r in b['residues']}
        self.assertEqual(reviewed, {'NAG', 'ASP'})
        self.runner.prepare_reviewed_receptor('test', request_id='sidechain', expected_revision=state.revision,
                                              model_changes=payload)
        done = self.wait(lambda s: s.workflow_data.get('receptor_parameterization_status') == 'completed')
        history = json.loads(Path(next(a.path for a in done.artifacts if a.kind == 'receptor_model_history')).read_text())
        self.assertEqual([c['kind'] for c in history['changes']], ['component_exclusion', 'sidechain_reconstruction'])
        self.assertEqual(history['model_input_sha256'], sha256(model))
        self.assertEqual(history['changes'][1]['modeled_heavy_atoms'], 3)
        self.assertEqual(history['changes'][1]['actor'], 'scientist')
        from docking_universal.services.receptor_model_history import normalize_preparation
        warning = normalize_preparation({'model_change_history': history})['receptor_modification_warning']
        self.assertIn('NAG A:200', warning['summary'])
        self.assertIn('ASP A:29', warning['summary'])
        self.assertTrue(warning['persistent_warning_required'])

    def test_stale_candidate_cannot_start_preparation_after_preview(self):
        self.source.write_text(self.source.read_text().replace('END\n', backbone() + 'END\n'))
        state = self.ready(); payload = self.payload(state)
        _, parent = preview_changes(self.source, payload['choices'], context={})
        receipt, _, record = fixture(self.root, parent)
        payload['choices']['sidechain_candidate'] = str(receipt)
        preview = self.runner.preview_receptor_changes('test', payload['choices'], expected_revision=state.revision)
        payload['preview_sha256'] = preview['preview_sha256']
        record['generator']['seed'] = 1
        receipt.write_text(json.dumps(record))
        with self.assertRaisesRegex(ValueError, 'differ'):
            self.runner.prepare_reviewed_receptor('test', request_id='stale', expected_revision=state.revision,
                                                  model_changes=payload)
        self.assertEqual(len(self.store.load('test').jobs), len(state.jobs))
        self.assertFalse((self.root / 'work/.docking-universal-reviewed-models').exists())


if __name__ == '__main__':
    unittest.main()
