import importlib.util
import json
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
        recorded = {key: "1.0" for key in ("docking_universal", "python", "rdkit", "molscrub", "meeko", "pdbfixer", "engine_version")}
        comparison = REPORT.compare_scientific_versions(recorded, dict(recorded))
        self.assertEqual(comparison["overall"], "SAME")
        changed = dict(recorded, meeko="2.0")
        comparison = REPORT.compare_scientific_versions(recorded, changed)
        self.assertEqual(comparison["overall"], "NOT THE SAME")
        self.assertEqual(next(row for row in comparison["entries"] if row["software"] == "Meeko")["status"], "DIFFERENT")

    def test_receptor_preparation_record_distinguishes_pdbfixer_use(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            receptor = study / "preparation" / "target_receptor_prep" / "receptor"
            receptor.mkdir(parents=True)
            self.assertFalse(REPORT.receptor_preparation_record(study)["pdbfixer_used"])
            (receptor / "pdbfixer_audit.json").write_text('{"status": "completed"}\n')
            (receptor / "receptor_after_pdbfixer.log").write_text("success\n")
            record = REPORT.receptor_preparation_record(study)
            self.assertTrue(record["pdbfixer_used"])
            self.assertIn("PDBFixer", record["path"])
            self.assertEqual(record["changes"]["status"], "completed")

    def test_receptor_preparation_record_distinguishes_legacy_linked_component_fallback(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            receptor = study / "preparation" / "target_receptor_prep" / "receptor"
            receptor.mkdir(parents=True)
            (receptor / "receptor_adfr_fallback.log").write_text("legacy preparation succeeded\n")
            record = REPORT.receptor_preparation_record(study)
            self.assertIn("ADFRsuite", record["path"])
            self.assertTrue(record["adfr_fallback_log"].endswith("receptor_adfr_fallback.log"))

    def test_receptor_preparation_record_recovers_external_preparation_route(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            prepared = temporary / "prepared" / "target_receptor_prep" / "receptor"
            prepared.mkdir(parents=True)
            receptor = prepared / "target.pdbqt"
            receptor.write_text("REMARK prepared receptor\n")
            (prepared / "receptor_disulfide_retry.log").write_text("CYX retry succeeded\n")
            study = temporary / "study"
            manifest = study / "compounds" / "ligand" / "seed_1" / "docking" / "run_manifest.tsv"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(f"receptor\t{receptor}\n")
            record = REPORT.receptor_preparation_record(study)
            self.assertIn("CYX disulfide-template retry", record["path"])
            self.assertTrue(record["disulfide_retry_log"].endswith("receptor_disulfide_retry.log"))

    def test_receptor_preparation_record_includes_ccd_audit(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            receptor = study / "preparation" / "target_receptor_prep" / "receptor"
            receptor.mkdir(parents=True)
            (receptor / "ccd_modification_audit.json").write_text(json.dumps({
                "modified_polymer_residue_count": 1,
                "residues": [{"residue": "A:67", "component": "CSO"}],
            }) + "\n")
            record = REPORT.receptor_preparation_record(study)
            self.assertEqual(record["ccd_modifications"]["modified_polymer_residue_count"], 1)
            self.assertTrue(record["ccd_modification_audit"].endswith("ccd_modification_audit.json"))

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
