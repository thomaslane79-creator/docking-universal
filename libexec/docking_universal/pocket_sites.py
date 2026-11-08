"""One selectable site for duplicate proposals, with exact source geometries.

This is presentation/decision consolidation, never a new box calculation.
Only hash-verified boxes in the same receptor frame may be grouped. Already
approved studies are immutable; older pending decisions are projected on read
and sealed by the existing explicit approval transaction.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
from dataclasses import replace
from pathlib import Path

from docking_universal_box_candidates import config_geometry

from .models import record_to_dict
from .pocket_metadata import region_prediction


def _verified_geometry(artifact):
    path = Path(artifact.path)
    if not artifact.sha256 or hashlib.sha256(path.read_bytes()).hexdigest() != artifact.sha256:
        raise ValueError('Retained docking box changed: ' + artifact.id)
    geometry = config_geometry(path)
    if len(geometry) != 6 or not all(math.isfinite(v) for v in geometry.values()) or any(
            geometry['size_' + axis] <= 0 for axis in 'xyz'):
        raise ValueError('Invalid retained docking box: ' + artifact.id)
    return geometry


def volume_overlap(left, right):
    """Intersection as a fraction of each box (not IoU or a center cutoff)."""
    intersection = 1.
    for axis in 'xyz':
        intersection *= max(0., min(left['center_' + axis] + left['size_' + axis] / 2,
                                   right['center_' + axis] + right['size_' + axis] / 2)
                            - max(left['center_' + axis] - left['size_' + axis] / 2,
                                  right['center_' + axis] - right['size_' + axis] / 2))
    return tuple(intersection / math.prod(g['size_' + axis] for axis in 'xyz') for g in (left, right))


def _frame(candidate):
    evidence = candidate.get('evidence') or {}
    # Missing values share the enclosing study's receptor frame. An explicit
    # variant may never be merged with that default or a different variant.
    keys = ('receptor_state', 'receptor_state_id', 'receptor_artifact_id',
            'receptor_sha256', 'coordinate_frame')
    return json.dumps({k: evidence.get(k, candidate.get(k)) for k in keys}, sort_keys=True)


def ligand_coordinates(path):
    """Read one retained PDB ligand's complete finite heavy-atom coordinates."""
    points, identities = [], set()
    for line in Path(path).read_text().splitlines():
        if not line.startswith(('ATOM  ', 'HETATM')):
            continue
        element = line[76:78].strip().upper() or line[12:16].strip().lstrip('0123456789')[:1].upper()
        if element in {'H', 'D'}:
            continue
        identities.add((line[17:20], line[21:27]))
        point = tuple(float(line[i:i+8]) for i in (30, 38, 46))
        if not all(math.isfinite(v) for v in point):
            raise ValueError('Nonfinite experimental ligand coordinates')
        points.append(point)
    if not points or len(identities) != 1:
        raise ValueError('Experimental evidence must identify one complete ligand instance')
    return points


def ligand_fits(points, geometry):
    return all(abs(v - geometry['center_' + axis]) <= geometry['size_' + axis] / 2
               for point in points for axis, v in zip('xyz', point))


def candidate_ligands(state, candidate, geometry):
    """Verified local/related observations that completely fit their own box."""
    from .services.pocket_review import candidate_with_input_ligand_evidence
    evidence = candidate_with_input_ligand_evidence(state, candidate, boundary_tolerance=0.)['evidence']
    local = (evidence.get('input_ligand_evidence') or {}).get('observations') or []
    related = (evidence.get('experimental_ligand_evidence') or {}).get('observations') or []
    assets = {str(Path(a.path).resolve()): a for a in state.artifacts}
    records = {}
    for observation in local + related:
        try:
            path = Path(observation['aligned_ligand_pdb']).resolve()
            asset = assets[str(path)]
            content = path.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            if not asset.sha256 or digest != asset.sha256:
                continue
            points = ligand_coordinates(path)
            if not ligand_fits(points, geometry):
                continue
            key = str(observation.get('source_ligand_id') or path) + '/' + digest
            records[key] = {'path': str(path), 'sha256': digest, 'heavy_atom_count': len(points),
                            'observation': copy.deepcopy(observation), 'points': points}
        except (OSError, KeyError, ValueError):
            continue
    return records


