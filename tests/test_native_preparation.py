import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libexec"))
from docking_universal.native_preparation import meeko_command, prepare_native_candidate, PreparationReviewRequired
from docking_universal.services.preparation import ReceptorPreparationOptions


class NativePreparationTests(unittest.TestCase):
    def test_meeko_boundary_has_no_implicit_deletion_or_altloc(self):
        command = meeko_command(Path("native source.cif"), Path("output"), Path("receptor.pdbqt"))
        self.assertEqual(command[:4], [sys.executable, "-m", "meeko.cli.mk_prepare_receptor", "--read_with_prody"])
        self.assertNotIn("--allow_bad_res", command)
        self.assertNotIn("--default_altloc", command)
        explicit = meeko_command(Path("source.pdb"), Path("output"), Path("receptor.pdbqt"),
                                 templates="A:30=ASP", additional_templates=Path("reviewed.json"))
        self.assertIn("--read_pdb", explicit)
        self.assertEqual(explicit[-4:], ["--set_template", "A:30=ASP", "--add_templates", "reviewed.json"])

    def test_unsupported_methods_stop_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.pdb"
            source.write_text("HEADER  test\n")
            for fields in ({"preparation_backend": "adfr"}, {"pocket_engine": "fpocket"}, {}):
                options = ReceptorPreparationOptions(source, root / "outputs", "pockets", **fields)
                with self.assertRaises(ValueError):
                    prepare_native_candidate(options)
                self.assertFalse((root / "outputs").exists())


if __name__ == "__main__":
    unittest.main()
