#!/usr/bin/env python3

import hashlib
import importlib.util
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BUNDLE_SPEC = importlib.util.spec_from_file_location(
    "docking_universal_bundle", ROOT / "libexec" / "docking_universal_bundle.py"
)
BUNDLE = importlib.util.module_from_spec(BUNDLE_SPEC)
BUNDLE_SPEC.loader.exec_module(BUNDLE)
CREATE_SPEC = importlib.util.spec_from_file_location(
    "docking_universal_create_protocol", ROOT / "libexec" / "docking-universal-create-protocol.py"
)
CREATE = importlib.util.module_from_spec(CREATE_SPEC)
CREATE_SPEC.loader.exec_module(CREATE)


class ProtocolTypeTests(unittest.TestCase):
    def test_legacy_approved_protocol_is_control_validated(self):
        record = {"control_status": "approved", "unknown_docking_allowed": True}
        self.assertEqual(BUNDLE.protocol_type(record), BUNDLE.CONTROL_VALIDATED)

    def test_exploratory_protocol_requires_explicit_authority(self):
        record = {
            "protocol_type": BUNDLE.LIGAND_GUIDED_EXPLORATORY,
            "exploratory_screening_allowed": True,
            "screening_authority": "user-confirmed-exploratory-use",
        }
        self.assertTrue(BUNDLE.protocol_can_screen(record))
        record["screening_authority"] = "automatic"
        self.assertFalse(BUNDLE.protocol_can_screen(record))

    def test_exploratory_bundle_records_type_and_locked_assets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor = root / "target.pdbqt"
            receptor_pdb = root / "target.pdb"
            box = root / "target_pocket1.conf"
            receptor.write_text("RECEPTOR\n")
            receptor_pdb.write_text("ATOM\n")
            box.write_text("center_x = 1\n")
            digest = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
            protocol = root / "target_ligand-guided-exploratory_protocol.json"
            protocol.write_text(json.dumps({
                "schema_name": "docking-universal-protocol", "schema_version": 1,
                "protocol_type": BUNDLE.LIGAND_GUIDED_EXPLORATORY,
                "control_status": "not_performed", "unknown_docking_allowed": False,
                "exploratory_screening_allowed": True,
                "screening_authority": "user-confirmed-exploratory-use",
                "locked_inputs": {
                    "receptor": str(receptor), "receptor_sha256": digest(receptor),
                    "receptor_pdb": str(receptor_pdb),
                    "box": str(box), "box_sha256": digest(box),
                },
            }))
            output = root / "target_ligand-guided-exploratory_2026-08-24.duprotocol"
            BUNDLE.create_bundle(protocol, root, output)
            with zipfile.ZipFile(output) as archive:
                manifest = json.loads(archive.read("bundle_manifest.json"))
            self.assertEqual(manifest["protocol_type"], BUNDLE.LIGAND_GUIDED_EXPLORATORY)
            extracted = BUNDLE.extract_bundle(output)
            extracted_record = json.loads(extracted.read_text())
            self.assertEqual(extracted_record["protocol_type"], BUNDLE.LIGAND_GUIDED_EXPLORATORY)
            self.assertTrue((extracted.parent / extracted_record["locked_inputs"]["receptor_pdb"]).is_file())

    def test_bundle_retains_user_approved_removal_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            receptor = root / "target.pdbqt"
            receptor_pdb = root / "target.pdb"
            box = root / "target.conf"
            removal_log = root / "receptor_user_approved_removal.log"
            removal_record = root / "user_approved_component_removal.txt"
            removal_manifest = root / "user_approved_component_removal.tsv"
            receptor.write_text("ATOM\n")
            receptor_pdb.write_text("ATOM\n")
            box.write_text("center_x = 1\n")
            removal_log.write_text("Files written\n")
            removal_record.write_text("User approved component removal.\n")
            removal_manifest.write_text("chain\tresidue_number\tinsertion_code\tresidue_name\tatom_count\nA\t67\t\tCSO\t8\n")
            protocol = root / "protocol.json"
            protocol.write_text(json.dumps({
                "schema_name": "docking-universal-protocol", "schema_version": 1,
                "protocol_type": BUNDLE.SITE_GUIDED_EXPLORATORY,
                "control_status": "not_performed", "unknown_docking_allowed": False,
                "exploratory_screening_allowed": True,
                "screening_authority": "user-confirmed-exploratory-use",
                "locked_inputs": {"receptor": str(receptor), "receptor_pdb": str(receptor_pdb), "box": str(box)},
                "receptor_preparation": {
                    "user_approved_component_removal": True,
                    "user_approved_component_removal_log": str(removal_log),
                    "user_approved_component_removal_record": str(removal_record),
                    "user_approved_component_removal_manifest": str(removal_manifest),
                },
            }))
            output = root / "approved-removal.duprotocol"
            BUNDLE.create_bundle(protocol, root, output)
            extracted = BUNDLE.extract_bundle(output)
            record = json.loads(extracted.read_text())
            retained = extracted.parent / record["receptor_preparation"]["user_approved_component_removal_manifest"]
            self.assertTrue(retained.is_file())
            self.assertIn("CSO", retained.read_text())

    def test_interactive_type_selection_covers_all_three_protocols(self):
        expected = [
            BUNDLE.CONTROL_VALIDATED,
            BUNDLE.LIGAND_GUIDED_EXPLORATORY,
            BUNDLE.SITE_GUIDED_EXPLORATORY,
        ]
        for answer, protocol_type in zip(("1", "2", "3"), expected):
            with self.subTest(answer=answer), patch("builtins.input", return_value=answer):
                self.assertEqual(CREATE.choose_type(), protocol_type)

    def test_multiple_ligand_and_box_selection(self):
        ligands = [
            {"resname": "AAA", "atoms": "10", "path": Path("AAA.pdb")},
            {"resname": "BBB", "atoms": "20", "path": Path("BBB.pdb")},
        ]
        with patch("builtins.input", return_value="2"):
            self.assertEqual(CREATE.choose_ligand(ligands, None, True)["resname"], "BBB")
        with self.assertRaisesRegex(SystemExit, "Requested ligand MISSING"):
            CREATE.choose_ligand(ligands, "MISSING", False)
        boxes = [Path("pocket1.conf"), Path("pocket2.conf")]
        with patch("builtins.input", return_value="2"):
            self.assertEqual(CREATE.choose_box(boxes, True), boxes[1])
        with self.assertRaisesRegex(SystemExit, "without a docking-box"):
            CREATE.choose_box([], True)

    def test_macos_graphical_structure_selection(self):
        selected = Path("/tmp/selected-structure.pdb")
        with (
            patch.object(CREATE.platform, "system", return_value="Darwin"),
            patch.object(CREATE.shutil, "which", return_value="/usr/bin/osascript"),
            patch.object(CREATE, "finder_file", return_value=selected) as finder,
            patch("builtins.input", return_value="2"),
        ):
            self.assertEqual(CREATE.choose_structure(Path("/tmp/inputs")), selected)
        finder.assert_called_once_with("Choose the structure PDB file")

    def test_ubuntu_structure_selection_prefers_zenity(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / "selected-structure.pdb"
            selected.write_text("ATOM\n")
            with (
                patch.object(CREATE.platform, "system", return_value="Linux"),
                patch.dict(CREATE.os.environ, {"DISPLAY": ":1"}),
                patch.object(CREATE.shutil, "which", side_effect=lambda name: "/usr/bin/zenity" if name == "zenity" else None),
                patch.object(CREATE.subprocess, "run") as run,
                patch("builtins.input", return_value="2"),
            ):
                run.return_value.returncode = 0
                run.return_value.stdout = str(selected) + "\n"
                self.assertEqual(CREATE.choose_structure(Path(directory) / "inputs"), selected.resolve())
            self.assertEqual(run.call_args.args[0][:3], ["zenity", "--file-selection", "--title=Choose the structure PDB file"])

    def test_protocol_output_parent_uses_ubuntu_graphical_folder_chooser(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(CREATE, "graphical_chooser_available", return_value=True),
            patch.object(CREATE, "choose_path_graphically", return_value=Path(directory)) as chooser,
        ):
            self.assertEqual(CREATE.choose_output_parent(), Path(directory))
        chooser.assert_called_once_with(
            "Choose where Docking Universal should save this protocol study", folder=True
        )

    def test_fpocket_fallback_acceptance_and_decline(self):
        self.assertTrue(CREATE.retry_fpocket_fallback(True))
        with patch("builtins.input", return_value=""):
            self.assertTrue(CREATE.retry_fpocket_fallback(False))
        with patch("builtins.input", return_value="n"):
            self.assertFalse(CREATE.retry_fpocket_fallback(False))

    def test_preparation_summary_discloses_user_approved_removal(self):
        with tempfile.TemporaryDirectory() as directory:
            prep = Path(directory)
            receptor = prep / "receptor"
            receptor.mkdir()
            (receptor / "user_approved_component_removal.txt").write_text("User approved component removal.\n")
            self.assertIn("explicitly approved removal", CREATE.preparation_summary(prep))

    def test_approved_removal_summary_names_removed_residues(self):
        with tempfile.TemporaryDirectory() as directory:
            manifest = Path(directory) / "user_approved_component_removal.tsv"
            manifest.write_text("chain\tresidue_number\tinsertion_code\tresidue_name\tatom_count\nT\t4\t\t8OG\t34\n")
            text = CREATE.approved_removal_summary({"receptor_preparation": {
                "user_approved_component_removal": True,
                "user_approved_component_removal_manifest": str(manifest),
            }})
            self.assertIn("explicitly approved", text)
            self.assertIn("1 other residue/component was removed", text)

    def test_approved_removal_summary_escalates_standard_residue_removal(self):
        text = CREATE.approved_removal_summary({"receptor_preparation": {
            "user_approved_component_removal": True,
            "user_approved_removed_components": [
                {"chain": "A", "residue_number": "305", "residue_name": "SER", "atom_count": "5"},
            ],
        }})
        self.assertIn("1 standard amino-acid residue was removed", text)
        self.assertIn("High-severity structural warning", text)

    def test_control_validated_wrapper_uses_repeatability_by_default(self):
        argv = [
            "docking-universal-create-protocol.py", "--type", "control-validated",
            "--complex", "bound.pdb", "--ligand-id", "LIG:A:1",
            "--out", "control-out", "--non-interactive",
        ]
        with patch.object(CREATE.sys, "argv", argv), patch.object(CREATE, "run") as run:
            CREATE.main()
        command = [str(value) for value in run.call_args.args[0]]
        self.assertIn("--control-tier", command)
        self.assertEqual(command[command.index("--control-tier") + 1], "repeatability")
        self.assertEqual(command[command.index("--control-ligand-id") + 1], "LIG:A:1")
        self.assertIn("--non-interactive", command)

    def test_noninteractive_control_requires_exact_ligand_id(self):
        argv = [
            "docking-universal-create-protocol.py", "--type", "control-validated",
            "--complex", "bound.pdb", "--out", "control-out", "--non-interactive",
        ]
        with patch.object(CREATE.sys, "argv", argv), patch.object(CREATE, "run"):
            with self.assertRaisesRegex(SystemExit, "requires --ligand-id"):
                CREATE.main()


if __name__ == "__main__":
    unittest.main()
