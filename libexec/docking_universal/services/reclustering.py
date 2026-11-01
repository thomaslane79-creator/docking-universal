"""Validate immutable retained pose inputs for an explicit analysis revision."""
from __future__ import annotations
import csv
import hashlib
import json
import math
from pathlib import Path

INPUT_NAMES = ('all_poses.sdf', 'pose_inventory.csv', 'cluster_summary.csv',
               'clustering_manifest.json', 'receptor.pdb')

def input_hashes(root):
    root = Path(root).resolve()
    missing = [name for name in INPUT_NAMES if not (root / name).is_file()]
    if missing:
        raise FileNotFoundError('Retained analysis is incomplete: ' + ', '.join(missing))
    if any((root / name).is_symlink() for name in INPUT_NAMES):
        raise ValueError('Retained analysis inputs must not be symbolic links')
    return {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in INPUT_NAMES}

def retained_engine(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'clustering_manifest.json').read_text())
    if manifest.get('engine'):
        return str(manifest['engine'])
    # A site can be nested one level below its compound. Never infer from the
    # current GUI engine selection or a filename suffix.
    for parent in (root.parent, root.parent.parent):
        path = parent / 'screen_manifest.json'
        if path.is_file():
            engine = json.loads(path.read_text()).get('engine')
            if engine:
                return str(engine)
    raise ValueError('Retained scoring engine is missing; cannot guess its identity')

def load_retained_records(root, engine):
    """Read every pose in original ID order; preserve state, energy and frame."""
    from ..sdf_io import read_sdf
    root = Path(root).resolve()
    before = input_hashes(root)
    if retained_engine(root) != engine:
        raise ValueError('Requested engine differs from the retained analysis')
    with (root / 'pose_inventory.csv').open(newline='') as handle:
        rows = list(csv.DictReader(handle))
    with (root / 'cluster_summary.csv').open(newline='') as handle:
        states = {int(row['cluster_id']): row['chemical_state'] for row in csv.DictReader(handle)}
    molecules = list(read_sdf(root / 'all_poses.sdf', removeHs=True))
    manifest = json.loads((root / 'clustering_manifest.json').read_text())
    if not rows or len(rows) != len(molecules) or manifest.get('pose_count') != len(rows):
        raise ValueError('Retained pose counts disagree; no poses may be silently skipped')
    records = []
    for index, (row, molecule) in enumerate(zip(rows, molecules), 1):
        if int(row['pose_id']) != index or molecule is None or molecule.GetNumConformers() != 1:
            raise ValueError('Retained pose identity/geometry is incomplete or reordered')
        energy = float(row['energy_kcal_per_mol'])
        if not math.isfinite(energy) or not molecule.HasProp('DockingUniversal_Energy'):
            raise ValueError('Retained pose lacks a finite recorded energy')
        if abs(molecule.GetDoubleProp('DockingUniversal_Energy') - energy) > 1e-8:
            raise ValueError('Retained SDF and pose table energies disagree')
        if not all(math.isfinite(float(v)) for xyz in molecule.GetConformer().GetPositions() for v in xyz):
            raise ValueError('Retained pose contains nonfinite coordinates')
        cluster = int(row['cluster_id'])
        if cluster not in states:
            raise ValueError('Retained chemical-state identity is missing')
        records.append({'molecule': molecule, 'pose_path': root / 'all_poses.sdf',
                        'source': row['source'],
                        'seed': int(row['seed']) if row['seed'] else None,
                        'conformer': row['conformer'],
                        'model': int(row['model']) if row['model'] else None,
                        'energy': energy, 'state': states[cluster]})
    if input_hashes(root) != before:
        raise ValueError('Retained analysis changed while it was being read')
    return records, before
