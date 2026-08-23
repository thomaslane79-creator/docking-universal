#!/usr/bin/env python3
"""Branch coverage for every choice exposed by the guided Python interface."""

import argparse
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "libexec" / "docking-universal-run.py"
SPEC = importlib.util.spec_from_file_location("docking_universal_guided", MODULE_PATH)
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)

CALIBRATE_PATH = Path(__file__).resolve().parents[1] / "libexec" / "docking-universal-calibrate.py"
CALIBRATE_SPEC = importlib.util.spec_from_file_location("docking_universal_calibrate", CALIBRATE_PATH)
CALIBRATE = importlib.util.module_from_spec(CALIBRATE_SPEC)
CALIBRATE_SPEC.loader.exec_module(CALIBRATE)


def ensemble_defaults():
    return argparse.Namespace(
        ph=7.4, conformers=3, conformers_override=None, base_seed=20260808,
        forcefield="mmff94", rmsd_prune=0.75, skip_tautomers=False,
        charge_model="gasteiger", seeds=5,
    )


def write_protocol(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        '{"schema_name":"docking-universal-protocol","schema_version":1,'
        '"control_status":"approved","unknown_docking_allowed":true,'
        '"acceptance":{"sampling_pass":true,"ranking_pass":true,'
        '"seed_requirement_pass":true},"engine":"vina",'
        '"calibration_tier":"repeatability","parameters":{"seeds":[1,2,3,4,5]}}'
    )


