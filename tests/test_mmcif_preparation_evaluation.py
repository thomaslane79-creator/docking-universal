import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from docking_universal.services.mmcif_preparation_evaluation import (
    compare_structure_paths,
    detect_native_mmcif_capabilities,
    meeko_native_mmcif_command,
)
from tests.test_structure_input import MMCIF


class MmcifPreparationEvaluationTests(unittest.TestCase):
    def test_meeko_native_command_is_explicit_and_does_not_replace_pdb_route(self):
        command = meeko_native_mmcif_command("mk_prepare_receptor.py", "input.cif", "out", "out.pdbqt")
        self.assertEqual(command[:3], ("mk_prepare_receptor.py", "--read_with_prody", "input.cif"))
        self.assertNotIn("--read_pdb", command)

    def test_capability_requires_prody_for_direct_meeko_mmcif(self):
        class Result:
            def __init__(self, code): self.returncode = code
        with patch("docking_universal.services.mmcif_preparation_evaluation.subprocess.run") as run, \
                patch("docking_universal.services.mmcif_preparation_evaluation.Path.is_file", return_value=True):
            run.side_effect = [Result(0), Result(0), Result(1)]
            capabilities = detect_native_mmcif_capabilities("python", "meeko")
        self.assertFalse(capabilities.direct_meeko_mmcif)
        self.assertTrue(any("ProDy" in note for note in capabilities.notes))

    def test_comparison_reports_differences_without_choosing_a_winner(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = root / "first.cif"; first.write_text(MMCIF)
            second = root / "second.cif"; second.write_text(MMCIF.replace("HETATM 2", "HETATM 3"))
            report = compare_structure_paths({"compatibility": first, "native": second})
            self.assertIn("does not automatically", report["interpretation"])
            self.assertEqual(report["pairwise"][0]["identity_jaccard"], 1.0)


if __name__ == "__main__":
    unittest.main()
