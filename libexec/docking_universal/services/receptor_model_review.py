"""Exact receptor changes for explicit review, never automatic repair/removal."""
from __future__ import annotations

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path

from .reviewed_exclusions import STANDARD_AMINO_ACIDS, residue_id


def digest(data):
    return hashlib.sha256(data).hexdigest()


def identity(row):
    keys = ('resname', 'chain', 'number', 'insertion_code')
    if not isinstance(row, dict) or set(row) - set(keys) - {'altloc'}:
        raise ValueError('Use exact residue identities; unknown change fields are not accepted')
    values = tuple(row.get(k, '') for k in keys)
    if any(not isinstance(v, str) for v in values) or not values[0] or not values[2]:
        raise ValueError('Residue name, chain, number and insertion code must be explicit strings')
    return values


def label(key):
    return f'{key[0]} {key[1] or "(blank chain)"}:{key[2]}{key[3]}'


def residue_record(key):
    return dict(zip(('resname', 'chain', 'number', 'insertion_code'), key))


def inspect_source(source):
    return inspect_source_data(Path(source).read_bytes())


def inspect_source_data(data):
    """Inspect one captured snapshot so hashes and parsed coordinates agree."""
    lines = data.decode('utf-8').splitlines(keepends=True)
    if sum(line.startswith('MODEL ') for line in lines) > 1:
        raise ValueError('Select one explicit structural model before receptor changes')
    atoms = defaultdict(list)
    serials = set()
    for line in lines:
        if not line.startswith(('ATOM  ', 'HETATM')):
            continue
        serial = int(line[6:11])
        if serial in serials:
            raise ValueError('Duplicate atom serials require input review before changing the receptor')
        serials.add(serial)
        xyz = tuple(float(line[i:i + 8]) for i in (30, 38, 46))
        occupancy = float(line[54:60].strip() or 0)
        if not all(math.isfinite(v) for v in (*xyz, occupancy)):
            raise ValueError('Nonfinite coordinates or occupancy require input review')
        atoms[residue_id(line)].append(line)
    if not atoms:
        raise ValueError('Receptor coordinates are empty')
    inventory = []
    for key, rows in atoms.items():
        alternatives = []
        for altloc in sorted({line[16:17].strip() for line in rows} - {''}):
            selected = [line for line in rows if line[16:17].strip() == altloc]
            alternatives.append({'altloc': altloc, 'atom_count': len(selected),
                'occupancy_min': min(float(line[54:60].strip() or 0) for line in selected),
                'occupancy_max': max(float(line[54:60].strip() or 0) for line in selected)})
        names = {line[12:16].strip() for line in rows}
        inventory.append({**residue_record(key), 'label': label(key), 'atom_count': len(rows),
                          'alternate_locations': alternatives,
                          'missing_backbone_atom_names': sorted({'N', 'CA', 'C', 'O'} - names)
                          if key[0] in STANDARD_AMINO_ACIDS else []})
    return data, lines, atoms, inventory