class StudyPathwayTests(unittest.TestCase):
    def test_all_three_study_choices(self):
        for choice, expected in (("1", "control"), ("2", "screen"), ("3", "exploratory")):
            with self.subTest(choice=choice), patch("builtins.input", return_value=choice):
                self.assertEqual(RUNNER.choose_mode(), expected)

    def test_invalid_study_choice_is_rejected(self):
        with patch("builtins.input", return_value="9"):
            self.assertIsNone(RUNNER.choose_mode())

    def test_output_parent_defaults_to_current_directory(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(RUNNER.platform, "system", return_value="Linux"), \
             patch.object(RUNNER, "graphical_chooser_available", return_value=False), \
             patch.object(RUNNER.Path, "cwd", return_value=Path(temporary)), \
             patch("builtins.input", return_value=""):
            self.assertEqual(RUNNER.choose_output_parent(), Path(temporary).resolve())

    def test_output_parent_accepts_an_explicit_path(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(RUNNER.platform, "system", return_value="Linux"), \
             patch.object(RUNNER, "graphical_chooser_available", return_value=False), \
             patch("builtins.input", return_value=temporary):
            self.assertEqual(RUNNER.choose_output_parent(), Path(temporary).resolve())

    def test_output_parent_uses_finder_folder_chooser_on_macos(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(RUNNER.platform, "system", return_value="Darwin"), \
             patch.object(RUNNER.shutil, "which", return_value="/usr/bin/osascript"), \
             patch.object(RUNNER.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = temporary + "\n"
            self.assertEqual(RUNNER.choose_output_parent(), Path(temporary).resolve())
            self.assertIn("choose folder", run.call_args.args[0][2])

    def test_output_parent_uses_graphical_chooser_on_ubuntu(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(RUNNER.platform, "system", return_value="Linux"), \
             patch.object(RUNNER, "graphical_chooser_available", return_value=True), \
             patch.object(RUNNER, "choose_path_graphically", return_value=Path(temporary)) as chooser:
            self.assertEqual(RUNNER.choose_output_parent(), Path(temporary))
            chooser.assert_called_once_with(
                "Choose where Docking Universal should save this study", folder=True
            )

    def test_front_finder_directory_is_detected_on_macos(self):
        with tempfile.TemporaryDirectory() as temporary, \
             patch.object(RUNNER.platform, "system", return_value="Darwin"), \
             patch.object(RUNNER.shutil, "which", return_value="/usr/bin/osascript"), \
             patch.object(RUNNER.subprocess, "run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = temporary + "\n"
            self.assertEqual(RUNNER.finder_front_directory(), Path(temporary).resolve())

    def test_explicit_output_bypasses_finder_directory(self):
        args = argparse.Namespace(
            non_interactive=False, out=Path("chosen"), complex=None,
            protocol=None, ligands=None, receptor_pdb=None,
            receptor_pdbqt=None, box=None,
        )
        with patch.object(RUNNER, "finder_front_directory") as finder, \
             patch.object(RUNNER.os, "chdir") as chdir:
            RUNNER.use_finder_working_directory(args)
            finder.assert_not_called()
            chdir.assert_not_called()


class CalibrationChoiceTests(unittest.TestCase):
    def test_all_six_calibration_choices(self):
        expected = {
            "1": ("quick", False), "2": ("quick", True),
            "3": ("repeatability", False), "4": ("broader", False),
            "5": ("conformers", False), "6": ("robust", False),
        }
        for choice, result in expected.items():
            with self.subTest(choice=choice):
                self.assertEqual(RUNNER.calibration_strategy(choice), result)

    def test_box_size_boundaries_and_invalid_values(self):
        self.assertEqual(RUNNER.validated_box_size("10"), "10")
        self.assertEqual(RUNNER.validated_box_size("26.0"), "26.0")
        self.assertEqual(RUNNER.validated_box_size("50"), "50")
        for value in ("9.9", "50.1", "text"):
            with self.subTest(value=value), self.assertRaises(SystemExit):
                RUNNER.validated_box_size(value)

    def test_all_manual_retry_tiers_and_inspect_inputs(self):
        result = {"acceptance": {"sampling_pass": False, "ranking_pass": False}}
        expected = {
            "1": "repeatability", "2": "broader", "3": "conformers",
            "4": "robust", "5": None,
        }
        for choice, tier in expected.items():
            with self.subTest(choice=choice), patch("builtins.input", return_value=choice):
                self.assertEqual(CALIBRATE.choose_manual_tier(result), tier)

    def test_retry_approaches_guided_manual_and_stop(self):
        failed = {"acceptance": {"sampling_pass": False, "ranking_pass": False}}
        with patch("builtins.input", return_value="1"):
            self.assertEqual(
                CALIBRATE.choose_retry_strategy("quick", failed),
                ("guided_incremental", "broader"),
            )
        with patch("builtins.input", side_effect=["2", "3"]):
            self.assertEqual(
                CALIBRATE.choose_retry_strategy("quick", failed),
                ("manual", "conformers"),
            )
        with patch("builtins.input", return_value="3"):
            self.assertEqual(
                CALIBRATE.choose_retry_strategy("quick", failed),
                ("inspect_inputs", None),
            )

    def test_guided_escalation_sequence_and_terminal_failure(self):
        failed = {"acceptance": {"sampling_pass": False, "ranking_pass": False}}
        quick_pass = {"acceptance": {"sampling_pass": True, "ranking_pass": True}}
        self.assertEqual(CALIBRATE.guided_next_tier("quick", quick_pass)[0], "repeatability")
        self.assertEqual(CALIBRATE.guided_next_tier("quick", failed)[0], "broader")
        self.assertEqual(CALIBRATE.guided_next_tier("repeatability", failed)[0], "broader")
        self.assertEqual(CALIBRATE.guided_next_tier("broader", failed)[0], "conformers")
        self.assertEqual(CALIBRATE.guided_next_tier("conformers", failed)[0], "robust")
        self.assertIsNone(CALIBRATE.guided_next_tier("robust", failed)[0])


class EnsembleOptionTests(unittest.TestCase):
    def test_all_force_fields_route_from_custom_control(self):
        for choice, expected in (("1", "mmff94"), ("2", "mmff94s"), ("3", "uff")):
            args = ensemble_defaults()
            answers = ["2", "7.4", "4", "42", choice, "0.75", "y", "gasteiger"]
            with self.subTest(choice=choice), patch("builtins.input", side_effect=answers):
                RUNNER.choose_ensemble_settings(args, "control")
            self.assertEqual(args.forcefield, expected)
            self.assertEqual(args.conformers_override, 4)

    def test_exploratory_custom_seed_count_and_tautomer_off(self):
        args = ensemble_defaults()
        answers = ["2", "6.8", "7", "99", "1", "1.0", "n", "gasteiger", "8"]
        with patch("builtins.input", side_effect=answers):
            RUNNER.choose_ensemble_settings(args, "exploratory")
        self.assertEqual(args.seeds, 8)
        self.assertTrue(args.skip_tautomers)

    def test_invalid_custom_values_are_rejected(self):
        args = ensemble_defaults()
        with patch("builtins.input", side_effect=["2", "7.4", "0"]), self.assertRaises(SystemExit):
            RUNNER.choose_ensemble_settings(args, "control")


class InputSourceTests(unittest.TestCase):
    def test_all_complex_source_choices(self):
        chosen = Path("/tmp/complex.pdb")
        with patch("builtins.input", side_effect=["1", "1hvr"]):
            self.assertEqual(RUNNER.choose_complex_source(), Path("1HVR"))
        with patch.object(RUNNER.platform, "system", return_value="Darwin"), \
             patch.object(RUNNER, "choose_file_with_finder", return_value=chosen), \
             patch("builtins.input", return_value="2"):
            self.assertEqual(RUNNER.choose_complex_source(), chosen)
        with patch("builtins.input", side_effect=["3", str(chosen)]):
            self.assertEqual(RUNNER.choose_complex_source(), chosen)

    def test_ligand_finder_file_and_directory_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); sdf = root / "one.sdf"; sdf.write_text("x\n$$$$\n")
            with patch.object(RUNNER.platform, "system", return_value="Darwin"), \
                 patch.object(RUNNER.shutil, "which", return_value="/usr/bin/osascript"), \
                 patch.object(RUNNER, "choose_sdf_with_finder", return_value=sdf), \
                 patch("builtins.input", return_value="1"):
                self.assertEqual(RUNNER.choose_ligand_source(), sdf)
            with patch.object(RUNNER.platform, "system", return_value="Darwin"), \
                 patch.object(RUNNER.shutil, "which", return_value="/usr/bin/osascript"), \
                 patch("builtins.input", side_effect=["2", str(sdf)]):
                self.assertEqual(RUNNER.choose_ligand_source(), sdf.resolve())
            with patch.object(RUNNER.platform, "system", return_value="Darwin"), \
                 patch.object(RUNNER.shutil, "which", return_value="/usr/bin/osascript"), \
                 patch("builtins.input", side_effect=["3", str(root)]):
                self.assertEqual(RUNNER.choose_ligand_source(), root.resolve())

    def test_portable_file_and_directory_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); sdf = root / "one.sdf"; sdf.write_text("x\n$$$$\n")
            with patch.object(RUNNER.platform, "system", return_value="Linux"), \
                 patch.object(RUNNER.shutil, "which", return_value=None), \
                 patch("builtins.input", side_effect=["1", str(sdf)]):
                self.assertEqual(RUNNER.choose_ligand_source(), sdf.resolve())
            with patch.object(RUNNER.platform, "system", return_value="Linux"), \
                 patch.object(RUNNER.shutil, "which", return_value=None), \
                 patch("builtins.input", side_effect=["2", str(root)]):
                self.assertEqual(RUNNER.choose_ligand_source(), root.resolve())


class ProtocolResumeChoiceTests(unittest.TestCase):
    def test_all_four_macos_protocol_choices(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); protocol = root / "control" / "protocol.json"; write_protocol(protocol)
            for choice, finder_value, extra in (
                ("1", protocol, []), ("2", root, []),
                ("3", None, [str(protocol)]), ("4", None, [str(root)]),
            ):
                answers = [choice, *extra]
                with self.subTest(choice=choice), \
                     patch.object(RUNNER.platform, "system", return_value="Darwin"), \
                     patch.object(RUNNER.shutil, "which", return_value="/usr/bin/osascript"), \
                     patch.object(RUNNER, "choose_path_with_finder", return_value=finder_value), \
                     patch("builtins.input", side_effect=answers):
                    self.assertEqual(RUNNER.choose_approved_protocol(), protocol.resolve())

    def test_multiple_approved_protocols_can_select_second(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); first = root / "a" / "protocol.json"; second = root / "b" / "protocol.json"
            write_protocol(first); write_protocol(second)
            with patch("builtins.input", return_value="2"):
                self.assertEqual(RUNNER.choose_approved_protocol_from(root), second.resolve())


class PocketChoiceTests(unittest.TestCase):
    def fixture(self, root):
        cavity = root / "target_receptor_prep" / "cavity"; cavity.mkdir(parents=True)
        boxes = [cavity / f"target_pocket{i}.conf" for i in (1, 2, 3)]
        for box in boxes:
            box.write_text("size_x = 26\n"); box.with_suffix(".pml").write_text("# scene\n")
        (cavity / "pocket_selection_diagnostics.tsv").write_text(
            "rank_order\tpocket_file\tscore\tdecision\n"
            "1\tpocket1_atm.pdb\t0.10\tselected\n"
            "2\tpocket2_atm.pdb\t0.09\tselected\n"
            "3\tpocket3_atm.pdb\t0.01\tselected\n"
        )
        return boxes

    def test_each_box_can_be_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            boxes = self.fixture(Path(directory))
            for index, expected in enumerate(boxes, 1):
                with self.subTest(index=index), patch("builtins.input", return_value=str(index)):
                    self.assertEqual(RUNNER.choose_prepared_box(boxes), expected)

    def test_review_none_number_and_all_competitive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); boxes = self.fixture(root)
            with patch("builtins.input", return_value="n"), patch.object(RUNNER.subprocess, "Popen") as popen:
                self.assertIsNone(RUNNER.review_pocket_scene(root, "/usr/bin/true", interactive=True))
                popen.assert_not_called()
            with patch("builtins.input", return_value="2"), patch.object(RUNNER.subprocess, "Popen") as popen:
                opened = RUNNER.review_pocket_scene(root, "/usr/bin/true", interactive=True)
                self.assertEqual(opened, [str(boxes[1].with_suffix(".pml"))]); self.assertEqual(popen.call_count, 1)
            with patch("builtins.input", return_value="a"), patch.object(RUNNER.subprocess, "Popen") as popen:
                opened = RUNNER.review_pocket_scene(root, "/usr/bin/true", interactive=True)
                self.assertEqual(len(opened), 2); self.assertEqual(popen.call_count, 2)


if __name__ == "__main__":
    unittest.main()
