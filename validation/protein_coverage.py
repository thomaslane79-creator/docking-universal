"""Read-only protein-level completion accounting for local validation evidence.

An operator declares target identities and primary cases before acceptance.
This module never launches, retries, repairs, downloads or approves anything.
"""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path

import system_validation as system

SCHEMA = 'docking-universal-protein-coverage-v1'
ROUTES = {'routine', 'reviewed_changes', 'external_manual_edit', 'unclassified'}


def read_panel(path):
    panel = json.loads(Path(path).read_text())
    if panel.get('schema') != SCHEMA or panel.get('selection') not in {'predeclared', 'retrospective'}:
        raise ValueError('A declared protein coverage panel is required')
    if not isinstance(panel.get('selection_note'), str) or not panel['selection_note'].strip():
        raise ValueError('Explain how the panel was selected and grouped')
    if panel.get('goal_comparison', 'at_least') not in {'at_least', 'greater_than'}:
        raise ValueError('Unknown protein-completion goal comparison')
    targets = panel.get('targets')
    if not isinstance(targets, list) or not targets:
        raise ValueError('Protein panel is empty')
    ids, cases, structures = set(), set(), {}
    for target in targets:
        if not system.ID.fullmatch(target.get('id', '')) or target['id'] in ids:
            raise ValueError('Protein identities must be unique')
        ids.add(target['id'])
        if any(not isinstance(target.get(k), str) or not target[k].strip() for k in ('label', 'family')):
            raise ValueError('Each protein needs a label and family')
        rows = target.get('cases')
        if not isinstance(rows, list) or not rows:
            raise ValueError('Each protein needs declared cases')
        if sum(row.get('primary') is True for row in rows) != 1:
            raise ValueError('Declare exactly one primary raw-input case per protein')
        for row in rows:
            key = row.get('case_id', '')
            if not system.ID.fullmatch(key) or key in cases:
                raise ValueError('A case cannot count for more than one protein or be repeated')
            cases.add(key)
            if type(row.get('primary')) is not bool:
                raise ValueError('Declare primary versus supplemental coverage explicitly')
            structure = row.get('structure', '')
            if not isinstance(structure, str) or not structure.strip():
                raise ValueError('Each case needs a structure identity')
            owner = structures.setdefault(structure.upper(), target['id'])
            if owner != target['id']:
                raise ValueError('One structure cannot inflate independent protein coverage')
            if row.get('engine') not in system.ENGINES:
                raise ValueError('Declare the engine for every case')
            if row.get('completion_route', 'unclassified') not in ROUTES:
                raise ValueError('Unknown preparation/completion classification')
            if row.get('completion_route') in {'routine', 'reviewed_changes'}:
                review = row.get('route_review') or {}
                if any(not isinstance(review.get(k), str) or not review[k].strip()
                       for k in ('actor', 'rationale', 'prepared_receptor_sha256')):
                    raise ValueError('Supported-route classification needs an explicit hash-bound review')
            if row.get('run') is not None and not isinstance(row['run'], str):
                raise ValueError('Run must be a local directory')
    return panel


