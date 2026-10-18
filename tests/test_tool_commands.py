from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.tool_commands import script_command, locate_script_tool

HOST_PATH = type(Path())


class NativeToolCommandTests(unittest.TestCase):
    def test_windows_python_script_uses_explicit_interpreter_and_literal_arguments(self):
        with patch("docking_universal.tool_commands.os.name", "nt"):
            # Avoid constructing a host-incompatible WindowsPath in a mocked
            # platform test; production uses the real native Path class.
            with patch("docking_universal.tool_commands.Path", HOST_PATH):
                self.assertEqual(script_command("Scripts/meeko.py", "a & b — ligand.sdf"),
                                 [sys.executable, "Scripts/meeko.py", "a & b — ligand.sdf"])
                with self.assertRaises(ValueError):
                    script_command("tool.cmd", "coordinates.pdb")
                self.assertEqual(script_command("tool.exe", "literal"), ["tool.exe", "literal"])

    def test_unix_command_is_not_changed(self):
        with patch("docking_universal.tool_commands.os.name", "posix"):
            with patch("docking_universal.tool_commands.Path", HOST_PATH):
                self.assertEqual(script_command("tool.py", "literal"), ["tool.py", "literal"])
                self.assertEqual(script_command("./tool", "literal"), ["./tool", "literal"])


if __name__ == "__main__":
    unittest.main()
