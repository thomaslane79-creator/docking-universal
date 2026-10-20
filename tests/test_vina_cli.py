import io
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.vina_cli import needs_native_transport, run_native_vina


class NativeVinaPathTests(unittest.TestCase):
    def test_transport_is_native_only_and_decided_before_search(self):
        arguments = ['--receptor', 'Greek Ω/receptor.pdbqt', '--cpu', '1']
        self.assertFalse(needs_native_transport(arguments, windows=False))
        self.assertTrue(needs_native_transport(arguments, windows=True))
        self.assertFalse(needs_native_transport(['--receptor', 'ASCII folder/r.pdbqt'], windows=True))

    def test_exact_input_output_bytes_and_scientific_flags_survive_private_staging(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / 'inputs Ω'; original.mkdir()
            sources = {flag: original / name for flag, name in
                       (('--receptor', 'receptor.pdbqt'), ('--ligand', 'ligand Ω.pdbqt'), ('--config', 'box.conf'))}
            for index, path in enumerate(sources.values()):
                path.write_bytes(b'unchanged input\r\n' + bytes([index, 255]))
            output = original / 'pose Ω.pdbqt'
            arguments = [item for flag, path in sources.items() for item in (flag, str(path))]
            arguments += ['--out', str(output), '--seed', '41001', '--cpu', '1', '--energy_range', '8']
            before = {flag: path.read_bytes() for flag, path in sources.items()}
            visited = []
            def execute(command, **options):
                work = Path(options['cwd']); visited.append(work)
                self.assertTrue(all(str(value).isascii() for value in command))
                for flag in sources:
                    self.assertEqual((work / command[command.index(flag) + 1]).read_bytes(), before[flag])
                self.assertEqual(command[-6:], ['--seed', '41001', '--cpu', '1', '--energy_range', '8'])
                self.assertEqual(options['stdin'], subprocess.DEVNULL)
                (work / command[command.index('--out') + 1]).write_bytes(b'exact pose\r\n\xff')
                return subprocess.CompletedProcess(command, 0)
            with patch('docking_universal.vina_cli.subprocess.run', side_effect=execute) as run:
                result = run_native_vina(['pinned-vina.exe'], arguments,
                    environment={'PINNED': 'yes'}, log=io.BytesIO(), staging_root=root / 'stage')
            self.assertEqual(run.call_count, 1)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(output.read_bytes(), b'exact pose\r\n\xff')
            self.assertTrue(all(path.read_bytes() == before[flag] for flag, path in sources.items()))
            self.assertFalse(visited[0].exists())

    def test_non_ascii_staging_root_is_rejected_before_search(self):
        with tempfile.TemporaryDirectory() as temporary:
            arguments = [item for flag in ('--receptor', '--ligand', '--config', '--out')
                         for item in (flag, str(Path(temporary) / flag[2:]))]
            with patch('docking_universal.vina_cli.subprocess.run') as run:
                with self.assertRaisesRegex(ValueError, 'no search'):
                    run_native_vina(['vina.exe'], arguments, environment={}, log=io.BytesIO(),
                                    staging_root=Path(temporary) / 'Ω')
                run.assert_not_called()
