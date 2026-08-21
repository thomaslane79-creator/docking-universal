import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "libexec" / "docking-universal-pdbfixer.py"
INPUT = ROOT / "tests" / "inputs" / "protein_ligand_complex" / "1HVR.pdb"


class PDBFixerPrecleanTests(unittest.TestCase):
    def test_writes_clean_receptor_and_audit(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "receptor.pdb"
            audit = Path(directory) / "pdbfixer_audit.json"
            subprocess.run(
                [sys.executable, str(HELPER), str(INPUT), str(output), str(audit)],
                check=True,
                capture_output=True,
                text=True,
            )

            record = json.loads(audit.read_text())
            self.assertGreater(output.stat().st_size, 0)
            self.assertEqual(record["output_pdb"], str(output.resolve()))
            self.assertEqual(record["policy"]["missing_residues"], "reported but not built")
            self.assertEqual(record["policy"]["missing_terminal_atoms"], "reported but not added")


if __name__ == "__main__":
    unittest.main()
