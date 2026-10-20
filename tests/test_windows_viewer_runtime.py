import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from docking_universal.windows_viewer_runtime import PROFILE, owned_gui_python, viewer_record


class OwnedWindowsViewerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve() / 'Application Ω'
        self.app = self.root / 'app'; self.app.mkdir(parents=True)
        self.prefix = self.root / 'runtimes/gui'
        self.python = self.prefix / 'python.exe'; self.prefix.mkdir(parents=True)
        self.python.write_bytes(b'owned-python')
        self.dll = self.prefix / 'share/viewer/opengl32.dll'; self.dll.parent.mkdir(parents=True)
        self.dll.write_bytes(b'pinned-viewer')
        self.receipt = self.root / '.bootstrap/viewer.json'; self.receipt.parent.mkdir()
        self.record = {'status': 'installed', 'profile': PROFILE, 'python': str(self.python),
            'opengl_dll': 'share/viewer/opengl32.dll', 'files': {'share/viewer/opengl32.dll': self.sha(self.dll)}}
        self.config = {'gui_python': 'runtimes/gui/python.exe', 'viewer_profile': PROFILE,
            'viewer_receipt': '.bootstrap/viewer.json'}
        self.save()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def sha(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def save(self):
        self.receipt.write_text(json.dumps(self.record), encoding='utf-8')
        self.config['viewer_receipt_sha256'] = self.sha(self.receipt)

    def load(self, **kwargs):
        return viewer_record(self.app, self.config, executing_python=kwargs.get('python', self.python))

    def test_exact_owned_viewer_receipt_and_libraries_verify_without_loading_dll(self):
        record, dll = self.load()
        self.assertEqual(record['profile'], PROFILE)
        self.assertEqual(dll, self.dll)
        self.assertIsNone(viewer_record(self.app, {}, executing_python=self.python))

    def test_changed_binary_and_receipt_fail_without_fallback(self):
        self.dll.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'library changed'):
            self.load()
        self.receipt.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'receipt changed'):
            self.load()

    def test_foreign_python_or_prefix_cannot_be_used(self):
        with self.assertRaisesRegex(ValueError, 'exact installation-owned'):
            self.load(python=self.prefix / 'other-python.exe')
        self.config['gui_python'] = str(self.root / 'foreign/python.exe')
        with self.assertRaisesRegex(ValueError, 'escaped'):
            owned_gui_python(self.app, self.config)

    def test_receipt_and_file_paths_cannot_escape_owned_directories(self):
        original = self.config['viewer_receipt']
        self.config['viewer_receipt'] = '../outside.json'
        with self.assertRaisesRegex(ValueError, 'escaped'):
            self.load()
        self.config['viewer_receipt'] = original
        outside = self.root / 'outside.dll'; outside.write_bytes(b'outside')
        self.record['files']['../../outside.dll'] = self.sha(outside); self.save()
        with self.assertRaisesRegex(ValueError, 'escaped'):
            self.load()

    def test_uncovered_graphics_dll_and_unknown_profile_fail_closed(self):
        self.record['files'] = {}; self.save()
        with self.assertRaisesRegex(ValueError, 'not covered'):
            self.load()
        self.config['viewer_profile'] = 'unaccepted-system-graphics'
        with self.assertRaisesRegex(ValueError, 'no graphics fallback'):
            self.load()

    def test_manager_owned_gui_must_be_sibling_of_verified_owned_science(self):
        manager = self.root.parent / ('d' * 32); manager.mkdir()
        owner = {'schema': 'docking-universal-private-manager-v1', 'installation': str(self.root),
                 'install_id': manager.name, 'sha256': 'e' * 64}
        (manager / 'docking-universal-owner.json').write_text(json.dumps(owner), encoding='utf-8')
        gui = manager / 'runtimes/gui/python.exe'; gui.parent.mkdir(parents=True); gui.write_bytes(b'gui')
        self.config.update(gui_python=str(gui), scientific_python=str(manager / 'runtimes/scientific/python.exe'),
            scientific_manager={'prefix': str(manager), 'install_id': manager.name, 'asset': {'sha256': 'e' * 64}},
            package_manager_conda=str(manager / 'Scripts/conda.exe'))
        self.assertEqual(owned_gui_python(self.app, self.config), gui)
        owner['installation'] = str(self.root / 'another-install')
        (manager / 'docking-universal-owner.json').write_text(json.dumps(owner), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'another installation'):
            owned_gui_python(self.app, self.config)


if __name__ == '__main__':
    unittest.main()
