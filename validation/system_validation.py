"""Local, sequential validation orchestration; no LLM, shell or network client.

Suite files are trusted operator configuration, not downloaded executable data.
The runner is not an OS/network sandbox for configured command adapters.
"""
from __future__ import annotations

from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timezone
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / 'libexec'))
from docking_universal.file_lock import acquire, release

SCHEMA = 'docking-universal-validation-v1'
LAYERS = {'regression', 'workflow', 'scientific', 'presentation', 'boundary'}
ENGINES = {'vina', 'qvinaw', 'adgpu'}
ID = re.compile(r'^[a-z0-9][a-z0-9_-]{0,79}$')


def now():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


def read_suite(path):
    path = Path(path).resolve()
    suite = json.loads(path.read_text())
    if suite.get('schema') != SCHEMA or not isinstance(suite.get('cases'), list) or not suite['cases']:
        raise ValueError('Invalid or empty validation suite')
    profile = suite.get('profile', {})
    if not isinstance(profile, dict) or not isinstance(profile.get('python'), str):
        raise ValueError('A Python runtime profile is required')
    seen = set()
    for case in suite['cases']:
        key = case.get('id', '')
        if not ID.fullmatch(key) or key in seen:
            raise ValueError('Case IDs must be unique safe directory names')
        seen.add(key)
        if case.get('layer') not in LAYERS or case.get('driver') not in {'unittest', 'command', 'screen_gui'}:
            raise ValueError('Unknown layer/driver in ' + key)
        if case.get('engine') is not None and case['engine'] not in ENGINES:
            raise ValueError('Unknown engine in ' + key)
        timeout = case.get('timeout_seconds', 1800)
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('Case timeout must be positive')
        if case.get('expected', 'success') not in {'success', 'rejection'}:
            raise ValueError('Unknown expected outcome')
        if case.get('expected') == 'rejection' and not case.get('checks'):
            raise ValueError('Expected rejection requires a specific evidence assertion')
        for name, item in case.get('inputs', {}).items():
            if not ID.fullmatch(name) or not isinstance(item, dict) or not isinstance(item.get('path'), str):
                raise ValueError('Invalid pinned input')
            if not re.fullmatch('[0-9a-f]{64}', item.get('sha256', '')):
                raise ValueError('Inputs require SHA256 pins')
        for check in case.get('checks', []):
            if check.get('kind') not in {'file', 'json', 'csv', 'pdf'}:
                raise ValueError('Unknown artifact check')
            relative = Path(check.get('path', ''))
            if not str(relative) or relative.is_absolute() or '..' in relative.parts:
                raise ValueError('Assertions must address case-local artifacts')
        if case['driver'] == 'command' and case.get('argv') and not case.get('checks'):
            raise ValueError('Command adapters require explicit evidence checks, not exit-code-only acceptance')
    return suite


def input_hashes(case):
    values = {}
    for name, item in case.get('inputs', {}).items():
        path = Path(item['path']).expanduser().resolve()
        if not path.is_file():
            raise ValueError('Missing input: ' + name)
        actual = sha(path)
        if actual != item['sha256']:
            raise ValueError('Changed pinned input: ' + name)
        values[name] = {'path': str(path), 'sha256': actual}
    return values


def resolve_artifact(root, relative):
    root = Path(root).resolve()
    target = (root / relative).resolve()
    if root not in target.parents:
        raise ValueError('Artifact escapes case directory')
    return target


def pointer(value, keys):
    for key in keys:
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def assert_artifacts(case, root):
    evidence = []
    for check in case.get('checks', []):
        path = resolve_artifact(root, check['path'])
        if not path.is_file() or path.stat().st_size < check.get('min_bytes', 1):
            raise ValueError('Missing/empty artifact: ' + check['path'])
        if check['kind'] == 'json':
            value = pointer(json.loads(path.read_text()), check.get('keys', []))
            if value != check['equals']:
                raise ValueError('JSON evidence mismatch: ' + check['path'])
        elif check['kind'] == 'csv':
            with path.open(newline='') as stream:
                reader = csv.DictReader(stream)
                if not set(check.get('columns', [])).issubset(reader.fieldnames or []):
                    raise ValueError('CSV columns missing: ' + check['path'])
                if sum(1 for _ in reader) < check.get('min_rows', 1):
                    raise ValueError('CSV rows missing: ' + check['path'])
        elif check['kind'] == 'pdf' and not path.read_bytes().startswith(b'%PDF-'):
            raise ValueError('Invalid PDF header: ' + check['path'])
        evidence.append({'path': check['path'], 'sha256': sha(path)})
    return evidence


