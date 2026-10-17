"""Hash-bound alpha visualization; never replaces retained detector decisions."""
import csv
import gzip
import hashlib
import json
import math
from pathlib import Path

VERSION = 'pocket-space-2.6-alpha-unfilled-v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def rows(path):
    with Path(path).open() as stream:
        return [{str(k).strip(): str(v or '').strip() for k, v in row.items()}
                for row in csv.DictReader(stream)]


def inputs(state):
    receptor = next((a for a in state.artifacts if a.kind == 'prepared_receptor_structure'), None)
    boxes = [Path(a.path) for a in state.artifacts if a.kind == 'docking_box']
    if receptor is None or not boxes:
        return None
    cavity = boxes[0].parent
    provenance = cavity / 'pocket_detection_provenance.json'
    if not provenance.is_file():
        return None
    record = json.loads(provenance.read_text())
    if record.get('engine') != 'p2rank':
        return None
    source = Path(record['source_predictions'])
    receptor_path = Path(receptor.path)
    if sha(receptor_path) != receptor.sha256 or Path(record['receptor']).resolve() != receptor_path.resolve():
        raise ValueError('Pocket-space visualization requires the unchanged prepared receptor')
    receptor_hash, predictions_hash = sha(receptor_path), sha(source)
    key = hashlib.sha256((VERSION + receptor_hash + predictions_hash).encode()).hexdigest()[:24]
    return dict(receptor=str(receptor_path.resolve()), predictions=str(source.resolve()),
                receptor_sha256=receptor_hash, predictions_sha256=predictions_hash,
                cache=str((cavity / 'pocket_space_visuals' / key).resolve()), version=VERSION)


def validate_output(record):
    """Fail closed if the alpha's ranks, scores, centers or residue sets differ."""
    cache = Path(record['cache'])
    if sha(record['receptor']) != record['receptor_sha256'] or sha(record['predictions']) != record['predictions_sha256']:
        raise ValueError('Pocket-space inputs changed during generation')
    name = Path(record['receptor']).name
    predicted = cache / 'alpha' / (name + '_predictions.csv')
    if rows(predicted) != rows(record['predictions']):
        raise ValueError('Alpha predictions do not exactly match retained P2Rank predictions; no grid attached')
    grid = cache / 'alpha' / 'visualizations' / 'data' / (name + '_pocket_grid.pdb.gz')
    ranks = {int(row['rank']) for row in rows(predicted)}
    counts = {}
    with gzip.open(grid, 'rt') as stream:
        for line in stream:
            if not line.startswith(('ATOM  ', 'HETATM')):
                continue
            rank = int(line[22:26])
            coords = [float(line[start:start+8]) for start in (30, 38, 46)]
            if rank not in ranks or not all(math.isfinite(v) for v in coords):
                raise ValueError('Invalid alpha pocket-grid coordinates or rank')
            counts[str(rank)] = counts.get(str(rank), 0) + 1
    if not counts:
        raise ValueError('Alpha did not export assigned pocket-space points')
    manifest = dict(record, grid=str(grid.resolve()), grid_sha256=sha(grid), counts=counts,
                    fill='none', spacing_angstrom=1.2, display_radius_angstrom=1.02,
                    meaning='Approximate surface of sampled predicted pocket space; not protein surface or exact cavity boundary')
    pending = cache / 'manifest.tmp'
    pending.write_text(json.dumps(manifest, indent=2) + '\n')
    pending.replace(cache / 'manifest.json')
    return manifest


def cached(record):
    path = Path(record['cache']) / 'manifest.json'
    if not path.is_file():
        return None
    if (sha(record['receptor']) != record['receptor_sha256']
            or sha(record['predictions']) != record['predictions_sha256']):
        return None
    manifest = json.loads(path.read_text())
    if any(manifest.get(key) != record.get(key) for key in
           ('version', 'receptor_sha256', 'predictions_sha256')):
        return None
    grid = Path(manifest['grid'])
    expected_grid = path.parent / 'alpha' / 'visualizations' / 'data' / (Path(record['receptor']).name + '_pocket_grid.pdb.gz')
    if grid.resolve() != expected_grid.resolve() or not grid.is_file() or sha(grid) != manifest['grid_sha256']:
        return None
    if (manifest.get('fill') != 'none' or manifest.get('display_radius_angstrom') != 1.02
            or manifest.get('spacing_angstrom') != 1.2):
        return None
    return manifest
