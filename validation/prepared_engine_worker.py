"""Compare a new CPU engine with retained Vina poses; never repeat preparation.

Trusted local manifests pin every consumed scientific input. This is an
experimental single-state, dry rigid-receptor comparison, not control approval.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time

from redock_prepared_ab import verify_coordinate_frame


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_manifest(path):
    manifest = json.loads(Path(path).read_text())
    if manifest['engine'] != 'qvinaw' or manifest['baseline_engine'] != 'vina':
        raise ValueError('This adapter supports retained Vina versus new QuickVina-W only')
    for item in manifest['inputs'].values():
        if digest(item['path']) != item['sha256']:
            raise ValueError('Pinned prepared input changed: ' + item['path'])
    if manifest['seeds'] != [41001, 41002, 41003]:
        raise ValueError('Require the three predeclared matched seeds')
    return manifest


def search_command(manifest, seed, output):
    """Retain the original search settings; only executable/CPU/output change."""
    original = json.loads(Path(manifest['inputs'][f'command-{seed}']['path']).read_text())
    if len(original) % 2 != 1:
        raise ValueError('Malformed original Vina invocation')
    pairs = list(zip(original[1::2], original[2::2]))
    options = dict(pairs)
    expected = {'--receptor', '--ligand', '--config', '--out', '--seed', '--cpu',
                '--exhaustiveness', '--num_modes', '--energy_range'}
    if set(options) != expected or len(pairs) != len(expected):
        raise ValueError('Unexpected or duplicate original search options')
    for flag, name in [('--receptor', 'receptor-pdbqt'), ('--ligand', 'ligand-pdbqt'),
                       ('--config', 'box'), ('--out', f'baseline-{seed}')]:
        if Path(options[flag]).resolve() != Path(manifest['inputs'][name]['path']).resolve():
            raise ValueError('Original command differs from pinned input: ' + flag)
    if int(options['--seed']) != seed or int(options['--cpu']) != 1:
        raise ValueError('Unexpected baseline seed or CPU configuration')
    options.update({'--out': str(output), '--cpu': '8'})
    return [manifest['executable'], *[part for key, _ in pairs for part in (key, options[key])]]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    manifest = load_manifest(args.manifest)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    record = {'status': 'running', 'phase': 'preflight', 'scope': manifest['scope'],
              'new_searches': 0, 'baseline_searches_reused': 3, 'seeds': manifest['seeds']}
    def save():
        (out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')
    def run(command, folder, name):
        (folder / (name + '.command.json')).write_text(json.dumps(command, indent=2) + '\n')
        with (folder / (name + '.log')).open('w') as log:
            result = subprocess.run(command, cwd=folder, stdout=log, stderr=subprocess.STDOUT,
                                    timeout=1800)
        if result.returncode:
            raise RuntimeError(name + ' failed with exit ' + str(result.returncode))
    save()
    try:
        paths = {key: item['path'] for key, item in manifest['inputs'].items()}
        record['coordinate_frame'] = verify_coordinate_frame(Path(paths['receptor-raw']), Path(paths['receptor-pdbqt']))
        rows = []
        for seed in manifest['seeds']:
            folder = out / str(seed)
            folder.mkdir()
            record.update(phase='searching', current_seed=seed); save()
            started = time.monotonic()
            run(search_command(manifest, seed, folder / 'poses.pdbqt'), folder, 'qvinaw')
            record['new_searches'] += 1
            record.setdefault('search_seconds', {})[str(seed)] = time.monotonic() - started
            record['phase'] = 'experimental-comparison'; save()
            for arm, poses in [('retained_vina', paths[f'baseline-{seed}']),
                               ('new_qvinaw', str(folder / 'poses.pdbqt'))]:
                destination = folder / arm
                command = [sys.executable, paths['comparison-tool'], '--reference-sdf', paths['ligand-sdf'],
                           '--crystal-ligand', paths['crystal'], '--docked-pdbqt', poses,
                           '--receptor-pdb', paths['receptor-pdb'], '--mk-export', paths['exporter'],
                           '--out', str(destination)]
                run(command, folder, arm)
                with (destination / 'pose_comparison.csv').open() as stream:
                    for row in csv.DictReader(stream):
                        rows.append(dict(row, arm=arm, seed=seed))
            save()
        with (out / 'poses.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
            writer.writeheader(); writer.writerows(rows)
        load_manifest(args.manifest)
        record.update(status='completed', phase='completed', pose_count=len(rows), original_inputs_unchanged=True)
        save()
        return 0
    except BaseException as exc:
        record.update(status='failed', reason=str(exc)); save()
        raise


if __name__ == '__main__':
    raise SystemExit(main())
