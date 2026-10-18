"""Portable local browser discovery; no browser execution or network."""
from pathlib import Path
import tempfile
import unittest

from docking_universal.browser_runtime import find_chromium


class BrowserRuntimeTests(unittest.TestCase):
    def test_native_windows_edge_install_location_with_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'Program Files (x86)'
            executable = root / 'Microsoft/Edge/Application/msedge.exe'
            executable.parent.mkdir(parents=True); executable.touch()
            self.assertEqual(find_chromium(environment={'ProgramFiles(x86)': str(root)},
                which=lambda _: None, system='Windows'), executable.resolve())

    def test_native_windows_user_chrome_install_location(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / 'Google/Chrome/Application/chrome.exe'
            executable.parent.mkdir(parents=True); executable.touch()
            self.assertEqual(find_chromium(environment={'LOCALAPPDATA': tmp},
                which=lambda _: None, system='Windows'), executable.resolve())

    def test_invalid_explicit_path_does_not_silently_select_another_browser(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = Path(tmp) / 'other'; other.touch()
            self.assertIsNone(find_chromium(Path(tmp) / 'absent', environment={},
                which=lambda _: str(other), system='Linux'))

    def test_linux_path_browser_is_used_without_installing(self):
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / 'chromium'; executable.touch()
            self.assertEqual(find_chromium(environment={}, system='Linux',
                which=lambda name: str(executable) if name == 'chromium-browser' else None), executable.resolve())


if __name__ == '__main__':
    unittest.main()
