import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[1] / 'validation/vina_execution_benchmark.py'
spec = importlib.util.spec_from_file_location('vina_execution_benchmark_test', SCRIPT)
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)


class VinaExecutionBenchmarkTests(unittest.TestCase):
    def test_analysis_recovery_never_redocks_completed_arms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / 'baseline'; baseline.mkdir()
            (baseline / 'original.txt').write_text('unchanged')
            bundle = root / 'original.duprotocol'; bundle.write_bytes(b'original fixture')
            config = {'baseline': str(baseline), 'protocol_bundle': str(bundle),
                      'protocol_sha256': benchmark.digest(bundle), 'parameters': {'seeds': [101]},
                      'compounds': [{'id': 'ligand', 'prepared': ['retained.pdbqt'], 'prepared_sha256': {}}]}
            benchmark.save(root / 'config.json', config)
            summary = {'status': 'failed', 'error': 'runtime fixture', 'arms': {}}
            for name in ('shared_grid_auto', 'shared_grid_cpu8'):
                arm = root / name; arm.mkdir()
                output = arm / 'pose.pdbqt'; output.write_text('MODEL\nENDMDL\n')
                benchmark.save(arm / 'execution.json', {'status': 'completed', 'jobs': [{'output': str(output)}]})
                summary['arms'][name] = {'docking_worker_seconds': 5}
            benchmark.save(root / 'summary.json', summary)
            with patch.object(benchmark.subprocess, 'run') as run, \
                    patch.object(benchmark, 'postprocess') as postprocess, \
                    patch.object(benchmark, 'compare_outputs'):
                benchmark.resume_analysis(root)
            run.assert_not_called()
            self.assertEqual(postprocess.call_count, 2)
            final = json.loads((root / 'summary.json').read_text())
            self.assertEqual(final['status'], 'completed')
            self.assertEqual(final['recovered_errors'], ['runtime fixture'])
            self.assertEqual((baseline / 'original.txt').read_text(), 'unchanged')

    def test_all_thirty_searches_keep_budget_and_reuse_maps_per_seed(self):
        instances, searches = [], []
        class FakeVina:
            def __init__(self, **options):
                self.options = options
                self.ligand = None
                instances.append(self)
            def set_receptor(self, path): self.receptor = path
            def compute_vina_maps(self, center, box_size, spacing):
                self.maps = (center, box_size, spacing)
                self.assert_maps_before_ligand = self.ligand is None
            def set_ligand_from_file(self, path): self.ligand = path
            def dock(self, **options): searches.append((self.options, self.ligand, options))
            def write_poses(self, path, **options): Path(path).write_text('MODEL 1\nENDMDL\n')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = {'receptor': 'retained.pdbqt', 'geometry': {'center_' + a: 0 for a in 'xyz'},
                      'parameters': {'seeds': [101, 102, 103, 104, 105], 'exhaustiveness': 16,
                                     'num_modes': 15, 'energy_range_kcal_per_mol': 8},
                      'compounds': [{'id': str(i), 'prepared': [f'{i}_conformer_{j}.pdbqt' for j in range(3)]}
                                    for i in range(2)]}
            config['geometry'].update({'size_' + a: 26 for a in 'xyz'})
            path = root / 'config.json'; path.write_text(json.dumps(config))
            with patch.dict('sys.modules', {'vina': SimpleNamespace(Vina=FakeVina, __version__='test-double')}):
                benchmark.worker(path, root, 8)
            self.assertEqual(len(instances), 5)
            self.assertEqual(len(searches), 30)
            self.assertTrue(all(v.assert_maps_before_ligand for v in instances))
            for options, ligand, search in searches:
                self.assertFalse(options['no_refine'])
                self.assertEqual(options['cpu'], 8)
                self.assertEqual(search, {'exhaustiveness': 16, 'n_poses': 15, 'min_rmsd': 1.0})
            record = json.loads((root / 'execution.json').read_text())
            self.assertEqual(record['status'], 'completed')
            self.assertEqual(len(record['map_builds']), 5)
            self.assertEqual(len(record['jobs']), 30)
