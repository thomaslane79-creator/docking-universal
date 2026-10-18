import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("native_installer_manager", ROOT / "tools/install_native_windows.py")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class NativeBootstrapManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.destination = Path(self.temporary.name) / "Native Ω managed installation"
        self.bootstrap = self.destination / ".bootstrap"
        self.manager_root = Path(self.temporary.name) / "managers"
        self.install_id = "abc123" + "0" * 26
        self.prefix = self.manager_root / self.install_id
        self.conda = self.prefix / "Scripts/conda.exe"
        self.python = self.prefix / "python.exe"
        self.asset = {"filename": "pinned-fixture.exe", "sha256": hashlib.sha256(b"fixture installer").hexdigest()}

    def tearDown(self):
        self.temporary.cleanup()

    def stage(self):
        self.conda.parent.mkdir(parents=True)
        self.conda.write_bytes(b"conda fixture")
        self.python.write_bytes(b"python fixture")
        self.bootstrap.mkdir(parents=True)
        (self.bootstrap / self.asset["filename"]).write_bytes(b"fixture installer")
        self.record = {"status": "installed", "asset": self.asset, "private_prefix": str(self.prefix), "install_id": self.install_id}
        self.owner = {"schema": "docking-universal-private-manager-v1", "installation": str(self.destination),
                      "install_id": self.install_id, "sha256": self.asset["sha256"]}
        (self.prefix / "docking-universal-owner.json").write_text(json.dumps(self.owner), encoding="utf-8")
        self.save_record()

    def save_record(self):
        (self.bootstrap / "manager-status.json").write_text(json.dumps(self.record), encoding="utf-8")

    def handoff(self, **overrides):
        options = dict(owned_manager=True, executing_python=self.python, asset=self.asset, manager_root=self.manager_root)
        options.update(overrides)
        return MODULE.reserve_destination(self.destination, self.conda, **options)

    def test_explicit_conda_still_requires_an_entirely_fresh_directory(self):
        result = MODULE.reserve_destination(self.destination, self.conda, owned_manager=False)
        self.assertEqual(result["mode"], "explicit_existing_conda")
        protected = self.destination / "study.txt"; protected.write_bytes(b"preserve me")
        with self.assertRaises(FileExistsError):
            MODULE.reserve_destination(self.destination, self.conda, owned_manager=False)
        self.assertEqual(protected.read_bytes(), b"preserve me")

    def test_verified_private_manager_is_the_only_permitted_preexisting_content(self):
        self.stage()
        result = self.handoff()
        self.assertEqual(result["mode"], "application_owned")
        self.assertEqual(result["asset"], self.asset)
        self.assertEqual({p.name for p in self.destination.iterdir()}, {".bootstrap"})

    def test_old_application_or_unknown_files_cannot_be_overwritten(self):
        self.stage()
        protected = self.destination / "app"; protected.mkdir()
        sentinel = protected / "study.json"; sentinel.write_bytes(b"preserve me")
        with self.assertRaisesRegex(ValueError, "fresh"):
            self.handoff()
        self.assertEqual(sentinel.read_bytes(), b"preserve me")

    def test_private_interpreter_and_conda_must_match_the_owned_prefix(self):
        self.stage()
        with self.assertRaisesRegex(ValueError, "exact private"):
            self.handoff(executing_python=Path("foreign-python.exe"))
        with self.assertRaisesRegex(ValueError, "exact private"):
            MODULE.reserve_destination(self.destination, Path("foreign-conda.exe"), owned_manager=True,
                                       executing_python=self.python, asset=self.asset, manager_root=self.manager_root)

    def test_installer_checksum_is_checked_again_before_installation(self):
        self.stage()
        (self.bootstrap / self.asset["filename"]).write_bytes(b"changed installer")
        with self.assertRaisesRegex(ValueError, "checksum"):
            self.handoff()

    def test_incomplete_or_changed_provenance_is_rejected(self):
        self.stage()
        for field, value in [("status", "failed"), ("asset", {}), ("private_prefix", "elsewhere")]:
            original = self.record[field]
            self.record[field] = value; self.save_record()
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, "provenance"):
                self.handoff()
            self.record[field] = original

    def test_manager_from_another_installation_cannot_be_claimed(self):
        self.stage()
        self.owner["installation"] = "another installation"
        (self.prefix / "docking-universal-owner.json").write_text(json.dumps(self.owner), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "owner"):
            self.handoff()

    def test_manager_pin_and_no_global_setup_flags_are_explicit(self):
        asset = json.loads((ROOT / "dependencies/miniforge-windows.json").read_text())
        self.assertEqual(asset["sha256"], "71cf9519087be74fa53021219ff292beb2fc05fa49e0bb6eb0e0b6b14fccbaab")
        self.assertIn("/releases/download/26.7.2-0/", asset["url"])
        self.assertEqual(asset["license"], "BSD-3-Clause")
        script = (ROOT / "install-windows.ps1").read_text()
        for flag in ["/InstallationType=JustMe", "/RegisterPython=0", "/AddToPath=0", "/NoRegistry=1", "/NoShortcuts=1"]:
            self.assertIn(flag, script)
        self.assertNotIn("Get-Command conda", script)
        self.assertIn("Get-FileHash -LiteralPath $installer", script)


if __name__ == "__main__":
    unittest.main()
