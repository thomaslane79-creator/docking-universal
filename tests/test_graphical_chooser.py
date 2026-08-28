#!/usr/bin/env python3

import importlib.util
import sys
import tempfile
import types
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
    def test_macos_finder_selects_file(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / "selected.pdb"
            selected.write_text("ATOM\n")
            with (
                patch.object(CHOOSER.platform, "system", return_value="Darwin"),
                patch.object(CHOOSER, "executable", return_value="/usr/bin/osascript"),
                patch.object(CHOOSER.subprocess, "run") as run,
            ):
                run.return_value.returncode = 0
                run.return_value.stdout = str(selected) + "\n"
                self.assertEqual(CHOOSER.backend(), "Finder")
                self.assertEqual(CHOOSER.choose("Choose structure"), selected.resolve())

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

    def test_cancelled_zenity_selection_stops_cleanly(self):
        with (
            patch.object(CHOOSER.platform, "system", return_value="Linux"),
            patch.dict(CHOOSER.os.environ, {"DISPLAY": ":1"}),
            patch.object(CHOOSER, "executable", side_effect=lambda env, name: "/usr/bin/zenity" if name == "zenity" else None),
            patch.object(CHOOSER.subprocess, "run") as run,
        ):
            run.return_value.returncode = 1
            run.return_value.stdout = ""
            with self.assertRaisesRegex(SystemExit, "cancelled"):
                CHOOSER.choose("Choose structure")

    def test_ubuntu_uses_tk_when_zenity_is_unavailable(self):
        with tempfile.TemporaryDirectory() as directory:
            selected = Path(directory) / "selected.sdf"
            selected.write_text("ligand\n$$$$\n")

            class Root:
                def withdraw(self):
                    return None

                def attributes(self, *_args):
                    return None

                def destroy(self):
                    return None

            tkinter = types.ModuleType("tkinter")
            tkinter.Tk = Root
            tkinter.TclError = RuntimeError
            filedialog = types.ModuleType("tkinter.filedialog")
            filedialog.askopenfilename = lambda **kwargs: str(selected)
            filedialog.askdirectory = lambda **kwargs: directory
            tkinter.filedialog = filedialog
            with (
                patch.object(CHOOSER.platform, "system", return_value="Linux"),
                patch.dict(CHOOSER.os.environ, {"DISPLAY": ":1"}),
                patch.object(CHOOSER, "executable", return_value=None),
                patch.dict(sys.modules, {"tkinter": tkinter, "tkinter.filedialog": filedialog}),
            ):
                self.assertEqual(CHOOSER.backend(), "Tk")
                self.assertEqual(CHOOSER.choose("Choose ligand", sdf=True), selected.resolve())


if __name__ == "__main__":
    unittest.main()