def recovery_metrics(path, expected_seeds, group_fields=('arm',), threshold=2.0):
    """Experimental, receptor-frame RMSD only; never Vina's internal RMSD.

    Consume per-pose comparisons, not preselected minima or clusters. The
    lowest-energy pose is primary. Report energy ties as an RMSD interval;
    never resolve equal energies by picking the closest experimental pose.
    """
    expected = {int(v) for v in expected_seeds}
    if (not expected or len(expected) != len(expected_seeds) or min(expected) <= 0
            or not math.isfinite(threshold) or threshold <= 0):
        raise ValueError('Declared seeds and positive recovery threshold required')
    groups = {}
    with Path(path).open(newline='') as stream:
        reader = csv.DictReader(stream)
        required = {'seed', 'affinity_kcal_per_mol', 'crystal_rmsd_angstrom', *group_fields}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError('Per-pose experimental comparison columns are required')
        for row in reader:
            seed = int(row['seed'])
            energy, rmsd = float(row['affinity_kcal_per_mol']), float(row['crystal_rmsd_angstrom'])
            if seed not in expected or not math.isfinite(energy) or not math.isfinite(rmsd) or rmsd < 0:
                raise ValueError('Unexpected seed or invalid energy/experimental RMSD')
            group = tuple(row[k] for k in group_fields)
            groups.setdefault(group, {}).setdefault(seed, []).append((energy, rmsd))
    if not groups or any(set(rows) != expected for rows in groups.values()):
        raise ValueError('Missing matched seeds; partial scientific comparison is not complete')
    result = []
    for group, seeds in sorted(groups.items()):
        rows = []
        for seed, poses in sorted(seeds.items()):
            lowest = min(p[0] for p in poses)
            tied = [r for e, r in poses if e == lowest]
            rows.append({'seed': seed, 'pose_count': len(poses), 'lowest_energy_kcal_mol': lowest,
                         'lowest_energy_rmsd_min_angstrom': min(tied), 'lowest_energy_rmsd_max_angstrom': max(tied),
                         'lowest_energy_tie_count': len(tied),
                         'recovered_all_lowest_energy_ties': max(tied) <= threshold,
                         'recovered_any_lowest_energy_tie': min(tied) <= threshold,
                         'secondary_best_of_poses_rmsd_angstrom': min(r for _, r in poses)})
        result.append({'group': dict(zip(group_fields, group)), 'seeds': rows,
                       'recovery_threshold_angstrom': threshold,
                       'primary_recovery_all_ties': sum(r['recovered_all_lowest_energy_ties'] for r in rows),
                       'primary_recovery_any_tie': sum(r['recovered_any_lowest_energy_tie'] for r in rows),
                       'seed_count': len(rows)})
    return result


