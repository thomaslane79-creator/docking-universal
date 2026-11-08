"""Portable local browser discovery; no browser execution or network."""
from pathlib import Path
import hashlib
import json
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

    def test_owned_browser_is_found_from_scientific_python_and_rejects_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp)
            browser = prefix / 'share/playwright-browsers/chromium-test/chrome'
            browser.parent.mkdir(parents=True); browser.write_bytes(b'owned browser')
            receipt = prefix / 'share/docking-universal/renderer-browser.json'
            receipt.parent.mkdir(parents=True)
            receipt.write_text(json.dumps({'schema': 'docking-universal-renderer-browser-v1',
                'executable': str(browser), 'executable_sha256': hashlib.sha256(browser.read_bytes()).hexdigest()}))
            values = {'DOCKING_UNIVERSAL_PYTHON': str(prefix / 'bin/python')}
            self.assertEqual(find_chromium(environment=values, which=lambda _: None, system='Linux'), browser.resolve())
            browser.write_bytes(b'changed')
            self.assertIsNone(find_chromium(environment=values, which=lambda _: None, system='Linux'))

    def test_owned_registration_cannot_point_outside_private_cache(self):
        from docking_universal.browser_runtime import register_private_chromium
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp, patch('docking_universal.browser_runtime.subprocess.check_output') as run:
            with self.assertRaises(ValueError):
                register_private_chromium(Path(tmp), Path(tmp) / 'outside/chrome', 'pinned')
            run.assert_not_called()

    def test_installer_keeps_an_existing_local_browser(self):
        from docking_universal.browser_runtime import install_private_chromium
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp); (prefix / 'conda-meta').mkdir()
            with patch('docking_universal.browser_runtime.find_chromium', return_value=prefix/'chrome'), \
                    patch('docking_universal.browser_runtime.subprocess.run') as install:
                result = install_private_chromium(prefix, prefix/'renderer')
                self.assertEqual(result['source'], 'existing_local')
                install.assert_not_called()


if __name__ == '__main__':
    unittest.main()
