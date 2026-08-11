#!/usr/bin/env python3
"""Focused tests for the interactive compound-input chooser."""

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "libexec" / "docking-universal-run.py"
SPEC = importlib.util.spec_from_file_location("docking_universal_run", MODULE_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)


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

    def test_macos_default_routes_to_protocol_finder(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol = Path(directory) / "protocol.json"
            self.write_protocol(protocol)
            with patch.object(RUNNER.platform, "system", return_value="Darwin"), \
                 patch.object(RUNNER.shutil, "which", return_value="/usr/bin/osascript"), \
                 patch.object(RUNNER, "choose_path_with_finder", return_value=protocol) as finder, \
                 patch("builtins.input", return_value=""):
                self.assertEqual(RUNNER.choose_approved_protocol(), protocol.resolve())
                finder.assert_called_once()

    def test_control_folder_discovers_approved_protocol(self):
        with tempfile.TemporaryDirectory() as directory:
            protocol = Path(directory) / "control" / "04_redocking" / "vina" / "repeatability" / "protocol.json"
            self.write_protocol(protocol)
            self.assertEqual(
                RUNNER.choose_approved_protocol_from(Path(directory)), protocol.resolve()
            )


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


if __name__ == "__main__":
    unittest.main()
