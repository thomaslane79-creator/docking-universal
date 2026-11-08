"""Local preparation diagnostics in a box's coordinate frame, never a waiver."""
from __future__ import annotations

import math
import copy
import ast
import hashlib
import json
from pathlib import Path
import re


def backend_residue_ids(text):
    """Read explicit backend identities, including list/dictionary diagnostics."""
    residues = set(re.findall(r"residue_key='([^:']+):([^']+)'", text))
    # Legacy charge diagnostics name the exact chain, component and author
    # number. Read only that diagnostic, never arbitrary colon-delimited paths.
    for chain, _component, number in re.findall(
            r'no Gasteiger parameters available for atom\s+[^:\s]+:([^:\s]*):'
            r'([A-Za-z0-9]{3})(-?\d+[A-Za-z]?):[^\s:]+', text, re.IGNORECASE):
        residues.add((chain, number))
    patterns = (
        r'(?:Template matching failed for|Requested altlocs not found|Residues with alternate location):\s*(\[[^\n]*?\])',
        r'Input residues\s+(\{[^\n]*?\})\s+not in residue_templates',
    )
    for pattern in patterns:
        for fragment in re.findall(pattern, text):
            try:
                values = ast.literal_eval(fragment)
            except (ValueError, SyntaxError):
                continue
            if not isinstance(values, (list, dict)):
                continue
            for value in values:
                if isinstance(value, str) and re.fullmatch(r'[^:\s/\\]*:-?\d+[A-Za-z]?', value):
                    residues.add(tuple(value.split(':', 1)))
    for first, second in re.findall(r'Expected \d+ paddings for \(([^,]+), ([^)]+)\)', text):
        for token in (first.strip(), second.strip()):
            if ':' in token:
                residues.add(tuple(token.split(':', 1)))
    return residues


def _project_reviewed_changes(record, geometry):
    """Locate reviewed changes in a later box using the pinned original model."""
    source = Path(record['source_path'])
    data = source.read_bytes()
    if hashlib.sha256(data).hexdigest() != record['source_sha256']:
        raise ValueError('Original receptor coordinates changed before box-impact review')
    from .receptor_model_review import inspect_source_data
    _, _, atoms, _ = inspect_source_data(data)
    choices = record.get('choices') or {}
    rows = list(choices.get('exclusions') or []) + list(choices.get('alternate_locations') or [])
    for change in record.get('changes') or []:
        rows.extend(change.get('generated_atoms') or [])
        rows.extend(change.get('rejected_inferred_edges') or [])
        rows.extend(endpoint for edge in change.get('rejected_inferred_interresidue_edges') or []
                    for endpoint in (edge['first'], edge['second']))
    selected = {tuple(row.get(key, '') for key in ('resname', 'chain', 'number', 'insertion_code'))
                for row in rows}
    if not selected <= atoms.keys():
        raise ValueError('A reviewed residue cannot be located in the pinned original model')
    generated = {(tuple(row.get(key, '') for key in ('resname', 'chain', 'number', 'insertion_code')),
                  row['atom_name']) for change in record.get('changes') or []
                 for row in change.get('generated_atoms') or []}
    modeled = {}
    if generated:
        model_data = Path(record['model_path']).read_bytes()
        if hashlib.sha256(model_data).hexdigest() != record['model_input_sha256']:
            raise ValueError('Reviewed model changed before modeled-atom box review')
        _, _, modeled, _ = inspect_source_data(model_data)
    residues = []
    for key in sorted(selected):
        coordinates = [tuple(float(line[start:start + 8]) for start in (30, 38, 46))
                       for line in atoms[key] if line[76:78].strip().upper() not in {'H', 'D'}]
        coordinates.extend(tuple(float(line[start:start + 8]) for start in (30, 38, 46))
                           for line in modeled.get(key, [])
                           if (key, line[12:16].strip()) in generated)
        if not coordinates:
            raise ValueError('A reviewed residue has no heavy-atom coordinates for box-impact review')
        residues.append({'residue': key[0], 'chain': key[1], 'number': key[2] + key[3],
                         'coordinates': coordinates})
    return for_box({'residues': residues}, geometry)['residues']


