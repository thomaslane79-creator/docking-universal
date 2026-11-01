import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.windows_qvinaw import PROFILE, record, supported_engines, engine_environment


class OwnedQuickVinaTests(unittest.TestCase):
    def test_native_cpu_containment_defaults_to_one_and_preserves_explicit_one(self):
        from docking_universal_dock import DockOptions, resolve_cpu
        native = {'DOCKING_UNIVERSAL_QVINAW_RUNTIME': 'owned-runtime'}
        with patch('docking_universal_dock.os.name', 'nt'):
            options = DockOptions(engine='qvinaw')
            resolve_cpu(options, native)
            self.assertEqual((options.cpu, options.cpu_source), ('1', 'windows_qvinaw_serial_containment'))
            options = DockOptions(engine='qvinaw', cpu='1')
            resolve_cpu(options, native)
            self.assertEqual((options.cpu, options.cpu_source), ('1', 'command_line'))
            options = DockOptions(engine='qvinaw')
            resolve_cpu(options, dict(native, DOCKING_UNIVERSAL_CPU='1'))
            self.assertEqual((options.cpu, options.cpu_source), ('1', 'environment'))

    def test_native_cpu_containment_rejects_unsafe_explicit_choices_without_rewriting_them(self):
        from docking_universal_dock import DockOptions, DockUsageError, resolve_cpu
        native = {'DOCKING_UNIVERSAL_QVINAW_RUNTIME': 'owned-runtime'}
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'box.conf'
            config.write_text('cpu = 4 # retained explicit setting\n')
            with patch('docking_universal_dock.os.name', 'nt'):
                for options, environment in (
                    (DockOptions(engine='qvinaw', cpu='0'), native),
                    (DockOptions(engine='qvinaw', cpu='4'), native),
                    (DockOptions(engine='qvinaw'), dict(native, DOCKING_UNIVERSAL_CPU='4')),
                    (DockOptions(engine='qvinaw', config=config), native)):
                    original = vars(options).copy()
                    with self.assertRaisesRegex(DockUsageError, 'explicit CPU setting was not changed'):
                        resolve_cpu(options, environment)
                    self.assertEqual(vars(options), original)
            self.assertEqual(config.read_text(), 'cpu = 4 # retained explicit setting\n')

    def test_cpu_containment_is_limited_to_the_owned_native_windows_quickvina_profile(self):
        from docking_universal_dock import DockOptions, resolve_cpu
        native = {'DOCKING_UNIVERSAL_QVINAW_RUNTIME': 'owned-runtime'}
        for operating_system, engine, environment in (
            ('posix', 'qvinaw', native), ('nt', 'qvinaw', {}), ('nt', 'vina', native)):
            with patch('docking_universal_dock.os.name', operating_system):
                options = DockOptions(engine=engine, cpu='4')
                resolve_cpu(options, environment)
                self.assertEqual(options.cpu, '4')

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