def preview_changes(source, choices, *, context):
    """Return a deterministic preview and in-memory derivative; write nothing."""
    if not isinstance(choices, dict) or set(choices) - {'exclusions', 'alternate_locations', 'sidechain_candidate', 'preparation_backend'}:
        raise ValueError('Only explicit exclusions, alternate locations and a reviewed side-chain candidate are supported')
    if 'preparation_backend' in choices and (not isinstance(choices['preparation_backend'], str)
                                           or choices['preparation_backend'] not in {'meeko', 'adfr'}):
        raise ValueError('Select an explicit Meeko or ADFRsuite preparation backend')
    data, lines, atoms, inventory = inspect_source(source)
    excluded_rows = choices.get('exclusions', [])
    alt_rows = choices.get('alternate_locations', [])
    if not isinstance(excluded_rows, list) or not isinstance(alt_rows, list):
        raise ValueError('Receptor changes must be lists of exact residue identities')
    excluded = [identity(row) for row in excluded_rows]
    reference = context.get('bound_reference')
    if reference and identity(reference) in excluded:
        raise ValueError('The selected bound reference ligand cannot be excluded from its control/site input')
    selected = [(identity(row), row.get('altloc')) for row in alt_rows]
    if len(excluded) != len(set(excluded)) or len(selected) != len({key for key, _ in selected}):
        raise ValueError('Each residue may appear only once in a change list')
    if set(excluded) & {key for key, _ in selected}:
        raise ValueError('A residue cannot be excluded and assigned an alternate location')
    if not (set(excluded) | {key for key, _ in selected}) <= atoms.keys():
        raise ValueError('An exact requested residue is absent from the reviewed coordinates')
    alternatives = dict(selected)
    for key, altloc in selected:
        if not isinstance(altloc, str) or len(altloc) != 1 or altloc not in {
                line[16:17].strip() for line in atoms[key]} - {''}:
            raise ValueError('Select an actual nonblank alternate location for the exact residue')
    # Shared blank-location atoms are kept. Chosen location labels become blank
    # so a later backend cannot silently choose another location or need A as a default.
    removed, retained, normalized = [], [], []
    for line in lines:
        if line.startswith(('ATOM  ', 'HETATM', 'ANISOU', 'TER   ')):
            key = residue_id(line)
            altloc = line[16:17].strip()
            if key in excluded or (key in alternatives and altloc and altloc != alternatives[key]):
                if line.startswith(('ATOM  ', 'HETATM')):
                    removed.append(line)
                continue
            if key in alternatives and altloc:
                normalized.append(line)
                line = line[:16] + ' ' + line[17:]
        retained.append(line)
    if not any(line.startswith('ATOM  ') for line in retained):
        raise ValueError('The changes would remove all protein coordinates')
    # Refuse duplicate atom identities instead of handing an ambiguous mixed
    # blank/chosen conformer to Meeko and pretending it was a resolved model.
    seen = set()
    for line in retained:
        if not line.startswith(('ATOM  ', 'HETATM')):
            continue
        key = (residue_id(line), line[12:16].strip(), line[16:17].strip())
        if key in seen:
            raise ValueError('Selected alternate location overlaps shared atom identities; review the input')
        seen.add(key)
    removed_serials = {int(line[6:11]) for line in removed}
    connections, result = [], []
    for line in retained:
        modified = line
        if line.startswith('CONECT'):
            numbers = [int(line[i:i + 5]) for i in range(6, len(line.rstrip()), 5) if line[i:i + 5].strip()]
            if any(n in removed_serials for n in numbers):
                kept = [n for n in numbers[1:] if n not in removed_serials]
                modified = ('CONECT' + ''.join(f'{n:5d}' for n in [numbers[0], *kept]) + '\n'
                            if numbers[0] not in removed_serials and kept else '')
        elif line.startswith('LINK  '):
            if any(residue_id(line, offset) in excluded for offset in (0, 30)):
                modified = ''
            else:
                for offset in (0, 30):
                    key = residue_id(line, offset)
                    alt = line[16 + offset:17 + offset].strip()
                    if key in alternatives and alt:
                        if alt != alternatives[key]:
                            modified = ''; break
                        modified = modified[:16 + offset] + ' ' + modified[17 + offset:]
        elif line.startswith('SSBOND'):
            ends = [('CYS', line[15:16].strip(), line[17:21].strip(), line[21:22].strip()),
                    ('CYS', line[29:30].strip(), line[31:35].strip(), line[35:36].strip())]
            if any(end in excluded for end in ends):
                modified = ''
        if modified != line:
            connections.append({'original': line.rstrip(), 'retained': modified.rstrip()})
        result.append(modified)
    derivative = ''.join(result).encode('utf-8')
    changes = []
    if excluded:
        standard = sum(key[0] in STANDARD_AMINO_ACIDS for key in excluded)
        changes.append({'kind': 'component_exclusion',
            'description': 'Excluded only these reviewed residues/components: ' + ', '.join(map(label, excluded)) + '.',
            'excluded_residues': [residue_record(key) for key in excluded],
            'removed_standard_amino_acids': standard, 'removed_other_components': len(excluded) - standard})
    if selected:
        changes.append({'kind': 'alternate_location_selection',
            'description': 'Selected deposited alternate locations: ' + ', '.join(
                f'{label(key)} = {alt}' for key, alt in selected) + '. Other locations were excluded; selected labels normalized to blank.',
            'selected_locations': [{**residue_record(key), 'altloc': alt} for key, alt in selected]})
    new_atoms = 0
    connectivity = None
    if 'sidechain_candidate' in choices:
        from .sidechain_candidate import apply_candidate
        derivative, reconstruction = apply_candidate(derivative, choices['sidechain_candidate'])
        connectivity = reconstruction.pop('connectivity_review', None)
        changes.append(reconstruction)
        new_atoms = reconstruction['modeled_heavy_atoms']
        if connectivity:
            changes.append(connectivity['change'])
    preview = {'schema_name': 'docking-universal-receptor-change-preview', 'schema_version': 1,
               'source_sha256': digest(data), 'model_input_sha256': digest(derivative),
               'context': context, 'choices': choices, 'changes': changes,
               'residue_inventory': inventory, 'removed_atom_count': len(removed),
               'selected_atom_labels_normalized': len(normalized), 'new_atoms_generated': new_atoms,
               'retained_atom_coordinates_unchanged': True, 'connection_changes': connections,
               'recommended': False, 'exploratory_only': True,
               'severity': 'high' if any(c.get('removed_standard_amino_acids') for c in changes) else 'warning',
               'persistent_warning_required': bool(changes), 'docking_ready': False}
    if connectivity:
        preview['connectivity_execution'] = connectivity['execution']
    preview['preview_sha256'] = digest(json.dumps(preview, sort_keys=True, separators=(',', ':')).encode())
    return preview, derivative


