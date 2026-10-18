import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("native_scientific", ROOT / "validation/native_windows_scientific.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NativeScientificSpecificationTests(unittest.TestCase):
    def test_every_scientific_pin_is_preserved(self):
        source = (ROOT / "environment.yml").read_text(encoding="utf-8")
        actual = MODULE.scientific_specification(source)
        expected = [line for line in source.splitlines() if not line.startswith("name:")
                    and line not in {"  - make", "  - fpocket=4.2.2"}]
        self.assertEqual(actual.splitlines(), expected)
        for required in ("python=3.9.23", "rdkit=2023.09.6", "cctbx-base", "meeko==0.7.1", "reportlab==4.2.5"):
            self.assertIn(required, actual)

    def test_changed_omission_requires_review_not_silent_filtering(self):
        with self.assertRaisesRegex(ValueError, "review"):
            MODULE.scientific_specification("dependencies:\n  - fpocket=5\n")
