"""Isolated Mac throughput pilot; no preparation or production scheduler changes."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'libexec'))
from docking_universal.vina_batch import digest, save

LAYOUTS = ((1, 8), (2, 4), (4, 2))
ACTIVE = {'running', 'queued'}


def check_idle(state_root):
    """Waiting for an unsubmitted user decision is not an active calculation."""
    paths = list(Path(state_root).glob('*/application_state.json'))
    if not paths:
        raise ValueError('No study state files found for the active-calculation guard')
    for path in paths:
        state = json.loads(path.read_text())
        if any(job['status'] in ACTIVE for job in state.get('jobs', [])):
            raise RuntimeError('Another GUI calculation is active: ' + path.parent.name)


def build_tasks(config, all_seeds=False):
    seeds = config['parameters']['seeds'] if all_seeds else config['parameters']['seeds'][:2]
    if len(seeds) < 2 or len(set(seeds)) != len(seeds):
        raise ValueError('At least two distinct retained seeds are required')
    tasks = []
    for seed in seeds:
        for compound in config['compounds']:
            inputs = [Path(p) for p in compound['prepared']]
            if len(inputs) != 3 or len({p.parent for p in inputs}) != 1:
                raise ValueError('Expected three prepared conformers in one directory')
            if set(inputs[0].parent.glob('*.pdbqt')) != set(inputs):
                raise ValueError('Prepared directory includes unexpected PDBQT inputs')
            tasks.append(dict(compound=compound['id'], seed=seed,
                              ligands=str(inputs[0].parent), inputs=list(map(str, inputs))))
    if len(tasks) != 2 * len(seeds):
        raise ValueError('This pilot requires exactly two compounds')
    return tasks


def command(config, task, folder, cpu, libexec, python, engine):
    params = config['parameters']
    return [str(python), '-u', str(libexec / 'docking-universal-dock'),
            '--engine-command', str(engine), '--vina-backend', 'api',
            '--receptor', config['receptor'], '--config', config['box'],
            '--ligands', task['ligands'], '--out', str(folder),
            '--cpu', str(cpu), '--seed', str(task['seed']),
            '--exhaustiveness', str(params['exhaustiveness']),
            '--num-modes', str(params['num_modes']),
            '--energy-range', str(params['energy_range_kcal_per_mol'])]


def validate_batch(config, task, folder, cpu):
    record = json.loads((folder / 'batch_execution.json').read_text())
    jobs = record.get('jobs', [])
    if (record['status'] != 'completed' or len(jobs) != 3 or record['map_builds'] != 1
            or record['parameters']['cpu'] != cpu or record['parameters']['seed'] != task['seed']
            or record['no_refine'] is not False
            or {j['ligand'] for j in jobs} != set(task['inputs'])):
        raise ValueError('Incomplete or unexpected API batch: ' + str(folder))
    comparisons = []
    for job in jobs:
        output = Path(job['output'])
        lines = output.read_text().splitlines()
        poses = sum(line.startswith('MODEL ') for line in lines)
        if (job['status'] != 'completed' or not poses
                or poses != sum(line.strip() == 'ENDMDL' for line in lines)
                or poses != sum(line.startswith('REMARK VINA RESULT:') for line in lines)):
            raise ValueError('Incomplete scored output: ' + str(output))
        reference = (Path(config['baseline']) / 'compounds' / task['compound'] /
                     f"seed_{task['seed']}" / 'docking' / output.name)
        comparisons.append(dict(output=str(output), reference=str(reference),
                                poses=poses, byte_identical=digest(output) == digest(reference)))
    return dict(comparisons=comparisons, execution_record=str(folder / 'batch_execution.json'),
                search_seconds=sum(j['search_seconds'] for j in jobs))


def terminate(process):
    if process.poll() is None:
        if os.name == 'nt':
            process.terminate()
        else:
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            if os.name == 'nt':
                process.kill()
            else:
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def run_arm(config, tasks, arm, workers, cpu, libexec, python, engine, state_root):
    if workers * cpu != 8 or (workers, cpu) not in LAYOUTS:
        raise ValueError('Pilot layouts must cap docking-search threads at eight')
    arm.mkdir()
    row = dict(status='running', workers=workers, threads_per_worker=cpu,
               max_simultaneous_search_threads=workers * cpu, batches=[])
    pending, active = list(tasks), []
    start = time.perf_counter()
    last_guard = -float('inf')
    try:
        while pending or active:
            if time.perf_counter() - last_guard >= 2:
                check_idle(state_root)
                last_guard = time.perf_counter()
            while pending and len(active) < workers:
                task = pending.pop(0)
                folder = arm / task['compound'] / f"seed_{task['seed']}"
                folder.mkdir(parents=True)
                cmd = command(config, task, folder, cpu, libexec, python, engine)
                log = (folder / 'dispatcher.log').open('w')
                try:
                    process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, 'PYTHONPATH': str(libexec)},
                        start_new_session=os.name != 'nt')
                except BaseException:
                    log.close()
                    raise
                item = dict(compound=task['compound'], seed=task['seed'], status='running',
                            pid=process.pid, command=cmd, directory=str(folder))
                row['batches'].append(item)
                active.append((process, log, item, task, time.perf_counter()))
            save(arm / 'execution.json', row)
            for entry in list(active):
                process, log, item, task, launched = entry
                code = process.poll()
                if code is None:
                    continue
                log.close()
                item.update(returncode=code, wall_seconds=time.perf_counter()-launched)
                if code:
                    item['status'] = 'failed'
                    raise RuntimeError('Docking batch failed; see ' + item['directory'] + '/dispatcher.log')
                item.update(validate_batch(config, task, Path(item['directory']), cpu), status='completed')
                active.remove(entry)
            if active:
                time.sleep(0.25)
        row.update(status='completed', wall_seconds=time.perf_counter()-start)
        comparisons = [c for b in row['batches'] for c in b['comparisons']]
        row.update(output_files=len(comparisons),
                   byte_identical_outputs=sum(c['byte_identical'] for c in comparisons))
        if row['output_files'] != 3 * len(tasks):
            raise ValueError('Wrong total completed output count')
        return row
    except BaseException as exc:
        row.update(status='failed', error=str(exc), wall_seconds=time.perf_counter()-start)
        raise
    finally:
        for process, log, item, *_ in active:
            terminate(process)
            log.close()
            if item['status'] == 'running':
                item['status'] = 'stopped_after_pilot_failure'
        save(arm / 'execution.json', row)


def summarize(arms, repeats=2):
    result = {}
    for workers, cpu in LAYOUTS:
        rows = [r for r in arms if r['workers'] == workers and r['status'] == 'completed']
        if len(rows) != repeats:
            raise ValueError(f'Each layout needs {repeats} completed repeats')
        key = f'{workers}x{cpu}'
        result[key] = dict(median_wall_seconds=statistics.median(r['wall_seconds'] for r in rows),
                           repeats=len(rows), output_files=sum(r['output_files'] for r in rows),
                           byte_identical_outputs=sum(r['byte_identical_outputs'] for r in rows))
    baseline = result['1x8']['median_wall_seconds']
    for value in result.values():
        value['throughput_speedup_vs_1x8'] = baseline / value['median_wall_seconds']
    return result


def main():
    def interrupted(_signal, _frame):
        raise InterruptedError('Pilot interrupted; stopping its child process groups')
    signal.signal(signal.SIGTERM, interrupted)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--state-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--all-seeds', action='store_true', help='Use every retained seed, not the first two')
    parser.add_argument('--repeats', type=int, choices=(1, 2), default=2,
                        help='One full-workload pass or two reversed-order pilot repeats')
    parser.add_argument('--libexec', type=Path, default=Path('/opt/anaconda3/envs/docking-universal/libexec/docking-universal'))
    parser.add_argument('--python', type=Path, default=Path('/opt/anaconda3/envs/docking-universal/bin/python'))
    parser.add_argument('--engine', type=Path, default=Path('/opt/anaconda3/envs/docking-universal-vina/bin/vina'))
    args = parser.parse_args()
    check_idle(args.state_root)
    args.output.mkdir(parents=True, exist_ok=False)  # Exclusive: never silently resume/restart.
    summary = dict(status='preflight', pid=os.getpid(), started_at=datetime.now(timezone.utc).isoformat(),
                   arms=[], layouts={}, limitations=[
                       'Two compounds, one receptor and three retained conformers per compound',
                       'Thermal/background activity is uncontrolled; this is a small timing experiment',
                       'Preparation reused; no PLIP, analysis or reports timed',
                       'Eight docking-search threads maximum, not CPU affinity or total OS thread count',
                       'Complete output equality is not experimental pose recovery',
                       'No production scheduling/default changes or automatic installation'])
    hashes = {}
    try:
        source = args.source / 'config.json'
        config = json.loads(source.read_text())
        hashes[str(source)] = digest(source)
        if digest(config['protocol_bundle']) != config['protocol_sha256']:
            raise ValueError('Retained protocol hash mismatch')
        hashes[config['protocol_bundle']] = config['protocol_sha256']
        for key in ('receptor', 'box', 'receptor_pdb'):
            hashes[config[key]] = digest(config[key])
        for compound in config['compounds']:
            for path, expected in compound['prepared_sha256'].items():
                if digest(path) != expected:
                    raise ValueError('Retained ligand hash mismatch: ' + path)
                hashes[path] = expected
        tasks = build_tasks(config, args.all_seeds)
        seeds = list(dict.fromkeys(t['seed'] for t in tasks))
        searches = 3 * len(tasks)
        summary.update(seeds=seeds, repeats=args.repeats, all_retained_seeds=args.all_seeds,
                       searches_per_arm=searches, planned_searches=searches * len(LAYOUTS) * args.repeats)
        summary['limitations'].append('One pass per layout, fixed layout/task order' if args.repeats == 1
                                      else 'Two repeats in reversed layout/task order')
        for task in tasks:
            for ligand in task['inputs']:
                reference = (Path(config['baseline']) / 'compounds' / task['compound'] /
                             f"seed_{task['seed']}" / 'docking' / (Path(ligand).stem + '_vina.pdbqt'))
                hashes[str(reference)] = digest(reference)
        for name in ('docking-universal-dock', 'docking_universal_dock.py',
                     'docking-universal-vina-batch.py', 'docking_universal/vina_batch.py'):
            hashes[str(args.libexec / name)] = digest(args.libexec / name)
        hashes[str(args.engine)] = digest(args.engine)
        hashes[str(Path(__file__).resolve())] = digest(Path(__file__).resolve())
        save(args.output / 'source_hashes.json', hashes)
        save(args.output / 'config.json', config)
        summary.update(status='running',
                       state_root=str(args.state_root), production_libexec=str(args.libexec))
        save(args.output / 'summary.json', summary)
        for repeat in range(args.repeats):
            layouts = LAYOUTS if repeat == 0 else tuple(reversed(LAYOUTS))
            for workers, cpu in layouts:
                arm = args.output / f'r{repeat+1}_{workers}x{cpu}'
                summary['current_arm'] = str(arm)
                save(args.output / 'summary.json', summary)
                print('Starting ' + arm.name, flush=True)
                row = run_arm(config, tasks if repeat == 0 else list(reversed(tasks)), arm,
                              workers, cpu, args.libexec, args.python, args.engine, args.state_root)
                row.update(repeat=repeat+1, directory=str(arm))
                summary['arms'].append(row)
                save(args.output / 'summary.json', summary)
                print(f"Completed {arm.name}: {row['wall_seconds']:.2f} s; "
                      f"{row['byte_identical_outputs']}/{searches} identical outputs", flush=True)
                if any(digest(p) != expected for p, expected in hashes.items()):
                    raise RuntimeError('An original input/reference or implementation changed')
        summary['layouts'] = summarize(summary['arms'], args.repeats)
        summary.update(status='completed' if all(r['byte_identical_outputs'] == searches for r in summary['arms'])
                       else 'completed_with_output_mismatches', originals_unchanged=True)
        summary.pop('current_arm', None)
    except BaseException as exc:
        summary.update(status='failed', error=str(exc))
        raise
    finally:
        summary['finished_at'] = datetime.now(timezone.utc).isoformat()
        save(args.output / 'summary.json', summary)


if __name__ == '__main__':
    main()
