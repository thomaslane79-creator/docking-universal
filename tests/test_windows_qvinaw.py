import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from docking_universal.windows_qvinaw import PROFILE, record, supported_engines, engine_environment


class OwnedQuickVinaTests(unittest.TestCase):
    def test_only_accepted_installation_enables_engine_not_an_inherited_test_flag(self):
        config = {'qvinaw_candidate_installed': True, 'qvinaw_supported': False}
        self.assertEqual(supported_engines(config, {}), ('vina',))
        self.assertEqual(supported_engines(config, {'DOCKING_UNIVERSAL_QVINAW_ACCEPTANCE': '1'}), ('vina',))
        self.assertEqual(supported_engines({'qvinaw_supported': True}, {}), ('vina',))
        config['qvinaw_supported'] = True
        self.assertEqual(supported_engines(config, {}), ('vina', 'qvinaw'))

    def test_owned_receipt_binary_and_prefix_must_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve(); app = root / 'app'; app.mkdir()
            executable = root / 'runtimes/qvinaw/Library/bin/qvinaw.exe'
            executable.parent.mkdir(parents=True); executable.write_bytes(b'pinned')
            receipt = root / 'receipt.json'
            entry = {'status': 'installed', 'profile': PROFILE, 'prefix': str(root / 'runtimes/qvinaw'),
                     'executable': str(executable), 'executable_sha256': hashlib.sha256(b'pinned').hexdigest()}
            receipt.write_text(json.dumps(entry), encoding='utf-8')
            config = {'qvinaw_candidate_installed': True, 'qvinaw_receipt': 'receipt.json',
                      'qvinaw_receipt_sha256': hashlib.sha256(receipt.read_bytes()).hexdigest()}
            self.assertEqual(record(app, config)['executable'], str(executable))
            executable.write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'identity changed'):
                record(app, config)
            receipt.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'receipt changed'):
                record(app, config)

    def test_engine_child_dll_order_does_not_mutate_scientific_environment(self):
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp).resolve()
            original = {'PATH': 'scientific-path', 'DOCKING_UNIVERSAL_QVINAW_RUNTIME': str(prefix)}
            selected = engine_environment(original, [str(prefix / 'Library/bin/qvinaw.exe')], windows=True)
            self.assertEqual(original['PATH'], 'scientific-path')
            self.assertTrue(selected['PATH'].endswith('scientific-path'))
            self.assertIs(engine_environment(original, ['qvinaw'], windows=False), original)
            with self.assertRaisesRegex(ValueError, 'escaped'):
                engine_environment(original, [str(prefix.parent / 'other/qvinaw.exe')], windows=True)


if __name__ == '__main__':
    unittest.main()
