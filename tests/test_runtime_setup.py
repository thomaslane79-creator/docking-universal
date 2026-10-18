"""Packaging and discovery contracts; no native viewer or docking searches."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal import ad4_gpu, runtime_setup

ROOT = Path(__file__).resolve().parents[1]


class RuntimeSetupTests(unittest.TestCase):
    def test_distributed_assets_match_the_manifest(self):
        assets = ROOT / 'dependencies/runtime/macos-arm64'
        manifest = runtime_setup.verified_manifest(assets)
        self.assertEqual(manifest['gpu']['minimum_macos'], '26.2')
        self.assertIn('autodock-gpu-source.tar.gz', manifest['files'])
        self.assertIn('LICENSE-PyMOL', manifest['files'])

    def test_corrupted_assets_are_rejected_before_installing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'item').write_bytes(b'changed')
            (root / 'manifest.json').write_text(json.dumps({
                'schema': 'docking-universal-mac-runtimes-v1',
                'files': {'item': {'sha256': 'wrong', 'bytes': 7}}}))
            with self.assertRaisesRegex(ValueError, 'checksum'):
                runtime_setup.verified_manifest(root)

    def test_unsupported_platform_and_os_are_rejected(self):
        for system, machine, version in (('Linux', 'aarch64', ''), ('Darwin', 'x86_64', '27.0'),
                                          ('Darwin', 'arm64', '26.1')):
            with patch.object(runtime_setup.platform, 'system', return_value=system), \
                 patch.object(runtime_setup.platform, 'machine', return_value=machine), \
                 patch.object(runtime_setup.platform, 'mac_ver', return_value=(version, (), '')):
                with self.assertRaises(ValueError):
                    runtime_setup.require_platform('26.2')

    def test_prefix_config_precedes_legacy_home_and_override_never_falls_back(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            engine = root / 'engine'; engine.write_bytes(b'engine'); engine.chmod(0o755)
            grid = root / 'grid'; grid.write_bytes(b'grid'); grid.chmod(0o755)
            config = root / 'share/docking-universal/adgpu/runtime.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'schema': 'docking-universal-adgpu-runtime-v1',
                'integration_accepted': True, 'executable': str(engine),
                'autogrid_executable': str(grid), 'autogrid_sha256': ad4_gpu.digest(grid)}))
            with patch.object(ad4_gpu.sys, 'prefix', str(root)), \
                 patch.object(ad4_gpu, 'PINNED_ENGINE_SHA256', ad4_gpu.digest(engine)), \
                 patch.object(ad4_gpu.platform, 'system', return_value='Darwin'), \
                 patch.object(ad4_gpu.platform, 'machine', return_value='arm64'), \
                 patch.object(ad4_gpu.platform, 'mac_ver', return_value=('27.0', (), '')):
                self.assertEqual(ad4_gpu.runtime_descriptor({})['executable'], str(engine.resolve()))
                with self.assertRaisesRegex(ValueError, 'not configured'):
                    ad4_gpu.runtime_descriptor({'DOCKING_UNIVERSAL_ADGPU_CONFIG': str(root / 'absent')})
                grid.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'AutoGrid'):
                    ad4_gpu.runtime_descriptor({})
                grid.write_bytes(b'grid')
                engine.write_bytes(b'tampered')
                with self.assertRaisesRegex(ValueError, 'tested patched'):
                    ad4_gpu.runtime_descriptor({})

    def test_pinned_binary_does_not_run_on_older_mac(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'config.json'
            config.write_text(json.dumps({'schema': 'docking-universal-adgpu-runtime-v1',
                'integration_accepted': True, 'executable': str(root / 'engine')}))
            with patch.object(ad4_gpu.platform, 'system', return_value='Darwin'), \
                 patch.object(ad4_gpu.platform, 'machine', return_value='arm64'), \
                 patch.object(ad4_gpu.platform, 'mac_ver', return_value=('26.1', (), '')):
                with self.assertRaisesRegex(ValueError, '26.2'):
                    ad4_gpu.runtime_descriptor({'DOCKING_UNIVERSAL_ADGPU_CONFIG': str(config)})

    def test_embedded_install_preserves_intentional_custom_registration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            scientific, gui = root / 'scientific', root / 'gui'
            for prefix in (scientific, gui):
                (prefix / 'conda-meta').mkdir(parents=True)
                (prefix / 'bin').mkdir()
                (prefix / 'bin/python').touch()
            registration = scientific / 'share/docking-universal/desktop-python'
            registration.parent.mkdir(parents=True)
            registration.write_text('/intentional/custom/python\n')
            manifest = {'pymol': {'minimum_macos': '15.0', 'python': '3.12', 'wheel': 'pinned.whl'}}
            assets = root / 'assets'; assets.mkdir()
            (assets / 'manifest.json').write_text('{}')
            imported = json.dumps({'pymol_extension': str(gui / 'lib/pymol/_cmd.so'), 'qt': '6'})
            with patch.object(runtime_setup, 'verified_manifest', return_value=manifest), \
                 patch.object(runtime_setup, 'require_platform'), \
                 patch.object(runtime_setup.subprocess, 'run'), \
                 patch.object(runtime_setup.subprocess, 'check_output', side_effect=['3.12\n', imported]):
                receipt = runtime_setup.install(assets, scientific, gui)
            self.assertEqual(registration.read_text(), '/intentional/custom/python\n')
            self.assertFalse(receipt['gpu_installed_by_this_run'])
            self.assertFalse((registration.parent / 'adgpu/runtime.json').exists())

    def test_import_failure_does_not_register_a_broken_viewer(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            scientific, gui = root / 'scientific', root / 'gui'
            for prefix in (scientific, gui):
                (prefix / 'conda-meta').mkdir(parents=True)
                (prefix / 'bin').mkdir()
                (prefix / 'bin/python').touch()
            manifest = {'pymol': {'minimum_macos': '15.0', 'python': '3.12', 'wheel': 'pinned.whl'}}
            with patch.object(runtime_setup, 'verified_manifest', return_value=manifest), \
                 patch.object(runtime_setup, 'require_platform'), \
                 patch.object(runtime_setup.subprocess, 'run'), \
                 patch.object(runtime_setup.subprocess, 'check_output', side_effect=[
                     '3.12\n', '{"pymol_extension":"/old/prototype/_cmd.so"}']):
                with self.assertRaisesRegex(ValueError, 'escaped'):
                    runtime_setup.install(root, scientific, gui)
            self.assertFalse((scientific / 'share/docking-universal/desktop-python').exists())


if __name__ == '__main__':
    unittest.main()
