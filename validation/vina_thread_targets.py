"""Repeated three-target CPU pilot, reusing exact retained prepared inputs."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--state-file', type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        raise ValueError('Output already exists; refusing duplicate/restart')
    state = json.loads(args.state_file.read_text())
    if any(j['status'] in ('queued', 'running', 'waiting_for_decision') for j in state['jobs']):
        raise ValueError('A scientific job is active')
    spec = importlib.util.spec_from_file_location('execution', Path(__file__).with_name('vina_execution_benchmark.py'))
    execution = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(execution)
    root = Path(__file__).resolve().parent / 'runs/conformer-ab'
    cases = [
        ('indinavir_protease', root / 'indinavir_2r5p_redocking_20261004_framechecked'),
        ('imatinib_abl', root / 'four_more_20261005_ready/imatinib_1iep/benchmark'),
        ('geldanamycin_hsp90', root / 'four_more_20261005_ready/geldanamycin_1yet/benchmark')]
    configs, hashes = {}, {}
    for name, source in cases:
        summary_path = source / 'summary.json'
        if json.loads(summary_path.read_text())['status'] != 'completed':
            raise ValueError('Source did not complete: ' + name)
        command_path = source / 'vacuum_pruned/dock_conf_01/seed_41001/vina.command.json'
        command = json.loads(command_path.read_text())
        options = {command[i]: command[i+1] for i in range(1, len(command), 2)}
        config = dict(receptor=options['--receptor'], geometry={},
            parameters=dict(seeds=[41001, 41002], exhaustiveness=16, num_modes=15, energy_range_kcal_per_mol=8),
            compounds=[dict(id=name, prepared=[options['--ligand']])])
        for line in Path(options['--config']).read_text().splitlines():
            if '=' in line:
                key, value = line.split('=', 1)
                if key.strip().startswith(('center_', 'size_')):
                    config['geometry'][key.strip()] = float(value.split('#')[0])
        for path in (summary_path, command_path, Path(options['--receptor']),
                     Path(options['--ligand']), Path(options['--config'])):
            hashes[str(path)] = execution.digest(path)
        configs[name] = config
    out.mkdir(parents=True)
    execution.save(out / 'source_hashes.json', hashes)
    for name, config in configs.items():
        execution.save(out / (name + '.json'), config)
    summary = dict(status='running', pid=os.getpid(), logical_cpus=os.cpu_count(), arms=[], cases={},
        limitations=['Three larger ligands/targets, one retained conformer and two matched seeds each',
            'Two repeats with varied order; thermal/background activity remains uncontrolled',
            'Preparation reused; no downstream analysis/report timing',
            'Same single chemical state and rigid receptor; no new scientific superiority claim',
            'The older geldanamycin retained conformer is reused; the later failed preparation was not rerun'])
    execution.save(out / 'summary.json', summary)
    try:
        for repeat in range(2):
            for index, (name, _) in enumerate(cases):
                order = [4, 8, 12]
                order = order[index:] + order[:index]
                if repeat:
                    order.reverse()
                for cpu in order:
                    arm = out / f'{name}_r{repeat+1}_cpu{cpu}'
                    arm.mkdir()
                    row = dict(case=name, repeat=repeat+1, cpu=cpu, status='running', directory=str(arm))
                    summary['arms'].append(row)
                    execution.save(out / 'summary.json', summary)
                    start = time.perf_counter()
                    try:
                        execution.worker(out / (name + '.json'), arm, cpu)
                        record = json.loads((arm / 'execution.json').read_text())
                        if record['status'] != 'completed' or len(record['jobs']) != 2:
                            raise ValueError('Incomplete worker output')
                        row.update(status='completed', worker_seconds=time.perf_counter()-start,
                                   search_seconds=sum(j['dock_seconds'] for j in record['jobs']))
                    except Exception as exc:
                        row.update(status='failed', error=str(exc))
                    execution.save(out / 'summary.json', summary)
        for name, _ in cases:
            rows = [r for r in summary['arms'] if r['case'] == name and r['status'] == 'completed']
            reference = {}
            comparisons = []
            for row in rows:
                record = json.loads((Path(row['directory']) / 'execution.json').read_text())
                for job in record['jobs']:
                    key = (job['seed'], job['ligand'])
                    digest = execution.digest(job['output'])
                    reference.setdefault(key, digest)
                    comparisons.append(digest == reference[key])
            summary['cases'][name] = dict(
                median_worker_seconds={str(cpu): statistics.median(r['worker_seconds'] for r in rows if r['cpu'] == cpu)
                                       for cpu in (4, 8, 12) if any(r['cpu'] == cpu for r in rows)},
                completed_arms=len(rows), compared_outputs=len(comparisons),
                byte_identical_across_threads_and_repeats=bool(comparisons) and all(comparisons))
        if any(execution.digest(p) != h for p, h in hashes.items()):
            raise ValueError('Retained source changed during pilot')
        summary.update(status='completed_with_failures' if any(r['status']=='failed' for r in summary['arms']) else 'completed',
                       original_inputs_unchanged=True)
    except BaseException as exc:
        summary.update(status='failed', error=str(exc))
        raise
    finally:
        execution.save(out / 'summary.json', summary)


if __name__ == '__main__':
    main()
