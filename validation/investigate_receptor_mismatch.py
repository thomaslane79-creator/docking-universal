"""Read-only investigation of the retained PDB/mmCIF preparation divergence.

No preparation, optimization, docking, network requests or scientific-state writes.
"""
from collections import Counter
import hashlib
import json
from pathlib import Path

import gemmi
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / 'validation/runs/full-scratch-two-paths-20261017'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def heavy_atoms(path):
    structure = gemmi.read_structure(str(path))
    return {(chain.name, residue.seqid.num, residue.seqid.icode.strip(), residue.name, atom.name.strip()):
            np.array((atom.pos.x, atom.pos.y, atom.pos.z))
            for chain in structure[0] for residue in chain if residue.het_flag == 'A'
            for atom in residue if atom.element.name not in ('H', 'D') and atom.altloc in ('\x00', 'A', ' ')}


def compare(left, right):
    a, b = heavy_atoms(left), heavy_atoms(right)
    keys = sorted(a.keys() & b.keys())
    differences = np.array([b[key] - a[key] for key in keys])
    translation = np.median(differences, axis=0)
    distances = np.linalg.norm(differences - translation, axis=1)
    return {'left_atom_count': len(a), 'right_atom_count': len(b), 'matched_atom_count': len(keys),
            'left_only_atoms': sorted(a.keys() - b.keys()), 'right_only_atoms': sorted(b.keys() - a.keys()),
            'translation_angstrom': translation.tolist(),
            'maximum_residual_angstrom': float(distances.max()),
            'rms_residual_angstrom': float(np.sqrt(np.mean(distances ** 2))),
            'named_atom_differences_above_0_01_angstrom': [
                {'atom': key, 'residual_angstrom': float(distance)}
                for key, distance in zip(keys, distances) if distance > .01]}


def pdbqt_atoms(path):
    return {(line[21:22].strip(), int(line[22:26]), line[26:27].strip(), line[17:20].strip(), line[12:16].strip()):
            {'charge': float(line[70:76]), 'type': line[77:].strip()}
            for line in path.read_text().splitlines() if line.startswith(('ATOM  ', 'HETATM'))}


def main():
    out = RUN / 'receptor-investigation'
    out.mkdir(exist_ok=False)
    series = json.loads((RUN / 'summary.json').read_text())
    roots = [RUN / name / 'preparation/2R8N_receptor_prep' for name in ('fresh-download', 'local-pdb')]
    raw = [Path(case['source']) for case in series['cases']]
    filtered = [root / 'receptor/2R8N_filtered.pdb' for root in roots]
    prepared = [roots[0] / 'receptor/2R8N.pdb', roots[1] / 'receptor/2R8N_reduce2H.pdb']
    pdbqt = [root / 'receptor/2R8N.pdbqt' for root in roots]
    audits = [root / 'receptor/reduce2_audit.json' for root in roots]
    logs = [root / 'receptor/reduce2.log' for root in roots]
    evidence = [root / 'cavity/pdb_site_evidence/pdb_ligand_site_evidence.json' for root in roots]
    states = sorted(RUN.glob('*/state/*/application_state.json'))
    observed = [*raw, *filtered, *prepared, *pdbqt, *audits, *logs, *evidence, *states,
                Path(series['original_study']), Path(series['approved_bundle'])]
    before = {str(path): sha(path) for path in observed}
    record = {'status': 'investigating', 'new_preparation_or_docking_jobs': 0,
              'raw_input_comparison': compare(*raw), 'filtered_comparison': compare(*filtered),
              'prepared_comparison_after_translation': compare(*prepared),
              'reduce2_audits': [json.loads(path.read_text()) for path in audits]}
    left, right = map(pdbqt_atoms, pdbqt)
    record['charge_and_hydrogen_comparison'] = {
        'additional_atoms_in_pdb_route': sorted(right.keys() - left.keys()),
        'missing_atoms_in_pdb_route': sorted(left.keys() - right.keys()),
        'shared_atoms_with_changed_charges': [key for key in sorted(left.keys() & right.keys())
                                            if left[key]['charge'] != right[key]['charge']],
        'total_partial_charge_mmcif_route': sum(value['charge'] for value in left.values()),
        'total_partial_charge_pdb_route': sum(value['charge'] for value in right.values()),
    }
    shift = np.array(record['prepared_comparison_after_translation']['translation_angstrom'])
    boxes = [case['approval_comparison']['geometry'] for case in series['cases']]
    centers = [np.array([float(box['center_' + axis]) for axis in 'xyz']) for box in boxes]
    record['box_comparison'] = {'center_difference_angstrom': (centers[1] - centers[0]).tolist(),
                               'translation_matches_receptor': bool(np.allclose(centers[1] - centers[0], shift, atol=1e-10, rtol=0)),
                               'sizes_equal': all(boxes[0]['size_' + axis] == boxes[1]['size_' + axis] for axis in 'xyz')}
    record['evidence_comparison'] = []
    for path in evidence:
        data = json.loads(path.read_text())
        record['evidence_comparison'].append({
            'path': str(path), 'observations': len(data['evidence']),
            'matched_cavity_counts': dict(Counter(str(item.get('matched_cavity')) for item in data['evidence'])),
            'first_ligand': data['evidence'][0]['source_ligand_id'],
            'first_ligand_distance_to_p1_box_angstrom': data['evidence'][0]['pocket_relationships'][0]['minimum_distance_to_box_angstrom'],
        })
    mmcif_log = logs[0].read_text()
    installed_helper = Path('/opt/anaconda3/envs/docking-universal/libexec/docking-universal/docking-universal-reduce2-receptor.py')
    text = installed_helper.read_text()
    record['root_cause_evidence'] = {
        'mmcif_reduce2_log_reports_success': 'Job complete' in mmcif_log,
        'mmcif_reduce2_log_reports_cif_output': 'Wrote 2R8N_filteredFH.cif' in mmcif_log,
        'installed_wrapper_searches_only_pdb_output': 'glob(f"{work.stem}*H.pdb")' in text,
        'installed_wrapper_input_atom_reader_is_pdb_line_only': 'line.startswith(("ATOM  ", "HETATM"))' in text,
        'local_filtered_pdb_has_crystal_record': 'CRYST1' in filtered[1].read_text(),
        'local_reduced_output_has_synthetic_p1_cell': 'P 1' in prepared[1].read_text().splitlines()[0],
        'installed_wrapper': str(installed_helper), 'installed_wrapper_sha256': sha(installed_helper),
    }
    assert record['raw_input_comparison']['matched_atom_count'] == 754
    assert record['raw_input_comparison']['maximum_residual_angstrom'] == 0
    assert record['filtered_comparison']['maximum_residual_angstrom'] == 0
    assert record['box_comparison']['translation_matches_receptor']
    assert all(sha(path) == expected for path, expected in before.items())
    assert sha(series['original_study']) == series['original_study_sha256']
    record.update(status='diagnosed', observed_files_unchanged=True, file_sha256=before,
                  interpretation='Preparation integration defects, not different source protein coordinates. Keep the series stopped; fix and validate mmCIF output handling and receptor/evidence frame preservation before new approvals or searches.')
    (out / 'comparison.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('status', 'new_preparation_or_docking_jobs',
                     'raw_input_comparison', 'box_comparison', 'root_cause_evidence')}, indent=2))


if __name__ == '__main__':
    main()
