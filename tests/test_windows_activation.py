import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from docking_universal.windows_activation import REPAIRS, repair_opencl_activation

FIXTURES = Path(__file__).parent / "fixtures/windows_opencl"


class WindowsActivationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.prefix = Path(self.temporary.name) / "Native prefix with spaces"
        for relative in REPAIRS:
            path = self.prefix / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FIXTURES / path.name, path)

    def tearDown(self):
        self.temporary.cleanup()

    def test_known_scripts_are_repaired_with_backups_but_dll_is_unchanged(self):
        dll = self.prefix / "Library/bin/OpenCL.dll"
        dll.parent.mkdir(parents=True)
        dll.write_bytes(b"unchanged test DLL identity")
        original = {relative: (self.prefix / relative).read_bytes() for relative in REPAIRS}
        result = repair_opencl_activation(self.prefix)
        self.assertEqual(result["status"], "repaired")
        self.assertEqual(dll.read_bytes(), b"unchanged test DLL identity")
        for relative in REPAIRS:
            path = self.prefix / relative
            self.assertEqual(path.with_suffix(path.suffix + ".docking-universal-original").read_bytes(), original[relative])
            self.assertNotEqual(path.read_bytes(), original[relative])

    def test_unknown_helper_fails_before_either_file_is_modified(self):
        first, second = list(REPAIRS)
        original = (self.prefix / first).read_bytes()
        (self.prefix / second).write_text("unknown upstream revision\n", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "review required"):
            repair_opencl_activation(self.prefix)
        self.assertEqual((self.prefix / first).read_bytes(), original)
        self.assertFalse(list(self.prefix.rglob("*.docking-universal-original")))

    @unittest.skipUnless(os.name == "nt", "Requires the native Windows command processor")
    def test_native_activation_with_spaced_prefix_and_icd_filename(self):
        self.native_activation(with_icd=True)

    @unittest.skipUnless(os.name == "nt", "Requires the native Windows command processor")
    def test_native_empty_vendor_directory_keeps_existing_setting(self):
        self.native_activation(with_icd=False)

    def native_activation(self, with_icd):
        repair_opencl_activation(self.prefix)
        if with_icd:
            (self.prefix / "Library/etc/OpenCL/vendors/test vendor.icd").write_text("C:\\Test Vendor\\driver.dll\n", encoding="utf-8")
        script = self.prefix / "activation-test.cmd"
        script.write_text('@echo off\ncall "%CONDA_PREFIX%\\etc\\conda\\activate.d\\khronos-opencl-icd-loader_activate.bat"\n'
                          'if errorlevel 1 exit /b 11\nset OCL_ICD_FILENAMES\n', encoding="utf-8")
        result = subprocess.run([os.environ["COMSPEC"], "/d", "/c", str(script)], capture_output=True,
            text=True, timeout=15, env={**os.environ, "CONDA_PREFIX": str(self.prefix), "OCL_ICD_FILENAMES": "existing"}, check=True)
        expected = "existing;C:\\Test Vendor\\driver.dll" if with_icd else "existing"
        self.assertIn("OCL_ICD_FILENAMES=" + expected, result.stdout)
        self.assertIn("OCL_ICD_FILENAMES_CONDA_BACKUP=existing", result.stdout)
        self.assertFalse((self.prefix / "Library/etc/OpenCL/vendors/temp.txt").exists())
