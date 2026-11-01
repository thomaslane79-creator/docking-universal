"""Supervisor, evidence and scientific-metric guards using tiny local workers."""
import csv
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'validation'))
import system_validation as system


class SystemValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.lock = self.root / 'runner.lock'
        self.out = self.root / 'run'
        self.driver = self.root / 'tiny_worker.py'
        self.driver.write_text('import json,sys\nfrom pathlib import Path\nPath(sys.argv[1]).write_text(json.dumps({"status":"passed","reason":"specific-test"}))\n')
        self.case = {'id':'tiny', 'layer':'workflow', 'driver':'command',
                     'inputs':{'driver':{'path':str(self.driver), 'sha256':system.sha(self.driver)}},
                     'argv':['{python}', '{driver}', '{out}/proof.json'],
                     'checks':[{'kind':'json','path':'proof.json','keys':['status'],'equals':'passed'}]}
        self.suite = {'schema':system.SCHEMA, 'name':'Synthetic tests only',
                      'profile':{'python':sys.executable, 'capabilities':[]}, 'cases':[self.case]}

    def tearDown(self):
        self.temp.cleanup()

    def run_suite(self, **kw):
        return system.run_suite(self.suite, self.out, execute=True, lock_path=self.lock, **kw)

    def test_requires_explicit_execution(self):
        with self.assertRaisesRegex(ValueError, 'execute'):
            system.run_suite(self.suite, self.out)
        self.assertFalse(self.out.exists())

    def test_success_creates_retained_proof_and_markdown(self):
        result = self.run_suite()
        self.assertEqual(result['status'], 'passed')
        self.assertTrue((self.out / 'results.md').is_file())
        self.assertIn('proof.json', result['cases'][0]['inventory'])

    def test_completed_resume_does_not_repeat_worker(self):
        first = self.run_suite()
        path = self.out / first['cases'][0]['directory'] / 'proof.json'
        before = path.stat().st_mtime_ns
        second = self.run_suite(resume=True)
        self.assertEqual(path.stat().st_mtime_ns, before)
        self.assertEqual(second['attempts'], [])

    def test_resume_detects_changed_output(self):
        result = self.run_suite()
        (self.out / result['cases'][0]['directory'] / 'proof.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            self.run_suite(resume=True)

    def test_changed_suite_cannot_resume(self):
        self.run_suite()
        self.case['timeout_seconds'] = 90
        with self.assertRaisesRegex(ValueError, 'changed'):
            self.run_suite(resume=True)

    def test_package_metadata_change_invalidates_runtime_identity(self):
        prefix = self.root / 'fake-environment'
        binary = prefix / 'bin/python'
        binary.parent.mkdir(parents=True)
        binary.write_text('unchanged-python')
        metadata = prefix / 'lib/python3.9/site-packages/fixture.dist-info/METADATA'
        metadata.parent.mkdir(parents=True)
        metadata.write_text('Name: synthetic-fixture\nVersion: 1\n')
        self.suite['profile']['scientific_python'] = str(binary)
        before = system.runtime_identity(self.suite)['fingerprint']
        metadata.write_text('Name: synthetic-fixture\nVersion: 2\n')
        self.assertNotEqual(system.runtime_identity(self.suite)['fingerprint'], before)

    def test_missing_capability_is_blocked_not_passed(self):
        self.case['requires'] = ['unavailable_gpu']
        result = self.run_suite()
        self.assertEqual(result['cases'][0]['status'], 'blocked')
        self.assertEqual(result['status'], 'incomplete')

    def test_missing_or_changed_input_is_blocked(self):
        self.driver.write_text('changed')
        result = self.run_suite()
        self.assertEqual(result['cases'][0]['status'], 'blocked')
        self.assertFalse((self.out / 'tiny').exists())

    def test_exit_zero_without_correct_evidence_fails(self):
        self.case['checks'][0]['equals'] = 'not-produced'
        result = self.run_suite()
        self.assertEqual(result['status'], 'failed')

    def test_unexpected_scientific_adapter_exit_requires_reconciliation(self):
        self.case['argv'] = [sys.executable,'-c','raise SystemExit(7)']
        result = self.run_suite()
        self.assertEqual(result['cases'][0]['status'],'interrupted')
        self.assertTrue(json.loads(self.lock.read_text())['unresolved_worker'])

    def test_expected_rejection_requires_exact_reason_not_arbitrary_failure(self):
        self.case.update(expected='rejection', expected_exit=0)
        self.case['checks'][0].update(keys=['reason'], equals='unsupported-macrocycle')
        self.assertEqual(self.run_suite()['status'], 'failed')

    def test_failed_case_not_automatically_retried(self):
        self.case['checks'][0]['equals'] = 'wrong'
        self.run_suite()
        self.run_suite(resume=True)
        self.assertFalse((self.out / 'tiny/attempt-002').exists())
        result = self.run_suite(resume=True, retry=['tiny'])
        self.assertEqual(len(result['attempts']), 1)
        self.assertTrue((self.out / 'tiny/attempt-002').is_dir())

    def test_visual_gate_cannot_be_replaced_by_functional_pass(self):
        self.case['visual_review_required'] = True
        self.assertEqual(self.run_suite()['status'], 'needs_visual_review')
        system.review(self.out, 'tiny', 'passed', 'Inspected the synthetic output fixture')
        self.assertEqual(json.loads((self.out / 'summary.json').read_text())['status'], 'passed')

    def test_visual_failure_wins_over_other_pending_reviews(self):
        rows = [{'status':'passed','visual_review':'failed'}, {'status':'passed','visual_review':'pending'}]
        self.assertEqual(system.aggregate(rows)[0], 'failed')

    def test_running_is_normal_progress_not_attention_failure(self):
        self.assertEqual(system.aggregate([{'status':'running'}])[0], 'running')

    def test_protected_file_mutation_is_failure(self):
        protected = self.root / 'study.json'
        protected.write_text('original')
        self.suite['profile']['protected_paths'] = [str(protected)]
        self.case['argv'] = [sys.executable, '-c', f'from pathlib import Path;Path({str(protected)!r}).write_text("mutated")']
        with self.assertRaisesRegex(ValueError, 'Protected file changed'):
            self.run_suite()

    def test_output_cannot_be_inside_protected_study(self):
        self.suite['profile']['protected_paths'] = [str(self.root)]
        with self.assertRaisesRegex(ValueError, 'inside protected'):
            self.run_suite()

    def test_artifact_symlink_escape_is_rejected(self):
        outside = self.root / 'outside.json'
        outside.write_text('{}')
        inside = self.root / 'case'
        inside.mkdir()
        try:
            (inside / 'proof.json').symlink_to(outside)
        except OSError:
            self.skipTest('Symlink creation not permitted')
        with self.assertRaisesRegex(ValueError, 'escapes'):
            system.assert_artifacts(self.case, inside)

    def test_lock_excludes_second_runner(self):
        with system.suite_lock(self.lock):
            with self.assertRaises(BlockingIOError):
                with system.suite_lock(self.lock):
                    pass

    def test_interrupted_owner_requires_reconciliation(self):
        self.lock.write_text(json.dumps({'unresolved_worker':True,'worker_pid':999999}))
        with self.assertRaisesRegex(ValueError, 'reconciliation'):
            with system.suite_lock(self.lock):
                pass

    def test_timeout_is_not_silently_retried(self):
        self.case['argv'] = [sys.executable, '-c', 'import time;time.sleep(20)']
        self.case['timeout_seconds'] = .02
        result = self.run_suite()
        self.assertEqual(result['cases'][0]['status'], 'interrupted')
        self.assertTrue(json.loads(self.lock.read_text())['unresolved_worker'])

    def test_anonymous_export_omits_all_sensitive_fields(self):
        value = system.public_status({'status':'passed','cases':[{'status':'passed','layer':'scientific',
            'id':'private-target', 'reason':'secret', 'scientific_metrics':{'energy':-99},'path':'/private/study'}]})
        text = json.dumps(value)
        for private in ('private-target', 'secret', '/private/study', 'energy', '-99'):
            self.assertNotIn(private, text)

    def test_unknown_or_duplicate_case_schema_rejected(self):
        self.suite['cases'].append(dict(self.case))
        path = self.root / 'suite.json'
        system.write(path, self.suite)
        with self.assertRaisesRegex(ValueError, 'unique'):
            system.read_suite(path)

    def test_no_tests_discovery_is_not_success(self):
        self.case.update(driver='unittest', modules=[])
        self.assertEqual(system.readiness(self.case, self.suite['profile'])[0], 'blocked')

    def test_numeric_catalog_case_ids_are_safe(self):
        self.case['id'] = '2r8n-screen-vina'
        path = self.root / 'suite.json'
        system.write(path, self.suite)
        self.assertEqual(system.read_suite(path)['cases'][0]['id'], self.case['id'])

    def test_gui_execution_requires_a_pinned_external_engine_binary(self):
        case = {'id':'gui','driver':'screen_gui','engine':'vina','import_review_approved':True,
                'inputs':{'protocol':{'path':str(self.driver),'sha256':system.sha(self.driver)},
                          'ligands':{'path':str(self.driver),'sha256':system.sha(self.driver)}}}
        profile = {'python':sys.executable,'gui_python':sys.executable,'scientific_python':sys.executable,
                   'runtime':str(self.root),'cli':str(self.driver),'study_roots':[str(self.root)]}
        state, reason = system.readiness(case, profile)
        self.assertEqual(state,'blocked')
        self.assertIn('engine executable',reason)
        profile['identity_files'] = {'vina':str(self.driver)}
        self.assertEqual(system.readiness(case, profile)[0],'ready')

    def test_gui_crash_without_cleanup_receipt_stops_queue(self):
        self.case.update(driver='screen_gui', engine='vina', import_review_approved=True)
        self.case['inputs'].update({k:{'path':str(self.driver),'sha256':system.sha(self.driver)} for k in ('protocol','ligands')})
        self.suite['profile'].update(gui_python=sys.executable, scientific_python=sys.executable,
            runtime=str(self.root), cli=str(self.driver), study_roots=[str(self.root)],
            identity_files={'vina':str(self.driver)})
        with patch.object(system,'command',return_value=[sys.executable,'-c','raise SystemExit(9)']):
            result = self.run_suite()
        self.assertEqual(result['cases'][0]['status'],'interrupted')
        self.assertTrue(json.loads(self.lock.read_text())['unresolved_worker'])

    def test_generated_catalog_is_valid_and_does_not_claim_unbound_examples_pass(self):
        import validate
        args = SimpleNamespace(python=sys.executable, gui_python=None, runtime=None, cli=None,
                               study_root=[], ad4=False, node=None)
        suite = validate.initial_suite(args)
        path = self.root / 'catalog.json'
        system.write(path, suite)
        self.assertEqual(len(system.read_suite(path)['cases']), 37)
        self.assertEqual(sum(c['driver'] == 'screen_gui' for c in suite['cases']), 24)
        scientific = [c for c in suite['cases'] if c['layer'] == 'scientific']
        self.assertEqual(len(scientific), 5)
        self.assertTrue(all(system.readiness(c, suite['profile'])[0] == 'blocked' for c in scientific))

    def test_nonfinite_timeout_is_rejected(self):
        self.case['timeout_seconds'] = float('inf')
        path = self.root / 'suite.json'
        path.write_text(json.dumps(self.suite))
        with self.assertRaisesRegex(ValueError, 'timeout'):
            system.read_suite(path)

    def test_incomplete_and_unreviewed_runs_have_nonzero_acceptance_exit(self):
        import validate
        self.assertEqual(validate.acceptance_exit('passed'), 0)
        for status in ('incomplete', 'needs_visual_review', 'failed', 'attention_required', 'no_coverage'):
            self.assertNotEqual(validate.acceptance_exit(status), 0)

    def test_comparison_rejects_changed_engine_and_preserves_coverage_changes(self):
        self.run_suite()
        candidate = self.root / 'candidate'
        candidate.mkdir()
        summary = json.loads((self.out / 'summary.json').read_text())
        summary['cases'][0]['engine'] = 'adgpu'
        summary['cases'].append({'id':'added', 'layer':'workflow', 'status':'blocked'})
        system.write(candidate / 'summary.json', summary)
        result = system.compare_runs(self.out, candidate)
        by_id = {v['id']:v for v in result['cases']}
        self.assertIn('not_comparable', by_id['tiny']['comparison'])
        self.assertEqual(by_id['added']['comparison'], 'new_coverage')

    def test_unsafe_case_and_check_paths_rejected(self):
        for key, value in (('id','../escape'), ('checks',[{'kind':'file','path':'../escape'}])):
            original = self.case[key]
            self.case[key] = value
            path = self.root / 'bad.json'
            system.write(path, self.suite)
            with self.assertRaises(ValueError):
                system.read_suite(path)
            self.case[key] = original


class ExperimentalMetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'poses.csv'

    def tearDown(self):
        self.temp.cleanup()

    def write(self, rows, columns=('arm','seed','affinity_kcal_per_mol','crystal_rmsd_angstrom')):
        with self.path.open('w',newline='') as stream:
            writer = csv.writer(stream); writer.writerow(columns); writer.writerows(rows)

    def test_primary_energy_pose_is_not_best_rmsd_pose(self):
        self.write([['a',1,-8,4],['a',1,-7,.8],['a',2,-8,1.2]])
        group = system.recovery_metrics(self.path,[1,2])[0]
        self.assertEqual(group['primary_recovery_all_ties'],1)
        self.assertEqual(group['seeds'][0]['lowest_energy_rmsd_min_angstrom'],4)
        self.assertEqual(group['seeds'][0]['secondary_best_of_poses_rmsd_angstrom'],.8)

    def test_energy_ties_do_not_cherry_pick_experimental_rmsd(self):
        self.write([['a',1,-8,4],['a',1,-8,.8]])
        group = system.recovery_metrics(self.path,[1])[0]
        self.assertEqual(group['primary_recovery_all_ties'],0)
        self.assertEqual(group['primary_recovery_any_tie'],1)
        self.assertEqual(group['seeds'][0]['lowest_energy_tie_count'],2)

    def test_missing_seed_in_one_arm_blocks_complete_comparison(self):
        self.write([['a',1,-8,1],['a',2,-8,1],['b',1,-8,1]])
        with self.assertRaisesRegex(ValueError, 'Missing matched seeds'):
            system.recovery_metrics(self.path,[1,2])

    def test_internal_vina_rmsd_columns_not_experimental_reference(self):
        self.write([['a',1,-8,0]], ('arm','seed','affinity_kcal_per_mol','rmsd_lower_bound'))
        with self.assertRaisesRegex(ValueError, 'experimental comparison'):
            system.recovery_metrics(self.path,[1])

    def test_nonfinite_and_unexpected_seeds_rejected(self):
        for row in (['a',1,'nan',1],['a',1,-8,'inf'],['a',2,-8,1],['a',1,-8,-1]):
            self.write([row])
            with self.assertRaises(ValueError):
                system.recovery_metrics(self.path,[1])


if __name__ == '__main__':
    unittest.main()
