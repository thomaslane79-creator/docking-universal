import unittest
from pathlib import Path

from docking_universal.runtime_layout import executable_directories, prefix_for_python


class RuntimeLayoutTests(unittest.TestCase):
    def test_windows_python_lives_at_prefix_root(self):
        root = Path("runtime with spaces")
        self.assertEqual(prefix_for_python(root / "python.exe", windows=True), root)
        self.assertEqual(executable_directories(root, windows=True)[:3],
                         [root, root / "Scripts", root / "Library/bin"])

    def test_unix_python_lives_in_bin(self):
        root = Path("runtime with spaces")
        self.assertEqual(prefix_for_python(root / "bin/python", windows=False), root)
        self.assertEqual(executable_directories(root, windows=False)[0], root / "bin")
