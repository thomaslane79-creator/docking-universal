"""No real docking: verify isolated workload, bounds, outputs and failure cleanup."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / 'validation/vina_concurrency_benchmark.py'
spec = importlib.util.spec_from_file_location('concurrency_pilot_test', SCRIPT)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class VinaConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.states = self.root / 'states'
        state = self.states / 'study/application_state.json'
        state.parent.mkdir(parents=True)
        state.write_text(json.dumps({'jobs': [{'status': 'waiting_for_decision'}]}))
        self.config = {'parameters': {'seeds': [101, 102, 103], 'exhaustiveness': 16,
            'num_modes': 15, 'energy_range_kcal_per_mol': 8}, 'compounds': [],
            'receptor': 'retained_receptor.pdbqt', 'box': 'retained_box.conf',
            'baseline': str(self.root / 'baseline')}
        for name in ('slow', 'fast'):
            folder = self.root / name
            folder.mkdir()
            inputs = [folder / f'conformer_{i}.pdbqt' for i in range(3)]
            for p in inputs:
                p.write_text('retained input')
            self.config['compounds'].append({'id': name, 'prepared': list(map(str, inputs))})
        self.tasks = pilot.build_tasks(self.config)

    def tearDown(self):
        self.temporary.cleanup()

    def test_same_four_batches_twelve_searches_and_explicit_settings(self):
        self.assertEqual(len(self.tasks), 4)
        self.assertEqual({t['seed'] for t in self.tasks}, {101, 102})
        self.assertEqual(sum(len(t['inputs']) for t in self.tasks), 12)
        for workers, cpu in pilot.LAYOUTS:
            self.assertEqual(workers * cpu, 8)
            cmd = pilot.command(self.config, self.tasks[0], self.root / 'out', cpu,
                                Path('/installed'), Path('/science/python'), Path('/engine/vina'))
            for flag, expected in (('--cpu', str(cpu)), ('--seed', '101'),
                    ('--exhaustiveness', '16'), ('--num-modes', '15'),
                    ('--energy-range', '8'), ('--vina-backend', 'api')):
                self.assertEqual(cmd[cmd.index(flag)+1], expected)
            self.assertNotIn('--skip-existing', cmd)

    def test_unexpected_input_and_active_gui_calculation_fail_closed(self):
        (self.root / 'slow/extra.pdbqt').write_text('unexpected')
        with self.assertRaisesRegex(ValueError, 'unexpected'):
            pilot.build_tasks(self.config)
        pilot.check_idle(self.states)
        (self.states / 'study/application_state.json').write_text(json.dumps({'jobs': [{'status': 'running'}]}))
        with self.assertRaisesRegex(RuntimeError, 'Another GUI calculation'):
            pilot.check_idle(self.states)

    def test_scheduler_bounds_and_every_task_runs_once(self):
        for workers, cpu in pilot.LAYOUTS:
            processes = []
            def spawn(*args, **kwargs):
                process = Mock(pid=100 + len(processes))
                process.poll.return_value = 0
                processes.append(process)
                self.assertLessEqual(len(processes), 4)
                self.assertTrue(kwargs['start_new_session'])
                return process
            fake_result = {'comparisons': [{'byte_identical': True}] * 3,
                           'execution_record': 'fixture', 'search_seconds': 1}
            with patch.object(pilot.subprocess, 'Popen', side_effect=spawn), \
                    patch.object(pilot, 'validate_batch', return_value=fake_result) as validate:
                row = pilot.run_arm(self.config, self.tasks, self.root / f'arm-{workers}',
                    workers, cpu, Path('/installed'), Path('/science/python'), Path('/engine/vina'), self.states)
            self.assertEqual(row['status'], 'completed')
            self.assertEqual(len(processes), 4)
            self.assertEqual(validate.call_count, 4)
            self.assertEqual(row['output_files'], 12)
            self.assertEqual(row['byte_identical_outputs'], 12)
            self.assertEqual({(b['compound'], b['seed']) for b in row['batches']},
                             {(t['compound'], t['seed']) for t in self.tasks})

    def test_failure_stops_other_workers_and_never_retries(self):
        bad, other = Mock(pid=10), Mock(pid=11)
        bad.poll.return_value = 1
        other.poll.return_value = None
        with patch.object(pilot.subprocess, 'Popen', side_effect=[bad, other]) as spawn, \
                patch.object(pilot, 'terminate') as stop:
            with self.assertRaisesRegex(RuntimeError, 'Docking batch failed'):
                pilot.run_arm(self.config, self.tasks, self.root / 'failure', 2, 4,
                    Path('/installed'), Path('/science/python'), Path('/engine/vina'), self.states)
        self.assertEqual(spawn.call_count, 2)
        self.assertEqual(stop.call_count, 2)
        record = json.loads((self.root / 'failure/execution.json').read_text())
        self.assertEqual(record['status'], 'failed')
        self.assertEqual(record['batches'][1]['status'], 'stopped_after_pilot_failure')

    def test_gui_guard_during_arm_stops_workers_without_touching_gui(self):
        process = Mock(pid=21)
        process.poll.return_value = None
        with patch.object(pilot.subprocess, 'Popen', return_value=process) as spawn, \
                patch.object(pilot, 'check_idle', side_effect=[None, RuntimeError('Another GUI calculation')]), \
                patch.object(pilot.time, 'sleep'), \
                patch.object(pilot.time, 'perf_counter', side_effect=range(0, 100, 3)), \
                patch.object(pilot, 'terminate') as stop:
            with self.assertRaisesRegex(RuntimeError, 'Another GUI calculation'):
                pilot.run_arm(self.config, self.tasks, self.root / 'guarded', 1, 8,
                    Path('/installed'), Path('/science/python'), Path('/engine/vina'), self.states)
        self.assertEqual(spawn.call_count, 1)
        stop.assert_called_once_with(process)

    def test_output_validation_compares_complete_bytes_not_just_best_energy(self):
        task = self.tasks[0]
        folder = self.root / 'output'
        folder.mkdir()
        jobs = []
        for ligand in task['inputs']:
            name = Path(ligand).stem + '_vina.pdbqt'
            out = folder / name
            reference = Path(self.config['baseline']) / 'compounds' / task['compound'] / 'seed_101/docking' / name
            reference.parent.mkdir(parents=True, exist_ok=True)
            text = 'MODEL 1\nREMARK VINA RESULT: -5.0 0 0\nENDMDL\n'
            out.write_text(text)
            reference.write_text(text)
            jobs.append({'ligand': ligand, 'output': str(out), 'status': 'completed', 'search_seconds': 2})
        record = {'status': 'completed', 'map_builds': 1, 'parameters': {'cpu': 8, 'seed': 101},
                  'no_refine': False, 'jobs': jobs}
        (folder / 'batch_execution.json').write_text(json.dumps(record))
        result = pilot.validate_batch(self.config, task, folder, 8)
        self.assertTrue(all(c['byte_identical'] for c in result['comparisons']))
        Path(jobs[0]['output']).write_text(text + 'changed coordinate inventory\n')
        result = pilot.validate_batch(self.config, task, folder, 8)
        self.assertFalse(result['comparisons'][0]['byte_identical'])
        Path(jobs[0]['output']).write_text('MODEL 1\n')
        with self.assertRaisesRegex(ValueError, 'Incomplete scored output'):
            pilot.validate_batch(self.config, task, folder, 8)

    def test_summary_requires_both_repeats_and_uses_whole_arm_wall_time(self):
        rows = [dict(workers=w, status='completed', wall_seconds=seconds,
                     output_files=12, byte_identical_outputs=12)
                for w, seconds in ((1, 100), (1, 120), (2, 60), (2, 50), (4, 40), (4, 48))]
        result = pilot.summarize(rows)
        self.assertEqual(result['1x8']['median_wall_seconds'], 110)
        self.assertEqual(result['2x4']['throughput_speedup_vs_1x8'], 2)
        self.assertEqual(result['4x2']['output_files'], 24)
        with self.assertRaisesRegex(ValueError, '2 completed repeats'):
            pilot.summarize(rows[:-1])

    def test_all_five_seeds_keep_thirty_searches_and_one_pass_summary_is_explicit(self):
        self.config['parameters']['seeds'] = [101, 102, 103, 104, 105]
        tasks = pilot.build_tasks(self.config, all_seeds=True)
        self.assertEqual(len(tasks), 10)
        self.assertEqual(sum(len(t['inputs']) for t in tasks), 30)
        self.assertEqual({t['seed'] for t in tasks}, {101, 102, 103, 104, 105})
        self.assertEqual(len(pilot.build_tasks(self.config)), 4)
        rows = [dict(workers=w, status='completed', wall_seconds=seconds,
                     output_files=30, byte_identical_outputs=30)
                for w, seconds in ((1, 500), (2, 450), (4, 600))]
        results = pilot.summarize(rows, repeats=1)
        self.assertEqual(results['1x8']['repeats'], 1)
        self.assertEqual(results['2x4']['output_files'], 30)
        self.assertEqual(results['2x4']['median_wall_seconds'], 450)


if __name__ == '__main__':
    unittest.main()
