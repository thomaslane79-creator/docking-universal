"""Retained PDB lookup availability, separate from scientific evidence counts."""


def lookup_coverage(record):
    skipped = record.get('skipped') or []
    failures = [item for item in skipped if str(item.get('reason', '')).startswith('download failed:')]
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
        return ('PDB lookup unavailable (internet required). Check connection/service. '
                'Local work can continue; this does not mean no supporting evidence exists.', True)
    if (record.get('coverage') or {}).get('failed_entry_count'):
        return ('PDB lookup incomplete · Some related structures could not be retrieved. '
                'Retained evidence remains usable; missing results are not evidence of absence.', True)
    if status == 'completed' and (record.get('coverage') or {}).get('observation_count') == 0:
        return ('PDB search completed · No qualifying ligand observations were found in the structures '
                'searched. This is not proof that supporting evidence does not exist.', False)
    return '', False
