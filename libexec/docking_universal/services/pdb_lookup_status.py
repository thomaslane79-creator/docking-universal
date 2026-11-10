"""Retained PDB lookup availability, separate from scientific evidence counts."""


def lookup_coverage(record):
    skipped = record.get('skipped') or []
    failures = [item for item in skipped if str(item.get('reason', '')).startswith(
        ('download failed:', 'download or coordinate conversion failed:'))]
    return {'candidate_entry_count': len(record.get('candidate_entries') or []),
            'observation_count': len(record.get('evidence') or []),
            'failed_entry_count': len(failures),
            'failed_entries': [item.get('entry') for item in failures]}


def lookup_status_for_state(state):
    record = dict(state.workflow_data.get('pdb_pocket_evidence') or {})
    if not record:
        mode = (state.workflow_data.get('study_setup') or {}).get('pdb_pocket_evidence')
        if mode == 'off':
            record = {'mode': 'off', 'status': 'not_requested'}
    return record


def lookup_notice(record):
    """Return text/severity; missing history is not evidence that lookup ran."""
    if not record:
        return '', False
    status, mode = record.get('status'), record.get('mode')
    if mode == 'off':
        return ('Local-only evidence · PDB databank search is off. Local information and any retained '
                'evidence remain usable; additional public evidence has not been sought.', False)
    if status in {'unavailable', 'failed'}:
        return ('PDB search failed · Supporting evidence could not be checked. '
                'This does not mean no supporting evidence exists. A connection problem or PDB service error '
                'may have prevented the lookup. Local information and previously retained evidence remain usable.', True)
    if (record.get('coverage') or {}).get('failed_entry_count'):
        return ('PDB lookup incomplete · Some related structures could not be retrieved or processed. '
                'Retained evidence remains usable; missing results are not evidence of absence.', True)
    if status == 'completed' and (record.get('coverage') or {}).get('observation_count') == 0:
        return ('PDB search completed · No qualifying ligand observations were found in the structures '
                'searched. This is not proof that supporting evidence does not exist.', False)
    if status == 'completed' and 'observation_count' not in (record.get('coverage') or {}):
        return ('PDB search completed · Result counts were not retained. Review the available evidence; '
                'an unknown count does not mean no supporting evidence exists.', False)
    return '', False
