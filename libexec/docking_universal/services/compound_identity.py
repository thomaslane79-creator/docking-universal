"""Display identities shared by library review and reports; filenames remain provenance."""
from pathlib import Path
import re


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
