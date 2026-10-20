import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "libexec"))
from docking_universal.native_preparation import meeko_command, prepare_native_candidate, PreparationReviewRequired, retain_exact_selected_boxes
from docking_universal.services.preparation import ReceptorPreparationOptions


class NativePreparationTests(unittest.TestCase):
    def test_ligand_only_candidate_never_starts_java_or_invents_a_pocket_score(self):
        fixture = Path(__file__).resolve().parents[1] / 'examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb'
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'bound.pdb'; source.write_bytes(fixture.read_bytes())
            options = ReceptorPreparationOptions(source, root / 'outputs', 'ligand',
                ligand_resname='MK1', ligand_chain_id='B', ligand_residue_number='902', reduce2='off')
            calls = []
            def runner(command, **kwargs):
                calls.append(command)
                if 'meeko.cli.mk_prepare_receptor' in command:
                    Path(command[command.index('-p') + 1]).write_text('synthetic receptor fixture\n')
                return subprocess.CompletedProcess(command, 0)
            with patch('docking_universal.native_preparation.importlib.util.find_spec', return_value=object()), \
                 patch('docking_universal.native_preparation.java_invocation', side_effect=AssertionError('Unrequested detector')):
                output = prepare_native_candidate(options, runner=runner, allow_ligand=True)
            record = json.loads((output / 'native-preparation.json').read_text())
            self.assertEqual(record['status'], 'prepared')
            self.assertFalse(record['pocket_prediction_requested'])
            self.assertFalse(list((output / 'cavity').glob('*.conf')))
            provenance = json.loads((output / 'cavity/pocket_detection_provenance.json').read_text())
            self.assertEqual(provenance['engine'], 'none')
            self.assertFalse(provenance['independent_evidence'])
            self.assertFalse(any('predict' in c or '-v' in c for c in calls))

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

    def test_box_center_precision_and_nonsequential_detector_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            cavity = Path(temporary)
            text = "center_x = 40.018\ncenter_y = 34.735\ncenter_z = -6.211\nsize_x = 26\nsize_y = 26\nsize_z = 26\n"
            config = cavity / "target_pocket1.conf"
            config.write_text(text)
            fourth = cavity / "target_pocket4.conf"
            fourth.write_text(text.replace("size_y = 26", "size_y = 27.948"))
            records = cavity / "selected_pocket_records.txt"
            records.write_text("2.4|pocket1_atm.pdb|40.0182|34.7353|-6.2114|2.4\n1.1|pocket4_atm.pdb|40.0182|34.7353|-6.2114|1.1\n")
            retain_exact_selected_boxes(cavity, "target")
            self.assertIn("center_x = 40.0182", config.read_text())
            self.assertIn("size_y = 27.948", fourth.read_text())
            self.assertFalse((cavity / "target_pocket2.conf").exists())
            self.assertTrue((cavity / "target_pocket4_box.pdb").exists())
            (cavity / "target_pocket3.conf").write_text(text)
            records.write_text(records.read_text().replace("1.1|pocket4", "1.2|pocket3_atm.pdb|40|34|-6|1.2\n1.1|pocket4"))
            before = config.read_bytes()
            with self.assertRaisesRegex(ValueError, "collides"):
                retain_exact_selected_boxes(cavity, "target")
            self.assertEqual(config.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