def runtime_identity(suite):
    profile = suite['profile']
    roots = [PROJECT / 'validation', PROJECT / 'libexec', PROJECT / 'tests', PROJECT / 'bin']
    files = {}
    def code_paths(root, omitted):
        for folder, directories, names in os.walk(root):
            directories[:] = [name for name in directories if name not in omitted]
            for name in names:
                path = Path(folder) / name
                if path.suffix in {'', '.py', '.sh', '.json', '.js', '.mjs', '.cjs'} and path.is_file():
                    yield path
    for root in roots:
        for path in code_paths(root, {'runs', 'local', '__pycache__', 'node_modules'}):
            files[str(path)] = sha(path)
    runtime = profile.get('runtime')
    if runtime and Path(runtime).is_dir():
        for path in code_paths(Path(runtime), {'node_modules', '__pycache__'}):
            files[str(path.resolve())] = sha(path)
    for name in ('python', 'gui_python', 'scientific_python', 'cli'):
        path = profile.get(name)
        if path and Path(path).is_file():
            files[str(Path(path).resolve())] = sha(Path(path).resolve())
    for name, path in profile.get('identity_files', {}).items():
        files[str(Path(path).resolve())] = sha(Path(path))
    # Detect chemistry/renderer package upgrades even when Python and the
    # application executable are unchanged. Read metadata, never import/solve
    # packages or retain an environment-variable dump.
    package_metadata = {}
    prefixes = set()
    for key in ('python', 'scientific_python', 'gui_python'):
        raw = profile.get(key)
        if raw:
            prefixes.update((Path(raw).expanduser().parent.parent, Path(raw).expanduser().resolve().parent.parent))
    for prefix in prefixes:
        for pattern in ('conda-meta/*.json', 'lib/python*/site-packages/*.dist-info/METADATA',
                        'Lib/site-packages/*.dist-info/METADATA', 'lib/python*/site-packages/*.egg-info/PKG-INFO'):
            for path in prefix.glob(pattern):
                if path.is_file():
                    package_metadata[str(path.resolve())] = sha(path)
    return {'platform': platform.system(), 'architecture': platform.machine(),
            'hardware': {'logical_cpus': os.cpu_count(), 'processor': platform.processor(), 'os_release': platform.release()},
            'profile': profile, 'code_files': files, 'package_metadata': package_metadata,
            'fingerprint': fingerprint({'code':files,'packages':package_metadata})}


def protected_hashes(suite):
    files = set()
    for raw in suite['profile'].get('protected_paths', []):
        path = Path(raw).expanduser().resolve()
        if path.is_dir():
            files.update(p for p in path.rglob('*') if p.is_file())
        else:
            files.add(path)
    return {str(p): sha(p) if p.is_file() else None for p in sorted(files)}


def check_protected(before):
    for path, expected in before.items():
        actual = sha(path) if Path(path).is_file() else None
        if actual != expected:
            raise ValueError('Protected file changed: ' + path)


def readiness(case, profile):
    if case.get('excluded_reason'):
        return 'excluded', case['excluded_reason']
    if not set(case.get('requires', [])).issubset(profile.get('capabilities', [])):
        return 'blocked', 'Required runtime/hardware capability not declared'
    try:
        input_hashes(case)
        if case['driver'] == 'unittest':
            if not case.get('modules'):
                raise ValueError('No regression modules configured')
        elif case['driver'] == 'command':
            if not case.get('argv') or not case.get('checks'):
                raise ValueError('Adapter command/evidence not bound')
        else:
            if not {'protocol', 'ligands'}.issubset(case.get('inputs', {})):
                raise ValueError('Reviewed protocol and local ligand library not bound')
            if not case.get('import_review_approved'):
                raise ValueError('Explicit protocol-import review required')
            if not all(profile.get(k) for k in ('runtime', 'gui_python', 'scientific_python', 'cli')):
                raise ValueError('Complete installed GUI/scientific profile required')
            if not profile.get('study_roots'):
                raise ValueError('Configure original study roots for the active-job guard before GUI execution')
            engine_binary = profile.get('identity_files', {}).get(case.get('engine'))
            if not engine_binary or not Path(engine_binary).is_file():
                raise ValueError('Pin the actual engine executable in profile.identity_files before GUI execution')
        executable = profile.get('gui_python') if case['driver'] == 'screen_gui' else profile['python']
        if not executable or not Path(executable).is_file():
            raise ValueError('Selected Python runtime is unavailable')
    except (ValueError, OSError) as exc:
        return 'blocked', str(exc)
    return 'ready', ''


def command(case, suite, out):
    profile = suite['profile']
    variables = {'project': str(PROJECT), 'out': str(out), **profile,
                 **{k: v['path'] for k, v in case.get('inputs', {}).items()}}
    if case['driver'] == 'unittest':
        return [profile['python'], '-m', 'unittest', '-v', *case['modules']]
    if case['driver'] == 'screen_gui':
        return [profile['gui_python'], str(PROJECT / 'validation/system_gui_worker.py'),
                '--case', str(out / 'case-input.json'), '--out', str(out / 'worker'),
                '--runtime', profile['runtime'], '--scientific-python', profile['scientific_python'], '--cli', profile['cli']]
    return [str(value).format_map(variables) for value in case['argv']]


