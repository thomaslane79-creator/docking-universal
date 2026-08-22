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

    def test_retained_versions_do_not_use_later_report_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            report = study / "report"
            report.mkdir()
            summary = {"docking_universal_version": "0.4.0"}
            (report / "study_summary.json").write_text(json.dumps(summary) + "\n")
            (report / "software_versions_and_references.json").write_text(json.dumps({
                "control_to_new_run_version_check": {
                    "entries": [
                        {"software": "Docking Universal", "new_run_version": "0.6.0"},
                        {"software": "Meeko", "new_run_version": "0.7.1"},
                    ],
                },
            }) + "\n")
            retained = REPORT.retained_scientific_versions(
                study, summary, {"engine_version": "AutoDock Vina v1.2.7"}
            )
            self.assertEqual(retained["docking_universal"], "0.4.0")
            self.assertEqual(retained["meeko"], "not recorded")
            self.assertEqual(retained["engine_version"], "AutoDock Vina v1.2.7")

    def test_compatible_legacy_comparison_can_supply_retained_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            report = study / "report"
            report.mkdir()
            summary = {"docking_universal_version": "0.6.0"}
            (report / "study_summary.json").write_text(json.dumps(summary) + "\n")
            (report / "software_versions_and_references.json").write_text(json.dumps({
                "control_to_new_run_version_check": {
                    "entries": [
                        {"software": "Docking Universal", "new_run_version": "0.6.0"},
                        {"software": "Meeko", "new_run_version": "0.7.1"},
                    ],
                },
            }) + "\n")
            retained = REPORT.retained_scientific_versions(study, summary, {})
            self.assertEqual(retained["docking_universal"], "0.6.0")
            self.assertEqual(retained["meeko"], "0.7.1")

    def test_compatible_legacy_software_table_can_migrate_exploratory_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            report = study / "report"
            report.mkdir()
            summary = {"docking_universal_version": "0.6.0"}
            (report / "study_summary.json").write_text(json.dumps(summary) + "\n")
            (report / "software_versions_and_references.json").write_text(json.dumps({
                "control_to_new_run_version_check": None,
                "software": [
                    {"software": "Docking Universal", "version": "0.6.0"},
                    {"software": "fpocket", "version": "4.2.2"},
                    {"software": "Meeko", "version": "0.7.1"},
                ],
            }) + "\n")
            retained = REPORT.retained_scientific_versions(study, summary, {})
            self.assertEqual(retained["fpocket"], "4.2.2")
            self.assertEqual(retained["meeko"], "0.7.1")

    def test_retained_artifacts_recover_openbabel_and_plip_versions(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            report = study / "report"
            interactions = study / "compounds" / "ligand" / "pose_analysis" / "cluster_001" / "interactions"
            report.mkdir(parents=True)
            interactions.mkdir(parents=True)
            summary = {"docking_universal_version": "0.6.0"}
            (report / "study_summary.json").write_text(json.dumps(summary) + "\n")
            (interactions / "complex_protonated.pdb").write_text(
                "HEADER    RETAINED COMPLEX\nAUTHOR    GENERATED BY OPEN BABEL 3.1.0\n"
            )
            (interactions / "report.xml").write_text(
                "<?xml version='1.0'?><report><plipversion>2.3.1</plipversion></report>\n"
            )
            retained = REPORT.retained_scientific_versions(study, summary, {})
            self.assertEqual(retained["openbabel"], "3.1.0")
            self.assertEqual(retained["plip"], "2.3.1")

    def test_report_rejects_missing_version_for_used_software(self):
        provenance = {
            "software": [
                {"software": "Open Babel", "version": "3.1.0"},
                {"software": "PLIP", "version": "not recorded"},
            ],
            "control_to_new_run_version_check": None,
        }
        with self.assertRaisesRegex(SystemExit, "PLIP: not recorded"):
            REPORT.require_complete_used_versions(provenance)

    def test_report_accepts_complete_versions_for_used_software(self):
        provenance = {
            "software": [
                {"software": "Open Babel", "version": "3.1.0"},
                {"software": "PLIP", "version": "2.3.1"},
            ],
            "control_to_new_run_version_check": {
                "entries": [{
                    "software": "Meeko",
                    "control_version": "0.7.1",
                    "new_run_version": "0.7.1",
                }],
            },
        }
        REPORT.require_complete_used_versions(provenance)

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

    def test_multi_ligand_results_are_read_for_every_compound(self):
        with tempfile.TemporaryDirectory() as temporary:
            study = Path(temporary)
            compounds = [
                {"compound_id": "ligand_a", "compound_name": "Ligand A", "status": "COMPLETED", "selected_representatives": 2},
                {"compound_id": "ligand_b", "compound_name": "Ligand B", "status": "COMPLETED", "selected_representatives": 3},
            ]
            for compound_id, score, cluster_id, count in (
                ("ligand_a", "-8.1", "4", 2),
                ("ligand_b", "-9.7", "7", 3),
            ):
                analysis = study / "compounds" / compound_id / "pose_analysis"
                analysis.mkdir(parents=True)
                rows = ["energy_rank,cluster_id,best_energy_kcal_per_mol,pose_count,seed_support,conformer_support"]
                rows.extend(f"{rank},{cluster_id},{score},38,5,3" for rank in range(1, count + 1))
                (analysis / "cluster_summary.csv").write_text("\n".join(rows) + "\n")
            records = REPORT.compound_result_records(
                study, compounds, ["Ligand A", "Ligand B"]
            )
            self.assertEqual([record["name"] for record in records], ["Ligand A", "Ligand B"])
            self.assertEqual(records[0]["best_energy_kcal_per_mol"], "-8.1")
            self.assertEqual(records[0]["cluster_count"], 2)
            self.assertEqual(records[1]["best_energy_kcal_per_mol"], "-9.7")
            self.assertEqual(records[1]["top_cluster"], "7")
            self.assertEqual(records[1]["cluster_count"], 3)
            self.assertEqual(records[1]["top_cluster_population"], "38")
            self.assertEqual(records[1]["top_cluster_seed_support"], "5")
            summary_rows = REPORT.single_compound_summary_rows(records[1], protocol={"approved": True})
            self.assertIn(["Ligand docked", "Ligand B"], summary_rows)
            self.assertIn(["Independent-seed support", "5"], summary_rows)
            self.assertIn(["Selected representatives", "3"], summary_rows)

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
