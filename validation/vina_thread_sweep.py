"""Small matched, sequential CPU-thread timing pilot; never changes defaults."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--state-file', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cpus', type=int, nargs='+', default=[12, 8, 10])
    args = parser.parse_args()
    if len(set(args.cpus)) != len(args.cpus) or any(c < 1 for c in args.cpus):
        raise ValueError('Choose distinct positive CPU counts')
    if args.output.exists():
        raise ValueError('Output exists; refusing a duplicate or silent restart')
    state = json.loads(args.state_file.read_text())
    if any(j['status'] in ('running', 'queued', 'waiting_for_decision') for j in state['jobs']):
        raise ValueError('A scientific job is active; refusing to compete with it')
    spec = importlib.util.spec_from_file_location('execution_benchmark',
        Path(__file__).with_name('vina_execution_benchmark.py'))
    benchmark = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(benchmark)
    config = json.loads((args.source / 'config.json').read_text())
    # Two matched seeds, both compounds and all three retained conformers.
    # Per-search exhaustiveness/pose count/energy window remain unchanged.
    config['parameters']['seeds'] = config['parameters']['seeds'][:2]
    checked = {config[k]: benchmark.digest(config[k]) for k in ('receptor', 'box', 'receptor_pdb')}
    checked[config['protocol_bundle']] = config['protocol_sha256']
    for compound in config['compounds']:
        checked.update(compound['prepared_sha256'])
    if any(benchmark.digest(p) != h for p, h in checked.items()):
        raise ValueError('A retained input hash does not match')
    args.output.mkdir(parents=True)
    benchmark.save(args.output / 'config.json', config)
    summary = dict(status='running', pid=os.getpid(), order=args.cpus, arms={},
        logical_cpus=os.cpu_count(), seeds=config['parameters']['seeds'],
        limitations=['Timing pilot: two matched seeds, not the full five-seed screen',
            'Sequential arm order, one run per setting; thermal/background effects are uncontrolled',
            'Exact preparation reused; no analysis/report generation timed',
            'Thread count is not CPU affinity; output equality is not experimental pose recovery'])
    benchmark.save(args.output / 'summary.json', summary)
    try:
        for cpu in args.cpus:
            arm = args.output / ('cpu_' + str(cpu))
            arm.mkdir()
            summary['current_cpu'] = cpu
            summary['arms'][str(cpu)] = dict(status='running')
            benchmark.save(args.output / 'summary.json', summary)
            start = time.perf_counter()
            with (arm / 'worker.log').open('w') as log:
                subprocess.run([sys.executable, str(Path(__file__).with_name('vina_execution_benchmark.py')),
                    '--worker', str(args.output / 'config.json'), '--arm', str(arm), '--cpu', str(cpu)],
                    check=True, stdout=log, stderr=subprocess.STDOUT)
            execution = json.loads((arm / 'execution.json').read_text())
            expected = len(config['parameters']['seeds']) * sum(len(c['prepared']) for c in config['compounds'])
            if execution['status'] != 'completed' or len(execution['jobs']) != expected:
                raise ValueError('Incomplete docking arm')
            matches = [Path(j['output']).read_bytes() ==
                (Path(config['baseline']) / Path(j['output']).relative_to(arm)).read_bytes()
                for j in execution['jobs']]
            summary['arms'][str(cpu)] = dict(status='completed',
                worker_seconds=time.perf_counter() - start,
                search_seconds=sum(j['dock_seconds'] for j in execution['jobs']),
                grid_seconds=sum(m['grid_seconds'] for m in execution['map_builds']),
                jobs=expected, byte_identical_outputs=sum(matches))
            benchmark.save(args.output / 'summary.json', summary)
        if any(benchmark.digest(p) != h for p, h in checked.items()):
            raise ValueError('A source input changed during execution')
        summary.update(status='completed', original_inputs_unchanged=True)
        summary.pop('current_cpu', None)
    except BaseException as exc:
        summary.update(status='failed', error=str(exc))
        raise
    finally:
        benchmark.save(args.output / 'summary.json', summary)


if __name__ == '__main__':
    main()
