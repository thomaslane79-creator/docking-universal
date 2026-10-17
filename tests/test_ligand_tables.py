import base64
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from rdkit import Chem
from docking_universal.services import ligand_library as service
from docking_universal.services.screening import count_ligands
from docking_universal.services.ligand_input import read_ligand_molecules
from tests.test_ligand_input import RUN


FIXTURE = Path(__file__).parent / 'fixtures/ligand_tables.xlsx'


class LigandTableTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'library.csv'
        self.source.write_text('ID,SMILES,Alternative,Name\n001,CCO,CCN,Alcohol\n002,C[C@H](O)C(=O)O,CC,Acid\n003,bad_smiles,CO,Invalid\n004,,CCC,Missing\n')

    def approve(self, path=None, sheet=None, smiles=None, name=None):
        path = path or self.source
        draft = service.inspect_ligand_library(path, sheet=sheet)
        table = draft['table']
        mapping = {'source_sha256': table['source_sha256'], 'sheet': table['sheet'],
                   'smiles_column': table['suggested_smiles_column'] if smiles is None else smiles,
                   'name_column': table['suggested_name_column'] if name is None else name}
        library = service.inspect_ligand_library(path, mapping)
        selection = {'fingerprint': library['fingerprint'], 'column_mapping': mapping,
                     'record_ids': [r['record_id'] for r in library['records'] if r['valid']]}
        return library, selection

    def test_detection_only_returns_headers_and_never_compounds(self):
        draft = service.inspect_ligand_library(self.source)
        self.assertEqual(draft['records'], [])
        self.assertFalse(draft['mapping_approved'])
        self.assertEqual(draft['table']['suggested_smiles_column'], 1)
        self.assertEqual(len(draft['table']['columns']), 4)
        with self.assertRaisesRegex(ValueError, 'Approve'):
            service.selected_library_records(self.source, {'fingerprint': draft['fingerprint'], 'record_ids': ['anything']})
        with self.assertRaisesRegex(ValueError, 'Approve'):
            count_ligands(self.source)
        with self.assertRaisesRegex(ValueError, 'approved columns'):
            read_ligand_molecules(self.source)

    def test_csv_mapping_selection_and_source_provenance(self):
        before = self.source.read_bytes()
        library, selection = self.approve()
        self.assertEqual([r['valid'] for r in library['records']], [True, True, False, False])
        self.assertEqual([r['source_row'] for r in library['records']], [2, 3, 4, 5])
        selection['record_ids'] = selection['record_ids'][1:]
        compounds = RUN.split_compounds(self.source, self.root / 'inputs/compounds', selection)
        self.assertEqual(len(compounds), 1)
        self.assertEqual(compounds[0]['compound_name'], 'Acid')
        self.assertEqual(compounds[0]['source_row'], 3)
        self.assertEqual(compounds[0]['column_mapping'], selection['column_mapping'])
        molecule = next(iter(Chem.SDMolSupplier(compounds[0]['input'])))
        self.assertEqual(Chem.MolToSmiles(molecule), 'C[C@H](O)C(=O)O')
        ledger = json.loads((self.root / 'inputs/ligand_library_review.json').read_text())
        self.assertEqual(len(ledger['records']), 4)
        self.assertEqual(sum(r['selected_for_docking'] for r in ledger['records']), 1)
        self.assertEqual(self.source.read_bytes(), before)

    def test_every_column_can_override_suggestion_and_mapping_changes_identity(self):
        original, first = self.approve()
        other, second = self.approve(smiles=2, name=0)
        self.assertEqual([r['name'] for r in other['records']], ['001', '002', '003', '004'])
        self.assertNotEqual(first['fingerprint'], second['fingerprint'])
        self.assertNotEqual(first['record_ids'][0], second['record_ids'][0])
        with self.assertRaisesRegex(ValueError, 'mapping changed|changed after review'):
            service.selected_library_records(self.source, {**first, 'column_mapping': second['column_mapping']})

    def test_mapping_survives_host_restart_and_preview_does_not_prepare_chemistry(self):
        library, selection = self.approve()
        service._REVIEW_CACHE.clear()
        preview = service.ligand_record_preview(self.source, selection['fingerprint'], selection['record_ids'][0], selection['column_mapping'])
        self.assertTrue(base64.b64decode(preview['png_base64']).startswith(b'\x89PNG'))
        _, selected = service.selected_library_records(self.source, selection)
        self.assertEqual(selected[0][1].GetNumConformers(), 0)
        self.assertEqual(selected[0][1].GetProp('InputColumn1:ID'), '001')
        with patch.object(service, '_scan', side_effect=AssertionError('reparsed')):
            service.selected_library_records(self.source, selection)

    def test_stale_file_during_approval_and_after_selection_is_rejected(self):
        library, selection = self.approve()
        self.source.write_text(self.source.read_text().replace('CCO', 'CCC'))
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            service.inspect_ligand_library(self.source, selection['column_mapping'])
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            service.selected_library_records(self.source, selection)

    def test_unknown_duplicate_blank_headers_are_selectable_by_position(self):
        self.source.write_text('molecule,molecule,,identifier\nCCO,CCN,CO,001\n')
        draft = service.inspect_ligand_library(self.source)
        self.assertIsNone(draft['table']['suggested_smiles_column'])
        self.assertEqual([c['index'] for c in draft['table']['columns']], [0, 1, 2, 3])
        library, _ = self.approve(smiles=2, name=3)
        self.assertEqual(library['records'][0]['formula'], 'CH4O')

    def test_tsv_bom_quoted_fields_and_salt_charge_are_preserved(self):
        path = self.root / 'library.TSV'
        path.write_text('Name\tSMILES\n"A\tB"\t[NH4+].[Cl-]\n', encoding='utf-16')
        library, selection = self.approve(path)
        self.assertEqual(library['records'][0]['name'], 'A\tB')
        _, rows = service.selected_library_records(path, selection)
        self.assertEqual(Chem.MolToSmiles(rows[0][1]), '[Cl-].[NH4+]')

    def test_excel_sheet_choice_formulas_and_numeric_smiles(self):
        draft = service.inspect_ligand_library(FIXTURE)
        self.assertEqual(draft['table']['sheets'], ['Read me', 'Compounds'])
        self.assertIsNone(draft['table']['suggested_smiles_column'])
        library, selection = self.approve(FIXTURE, sheet='Compounds')
        self.assertEqual([r['valid'] for r in library['records']], [True, True, True, False, False, False])
        self.assertIn('literal text', library['records'][4]['error'])
        self.assertIn('Formula', library['records'][5]['error'])
        _, rows = service.selected_library_records(FIXTURE, selection)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2][0]['source_sheet'], 'Compounds')

    def test_each_table_format_materializes_selected_chemistry_and_no_name_is_allowed(self):
        tsv = self.root / 'molecules.tsv'
        tsv.write_text('Name\tSMILES\nSame\tCCO\nSame\tCCN\n')
        for source, sheet in ((self.source, None), (tsv, None), (FIXTURE, 'Compounds')):
            with self.subTest(source=source):
                library, selection = self.approve(source, sheet=sheet)
                compounds = RUN.split_compounds(source, self.root / source.stem / 'inputs/compounds', selection)
                self.assertEqual(len(compounds), len(selection['record_ids']))
                self.assertEqual(len({r['compound_id'].lower() for r in compounds}), len(compounds))
                self.assertTrue(all(Path(r['input']).suffix == '.sdf' for r in compounds))
                self.assertTrue(all(r['source_row'] >= 2 for r in compounds))
        draft = service.inspect_ligand_library(self.source)
        mapping = {'source_sha256': draft['table']['source_sha256'], 'sheet': None,
                   'smiles_column': 1, 'name_column': None}
        library = service.inspect_ligand_library(self.source, mapping)
        self.assertEqual(library['records'][0]['name'], 'Compound 1')
        with self.assertRaisesRegex(SystemExit, 'approved columns'):
            RUN.split_compounds(self.source, self.root / 'unapproved')

    def test_quoted_multiline_csv_retains_starting_source_line(self):
        self.source.write_text('Name,SMILES\n"First\ncompound",CCO\nSecond,CCN\n')
        library, _ = self.approve()
        self.assertEqual([r['source_row'] for r in library['records']], [2, 4])

    def test_duplicate_xlsx_addresses_are_rejected_not_overwritten(self):
        path = self.root / 'duplicate.xlsx'
        with zipfile.ZipFile(FIXTURE) as original, zipfile.ZipFile(path, 'w') as changed:
            for item in original.infolist():
                content = original.read(item.filename)
                if item.filename == 'xl/worksheets/sheet2.xml':
                    content = content.replace(b'r="A3"', b'r="A2"')
                changed.writestr(item, content)
        with self.assertRaisesRegex(ValueError, 'address'):
            service.inspect_ligand_library(path, sheet='Compounds')
        with zipfile.ZipFile(FIXTURE) as original, zipfile.ZipFile(path, 'w') as changed:
            for item in original.infolist():
                content = original.read(item.filename)
                if item.filename == 'xl/workbook.xml':
                    content = content.replace(b'name="Compounds"', b'')
                changed.writestr(item, content)
        with self.assertRaisesRegex(ValueError, 'missing its name'):
            service.inspect_ligand_library(path)

    def test_invalid_rows_cannot_be_selected_and_mapping_is_validated(self):
        library, selection = self.approve()
        with self.assertRaisesRegex(ValueError, 'invalid compound'):
            service.selected_library_records(self.source, {**selection, 'record_ids': [library['records'][-1]['record_id']]})
        for changes in ({'smiles_column': None}, {'smiles_column': True}, {'smiles_column': 9}, {'name_column': 1}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                service.inspect_ligand_library(self.source, {**selection['column_mapping'], **changes})

    def test_empty_broken_csv_and_non_xlsx_zip_fail_clearly(self):
        for text in ('', 'Name,SMILES\n"unterminated,CCO'):
            self.source.write_text(text)
            with self.assertRaises(ValueError):
                service.inspect_ligand_library(self.source)
        bad = self.root / 'bad.xlsx'
        bad.write_bytes(b'not an xlsx')
        with self.assertRaisesRegex(ValueError, 'XLSX'):
            service.inspect_ligand_library(bad)

    def test_xlsx_external_sheet_and_xml_entities_are_never_loaded(self):
        for external in (True, False):
            path = self.root / 'unsafe.xlsx'
            with zipfile.ZipFile(FIXTURE) as original, zipfile.ZipFile(path, 'w') as changed:
                for item in original.infolist():
                    content = original.read(item.filename)
                    if item.filename == 'xl/_rels/workbook.xml.rels' and external:
                        content = content.replace(b'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"',
                            b'TargetMode="External" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet"')
                    if item.filename == 'xl/workbook.xml' and not external:
                        content = b'<!DOCTYPE workbook [<!ENTITY x "bad">]>' + content
                    changed.writestr(item, content)
            with self.assertRaises(ValueError):
                service.inspect_ligand_library(path)

    def test_thousands_of_rows_can_be_read_without_selecting_any_implicitly(self):
        self.source.write_text('Name,SMILES\n' + ''.join(f'Compound {i},CCO\n' for i in range(2501)))
        draft = service.inspect_ligand_library(self.source)
        self.assertFalse(draft['records'])
        library, selection = self.approve()
        self.assertEqual(len(library['records']), 2501)
        self.assertEqual(len({r['record_id'] for r in library['records']}), 2501)
