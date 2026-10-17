import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from rdkit import Chem

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "validation"))
import conformer_ab as ab
import mmff_variants as variants


class MMFFVariantTests(unittest.TestCase):
    def pool(self, root):
        path = root / "source.sdf"
        ab.sdf(path, [Chem.MolFromSmiles("CC(=O)N(C)CC")])
        return ab.independent_pool(path, 2, 42)[1]

    def test_variant_is_passed_and_source_is_not_mutated(self):
        with tempfile.TemporaryDirectory() as directory:
            molecule = self.pool(Path(directory))[0]
            original = Chem.MolToMolBlock(molecule)
            actual = ab.AllChem.MMFFGetMoleculeProperties
            with mock.patch.object(ab.AllChem, "MMFFGetMoleculeProperties", wraps=actual) as properties:
                _, energy = ab.minimize_mmff(molecule, "MMFF94s")
                self.assertEqual(properties.call_args.kwargs["mmffVariant"], "MMFF94s")
                self.assertIsInstance(energy, float)
            self.assertEqual(Chem.MolToMolBlock(molecule), original)
            with self.assertRaisesRegex(ValueError, "Unsupported"):
                ab.minimize_mmff(molecule, "not-a-forcefield")

    def test_reuse_requires_same_ids_energies_and_unfitted_coordinates(self):
        with tempfile.TemporaryDirectory() as directory:
            molecule, energy = ab.minimize_mmff(self.pool(Path(directory))[0])
            records = [{"input_id": 1, "molecule": molecule, "energy_kcal_mol": energy}]
            ab.prune(records, 0.75, 1)
            prior = {"records": [{key: value for key, value in records[0].items() if key != "molecule"}]}
            self.assertTrue(variants.verify_baseline(records, records, prior, [molecule])["passed"])
            shifted = Chem.Mol(molecule)
            position = shifted.GetConformer().GetAtomPosition(0)
            shifted.GetConformer().SetAtomPosition(0, (position.x + 1, position.y, position.z))
            with self.assertRaisesRegex(ValueError, "baseline changed"):
                variants.verify_baseline(records, records, prior, [shifted])
            prior["records"][0]["energy_kcal_mol"] += 0.1
            with self.assertRaisesRegex(ValueError, "baseline changed"):
                variants.verify_baseline(records, records, prior, [molecule])

    def test_reuse_rejects_inventory_and_selected_id_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            molecule = self.pool(Path(directory))[0]
            records = [{"input_id": 1, "molecule": molecule, "energy_kcal_mol": 1}]
            with self.assertRaisesRegex(ValueError, "inventory changed"):
                variants.verify_baseline(records, records, {"records": []}, [molecule])
            prior = {"records": [{"input_id": 1, "energy_kcal_mol": 1, "disposition": "near_duplicate"}]}
            with self.assertRaisesRegex(ValueError, "retained IDs changed"):
                variants.verify_baseline(records, records, prior, [molecule])

    def test_no_overwrite_or_duplicate_start(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(SystemExit):
                variants.main(["--source", str(root), "--out", str(root)])
            ab.dump(root / "series.json", {"status": "running"})
            with self.assertRaises(SystemExit):
                variants.main(["--out", str(root), "--dock"])

    def test_docking_failure_is_terminal_and_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ab.dump(root / "summary.json", {"status": "ready", "input_sha256": {"box.conf": "missing"}})
            with self.assertRaises(OSError):
                variants.dock_case(root)
            self.assertEqual(variants.load(root / "summary.json")["status"], "failed")
            with self.assertRaisesRegex(ValueError, "ready"):
                variants.dock_case(root)


if __name__ == "__main__":
    unittest.main()
