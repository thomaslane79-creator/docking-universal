import importlib.util
from pathlib import Path
import tempfile
import unittest

from rdkit import Chem
from rdkit.Chem import AllChem
from docking_universal.services.ligand_input import ligand_input_files, read_ligand_molecules
from docking_universal.services.screening import count_ligands

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("mol_import_run", ROOT / "libexec/docking-universal-run.py")
RUN = importlib.util.module_from_spec(spec)
spec.loader.exec_module(RUN)


class LigandInputTests(unittest.TestCase):
    def test_v2000_v3000_mol_preserve_chemistry_coordinates_and_source(self):
        molecule = Chem.AddHs(Chem.MolFromSmiles("C[C@H](O)C(=O)[O-]"))
        molecule.SetProp("_Name", "Chiral example")
        AllChem.EmbedMolecule(molecule, randomSeed=7)
        for v3000 in (False, True):
            with self.subTest(v3000=v3000), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                source = root / "ligand.MOL"
                Chem.MolToMolFile(molecule, str(source), forceV3000=v3000)
                original = source.read_bytes()
                before = read_ligand_molecules(source)[0]
                self.assertEqual(count_ligands(source), 1)
                compounds = RUN.split_compounds(source, root / "normalized")
                self.assertEqual(len(compounds), 1)
                self.assertEqual(compounds[0]["source"], str(source.resolve()))
                after = read_ligand_molecules(compounds[0]["input"])[0]
                self.assertEqual(Chem.MolToSmiles(before), Chem.MolToSmiles(after))
                self.assertEqual(before.GetNumAtoms(), after.GetNumAtoms())
                for a, b in zip(before.GetConformer().GetPositions(), after.GetConformer().GetPositions()):
                    self.assertLess(max(abs(a - b)), 1e-4)
                self.assertEqual(source.read_bytes(), original)

    def test_mixed_folder_case_insensitive_and_each_sdf_record_is_counted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            mol = Chem.MolFromSmiles("CCO")
            Chem.MolToMolFile(mol, str(root / "one.MOL"))
            with Chem.SDWriter(str(root / "two.SDF")) as writer:
                writer.write(mol)
                writer.write(Chem.MolFromSmiles("CCN"))
            (root / "ignored.txt").write_text("not a ligand")
            self.assertEqual(len(ligand_input_files(root)), 2)
            self.assertEqual(count_ligands(root), 3)
            compounds = RUN.split_compounds(root, root / "normalized")
            self.assertEqual(len(compounds), 3)
            self.assertEqual(len({row["compound_id"] for row in compounds}), 3)

    def test_invalid_and_multi_record_mol_are_rejected_before_screening(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            invalid = root / "bad.mol"
            invalid.write_text("not a molfile\n")
            with self.assertRaisesRegex(ValueError, "one readable molecule|Unable to read"):
                read_ligand_molecules(invalid)
            multi = root / "multiple.mol"
            with Chem.SDWriter(str(multi)) as writer:
                writer.write(Chem.MolFromSmiles("CCO"))
                writer.write(Chem.MolFromSmiles("CCN"))
            with self.assertRaisesRegex(ValueError, "use SDF"):
                read_ligand_molecules(multi)

    def test_unsupported_inputs_and_empty_folders_have_clear_errors(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "SDF or MOL"):
                ligand_input_files(root)
            source = root / "ligand.txt"
            source.write_text("CCO")
            with self.assertRaisesRegex(FileNotFoundError, "SDF or MOL"):
                ligand_input_files(source)


if __name__ == "__main__":
    unittest.main()