def write_model(root, source_name, preview, derivative, *, actor, rationale):
    if not preview['changes'] or not actor.strip() or not rationale.strip():
        raise ValueError('Explicit changes, approval actor and rationale are required')
    if digest(derivative) != preview['model_input_sha256']:
        raise ValueError('Reviewed model bytes changed')
    if Path(source_name).name != source_name or Path(source_name).suffix.lower() != '.pdb':
        raise ValueError('Use a single retained PDB filename inside the model directory')
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    model = root / 'model' / source_name
    model.parent.mkdir()
    model.write_bytes(derivative)
    record = {**preview, 'actor': actor, 'rationale': rationale,
              'model_path': str(model.resolve()), 'status': 'approved_changes_not_parameterized'}
    (root / 'reviewed_model.json').write_text(json.dumps(record, indent=2) + '\n')
    return model, record


def retain_reviewed_receptor_input(root, preview, derivative):
    """Keep the original receptor filter's inventory through explicit changes.

    Pruning a LINK during an approved exclusion must not make a second,
    unselected component disappear when the legacy filter runs again. Retain
    only atoms admitted by the original filter, plus explicitly modeled atoms,
    using the already reviewed full derivative's labels and coordinates.
    """
    from ..receptor_filter import filter_receptor_pdb
    root = Path(root)
    source = Path(preview['source_path'])
    if digest(source.read_bytes()) != preview['source_sha256'] or digest(derivative) != preview['model_input_sha256']:
        raise ValueError('Original source or reviewed model changed before retaining its receptor inventory')
    baseline = root / 'model/original_filtered_receptor.pdb'
    filter_receptor_pdb(source, baseline)
    allowed = {}
    context = []
    for line in baseline.read_text().splitlines(keepends=True):
        if line.startswith(('ATOM  ', 'HETATM')):
            allowed[(residue_id(line), line[12:16].strip())] = line[:6]
        else:
            context.append(line)
    modeled = {(tuple(row.get(key, '') for key in ('resname', 'chain', 'number', 'insertion_code')), row['atom_name'])
               for change in preview['changes'] for row in change.get('generated_atoms', [])}
    selected = list(context)
    for line in derivative.decode('utf-8').splitlines(keepends=True):
        if not line.startswith(('ATOM  ', 'HETATM')):
            continue
        key = (residue_id(line), line[12:16].strip())
        if key in allowed or key in modeled:
            selected.append(allowed.get(key, line[:6]) + line[6:])
    if not any(line.startswith('ATOM  ') for line in selected):
        raise ValueError('Reviewed receptor inventory contains no protein coordinates')
    output = root / 'model/reviewed_filtered_receptor.pdb'
    output.write_text(''.join(selected))
    if digest(source.read_bytes()) != preview['source_sha256']:
        raise ValueError('Original receptor source changed during inventory review')
    return {'path': str(output.resolve()), 'sha256': digest(output.read_bytes()),
            'baseline_path': str(baseline.resolve()), 'baseline_sha256': digest(baseline.read_bytes()),
            'policy': 'original receptor inventory with only the explicitly reviewed model changes'}


def validate_reviewed_model_inputs(record, record_path, record_sha256, *, additional_pins=None):
    """Reject input/approval mutation before a worker can be marked completed."""
    filtered = record['reviewed_receptor_input']
    pins = [
        ('Reviewed receptor model', record['model_path'], record['model_input_sha256']),
        ('Receptor change approval record', record_path, record_sha256),
        ('Original receptor review source', record['source_path'], record['source_sha256']),
        ('Reviewed receptor inventory', filtered['path'], filtered['sha256']),
        ('Original receptor inventory baseline', filtered['baseline_path'], filtered['baseline_sha256']),
    ]
    pins.extend(('Original receptor input', path, expected) for path, expected in (additional_pins or {}).items())
    for label, path, expected in pins:
        path = Path(path)
        if not path.is_file() or digest(path.read_bytes()) != expected:
            raise ValueError(label + ' changed during preparation: ' + str(path))