def inventory(root):
    result = {}
    for path in sorted(Path(root).rglob('*')):
        if path.is_file() and path.name != 'case-result.json':
            relative = str(path.relative_to(root))
            resolve_artifact(root, relative)
            result[relative] = sha(path)
    return result


def verify_saved(row, run):
    root = resolve_artifact(run, row['directory'])
    for relative, expected in row.get('inventory', {}).items():
        if sha(resolve_artifact(root, relative)) != expected:
            raise ValueError('Completed evidence changed; do not reuse: ' + row['id'])
    if not row.get('inventory'):
        raise ValueError('Completed case lacks retained evidence')


def aggregate(cases):
    counts = Counter(c['status'] for c in cases)
    if counts['interrupted']:
        status = 'attention_required'
    elif counts['running']:
        status = 'running'
    elif counts['failed'] or any(c.get('visual_review') == 'failed' for c in cases):
        status = 'failed'
    elif counts['blocked'] or counts['not_run']:
        status = 'incomplete'
    elif any(c['status'] == 'passed' and c.get('visual_review') == 'pending' for c in cases):
        status = 'needs_visual_review'
    else:
        status = 'passed' if counts['passed'] else 'no_coverage'
    return status, dict(counts)


def save_summary(run, summary):
    summary['status'], summary['counts'] = aggregate(summary['cases'])
    summary['updated_utc'] = now()
    write(run / 'summary.json', summary)
    lines = ['# Local validation results', '', 'Status: ' + summary['status'], '',
             '| Case | Layer | Engine | Status | Visual review | Seconds |',
             '| --- | --- | --- | --- | --- | --- |']
    for row in summary['cases']:
        lines.append('| ' + ' | '.join(str(row.get(k, '—')) for k in
                     ('id', 'layer', 'engine', 'status', 'visual_review', 'elapsed_seconds')) + ' |')
    lines += ['', 'Missing, excluded and unreviewed cases are not passes. Scientific metrics stay local.', '']
    (run / 'results.md').write_text('\n'.join(lines))


