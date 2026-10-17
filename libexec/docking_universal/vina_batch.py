"""Version-gated sequential Vina batches; no chemistry or sampling changes."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import UUID

SUPPORTED_VERSION = '1.2.7'


class UnsupportedBatch(ValueError):
    pass


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def parameters(options):
    """Reject options we cannot faithfully translate, before doing any work."""
    geometry = {prefix + '_' + axis for prefix in ('center', 'size') for axis in 'xyz'}
    allowed = geometry | {'exhaustiveness', 'num_modes', 'energy_range', 'seed', 'cpu'}
    values = {}
    for line in options.config.read_text(encoding='utf-8').splitlines():
        line = line.split('#', 1)[0].strip()
        if not line:
            continue
        if '=' not in line:
            raise UnsupportedBatch('unsupported config syntax')
        key, value = [p.strip() for p in line.split('=', 1)]
        if key not in allowed or key in values:
            raise UnsupportedBatch('unsupported or duplicate config option: ' + key)
        values[key] = value
    if not geometry <= values.keys():
        raise UnsupportedBatch('explicit center/size required')
    for key, attribute, default in (
        ('exhaustiveness', 'exhaustiveness', '8'), ('num_modes', 'num_modes', '9'),
        ('energy_range', 'energy_range', '3'), ('seed', 'seed', '0'), ('cpu', 'cpu', '0')):
        override = getattr(options, attribute)
        values[key] = override if override is not None else values.get(key, default)
    try:
        result = {key: float(values[key]) for key in geometry | {'energy_range'}}
        result.update({key: int(values[key]) for key in ('cpu', 'seed', 'exhaustiveness', 'num_modes')})
        if (not all(math.isfinite(v) for v in result.values()) or result['cpu'] < 0
                or not 1 <= result['seed'] < 2147483647 or result['exhaustiveness'] < 1
                or result['num_modes'] < 1 or result['energy_range'] <= 0
                or any(result['size_' + axis] <= 0 for axis in 'xyz')):
            raise ValueError
    except (ValueError, TypeError, OverflowError):
        raise UnsupportedBatch('positive search settings and an explicit nonzero seed required')
    return result


def probe():
    import vina
    binary = Path(sys.prefix) / ('Scripts/vina.exe' if os.name == 'nt' else 'bin/vina')
    return dict(api_version=vina.__version__, python=sys.executable,
                module=str(Path(vina.__file__).resolve()),
                executable=str(binary.resolve()) if binary.is_file() else None)


def runtime(invocation, version, environment, script):
    if version.strip() != 'AutoDock Vina v' + SUPPORTED_VERSION:
        raise UnsupportedBatch('only Vina ' + SUPPORTED_VERSION + ' is validated for persistent batches')
    command = invocation.command
    if len(command) == 1:
        binary = Path(command[0]).resolve()
        python = binary.with_name('python.exe' if os.name == 'nt' else 'python')
        if not python.is_file():
            raise UnsupportedBatch('no matching engine-environment Python')
        prefix = (str(python),)
    elif command[-1] == 'vina' and '-n' in command:
        binary = None
        prefix = (*command[:-1], 'python')
    else:
        raise UnsupportedBatch('unrecognized engine wrapper')
    try:
        checked = subprocess.run([*prefix, str(script), '--probe'], env=dict(environment),
                                 text=True, capture_output=True, timeout=30)
        info = json.loads(checked.stdout) if checked.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError):
        info = None
    if (not isinstance(info, dict) or info.get('api_version') != SUPPORTED_VERSION
            or not info.get('executable')):
        raise UnsupportedBatch('matching Vina Python API unavailable')
    if binary is not None and Path(info['executable']).resolve() != binary:
        raise UnsupportedBatch('Python API and selected engine are from different installations')
    return prefix, info


def run_worker(request_path):
    """One process/seed/map set, replacing ligand state for every exact input."""
    import vina
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    if vina.__version__ != SUPPORTED_VERSION:
        raise RuntimeError('Vina API version changed after preflight')
    params = request['parameters']
    output = Path(request['output'])
    request_id = str(UUID(request['request_id']))
    record_path = output / 'batch_records' / (request_id + '.json')
    record_path.parent.mkdir(parents=True, exist_ok=True)
    def publish(record):
        save(record_path, record)
        save(output / 'batch_execution.json', record)  # Latest-run convenience alias.
    record = dict(status='running', request_id=request['request_id'], pid=os.getpid(), api=probe(), parameters=params,
                  started_at=datetime.now(timezone.utc).isoformat(), jobs=[],
                  receptor_sha256=request['receptor_sha256'], config_sha256=request['config_sha256'],
                  no_refine=False, spacing_angstrom=0.375, min_rmsd_angstrom=1.0,
                  map_builds=0, map_atom_types='all Vina types; computed before ligand loading')
    started = time.perf_counter()
    publish(record)
    def unchanged(path, expected):
        if digest(path) != expected:
            raise RuntimeError('Input changed after batch preflight: ' + str(path))
    try:
        if request['runtime'] != record['api']:
            raise RuntimeError('Vina runtime changed after batch preflight')
        unchanged(request['receptor'], request['receptor_sha256'])
        unchanged(request['config'], request['config_sha256'])
        engine = None
        for job in request['jobs']:
            ligand, destination, log = (Path(job[k]) for k in ('ligand', 'output', 'log'))
            row = dict(ligand=str(ligand), output=str(destination), log=str(log),
                       ligand_sha256=job['sha256'], status='running')
            if request['skip_existing'] and destination.is_file() and destination.stat().st_size:
                row['status'] = 'skipped'
                record['jobs'].append(row)
                print('skip  ' + ligand.stem, flush=True)
                publish(record)
                continue
            # Input integrity errors are batch-fatal, not chemistry failures.
            unchanged(ligand, job['sha256'])
            unchanged(request['receptor'], request['receptor_sha256'])
            unchanged(request['config'], request['config_sha256'])
            print('run   ' + ligand.stem, flush=True)
            record['current_ligand'] = str(ligand)
            publish(record)
            # A cancelled write must not be discovered as a pose by collectors
            # that recursively enumerate *.pdbqt.
            temporary = destination.with_name(destination.name + '.partial')
            maps_ready = engine is not None
            try:
                if engine is None:
                    setup = time.perf_counter()
                    engine = vina.Vina(sf_name='vina', cpu=params['cpu'], seed=params['seed'],
                                       no_refine=False, verbosity=0)
                    engine.set_receptor(request['receptor'])
                    record['receptor_setup_seconds'] = time.perf_counter() - setup
                    setup = time.perf_counter()
                    engine.compute_vina_maps([params['center_' + a] for a in 'xyz'],
                                             [params['size_' + a] for a in 'xyz'], spacing=0.375)
                    record.update(map_builds=record['map_builds']+1,
                                  grid_seconds=time.perf_counter()-setup)
                    maps_ready = True
                with log.open('w', encoding='utf-8') as stream, redirect_stdout(stream), redirect_stderr(stream):
                    print('AutoDock Vina ' + SUPPORTED_VERSION + ' — persistent API batch')
                    print(json.dumps(params, sort_keys=True))
                    setup = time.perf_counter()
                    engine.set_ligand_from_file(str(ligand))
                    row['ligand_setup_seconds'] = time.perf_counter() - setup
                    setup = time.perf_counter()
                    engine.dock(exhaustiveness=params['exhaustiveness'], n_poses=params['num_modes'],
                                min_rmsd=1.0, max_evals=0)
                    row['search_seconds'] = time.perf_counter() - setup
                    engine.write_poses(str(temporary), n_poses=params['num_modes'],
                                       energy_range=params['energy_range'], overwrite=True)
                    text = temporary.read_text(encoding='utf-8')
                    lines = text.splitlines()
                    row['pose_count'] = sum(line.startswith('MODEL ') for line in lines)
                    if (not row['pose_count'] or row['pose_count'] != sum(line.strip() == 'ENDMDL' for line in lines)
                            or row['pose_count'] != sum(line.startswith('REMARK VINA RESULT:') for line in lines)):
                        raise ValueError('Vina did not write a complete scored pose inventory')
                    unchanged(ligand, job['sha256'])
                    temporary.replace(destination)
                    row.update(status='completed', output_sha256=digest(destination))
                    print(f"Saved {row['pose_count']} poses: {destination.name}")
            except Exception as exc:
                temporary.unlink(missing_ok=True)
                destination.unlink(missing_ok=True)
                row.update(status='failed', error=str(exc))
                with log.open('a', encoding='utf-8') as stream:
                    print(str(exc), file=stream)
                print(f'ERROR: vina failed for {ligand.stem}; see {log}', file=sys.stderr, flush=True)
                if not maps_ready:
                    record['jobs'].append(row)
                    raise RuntimeError('Vina receptor/map setup failed: ' + str(exc)) from exc
                # A failed ligand must not contaminate the next input. Reset
                # the engine/maps after failure, never repeat the failed search.
                engine = None
            record['jobs'].append(row)
            publish(record)
        unchanged(request['receptor'], request['receptor_sha256'])
        unchanged(request['config'], request['config_sha256'])
        for job in request['jobs']:
            unchanged(job['ligand'], job['sha256'])
        record['status'] = 'completed_with_failures' if any(j['status']=='failed' for j in record['jobs']) else 'completed'
        record.pop('current_ligand', None)
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
        raise
    finally:
        record.update(wall_seconds=time.perf_counter()-started, finished_at=datetime.now(timezone.utc).isoformat())
        publish(record)
    return 1 if record['status'] == 'completed_with_failures' else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', action='store_true')
    parser.add_argument('--request', type=Path)
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe()))
        return 0
    if not args.request:
        parser.error('--request required')
    return run_worker(args.request)


if __name__ == '__main__':
    raise SystemExit(main())
