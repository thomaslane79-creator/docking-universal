import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from rdkit import Chem
from docking_universal.services.ligand_library import (
    inspect_ligand_library, selected_library_records, ligand_record_preview,
)
from docking_universal.services.screening import build_screening_plan
from docking_universal.application import StudyController
from docking_universal.host import CommandDispatcher
from docking_universal.state import JsonStudyStore
from docking_universal.viewer.messages import Command
from tests.test_ligand_input import RUN


class LigandLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.source = self.root / 'library.sdf'
        with Chem.SDWriter(str(self.source)) as writer:
            for name, smiles in [('Alcohol', 'CCO'), ('Amine', 'CCN'), ('Chiral acid', 'C[C@H](O)C(=O)O')]:
                molecule = Chem.MolFromSmiles(smiles)
                molecule.SetProp('_Name', name)
                writer.write(molecule)
        self.library = inspect_ligand_library(self.source)
        self.selection = {'fingerprint': self.library['fingerprint'],
                          'record_ids': [self.library['records'][1]['record_id']]}

    def tearDown(self):
        self.temporary.cleanup()

    def test_subset_materialization_keeps_source_record_hash_and_only_selected_chemistry(self):
        before = self.source.read_bytes()
        compounds = RUN.split_compounds(self.source, self.root / 'inputs/compounds', self.selection)
        self.assertEqual([row['compound_name'] for row in compounds], ['Amine'])
        self.assertEqual(compounds[0]['source_record'], 2)
        self.assertEqual(compounds[0]['source_sha256'], hashlib.sha256(before).hexdigest())
        molecule = next(iter(Chem.SDMolSupplier(compounds[0]['input'])))
        self.assertEqual(Chem.MolToSmiles(molecule), 'CCN')
        review = json.loads((self.root / 'inputs/ligand_library_review.json').read_text())
        self.assertEqual([row['source_record'] for row in review['records'] if row['selected_for_docking']], [2])
        self.assertEqual(len(review['records']), 3)
        self.assertEqual(self.source.read_bytes(), before)

    def test_stale_empty_duplicate_and_unknown_selections_fail_closed(self):
        for identifiers in ([], ['unknown'], [self.selection['record_ids'][0]] * 2, [{}]):
            with self.subTest(identifiers=identifiers), self.assertRaises(ValueError):
                selected_library_records(self.source, {**self.selection, 'record_ids': identifiers})
        self.source.write_text(self.source.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            selected_library_records(self.source, self.selection)

    def test_invalid_sdf_record_is_visible_and_cannot_be_selected(self):
        with self.source.open('a') as stream:
            stream.write('bad\nnot a molecule\n\n\n$$$$\n')
        library = inspect_ligand_library(self.source)
        self.assertEqual(len(library['records']), 4)
        self.assertFalse(library['records'][-1]['valid'])
        with self.assertRaisesRegex(ValueError, 'invalid compound'):
            selected_library_records(self.source, {'fingerprint': library['fingerprint'],
                'record_ids': [library['records'][-1]['record_id']]})

    def test_preview_is_png_and_never_changes_source_or_selected_molecule(self):
        before = self.source.read_bytes()
        preview = ligand_record_preview(self.source, self.library['fingerprint'], self.selection['record_ids'][0])
        self.assertTrue(base64.b64decode(preview['png_base64']).startswith(b'\x89PNG'))
        self.assertEqual(self.source.read_bytes(), before)

    def test_reviewed_previews_and_workload_reuse_molecules_without_reparsing(self):
        from docking_universal.services import ligand_library as service
        with patch.object(service, '_scan', side_effect=AssertionError('unnecessary library reparse')):
            first = ligand_record_preview(self.source, self.library['fingerprint'], self.selection['record_ids'][0])
            second = ligand_record_preview(self.source, self.library['fingerprint'], self.selection['record_ids'][0])
            self.assertEqual(first, second)
            _library, chosen = selected_library_records(self.source, self.selection)
            self.assertEqual(len(chosen), 1)

    def test_full_hash_validation_is_not_replaced_by_the_preview_file_stat_guard(self):
        from docking_universal.services import ligand_library as service
        signature = service._source_signature(self.source)
        text = self.source.read_text()
        self.source.write_text(text.replace('Alcohol', 'Changed'))
        with patch.object(service, '_source_signature', return_value=signature):
            with self.assertRaisesRegex(ValueError, 'changed after review'):
                selected_library_records(self.source, self.selection)

    def test_cached_previews_detect_changed_sources_and_cache_is_bounded(self):
        from docking_universal.services import ligand_library as service
        self.source.write_text(self.source.read_text() + '\n')
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            ligand_record_preview(self.source, self.library['fingerprint'], self.selection['record_ids'][0])
        for index in range(3):
            source = self.root / f'extra-{index}.mol'
            Chem.MolToMolFile(Chem.MolFromSmiles('CCO'), str(source))
            inspect_ligand_library(source)
        self.assertLessEqual(len(service._REVIEW_CACHE), 2)

    def test_workload_counts_only_selected_compounds(self):
        protocol = self.root / 'protocol.json'
        protocol.write_text(json.dumps({'schema_name': 'docking-universal-protocol',
            'protocol_type': 'site-guided-exploratory', 'screening_authority': 'user-confirmed-exploratory-use',
            'exploratory_screening_allowed': True, 'parameters': {'conformers_per_state': 3, 'seeds': [1, 2]},
            'locked_inputs': {'box': 'one.conf', 'boxes': [{'box': 'one.conf', 'box_label': 'P1'}]}}))
        plan = build_screening_plan(protocol, self.source, ligand_selection=self.selection)
        self.assertEqual(plan.compound_count, 1)
        self.assertEqual(plan.total_docking_jobs, 6)

    def test_host_inspection_and_preview_are_read_only(self):
        store = JsonStudyStore(self.root / 'state')
        controller = StudyController(store)
        controller.create_study('test', 'test')
        before = store.path_for('test').read_bytes()
        dispatcher = CommandDispatcher(controller, 'session')
        response = dispatcher.dispatch(Command('test', 'session', 'read', 'inspect_ligand_library',
                                              {'ligand_source': str(self.source)}))
        self.assertEqual(response.status, 'applied')
        self.assertEqual(len(response.result['library']['records']), 3)
        response = dispatcher.dispatch(Command('test', 'session', 'preview', 'ligand_record_preview',
            {'ligand_source': str(self.source), 'fingerprint': self.library['fingerprint'],
             'record_id': self.selection['record_ids'][0]}))
        self.assertEqual(response.status, 'applied')
        self.assertEqual(store.path_for('test').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
