"""Observe official Conda-forge build availability; not a solver/native test."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
from pathlib import Path
import urllib.request

SPECS = {'python': '3.9.23', 'fpocket': '4.2.2', 'qvina': '2.1.0', 'vina': '1.2.7',
         'cctbx-base': None, 'pymol-open-source': '3.1.0', 'plip': '2.3.1',
         'molscrub': '0.2.2', 'pdbfixer': '1.11', 'rdkit': '2023.09.6',
         'openbabel': '3.1.1', 'pyqt6': None, 'glew': '2.3.0'}
PLATFORMS = ('win-64', 'linux-64', 'osx-arm64', 'osx-64')


def inspect(item):
    name, version = item
    url = 'https://api.anaconda.org/package/conda-forge/' + name
    row = {'package': name, 'requested_version': version, 'source': url}
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            metadata = json.load(response)
        builds = metadata['files']
        selected = [f for f in builds if version is None or f.get('version') == version]
        row['platforms'] = {target: {'matching_build_count': sum(
            f.get('attrs', {}).get('subdir') in (target, 'noarch') for f in selected),
            'any_version_published': any(f.get('attrs', {}).get('subdir') in (target, 'noarch') for f in builds)}
            for target in PLATFORMS}
        row['status'] = 'observed'
    except Exception as exc:
        row.update(status='unavailable', error=str(exc))
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.out.exists():
        parser.error('Choose a new output file; do not overwrite prior observations')
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(inspect, SPECS.items()))
    record = {'schema': 'docking-universal-platform-dependency-audit-v1',
        'checked_utc': datetime.now(timezone.utc).isoformat(), 'scope': 'Published builds only; no solving, installation or native acceptance',
        'packages': rows, 'missing_matching_builds': {target: [r['package'] for r in rows if
            r['status'] == 'observed' and r['platforms'][target]['matching_build_count'] == 0] for target in PLATFORMS}}
    args.out.write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record['missing_matching_builds']))
    return 0 if all(r['status'] == 'observed' for r in rows) else 1


if __name__ == '__main__':
    raise SystemExit(main())