def case_outcome(case):
    """Verify closed evidence; never treat preparation or exit-zero alone as a dock."""
    result = {k: case[k] for k in ('case_id', 'structure', 'engine', 'primary')}
    result.update(completed=False, completion_route=case.get('completion_route', 'unclassified'),
                  visual_review='not_run', platform=None, runtime_fingerprint=None)
    if not case.get('run'):
        return dict(result, status='not_run', reason='No run bound; case stays in the denominator')
    run = Path(case['run']).expanduser().resolve()
    summary_path = run / 'summary.json'
    if not summary_path.is_file():
        return dict(result, status='not_run', reason='Bound run has not produced a summary')
    summary = json.loads(summary_path.read_text())
    if summary.get('schema') != system.SCHEMA:
        raise ValueError('Unknown validation-run schema')
    rows = [r for r in summary.get('cases', []) if r['id'] == case['case_id']]
    if len(rows) != 1:
        raise ValueError('Bound run must contain exactly one matching case')
    row = rows[0]
    if str(row.get('target', '')).upper() != case['structure'].upper() or row.get('engine') != case['engine']:
        raise ValueError('Bound outcome has a different structure or engine')
    result.update(status=row['status'], visual_review=row.get('visual_review', 'pending'),
                  platform=summary.get('identity', {}).get('platform'),
                  runtime_fingerprint=summary.get('identity', {}).get('fingerprint'),
                  run=str(run), summary_sha256=system.sha(summary_path))
    if row['status'] != 'passed':
        return dict(result, reason=row.get('reason', 'Workflow did not complete'))
    # Same retained-output verifier used by supervisor resume and visual review.
    system.verify_saved(row, run)
    attempt = system.resolve_artifact(run, row['directory'])
    required = ('worker/summary.json', 'worker/raw-preparation.json')
    if any(name not in row['inventory'] for name in required):
        return dict(result, status='incomplete_evidence', reason='Raw preparation and docking receipts are required')
    worker, raw = [json.loads(system.resolve_artifact(attempt, name).read_text()) for name in required]
    jobs = worker.get('workload', {}).get('total_docking_jobs')
    if (worker.get('status') != 'passed' or worker.get('real_screening_started') is not True
            or type(jobs) is not int or jobs < 1 or raw.get('status') != 'passed'
            or raw.get('reference_site_verified') is not True
            or raw.get('original_inputs_unchanged') is not True
            or raw.get('raw_active_job_after_cleanup') is not False
            or raw.get('raw_pending_decision_after_cleanup') is not False
            or 'Fresh-host reopen preserves result count' not in worker.get('checks', [])
            or 'Reopen preserves saved scientific state' not in worker.get('checks', [])):
        return dict(result, status='incomplete_evidence', reason='Raw-input/docking/cleanup evidence is incomplete')
    if worker.get('engine') != case['engine'] or str(raw.get('target', '')).upper() != case['structure'].upper():
        raise ValueError('Worker receipts disagree with the declared protein case')
    if result['completion_route'] in {'routine', 'reviewed_changes'}:
        if case['route_review']['prepared_receptor_sha256'] != raw.get('receptor_sha256'):
            raise ValueError('Completion-route review belongs to a different prepared receptor')
        result['route_review'] = case['route_review']
    inventory = row['inventory']
    # Evidence of retained scientific products, not only a worker's success flag.
    products = {
        'poses': any(p.endswith('/pose_analysis/all_poses.sdf') for p in inventory),
        'clusters': any(p.endswith('/pose_analysis/cluster_summary.csv') for p in inventory),
        'interactions': any(p.endswith('/interactions/report.xml') for p in inventory),
        'diagrams': any(p.endswith('/interactions/representative_plip2d.png') for p in inventory),
        'report': any('/screen/report/' in p and p.endswith('.pdf') for p in inventory),
    }
    if not all(products.values()):
        return dict(result, status='incomplete_evidence', products=products,
                    reason='Required retained docking products are missing')
    return dict(result, completed=True, new_engine_searches=jobs, products=products,
                reason='Raw-input workflow completed; visual and accuracy gates remain separate')


def assess(panel):
    targets = []
    for target in panel['targets']:
        cases = [case_outcome(case) for case in target['cases']]
        primary = next(row for row in cases if row['primary'])
        targets.append({'id': target['id'], 'label': target['label'], 'family': target['family'],
                        'primary_completed': primary['completed'], 'primary_route': primary['completion_route'],
                        'supplemental_completion_only': not primary['completed'] and any(c['completed'] for c in cases),
                        'cases': cases})
    count = len(targets)
    completed = sum(t['primary_completed'] for t in targets)
    supported = sum(t['primary_completed'] and t['primary_route'] in {'routine', 'reviewed_changes'} for t in targets)
    primary_cases = [next(c for c in t['cases'] if c['primary']) for t in targets]
    identities = {(c['platform'], c['runtime_fingerprint']) for c in primary_cases if c.get('run')}
    unresolved = sum(c['status'] in {'not_run', 'running'} for c in primary_cases)
    reasons = []
    if panel['selection'] != 'predeclared':
        reasons.append('Retrospective diagnostics cannot establish the prospective coverage target')
    if count < 100:
        reasons.append('The broad acceptance panel needs at least 100 distinct protein targets')
    if unresolved:
        reasons.append('Primary cases remain unrun or running')
    if len(identities) != 1 or any(not all(pair) for pair in identities):
        reasons.append('Matching runtime/platform acceptance has not been established')
    strict = panel.get('goal_comparison', 'at_least') == 'greater_than'
    if supported * 10 < count * 9 or (strict and supported * 10 == count * 9):
        reasons.append('Verified application-supported primary completion is not above 90%' if strict else
                       'Verified application-supported primary completion is below 90%')
    return {'schema': SCHEMA, 'selection': panel['selection'], 'selection_note': panel['selection_note'],
            'status': 'completion_target_met' if not reasons else 'completion_target_not_established',
            'goal_percent': 90, 'goal_comparison': 'greater_than' if strict else 'at_least',
            'protein_count': count, 'primary_completed': completed,
            'primary_completion_percent': 100 * completed / count,
            'application_supported_completed': supported,
            'application_supported_completion_percent': 100 * supported / count,
            'primary_routes': dict(Counter(t['primary_route'] for t in targets if t['primary_completed'])),
            'primary_statuses': dict(Counter(c['status'] for c in primary_cases)),
            'visual_reviews': dict(Counter(c['visual_review'] for c in primary_cases)),
            'supplemental_completion_only': sum(t['supplemental_completion_only'] for t in targets),
            'acceptance_limitations': reasons, 'targets': targets,
            'new_calculations_launched': 0, 'scientific_accuracy_assessed': False,
            'scope': 'Local functional completion accounting; target grouping requires scientific curation. '
                     'Not accuracy, visual acceptance, engine equivalence or general population prevalence.'}