def consolidate_site_candidates(state):
    """Return copied candidate records plus a lossless grouping receipt."""
    originals = state.workflow_data.get('pocket_candidates') or []
    if any((c.get('evidence') or {}).get('site_group') for c in originals):
        return originals, None
    artifacts = {a.id: a for a in state.artifacts}
    geometries, ligands = {}, {}
    for candidate in originals:
        identity = candidate['id']
        try:
            geometries[identity] = _verified_geometry(artifacts[candidate['box_artifact_id']])
        except (OSError, KeyError, ValueError):
            continue  # Missing/unverified assets cannot justify consolidation.
        ligands[identity] = candidate_ligands(state, candidate, geometries[identity])

    def relationship(left, right):
        a, b = left['id'], right['id']
        if a not in geometries or b not in geometries or _frame(left) != _frame(right):
            return None
        # Two separately reviewed reference anchors retain separate authority.
        if all((c.get('evidence') or {}).get('reviewed_incomplete_reference') for c in (left, right)):
            return None
        fractions = volume_overlap(geometries[a], geometries[b])
        combined = {**(ligands.get(a) or {}), **(ligands.get(b) or {})}
        complete_ligands = bool(ligands.get(a) and ligands.get(b)) and all(
            ligand_fits(record['points'], geometries[identity])
            for record in combined.values() for identity in (a, b))
        identical_box = geometries[a] == geometries[b]
        if complete_ligands or identical_box:
            return {'left': a, 'right': b, 'overlap_fractions': list(fractions),
                    'reason': 'both_boxes_contain_all_experimental_ligands' if complete_ligands else 'identical_original_geometry',
                    'ligand_sha256s': sorted({r['sha256'] for r in combined.values()})}
        return None

    groups = []
    # Complete-link grouping prevents an A~B~C chain joining distinct A/C boxes.
    for candidate in originals:
        group = next((g for g in groups if all(relationship(candidate, other) for other in g)), None)
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)
    if all(len(group) == 1 for group in groups):
        return originals, None

    candidates, receipts = [], []
    for group in groups:
        if len(group) == 1:
            candidates.append(copy.deepcopy(group[0]))
            continue
        anchors = [c for c in group if (c.get('evidence') or {}).get('reviewed_incomplete_reference')]
        bound = [c for c in group if (c.get('evidence') or {}).get('source') == 'input_bound_ligand']
        exact_bound = [c for c in group if bound and geometries[c['id']] == geometries[bound[0]['id']]]
        representative = (anchors or exact_bound or group)[0]
        chosen = copy.deepcopy(representative)
        members = []
        for member in group:
            artifact = artifacts[member['box_artifact_id']]
            record = copy.deepcopy(member)
            record['box'] = record_to_dict(artifact)
            record['geometry'] = geometries[member['id']]
            prediction = region_prediction({'box': artifact.path, 'box_sha256': artifact.sha256,
                                            'box_label': member['id']})
            if prediction:
                record['pocket_prediction'] = prediction
            members.append(record)
        receipt = {'schema_version': 1, 'representative_id': chosen['id'],
                   'geometry_policy': 'unchanged original box; no averaging or union',
                   'member_ids': [c['id'] for c in group], 'members': members,
                   'relationships': [relationship(a, b) for i, a in enumerate(group) for b in group[i+1:]]}
        combined = {}
        for member in group:
            combined.update(ligands.get(member['id']) or {})
        receipt['ligands'] = [{k: copy.deepcopy(v) for k, v in record.items() if k != 'points'}
                              for record in combined.values()]
        receipt['sha256'] = hashlib.sha256(json.dumps(receipt, sort_keys=True).encode()).hexdigest()
        evidence = chosen.setdefault('evidence', {})
        evidence['site_group'] = receipt
        evidence['automation_eligible'] = all((c.get('evidence') or {}).get('automation_eligible', True) for c in group)
        evidence['requires_homolog_approval'] = any((c.get('evidence') or {}).get('requires_homolog_approval') for c in group)
        # Only an identical original geometry can inherit the bound-site role.
        # Other source evidence stays in members, without being asserted to fit
        # the representative or acquiring its detector score.
        if bound and geometries[chosen['id']] == geometries[bound[0]['id']] and evidence.get('source') != 'input_bound_ligand':
            evidence['input_bound_ligand'] = copy.deepcopy(bound[0]['evidence'])
        related = [r['observation'] for r in combined.values() if r['observation'].get('source') != 'input_structure'
                   and ligand_fits(r['points'], geometries[chosen['id']])]
        if related:
            classes = {}
            for observation in related:
                key = observation.get('evidence_class', 'unclassified')
                classes[key] = classes.get(key, 0) + 1
            evidence['experimental_ligand_evidence'] = dict(observations=related, observation_count=len(related),
                pdb_entry_count=len({r.get('entry') for r in related}), evidence_class_counts=classes)
        chosen['summary'] += '; one site from ' + ', '.join(receipt['member_ids'])
        candidates.append(chosen)
        receipts.append(receipt)
    for rank, candidate in enumerate(candidates, 1):
        candidate['rank'] = rank  # Source ranks remain unchanged in members.
    return candidates, {'schema_version': 1, 'original_candidates': copy.deepcopy(originals),
                        'groups': receipts}


