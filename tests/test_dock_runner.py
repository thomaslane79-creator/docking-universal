import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOCK = ROOT / "libexec" / "docking-universal-dock"


class DockRunnerCharacterizationTests(unittest.TestCase):
    """Lock the observable contract of the shell docking stage before migration."""

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.receptor = self.root / "receptor.pdbqt"
        self.receptor.write_text(
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00  0.00           C\n",
            encoding="utf-8",
        )
        self.config = self.root / "box.conf"
        self.config.write_text(
            "center_x = 0\ncenter_y = 0\ncenter_z = 0\n"
            "size_x = 20\nsize_y = 20\nsize_z = 20\n",
            encoding="utf-8",
        )
        self.ligands = self.root / "ligands"
        self.ligands.mkdir()
        (self.ligands / "alpha.pdbqt").write_text("MODEL\n", encoding="utf-8")
        (self.ligands / "beta.pdbqt").write_text("MODEL\n", encoding="utf-8")
        # Engine outputs copied into an input directory must never become inputs.
        (self.ligands / "old_out.pdbqt").write_text("MODEL\n", encoding="utf-8")
        self.argument_log = self.root / "engine-arguments.txt"
        self.engine = self.root / "fake engine"
        self.engine.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import os
                import pathlib
                import sys

                if sys.argv[1:] == ["--version"]:
                    print("AutoDock Vina characterization-1.0")
                    raise SystemExit(0)
                argument_log = pathlib.Path(os.environ["DOCK_ARGUMENT_LOG"])
                with argument_log.open("a", encoding="utf-8") as stream:
                    stream.write(repr(sys.argv[1:]) + "\\n")
                output = pathlib.Path(sys.argv[sys.argv.index("--out") + 1])
                ligand = pathlib.Path(sys.argv[sys.argv.index("--ligand") + 1])
                if os.environ.get("DOCK_FAIL_LIGAND") == ligand.stem:
                    output.write_text("partial output\\n", encoding="utf-8")
                    raise SystemExit(7)
                output.write_text("MODEL 1\\nENDMDL\\n", encoding="utf-8")
                """
            ),
            encoding="utf-8",
        )
        self.engine.chmod(self.engine.stat().st_mode | stat.S_IXUSR)

    def tearDown(self):
        self.temporary_directory.cleanup()

    def run_dock(self, *extra_arguments, output_name="results", environment=None):
        output = self.root / output_name
        command = [
            str(DOCK),
            "--engine",
            "quickvina-w",
            "--engine-command",
            str(self.engine),
            "--receptor",
            str(self.receptor),
            "--ligands",
            str(self.ligands),
            "--config",
            str(self.config),
            "--out",
            str(output),
            *extra_arguments,
        ]
        process_environment = os.environ.copy()
        process_environment["DOCK_ARGUMENT_LOG"] = str(self.argument_log)
        if environment:
            process_environment.update(environment)
        completed = subprocess.run(command, text=True, capture_output=True, env=process_environment)
        return completed, output

    def test_forwards_engine_options_and_records_artifacts(self):
        completed, output = self.run_dock(
            "--exhaustiveness",
            "7",
            "--num-modes",
            "4",
            "--energy-range",
            "6",
            "--seed",
            "41001",
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout,
            "Docking-box preflight passed: 1 receptor atoms are inside the search box.\n"
            f"run   alpha\nrun   beta\nBatch complete: {output}\n"
            "Successful docking jobs: 2\nFailed docking jobs: 0\nSkipped existing jobs: 0\n",
        )
        argument_lines = self.argument_log.read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(argument_lines), 2)
        self.assertTrue(all("old_out.pdbqt" not in line for line in argument_lines))
        self.assertTrue(all("'--exhaustiveness', '7'" in line for line in argument_lines))
        self.assertTrue(all("'--num_modes', '4'" in line for line in argument_lines))
        self.assertTrue(all("'--energy_range', '6'" in line for line in argument_lines))
        self.assertTrue(all("'--seed', '41001'" in line for line in argument_lines))
        manifest = (output / "run_manifest.tsv").read_text(encoding="utf-8")
        self.assertIn("engine\tqvinaw\n", manifest)
        self.assertIn("engine_version\tAutoDock Vina characterization-1.0\n", manifest)
        self.assertIn("engine_source\texplicit executable\n", manifest)
        self.assertIn(f"engine_command\t{self.engine}\n", manifest)
        self.assertTrue((output / "box.conf.used").is_file())
        self.assertEqual((output / "box.conf.used").read_bytes(), self.config.read_bytes())

    def test_skip_existing_preserves_output_and_reports_count(self):
        output = self.root / "skip-results"
        output.mkdir()
        existing = output / "alpha_qvinaw.pdbqt"
        existing.write_text("keep me\n", encoding="utf-8")

        completed, _ = self.run_dock("--skip-existing", output_name="skip-results")

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(existing.read_text(encoding="utf-8"), "keep me\n")
        self.assertIn("skip  alpha\n", completed.stdout)
        self.assertIn("run   beta\n", completed.stdout)
        self.assertIn("Successful docking jobs: 1\n", completed.stdout)
        self.assertIn("Skipped existing jobs: 1\n", completed.stdout)

    def test_failure_removes_partial_output_but_continues_batch(self):
        completed, output = self.run_dock(environment={"DOCK_FAIL_LIGAND": "alpha"})

        self.assertEqual(completed.returncode, 1)
        self.assertFalse((output / "alpha_qvinaw.pdbqt").exists())
        self.assertTrue((output / "beta_qvinaw.pdbqt").is_file())
        self.assertIn("ERROR: qvinaw failed for alpha", completed.stderr)
        self.assertIn("Successful docking jobs: 1\n", completed.stdout)
        self.assertIn("Failed docking jobs: 1\n", completed.stdout)

    def test_missing_inputs_fail_before_creating_output(self):
        output = self.root / "not-created"
        completed = subprocess.run(
            [str(DOCK), "--engine", "vina", "--out", str(output)],
            text=True,
            capture_output=True,
        )

        self.assertEqual(completed.returncode, 2)
        self.assertFalse(output.exists())
        self.assertIn("prepared docking inputs are required", completed.stderr)


if __name__ == "__main__":
    unittest.main()
