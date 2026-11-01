"""Exact reviewed incomplete site anchors, separate from receptor modifications."""
from __future__ import annotations

import copy
import hashlib
import json
import math
from pathlib import Path
import re

SCHEMA = 'docking-universal-reviewed-site-reference'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def seal(record):
    return digest(json.dumps(record, sort_keys=True, separators=(',', ':'), allow_nan=False).encode())


def normalize(record, expected_receptor_sha256=None):
    """Validate inline provenance and regenerate the warning without local files."""
    value = copy.deepcopy(record)
    if not isinstance(value, dict) or value.get('schema_name') != SCHEMA or value.get('schema_version') != 1:
        raise ValueError('Unsupported site-reference review')
    review = value.get('review')
    if not isinstance(review, dict) or value.get('review_sha256') != seal(review):
        raise ValueError('Site-reference review changed after explicit approval')
    for key in ('original_input_sha256', 'normalized_input_sha256', 'screening_input_sha256',
                'ccd_sha256', 'box_sha256', 'authority_sha256', 'receipt_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', str(review.get(key, ''))):
            raise ValueError('Site-reference review requires complete input/box/authority hashes')
    for key in ('actor', 'rationale', 'screening_smiles', 'candidate_id'):
        if not isinstance(review.get(key), str) or not review[key].strip():
            raise ValueError('Site-reference review requires explicit identity and rationale')
    identity = review.get('identity') or {}
    if (set(identity) != {'resname', 'chain_id', 'residue_number', 'insertion_code', 'altloc'}
            or not all(identity.get(k) for k in ('resname', 'chain_id', 'residue_number'))
            or identity.get('altloc')):
        raise ValueError('Incomplete anchor review requires one exact unambiguous deposited instance')
    found, complete = review.get('deposited_heavy_atoms'), review.get('complete_ccd_heavy_atoms')
    missing = review.get('missing_atom_names')
    if (type(found) is not int or type(complete) is not int or not 0 < found < complete
            or not isinstance(missing, list) or len(missing) != complete - found
            or len(set(missing)) != len(missing) or any(not isinstance(x, str) or not x for x in missing)):
        raise ValueError('Site-reference review requires an exact incomplete heavy-atom inventory')
    geometry = review.get('geometry') or {}
    if (set(geometry) != {p+a for p in ('center_', 'size_') for a in 'xyz'}
            or any(type(v) not in (float, int) or not math.isfinite(v) for v in geometry.values())
            or any(geometry['size_'+a] <= 0 for a in 'xyz')):
        raise ValueError('Site-reference review requires the unchanged six-field box')
    if (review.get('exploratory_site_only') is not True or review.get('atom_changes') != 0
            or review.get('chemistry_changes') != 0 or review.get('control_authority') is not False):
        raise ValueError('Site-reference review cannot authorize model/chemistry changes or controls')
    if expected_receptor_sha256 and value.get('prepared_receptor_sha256') != expected_receptor_sha256:
        raise ValueError('Site-reference review belongs to a different prepared receptor')
    name = f"{identity['resname']} {identity['chain_id']}:{identity['residue_number']}{identity['insertion_code']}"
    value['warning'] = (
        f'Reviewed incomplete reference {name}: {found}/{complete} heavy atoms deposited; '
        'existing coordinates define an exploratory site anchor only. Complete screening chemistry '
        'and stereochemistry come from the predeclared CCD-derived input, not reconstructed deposited atoms. '
        'No reference atoms were filled in and the frozen box was unchanged. '
        'The complete ligand chemistry/stereochemistry is not established by these coordinates. '
        'This is not a pose-recovery control and grants no receptor repair or removal authority.')
    return value