def project_pending_site_review(state):
    """Read-only projection, also reused inside the explicit approval write."""
    decisions = [d for d in state.pending_decisions if d.kind == 'select_pockets']
    if not decisions or state.selected_pocket_ids:
        return state
    candidates, receipt = consolidate_site_candidates(state)
    if receipt is None:
        return state
    result = copy.deepcopy(state)
    result.workflow_data['pocket_candidates'] = candidates
    receipt['original_decisions'] = [record_to_dict(d) for d in decisions]
    result.workflow_data['pocket_site_grouping'] = receipt
    source = result.workflow_data.get('pocket_review_source')
    if source:
        source['candidate_count'] = len(candidates)
    for decision in result.pending_decisions:
        if decision.kind != 'select_pockets':
            continue
        options = {o.value: o for o in decision.options}
        decision.options = tuple(replace(options[c['id']], consequence=c['summary'],
            automation_eligible=(c.get('evidence') or {}).get('automation_eligible', True)) for c in candidates)
        decision.maximum_selections = min(decision.maximum_selections or len(candidates), len(candidates))
        decision.detected = f'{len(candidates)} candidate docking regions are available'
        decision.payload['candidate_ids'] = [c['id'] for c in candidates]
    return result


def verify_site_group_approval(state, selections):
    """Reject changed files before an explicit selection can seal the group."""
    artifacts = {a.id: a for a in state.artifacts}
    for candidate in state.workflow_data.get('pocket_candidates') or []:
        if candidate['id'] not in selections:
            continue
        artifact = artifacts.get(candidate.get('box_artifact_id'))
        if artifact is not None:
            _verified_geometry(artifact)
        group = (candidate.get('evidence') or {}).get('site_group')
        if not group:
            continue
        for member in group['members']:
            retained = artifacts[member['box_artifact_id']]
            if retained.sha256 != member['box']['sha256'] or _verified_geometry(retained) != member['geometry']:
                raise ValueError('Grouped site source changed: ' + member['id'])
        for ligand in group.get('ligands', []):
            if hashlib.sha256(Path(ligand['path']).read_bytes()).hexdigest() != ligand['sha256']:
                raise ValueError('Grouped experimental ligand changed')


def site_group_summary(group):
    """Small, readable source list for the existing expanded evidence window."""
    expanded = group.get('geometry_policy') == 'explicitly reviewed ligand-covering expansion'
    lines = [f"One site from {', '.join(group['member_ids'])}.",
             f"Docking uses the {'reviewed expanded' if expanded else 'unchanged'} {group['representative_id']} box."]
    for member in group['members']:
        prediction = member.get('pocket_prediction') or {}
        evidence = member.get('evidence') or {}
        score = prediction.get('score', evidence.get('score'))
        detector = prediction.get('detector', evidence.get('detector', ''))
        lines.append(f"{member['id']}: {detector + ' score ' + str(score) if score is not None else 'unscored'}; "
                     + member.get('summary', ''))
    lines.append('Source scores describe their original detector boxes, not the selected box or binding affinity.')
    return '\n'.join(lines)


