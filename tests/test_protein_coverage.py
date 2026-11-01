"""Synthetic evidence fixtures; these tests do not perform or count real docking."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'validation'))
import protein_coverage as coverage
import system_validation as system


class ProteinCoverageTests(unittest.TestCase):
    def test_strict_goal_requires_91_of_100_and_keeps_failures_in_denominator(self):
        panel = {'selection': 'predeclared', 'selection_note': 'Synthetic accounting test',
                 'goal_comparison': 'greater_than',
                 'targets': [{'id': f'p-{i}', 'label': f'Protein {i}', 'family': 'Synthetic',
                              'cases': [{'index': i}]} for i in range(100)]}
        for successes, expected in [(90, 'completion_target_not_established'), (91, 'completion_target_met')]:
            def outcome(case):
                passed = case['index'] < successes
                return {'primary': True, 'completed': passed, 'completion_route': 'routine',
                        'visual_review': 'pending', 'platform': 'fixture', 'runtime_fingerprint': 'same',
                        'run': 'synthetic', 'status': 'passed' if passed else 'failed'}
            with self.subTest(successes=successes), patch.object(coverage, 'case_outcome', side_effect=outcome):
                result = coverage.assess(panel)
                self.assertEqual(result['status'], expected)
                self.assertEqual(result['protein_count'], 100)
                self.assertEqual(result['application_supported_completed'], successes)
                self.assertEqual(result['goal_comparison'], 'greater_than')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.run = self.root / 'run'
        self.case = {'case_id': 'one', 'structure': 'TEST', 'engine': 'vina',
                     'primary': True, 'run': str(self.run)}
        self.panel = {'schema': coverage.SCHEMA, 'selection': 'predeclared',
                      'selection_note': 'Synthetic independent-target fixtures, not scientific evidence',
                      'targets': [{'id': 'protein-1', 'label': 'Protein one', 'family': 'Family one',
                                   'cases': [self.case]}]}
        self.attempt = self.run / 'one/attempt-001'
        self.worker = {'status': 'passed', 'engine': 'vina', 'real_screening_started': True,
                       'workload': {'total_docking_jobs': 1},
                       'checks': ['Fresh-host reopen preserves result count', 'Reopen preserves saved scientific state']}
        self.raw = {'status': 'passed', 'target': 'TEST', 'reference_site_verified': True,
                    'original_inputs_unchanged': True, 'receptor_sha256': 'a' * 64,
                    'raw_active_job_after_cleanup': False, 'raw_pending_decision_after_cleanup': False}
        self.write_evidence()

    def write_evidence(self, status='passed', visual='pending'):
        paths = ['worker/summary.json', 'worker/raw-preparation.json',
                 'worker/screen/compounds/c/pose_analysis/all_poses.sdf',
                 'worker/screen/compounds/c/pose_analysis/cluster_summary.csv',
                 'worker/screen/compounds/c/pose_analysis/cluster_001/interactions/report.xml',
                 'worker/screen/compounds/c/pose_analysis/cluster_001/interactions/representative_plip2d.png',
                 'worker/screen/report/result.pdf']
        for name in paths:
            p = self.attempt / name
            p.parent.mkdir(parents=True, exist_ok=True)
            value = self.worker if name == paths[0] else self.raw if name == paths[1] else None
            p.write_text(json.dumps(value) if value is not None else 'synthetic product')
        row = {'id': 'one', 'target': 'TEST', 'engine': 'vina', 'status': status,
               'directory': 'one/attempt-001', 'visual_review': visual,
               'inventory': {p: system.sha(self.attempt / p) for p in paths}}
        self.summary = {'schema': system.SCHEMA, 'fingerprint': 'suite-specific',
                        'identity': {'platform': 'fixture', 'fingerprint': 'runtime-specific'},
                        'cases': [row]}
        system.write(self.run / 'summary.json', self.summary)

    def validated(self, panel=None):
        path = self.root / 'panel.json'
        path.write_text(json.dumps(self.panel if panel is None else panel))
        return coverage.read_panel(path)

    def test_raw_completion_is_not_accuracy_or_visual_acceptance(self):
        result = coverage.assess(self.validated())
        self.assertEqual(result['primary_completed'], 1)
        self.assertEqual(result['visual_reviews'], {'pending': 1})
        self.assertFalse(result['scientific_accuracy_assessed'])
        self.assertEqual(result['status'], 'completion_target_not_established')

    def test_many_scenarios_do_not_inflate_protein_count(self):
        for n in range(12):
            self.panel['targets'][0]['cases'].append(dict(self.case, primary=False, case_id=f'extra-{n}', run=None))
        result = coverage.assess(self.validated())
        self.assertEqual((result['protein_count'], result['primary_completed']), (1, 1))

    def test_duplicate_cases_and_structure_aliases_are_rejected(self):
        for same_case in (True, False):
            panel = copy.deepcopy(self.panel)
            target = copy.deepcopy(panel['targets'][0]); target['id'] = 'different-name'
            if not same_case:
                target['cases'][0]['case_id'] = 'different-case'
            panel['targets'].append(target)
            with self.assertRaises(ValueError):
                self.validated(panel)

    def test_failed_primary_not_replaced_by_successful_secondary(self):
        self.panel['targets'][0]['cases'] = [dict(self.case, case_id='unrun', run=None), dict(self.case, primary=False)]
        result = coverage.assess(self.validated())
        self.assertEqual(result['primary_completed'], 0)
        self.assertEqual(result['supplemental_completion_only'], 1)
        self.assertEqual(result['protein_count'], 1)

    def test_failed_blocked_and_unrun_remain_in_denominator(self):
        for status in ('failed', 'blocked', 'interrupted', 'not_run', 'running'):
            self.write_evidence(status=status)
            result = coverage.assess(self.validated())
            self.assertEqual((result['protein_count'], result['primary_completed']), (1, 0))

    def test_exit_zero_preparation_only_or_no_search_is_not_completion(self):
        for value in (0, True, None):
            self.worker['workload']['total_docking_jobs'] = value
            self.write_evidence()
            self.assertEqual(coverage.assess(self.validated())['primary_completed'], 0)
        self.worker['workload']['total_docking_jobs'] = 1
        self.worker['real_screening_started'] = False
        self.write_evidence()
        self.assertEqual(coverage.assess(self.validated())['primary_completed'], 0)

    def test_protocol_reuse_does_not_substitute_for_raw_preparation(self):
        del self.summary['cases'][0]['inventory']['worker/raw-preparation.json']
        system.write(self.run / 'summary.json', self.summary)
        self.assertEqual(coverage.assess(self.validated())['primary_completed'], 0)

    def test_cleanup_and_reopen_must_be_explicit(self):
        del self.raw['raw_active_job_after_cleanup']
        self.write_evidence()
        self.assertEqual(coverage.assess(self.validated())['primary_completed'], 0)
        self.raw['raw_active_job_after_cleanup'] = False
        self.worker['checks'] = []
        self.write_evidence()
        self.assertEqual(coverage.assess(self.validated())['primary_completed'], 0)

    def test_changed_evidence_and_wrong_engine_are_rejected(self):
        (self.attempt / 'worker/summary.json').write_text('{}')
        with self.assertRaisesRegex(ValueError, 'evidence changed'):
            coverage.assess(self.validated())
        self.write_evidence()
        self.case['engine'] = 'qvinaw'
        with self.assertRaisesRegex(ValueError, 'different structure or engine'):
            coverage.assess(self.validated())

    def test_missing_product_is_not_completed(self):
        del self.summary['cases'][0]['inventory']['worker/screen/report/result.pdf']
        system.write(self.run / 'summary.json', self.summary)
        self.assertEqual(coverage.assess(self.validated())['primary_completed'], 0)

    def test_route_requires_review_of_exact_prepared_receptor(self):
        self.case['completion_route'] = 'reviewed_changes'
        with self.assertRaisesRegex(ValueError, 'hash-bound review'):
            self.validated()
        self.case['route_review'] = {'actor': 'fixture operator', 'rationale': 'Reviewed synthetic inventory',
                                     'prepared_receptor_sha256': 'b' * 64}
        with self.assertRaisesRegex(ValueError, 'different prepared receptor'):
            coverage.assess(self.validated())
        self.case['route_review']['prepared_receptor_sha256'] = 'a' * 64
        self.assertEqual(coverage.assess(self.validated())['application_supported_completed'], 1)

    def test_manual_external_rescue_is_disclosed_not_supported_completion(self):
        self.case['completion_route'] = 'external_manual_edit'
        result = coverage.assess(self.validated())
        self.assertEqual(result['primary_completed'], 1)
        self.assertEqual(result['application_supported_completed'], 0)

    def test_cli_never_overwrites_existing_result_or_evidence(self):
        panel = self.root / 'panel.json'; panel.write_text(json.dumps(self.panel))
        out = self.root / 'out.json'
        script = Path(coverage.__file__).with_name('validate.py')
        command = [sys.executable, str(script), 'protein-coverage', '--panel', str(panel), '--out', str(out)]
        first = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(first.returncode, 3, first.stderr)
        before = out.read_bytes()
        second = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(second.returncode, 2)
        self.assertEqual(out.read_bytes(), before)

    def test_acceptance_requires_100_targets_fixed_profile_and_90_percent(self):
        # Stub only case reading for the threshold arithmetic; this is not a
        # molecular/GUI fixture and cannot produce a real acceptance receipt.
        from unittest.mock import patch
        targets = []
        for n in range(100):
            targets.append({'id': f'p{n}', 'label': f'Protein {n}', 'family': 'Fixture family',
                            'cases': [dict(self.case, case_id=f'case-{n}', structure=f'S{n}')]})
        panel = self.validated(dict(self.panel, targets=targets))
        def outcome(case):
            completed = int(case['case_id'].split('-')[1]) < 90
            return dict(case, completed=completed, status='passed' if completed else 'failed',
                        completion_route='routine', visual_review='pending',
                        platform='fixture', runtime_fingerprint='same-runtime')
        with patch.object(coverage, 'case_outcome', side_effect=outcome):
            result = coverage.assess(panel)
            self.assertEqual(result['status'], 'completion_target_met')
            self.assertEqual(result['application_supported_completion_percent'], 90)
            panel['selection'] = 'retrospective'
            self.assertEqual(coverage.assess(panel)['status'], 'completion_target_not_established')
            panel['selection'] = 'predeclared'; panel['targets'].pop()
            self.assertEqual(coverage.assess(panel)['status'], 'completion_target_not_established')

    def test_mixed_candidate_runtimes_do_not_establish_single_build_acceptance(self):
        from unittest.mock import patch
        targets = [dict(self.panel['targets'][0], id=f'p{n}',
                        cases=[dict(self.case, case_id=f'c{n}', structure=f'S{n}')]) for n in range(100)]
        panel = self.validated(dict(self.panel, targets=targets))
        def outcome(case):
            return dict(case, completed=True, status='passed', completion_route='routine',
                        visual_review='pending', platform='fixture',
                        runtime_fingerprint='new-build' if case['case_id'] == 'c0' else 'old-build')
        with patch.object(coverage, 'case_outcome', side_effect=outcome):
            result = coverage.assess(panel)
        self.assertEqual(result['primary_completed'], 100)
        self.assertEqual(result['status'], 'completion_target_not_established')
        self.assertTrue(any('runtime/platform' in reason for reason in result['acceptance_limitations']))


if __name__ == '__main__':
    unittest.main()