def stage(controller, study_id, payload, *, expected_revision, request_id):
    """Import a specifically approved receipt before the ordinary GUI box decision."""
    from ..state import RevisionConflictError
    from docking_universal_box_candidates import config_geometry
    from .bound_ligands import detect_bound_ligands
    import gemmi

    if set(payload) != {'receipt', 'reviewed_sha256'}:
        raise ValueError('Site-reference review accepts only an exact reviewed receipt')
    state = controller.get_study(study_id)
    if expected_revision is None or state.revision != expected_revision:
        raise RevisionConflictError('Study changed before site-reference review')
    active = state.active_job
    if ((active and (active.stage != 'pocket_review' or active.status.value != 'waiting_for_decision'))
            or state.selected_pocket_ids
            or state.workflow_data.get('receptor_parameterization_status') != 'not_started'
            or not any(d.kind == 'select_pockets' for d in state.pending_decisions)):
        raise ValueError('Review the reference before box approval and receptor parameterization')
    if state.workflow_data.get('reviewed_site_reference'):
        raise ValueError('A site-reference review is already retained; no replacement')
    data = Path(payload['receipt']).read_bytes()
    if digest(data) != payload['reviewed_sha256']:
        raise ValueError('Site-reference receipt changed after review')
    receipt = json.loads(data)
    if receipt.get('approved') is not True:
        raise ValueError('Explicit site-reference approval is required')
    files = {}
    for key in ('source', 'screening_input', 'ccd', 'authority'):
        item = receipt[key]
        snapshot = Path(item['path']).read_bytes()
        if digest(snapshot) != item['sha256']:
            raise ValueError('Reviewed site-reference input changed: ' + key)
        files[key] = snapshot
    authority = json.loads(files['authority'])
    if receipt.get('case_id') not in (authority.get('approved_cases') or []):
        raise ValueError('Direct reference authority does not include this exact case')
    setup = state.workflow_data['study_setup']
    if receipt['source']['sha256'] != setup['input_structure_sha256']:
        raise ValueError('Reviewed site reference belongs to another source structure')
    source = Path(setup['input_pdb'])
    normalized_hash = digest(source.read_bytes())
    identity = receipt['identity']
    instances = [i for c in detect_bound_ligands(source) for i in c.instances if i.identity == identity]
    if len(instances) != 1 or instances[0].altlocs:
        raise ValueError('Reviewed reference instance is missing or ambiguous')
    structure = gemmi.read_structure(str(source))
    if len(structure) != 1:
        raise ValueError('Reviewed reference requires one source model')
    residues = [r for c in structure[0] for r in c if c.name == identity['chain_id']
                and str(r.seqid.num) == identity['residue_number'] and r.name == identity['resname']
                and str(r.seqid.icode).strip('\x00 ?. ') == identity['insertion_code']]
    if len(residues) != 1:
        raise ValueError('Reviewed reference requires one source model and instance')
    observed = {a.name: a.element.name.upper() for a in residues[0] if a.element.name not in ('H', 'D')}
    ccd = gemmi.cif.read_string(files['ccd'].decode()).sole_block()
    if gemmi.cif.as_string(str(ccd.find_value('_chem_comp.id'))) != identity['resname']:
        raise ValueError('Reviewed reference CCD component differs from the deposited identity')
    atoms = {gemmi.cif.as_string(str(row[0])): gemmi.cif.as_string(str(row[1])).upper()
             for row in ccd.find('_chem_comp_atom.', ['atom_id', 'type_symbol'])
             if gemmi.cif.as_string(str(row[1])).upper() not in ('H', 'D')}
    if (set(observed) - set(atoms) or any(atoms[n] != e for n, e in observed.items())
            or len(observed) != receipt['deposited_heavy_atoms']
            or len(atoms) != receipt['complete_ccd_heavy_atoms']
            or sorted(set(atoms) - set(observed)) != receipt['missing_atom_names']):
        raise ValueError('Reviewed incomplete-reference atom inventory changed')
    candidates = []
    wanted = {k: identity[k] for k in ('resname', 'chain_id', 'residue_number', 'insertion_code')}
    artifacts = {a.id: a for a in state.artifacts}
    for candidate in state.workflow_data.get('pocket_candidates', []):
        evidence = candidate.get('evidence') or {}
        bound = evidence if evidence.get('source') == 'input_bound_ligand' else evidence.get('input_bound_ligand') or {}
        if bound.get('input_ligand_identity') == wanted:
            box = Path(artifacts[candidate['box_artifact_id']].path)
            geometry = config_geometry(box)
            if all(abs(geometry[k] - round(receipt['geometry'][k], 3)) < 0.0001 for k in geometry):
                candidates.append((candidate, box, geometry))
    if len(candidates) != 1:
        raise ValueError('Review requires the unchanged exact input-ligand box')
    candidate, box, geometry = candidates[0]
    review = {k: copy.deepcopy(receipt[k]) for k in ('identity', 'screening_smiles', 'deposited_heavy_atoms',
        'complete_ccd_heavy_atoms', 'missing_atom_names', 'actor', 'rationale')}
    review.update(original_input_sha256=receipt['source']['sha256'], normalized_input_sha256=normalized_hash,
        screening_input_sha256=receipt['screening_input']['sha256'], ccd_sha256=receipt['ccd']['sha256'],
        authority_sha256=receipt['authority']['sha256'], receipt_sha256=digest(data),
        box_sha256=digest(box.read_bytes()), geometry=geometry, candidate_id=candidate['id'],
        exploratory_site_only=True, atom_changes=0, chemistry_changes=0, control_authority=False)
    record = normalize(dict(schema_name=SCHEMA, schema_version=1, review=review, review_sha256=seal(review)))
    # Recheck the source snapshots before committing; no science or files are written.
    if digest(source.read_bytes()) != normalized_hash or any(
            digest(Path(receipt[k]['path']).read_bytes()) != digest(v) for k, v in files.items()):
        raise ValueError('Reference input changed during review')

    def commit(current):
        active = current.active_job
        if (current.revision != expected_revision or current.selected_pocket_ids
                or (active and (active.stage != 'pocket_review' or active.status.value != 'waiting_for_decision'))):
            raise RevisionConflictError('Study changed during reference review')
        current.workflow_data['reviewed_site_reference'] = record
        for row in current.workflow_data['pocket_candidates']:
            if row['id'] == candidate['id']:
                row['summary'] += '; ' + record['warning']
                row.setdefault('evidence', {})['reviewed_incomplete_reference'] = record
                row['evidence']['automation_eligible'] = False
        from dataclasses import replace
        for decision in current.pending_decisions:
            if decision.kind == 'select_pockets':
                decision.consequences += (record['warning'],)
                decision.presentation['site_reference_warning'] = record['warning']
                decision.options = tuple(replace(option,
                    consequence=option.consequence + '; ' + record['warning'], automation_eligible=False)
                    if option.value == candidate['id'] else option for option in decision.options)
    controller.store.update(study_id, commit)
    return record


def attach(preparation, state, receptor_sha256, regions):
    record = state.workflow_data.get('reviewed_site_reference')
    if record is None:
        return preparation
    record = normalize(record)
    review = record['review']
    if (state.selected_pocket_ids != [review['candidate_id']] or len(regions) != 1
            or regions[0]['box_sha256'] != review['box_sha256']):
        raise ValueError('Selected reference site changed after review')
    setup = state.workflow_data['study_setup']
    if (digest(Path(setup['input_structure']).read_bytes()) != review['original_input_sha256']
            or digest(Path(setup['input_pdb']).read_bytes()) != review['normalized_input_sha256']):
        raise ValueError('Source reference changed before finalization')
    record['prepared_receptor_sha256'] = receptor_sha256
    result = copy.deepcopy(preparation)
    result['site_reference_review'] = normalize(record, receptor_sha256)
    return result
