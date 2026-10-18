import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.native_entrypoint import isolated_environment, launch_command, main


class NativeEntrypointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / "Native Ω test with spaces"
        self.app = self.root / "app"
        self.app.mkdir(parents=True)
        self.config = {"schema": "docking-universal-native-preview-v1", "host_python": "runtimes/host/python.exe",
                       "gui_python": "runtimes/gui/python.exe", "vina_executable": "engines/vina.exe",
                       "vina_sha256": hashlib.sha256(b"test pinned engine").hexdigest()}
        for key in ("host_python", "gui_python", "vina_executable"):
            path = self.root / self.config[key]
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"test pinned engine")
        (self.app / "native-preview.json").write_text(json.dumps(self.config), encoding="utf-8")
        (self.app / "VERSION").write_text("test-version", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_desktop_launch_keeps_arguments_literal_and_runtimes_separate(self):
        selected = str(self.root / 'results Ω & test')
        command, environment = launch_command(self.app, self.config, ["desktop", "--state-root", selected])
        self.assertEqual(command[0], str(self.root / self.config["gui_python"]))
        self.assertEqual(command[command.index("--host-python") + 1], str(self.root / self.config["host_python"]))
        self.assertEqual(command[-1], selected)
        self.assertNotIn("cmd.exe", command)
        self.assertNotIn("bash", command)

    def test_unsupported_workflow_never_launches_a_process(self):
        with patch("docking_universal.native_entrypoint.subprocess.call") as run:
            self.assertEqual(main(["prepare-receptor", "--input", "private.pdb"], app=self.app), 2)
            run.assert_not_called()

    def test_engine_choice_cannot_be_silently_substituted(self):
        for flag in ("--engine", "--engine=ad4", "--engine-command", "--engine-env", "--vina-backend=api"):
            with self.subTest(flag=flag), self.assertRaisesRegex(ValueError, "engine overrides"):
                launch_command(self.app, self.config, ["dock", flag])

    def test_pinned_prepared_input_dock_is_a_python_command_not_a_batch_file(self):
        command, environment = launch_command(self.app, self.config, ["dock", "--receptor", "a & b.pdbqt"])
        self.assertEqual(command[0], str(self.root / self.config["host_python"]))
        self.assertIn("a & b.pdbqt", command)
        self.assertEqual(command[-1], "cli")
        self.assertEqual(environment["DOCKING_UNIVERSAL_PYTHON"], command[0])
        (self.root / self.config["vina_executable"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            launch_command(self.app, self.config, ["dock"])

    def test_full_install_check_never_claims_success_for_preview(self):
        self.assertEqual(main(["check-install"], app=self.app), 0)
        self.assertEqual(main(["check-install", "--full"], app=self.app), 1)

    def test_foreign_python_and_qt_configuration_is_not_inherited(self):
        values = isolated_environment(self.root, {"PATH": "system-path", "PYTHONHOME": "foreign",
            "PYTHONPATH": "foreign", "QT_PLUGIN_PATH": "Qt5", "KEEP_ME": "yes"})
        self.assertNotIn("PYTHONHOME", values)
        self.assertNotIn("PYTHONPATH", values)
        self.assertNotIn("QT_PLUGIN_PATH", values)
        self.assertEqual(values["KEEP_ME"], "yes")
        self.assertEqual(values["PYTHONIOENCODING"], "utf-8")

    def test_staging_excludes_checkout_libraries_and_generated_outputs(self):
        root = self.root / "fixture-source"
        package = root / "libexec/docking_universal"
        package.mkdir(parents=True)
        for relative, content in (("libexec/entry.py", "pass"),
                                  ("libexec/docking_universal/__init__.py", ""),
                                  ("libexec/docking_universal/node_modules/secret.js", "never copy"),
                                  ("libexec/docking_universal/results/private.pdb", "never copy"),
                                  ("studies/state.json", "never copy"), ("VERSION", "test"), ("LICENSE", "test")):
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        script = Path(__file__).parents[1] / "tools/install_native_windows.py"
        spec = importlib.util.spec_from_file_location("native_installer", script)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        out = self.root / "staged"
        hashes = module.copy_application(root, out)
        self.assertEqual(set(hashes), {"entry.py", "docking_universal/__init__.py", "VERSION", "LICENSE"})
        with self.assertRaises(FileExistsError):
            module.copy_application(root, out)
