import importlib.util
import tempfile
import unittest
from pathlib import Path

import gemmi
from tests.test_structure_input import MMCIF

spec = importlib.util.spec_from_file_location(
    "native_receptor", Path(__file__).resolve().parents[1] / "libexec/docking-universal-native-receptor.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class NativeReceptorTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec('prody'), 'ProDy required for native backend reader')
    def test_backend_reader_keeps_final_atom_when_atom_loop_is_last_category(self):
        from prody import parseMMCIF
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, filtered, output = root / 'source.cif', root / 'filtered.pdb', root / 'output.cif'
            pdb = ('ATOM      1  CA  ALA A   1       0.000   1.000   2.000  1.00 10.00           C\n'
                   'ATOM      2  CB  ALA A   1       2.000   3.000   4.000  1.00 10.00           C\n')
            gemmi.read_pdb_string(pdb).make_mmcif_document().write_file(str(source))
            filtered.write_text(pdb)
            module.filtered_mmcif(source, filtered, output)
            parsed = parseMMCIF(str(output), altloc='all')
            self.assertEqual(parsed.numAtoms(), 2)
            self.assertEqual(parsed.getNames().tolist(), ['CA', 'CB'])
            self.assertEqual(parsed.getChids().tolist(), ['A', 'A'])
            self.assertEqual(parsed.getCoords().tolist(), [[0., 1., 2.], [2., 3., 4.]])
            self.assertEqual(source.read_text().splitlines()[-1].split()[0], 'ATOM')

    def test_filter_excludes_ligand_and_preserves_receptor_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.cif"
            source.write_text(MMCIF)
            filtered = root / "filtered.pdb"
            filtered.write_text("ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 10.00           C\n")
            output = root / "filtered.cif"
            module.filtered_mmcif(source, filtered, output)
            structure = gemmi.read_structure(str(output))
            residues = [r for m in structure for c in m for r in c]
            self.assertEqual([r.name for r in residues], ["ALA"])
            self.assertEqual(residues[0][0].pos.x, 0.0)
            self.assertEqual(residues[0].subchain, "A")

    def test_unmapped_filter_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.cif"
            source.write_text(MMCIF)
            filtered = root / "filtered.pdb"
            filtered.write_text("ATOM      1  CA  ALA Z   1       0.000   0.000   0.000  1.00 10.00           C\n")
            with self.assertRaisesRegex(ValueError, "do not map"):
                module.filtered_mmcif(source, filtered, root / "output.cif")
