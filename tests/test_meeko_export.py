import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

from docking_universal.meeko_export import export_sdf


class NativeMeekoExportTests(unittest.TestCase):
    def test_native_transport_preserves_exact_input_output_and_executable(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); staging = root / 'owned-staging'
            source = root / 'input 日本語.pdbqt'; source.write_bytes(b'ORIGINAL COORDINATES\n')
            destination = root / 'output Ω.sdf'
            commands = []
            def runner(command, **options):
                commands.append(command)
                self.assertEqual(Path(command[1]).read_bytes(), source.read_bytes())
                self.assertTrue(str(Path(command[1])).isascii())
                Path(command[-1]).write_bytes(b'EXACT NATIVE SDF\n$$$$\n')
                return subprocess.CompletedProcess(command, 0)
            with patch.dict(os.environ, {'DOCKING_UNIVERSAL_NATIVE_STAGING_ROOT': str(staging)}):
                result = export_sdf('pinned-exporter.exe', source, destination, windows=True, runner=runner)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(commands[0][0], 'pinned-exporter.exe')
            self.assertEqual(commands[0][-2], '-s')
            self.assertEqual(destination.read_bytes(), b'EXACT NATIVE SDF\n$$$$\n')
            self.assertEqual(source.read_bytes(), b'ORIGINAL COORDINATES\n')
            self.assertEqual(list(staging.iterdir()), [])

    def test_zero_exit_without_new_output_never_reuses_old_sdf(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'input.pdbqt'; source.touch()
            output = root / 'old.sdf'; output.write_bytes(b'old-result')
            with patch.dict(os.environ, {'DOCKING_UNIVERSAL_NATIVE_STAGING_ROOT': str(root / 'stage')}):
                with self.assertRaisesRegex(RuntimeError, 'without a nonempty new SDF'):
                    export_sdf('native.exe', source, output, windows=True,
                               runner=lambda *a, **kw: subprocess.CompletedProcess(a, 0))
            self.assertEqual(output.read_bytes(), b'old-result')

    def test_failed_export_does_not_publish_partial_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'input.pdbqt'; source.touch(); output = root / 'out.sdf'
            def fail(command, **kw):
                Path(command[-1]).write_bytes(b'PARTIAL')
                return subprocess.CompletedProcess(command, 1)
            with patch.dict(os.environ, {'DOCKING_UNIVERSAL_NATIVE_STAGING_ROOT': str(root / 'stage')}):
                self.assertEqual(export_sdf('native.exe', source, output, windows=True, runner=fail).returncode, 1)
            self.assertFalse(output.exists())

    def test_non_ascii_staging_fails_before_engine_execution(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary); source = root / 'input.pdbqt'; source.touch(); run = Mock()
            with patch.dict(os.environ, {'DOCKING_UNIVERSAL_NATIVE_STAGING_ROOT': str(root / '日本語')}):
                with self.assertRaisesRegex(ValueError, 'ASCII staging'):
                    export_sdf('native.exe', source, root / 'out.sdf', windows=True, runner=run)
            run.assert_not_called()

    def test_unix_keeps_literal_file_arguments_and_no_staging(self):
        run = Mock(return_value=subprocess.CompletedProcess([], 0))
        export_sdf('./explicit exporter', 'original.pdbqt', 'original.sdf', windows=False, runner=run)
        run.assert_called_once_with(['./explicit exporter', 'original.pdbqt', '-s', 'original.sdf'], capture_output=True, text=True)


if __name__ == '__main__':
    unittest.main()
