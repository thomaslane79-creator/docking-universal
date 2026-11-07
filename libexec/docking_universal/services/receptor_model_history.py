"""Portable, hash-bound model-change provenance; never authorizes a repair."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re

SCHEMA = 'docking-universal-receptor-model-history'
KINDS = {'sidechain_reconstruction', 'component_exclusion', 'manual_receptor_edit',
         'partial_residue_reconstruction', 'alternate_location_selection', 'atom_label_normalization',
         'standard_residue_connectivity_override', 'preparation_method_change'}


def recorded_backend_summary(audit_path):
    """Prefer accepted routing or retained failure evidence over log existence."""
    path = Path(audit_path)
    try:
        audit = json.loads(path.read_text())
    except (OSError, ValueError, TypeError):
        audit = {}
    routes = {
        'adfr_primary': 'ADFRsuite selected as the primary receptor-preparation backend; the retained backend log records the applied path',
        'adfr_legacy_linked_component_fallback': 'legacy ADFRsuite fallback after Meeko rejected a linked deposited component',
        'strict_meeko': 'strict Meeko succeeded; PDBFixer was not needed',
        'pdbfixer_then_strict_meeko': 'conservative PDBFixer repair followed by strict Meeko',
        'meeko_disulfide_templates': 'strict Meeko succeeded after a CYX disulfide-template retry',
        'guided_histidine_template': 'strict Meeko succeeded after an explicit histidine-template review',
        'meeko_user_approved_component_removal': 'user-approved removal of unmatched receptor components after safe preparation fallbacks failed',
    }
    if isinstance(audit, dict) and audit.get('preparation_route') in routes:
        route = audit['preparation_route']
        # Preserve existing richer Reduce2/PDB2PQR summaries unless an ADFR
        # route or leftover ADFR log actually requires disambiguation.
        if route.startswith('adfr_') or path.with_name('receptor_adfr_fallback.log').is_file():
            return routes[route]
        return None
    # Failed startup or rejected output can leave an ADFR log. That file alone
    # must never become a claim that the legacy backend prepared a receptor.
    try:
        intervention = json.loads(path.with_name('preparation_intervention.json').read_text())
    except (OSError, ValueError, TypeError):
        return None
    fallback = intervention.get('adfr_fallback') if isinstance(intervention, dict) else None
    if isinstance(fallback, dict) and fallback.get('status') not in {None, 'not_needed', 'succeeded'}:
        return 'Receptor preparation stopped; ADFRsuite status ' + str(fallback['status']) + ': ' + str(fallback.get('reason') or 'Inspect the retained preparation intervention.')
    return None


def validate_history(history, expected_receptor_sha256=None):
    if not isinstance(history, dict) or history.get('schema_name') != SCHEMA or history.get('schema_version') != 1:
        raise ValueError('Unsupported receptor-model change history')
    for key in ('original_input_sha256', 'model_input_sha256', 'prepared_receptor_sha256'):
        if not re.fullmatch('[0-9a-f]{64}', str(history.get(key, ''))):
            raise ValueError('Receptor-model history requires complete input/output hashes')
    if expected_receptor_sha256 and history['prepared_receptor_sha256'] != expected_receptor_sha256:
        raise ValueError('Receptor-model history belongs to a different prepared receptor')
    changes = history.get('changes')
    if not isinstance(changes, list) or not changes:
        raise ValueError('Receptor-model history requires an explicit nonempty change inventory')
    for row in changes:
        if not isinstance(row, dict) or row.get('kind') not in KINDS:
            raise ValueError('Unsupported receptor-model change type')
        if any(not isinstance(row.get(k), str) or not row[k].strip() for k in ('description', 'actor', 'rationale')):
            raise ValueError('Model changes require a description, approval actor and rationale')
        for key in ('removed_standard_amino_acids', 'removed_other_components', 'modeled_heavy_atoms'):
            value = row.get(key, 0)
            if type(value) is not int or value < 0:
                raise ValueError('Model-change counts must be nonnegative integers')
        if row['kind'] == 'preparation_method_change':
            if (not isinstance(row.get('previous_backend'), str)
                    or not isinstance(row.get('preparation_backend'), str)
                    or row['previous_backend'] not in {'meeko', 'adfr'}
                    or row['preparation_backend'] not in {'meeko', 'adfr'}
                    or row['previous_backend'] == row['preparation_backend']
                    or row.get('input_coordinates_unchanged') is not True
                    or row.get('input_atom_inventory_unchanged') is not True
                    or any(row.get(key, 0) for key in ('removed_standard_amino_acids', 'removed_other_components', 'modeled_heavy_atoms'))):
                raise ValueError('Preparation-method changes require distinct known methods and unchanged input atoms/coordinates')
        if row['kind'] == 'standard_residue_connectivity_override':
            if (row.get('coordinate_changes') != 0 or row.get('atoms_removed') != 0
                    or row.get('strict_valence_checks_retained') is not True
                    or row.get('coordinate_stage_reused') is not True
                    or not isinstance(row.get('rejected_inferred_edges'), list) or not row['rejected_inferred_edges']):
                raise ValueError('Connectivity history must retain exact edges, atoms/coordinates and strict checks')
            for key in ('backend_input_sha256', 'source_model_sha256', 'review_sha256', 'authority_sha256'):
                if not re.fullmatch('[0-9a-f]{64}', str(row.get(key, ''))):
                    raise ValueError('Connectivity history requires complete source/authority hashes')
    return history


def normalize_preparation(preparation, expected_receptor_sha256=None):
    """Preserve old warnings and regenerate mandatory warnings from inline history."""
    result = copy.deepcopy(preparation or {})
    if result.get('site_reference_review') is not None:
        from .site_reference_review import normalize
        result['site_reference_review'] = normalize(result['site_reference_review'], expected_receptor_sha256)
    if result.get('model_change_history') is None:
        return result
    history = validate_history(result['model_change_history'], expected_receptor_sha256)
    changes = history['changes']
    standard = sum(row.get('removed_standard_amino_acids', 0) for row in changes)
    high = bool(standard or any(row['kind'] in {'manual_receptor_edit', 'partial_residue_reconstruction'} for row in changes))
    old = result.get('receptor_modification_warning') or {}
    if old.get('code') == 'reviewed-receptor-model-changes':
        old = result.get('prior_receptor_modification_warning') or {}
    elif old:
        result['prior_receptor_modification_warning'] = copy.deepcopy(old)
    summary = 'The receptor differs from the original input following explicitly reviewed model changes. '
    descriptions = []
    for row in changes[:2]:
        text = row['description'].strip()
        descriptions.append(text if len(text) <= 240 else (text[:237].rsplit(' ', 1)[0] or text[:237]) + '...')
    summary += ' '.join(descriptions)
    if len(changes) > 2:
        summary += f' {len(changes) - 2} additional change entries are retained in the complete inventory.'
    if old.get('summary') and old['summary'] not in summary:
        summary += ' ' + old['summary']
    result['receptor_modification_warning'] = {
        **old, 'code': 'reviewed-receptor-model-changes',
        'severity': 'high' if high or old.get('severity') == 'high' else 'warning',
        'summary': summary, 'structural_review_required': True,
        'control_redocking_required': True, 'persistent_warning_required': True,
        'model_change_count': len(changes), 'removed_standard_amino_acid_count':
            standard + (old.get('removed_standard_amino_acid_count') or 0),
        'parameterization_success_is_not_scientific_validation': True,
    }
    return result


def attach_retained_history(preparation, preparation_root, receptor_pdbqt):
    path = Path(preparation_root) / 'receptor/receptor_model_history.json'
    result = copy.deepcopy(preparation)
    if path.is_file():
        result['model_change_history'] = json.loads(path.read_text())
    digest = hashlib.sha256(Path(receptor_pdbqt).read_bytes()).hexdigest()
    return normalize_preparation(result, digest)
