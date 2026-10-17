"""Serial, isolated full-budget Vina execution comparison using retained inputs.

No preparation is repeated and no production defaults or studies are changed.
The existing CLI run is a historical baseline, not a contemporaneous control.
"""
import argparse
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import resource
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'libexec'))
from docking_universal.screening_progress import write_screening_progress


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'libexec' / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def worker(config_path, arm, cpu):
    import vina
    config = json.loads(config_path.read_text())
    params, box = config['parameters'], config['geometry']
    record = {'status': 'running', 'cpu_setting': cpu, 'version': vina.__version__,
              'pid': os.getpid(), 'started_at': datetime.now(timezone.utc).isoformat(),
              'map_builds': [], 'jobs': [], 'no_refine': False}
    started = time.perf_counter()
    save(arm / 'execution.json', record)
    try:
        for seed in params['seeds']:
            start = time.perf_counter()
            engine = vina.Vina(sf_name='vina', cpu=cpu, seed=seed, no_refine=False, verbosity=0)
            engine.set_receptor(config['receptor'])
            receptor_seconds = time.perf_counter() - start
            start = time.perf_counter()
            # All atom-type maps are computed before loading a ligand. Maps stay
            # in memory (no text-map precision loss), reused for six inputs/seed.
            engine.compute_vina_maps([box['center_' + a] for a in 'xyz'],
                                     [box['size_' + a] for a in 'xyz'], spacing=0.375)
            record['map_builds'].append({'seed': seed, 'receptor_seconds': receptor_seconds,
                                         'grid_seconds': time.perf_counter() - start})
            for compound in config['compounds']:
                for ligand in compound['prepared']:
                    output = arm / 'compounds' / compound['id'] / f'seed_{seed}/docking' / (Path(ligand).stem + '_vina.pdbqt')
                    output.parent.mkdir(parents=True, exist_ok=True)
                    record['current'] = {'compound': compound['id'], 'ligand': Path(ligand).name, 'seed': seed}
                    save(arm / 'execution.json', record)
                    start = time.perf_counter()
                    engine.set_ligand_from_file(ligand)
                    set_ligand_seconds = time.perf_counter() - start
                    before = resource.getrusage(resource.RUSAGE_SELF)
                    start = time.perf_counter()
                    # Vina 1.2.7 global_search initializes RNG from m_seed on
                    # every call. Ligand replacement resets pose state.
                    engine.dock(exhaustiveness=params['exhaustiveness'], n_poses=params['num_modes'], min_rmsd=1.0)
                    seconds = time.perf_counter() - start
                    after = resource.getrusage(resource.RUSAGE_SELF)
                    engine.write_poses(str(output), n_poses=params['num_modes'],
                                       energy_range=params['energy_range_kcal_per_mol'], overwrite=False)
                    if not output.is_file() or 'ENDMDL' not in output.read_text():
                        raise ValueError('No complete poses: ' + str(output))
                    record['jobs'].append({**record['current'], 'output': str(output),
                        'set_ligand_seconds': set_ligand_seconds, 'dock_seconds': seconds,
                        'cpu_seconds': after.ru_utime + after.ru_stime - before.ru_utime - before.ru_stime})
                    save(arm / 'execution.json', record)
        record['status'] = 'completed'
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
        raise
    finally:
        record['wall_seconds'] = time.perf_counter() - started
        record['finished_at'] = datetime.now(timezone.utc).isoformat()
        save(arm / 'execution.json', record)