def candidate_with_model_change_review(state, candidate, *, geometry_override=None):
    """Decorate a GUI copy; reopening a box must not hide a successful override."""
    if candidate is None:
        return None
    from .pocket_review import candidate_with_input_ligand_evidence
    candidate = candidate_with_input_ligand_evidence(state, candidate)
    history_artifact = next((a for a in state.artifacts if a.kind == 'receptor_model_history'), None)
    if history_artifact is None:
        return candidate
    result = copy.deepcopy(candidate)
    evidence = result.setdefault('evidence', {})
    try:
        path = Path(history_artifact.path)
        if hashlib.sha256(path.read_bytes()).hexdigest() != history_artifact.sha256:
            raise ValueError('Saved receptor-model history has changed')
        history = json.loads(path.read_text())
        prepared = next(a for a in state.artifacts if a.kind == 'prepared_receptor')
        from .receptor_model_history import normalize_preparation
        warning = normalize_preparation({'model_change_history': history}, prepared.sha256)['receptor_modification_warning']
        text = 'User-approved receptor changes: ' + ' '.join(c['description'] for c in history['changes'][:2])
        if warning['severity'] == 'high':
            text = 'HIGH-SEVERITY MODEL CHANGE. ' + text
        review = {'status': 'prepared_with_reviewed_model_changes', 'warning': text,
                  'category': 'These changes remain flagged after successful preparation.',
                  'severity': warning['severity'], 'residues': [], 'persistent_warning_required': True,
                  'distance_is_permission_to_ignore': False}
        record = next((a for a in state.artifacts if a.kind == 'reviewed_receptor_model'
                       and a.sha256 == history.get('review_record_sha256')), None)
        if record is None:
            raise ValueError('The matching receptor-change approval record is unavailable')
        if record:
            record_path = Path(record.path)
            if hashlib.sha256(record_path.read_bytes()).hexdigest() != record.sha256:
                raise ValueError('Saved receptor-change approval record has changed')
            retained = json.loads(record_path.read_text())
            box = next((a for a in state.artifacts if a.id == candidate.get('box_artifact_id')), None)
            if box:
                box_path = Path(box.path)
                if hashlib.sha256(box_path.read_bytes()).hexdigest() != box.sha256:
                    raise ValueError('Saved docking box changed before receptor-change review')
                from docking_universal_box_candidates import config_geometry
                # Recompute for the actual box, including boxes created after
                # an early failed-preparation exclusion review. Never interpret
                # an empty pre-box preview as evidence of no affected residues.
                if retained.get('source_path') and retained.get('source_sha256'):
                    review['residues'] = _project_reviewed_changes(retained,
                        geometry_override if geometry_override is not None else config_geometry(box_path))
                else:
                    # Older retained records may contain only the original
                    # hash-bound per-box review; preserve that compatibility.
                    if geometry_override is not None and geometry_override != config_geometry(box_path):
                        raise ValueError('Original coordinates are unavailable for reviewing changes in an expanded box')
                    for index, region in enumerate(retained['context']['selected_regions']):
                        if region['sha256'] == box.sha256:
                            review['residues'] = retained['selected_box_review'][index]['residues']
                            break
                    else:
                        raise ValueError('No verified original coordinates or matching retained box-impact review')
            else:
                raise ValueError('Docking-box evidence is unavailable for receptor-change review')
        inside = [row for row in review['residues'] if row.get('inside_box')]
        method_changed = any(change['kind'] == 'preparation_method_change' for change in history['changes'])
        if method_changed:
            review['warning'] += ' The preparation-method change applies to the whole receptor and every docking box.'
            review['preparation_method_changed'] = True
        if inside:
            review['severity'] = 'high'
            review['warning'] += ' Reviewed receptor changes affect residues inside this box: ' + ', '.join(
                f"{row['residue']} {row['chain'] or '(blank)'}:{row['number']}" for row in inside) + '.'
        review['changes_inside_box'] = bool(inside) or method_changed
        evidence['receptor_model_review'] = review
    except (OSError, ValueError, KeyError, StopIteration, IndexError) as exc:
        evidence['receptor_model_review'] = {
            'status': 'model_change_evidence_unverified', 'severity': 'high', 'residues': [],
            'warning': 'This study has receptor-model changes, but their retained review could not be verified: ' + str(exc),
            'persistent_warning_required': True}
    return result


