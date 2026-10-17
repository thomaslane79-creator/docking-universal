"""Worker phase integration with mocked scientific commands, never real docking."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from rdkit import Chem
from docking_universal.screening_progress import read_screening_progress


class ScreeningProgressTests(unittest.TestCase):
    def test_real_compound_orchestration_publishes_custom_ph_and_each_phase(self):
        script = Path(__file__).resolve().parents[1] / 'libexec/docking-universal-screen.py'
        spec = importlib.util.spec_from_file_location('screen_progress_worker', script)
        worker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(worker)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ligand, receptor = root / 'amine.mol', root / 'receptor.pdbqt'
            Chem.MolToMolFile(Chem.MolFromSmiles('CCN'), str(ligand))
            receptor.write_text('RECEPTOR\n')
            boxes = [root / 'box1.conf', root / 'box2.conf']
            for box in boxes:
                box.write_text('center_x = 0\n')
            output = root / 'compound'
            phases, commands = [], []

            def fake_run(command):
                command = list(map(str, command))
                commands.append(command)
                phases.append(read_screening_progress(output))
                if 'collect' in command:
                    scores = Path(command[command.index('--out') + 1])
                    scores.parent.mkdir(parents=True, exist_ok=True)
                    scores.write_text('affinity\n-7.0\n')
                elif 'cluster-poses' in command:
                    cluster = Path(command[command.index('--out') + 1]) / 'cluster_001'
                    cluster.mkdir(parents=True)

            argv = [str(script), '--exploratory', '--ligand', str(ligand),
                    '--receptor', str(receptor), '--boxes', *map(str, boxes),
                    '--out', str(output), '--ph', '6.5', '--seeds', '2',
                    '--conformers', '1', '--non-interactive']
            with patch.object(sys, 'argv', argv), patch.object(worker, 'run', side_effect=fake_run):
                worker.main()
            phases_seen = {record['phase'] for record in phases}
            self.assertTrue({'depiction', 'ligands', 'ligand_atoms', 'docking',
                             'clustering', 'visuals', 'interactions'} <= phases_seen)
            self.assertIn('pH 6.5', next(r['message'] for r in phases if r['phase'] == 'ligands'))
            self.assertTrue(any('site 2/2, repeat 2/2' in r['message'] for r in phases))
            self.assertEqual(len([c for c in commands if 'dock' in c]), 4)
            self.assertEqual(read_screening_progress(output)['phase'], 'finished')
            ensemble = next(c for c in commands if any('ensemble.py' in arg for arg in c))
            self.assertEqual(ensemble[ensemble.index('--ph') + 1], '6.5')
            self.assertEqual(Chem.MolToSmiles(Chem.MolFromMolFile(str(ligand))), 'CCN')


if __name__ == '__main__':
    unittest.main()
