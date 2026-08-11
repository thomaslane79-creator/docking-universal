import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "libexec" / "docking-universal-pdf-report.py"
SPEC = importlib.util.spec_from_file_location("docking_universal_pdf_report", SCRIPT)
REPORT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPORT)


class CavityReportTests(unittest.TestCase):
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
