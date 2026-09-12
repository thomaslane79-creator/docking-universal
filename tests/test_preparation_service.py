import tempfile
import unittest
from pathlib import Path

from docking_universal.services.preparation import ReceptorPreparationOptions, build_receptor_preparation_plan


class PreparationServiceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.input = self.root / "Target with spaces.pdb"
        self.input.write_text("ATOM      1  CA  GLY A   1       0.000   0.000   0.000  1.00 10.00           C\n")
        self.executable = self.root / "prepare engine.sh"
        self.executable.write_text("#!/usr/bin/env bash\nexit 0\n")

    def tearDown(self):
        self.temporary.cleanup()

    def test_plan_supplies_every_interactive_choice_without_shell_command_text(self):
        plan = build_receptor_preparation_plan(
            self.executable,
            ReceptorPreparationOptions(
                self.input, self.root / "output with spaces", "pockets",
                feedback_level="guided",
            ),
            base_environment={"PATH": "/usr/bin"},
        )
        self.assertEqual(plan.request.command, (str(self.executable.resolve()), str(self.input.resolve())))
        self.assertEqual(plan.request.environment["DOCKING_UNIVERSAL_REMOVAL_PROMPT"], "0")
        self.assertEqual(plan.request.environment["MEEKO_ALLOW_BAD_RES"], "0")
        self.assertEqual(plan.request.environment["DOCKING_UNIVERSAL_SITE_MODE"], "pockets")
        self.assertEqual(plan.request.environment["FEEDBACK_LEVEL"], "guided")
        self.assertIn("Target_with_spaces_receptor_prep", str(plan.receptor_pdbqt))

    def test_ligand_mode_requires_explicit_structural_choice(self):
        options = ReceptorPreparationOptions(self.input, self.root, "ligand")
        with self.assertRaisesRegex(ValueError, "explicitly selected"):
            build_receptor_preparation_plan(self.executable, options)

    def test_model_changing_removal_cannot_be_enabled_by_plan(self):
        plan = build_receptor_preparation_plan(
            self.executable,
            ReceptorPreparationOptions(self.input, self.root, "pockets"),
            base_environment={"MEEKO_ALLOW_BAD_RES": "1", "DOCKING_UNIVERSAL_REMOVAL_PROMPT": "1"},
        )
        self.assertEqual(plan.request.environment["MEEKO_ALLOW_BAD_RES"], "0")
        self.assertEqual(plan.request.environment["DOCKING_UNIVERSAL_REMOVAL_PROMPT"], "0")


if __name__ == "__main__":
    unittest.main()
