import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from docking_universal import vina_batch as batch
from docking_universal_dock import DockOptions, EngineInvocation, DockRuntimeError, run_docking, _run_api_batch, resolve_engine


class VinaBatchTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.receptor, self.config = self.root / 'receptor.pdbqt', self.root / 'box.conf'
        self.receptor.write_text('retained receptor')
        self.config.write_text(''.join(f'{prefix}_{axis} = {0 if prefix == "center" else 26}\n'
                                     for prefix in ('center', 'size') for axis in 'xyz'))
        self.inputs = self.root / 'inputs'; self.inputs.mkdir()
        for name in ('a', 'b', 'c'):
            (self.inputs / (name + '.pdbqt')).write_text('retained ' + name)
        self.output = self.root / 'output'; self.output.mkdir()
        self.options = DockOptions(receptor=self.receptor, config=self.config, ligand_dir=self.inputs,
                                   output_dir=self.output, seed='41001', cpu='8')
        self.runtime = dict(api_version='1.2.7', python='python', module='vina.py', executable='vina')

    def request(self, skip=False):
        jobs = [dict(ligand=str(p), sha256=batch.digest(p), output=str(self.output / (p.stem + '_vina.pdbqt')),
                     log=str(self.output / (p.stem + '_vina.log'))) for p in sorted(self.inputs.glob('*.pdbqt'))]
        value = dict(request_id='11111111-1111-4111-8111-111111111111', parameters=batch.parameters(self.options), runtime=self.runtime,
                     receptor=str(self.receptor), receptor_sha256=batch.digest(self.receptor),
                     config=str(self.config), config_sha256=batch.digest(self.config),
                     output=str(self.output), skip_existing=skip, jobs=jobs)
        path = self.output / 'request.json'; batch.save(path, value)
        return path

    def fake_engine(self, fail=None, bad_output=False):
        instances, searches = [], []
        class Engine:
            def __init__(self, **options):
                self.options = options; self.ligand = None
                instances.append(self)
            def set_receptor(self, path): self.receptor = path
            def compute_vina_maps(self, center, size, spacing):
                assert self.ligand is None
                self.maps = (center, size, spacing)
            def set_ligand_from_file(self, path):
                self.ligand = path
                if Path(path).stem == fail:
                    raise ValueError('bad ligand fixture')
            def dock(self, **parameters): searches.append((self.ligand, parameters))
            def write_poses(self, path, **parameters):
                Path(path).write_text('incomplete' if bad_output else 'MODEL 1\nREMARK VINA RESULT: -5 0 0\nENDMDL\n')
        return Engine, instances, searches

    def execute(self, request, **kwargs):
        engine, instances, searches = self.fake_engine(**kwargs)
        with patch.dict('sys.modules', {'vina': SimpleNamespace(__version__='1.2.7', Vina=engine)}), \
                patch.object(batch, 'probe', return_value=self.runtime), patch('sys.stdout', io.StringIO()), \
                patch('sys.stderr', io.StringIO()):
            code = batch.run_worker(request)
        return code, instances, searches, json.loads((self.output / 'batch_execution.json').read_text())

    def test_maps_once_before_any_ligand_and_exact_search_settings(self):
        code, instances, searches, record = self.execute(self.request())
        self.assertEqual(code, 0)
        self.assertEqual(len(instances), 1)
        self.assertEqual(record['map_builds'], 1)
        self.assertEqual(instances[0].options, dict(sf_name='vina', cpu=8, seed=41001, no_refine=False, verbosity=0))
        self.assertEqual(instances[0].maps, ([0, 0, 0], [26, 26, 26], .375))
        self.assertEqual(len(searches), 3)
        self.assertTrue(all(p == dict(exhaustiveness=8, n_poses=9, min_rmsd=1.0, max_evals=0) for _, p in searches))
        self.assertEqual([r['status'] for r in record['jobs']], ['completed'] * 3)
        self.assertEqual(record['request_id'], '11111111-1111-4111-8111-111111111111')
        self.assertTrue((self.output / 'batch_records' / (record['request_id'] + '.json')).is_file())

    def test_one_bad_ligand_is_not_retried_and_next_gets_clean_engine(self):
        code, instances, searches, record = self.execute(self.request(), fail='b')
        self.assertEqual(code, 1)
        self.assertEqual([r['status'] for r in record['jobs']], ['completed', 'failed', 'completed'])
        self.assertEqual(len(instances), 2)
        self.assertEqual(len(searches), 2)
        self.assertFalse((self.output / 'b_vina.pdbqt').exists())
        self.assertIn('bad ligand fixture', (self.output / 'b_vina.log').read_text())

    def test_skip_existing_is_byte_preserving_and_all_skipped_builds_no_maps(self):
        for name in ('a', 'b', 'c'):
            (self.output / (name + '_vina.pdbqt')).write_text('keep me')
        code, instances, searches, record = self.execute(self.request(skip=True))
        self.assertEqual((code, len(instances), len(searches), record['map_builds']), (0, 0, 0, 0))
        self.assertTrue(all(r['status'] == 'skipped' for r in record['jobs']))
        self.assertTrue(all(p.read_text() == 'keep me' for p in self.output.glob('*_vina.pdbqt')))

    def test_later_skip_keeps_the_original_per_request_record(self):
        self.execute(self.request())
        original = self.output / 'batch_records/11111111-1111-4111-8111-111111111111.json'
        before = original.read_bytes()
        request = self.request(skip=True)
        value = json.loads(request.read_text())
        value['request_id'] = '22222222-2222-4222-8222-222222222222'
        batch.save(request, value)
        code, _, _, record = self.execute(request)
        self.assertEqual(code, 0)
        self.assertEqual(record['map_builds'], 0)
        self.assertEqual(original.read_bytes(), before)
        self.assertEqual(len(list((self.output / 'batch_records').glob('*.json'))), 2)

    def test_incomplete_output_is_not_promoted(self):
        code, _, _, record = self.execute(self.request(), bad_output=True)
        self.assertEqual(code, 1)
        self.assertEqual(len(list(self.output.glob('*.pdbqt'))), 0)
        self.assertEqual(record['status'], 'completed_with_failures')

    def test_input_change_and_runtime_change_are_fatal_before_search(self):
        for altered in ('input', 'runtime'):
            request = self.request()
            value = json.loads(request.read_text())
            if altered == 'input':
                value['receptor_sha256'] = 'changed'
            else:
                value['runtime'] = dict(self.runtime, api_version='wrong')
            batch.save(request, value)
            with self.assertRaises(RuntimeError):
                self.execute(request)
            self.assertEqual(json.loads((self.output / 'batch_execution.json').read_text())['status'], 'failed')

    def test_unsupported_configs_and_unseeded_searches_fail_closed(self):
        self.assertEqual(batch.parameters(self.options)['num_modes'], 9)
        self.options.seed = None
        with self.assertRaises(batch.UnsupportedBatch): batch.parameters(self.options)
        self.options.seed = '41001'
        for extra in ('flex = receptor.pdbqt\n', 'scoring = ad4\n', 'min_rmsd = 2\n',
                      'center_x = 5\n', 'weight_gauss1 = -1\n'):
            original = self.config.read_text()
            self.config.write_text(original + extra)
            with self.assertRaises(batch.UnsupportedBatch): batch.parameters(self.options)
            self.config.write_text(original)
        self.options.exhaustiveness, self.options.num_modes, self.options.energy_range = '16', '15', '8'
        self.assertEqual(batch.parameters(self.options)['exhaustiveness'], 16)

    def test_runtime_gates_version_and_installation_identity(self):
        invocation = EngineInvocation((str(self.root / 'vina'),), 'fixture')
        with self.assertRaises(batch.UnsupportedBatch):
            batch.runtime(invocation, 'AutoDock Vina v1.2.6', {}, self.root / 'worker.py')
        (self.root / 'python').write_text('fixture')
        result = SimpleNamespace(returncode=0, stdout=json.dumps(self.runtime))
        with patch.object(batch.subprocess, 'run', return_value=result):
            with self.assertRaises(batch.UnsupportedBatch):
                batch.runtime(invocation, 'AutoDock Vina v1.2.7', {}, self.root / 'worker.py')

    def test_managed_conda_binary_is_verified_before_bypassing_wrapper(self):
        prefix = self.root / 'managed'
        binary = prefix / ('Scripts/vina.exe' if os.name == 'nt' else 'bin/vina')
        binary.parent.mkdir(parents=True)
        binary.write_text('fixture'); binary.chmod(0o755)
        def which(name, path=None): return '/conda' if name == 'conda' else None
        with patch('docking_universal_dock.shutil.which', side_effect=which), \
                patch('docking_universal_dock.subprocess.run', side_effect=[
                    SimpleNamespace(returncode=0, stdout=json.dumps(str(prefix))),
                    SimpleNamespace(returncode=0, stdout='AutoDock Vina v1.2.7\n')]):
            invocation = resolve_engine(DockOptions(), {})
        self.assertEqual(invocation.command, (str(binary.resolve()),))
        self.assertIn('verified direct executable', invocation.source)
        with patch('docking_universal_dock.shutil.which', side_effect=which), \
                patch('docking_universal_dock.subprocess.run', side_effect=[
                    SimpleNamespace(returncode=0, stdout=json.dumps(str(prefix))),
                    SimpleNamespace(returncode=1, stdout='activation required'),
                    SimpleNamespace(returncode=0)]):
            invocation = resolve_engine(DockOptions(), {})
        self.assertEqual(invocation.command[-1], 'vina')
        self.assertIn('run', invocation.command)

    def test_api_failure_never_falls_back_to_cli(self):
        self.options.vina_backend = 'api'
        with patch('docking_universal_dock._engine_version', return_value='AutoDock Vina v1.2.7'), \
                patch.object(batch, 'runtime', return_value=(('python',), self.runtime)), \
                patch('docking_universal_dock._run_api_batch', side_effect=DockRuntimeError('fixture failure')), \
                patch('docking_universal_dock.subprocess.run') as cli:
            with self.assertRaises(DockRuntimeError):
                run_docking(self.options, EngineInvocation(('vina',), 'fixture'), {}, stdout=io.StringIO())
        cli.assert_not_called()

    def test_automatic_multi_input_selects_the_verified_batch_backend(self):
        from docking_universal_dock import DockBatchResult
        with patch('docking_universal_dock._engine_version', return_value='AutoDock Vina v1.2.7'), \
                patch.object(batch, 'runtime', return_value=(('python',), self.runtime)) as runtime, \
                patch('docking_universal_dock._run_api_batch', return_value=DockBatchResult(self.output, 3, 0, 0)) as worker:
            result = run_docking(self.options, EngineInvocation(('vina',), 'fixture'), {}, stdout=io.StringIO())
        runtime.assert_called_once()
        worker.assert_called_once()
        self.assertEqual(result.successful, 3)
        self.assertIn('execution_backend\tvina_python_batch', (self.output / 'run_manifest.tsv').read_text())

    def test_automatic_single_input_avoids_api_setup(self):
        (self.inputs / 'b.pdbqt').unlink()
        (self.inputs / 'c.pdbqt').unlink()
        def engine(command, **kwargs):
            Path(command[command.index('--out') + 1]).write_text('MODEL\nENDMDL\n')
            return SimpleNamespace(returncode=0)
        with patch('docking_universal_dock._engine_version', return_value='AutoDock Vina v1.2.7'), \
                patch.object(batch, 'runtime') as runtime, \
                patch('docking_universal_dock.subprocess.run', side_effect=engine):
            result = run_docking(self.options, EngineInvocation(('vina',), 'fixture'), {}, stdout=io.StringIO())
        runtime.assert_not_called()
        self.assertEqual(result.successful, 1)
        self.assertIn('fewer than two pending ligands', (self.output / 'run_manifest.tsv').read_text())

    def test_interruption_terminates_worker_without_a_retry(self):
        class Interrupted:
            def __iter__(self): raise KeyboardInterrupt
            def close(self): pass
        process = Mock(stdout=Interrupted())
        selected = (('python',), Path('worker.py'), batch.parameters(self.options), self.runtime)
        with patch('docking_universal_dock.subprocess.Popen', return_value=process):
            with self.assertRaises(KeyboardInterrupt):
                _run_api_batch(self.options, sorted(self.inputs.glob('*.pdbqt')), selected, {}, io.StringIO())
        process.terminate.assert_called_once()
        process.wait.assert_called_once_with(timeout=5)

    def test_stale_worker_record_cannot_be_accepted(self):
        process = Mock(stdout=io.StringIO(''), **{'wait.return_value': 0})
        batch.save(self.output / 'batch_execution.json', dict(request_id='old', status='completed', jobs=[]))
        selected = (('python',), Path('worker.py'), batch.parameters(self.options), self.runtime)
        with patch('docking_universal_dock.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(DockRuntimeError, 'no automatic CLI retry'):
                _run_api_batch(self.options, sorted(self.inputs.glob('*.pdbqt')), selected, {}, io.StringIO())