def preview_site_expansion(state, candidate_ids, base_id):
    """Calculate a proposal only: extend a selected original box around ligands.

    Four Å per ligand face matches the existing bound-ligand box policy. No
    original face moves inward. Display every resulting dimension; 'small' is
    the user's judgement, never a hidden automatic size/overlap cutoff.
    """
    state = project_pending_site_review(state)
    if state.selected_pocket_ids or not any(d.kind == 'select_pockets' for d in state.pending_decisions):
        raise ValueError('Only an unapproved pending site review can be expanded')
    ids = list(candidate_ids)
    if len(ids) < 2 or len(set(ids)) != len(ids) or base_id not in ids:
        raise ValueError('Select at least two sites and one starting box')
    candidates = {c['id']: c for c in state.workflow_data.get('pocket_candidates', [])}
    selected = [candidates[i] for i in ids]
    verify_site_group_approval(state, ids)
    if len({_frame(c) for c in selected}) != 1:
        raise ValueError('Cannot combine different receptor states or coordinate frames')
    if any((c.get('evidence') or {}).get('reviewed_incomplete_reference') for c in selected):
        raise ValueError('A reviewed incomplete reference is tied to its exact original box; start a separate site review to change it')
    artifacts = {a.id: a for a in state.artifacts}
    geometries = {c['id']: _verified_geometry(artifacts[c['box_artifact_id']]) for c in selected}
    ligands = {}
    for candidate in selected:
        records = candidate_ligands(state, candidate, geometries[candidate['id']])
        if not records:
            raise ValueError(candidate['id'] + ' has no hash-verified complete experimental ligand. Regenerate its retained evidence before combining sites.')
        ligands.update(records)
    base = geometries[base_id]
    geometry, faces = {}, {}
    for coordinate, axis in enumerate('xyz'):
        values = [p[coordinate] for ligand in ligands.values() for p in ligand['points']]
        old_low = base['center_' + axis] - base['size_' + axis] / 2
        old_high = base['center_' + axis] + base['size_' + axis] / 2
        low, high = min(old_low, min(values) - 4.), max(old_high, max(values) + 4.)
        # Symmetric outward rounding preserves both faces when the engine
        # configuration is serialized with its established 0.001 Å precision.
        center = round((low + high) / 2, 3)
        size = math.ceil(2 * max(center - low, high - center) * 1000 - 1e-9) / 1000
        geometry['center_' + axis], geometry['size_' + axis] = center, size
        faces[axis] = {'lower_extension_angstrom': round(old_low - (center - size/2), 4),
                       'upper_extension_angstrom': round(center + size/2 - old_high, 4)}
    preview = {'schema_version': 1, 'candidate_ids': ids, 'base_id': base_id,
               'study_revision': state.revision, 'original_geometry': base, 'geometry': geometry,
               'face_extensions': faces, 'ligand_margin_angstrom': 4.,
               'boxes': [record_to_dict(artifacts[c['box_artifact_id']]) for c in selected],
               'ligands': [{k: copy.deepcopy(v) for k, v in ligand.items() if k != 'points'} for ligand in ligands.values()]}
    from .services.preparation_site_issues import candidate_with_model_change_review
    reviewed = candidate_with_model_change_review(state, candidates[base_id], geometry_override=geometry)
    preview['receptor_model_review'] = (reviewed.get('evidence') or {}).get('receptor_model_review')
    preview['preview_sha256'] = hashlib.sha256(json.dumps(preview, sort_keys=True).encode()).hexdigest()
    return preview


