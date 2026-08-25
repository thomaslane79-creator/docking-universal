#!/usr/bin/env python3

import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "docking_universal_choose_path", ROOT / "libexec" / "docking-universal-choose-path.py"
)
CHOOSER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHOOSER)


class GraphicalChooserTests(unittest.TestCase):
    def test_ubuntu_prefers_zenity_and_selects_folder(self):
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(CHOOSER.platform, "system", return_value="Linux"),
            patch.dict(CHOOSER.os.environ, {"DISPLAY": ":1"}),
            patch.object(CHOOSER, "executable", side_effect=lambda env, name: "/usr/bin/zenity" if name == "zenity" else None),
            patch.object(CHOOSER.subprocess, "run") as run,
        ):
            run.return_value.returncode = 0
            run.return_value.stdout = directory + "\n"
            self.assertEqual(CHOOSER.backend(), "Zenity")
            self.assertEqual(CHOOSER.choose("Choose output", folder=True), Path(directory).resolve())
        self.assertIn("--directory", run.call_args.args[0])

    def test_headless_ubuntu_has_no_graphical_backend(self):
        with (
            patch.object(CHOOSER.platform, "system", return_value="Linux"),
            patch.dict(CHOOSER.os.environ, {}, clear=True),
        ):
            self.assertIsNone(CHOOSER.backend())


if __name__ == "__main__":
    unittest.main()
