"""Full-workload accounting and neutral AD4 adapter; no scientific jobs."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from rdkit import Chem

VALIDATION = Path(__file__).resolve().parents[1] / "validation"
sys.path.insert(0, str(VALIDATION))
spec = importlib.util.spec_from_file_location("gpu_screen_test", VALIDATION / "autodock_gpu_full_screen.py")
screen = importlib.util.module_from_spec(spec)
spec.loader.exec_module(screen)


class FullScreenTests(unittest.TestCase):
    def test_report_uses_library_identifier_not_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "filename_not_a_molecule.sdf"
            mol = Chem.MolFromSmiles("CC")
            mol.SetProp("_Name", "filename_not_a_molecule")
            mol.SetProp("Nextval_ID", "12388")
            with Chem.SDWriter(str(source)) as writer:
                writer.write(mol)
            self.assertEqual(screen.report_compound_identity({"input": str(source)}, 1)[0], "Compound 12388")
            mol.ClearProp("Nextval_ID")
            with Chem.SDWriter(str(source)) as writer:
                writer.write(mol)
            self.assertEqual(screen.report_compound_identity({"input": str(source)}, 1)[0], "Compound 1")

    def test_all_two_by_three_by_five_inputs_kept(self):
        config = {"parameters": {"seeds": list(range(5))}, "compounds": []}
        for name in ("large", "small"):
            config["compounds"].append({"id": name, "prepared": [f"{name}{i}.pdbqt" for i in range(3)],
                "prepared_sha256": {f"{name}{i}.pdbqt": "same" for i in range(3)}})
        with patch.object(screen, "digest", return_value="same"), patch.object(Path, "read_text", return_value="input"), \
             patch.object(screen, "mapped_molecule", return_value=Chem.MolFromSmiles("CC")), \
             patch.object(screen, "pdbqt_atoms", return_value=[("prefix", (0, 0, 0), 0, "C")]):
            rows = screen.inventory(config)
        self.assertEqual(len(rows), 30)
        self.assertEqual(len({(r['compound'], r['conformer'], r['seed']) for r in rows}), 30)

    def test_adapter_does_not_invent_vina_scores_or_crystal_rmsd(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "adapter"
            rows = [{"molecule": Chem.MolFromSmiles("CC"), "run": 2,
                     "binding_energy_kcal_mol": -5., "pdbqt": "native_ad4.pdbqt"}]
            screen.typed_adapter(Path(tmp), output, rows)
            text = (output / "pose_comparison.csv").read_text()
            self.assertIn("affinity_kcal_per_mol", text)
            self.assertNotIn("rmsd", text.lower())
            self.assertNotIn("VINA", (output / "pose_001.sdf").read_text())
            self.assertIn("AutoDock-GPU AD4", (output / "score_provenance.json").read_text())
            self.assertNotIn("molecule", rows[0])


if __name__ == "__main__":
    unittest.main()