def collect_site_issues(preparation_root, source):
    logs = sorted((Path(preparation_root) / 'receptor').glob('receptor*.log'))
    text = '\n'.join(path.read_text(errors='replace') for path in logs)
    residues = backend_residue_ids(text)
    source_lines = Path(source).read_text().splitlines()
    unsupported_elements = {element.upper() for element in re.findall(
        r"Element ([A-Z][a-z]?) (?:doesn't|does not) have an implemented covalent radius", text)}
    residues.update((line[21:22].strip(), line[22:27].strip()) for line in source_lines
                    if line.startswith(('ATOM  ', 'HETATM'))
                    and line[76:78].strip().upper() in unsupported_elements)
    atoms = {}
    for line in source_lines:
        if not line.startswith(('ATOM  ', 'HETATM')) or line[76:78].strip().upper() in {'H', 'D'}:
            continue
        key = (line[21:22].strip(), line[22:27].strip())
        if key not in residues:
            continue
        try:
            xyz = tuple(float(line[i:i + 8]) for i in (30, 38, 46))
        except ValueError:
            continue
        if all(math.isfinite(v) for v in xyz):
            entry = atoms.setdefault(key, {'chain': key[0], 'number': key[1],
                                          'residue': line[17:20].strip(), 'coordinates': []})
            entry['coordinates'].append(xyz)
    intervention_path = Path(preparation_root) / 'receptor/preparation_intervention.json'
    intervention = {}
    if intervention_path.is_file():
        from .preparation_interventions import read_intervention_record
        intervention = read_intervention_record(intervention_path)
    return {'status': 'preparation_failed', 'residues': list(atoms.values()),
            'category': intervention.get('category', 'Receptor parameterization did not complete'),
            'scientific_concern': intervention.get('scientific_concern', ''),
            'recommended_action': intervention.get('recommended_action', ''),
            'unlocated_residue_ids': [':'.join(key) for key in sorted(residues - atoms.keys())],
            'diagnostic_logs': [str(p.resolve()) for p in logs],
            'diagnostic_scope': 'Backend-named residues; not a complete chemistry assessment.',
            'automatic_exclusions': False, 'automatic_repairs': False}


def for_box(record, geometry):
    """Minimum distance to the entire box, including 0 for atoms inside it."""
    values = {key: float(geometry[key]) for axis in 'xyz' for key in ('center_' + axis, 'size_' + axis)}
    if not all(math.isfinite(v) for v in values.values()) or any(values['size_' + a] <= 0 for a in 'xyz'):
        raise ValueError('A finite positive-size box is required for preparation-distance review')
    rows = []
    for residue in record.get('residues', []):
        coordinates = residue['coordinates']
        distance = min(math.sqrt(sum(max(abs(v - values['center_' + axis]) - values['size_' + axis] / 2, 0)**2
                                    for axis, v in zip('xyz', xyz))) for xyz in coordinates)
        rows.append({key: value for key, value in residue.items() if key != 'coordinates'} | {
            'minimum_distance_to_box_angstrom': distance, 'inside_box': distance == 0})
    return {key: value for key, value in record.items() if key != 'residues'} | {
        'residues': sorted(rows, key=lambda row: (row['minimum_distance_to_box_angstrom'], row['chain'], row['number'])),
        'distance_is_permission_to_ignore': False,
        'warning': 'Receptor preparation failed. These are distances to this whole box, not its center. '
                   'Distance alone does not establish safety. No residues were omitted by this review.'}
