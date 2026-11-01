import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('prepared_worker', Path(__file__).resolve().parents[1] / 'validation/prepared_engine_worker.py')
# The worker imports an existing validation helper rather than installed code.
import sys
sys.path.insert(0, str(Path(SPEC.origin).parent))
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


class PreparedCommandTests(unittest.TestCase):
    def test_preserves_search_budget_and_pins(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            command = ['/engine/vina', '--receptor', str(root/'r'), '--ligand', str(root/'l'),
                       '--config', str(root/'b'), '--out', str(root/'old'), '--seed', '41001',
                       '--cpu', '1', '--exhaustiveness', '8', '--num_modes', '9', '--energy_range', '3']
            source = root/'command.json'; source.write_text(json.dumps(command))
            manifest = {'executable':'/engine/qvinaw', 'inputs':{k:{'path':str(v)} for k,v in
                        [('command-41001', source), ('receptor-pdbqt', root/'r'), ('ligand-pdbqt', root/'l'),
                         ('box', root/'b'), ('baseline-41001', root/'old')]}}
            result = worker.search_command(manifest, 41001, root/'new')
            self.assertEqual(result[0], '/engine/qvinaw')
            options = dict(zip(result[1::2], result[2::2]))
            self.assertEqual(options['--exhaustiveness'], '8')
            self.assertEqual(options['--num_modes'], '9')
            self.assertEqual(options['--energy_range'], '3')
            self.assertEqual(options['--cpu'], '8')
            manifest['inputs']['box']['path'] = str(root/'different')
            with self.assertRaisesRegex(ValueError, 'pinned input'):
                worker.search_command(manifest, 41001, root/'new')

    def test_changed_input_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); item = root/'input'; item.write_text('original')
            manifest = {'engine':'qvinaw','baseline_engine':'vina','seeds':[41001,41002,41003],
                        'inputs':{'source':{'path':str(item),'sha256':worker.digest(item)}}}
            path = root/'manifest.json'; path.write_text(json.dumps(manifest))
            self.assertEqual(worker.load_manifest(path)['engine'], 'qvinaw')
            item.write_text('changed')
            with self.assertRaisesRegex(ValueError, 'input changed'):
                worker.load_manifest(path)