def postprocess(config, baseline, arm, log):
    """Run the same cluster/representative/PLIP/report stages on new poses."""
    cli = Path('/opt/anaconda3/envs/docking-universal/bin/docking-universal')
    def run(command):
        print(' '.join(map(str, command)), file=log, flush=True)
        subprocess.run(list(map(str, command)), stdout=log, stderr=subprocess.STDOUT, check=True)
    collector = module('execution_collect', 'docking-universal-collect.py')
    runner = module('execution_report', 'docking-universal-run.py')
    for compound in config['compounds']:
        path = arm / 'compounds' / compound['id']
        rows = []
        for pdbqt in sorted(path.glob('seed_*/docking/*_vina.pdbqt')):
            rows.extend({'site': 1, 'seed': int(pdbqt.parent.parent.name[5:]), **row}
                        for row in collector.parse_file(pdbqt))
        if not rows:
            raise ValueError('No pose rows: ' + compound['id'])
        with (path / 'all_scores.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        analysis = path / 'pose_analysis'
        run([cli, 'cluster-poses', '--docking-root', path, '--ligand-work', path / 'ligand_preparation/ligand_work',
             '--receptor', config['receptor_pdb'], '--out', analysis, '--cluster-rmsd', config['cluster_rmsd'],
             '--representatives', config['representatives'], '--mk-export', '/opt/anaconda3/envs/docking-universal/bin/mk_export.py'])
        run([cli, 'render3d', analysis / 'representative_browser.pml', '--out', analysis / 'representative_browser.png',
             '--session-out', analysis / 'representative_browser.pse'])
        for cluster in sorted(analysis.glob('cluster_*')):
            if not cluster.is_dir(): continue
            run([cli, 'render3d', cluster / 'representative.pml', '--out', cluster / 'representative.png',
                 '--session-out', cluster / 'representative.pse'])
            run([cli, 'interactions', cluster / 'complex.pdb', '--out-dir', cluster / 'interactions',
                 '--skip-native-visuals', '--typed-ligand-sdf', cluster / 'representative.sdf',
                 '--ligand-resname', 'UNL', '--ligand-chain', 'Z', '--ligand-position', '1'])
            scene = cluster / 'interactions/complex_plip_all_in_one.pml'
            if scene.is_file():
                run([cli, 'render3d', scene, '--out', scene.with_suffix('.png'), '--session-out', scene.with_suffix('.pse')])
        manifest = json.loads((baseline / 'compounds' / compound['id'] / 'screen_manifest.json').read_text())
        manifest.update(ligand=str(arm / 'inputs/compounds' / Path(compound['input']).name),
                        receptor=config['receptor'], box=config['box'], protocol=config['protocol_record'],
                        execution_benchmark=True, execution_record=str(arm / 'execution.json'))
        save(path / 'screen_manifest.json', manifest)
    manifest = json.loads((baseline / 'study_manifest.json').read_text())
    manifest.update(study_name='2R8N execution benchmark ' + arm.name, execution_benchmark=True,
                    execution_config=config, completion_status='COMPLETED',
                    protocol=config['protocol_record'])
    save(arm / 'study_manifest.json', manifest)
    compounds = json.loads((baseline / 'inputs/compound_library_inventory.json').read_text())['compounds']
    for compound in compounds:
        compound['input'] = str(arm / 'inputs/compounds' / Path(compound['input']).name)
        compound['run_status'] = 'COMPLETED'
    runner.write_reports(arm, manifest, compounds)
    if not list((arm / 'report').glob('*.pdf')):
        raise ValueError('Full PDF report was not created; inspect report log')


def compare_outputs(baseline, arm):
    from rdkit import Chem
    from rdkit.Chem import rdMolAlign
    from meeko import PDBQTMolecule, RDKitMolCreate
    def molecule(path):
        values = RDKitMolCreate.from_pdbqt_mol(PDBQTMolecule.from_file(str(path), skip_typing=True))
        if len(values) != 1 or values[0] is None: raise ValueError('Cannot compare typed poses: ' + str(path))
        return Chem.RemoveHs(values[0])
    def energies(path):
        return [float(line.split()[3]) for line in path.read_text().splitlines() if line.startswith('REMARK VINA RESULT:')]
    rows = []
    for path in sorted(arm.glob('compounds/*/seed_*/docking/*_vina.pdbqt')):
        old = baseline / path.relative_to(arm)
        before, after = molecule(old), molecule(path)
        old_energies, new_energies = energies(old), energies(path)
        rows.append({'compound': path.parts[-4], 'seed': path.parts[-3], 'conformer': path.stem,
                     'baseline_best_energy_kcal_mol': old_energies[0], 'new_best_energy_kcal_mol': new_energies[0],
                     'energy_difference_kcal_mol': new_energies[0] - old_energies[0],
                     'best_pose_to_baseline_best_pose_rmsd_angstrom': rdMolAlign.CalcRMS(after, before, prbId=0, refId=0, maxMatches=100000),
                     'baseline_pose_count': len(old_energies), 'new_pose_count': len(new_energies),
                     'pdbqt_byte_identical': path.read_bytes() == old.read_bytes()})
    with (arm / 'comparison.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    save(arm / 'comparison_summary.json', {'job_count': len(rows),
        'rmsd_definition': 'symmetry-aware heavy-atom RMSD in receptor frame to matching historical lowest-energy pose, not experimental RMSD',
        'max_absolute_best_energy_difference': max(abs(row['energy_difference_kcal_mol']) for row in rows),
        'max_best_pose_rmsd_to_baseline': max(row['best_pose_to_baseline_best_pose_rmsd_angstrom'] for row in rows)})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--protocol', type=Path)
    parser.add_argument('--baseline', type=Path)
    parser.add_argument('--state-file', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', type=Path)
    parser.add_argument('--arm', type=Path)
    parser.add_argument('--cpu', type=int)
    parser.add_argument('--resume-analysis', type=Path,
                        help='Explicitly resume a failed post-processing stage; never repeat completed docking')
    args = parser.parse_args()
    if args.worker:
        worker(args.worker, args.arm, args.cpu)
        return
    os.environ['DOCKING_UNIVERSAL_PYTHON'] = sys.executable
    os.environ['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ.get('PATH', '')
    if args.resume_analysis:
        resume_analysis(args.resume_analysis.resolve())
        return
    from docking_universal_bundle import extract_bundle, resolve_locked_path
    from docking_universal.services.screening import read_protocol_record
    if args.output.exists():
        raise ValueError('Output already exists; refusing duplicate/resumed benchmark')
    state = json.loads(args.state_file.read_text())
    if any(job['status'] in ('running', 'queued', 'waiting_for_decision') for job in state['jobs']):
        raise ValueError('A scientific stage is still active; do not compete with it')
    baseline, out = args.baseline.resolve(), args.output.resolve()
    protocol = read_protocol_record(args.protocol)
    if protocol['engine'] != 'vina': raise ValueError('This benchmark requires a Vina protocol')
    out.mkdir(parents=True)
    original_hash = digest(args.protocol)
    original_inventory = baseline / 'inputs/compound_library_inventory.json'
    baseline_hashes = {str(p): digest(p) for p in baseline.rglob('*') if p.is_file()}
    save(out / 'baseline_hashes.json', baseline_hashes)
    record_path = extract_bundle(args.protocol)
    record = json.loads(record_path.read_text())
    inputs = out / 'locked_inputs'; inputs.mkdir()
    copied = {}
    for key in ('receptor', 'receptor_pdb', 'box'):
        source = resolve_locked_path(record_path, record['locked_inputs'][key])
        expected = record['locked_inputs'].get(key + '_sha256')
        if expected and digest(source) != expected: raise ValueError('Locked hash mismatch: ' + key)
        target = inputs / source.name; shutil.copy2(source, target); copied[key] = str(target)
    geometry = {}
    for line in Path(copied['box']).read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            if key.strip().startswith(('center_', 'size_')): geometry[key.strip()] = float(value.split('#')[0])
    source_manifest = json.loads((baseline / 'study_manifest.json').read_text())
    config = dict(copied, parameters=protocol['parameters'], geometry=geometry,
                  protocol_record=str(record_path), protocol_bundle=str(args.protocol.resolve()),
                  protocol_sha256=original_hash, baseline=str(baseline),
                  cluster_rmsd=source_manifest['cluster_rmsd_angstrom'],
                  representatives=source_manifest['representatives'], compounds=[])
    for compound in json.loads(original_inventory.read_text())['compounds']:
        path = baseline / 'compounds' / compound['compound_id']
        prepared = sorted((path / 'ligand_preparation/pdbqt_ligands').glob('*.pdbqt'))
        existing = json.loads((path / 'screen_manifest.json').read_text())
        if existing['protocol_sha256'] != digest(record_path): raise ValueError('Baseline locked protocol mismatch')
        used = next(path.glob('seed_*/docking/*.conf.used'))
        if digest(used) != digest(copied['box']): raise ValueError('Baseline box mismatch')
        if existing['ligand_sha256'] != digest(compound['input']): raise ValueError('Baseline input changed')
        if existing['seeds'] != protocol['parameters']['seeds']: raise ValueError('Baseline seed mismatch')
        if existing['ensemble_parameters']['ph'] != protocol['parameters']['ph']: raise ValueError('Baseline pH mismatch')
        if not prepared: raise ValueError('No prepared ligands')
        config['compounds'].append({'id': compound['compound_id'], 'input': compound['input'],
                                    'prepared': [str(p) for p in prepared],
                                    'prepared_sha256': {str(p): digest(p) for p in prepared}})
    save(out / 'config.json', config)
    job = next(job for job in reversed(state['jobs']) if job['stage'] == 'screening')
    baseline_seconds = (datetime.fromisoformat(job['finished_at']) - datetime.fromisoformat(job['started_at'])).total_seconds()
    summary = {'status': 'running', 'pid': os.getpid(), 'baseline_worker_seconds': baseline_seconds,
               'limitations': ['Historical baseline, not concurrent or randomized timing control',
                 'Exact retained preparation reused, not re-timed', 'No experimental poses for these two unknown compounds',
                 'API and CLI builds can differ numerically despite matching Vina versions',
                 '8 threads is not affinity to performance cores'], 'arms': {}}
    save(out / 'summary.json', summary)
    try:
        for cpu in (0, 8):
            name = 'shared_grid_auto' if cpu == 0 else 'shared_grid_cpu8'
            arm = out / name; arm.mkdir()
            for compound in config['compounds']:
                target = arm / 'compounds' / compound['id']; target.mkdir(parents=True)
                for item in ('ligand_preparation', 'depiction'):
                    shutil.copytree(baseline / 'compounds' / compound['id'] / item, target / item)
                for item in ('independent_ensemble.sdf', 'independent_ensemble.manifest.json'):
                    shutil.copy2(baseline / 'compounds' / compound['id'] / item, target / item)
            shutil.copytree(baseline / 'inputs', arm / 'inputs')
            summary['arms'][name] = {'status': 'docking', 'cpu': cpu}
            save(out / 'summary.json', summary)
            start = time.perf_counter()
            with (arm / 'worker.log').open('w') as log:
                subprocess.run(['/opt/anaconda3/envs/docking-universal-vina/bin/python', __file__,
                                '--worker', str(out / 'config.json'), '--arm', str(arm), '--cpu', str(cpu)],
                               stdout=log, stderr=subprocess.STDOUT, check=True)
            summary['arms'][name].update(status='analysis', docking_worker_seconds=time.perf_counter() - start)
            save(out / 'summary.json', summary)
            compare_outputs(baseline, arm)
            with (arm / 'analysis.log').open('w') as log:
                postprocess(config, baseline, arm, log)
            summary['arms'][name].update(status='completed', docking_plus_analysis_seconds=time.perf_counter() - start)
            save(out / 'summary.json', summary)
        if digest(args.protocol) != original_hash: raise ValueError('Protocol changed during benchmark')
        if any(not Path(path).is_file() or digest(path) != value for path, value in baseline_hashes.items()):
            raise ValueError('Historical baseline changed during benchmark')
        summary.update(status='completed', original_protocol_and_baseline_unchanged=True)
    except BaseException as exc:
        summary.update(status='failed', error=str(exc))
        raise
    finally:
        save(out / 'summary.json', summary)


def resume_analysis(out):
    """Recover runtime selection errors from verified saved poses, not new docks."""
    config = json.loads((out / 'config.json').read_text())
    summary = json.loads((out / 'summary.json').read_text())
    if summary['status'] != 'failed': raise ValueError('Only an explicitly failed benchmark can be resumed')
    for compound in config['compounds']:
        for path, expected in compound['prepared_sha256'].items():
            if digest(path) != expected: raise ValueError('Prepared input changed: ' + path)
    if digest(config['protocol_bundle']) != config['protocol_sha256']: raise ValueError('Protocol changed')
    baseline = Path(config['baseline'])
    hashes = out / 'baseline_hashes.json'
    if hashes.exists():
        baseline_hashes = json.loads(hashes.read_text())
    else:
        baseline_hashes = {str(p): digest(p) for p in baseline.rglob('*') if p.is_file()}
        save(hashes, baseline_hashes)
    summary.setdefault('recovered_errors', []).append(summary.pop('error'))
    summary.update(status='running', pid=os.getpid())
    save(out / 'summary.json', summary)
    try:
        for cpu in (0, 8):
            name = 'shared_grid_auto' if cpu == 0 else 'shared_grid_cpu8'
            arm = out / name
            if arm.exists():
                execution = json.loads((arm / 'execution.json').read_text())
                expected = len(config['parameters']['seeds']) * sum(len(c['prepared']) for c in config['compounds'])
                if execution['status'] != 'completed' or len(execution['jobs']) != expected:
                    raise ValueError('Existing docking is incomplete; refusing silent restart: ' + name)
                if any(not Path(job['output']).is_file() for job in execution['jobs']):
                    raise ValueError('A completed docking output is missing')
            else:
                arm.mkdir()
                for compound in config['compounds']:
                    target = arm / 'compounds' / compound['id']; target.mkdir(parents=True)
                    for item in ('ligand_preparation', 'depiction'):
                        shutil.copytree(baseline / 'compounds' / compound['id'] / item, target / item)
                    for item in ('independent_ensemble.sdf', 'independent_ensemble.manifest.json'):
                        shutil.copy2(baseline / 'compounds' / compound['id'] / item, target / item)
                shutil.copytree(baseline / 'inputs', arm / 'inputs')
                summary['arms'][name] = {'status': 'docking', 'cpu': cpu}
                save(out / 'summary.json', summary)
                start = time.perf_counter()
                with (arm / 'worker.log').open('w') as log:
                    subprocess.run(['/opt/anaconda3/envs/docking-universal-vina/bin/python', __file__,
                                    '--worker', str(out / 'config.json'), '--arm', str(arm), '--cpu', str(cpu)],
                                   stdout=log, stderr=subprocess.STDOUT, check=True)
                summary['arms'][name]['docking_worker_seconds'] = time.perf_counter() - start
            summary['arms'][name]['status'] = 'analysis'
            save(out / 'summary.json', summary)
            compare_outputs(baseline, arm)
            start = time.perf_counter()
            with (arm / 'analysis.log').open('a') as log:
                log.write('\nExplicit analysis continuation with scientific Python; completed docking reused.\n')
                log.flush()
                postprocess(config, baseline, arm, log)
            summary['arms'][name].update(status='completed', analysis_seconds=time.perf_counter() - start)
            summary['arms'][name]['docking_plus_analysis_seconds'] = (
                summary['arms'][name]['docking_worker_seconds'] + summary['arms'][name]['analysis_seconds'])
            save(out / 'summary.json', summary)
        if any(digest(path) != expected for path, expected in baseline_hashes.items()):
            raise ValueError('Historical baseline changed')
        if digest(config['protocol_bundle']) != config['protocol_sha256']: raise ValueError('Protocol changed')
        summary.update(status='completed', original_protocol_and_baseline_unchanged=True)
    except BaseException as exc:
        summary.update(status='failed', error=str(exc))
        raise
    finally:
        save(out / 'summary.json', summary)


if __name__ == '__main__':
    main()
