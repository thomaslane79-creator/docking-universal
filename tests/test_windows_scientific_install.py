import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.windows_scientific_install import extract_p2rank, install_scientific_runtime
from docking_universal.windows_scientific_runtime import owned_scientific_python, require_vina_options, stage_command


class ScientificInstallationTests(unittest.TestCase):
    def test_archive_members_are_all_checked_before_any_extraction(self):
        for unsafe in ("root/../escape", "/absolute", "root/C:/escape", "root/..\\escape", "link"):
            with self.subTest(unsafe=unsafe), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                archive = root / "test.tar.gz"
                with tarfile.open(archive, "w:gz") as package:
                    first = tarfile.TarInfo("root/prank.bat"); first.size = 2
                    package.addfile(first, io.BytesIO(b"ok"))
                    bad = tarfile.TarInfo(unsafe)
                    if unsafe == "link":
                        bad.type = tarfile.SYMTYPE; bad.linkname = "outside"
                    package.addfile(bad)
                with self.assertRaises(ValueError):
                    extract_p2rank(archive, root / "destination")
                self.assertFalse((root / "destination").exists())

    def test_archive_extracts_into_fresh_owned_root_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = root / "test.tar.gz"
            with tarfile.open(archive, "w:gz") as package:
                member = tarfile.TarInfo("p2rank/bin/tool.jar"); member.size = 3
                package.addfile(member, io.BytesIO(b"jar"))
            destination = root / "P2Rank Ω with spaces"
            extract_p2rank(archive, destination)
            self.assertEqual((destination / "bin/tool.jar").read_bytes(), b"jar")
            with self.assertRaises(FileExistsError):
                extract_p2rank(archive, destination)

    def test_partial_install_is_never_updated_or_deleted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); prefix = root / "scientific"; prefix.mkdir()
            (prefix / "sentinel").write_text("preserve")
            with patch("docking_universal.windows_scientific_install.subprocess.run") as run:
                with self.assertRaises(FileExistsError):
                    install_scientific_runtime(conda=root / "conda.exe", prefix=prefix, app=root / "app",
                        source_assets=root, work=root / "audit")
                run.assert_not_called()
            self.assertFalse((root / "audit").exists())
            self.assertEqual((prefix / "sentinel").read_text(), "preserve")


class InstalledScientificDispatcherTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / "Owned Ω runtime with spaces"
        self.app = self.root / "app"; self.app.mkdir(parents=True)
        python = self.root / "runtimes/scientific/python.exe"
        java = python.parent / "Library/lib/jvm/bin/java.exe"
        node = python.parent / "node.exe"
        engine = self.root / "engines/vina.exe"
        for path in (python, java, node, engine):
            path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(b"pinned")
        receipt = self.root / ".bootstrap/scientific-install.json"
        receipt.parent.mkdir(parents=True)
        p2rank = self.root / "share/p2rank-2.5.1"
        launcher = p2rank / "docking-universal-launcher"
        launcher.mkdir(parents=True)
        for name in ("NativeArguments.java", "NativeArguments.class"):
            (launcher / name).write_bytes(b"pinned")
        receipt.write_text(json.dumps({"status": "dependencies_installed", "python": str(python),
            "java": str(java), "node": str(node), "p2rank": str(p2rank),
            "java_argument_transport": {key: hashlib.sha256(b"pinned").hexdigest() for key in ("source_sha256", "class_sha256")},
            "browser": str(self.root / "browser.exe")}), encoding="utf-8")
        self.configuration = {"scientific_receipt": str(receipt.relative_to(self.root)),
            "scientific_receipt_sha256": hashlib.sha256(receipt.read_bytes()).hexdigest(),
            "scientific_python": str(python.relative_to(self.root)),
            "vina_executable": str(engine.relative_to(self.root)),
            "vina_sha256": hashlib.sha256(engine.read_bytes()).hexdigest()}

    def tearDown(self):
        self.temporary.cleanup()

    def test_scientific_launch_uses_installed_script_python_and_literal_arguments(self):
        command, environment = stage_command(self.app, self.configuration, "dock", ["--out", "Ω & output"],
            {"PATH": "OS-only", "PYTHONHOME": "foreign", "PYTHONPATH": "source-checkout", "QT_PLUGIN_PATH": "Qt5"})
        self.assertEqual(command[:2], [str(self.root / self.configuration["scientific_python"]), str(self.app / "docking_universal_dock.py")])
        self.assertEqual(command[command.index("--out") + 1], "Ω & output")
        self.assertEqual(command[-2:], ["--vina-backend", "cli"])
        self.assertEqual(environment["DOCKING_UNIVERSAL_CLI"], str(self.app / "docking-universal-native.py"))
        for name in ("PYTHONHOME", "PYTHONPATH", "QT_PLUGIN_PATH"):
            self.assertNotIn(name, environment)

    def test_damaged_install_record_stops_before_any_child_launch(self):
        (self.root / self.configuration["scientific_receipt"]).write_text("changed")
        with self.assertRaisesRegex(ValueError, "receipt changed"):
            stage_command(self.app, self.configuration, "dock", [], {})

    def test_changed_unicode_transport_stops_before_any_job(self):
        launcher = self.root / "share/p2rank-2.5.1/docking-universal-launcher/NativeArguments.class"
        launcher.write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "transport changed"):
            stage_command(self.app, self.configuration, "dock", [], {})

    def test_external_scientific_prefix_requires_exact_private_manager_ownership(self):
        manager = self.root.parent / ("a" * 32)
        manager.mkdir()
        owner = {"schema": "docking-universal-private-manager-v1", "installation": str(self.root),
                 "install_id": manager.name, "sha256": "b" * 64}
        (manager / "docking-universal-owner.json").write_text(json.dumps(owner), encoding="utf-8")
        expected = manager / "runtimes/scientific/python.exe"
        self.configuration.update(scientific_manager={"prefix": str(manager), "install_id": manager.name,
            "asset": {"sha256": owner["sha256"]}}, scientific_python=str(expected),
            package_manager_conda=str(manager / "Scripts/conda.exe"))
        self.assertEqual(owned_scientific_python(self.app, self.configuration), expected)
        owner["installation"] = str(self.root / "some-other-application")
        (manager / "docking-universal-owner.json").write_text(json.dumps(owner), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "another installation"):
            owned_scientific_python(self.app, self.configuration)
        self.configuration.pop("scientific_manager")
        with self.assertRaisesRegex(ValueError, "exact owned runtime"):
            owned_scientific_python(self.app, self.configuration)

    def test_explicit_other_engine_or_custom_override_never_becomes_vina(self):
        for options in (["--engine", "adgpu"], ["--engine=qvinaw"], ["--vina-backend=api"],
                        ["--engine-command", "other.exe"], ["--engine-env=foreign"]):
            with self.subTest(options=options), self.assertRaises(ValueError):
                require_vina_options(options)

    def test_screen_checks_locked_protocol_engine_before_creating_any_outputs(self):
        for engine in ("adgpu", "qvinaw"):
            with self.subTest(engine=engine), patch("docking_universal.services.protocol_import.inspect_protocol_bundle", return_value={"engine": engine}) as inspect:
                with self.assertRaisesRegex(ValueError, "protocol's engine"):
                    stage_command(self.app, self.configuration, "screen", ["--protocol", "test.duprotocol", "--out", str(self.root / "new-study")], {})
                inspect.assert_called_once_with(Path("test.duprotocol"))
                self.assertFalse((self.root / "new-study").exists())
        with self.assertRaisesRegex(ValueError, "explicit approved"):
            stage_command(self.app, self.configuration, "screen", [], {})


if __name__ == "__main__":
    unittest.main()
