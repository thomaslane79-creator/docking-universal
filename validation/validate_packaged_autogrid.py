"""Local numerical map-parity check; no search and no structural uploads."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--gpf', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    record = {'status': 'running', 'reference': str(args.reference), 'candidate': str(args.candidate),
              'docking_searches': 0, 'map_comparisons': []}
    try:
        for arm, executable in (('reference', args.reference), ('candidate', args.candidate)):
            folder = args.out / arm; folder.mkdir()
            # Copy only local map input files, not previous outputs.
            for path in args.gpf.parent.iterdir():
                if path.suffix in ('.pdbqt', '.gpf', '.dat'):
                    shutil.copy2(path, folder / path.name)
            with (folder / 'run.log').open('w') as stream:
                subprocess.run([str(executable.resolve()), '-p', args.gpf.name, '-l', 'maps.glg'],
                    cwd=folder, stdout=stream, stderr=subprocess.STDOUT, check=True, timeout=180)
            if 'Successful Completion' not in (folder / 'maps.glg').read_text():
                raise ValueError('AutoGrid completion missing')
        reference = args.out / 'reference'; candidate = args.out / 'candidate'
        expected = sorted(p.name for p in reference.glob('*.map'))
        if not expected or expected != sorted(p.name for p in candidate.glob('*.map')):
            raise ValueError('Map inventory differs')
        for name in expected:
            left = (reference / name).read_text().splitlines()[6:]
            right = (candidate / name).read_text().splitlines()[6:]
            row = {'map': name, 'values': len(left), 'exact_numeric_payload': left == right}
            record['map_comparisons'].append(row)
            if left != right:
                raise ValueError(f'Numerical map payload differs: {name}')
        record['status'] = 'passed'
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
    (args.out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record))
    return 0 if record['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
