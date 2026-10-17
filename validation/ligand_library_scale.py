"""Synthetic library-size acceptance, not a docking/scientific benchmark."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'libexec'))


def main():
    from rdkit import Chem
    from docking_universal.services import ligand_library as service
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    template = ROOT / 'examples/tutorials/01_bound_ligand/inputs/rilpivirine_pubchem.sdf'
    molecule = next(m for m in Chem.SDMolSupplier(str(template), removeHs=False) if m is not None)
    results = {'basis': 'Repeated retained rilpivirine chemistry/coordinates with unique names; size/UI test, not docking',
               'template_heavy_atoms': molecule.GetNumHeavyAtoms(), 'cases': []}
    for count in (1000, 10000):
        folder = args.output / str(count) / 'ligands'
        folder.mkdir(parents=True)
        source = folder / 'library.sdf'
        with Chem.SDWriter(str(source)) as writer:
            for index in range(count):
                molecule.SetProp('_Name', f'Rilpivirine {index + 1:05d}')
                writer.write(molecule)
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        start = time.perf_counter()
        library = service.inspect_ligand_library(folder)
        indexing = time.perf_counter() - start
        selection = {'fingerprint': library['fingerprint'],
                     'record_ids': [library['records'][i]['record_id'] for i in (0, 50, count - 1)]}
        start = time.perf_counter()
        with patch.object(service, '_scan', side_effect=AssertionError('Unexpected full library reparse')):
            image = service.ligand_record_preview(folder, library['fingerprint'], selection['record_ids'][0])
            first_preview = time.perf_counter() - start
            start = time.perf_counter()
            cached = service.ligand_record_preview(folder, library['fingerprint'], selection['record_ids'][0])
            cached_preview = time.perf_counter() - start
            start = time.perf_counter()
            _library, chosen = service.selected_library_records(folder, selection)
            selected_validation = time.perf_counter() - start
        case = {'records': count, 'file_bytes': source.stat().st_size, 'index_seconds': indexing,
                'first_preview_seconds': first_preview, 'cached_preview_seconds': cached_preview,
                'full_hash_selection_validation_seconds': selected_validation,
                'all_records_present': len(library['records']) == count,
                'selected_records': [row['source_record'] for row, _m in chosen],
                'cache_returns_identical_preview': image == cached,
                'source_unchanged': hashlib.sha256(source.read_bytes()).hexdigest() == before}
        assert case['all_records_present'] and case['selected_records'] == [1, 51, count]
        assert case['cache_returns_identical_preview'] and case['source_unchanged']
        results['cases'].append(case)
        print(json.dumps(case), flush=True)
    (args.output / 'scale-verification.json').write_text(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
