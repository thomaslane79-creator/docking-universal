#!/usr/bin/env python3
"""Focused tests for the interactive compound-input chooser."""

import importlib.util
import argparse
import tempfile
import unittest
import sys
import io
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "libexec" / "docking-universal-run.py"
SPEC = importlib.util.spec_from_file_location("docking_universal_run", MODULE_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


class RunCommandSyntaxTests(unittest.TestCase):
    def test_pocket_review_helpers_remain_public_compatibility_exports(self):
        self.assertTrue(callable(RUNNER.describe_prepared_boxes))
        self.assertTrue(callable(RUNNER.prepared_box_records))

    def test_run_screen_positional_workflow(self):
        with patch.object(sys, "argv", ["docking-universal-run.py", "screen"]):
            args = RUNNER.parse_args()
        self.assertEqual(args.workflow, "screen")
        self.assertIsNone(args.mode)

    def test_legacy_mode_spelling_remains_compatible(self):
        with patch.object(sys, "argv", ["docking-universal-run.py", "--mode", "screen"]):
            args = RUNNER.parse_args()
        self.assertEqual(args.mode, "screen")
        self.assertIsNone(args.workflow)

    def test_conflicting_workflow_spellings_are_rejected(self):
        with patch.object(
            sys, "argv",
            ["docking-universal-run.py", "screen", "--mode", "control"],
        ), self.assertRaises(SystemExit):
            RUNNER.parse_args()

    def test_control_ligand_id_public_alias_remains_compatible(self):
        with patch.object(
            sys, "argv",
            ["docking-universal-run.py", "--mode", "control", "--ligand-id", "XK2:A:263"],
        ):
            args = RUNNER.parse_args()
        self.assertEqual(args.control_ligand_id, "XK2:A:263")

    def test_selected_protocol_summary_displays_scientific_identity(self):
        record = {
            "target": "2R8N",
            "protocol_type": "site-guided-exploratory",
            "evidence_basis": "fpocket cavity analysis and user-reviewed docking box",
            "screening_authority": "user-confirmed-exploratory-use",
            "created_utc": "2026-08-24T12:00:00+00:00",
            "locked_inputs": {"box": "2R8N_pocket1.conf"},
        }
        output = io.StringIO()
        with patch("sys.stdout", output):
            RUNNER.print_selected_protocol(record)
        text = output.getvalue()
        for expected in (
            "Target: 2R8N", "Protocol type: Site-guided exploratory",
            "Evidence basis: fpocket cavity analysis", "Screening authority:",
            "Created: 2026-08-24", "Docking box: 2R8N_pocket1.conf",
        ):
            self.assertIn(expected, text)

    def test_selected_protocol_displays_persistent_receptor_warning(self):
        record = {
            "target": "5KRH",
            "protocol_type": "site-guided-exploratory",
            "locked_inputs": {"box": "5KRH_pocket1.conf"},
            "receptor_preparation": {
                "user_approved_component_removal": True,
                "user_approved_removed_components": [
                    {"chain": "A", "residue_number": "305", "residue_name": "SER", "atom_count": "5"},
                ],
            },
        }
        output = io.StringIO()
        with patch("sys.stdout", output):
            RUNNER.print_selected_protocol(record)
        self.assertIn("WARNING: The receptor model was changed", output.getvalue())
        self.assertIn("HIGH-SEVERITY STRUCTURAL MODIFICATION", output.getvalue())


class LigandSourceSelectionTests(unittest.TestCase):
    def test_macos_default_routes_to_finder(self):
        expected = Path("/tmp/selected.sdf")
        with patch.object(RUNNER.platform, "system", return_value="Darwin"), \
             patch.object(RUNNER.shutil, "which", return_value="/usr/bin/osascript"), \
             patch.object(RUNNER, "choose_sdf_with_finder", return_value=expected) as finder, \
             patch("builtins.input", return_value=""):
            self.assertEqual(RUNNER.choose_ligand_source(), expected)
            finder.assert_called_once_with()

    def test_manual_sdf_path(self):
        with tempfile.TemporaryDirectory() as directory:
            sdf = Path(directory) / "compound.sdf"
            sdf.write_text("compound\n$$$$\n")
            with patch.object(RUNNER.platform, "system", return_value="Darwin"), \
                 patch.object(RUNNER.shutil, "which", return_value="/usr/bin/osascript"), \
                 patch("builtins.input", side_effect=["2", str(sdf)]):
                self.assertEqual(RUNNER.choose_ligand_source(), sdf.resolve())


class ApprovedProtocolSelectionTests(unittest.TestCase):
    @staticmethod
    def write_protocol(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"schema_name":"docking-universal-protocol","schema_version":1,'
            '"control_status":"approved","unknown_docking_allowed":true,'
            '"acceptance":{"sampling_pass":true,"ranking_pass":true,'
            '"seed_requirement_pass":true},"engine":"vina",'
            '"calibration_tier":"repeatability","parameters":{"seeds":[1,2,3,4,5]}}'
        )

    def test_macos_default_routes_to_protocol_file(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol = Path(directory) / "study" / "control" / "protocol.json"
            self.write_protocol(protocol)
            with patch.object(RUNNER.platform, "system", return_value="Darwin"), \
                 patch.object(RUNNER.shutil, "which", return_value="/usr/bin/osascript"), \
                 patch.object(RUNNER, "choose_path_with_finder", return_value=protocol) as finder, \
                 patch("builtins.input", return_value=""):
                self.assertEqual(RUNNER.choose_approved_protocol(), protocol.resolve())
                finder.assert_called_once_with(
                    "Choose the reusable .duprotocol bundle or protocol.json"
                )

    def test_report_filename_uses_reused_protocol_receptor(self):
        with tempfile.TemporaryDirectory() as directory:
            name = RUNNER.report_pdf_name(
                Path(directory),
                {
                    "workflow": "screen", "created_utc": "2026-08-24T00:00:00Z",
                    "configured_locked_inputs": {"receptor": "assets/1HVR.pdbqt"},
                },
                [{"compound_name": "Rilpivirine"}],
            )
        self.assertEqual(name, "1HVR_Rilpivirine_2026-08-24_docking_report.pdf")

    def test_portable_bundle_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor = root / "receptor.pdbqt"
            box = root / "pocket.conf"
            receptor.write_text("RECEPTOR\n")
            box.write_text("center_x = 1\n")
            protocol = root / "control" / "protocol.json"
            protocol.parent.mkdir()
            import hashlib, json
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            protocol.write_text(json.dumps({
                "schema_name": "docking-universal-protocol", "schema_version": 1,
                "control_status": "approved", "unknown_docking_allowed": True,
                "locked_inputs": {
                    "receptor": str(receptor), "receptor_sha256": digest(receptor),
                    "box": str(box), "box_sha256": digest(box),
                },
            }))
            bundle = RUNNER.create_bundle(
                protocol, root, root / "test.duprotocol", control_compound="Known inhibitor"
            )
            extracted = RUNNER.materialize_protocol(bundle)
            record = json.loads(extracted.read_text())
            self.assertEqual(RUNNER.protocol_source_filename(extracted), "test.duprotocol")
            self.assertEqual(record["control_evidence"]["compound"], "Known inhibitor")
            self.assertTrue((extracted.parent / record["locked_inputs"]["receptor"]).is_file())
            self.assertTrue((extracted.parent / record["locked_inputs"]["box"]).is_file())

    def test_control_folder_discovers_approved_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol = Path(directory) / "control" / "04_redocking" / "vina" / "repeatability" / "protocol.json"
            self.write_protocol(protocol)
            self.assertEqual(
                RUNNER.choose_approved_protocol_from(Path(directory)), protocol.resolve()
            )

    def test_missing_protocol_offers_to_start_control(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing" / "protocol.json"
            with patch("builtins.input", return_value="1"), \
                 self.assertRaises(RUNNER.StartControlRequested):
                RUNNER.choose_approved_protocol_from(missing)

    def test_missing_protocol_can_switch_to_exploratory(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing" / "protocol.json"
            with patch("builtins.input", return_value="2"), \
                 self.assertRaises(RUNNER.StartExploratoryRequested):
                RUNNER.choose_approved_protocol_from(missing)

    def test_unapproved_protocol_is_distinct_from_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol = Path(directory) / "protocol.json"
            protocol.write_text(
                '{"schema_name":"docking-universal-protocol","schema_version":1,'
                '"control_status":"failed","unknown_docking_allowed":false}'
            )
            with patch("builtins.input", return_value="3"), \
                 self.assertRaisesRegex(SystemExit, "no approved protocol"):
                RUNNER.choose_approved_protocol_from(protocol)


class ControlFolderNamingTests(unittest.TestCase):
    def test_readable_control_name(self):
        self.assertEqual(
            RUNNER.finalized_control_name(
                Path("/inputs/1HVR.pdb"), "XK2:A:263", "20260811_143025"
            ),
            "control_1HVR_XK2_20260811_143025",
        )

    def test_relocation_repairs_absolute_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = root / "control_pending_1HVR_20260811_143025"
            new = root / "control_1HVR_XK2_20260811_143025"
            old.mkdir()
            record = old / "protocol.json"
            record.write_text('{"receptor":"' + str(old / "receptor.pdbqt") + '"}')
            relocated = RUNNER.relocate_study(old, new)
            self.assertEqual(relocated, new.resolve())
            updated = (new / "protocol.json").read_text()
            self.assertIn(str(new.absolute()), updated)
            self.assertNotIn(str(old.absolute()), updated)

    def test_non_macos_default_is_manual_path(self):
        with tempfile.TemporaryDirectory() as directory:
            sdf = Path(directory) / "compound.sdf"
            sdf.write_text("compound\n$$$$\n")
            with patch.object(RUNNER.platform, "system", return_value="Linux"), \
                 patch.object(RUNNER.shutil, "which", return_value=None), \
                 patch("builtins.input", side_effect=["", str(sdf)]):
                self.assertEqual(RUNNER.choose_ligand_source(), sdf.resolve())


class EnsembleSettingsTests(unittest.TestCase):
    @staticmethod
    def defaults():
        return argparse.Namespace(
            ph=7.4, conformers=3, conformers_override=None, base_seed=20260808,
            forcefield="mmff94", rmsd_prune=0.75, skip_tautomers=False,
            charge_model="gasteiger", seeds=5,
        )

    def test_default_choice_preserves_recommended_settings(self):
        args = self.defaults()
        with patch("builtins.input", return_value=""):
            RUNNER.choose_ensemble_settings(args, "exploratory")
        self.assertEqual(args.ph, 7.4)
        self.assertEqual(args.conformers, 3)
        self.assertEqual(args.forcefield, "mmff94")
        self.assertFalse(args.skip_tautomers)

    def test_custom_control_settings_are_applied(self):
        args = self.defaults()
        answers = ["2", "6.5", "8", "1234", "2", "1.1", "n", "gasteiger"]
        with patch("builtins.input", side_effect=answers):
            RUNNER.choose_ensemble_settings(args, "control")
        self.assertEqual(args.ph, 6.5)
        self.assertEqual(args.conformers_override, 8)
        self.assertEqual(args.base_seed, 1234)
        self.assertEqual(args.forcefield, "mmff94s")
        self.assertEqual(args.rmsd_prune, 1.1)
        self.assertTrue(args.skip_tautomers)

    def test_approved_screen_does_not_prompt_or_override_protocol(self):
        args = self.defaults()
        with patch("builtins.input") as prompt:
            RUNNER.choose_ensemble_settings(args, "screen")
        prompt.assert_not_called()


class PocketReviewTests(unittest.TestCase):
    def test_near_tied_pockets_are_marked_competitive(self):
        with tempfile.TemporaryDirectory() as directory:
            cavity = Path(directory) / "cavity"
            cavity.mkdir()
            boxes = [cavity / f"target_pocket{index}.conf" for index in (1, 2, 3)]
            for box in boxes:
                box.write_text("size_x = 26\n")
            (cavity / "pocket_selection_diagnostics.tsv").write_text(
                "rank_order\tpocket_file\tscore\tdecision\n"
                "1\tpocket1_atm.pdb\t0.0861\tselected\n"
                "2\tpocket2_atm.pdb\t0.0725\tselected\n"
                "3\tpocket3_atm.pdb\t0.0125\tselected\n"
            )
            records = RUNNER.prepared_box_records(boxes)
            self.assertTrue(records[0]["competitive"])
            self.assertTrue(records[1]["competitive"])
            self.assertFalse(records[2]["competitive"])
            self.assertEqual(records[1]["row"]["pocket_file"], "pocket2_atm.pdb")


class ReportFilenameTests(unittest.TestCase):
    def test_single_ligand_report_name(self):
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory)
            (study / "inputs").mkdir()
            (study / "inputs" / "2R8N.pdb").write_text("END\n")
            manifest = {"workflow": "exploratory", "created_utc": "2026-08-11T12:00:00Z"}
            compounds = [{"compound_name": "Indinavir"}]
            self.assertEqual(
                RUNNER.report_pdf_name(study, manifest, compounds),
                "2R8N_Indinavir_2026-08-11_docking_report.pdf",
            )

    def test_large_library_report_name_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory)
            (study / "inputs").mkdir()
            (study / "inputs" / "4AKE.pdb").write_text("END\n")
            manifest = {"workflow": "exploratory", "created_utc": "2026-08-11T12:00:00Z"}
            compounds = [{"compound_name": f"Ligand {index}"} for index in range(15)]
            self.assertEqual(
                RUNNER.report_pdf_name(study, manifest, compounds),
                "4AKE_15-ligands_2026-08-11_docking_report.pdf",
            )

    def test_cavity_only_report_name(self):
        with tempfile.TemporaryDirectory() as directory:
            study = Path(directory)
            (study / "inputs").mkdir()
            (study / "inputs" / "4AKE.pdb").write_text("END\n")
            manifest = {"workflow": "exploratory", "created_utc": "2026-08-11T12:00:00Z"}
            self.assertEqual(
                RUNNER.report_pdf_name(study, manifest, []),
                "4AKE_cavity_2026-08-11_cavity_report.pdf",
            )


if __name__ == "__main__":
    unittest.main()