def apply_site_expansion(controller, study_id, candidate_ids, base_id, preview_sha256,
                         rationale, actor, expected_revision, request_id=None):
    """Stage one reviewed box in the existing pending decision; grant no approval."""
    from .decisions import DecisionOption
    from .models import ArtifactRecord
    from .state import RevisionConflictError
    from docking_universal_region import write_box_files
    state = controller.get_study(study_id)
    prior = next((r for r in state.workflow_data.get('site_expansion_history', [])
                  if request_id and r.get('request_id') == request_id), None)
    if prior:
        return prior
    if state.revision != expected_revision:
        raise RevisionConflictError('Study changed before the box expansion review')
    if not str(rationale or '').strip():
        raise ValueError('Record why these ligands should share a docking site')
    preview = preview_site_expansion(state, candidate_ids, base_id)
    if preview['preview_sha256'] != preview_sha256:
        raise ValueError('Site expansion preview changed; review the new proposal')
    projected = project_pending_site_review(state)
    candidates = projected.workflow_data['pocket_candidates']
    selected = [c for c in candidates if c['id'] in candidate_ids]
    all_ids = {c['id'] for c in candidates}
    number = next(n for n in range(1, len(candidates) + 2) if 'E' + str(n) not in all_ids)
    identity = 'E' + str(number)
    path = controller.store.path_for(study_id).parent / 'site-boxes' / (identity + '-' + preview_sha256[:16] + '.conf')
    write_box_files(path, preview['geometry'])
    artifact = ArtifactRecord('expanded-site-' + preview_sha256[:16], 'docking_box', str(path.resolve()),
                              hashlib.sha256(path.read_bytes()).hexdigest(), 'User-reviewed ligand-covering box expansion')
    if config_geometry(path) != preview['geometry']:
        raise ValueError('Written expansion differs from its reviewed geometry')
    sources = {a.id: a for a in state.artifacts}
    members = []
    for candidate in selected:
        old_group = (candidate.get('evidence') or {}).get('site_group')
        if old_group:
            members.extend(copy.deepcopy(old_group['members']))
        else:
            member = copy.deepcopy(candidate)
            member['box'] = record_to_dict(sources[candidate['box_artifact_id']])
            member['geometry'] = _verified_geometry(sources[candidate['box_artifact_id']])
            prediction = region_prediction({'box': member['box']['path'], 'box_sha256': member['box']['sha256'],
                                            'box_label': candidate['id']})
            if prediction:
                member['pocket_prediction'] = prediction
            members.append(member)
    group = {'schema_version': 1, 'representative_id': identity,
             'geometry_policy': 'explicitly reviewed ligand-covering expansion',
             'member_ids': [m['id'] for m in members], 'members': members, 'ligands': preview['ligands'],
             'relationships': [{'reason': 'user_reviewed_ligand_expansion', 'preview_sha256': preview_sha256}]}
    group['expansion_review'] = {'preview': copy.deepcopy(preview), 'actor': str(actor),
                                'rationale': str(rationale).strip(), 'grants_approval': False}
    group['sha256'] = hashlib.sha256(json.dumps(group, sort_keys=True).encode()).hexdigest()
    combined = {'id': identity, 'label': identity, 'rank': min(c['rank'] for c in selected),
                'box_artifact_id': artifact.id, 'summary': 'Reviewed ligand-covering site from ' + ', '.join(candidate_ids),
                'evidence': {'kind': 'ligand_defined', 'source': 'reviewed_ligand_expansion',
                             'geometry': preview['geometry'], 'automation_eligible': False, 'site_group': group}}
    for key in ('receptor_state', 'receptor_state_id', 'receptor_artifact_id', 'receptor_sha256', 'coordinate_frame'):
        value = (selected[0].get('evidence') or {}).get(key, selected[0].get(key))
        if value is not None:
            combined['evidence'][key] = copy.deepcopy(value)
    related = [r['observation'] for r in preview['ligands'] if r['observation'].get('source') != 'input_structure']
    if related:
        classes = {}
        for row in related:
            key = row.get('evidence_class', 'unclassified'); classes[key] = classes.get(key, 0) + 1
        combined['evidence']['experimental_ligand_evidence'] = dict(observations=related, observation_count=len(related),
            pdb_entry_count=len({r.get('entry') for r in related}), evidence_class_counts=classes)
    receipt = dict(preview=preview, candidate_id=identity, actor=str(actor), rationale=str(rationale).strip(),
                   request_id=request_id, original_candidates=copy.deepcopy(candidates), grants_approval=False)

    def commit(current):
        # Recheck every bound input inside the transaction, including files
        # changed without a study revision while the dialog was open.
        if preview_site_expansion(current, candidate_ids, base_id)['preview_sha256'] != preview_sha256:
            raise ValueError('Site expansion inputs changed during review')
        projected_current = project_pending_site_review(current)
        current.workflow_data = projected_current.workflow_data
        current.decisions = projected_current.decisions
        rows = []
        for candidate in candidates:
            if candidate['id'] in candidate_ids:
                if not any(c['id'] == identity for c in rows):
                    rows.append(combined)
            else:
                rows.append(copy.deepcopy(candidate))
        for rank, candidate in enumerate(rows, 1):
            candidate['rank'] = rank
        current.workflow_data['pocket_candidates'] = rows
        current.workflow_data.setdefault('site_expansion_history', []).append(receipt)
        if current.workflow_data.get('pocket_review_source'):
            current.workflow_data['pocket_review_source']['candidate_count'] = len(rows)
        current.artifacts.append(artifact)
        for decision in current.pending_decisions:
            if decision.kind != 'select_pockets':
                continue
            options = {o.value: o for o in decision.options}
            decision.options = tuple(DecisionOption(identity, identity, combined['summary'], automation_eligible=False)
                if c['id'] == identity else options[c['id']] for c in rows)
            decision.maximum_selections = min(decision.maximum_selections or len(rows), len(rows))
            decision.payload['candidate_ids'] = [c['id'] for c in rows]
            decision.detected = f'{len(rows)} candidate docking regions are available'
            decision.artifact_ids += (artifact.id,)
        verify_site_group_approval(current, [identity])
        return receipt
    _, result = controller.store.update(study_id, commit, expected_revision=expected_revision)
    return result