@contextmanager
def suite_lock(path):
    """Cross-platform exclusive runner lock; unresolved workers block new work."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        acquire(handle, blocking=False)
        try:
            handle.seek(0)
            raw = handle.read()
            previous = json.loads(raw) if raw else {}
            if previous.get('unresolved_worker'):
                raise ValueError('An interrupted worker requires explicit reconciliation before new work: ' + str(path))
            def update(value):
                handle.seek(0); handle.truncate()
                handle.write(json.dumps(value).encode()); handle.flush(); os.fsync(handle.fileno())
            yield update
        finally:
            release(handle)


def idle_guard(suite):
    for raw in suite['profile'].get('study_roots', []):
        for path in Path(raw).expanduser().glob('*/application_state.json'):
            state = json.loads(path.read_text())
            jobs = state.get('jobs', [])
            if isinstance(jobs, dict):
                jobs = jobs.values()
            if any(j.get('status') in {'running', 'queued'} for j in jobs):
                raise ValueError('Another scientific study is active; sequential validation not launched')


def run_suite(suite, out, *, layers=None, resume=False, retry=(), execute=False, lock_path=None):
    if not execute:
        raise ValueError('Execution requires --execute; use plan first')
    out = Path(out).resolve()
    for raw in suite['profile'].get('protected_paths', []):
        path = Path(raw).expanduser().resolve()
        if path == out or path in out.parents:
            raise ValueError('Validation output must not be inside protected studies/data')
    identity = runtime_identity(suite)
    run_key = fingerprint({'suite': suite, 'identity': identity})
    if out.exists() and not resume:
        raise ValueError('Run exists; explicit resume or a new directory is required')
    if resume:
        summary = json.loads((out / 'summary.json').read_text())
        if summary['fingerprint'] != run_key:
            raise ValueError('Suite, inputs or runtime/code changed; use a new run')
    else:
        out.mkdir(parents=True, exist_ok=False)
        summary = {'schema': SCHEMA, 'name': suite.get('name', 'Validation'), 'started_utc': now(),
                   'fingerprint': run_key, 'identity': identity,
                   'cases': [{'id': c['id'], 'layer':c['layer'], 'engine':c.get('engine'), 'status':'not_run'}
                             for c in suite['cases']], 'attempts': [],
                   'lock_path': str(Path(lock_path or PROJECT / 'validation/runs/.system-validation.lock').resolve())}
        write(out / 'suite.json', suite)
    selected = [c for c in suite['cases'] if not layers or c['layer'] in layers]
    if not selected:
        raise ValueError('No cases selected')
    if set(retry) - {c['id'] for c in selected}:
        raise ValueError('Retry IDs must belong to selected cases')
    with suite_lock(lock_path or PROJECT / 'validation/runs/.system-validation.lock') as owner:
        protection = summary.setdefault('protected_files', protected_hashes(suite))
        check_protected(protection)
        for case in selected:
            prior = next((r for r in summary['cases'] if r['id'] == case['id']), None)
            if case['id'] in retry and (not prior or prior['status'] != 'failed'):
                raise ValueError('Only an explicitly failed case can be retried')
            if prior and prior['status'] == 'passed':
                verify_saved(prior, out)
                if prior['id'] in retry:
                    raise ValueError('Completed cases cannot be retried in this run')
                continue
            if prior and prior['status'] in {'running', 'interrupted'}:
                raise ValueError('Interrupted case requires operator reconciliation; never restarted automatically')
            if prior and prior['status'] == 'failed' and case['id'] not in retry:
                continue
            row = {'id': case['id'], 'layer': case['layer'], 'engine': case.get('engine'),
                   'target': case.get('target'), 'status': 'not_run',
                   'execution_contract': fingerprint({k:case.get(k) for k in
                       ('driver','argv','modules','expected','expected_exit','experimental_metrics','max_jobs')}),
                   'visual_review': 'pending' if case.get('visual_review_required') else 'not_required'}
            if prior:
                if prior.get('directory'):
                    summary['attempts'].append(dict(prior))
                summary['cases'].remove(prior)
            summary['cases'].append(row)
            ready, reason = readiness(case, suite['profile'])
            if ready != 'ready':
                row.update(status=ready, reason=reason)
                save_summary(out, summary)
                continue
            if case.get('network_required'):
                row.update(status='blocked', reason='Network-dependent adapter requires separately approved setup outside this local runner')
                save_summary(out, summary)
                continue
            if case['driver'] != 'unittest':
                idle_guard(suite)
            before = input_hashes(case)
            attempt = 1 + sum(r['id'] == case['id'] for r in summary['attempts'])
            directory = out / case['id'] / ('attempt-%03d' % attempt)
            directory.mkdir(parents=True, exist_ok=False)
            write(directory / 'case-input.json', case)
            row.update(status='running', started_utc=now(), directory=str(directory.relative_to(out)), inputs=before)
            save_summary(out, summary)
            environment = dict(os.environ)
            environment.update(suite['profile'].get('environment', {}))
            environment['PYTHONPATH'] = os.pathsep.join([str(PROJECT / 'libexec'), str(PROJECT / 'tests')])
            if case['driver'] == 'unittest':
                environment['QT_QPA_PLATFORM'] = 'offscreen'
            environment['MPLCONFIGDIR'] = str(directory / 'matplotlib')
            started = time.monotonic()
            process = None
            interrupted = False
            try:
                argv = command(case, suite, directory)
                row['command'] = argv
                with (directory / 'worker.log').open('w') as log:
                    process = subprocess.Popen(argv, cwd=PROJECT, env=environment, stdout=log,
                                               stderr=subprocess.STDOUT, start_new_session=(os.name != 'nt'))
                    owner({'unresolved_worker': True, 'runner_pid': os.getpid(), 'worker_pid': process.pid,
                           'run': str(out), 'case': case['id'], 'started_utc': now()})
                    row['worker_pid'] = process.pid
                    while process.poll() is None:
                        row['elapsed_seconds'] = round(time.monotonic() - started, 2)
                        save_summary(out, summary)
                        if time.monotonic() - started > case.get('timeout_seconds', 1800):
                            interrupted = True
                            raise TimeoutError('Worker deadline exceeded; check detached scientific jobs before any retry')
                        time.sleep(.5)
                row['returncode'] = process.returncode
                if case['driver'] == 'screen_gui':
                    receipt = directory / 'worker/summary.json'
                    try:
                        worker = json.loads(receipt.read_text())
                    except (OSError, json.JSONDecodeError):
                        interrupted = True
                        raise ValueError('GUI worker exited without a valid completion/cleanup receipt; reconcile before continuing')
                    if worker.get('status') not in {'passed', 'failed', 'blocked'} or worker.get('active_job_after_cleanup'):
                        interrupted = True
                        raise ValueError('Worker could not confirm scientific-job cleanup; reconcile before continuing')
                    if process.returncode == 3 and worker.get('status') == 'blocked':
                        row.update(status='blocked', reason=worker.get('reason', 'GUI preflight blocked'), inventory=inventory(directory))
                        continue
                if process.returncode != case.get('expected_exit', 0):
                    if case['driver'] != 'unittest':
                        interrupted = True
                    raise ValueError('Unexpected worker exit; inspect retained local log')
                evidence = assert_artifacts(case, directory)
                if case['driver'] == 'unittest':
                    text = (directory / 'worker.log').read_text(errors='replace')
                    match = re.search(r'Ran (\d+) tests?', text)
                    if not match or int(match[1]) == 0 or not re.search(r'^OK(?:\s|$)', text, re.M):
                        raise ValueError('Regression worker did not prove nonempty successful discovery')
                    row['test_count'] = int(match[1])
                    skipped = re.search(r'skipped=(\d+)', text)
                    row['skipped_test_count'] = int(skipped[1]) if skipped else 0
                    if row['skipped_test_count'] >= row['test_count']:
                        raise ValueError('All regression cases skipped; no executed coverage')
                if case.get('experimental_metrics'):
                    config = case['experimental_metrics']
                    if config.get('coordinate_basis') != 'experimental-receptor-frame-no-fit':
                        raise ValueError('Experimental RMSD basis must be explicit')
                    row['scientific_metrics'] = recovery_metrics(resolve_artifact(directory, config['path']),
                        config['seeds'], tuple(config.get('groups', ['arm'])), config.get('threshold_angstrom', 2.0))
                    if config.get('expected_groups') is not None:
                        actual = sorted(fingerprint(v['group']) for v in row['scientific_metrics'])
                        if actual != sorted(fingerprint(v) for v in config['expected_groups']):
                            raise ValueError('Declared scientific comparison group is missing or changed')
                    for group in row['scientific_metrics']:
                        minimum = config.get('minimum_recovered_seeds')
                        if minimum is not None and group['primary_recovery_all_ties'] < minimum:
                            raise ValueError('Predeclared lowest-energy experimental recovery criterion not met')
                if before != input_hashes(case):
                    raise ValueError('Pinned inputs changed during execution')
                check_protected(protection)
                row.update(status='passed', evidence=evidence, inventory=inventory(directory))
            except BaseException as exc:
                if isinstance(exc, (KeyboardInterrupt, TimeoutError)):
                    interrupted = True
                if process is not None and process.poll() is None:
                    interrupted = True
                    process.terminate()
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait(timeout=5)
                row.update(status='interrupted' if interrupted else 'failed', reason=str(exc))
                if isinstance(exc, KeyboardInterrupt):
                    raise
            finally:
                row.update(finished_utc=now(), elapsed_seconds=round(time.monotonic() - started, 2))
                write(directory / 'case-result.json', row)
                save_summary(out, summary)
                if not interrupted:
                    owner({'unresolved_worker': False, 'finished_utc': now()})
            if interrupted:
                break
        known = {r['id'] for r in summary['cases']}
        for case in suite['cases']:
            if case['id'] not in known:
                summary['cases'].append({'id': case['id'], 'layer': case['layer'], 'engine': case.get('engine'),
                                         'status': 'not_run', 'reason': 'Not selected or execution stopped'})
        check_protected(protection)
        save_summary(out, summary)
    return summary


def review(run, case_id, decision, note):
    if decision not in {'passed', 'failed'} or not note.strip():
        raise ValueError('Review requires pass/fail and a substantive note')
    run = Path(run).resolve()
    snapshot = json.loads((run / 'summary.json').read_text())
    with suite_lock(snapshot['lock_path']):
        summary = json.loads((run / 'summary.json').read_text())
        row = next(r for r in summary['cases'] if r['id'] == case_id)
        if row['status'] != 'passed' or row.get('visual_review') == 'not_required':
            raise ValueError('Only a completed case requiring visual review can be reviewed')
        verify_saved(row, run)
        row.update(visual_review=decision, review_note=note, reviewed_utc=now())
        save_summary(run, summary)


def public_status(summary):
    """Only anonymous counts, never targets/paths/logs/hashes or scientific values."""
    return {'schema': SCHEMA + '-status', 'status': summary['status'],
            'counts': dict(Counter(row['status'] for row in summary['cases'])),
            'layers': {layer: dict(Counter(r['status'] for r in summary['cases'] if r['layer'] == layer))
                       for layer in sorted(LAYERS)}}


def compare_runs(baseline, candidate):
    """Local regression comparison; never mix changed inputs or engine identities."""
    paths = [Path(p).resolve() for p in (baseline, candidate)]
    summaries = [json.loads((p / 'summary.json').read_text()) for p in paths]
    maps = [{r['id']: r for r in value['cases']} for value in summaries]
    rows = []
    for key in sorted(set(maps[0]) | set(maps[1])):
        old, new = maps[0].get(key), maps[1].get(key)
        item = {'id': key, 'baseline': old['status'] if old else 'absent', 'candidate': new['status'] if new else 'absent'}
        if old is None or new is None:
            item['comparison'] = 'new_coverage' if old is None else 'removed_coverage'
        elif old.get('engine') != new.get('engine') or old.get('execution_contract') != new.get('execution_contract') or {
                k: v['sha256'] for k, v in old.get('inputs', {}).items()} != {
                k: v['sha256'] for k, v in new.get('inputs', {}).items()}:
            item['comparison'] = 'not_comparable_changed_engine_inputs_or_execution_contract'
        else:
            for row, root in ((old, paths[0]), (new, paths[1])):
                if row['status'] == 'passed':
                    verify_saved(row, root)
            item['comparison'] = 'regression' if old['status'] == 'passed' and new['status'] != 'passed' else 'comparable'
            item['visual_baseline'] = old.get('visual_review')
            item['visual_candidate'] = new.get('visual_review')
            if old.get('visual_review') == 'passed' and new.get('visual_review') == 'failed':
                item['comparison'] = 'regression'
            if 'elapsed_seconds' in old and 'elapsed_seconds' in new:
                item['descriptive_elapsed_delta_seconds'] = new['elapsed_seconds'] - old['elapsed_seconds']
            before = {fingerprint(g['group']): g for g in old.get('scientific_metrics', [])}
            after = {fingerprint(g['group']): g for g in new.get('scientific_metrics', [])}
            if before or after:
                matched = set(before) == set(after) and all(
                    [r['seed'] for r in before[g]['seeds']] == [r['seed'] for r in after[g]['seeds']]
                    and before[g]['recovery_threshold_angstrom'] == after[g]['recovery_threshold_angstrom'] for g in before)
                item['scientific_comparison'] = 'matched' if matched else 'not_comparable_changed_groups_seeds_or_threshold'
                if matched:
                    item['primary_recovery_all_ties_delta'] = {
                        g: after[g]['primary_recovery_all_ties'] - before[g]['primary_recovery_all_ties'] for g in before}
        rows.append(item)
    return {'schema': SCHEMA + '-comparison', 'cases': rows,
            'regressions': sum(r['comparison'] == 'regression' for r in rows),
            'removed_coverage': sum(r['comparison'] == 'removed_coverage' for r in rows),
            'timing_caution': 'Descriptive only; runtime/hardware/search settings must be matched before any speed claim.'}
