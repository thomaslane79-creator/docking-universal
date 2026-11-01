#!/usr/bin/env python3
"""Plan, execute, resume and review local Docking Universal validation suites."""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys

import system_validation as system


def acceptance_exit(status):
    return 0 if status == 'passed' else 1 if status in {'failed', 'attention_required'} else 3


def initial_suite(args):
    profile = {'python': str(Path(args.python).resolve()), 'capabilities': ['cpu'],
               'gui_python': str(Path(args.gui_python).resolve()) if args.gui_python else None,
               'scientific_python': str(Path(args.python).resolve()),
               'runtime': str(Path(args.runtime).resolve()) if args.runtime else None,
               'cli': str(Path(args.cli).resolve()) if args.cli else None,
               'study_roots': [str(Path(p).expanduser().resolve()) for p in args.study_root],
               'protected_paths': [str(Path(p).expanduser().resolve()) for p in args.study_root],
               'environment': {}}
    prefix = Path(args.python).resolve().parent.parent
    identities = {}
    for name, path in (('vina', prefix.parent / 'docking-universal-vina/bin/vina'),
                       ('qvinaw', prefix.parent / 'docking-universal-qvinaw/bin/qvinaw')):
        if path.is_file():
            identities[name] = str(path.resolve())
    for descriptor in (prefix / 'share/docking-universal/adgpu/runtime.json',
                       Path.home() / '.config/docking-universal/adgpu.json'):
        if descriptor.is_file():
            identities['gpu_descriptor'] = str(descriptor)
            engine = Path(json.loads(descriptor.read_text()).get('executable', ''))
            if engine.is_file():
                identities['adgpu'] = str(engine.resolve())
            break
    node = args.node or shutil.which('node')
    if node:
        profile['environment']['DOCKING_UNIVERSAL_NODE'] = str(Path(node).resolve())
        identities['node'] = str(Path(node).resolve())
    profile['identity_files'] = identities
    if args.gui_python:
        profile['capabilities'].append('desktop')
    if args.ad4:
        profile['capabilities'].append('ad4_gpu')
    groups = {
        'state-authority': ['test_state_transactions', 'test_protocol_types', 'test_protocol_import', 'test_system_validation'],
        'chemical-inputs': ['test_sdf_io', 'test_ligand_library', 'test_ligand_tables'],
        'engine-guards': ['test_vina_cli', 'test_ad4_gpu', 'test_native_control'],
        'results-meaning': ['test_results_review_model', 'test_results_review_controller'],
        'report-provenance': ['test_report_synchronization', 'test_report_cavity'],
        'report-framing': ['test_report_snapshot_framing', 'test_figure_labels'],
        'workflow-errors': ['test_screening_workflow', 'test_process_adapter', 'test_application_host'],
        'portability-guards': ['test_windows_qvinaw', 'test_windows_viewer_runtime', 'test_file_lock'],
    }
    cases = [{'id': key, 'layer': 'regression', 'driver': 'unittest', 'modules': modules,
              'timeout_seconds': 300, 'visual_review_required': False} for key, modules in groups.items()]
    catalog = json.loads((system.PROJECT / 'validation/suites/examples.json').read_text())
    for example in catalog['examples']:
        for engine in ('vina', 'qvinaw', 'adgpu'):
            case = {'id': example['id'] + '-' + engine, 'layer': 'workflow', 'driver': 'screen_gui',
                    'target': example['target'], 'family': example['family'], 'engine': engine,
                    'features': example['features'], 'requires': ['desktop'] + (['ad4_gpu'] if engine == 'adgpu' else []),
                    'inputs': {}, 'timeout_seconds': 7200, 'import_review_approved': False,
                    'max_jobs': 50,
                    'exploratory_authorized': False, 'visual_review_required': True,
                    'checks': [{'kind':'json', 'path':'worker/summary.json', 'keys':['status'], 'equals':'passed'},
                               {'kind':'json', 'path':'worker/summary.json', 'keys':['engine'], 'equals':engine}]}
            if engine in example.get('engine_exclusions', {}):
                case['excluded_reason'] = example['engine_exclusions'][engine]
            cases.append(case)
    for example in catalog['examples']:
        if example['id'] not in {'2r5p-indinavir','2o4p-tipranavir','1mrw-kni577','1iep-imatinib','1yet-geldanamycin'}:
            continue
        cases.append({'id':'recovery-' + example['id'], 'target':example['target'], 'family':example['family'],
                      'layer':'scientific', 'driver':'command', 'engine':'vina', 'argv':[], 'inputs':{},
                      'timeout_seconds':21600, 'visual_review_required':False,
                      'checks':[{'kind':'json','path':'benchmark/summary.json','keys':['status'],'equals':'completed'},
                                {'kind':'csv','path':'benchmark/poses.csv',
                                 'columns':['arm','seed','affinity_kcal_per_mol','crystal_rmsd_angstrom'],'min_rows':3}],
                      'experimental_metrics':{'path':'benchmark/poses.csv','seeds':[41001,41002,41003],
                                              'coordinate_basis':'experimental-receptor-frame-no-fit',
                                              'groups':['arm'],'expected_groups':[{'arm':'baseline'}],
                                              'threshold_angstrom':2.0}})
    return {'schema': system.SCHEMA, 'name': 'Docking Universal systematic local validation',
            'profile': profile, 'cases': cases}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    commands.add_parser('catalog', help='Show planned examples and boundary coverage, without downloads')
    p = commands.add_parser('init', help='Create a local machine suite; does not run calculations')
    p.add_argument('--out', required=True, type=Path)
    p.add_argument('--python', default=sys.executable)
    p.add_argument('--gui-python'); p.add_argument('--runtime'); p.add_argument('--cli')
    p.add_argument('--node', help='Explicit local renderer Node executable')
    p.add_argument('--study-root', action='append', default=[])
    p.add_argument('--ad4', action='store_true', help='Declare AD4 capability; the worker still verifies actual runtime availability')
    p = commands.add_parser('plan'); p.add_argument('--suite', type=Path, required=True)
    p.add_argument('--layer', action='append', choices=sorted(system.LAYERS))
    p = commands.add_parser('bind', help='Pin a reviewed bundle and local ligand library to a matrix case')
    p.add_argument('--suite', required=True, type=Path); p.add_argument('--case', required=True)
    p.add_argument('--protocol', required=True, type=Path); p.add_argument('--ligands', required=True, type=Path)
    p.add_argument('--approve-import', required=True, action='store_true')
    p.add_argument('--approve-exploratory', action='store_true')
    p = commands.add_parser('run')
    p.add_argument('--suite', required=True, type=Path); p.add_argument('--out', required=True, type=Path)
    p.add_argument('--layer', action='append', choices=sorted(system.LAYERS))
    p.add_argument('--execute', action='store_true'); p.add_argument('--resume', action='store_true')
    p.add_argument('--retry', action='append', default=[], help='Explicit failed case only; creates a new attempt, never overwrites')
    p = commands.add_parser('review')
    p.add_argument('--run', type=Path, required=True); p.add_argument('--case', required=True)
    p.add_argument('--decision', choices=('passed', 'failed'), required=True); p.add_argument('--note', required=True)
    p = commands.add_parser('status'); p.add_argument('--run', type=Path, required=True)
    p = commands.add_parser('protein-coverage', help='Read-only completion accounting by distinct declared protein targets')
    p.add_argument('--panel', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True, help='New local result file; existing evidence is never overwritten')
    p = commands.add_parser('export-status', help='Anonymous counts only, safe for status-only CI handling')
    p.add_argument('--run', type=Path, required=True); p.add_argument('--out', type=Path, required=True)
    p = commands.add_parser('compare', help='Compare two local runs without redocking or treating changed inputs as equivalent')
    p.add_argument('--baseline', type=Path, required=True); p.add_argument('--candidate', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p = commands.add_parser('reconcile', help='Acknowledge an interrupted worker only after checking no scientific job is active')
    p.add_argument('--confirm-workers-stopped', action='store_true', required=True)
    args = parser.parse_args()
    if args.action == 'catalog':
        print((system.PROJECT / 'validation/suites/examples.json').read_text()); return 0
    if args.action == 'protein-coverage':
        from protein_coverage import read_panel, assess
        if args.out.exists():
            parser.error('Refusing to overwrite an existing coverage result')
        panel = read_panel(args.panel)
        result = assess(panel)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        with args.out.open('x') as stream:
            json.dump(result, stream, indent=2, allow_nan=False)
            stream.write('\n')
        print(json.dumps({k: result[k] for k in ('status', 'protein_count', 'primary_completed',
                         'application_supported_completed', 'acceptance_limitations')}, indent=2))
        return 0 if result['status'] == 'completion_target_met' else 3
    if args.action == 'init':
        if args.out.exists():
            parser.error('Refusing to overwrite an existing local suite')
        system.write(args.out, initial_suite(args))
        print('Created local suite; plan/bind before executing. No scientific work was launched.'); return 0
    if args.action in {'plan', 'bind', 'run'}:
        suite = system.read_suite(args.suite)
    if args.action == 'plan':
        rows = []
        for case in suite['cases']:
            if args.layer and case['layer'] not in args.layer:
                continue
            status, reason = system.readiness(case, suite['profile'])
            rows.append({'id': case['id'], 'layer': case['layer'], 'engine': case.get('engine'),
                         'status': status, 'reason': reason, 'timeout_seconds': case.get('timeout_seconds', 1800),
                         'visual_review_required': case.get('visual_review_required', False)})
            if status == 'ready' and case['driver'] == 'screen_gui':
                from docking_universal.services.screening import build_screening_plan
                from system_gui_worker import planning_selection
                try:
                    plan = build_screening_plan(case['inputs']['protocol']['path'], case['inputs']['ligands']['path'],
                                                expected_protocol_sha256=case['inputs']['protocol']['sha256'],
                                                ligand_selection=planning_selection(case))
                    rows[-1].update(planned_docking_jobs=plan.total_docking_jobs, compounds=plan.compound_count,
                                    max_jobs=case.get('max_jobs', 50))
                    if plan.total_docking_jobs > case.get('max_jobs', 50):
                        rows[-1].update(status='blocked', reason='Case workload exceeds the configured job budget')
                except (ValueError, OSError) as exc:
                    rows[-1].update(status='blocked', reason=str(exc))
        print(json.dumps(rows, indent=2)); return 0
    if args.action == 'bind':
        from docking_universal.services.protocol_import import inspect_protocol_bundle
        case = next(c for c in suite['cases'] if c['id'] == args.case)
        if case['driver'] != 'screen_gui' or case.get('excluded_reason'):
            parser.error('Only a supported GUI-screening case may be bound this way')
        preview = inspect_protocol_bundle(args.protocol)
        if preview['engine'] != case['engine']:
            parser.error('Bundle engine differs from selected matrix case')
        if str(preview['target']).upper() != str(case.get('target', '')).upper():
            parser.error('Bundle target differs from selected matrix example; do not relabel another target as coverage')
        # Binding is not permission to silently change settings or choose a site.
        for name, path in (('protocol', args.protocol), ('ligands', args.ligands)):
            if not path.is_file():
                parser.error('Local file missing: ' + name)
            case['inputs'][name] = {'path': str(path.resolve()), 'sha256': system.sha(path)}
        case.update(import_review_approved=True, exploratory_authorized=args.approve_exploratory)
        system.write(args.suite, suite)
        print('Pinned reviewed files; no calculation launched.'); return 0
    if args.action == 'run':
        summary = system.run_suite(suite, args.out, layers=args.layer, resume=args.resume,
                                   retry=args.retry, execute=args.execute)
        print(json.dumps({'status': summary['status'], 'counts': summary['counts'], 'results':str(args.out / 'results.md')}, indent=2))
        return acceptance_exit(summary['status'])
    if args.action == 'review':
        system.review(args.run, args.case, args.decision, args.note); return 0
    if args.action == 'compare':
        result = system.compare_runs(args.baseline, args.candidate)
        system.write(args.out, result)
        if result['regressions'] or result['removed_coverage']:
            return 1
        return 3 if any(r['comparison'].startswith('not_comparable') for r in result['cases']) else 0
    if args.action in {'status', 'export-status'}:
        summary = json.loads((args.run / 'summary.json').read_text())
        if args.action == 'export-status':
            system.write(args.out, system.public_status(summary))
        else:
            print(json.dumps({'status':summary['status'], 'counts':summary['counts'],
                              'cases':[{k:r.get(k) for k in ('id','status','visual_review','reason')} for r in summary['cases']]}, indent=2))
        return 0
    if args.action == 'reconcile':
        path = system.PROJECT / 'validation/runs/.system-validation.lock'
        # Take the same OS lock before replacing metadata. Never unlock a live runner.
        with path.open('a+b') as stream:
            system.acquire(stream, blocking=False)
            try:
                stream.seek(0); previous = stream.read()
                if previous:
                    system.write(path.with_name('.system-validation-reconciled.json'), json.loads(previous))
                stream.seek(0); stream.truncate(); stream.write(b'{"unresolved_worker":false}'); stream.flush()
            finally:
                system.release(stream)
        print('Runner lock reconciled. Interrupted case records remain interrupted; use a new run after review.'); return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError) as error:
        print('Validation stopped: ' + str(error), file=sys.stderr)
        raise SystemExit(2)
