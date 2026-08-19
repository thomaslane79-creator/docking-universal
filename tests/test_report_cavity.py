import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "libexec" / "docking-universal-pdf-report.py"
SPEC = importlib.util.spec_from_file_location("docking_universal_pdf_report", SCRIPT)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class CavityReportTests(unittest.TestCase):
    def test_package_version_uses_source_or_installed_version_file(self):
        expected = (SCRIPT.parent.parent / "VERSION").read_text().strip()
        self.assertEqual(REPORT.package_version(), expected)
        original_file = REPORT.__file__
        try:
            with tempfile.TemporaryDirectory() as temporary:
                installed_dir = Path(temporary)
                REPORT.__file__ = str(installed_dir / "docking-universal-pdf-report.py")
                (installed_dir / "VERSION").write_text(expected + "\n")
                self.assertEqual(REPORT.package_version(), expected)
        finally:
            REPORT.__file__ = original_file

    def test_scientific_version_comparison(self):
        recorded = {key: "1.0" for key in ("docking_universal", "python", "rdkit", "molscrub", "meeko", "engine_version")}
        comparison = REPORT.compare_scientific_versions(recorded, dict(recorded))
        self.assertEqual(comparison["overall"], "SAME")
        changed = dict(recorded, meeko="2.0")
        comparison = REPORT.compare_scientific_versions(recorded, changed)
        self.assertEqual(comparison["overall"], "NOT THE SAME")
        self.assertEqual(next(row for row in comparison["entries"] if row["software"] == "Meeko")["status"], "DIFFERENT")

    def test_pubchem_source_suffix_is_not_part_of_compound_name(self):
        self.assertEqual(
            REPORT.display_compound_name("Rilpivirine Pubchem", "rilpivirine_pubchem.sdf"),
            "Rilpivirine",
        )
        self.assertEqual(
            REPORT.display_compound_name("6451164", "rilpivirine_pubchem_6451164.sdf"),
            "Rilpivirine",
        )

    def test_fpocket_descriptors_and_box_volume_inputs(self):
        with tempfile.TemporaryDirectory() as temporary:
            cavity = Path(temporary)
            (cavity / "target_info.txt").write_text(
                "Pocket 5 :\n\tDruggability Score : \t0.321\n\tVolume : \t456.789\n"
            )
            config = cavity / "target_pocket5.conf"
            config.write_text(
                "# source_protein = local.pdb\nsize_x = 20\nsize_y = 21\nsize_z = 22\n"
            )
            descriptors = REPORT.read_fpocket_descriptors(cavity)
            self.assertEqual(descriptors["pocket5_atm.pdb"]["druggability_score"], 0.321)
            self.assertEqual(descriptors["pocket5_atm.pdb"]["volume_angstrom3"], 456.789)
            self.assertEqual(REPORT.read_box_dimensions(config), [20.0, 21.0, 22.0])


if __name__ == "__main__":
    unittest.main()
