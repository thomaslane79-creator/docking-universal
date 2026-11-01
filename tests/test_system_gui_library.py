import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SPEC=importlib.util.spec_from_file_location('gui_worker_library',Path(__file__).resolve().parents[1]/'validation/system_gui_worker.py')
worker=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(worker)


class ExplicitLibraryTests(unittest.TestCase):
    def setUp(self):
        self.library={'records':[{'valid':True},{'valid':False},{'valid':True}],
                      'table':{'columns':[{'index':0},{'index':1}],'source_sha256':'hash','sheet':'Compounds'}}

    def test_suggestions_do_not_approve_columns(self):
        with self.assertRaises(ValueError):worker.reviewed_columns(self.library,None)

    def test_exact_mapping_carries_source_and_sheet(self):
        self.assertEqual(worker.reviewed_columns(self.library,{'smiles_column':1,'name_column':0,'sheet':'Compounds'}),
                         {'source_sha256':'hash','sheet':'Compounds','smiles_column':1,'name_column':0})

    def test_other_sheet_or_missing_columns_rejected(self):
        for mapping in [{'smiles_column':3},{'smiles_column':1,'name_column':4},
                        {'smiles_column':1,'sheet':'Other'}]:
            with self.subTest(mapping=mapping),self.assertRaises(ValueError):worker.reviewed_columns(self.library,mapping)

    def test_invalid_empty_duplicate_or_outside_selection_rejected(self):
        for selection in [None,[],[0,0],[1],[-1],[3],[True]]:
            with self.subTest(selection=selection),self.assertRaises(ValueError):worker.selected_indices(self.library,selection)

    def test_valid_subset_not_confused_with_entire_library(self):
        self.assertEqual(worker.selected_indices(self.library,[2]),[2])

    def test_planning_preserves_the_selected_record_ids(self):
        case={'inputs':{'ligands':{'path':'fixture.sdf'}},'selected_record_indices':[2]}
        library={'fingerprint':'pinned','records':[{'valid':True,'record_id':str(i)} for i in range(3)]}
        with patch('docking_universal.services.ligand_library.inspect_ligand_library',return_value=library):
            self.assertEqual(worker.planning_selection(case),{'fingerprint':'pinned','record_ids':['2']})

    def test_planning_does_not_implicitly_approve_a_table(self):
        case={'inputs':{'ligands':{'path':'fixture.csv'}},'selected_record_indices':[0]}
        with patch('docking_universal.services.ligand_library.inspect_ligand_library',return_value=self.library):
            with self.assertRaisesRegex(ValueError,'approval'):
                worker.planning_selection(case)
