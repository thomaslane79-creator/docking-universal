"""Sequential retained-output acceptance and gated installation of Vina batches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'libexec'))
from docking_universal.vina_batch import digest, save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wait-for', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--install-to', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    if out.exists():
        raise ValueError('Output exists; refusing a duplicate acceptance run')
    out.mkdir(parents=True)
    summary = dict(status='waiting_for_cpu_pilot', pid=os.getpid(), cases=[], checks=[])
    summary_path = out / 'summary.json'
    save(summary_path, summary)
    def check(name, condition):
        summary['checks'].append(dict(name=name, passed=bool(condition)))
        save(summary_path, summary)
        if not condition:
            raise AssertionError(name)
    try:
        while True:
            preceding = json.loads(args.wait_for.read_text())
            if preceding['status'] not in ('running', 'queued'):
                if preceding['status'] != 'completed':
                    raise RuntimeError('CPU pilot stopped without full completion: ' + preceding['status'])
                break
            time.sleep(20)
        summary['status'] = 'running_acceptance'
        save(summary_path, summary)
        files = ['docking_universal/vina_batch.py', 'docking-universal-vina-batch.py', 'docking_universal_dock.py']
        implementation = {f: digest(ROOT / 'libexec' / f) for f in files}
        summary['implementation_sha256'] = implementation
        source_hashes = {}
        env = dict(os.environ, DOCKING_UNIVERSAL_VINA_BACKEND='api', DOCKING_UNIVERSAL_CPU='8',
                   DOCKING_UNIVERSAL_PYTHON=sys.executable, PYTHONPATH=str(ROOT / 'libexec'))
        engine = '/opt/anaconda3/envs/docking-universal-vina/bin/vina'
        def invoke(folder, receptor, config, inputs, seed, effort, modes, window, backend='api', extra=()):
            command = [sys.executable, '-u', str(ROOT / 'libexec/docking-universal-dock'),
                '--engine-command', engine, '--receptor', str(receptor), '--config', str(config),
                '--ligands', str(inputs), '--out', str(folder), '--seed', str(seed), '--cpu', '8',
                '--exhaustiveness', str(effort), '--num-modes', str(modes), '--energy-range', str(window),
                '--vina-backend', backend, *extra]
            start = time.perf_counter()
            with folder.with_suffix('.log').open('w') as log:
                completed = subprocess.run(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            return completed.returncode, time.perf_counter()-start
        config = json.loads((ROOT / 'validation/runs/vina-execution-20261015_095135/config.json').read_text())
        compound = config['compounds'][1]
        cases = [dict(name='current_screen', receptor=config['receptor'], config=config['box'],
            ligands=compound['prepared'], seed=20260808, effort=16, modes=15, window=8,
            references=[str(Path(config['baseline']) / 'compounds' / compound['id'] /
                'seed_20260808/docking' / (Path(p).stem + '_vina.pdbqt')) for p in compound['prepared']])]
        base = ROOT / 'validation/runs/conformer-ab'
        for name, source in [('indinavir_protease', base / 'indinavir_2r5p_redocking_20261004_framechecked'),
                ('imatinib_abl', base / 'four_more_20261005_ready/imatinib_1iep/benchmark'),
                ('geldanamycin_hsp90', base / 'four_more_20261005_ready/geldanamycin_1yet/benchmark')]:
            command = json.loads((source / 'vacuum_pruned/dock_conf_01/seed_41001/vina.command.json').read_text())
            options = {command[i]: command[i+1] for i in range(1, len(command), 2)}
            folders = [source / 'vacuum_pruned' / f'dock_conf_{i:02d}' for i in (1, 2)]
            cases.append(dict(name=name, receptor=options['--receptor'], config=options['--config'],
                ligands=[str(f / 'ligand.pdbqt') for f in folders], seed=41001, effort=8, modes=9, window=3,
                references=[str(f / 'seed_41001/poses.pdbqt') for f in folders]))
        for case in cases:
            for path in [case['receptor'], case['config'], *case['ligands'], *case['references']]:
                source_hashes[path] = digest(path)
        save(out / 'source_hashes.json', source_hashes)
        for case in cases:
            folder = out / case['name']; folder.mkdir()
            inputs = folder / 'inputs'; inputs.mkdir()
            for index, source in enumerate(case['ligands'], 1):
                shutil.copy2(source, inputs / f'conformer_{index:02d}.pdbqt')
            row = dict(case, status='running')
            summary['cases'].append(row)
            save(summary_path, summary)
            code, elapsed = invoke(folder / 'api', case['receptor'], case['config'], inputs,
                case['seed'], case['effort'], case['modes'], case['window'])
            check(case['name'] + ': API batch completed', code == 0)
            record = json.loads((folder / 'api/batch_execution.json').read_text())
            check(case['name'] + ': exactly one all-type map build', record['map_builds'] == 1)
            paths = [folder / 'api' / f'conformer_{i:02d}_vina.pdbqt' for i in range(1, len(case['ligands'])+1)]
            check(case['name'] + ': all complete poses match retained CLI outputs',
                  all(digest(path) == digest(reference) for path, reference in zip(paths, case['references'])))
            row.update(status='passed', api_wall_seconds=elapsed,
                       api_record=str(folder / 'api/batch_records' / (record['request_id'] + '.json')),
                       search_seconds=sum(j['search_seconds'] for j in record['jobs']))
            before = {str(p): digest(p) for p in paths}
            code, _ = invoke(folder / 'api', case['receptor'], case['config'], inputs,
                case['seed'], case['effort'], case['modes'], case['window'], extra=['--skip-existing'])
            skipped = json.loads((folder / 'api/batch_execution.json').read_text())
            check(case['name'] + ': skip preserves outputs and builds no maps', code == 0 and skipped['map_builds'] == 0
                  and all(j['status']=='skipped' for j in skipped['jobs'])
                  and all(digest(p)==h for p, h in before.items()))
            if case['name'] == 'current_screen':
                code, elapsed = invoke(folder / 'cli', case['receptor'], case['config'], inputs,
                    case['seed'], case['effort'], case['modes'], case['window'], backend='cli')
                check('current screen: fresh same-thread CLI outputs also match', code == 0 and
                      all(digest(folder / 'cli' / p.name) == digest(p) for p in paths))
                row['fresh_direct_cli_wall_seconds'] = elapsed
                bad = folder / 'failure_inputs'; bad.mkdir()
                (bad / 'a_bad.pdbqt').write_text('invalid ligand fixture\n')
                shutil.copy2(sorted(inputs.glob('*.pdbqt'))[0], bad / 'b_good.pdbqt')
                code, _ = invoke(folder / 'failure', case['receptor'], case['config'], bad,
                    case['seed'], case['effort'], case['modes'], case['window'])
                failed = json.loads((folder / 'failure/batch_execution.json').read_text())
                check('native bad ligand is not retried; next ligand succeeds with clean maps', code == 1 and
                      [j['status'] for j in failed['jobs']] == ['failed', 'completed'] and failed['map_builds']==2)
                check('native failure retains only the valid complete pose output',
                      not (folder / 'failure/a_bad_vina.pdbqt').exists() and
                      digest(folder / 'failure/b_good_vina.pdbqt') == digest(paths[0]))
            save(summary_path, summary)
        check('retained scientific inputs and outputs unchanged', all(digest(p)==h for p, h in source_hashes.items()))
        check('tested implementation unchanged during acceptance', all(digest(ROOT/'libexec'/f)==h for f,h in implementation.items()))
        if args.install_to:
            summary['status'] = 'installing_verified_backend'
            save(summary_path, summary)
            backups = out / 'installed_before'; backups.mkdir()
            for f in files:  # Dispatcher last: incomplete installation cannot select the new path.
                source, destination = ROOT / 'libexec' / f, args.install_to / f
                if destination.exists():
                    backup = backups / f; backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(destination, backup)
                temporary = destination.with_name(destination.name + '.new')
                shutil.copy2(source, temporary)
                temporary.replace(destination)
            check('installed backend matches tested source', all(digest(args.install_to/f)==h for f,h in implementation.items()))
            summary['installed_to'] = str(args.install_to)
        summary['status'] = 'passed'
    except BaseException as exc:
        summary.update(status='failed', error=str(exc))
        raise
    finally:
        save(summary_path, summary)


if __name__ == '__main__':
    main()
