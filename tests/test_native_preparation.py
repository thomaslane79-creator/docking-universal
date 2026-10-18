import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

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

    def test_partial_failed_pdbqt_cannot_satisfy_next_attempt(self):
        fixture = Path(__file__).resolve().parents[1] / "examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb"
        before = fixture.read_bytes()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            p2rank = root / "p2rank"
            (p2rank / "bin/lib").mkdir(parents=True)
            (p2rank / "bin/p2rank.jar").touch()
            java = root / "java.exe"; java.touch()
            calls = []

            def runner(command, **kwargs):
                calls.append(command)
                if command[-1] == "-v":
                    kwargs["stdout"].write("P2Rank 2.5.1\n")
                elif "meeko.cli.mk_prepare_receptor" in command:
                    output = Path(command[command.index("-p") + 1])
                    if not output.with_name(output.name + ".before-receptor_after_pdbfixer").exists():
                        output.write_text("PARTIAL INVALID OUTPUT\n")
                        return subprocess.CompletedProcess(command, 1)
                    # Deliberately return zero without producing output.
                elif command[1].endswith("docking-universal-pdbfixer.py"):
                    Path(command[3]).write_bytes(Path(command[2]).read_bytes())
                return subprocess.CompletedProcess(command, 0)

            options = ReceptorPreparationOptions(fixture, root / "outputs", "pockets", reduce2="off")
            with patch("docking_universal.native_preparation.importlib.util.find_spec", return_value=object()):
                with self.assertRaises(PreparationReviewRequired):
                    prepare_native_candidate(options, p2rank=p2rank, java=java, runner=runner)
            record = json.loads((root / "outputs/2R8N_receptor_prep/receptor/preparation_intervention.json").read_text())
            self.assertEqual(record["kind"], "review_required")
            self.assertEqual(fixture.read_bytes(), before)
            self.assertFalse(any("--allow_bad_res" in command for command in calls))
            self.assertFalse(any("predict" in command for command in calls))


if __name__ == "__main__":
    unittest.main()
