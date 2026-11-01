"""Portable safety regressions for the cohort repairs; no scientific inputs."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

from docking_universal.plip_sites import retained_binding_site, select_binding_site
from docking_universal.services.repair_geometry import introduced_heavy_atom_overlaps

ROOT = Path(__file__).resolve().parents[1]

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'libexec' / filename)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module

REPORT = load('cohort_pdf', 'docking-universal-pdf-report.py')
STARTUP = load('cohort_startup', 'docking-universal-backend-startup.py')

def site(name='UNL', chain='Z', number='1', kind='SMALLMOLECULE'):
    return ('<bindingsite><identifiers><hetid>' + name + '</hetid><chain>' + chain +
            '</chain><position>' + number + '</position><ligtype>' + kind +
            '</ligtype></identifiers><interactions/></bindingsite>')

class CohortRepairTests(unittest.TestCase):
    def test_multi_component_report_uses_exact_retained_ligand_not_first_ion(self):
        for xml in (site('CA', 'A', '480', 'ION') + site(), site() + site('CA', 'A', '480', 'ION')):
            selected = retained_binding_site(ET.fromstring('<report>' + xml + '</report>'))
            self.assertEqual(selected.findtext('identifiers/hetid'), 'UNL')

    def test_missing_or_ambiguous_retained_identity_fails_closed(self):
        for xml in ('', site() + site(), site('CA', 'A', '480', 'ION'), site('UNL', 'A', '1')):
            with self.subTest(xml=xml), self.assertRaises(ValueError):
                retained_binding_site(ET.fromstring('<report>' + xml + '</report>'))

    def test_component_only_selection_does_not_guess_between_instances(self):
        root = ET.fromstring('<report>' + site() + site('UNL', 'B', '2') + '</report>')
        with self.assertRaises(ValueError):
            select_binding_site(root, ligand_id='UNL')
        self.assertEqual(select_binding_site(root, ligand_id='UNL', chain='Z', position='1').findtext('identifiers/chain'), 'Z')

    def test_legacy_single_experimental_site_remains_readable(self):
        root = ET.fromstring('<report>' + site('MK1', 'B', '902') + '</report>')
        self.assertEqual(retained_binding_site(root).findtext('identifiers/hetid'), 'MK1')

    def test_repair_guard_rejects_only_introduced_gross_overlaps(self):
        ca = 'ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\n'
        cb = 'ATOM      2  CB  ALA A   1       0.500   0.000   0.000  1.00 20.00           C\n'
        with tempfile.TemporaryDirectory() as d:
            original, repaired = Path(d) / 'original.pdb', Path(d) / 'repaired.pdb'
            original.write_text(ca); repaired.write_text(ca + cb)
            self.assertEqual(len(introduced_heavy_atom_overlaps(original, repaired)), 1)
            self.assertEqual(introduced_heavy_atom_overlaps(repaired, repaired), [])

    @unittest.skipUnless(importlib.util.find_spec('gemmi'), 'gemmi required for native mmCIF')
    def test_repair_guard_reads_native_mmcif_and_preserves_author_residue_identity(self):
        import gemmi
        # Negative author numbering plus insertion code must match the PDB
        # derivative. A pre-existing close pair must not become a new repair.
        ca = 'ATOM      1  CA  ALA A  -1B      0.000   0.000   0.000  1.00 20.00           C\n'
        cb = 'ATOM      2  CB  ALA A  -1B      0.500   0.000   0.000  1.00 20.00           C\n'
        og = 'ATOM      3  OG  SER A   2       0.000   0.500   0.000  1.00 20.00           O\n'
        with tempfile.TemporaryDirectory() as d:
            source, repaired = Path(d) / 'source.mmcif', Path(d) / 'repaired.pdb'
            gemmi.read_pdb_string(ca + cb).make_mmcif_document().write_file(str(source))
            repaired.write_text(ca + cb)
            self.assertEqual(introduced_heavy_atom_overlaps(source, repaired), [])
            repaired.write_text(ca + cb + og)
            hits = introduced_heavy_atom_overlaps(source, repaired)
            self.assertEqual(len(hits), 2)
            self.assertTrue(all(hit['first'] == ('A', '2', 'SER', 'OG') for hit in hits))
            self.assertEqual({hit['second'][1] for hit in hits}, {'-1B'})

    @unittest.skipUnless(importlib.util.find_spec('gemmi'), 'gemmi required for native mmCIF')
    def test_repair_guard_refuses_multiple_mmcif_models_without_selecting_one(self):
        import gemmi
        pdb = ('MODEL        1\nATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 20.00           C\nENDMDL\n'
               'MODEL        2\nATOM      1  CA  ALA A   1       2.000   0.000   0.000  1.00 20.00           C\nENDMDL\n')
        with tempfile.TemporaryDirectory() as d:
            source, repaired = Path(d) / 'source.cif', Path(d) / 'repaired.pdb'
            gemmi.read_pdb_string(pdb).make_mmcif_document().write_file(str(source))
            repaired.write_text(pdb)
            with self.assertRaisesRegex(ValueError, 'one explicit structural model'):
                introduced_heavy_atom_overlaps(source, repaired)

    def test_repair_guard_refuses_empty_and_nonfinite_coordinates(self):
        with tempfile.TemporaryDirectory() as d:
            source, repaired = Path(d) / 'source.pdb', Path(d) / 'repaired.pdb'
            source.write_text('END\n'); repaired.write_text('END\n')
            with self.assertRaisesRegex(ValueError, 'finite, nonempty'):
                introduced_heavy_atom_overlaps(source, repaired)
            source.write_text('ATOM      1  CA  ALA A   1         nan   0.000   0.000  1.00 20.00           C\n')
            with self.assertRaisesRegex(ValueError, 'finite, nonempty'):
                introduced_heavy_atom_overlaps(source, repaired)

    def test_backend_probe_uses_help_only_and_preserves_startup_failure(self):
        import subprocess
        with patch.object(STARTUP.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'help', '')) as run:
            self.assertTrue(STARTUP.probe('backend')['available'])
            self.assertEqual(run.call_args.args[0], ['backend', '-h'])
            self.assertIs(run.call_args.kwargs['stdin'], subprocess.DEVNULL)
        with patch.object(STARTUP.subprocess, 'run', side_effect=OSError('incompatible executable')):
            self.assertFalse(STARTUP.probe('backend')['available'])

    def preparation(self, protocol, summary=None, local=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); (root / 'report').mkdir()
            if summary:
                import json
                (root / 'report/study_summary.json').write_text(json.dumps(summary))
            if local:
                (root / 'preparation/a/receptor').mkdir(parents=True)
            return REPORT.reproducibility_record(protocol, root, None)['receptor_preparation']

    def test_portable_protocol_preserves_recorded_strict_preparation(self):
        result = self.preparation({'receptor_preparation_summary': 'Strict Meeko succeeded; PDBFixer was not needed'})
        self.assertEqual(result['path'], 'Strict Meeko succeeded; PDBFixer was not needed')
        self.assertIs(result['pdbfixer_used'], False)

    def test_missing_history_does_not_invent_preparation_success(self):
        result = self.preparation({})
        self.assertIn('outside this recorded run', result['path'])
        self.assertIsNone(result['pdbfixer_used'])

    def test_screen_handoff_and_local_artifacts_precede_portable_summary(self):
        result = self.preparation({'receptor_preparation_summary': 'older history'}, {'protocol_receptor_preparation_summary': 'screen history'})
        self.assertEqual(result['path'], 'screen history')
        result = self.preparation({'receptor_preparation_summary': 'older history'}, local=True)
        self.assertEqual(result['path'], 'strict Meeko succeeded; PDBFixer was not needed')

if __name__ == '__main__':
    unittest.main()
