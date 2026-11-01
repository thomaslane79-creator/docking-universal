"""Verify an explicitly reviewed local candidate; never generate or choose a model."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


SCHEMA = 'docking-universal-sidechain-candidate'
# Standard heavy side-chain atom identities. Backbone/terminal atoms and modified
# residues are deliberately outside this candidate-adoption contract.
SIDECHAINS = {
    'ALA': 'CB', 'ARG': 'CB CG CD NE CZ NH1 NH2', 'ASN': 'CB CG OD1 ND2',
    'ASP': 'CB CG OD1 OD2', 'CYS': 'CB SG', 'GLN': 'CB CG CD OE1 NE2',
    'GLU': 'CB CG CD OE1 OE2', 'GLY': '', 'HIS': 'CB CG ND1 CD2 CE1 NE2',
    'ILE': 'CB CG1 CG2 CD1', 'LEU': 'CB CG CD1 CD2', 'LYS': 'CB CG CD CE NZ',
    'MET': 'CB CG SD CE', 'PHE': 'CB CG CD1 CD2 CE1 CE2 CZ', 'PRO': 'CB CG CD',
    'SER': 'CB OG', 'THR': 'CB OG1 CG2', 'TRP': 'CB CG CD1 CD2 NE1 CE2 CE3 CZ2 CZ3 CH2',
    'TYR': 'CB CG CD1 CD2 CE1 CE2 CZ OH', 'VAL': 'CB CG1 CG2',
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _hash(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value)


def apply_candidate(parent, manifest_path):
    """Return verified model bytes and portable provenance, without writing files.

    The parent is the exact in-memory result of the separately reviewed
    exclusions/conformer choices. Removing only the declared new ATOM records
    must recover that parent byte for byte, including hydrogens and metadata.
    A receipt is a declaration of generation, not proof of chemical accuracy.
    """
    from .receptor_model_review import inspect_source_data, identity, label
    from .repair_geometry import introduced_heavy_atom_overlaps_from_atoms

    if not isinstance(manifest_path, str) or not manifest_path.strip():
        raise ValueError('Select an explicit local side-chain candidate receipt')
    path = Path(manifest_path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('The side-chain candidate receipt must be a regular local file')
    manifest_data = path.read_bytes()
    receipt = json.loads(manifest_data)
    required = {'schema_name', 'schema_version', 'parent_sha256', 'model_file',
                'model_sha256', 'generated_atoms', 'generator'}
    if (not isinstance(receipt, dict) or not required <= set(receipt) or set(receipt) - required - {'prior_model', 'connectivity_review'}
            or receipt['schema_name'] != SCHEMA or receipt['schema_version'] != 1):
        raise ValueError('Unsupported side-chain candidate receipt')
    if not _hash(receipt['parent_sha256']) or receipt['parent_sha256'] != _sha(parent):
        raise ValueError('Side-chain candidate belongs to a different reviewed parent model')
    name = receipt['model_file']
    if not isinstance(name, str) or Path(name).name != name or Path(name).suffix.lower() != '.pdb':
        raise ValueError('Candidate model must be a single PDB file beside its receipt')
    model_path = path.parent / name
    if model_path.is_symlink() or not model_path.is_file():
        raise ValueError('Candidate model must be a regular local file')
    model = model_path.read_bytes()
    if not _hash(receipt['model_sha256']) or _sha(model) != receipt['model_sha256']:
        raise ValueError('Side-chain candidate model hash changed')
    generator = receipt['generator']
    if (not isinstance(generator, dict) or set(generator) != {
            'method', 'software', 'seed', 'script_sha256', 'approval_sha256', 'audit_sha256'}
            or any(not isinstance(generator[k], str) or not generator[k].strip() for k in ('method', 'software'))
            or type(generator['seed']) is not int
            or any(not _hash(generator[k]) for k in ('script_sha256', 'approval_sha256', 'audit_sha256'))):
        raise ValueError('Candidate generation method, software, seed and provenance hashes are required')
    rows = receipt['generated_atoms']
    if not isinstance(rows, list) or not rows:
        raise ValueError('An exact nonempty generated-atom inventory is required')
    expected = {}
    for row in rows:
        if not isinstance(row, dict) or set(row) != {
                'resname', 'chain', 'number', 'insertion_code', 'atom_name', 'element'}:
            raise ValueError('Use exact generated atom identities and elements')
        key = identity({k: row[k] for k in ('resname', 'chain', 'number', 'insertion_code')})
        atom_name = row['atom_name']
        if (key[0] not in SIDECHAINS or not isinstance(atom_name, str)
                or atom_name not in SIDECHAINS[key[0]].split()
                or row['element'] != atom_name[0]):
            raise ValueError('Only missing standard side-chain heavy atoms are supported; no backbone additions')
        atom_key = (key, atom_name)
        if atom_key in expected:
            raise ValueError('A generated atom may be declared only once')
        expected[atom_key] = row

    # Read-only parser checks duplicate serials, nonfinite coordinates and models.
    _, model_lines, _, _ = inspect_source_data(model)
    parent_lines = parent.decode('utf-8').splitlines(keepends=True)
    original, original_serials = {}, set()
    for line in parent_lines:
        if not line.startswith(('ATOM  ', 'HETATM')):
            continue
        key = (identity_from_line(line), line[12:16].strip())
        # Unresolved locations elsewhere are left to strict preparation. They
        # may never be chosen or silently normalized by this candidate.
        original.setdefault(key, []).append(line)
        original_serials.add(int(line[6:11]))
    for (key, name) in expected:
        if (key, name) in original:
            raise ValueError('A proposed side-chain atom is already observed in the parent')
        residue_lines = [line for (r, _), lines in original.items() if r == key for line in lines]
        if (not residue_lines or any(line[16:17].strip() for line in residue_lines)
                or not {'N', 'CA', 'C', 'O'} <= {line[12:16].strip() for line in residue_lines}):
            raise ValueError('Side-chain additions require an existing, resolved, complete backbone')
    retained, found = [], set()
    all_xyz = []
    for line in model_lines:
        if not line.startswith(('ATOM  ', 'HETATM')):
            retained.append(line)
            continue
        key = (identity_from_line(line), line[12:16].strip())
        xyz = tuple(float(line[i:i + 8]) for i in (30, 38, 46))
        element = line[76:78].strip().upper()
        if key in expected:
            if (key in found or not line.startswith('ATOM  ') or line[16:17].strip()
                    or element != expected[key]['element'] or int(line[6:11]) in original_serials):
                raise ValueError('Generated atom records differ from the explicit candidate inventory')
            found.add(key)
        else:
            retained.append(line)
        if element not in {'H', 'D'}:
            all_xyz.append((key, xyz))
    if found != set(expected) or ''.join(retained).encode('utf-8') != parent:
        raise ValueError('Candidate changes observed records or adds/removes undeclared atoms or metadata')
    original_xyz = [(key, xyz) for key, xyz in all_xyz if key not in expected]
    if introduced_heavy_atom_overlaps_from_atoms(original_xyz, all_xyz):
        raise ValueError('Generated side-chain atoms introduce gross heavy-atom overlaps')
    generated = list(expected.values())
    descriptions = [f"{label(key)} {name}" for key, name in expected]
    prior_history = {}
    if 'prior_model' in receipt:
        prior = receipt['prior_model']
        if (not isinstance(prior, dict) or set(prior) != {'file', 'sha256', 'audit_sha256', 'regenerated_atoms'}
                or not _hash(prior['sha256']) or not _hash(prior['audit_sha256'])
                or not isinstance(prior['file'], str) or Path(prior['file']).name != prior['file']
                or Path(prior['file']).suffix.lower() != '.pdb'):
            raise ValueError('Prior reconstruction requires its exact model, audit hash and regenerated atom list')
        prior_path = path.parent / prior['file']
        if prior_path.is_symlink() or not prior_path.is_file():
            raise ValueError('Prior reconstructed model must be a regular local file')
        prior_data = prior_path.read_bytes()
        if _sha(prior_data) != prior['sha256']:
            raise ValueError('Prior reconstructed model hash changed')
        _, prior_lines, _, _ = inspect_source_data(prior_data)
        prior_atoms = {}
        for line in prior_lines:
            if not line.startswith(('ATOM  ', 'HETATM')):
                continue
            key = (identity_from_line(line), line[12:16].strip())
            if key in expected:
                if key in prior_atoms or line[16:17].strip():
                    raise ValueError('Prior modeled atom identities are ambiguous')
                prior_atoms[key] = line
        remodeled = prior['regenerated_atoms']
        if (not isinstance(remodeled, list) or not remodeled
                or any(row not in generated for row in remodeled)
                or len({json.dumps(row, sort_keys=True) for row in remodeled}) != len(remodeled)):
            raise ValueError('Regenerated atoms must be an exact nonempty subset of the full modeled inventory')
        remodeled_keys = {(_residue_key(row), row['atom_name']) for row in remodeled}
        if prior_atoms.keys() != expected.keys():
            raise ValueError('Prior reconstructed model has a different modeled inventory')
        if any(prior_atoms[key][76:78].strip().upper() != row['element'] for key, row in expected.items()):
            raise ValueError('A previously modeled atom element changed')
        proposed_atoms = {(identity_from_line(line), line[12:16].strip()): line for line in model_lines
                          if line.startswith(('ATOM  ', 'HETATM'))}
        for key in expected.keys() - remodeled_keys:
            if (prior_atoms[key][30:54] != proposed_atoms[key][30:54]
                    or prior_atoms[key][76:78] != proposed_atoms[key][76:78]):
                raise ValueError('A previously modeled atom outside the approved regeneration list changed')
        grouped = {}
        for row in remodeled:
            grouped.setdefault(_residue_key(row), []).append(row['atom_name'])
        detail = ', '.join(f"{label(key)} {'/'.join(names)}" for key, names in grouped.items())
        prior_history = {'prior_model_sha256': prior['sha256'], 'prior_generation_audit_sha256': prior['audit_sha256'],
                         'regenerated_atoms': remodeled, 'regenerated_heavy_atoms': len(remodeled),
                         'retained_modeled_heavy_atoms': len(generated) - len(remodeled)}
        description = (f"{len(generated)} modeled side-chain heavy atoms: "
                       f"{prior_history['retained_modeled_heavy_atoms']} retained unchanged; "
                       f"{len(remodeled)} regenerated ({detail}). Observed records unchanged; no backbone built. "
                       'Full atom inventory and generation history retained.')
    else:
        description = ('Reconstructed only these reviewed missing side-chain atoms: ' + ', '.join(descriptions)
                       + '. Observed records unchanged; no backbone or missing residues built. Local candidate generation: '
                       + generator['method'] + '.')
    change = {'kind': 'sidechain_reconstruction',
        'description': description,
        'generated_atoms': generated, 'modeled_heavy_atoms': len(generated),
        'parent_model_sha256': receipt['parent_sha256'], 'model_input_sha256': receipt['model_sha256'],
        'candidate_receipt_sha256': _sha(manifest_data), 'generator': generator,
        'observed_records_unchanged': True, 'backbone_atoms_added': 0,
        'generation_source': 'explicitly_reviewed_local_candidate', **prior_history}
    if 'connectivity_review' in receipt:
        from .reviewed_connectivity import validate_review
        review_path = receipt['connectivity_review']
        _, connectivity = validate_review(review_path, receipt['model_sha256'])
        change['connectivity_review'] = {'change': connectivity,
            'execution': {'path': str(Path(review_path).resolve()), 'sha256': connectivity['review_sha256']}}
    return model, change


def identity_from_line(line):
    return (line[17:20].strip(), line[21:22].strip(), line[22:26].strip(), line[26:27].strip())


def _residue_key(row):
    return tuple(row[k] for k in ('resname', 'chain', 'number', 'insertion_code'))
