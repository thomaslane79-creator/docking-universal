"""Status-only installer diagnostics preserve causes, not environment dumps."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('native_bootstrap_validation', ROOT / 'validation/native_windows_bootstrap.py')
MODULE = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(MODULE)


class InstallationDiagnosticTests(unittest.TestCase):
    def test_short_diagnostic_is_unchanged(self):
        self.assertEqual(MODULE.installation_diagnostic('known dependency error'), 'known dependency error')

    def test_root_error_at_end_is_not_lost(self):
        text = 'installer stage\n' + ('package metadata\n' * 1000) + 'RootDependencyError: exact cause\n'
        result = MODULE.installation_diagnostic(text)
        self.assertTrue(result.startswith('installer stage\n'))
        self.assertTrue(result.endswith('RootDependencyError: exact cause\n'))
        self.assertLessEqual(len(result), 8000)

    def test_environment_dump_is_removed_before_clipping(self):
        text = 'root error\n  environment variables:\nPRIVATE_FIXTURE_KEY=do-not-retain\n'
        self.assertEqual(MODULE.installation_diagnostic(text), 'root error\n')

    def test_large_diagnostic_cannot_retain_environment_tail(self):
        text = 'context\n' + ('metadata\n' * 2000) + 'RootError: cause\n  environment variables:\nSECRET_FIXTURE=not-uploaded'
        result = MODULE.installation_diagnostic(text)
        self.assertTrue(result.endswith('RootError: cause\n'))
        self.assertNotIn('SECRET_FIXTURE', result)


if __name__ == '__main__':
    unittest.main()
