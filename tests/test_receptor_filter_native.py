import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from docking_universal.receptor_filter import disulfide_templates, filter_receptor_pdb

ROOT = Path(__file__).resolve().parents[1]


class NativeReceptorFilterTests(unittest.TestCase):
    def test_crystal_context_and_component_policy_are_preserved(self):
        def record(kind, serial, residue, number, element="C"):
            return f"{kind:<6}{serial:5d} {'CA':^4} {residue:>3} A{number:4d}    {serial:8.3f}{0:8.3f}{0:8.3f}{1:6.2f}{20:6.2f}          {element:>2}\n"
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, target = root / "input.pdb", root / "filtered.pdb"
            source.write_text("CRYST1   46.711   46.711  100.708  90.00  90.00  90.00 P 41 21 2     8\n"
                "SCALE1      0.021408  0.000000  0.000000        0.00000\n"
                "MODRES 1ABC CSO A   2  CYS  S-HYDROXYCYSTEINE\n"
                "LINK         CA  ALA A   1                 C1  ADX A 101\n"
                + record("ATOM", 1, "ALA", 1) + record("HETATM", 2, "CSO", 2)
                + record("HETATM", 3, "ADX", 101) + record("HETATM", 4, "ADX", 101)
                + record("HETATM", 5, "LIG", 201) + record("HETATM", 6, "HOH", 301, "O")
                + record("HETATM", 7, "ZN", 401, "ZN") + record("HETATM", 8, "NA", 402, "NA"), encoding="utf-8")
            original = source.read_bytes()
            result = filter_receptor_pdb(source, target)
            text = target.read_text(encoding="utf-8")
            self.assertEqual(source.read_bytes(), original)
            self.assertEqual(result["retained_linked_components"], ["ADX:A:101"])
            self.assertEqual(sum(line.startswith("ATOM  ") for line in text.splitlines()), 2)
            for retained in ("CRYST1", "SCALE1", "CSO", "ADX", "ZN"):
                self.assertIn(retained, text)
            for omitted in ("LIG", "HOH", "NA"):
                self.assertNotIn(omitted, text)

    @unittest.skipIf(os.name == "nt", "Compare the original POSIX implementation on its native platform")
    def test_public_receptors_match_original_filter_byte_for_byte(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sources = sorted((ROOT / "examples/tutorials").glob("*/inputs/*.pdb"))
            self.assertTrue(sources)
            for number, source in enumerate(sources):
                with self.subTest(source=source.name):
                    expected, actual = root / f"legacy-{number}.pdb", root / f"native-{number}.pdb"
                    subprocess.run(["bash", "-c", '. "$1"; filter_receptor_input "$2" "$3"', "filter-parity",
                                    str(ROOT / "libexec/docking-universal-prepare-support.sh"), str(source), str(expected)], check=True)
                    filter_receptor_pdb(source, actual)
                    self.assertEqual(actual.read_bytes(), expected.read_bytes())
                    assignments = subprocess.check_output(["bash", "-c", '. "$1"; disulfide_template_assignments "$2"', "disulfide-parity",
                        str(ROOT / "libexec/docking-universal-prepare-support.sh"), str(source)], text=True).strip()
                    self.assertEqual(disulfide_templates(source), assignments)
