from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.plip_runtime import plip_invocation


class NativeInteractionCommandTests(unittest.TestCase):
    def test_windows_relative_io_retains_exact_bytes_and_analysis_flags(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "Native — Ω 化合物"
            root.mkdir()
            source = root / "original & ligand.pdb"
            content = b"HEADER    SYNTHETIC FIXTURE\r\nEND\r\n"
            source.write_bytes(content)
            output = root / "Interaction results"
            output.mkdir()
            with patch("docking_universal.plip_runtime.platform.system", return_value="Windows"):
                command, cwd = plip_invocation("plip", source, output, "-x", "-t")
                self.assertEqual(command, [sys.executable, "-m", "plip.plipcmd", "-f", "plip_input.pdb", "-x", "-t", "-o", "."])
                self.assertEqual(cwd, output)
                self.assertEqual((output / "plip_input.pdb").read_bytes(), content)
                self.assertEqual(source.read_bytes(), content)
                with self.assertRaises(FileExistsError):
                    plip_invocation("plip", source, output, "-x", "-t")

    def test_custom_executable_is_not_replaced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "input.pdb"; source.write_bytes(b"END\n")
            output = root / "output"; output.mkdir()
            with patch("docking_universal.plip_runtime.platform.system", return_value="Windows"), \
                 patch("docking_universal.plip_runtime.locate_script_tool", return_value="custom.exe"), \
                 patch("docking_universal.plip_runtime.script_command", return_value=["custom.exe"]) as script:
                command, cwd = plip_invocation("explicit.exe", source, output, "-y", "-p")
            script.assert_called_once_with("custom.exe")
            self.assertEqual(command, ["custom.exe", "-f", "plip_input.pdb", "-y", "-p", "-o", "."])
            self.assertEqual(cwd, output)

    def test_unix_invocation_is_unchanged(self):
        with patch("docking_universal.plip_runtime.platform.system", return_value="Darwin"):
            command, cwd = plip_invocation("./custom-plip", Path("input.pdb"), Path("results"), "-x", "-t")
        self.assertEqual(command, ["./custom-plip", "-f", "input.pdb", "-x", "-t", "-o", "results"])
        self.assertIsNone(cwd)


if __name__ == "__main__":
    unittest.main()
