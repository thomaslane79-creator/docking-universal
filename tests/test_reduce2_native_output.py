"""Regression coverage for native Reduce2 output and receptor coordinate frames."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import gemmi


ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "libexec/docking-universal-reduce2-receptor.py"
PDB = (
    "CRYST1   46.711   46.711  100.708  90.00  90.00  90.00 P 41 21 2     8\n"
    "ATOM      1  N   ALA A   1      10.000  20.000  30.000  1.00 20.00           N\n"
    "ATOM      2  CA  ALA A   1      11.500  20.000  30.000  1.00 20.00           C\n"
    "ATOM      3  C   ALA A   1      12.000  21.000  30.000  1.00 20.00           C\n"
    "ATOM      4  O   ALA A   1      12.000  22.000  30.000  1.00 20.00           O\n"
    "ATOM      5  CB  ALA A   1      11.500  19.000  31.000  1.00 20.00           C\n"
    "END\n"
)


class Reduce2NativeOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_case(self, transform="", *, cif=False, suffix=None, duplicate=False, missing=False, failed=False):
        source = self.root / ("input" + (suffix or (".cif" if cif else ".pdb")))
        if cif:
            gemmi.read_pdb_string(PDB).make_mmcif_document().write_file(str(source))
        else:
            source.write_text(PDB)
        fake = self.root / "fake_reduce2.py"
        fake.write_text(
            "import pathlib, sys, gemmi\n"
            "p = pathlib.Path(sys.argv[1])\n"
            "s = gemmi.read_structure(str(p))\n"
            + transform + "\n"
            "out = p.with_name(p.stem + 'FH' + p.suffix)\n"
            + ("sys.exit(1)\n" if failed else "")
            + ("sys.exit(0)\n" if missing else "")
            + "if p.suffix == '.pdb': s.write_pdb(str(out))\n"
            "else: s.make_mmcif_document().write_file(str(out))\n"
            + ("out.with_name(p.stem + 'H' + p.suffix).write_text(out.read_text())\n" if duplicate else "")
        )
        output = self.root / "accepted.pdb"
        audit = self.root / "audit.json"
        process = subprocess.run(
            [sys.executable, str(HELPER), str(source), str(output), str(audit), str(self.root / "reduce2.log")],
            env=dict(os.environ, REDUCE2_SCRIPT=str(fake), DOCKING_UNIVERSAL_GEOSTD=str(self.root)),
            capture_output=True, text=True,
        )
        self.assertTrue(audit.exists(), process.stderr)
        return process.returncode, json.loads(audit.read_text()), output

    def test_native_cif_is_audited_converted_and_retained(self):
        code, audit, output = self.run_case(cif=True)
        self.assertEqual(code, 0)
        self.assertEqual(audit["input_heavy_atom_count"], 5)
        self.assertEqual(audit["output_heavy_atom_count"], 5)
        self.assertEqual(audit["coordinate_frame"]["status"], "preserved")
        self.assertTrue(output.exists())
        self.assertTrue(Path(audit["native_output"]).is_file())

    def test_native_mmcif_extension(self):
        code, audit, _ = self.run_case(cif=True, suffix=".mmcif")
        self.assertEqual(code, 0)
        self.assertEqual(audit["native_output_name"], "inputFH.mmcif")

    def test_translated_pdb_is_not_accepted(self):
        code, audit, output = self.run_case("for a in s[0][0][0]: a.pos.x += 20")
        self.assertEqual(code, 2)
        self.assertEqual(audit["coordinate_frame"]["status"], "changed")
        self.assertFalse(output.exists())

    def test_translated_cif_is_not_accepted(self):
        code, audit, output = self.run_case("for a in s[0][0][0]: a.pos.z -= 30", cif=True)
        self.assertEqual(code, 2)
        self.assertEqual(audit["coordinate_frame"]["anchor_count"], 4)
        self.assertFalse(output.exists())

    def test_rotation_is_not_fitted_away(self):
        code, audit, output = self.run_case("for a in s[0][0][0]: a.pos.x, a.pos.y = -a.pos.y, a.pos.x")
        self.assertEqual(code, 2)
        self.assertFalse(audit["coordinate_frame"]["alignment_applied"])
        self.assertFalse(output.exists())

    def test_sidechain_optimization_is_allowed(self):
        code, audit, _ = self.run_case("s[0][0][0]['CB'][0].pos.y += 1")
        self.assertEqual(code, 0)
        self.assertEqual(audit["coordinate_frame"]["maximum_anchor_displacement_angstrom"], 0)

    def test_dropped_heavy_atom_is_rejected(self):
        code, audit, output = self.run_case("del s[0][0][0][4]", cif=True)
        self.assertEqual(code, 2)
        self.assertTrue(audit["missing_input_heavy_atoms"])
        self.assertFalse(output.exists())

    def test_changed_element_is_rejected(self):
        code, audit, _ = self.run_case("s[0][0][0][4].element = gemmi.Element('N')")
        self.assertEqual(code, 2)
        self.assertTrue(audit["unexpected_output_heavy_atoms"])

    def test_changed_alternate_location_is_rejected(self):
        code, audit, _ = self.run_case("s[0][0][0][4].altloc = 'B'", cif=True)
        self.assertEqual(code, 2)
        self.assertTrue(audit["missing_input_heavy_atoms"])

    def test_changed_residue_identity_is_rejected(self):
        code, audit, _ = self.run_case("s[0][0][0].name = 'VAL'", cif=True)
        self.assertEqual(code, 2)
        self.assertTrue(audit["missing_input_heavy_atoms"])

    def test_ambiguous_outputs_are_not_selected_arbitrarily(self):
        code, audit, output = self.run_case(duplicate=True)
        self.assertEqual(code, 1)
        self.assertEqual(audit["reason"], "Reduce2 output ambiguous")
        self.assertFalse(output.exists())

    def test_missing_output_is_not_a_chemistry_failure(self):
        code, audit, _ = self.run_case(missing=True)
        self.assertEqual(code, 1)
        self.assertEqual(audit["reason"], "Reduce2 output missing")
        self.assertEqual(audit["process_returncode"], 0)

    def test_process_failure_is_explicit(self):
        code, audit, _ = self.run_case(failed=True)
        self.assertEqual(code, 1)
        self.assertEqual(audit["reason"], "Reduce2 process failed")


if __name__ == "__main__":
    unittest.main()
