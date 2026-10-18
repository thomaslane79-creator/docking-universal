from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.sdf_io import read_sdf, sdf_writer, write_pdb

try:
    from rdkit import Chem
    from rdkit.Chem import AllChem
except ImportError:
    Chem = None


@unittest.skipIf(Chem is None, "requires the pinned scientific runtime")
class UnicodeSdfTests(unittest.TestCase):
    def test_stream_boundary_preserves_atoms_hydrogens_maps_stereo_coordinates_and_properties(self):
        molecule = Chem.AddHs(Chem.MolFromSmiles("C[C@H](O)C(=O)N"))
        self.assertEqual(AllChem.EmbedMolecule(molecule, randomSeed=41001), 0)
        molecule.SetProp("_Name", "Ligand Ω")
        molecule.SetProp("source", "fixture")
        for index, atom in enumerate(molecule.GetAtoms(), 1):
            atom.SetAtomMapNum(index)
        with tempfile.TemporaryDirectory() as temporary:
            baseline = Path(temporary) / "baseline.sdf"
            with Chem.SDWriter(str(baseline)) as original_writer:
                original_writer.SetProps(["source"])
                original_writer.write(molecule)
            expected = list(Chem.SDMolSupplier(str(baseline), removeHs=False))[0]
            root = Path(temporary) / "Native — Ω 化合物"
            root.mkdir()
            path = root / "ligand.sdf"
            with patch("docking_universal.sdf_io.WINDOWS", True):
                with sdf_writer(path) as writer:
                    writer.SetProps(["source"])
                    writer.write(molecule)
                restored = list(read_sdf(path, removeHs=False))[0]
                write_pdb(restored, root / "ligand.pdb")
            # RDKit can assign additional tags from 3D during its ordinary SDF
            # round trip (notably when every explicit H has a unique map).
            # Compare the existing reader/writer result, not a pre-I/O tag set.
            self.assertEqual(Chem.MolToSmiles(restored), Chem.MolToSmiles(expected))
            self.assertEqual(restored.GetNumAtoms(), molecule.GetNumAtoms())
            self.assertEqual(restored.GetProp("source"), "fixture")
            self.assertEqual(restored.GetProp("_Name"), "Ligand Ω")
            for index in range(molecule.GetNumAtoms()):
                self.assertEqual(restored.GetAtomWithIdx(index).GetAtomMapNum(), index + 1)
                self.assertLess((restored.GetConformer().GetAtomPosition(index) - molecule.GetConformer().GetAtomPosition(index)).Length(), 0.0001)
            self.assertIn("HETATM", (root / "ligand.pdb").read_text())

    def test_unix_retains_original_filename_supplier_and_writer(self):
        if __import__("os").name == "nt":
            self.skipTest("Unix-only method boundary")
        with patch("docking_universal.sdf_io.WINDOWS", False):
            with patch.object(Chem, "SDMolSupplier", return_value="same-supplier") as supplier:
                self.assertEqual(read_sdf("literal.sdf", removeHs=False), "same-supplier")
                supplier.assert_called_once_with("literal.sdf", removeHs=False)
            with patch.object(Chem, "SDWriter", return_value="same-writer") as writer:
                self.assertEqual(sdf_writer("literal.sdf"), "same-writer")
                writer.assert_called_once_with("literal.sdf")


if __name__ == "__main__":
    unittest.main()
