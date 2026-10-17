"""Scientific fingerprint must ignore headers but detect population changes."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest

VALIDATION = Path(__file__).resolve().parents[1] / "validation"
sys.path.insert(0, str(VALIDATION))
spec = importlib.util.spec_from_file_location("adgpu_repro_test", VALIDATION / "autodock_gpu_repro.py")
repro = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repro)


class FingerprintTests(unittest.TestCase):
    def fixture(self, root):
        atom = "ATOM      1  C1  LIG A   1       1.000   2.000   3.000  1.00  0.00     0.000 C\n"
        (root / "ligand_docked_run1_entity1.pdbqt").write_text(atom)
        self.rows = [f"{n:4} | 1.234 | -2.000 / -2.000 / 0.000 | 0 |" for n in range(1, 151)]
        self.table = root / "final_population_run1.txt"
        self.table.write_text("header\n" + "\n".join(self.rows))

    def test_population_changes_not_just_winner_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            before = repro.fingerprint(root, 1)
            self.rows[149] = self.rows[149].replace("1.234", "1.235")
            self.table.write_text("new header\n" + "\n".join(self.rows))
            after = repro.fingerprint(root, 1)
            self.assertEqual(before["pose_sha256"], after["pose_sha256"])
            self.assertNotEqual(before["population_sha256"], after["population_sha256"])

    def test_header_changes_ignored_and_missing_rows_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.fixture(root)
            before = repro.fingerprint(root, 1)
            self.table.write_text("different time/path\n" + "\n".join(self.rows))
            self.assertEqual(before, repro.fingerprint(root, 1))
            self.table.write_text("\n".join(self.rows[:-1]))
            with self.assertRaisesRegex(ValueError, "Incomplete"):
                repro.fingerprint(root, 1)


if __name__ == "__main__":
    unittest.main()
