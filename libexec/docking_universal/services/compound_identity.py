"""Display identities shared by library review and reports; filenames remain provenance."""
from pathlib import Path
import re
import json


def retained_compound_name(study, compound_id):
    """Read presentation names without changing retained input or identifiers."""
    study = Path(study)
    identity = str(compound_id)
    try:
        overrides = json.loads((study / 'report' / 'compound_display_names.json').read_text())
        name = (overrides.get('names') or {}).get(identity)
        if isinstance(name, str) and name.strip():
            return name.strip()
    except (OSError, ValueError, AttributeError):
        pass
    try:
        inventory = json.loads((study / 'inputs' / 'compound_library_inventory.json').read_text())
        for row in inventory.get('compounds', inventory.get('entries', [])):
            if str(row.get('compound_id')) == identity and str(row.get('compound_name') or '').strip():
                return str(row['compound_name']).strip()
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return identity


def retained_compound_name_for_path(compound):
    compound = Path(compound)
    return retained_compound_name(compound.parent.parent, compound.name)


def compound_display_name(molecule, source, ordinal):
    def prop(key):
        return molecule.GetProp(key).strip() if molecule.HasProp(key) else ''

    # This library's retained identifier is substantially more useful than its
    # repeated SDF title (which is the name of the entire input library).
    if prop('Nextval_ID'):
        return 'Compound ' + prop('Nextval_ID')
    stem = Path(source).stem.casefold()
    for key in ('DockingUniversal_CompoundName', 'Name', '_Name'):
        name = prop(key)
        normalized = name.casefold()
        file_title = normalized == stem or stem.startswith(normalized + '_')
        if name and not file_title:
            return name
    for key in ('Compound_ID', 'compound_id', 'ID', 'PUBCHEM_COMPOUND_CID'):
        if prop(key):
            return 'Compound ' + prop(key)
    return f'Compound {ordinal}'
