"""Exact, explicitly reviewed PDB exclusions; never a permissive backend flag."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

STANDARD_AMINO_ACIDS = frozenset('ALA ARG ASN ASP CYS GLN GLU GLY HIS ILE LEU LYS MET PHE PRO SER THR TRP TYR VAL'.split())


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def residue_id(line, offset=0):
    return (line[17 + offset:20 + offset].strip(), line[21 + offset:22 + offset].strip(),
            line[22 + offset:26 + offset].strip(), line[26 + offset:27 + offset].strip())


def create_reviewed_exclusion(source, output_directory, residues, *, reviewed_source_sha256, actor, rationale):
    """Write a derivative plus an immutable local approval/change inventory.

    Exclusions specify exact (resname, chain, residue number, insertion code).
    Protein exclusions are allowed, but remain high-severity model changes and
    may fail subsequent strict parameterization. No additional residue is ever
    inferred, no atom is moved, and no valid parameterization is claimed here.
    """
    source, output = Path(source).resolve(), Path(output_directory).resolve()
    if not source.is_file() or sha256(source) != reviewed_source_sha256:
        raise ValueError('Reviewed receptor is missing or changed')
    if output.exists():
        raise ValueError('Reviewed exclusions require a new output directory')
    if not isinstance(actor, str) or not actor.strip() or not isinstance(rationale, str) or not rationale.strip():
        raise ValueError('An explicit approval actor and rationale are required')
    items = [tuple(row) for row in residues]
    if not items or len(items) != len(set(items)) or any(
            len(row) != 4 or any(not isinstance(v, str) for v in row) or not row[0] or not row[2]
            for row in items):
        raise ValueError('Supply unique exact residue identities; no wildcards or inferred removals')
    lines = source.read_text().splitlines(keepends=True)
    if sum(line.startswith('MODEL ') for line in lines) > 1:
        raise ValueError('Select one explicit receptor model before reviewing exclusions')
    chosen = set(items)
    atoms = [line for line in lines if line.startswith(('ATOM  ', 'HETATM'))]
    present = {residue_id(line) for line in atoms}
    if not chosen <= present:
        raise ValueError('An exact reviewed residue is absent; no name-only or partial matches are accepted')
    removed_atoms = [line for line in atoms if residue_id(line) in chosen]
    removed_serials = {int(line[6:11]) for line in removed_atoms}
    retained, changed_records = [], []
    for line in lines:
        if line.startswith(('ATOM  ', 'HETATM', 'ANISOU', 'TER   ')) and residue_id(line) in chosen:
            continue
        affected = False
        if line.startswith('LINK  '):
            affected = residue_id(line) in chosen or residue_id(line, 30) in chosen
        elif line.startswith('SSBOND'):
            ends = [('CYS', line[15:16].strip(), line[17:21].strip(), line[21:22].strip()),
                    ('CYS', line[29:30].strip(), line[31:35].strip(), line[35:36].strip())]
            affected = any(end in chosen for end in ends)
        elif line.startswith('CONECT'):
            serials = [int(line[start:start + 5]) for start in range(6, len(line.rstrip()), 5)
                       if line[start:start + 5].strip()]
            if serials and any(serial in removed_serials for serial in serials):
                changed_records.append({'original': line.rstrip(), 'action': 'prune connections to excluded atoms'})
                if serials[0] not in removed_serials:
                    remaining = [serials[0]] + [n for n in serials[1:] if n not in removed_serials]
                    if len(remaining) > 1:
                        retained.append('CONECT' + ''.join(f'{n:5d}' for n in remaining) + '\n')
                continue
        if affected:
            changed_records.append({'original': line.rstrip(), 'action': 'remove connection to excluded residue'})
        else:
            retained.append(line)
    # Source text and all remaining atom records (including occupancy/altloc)
    # remain exact, not a coordinate-format round trip through a modeling tool.
    assert [l for l in retained if l.startswith(('ATOM  ', 'HETATM'))] == [
        l for l in atoms if residue_id(l) not in chosen]
    if sha256(source) != reviewed_source_sha256:
        raise ValueError('Source changed during exclusion review')
    output.mkdir(parents=True)
    derivative = output / (source.stem + '_reviewed_exclusions.pdb')
    derivative.write_text(''.join(retained))
    (output / 'excluded_atoms.pdb').write_text(''.join(removed_atoms) + 'END\n')
    standard = [row for row in items if row[0] in STANDARD_AMINO_ACIDS]
    warning = {
        'severity': 'high' if standard else 'warning',
        'summary': 'User-approved receptor-model exclusion; the scored receptor differs from the deposited input.',
        'standard_amino_acids_excluded': len(standard), 'residues_excluded': len(items),
        'persistent_warning_required': True, 'exploratory_only': True,
        'recommended': False, 'parameterization_pass_is_not_scientific_validation': True,
    }
    record = {
        'schema_name': 'docking-universal-reviewed-receptor-exclusions', 'schema_version': 1,
        'source': str(source), 'source_sha256': reviewed_source_sha256,
        'derivative': str(derivative), 'derivative_sha256': sha256(derivative),
        'approval': {'actor': actor, 'rationale': rationale, 'scope': 'only the explicitly listed residue identities'},
        'excluded_residues': [dict(zip(('resname', 'chain', 'number', 'insertion_code'), row)) for row in items],
        'excluded_atom_count': len(removed_atoms), 'changed_connection_records': changed_records,
        'remaining_atom_records_unchanged': True, 'source_unchanged': True,
        'new_atoms_generated': 0, 'additional_residues_excluded': 0,
        'docking_ready': False, 'receptor_modification_warning': warning,
    }
    (output / 'reviewed_exclusions.json').write_text(json.dumps(record, indent=2) + '\n')
    return record
