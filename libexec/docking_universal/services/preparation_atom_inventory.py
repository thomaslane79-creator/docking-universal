"""Describe missing atom names before modeling; no coordinate construction."""


def missing_atom_inventory(missing_atoms):
    rows = []
    for residue, atoms in missing_atoms.items():
        names = sorted(atom.name for atom in atoms)
        rows.append({'chain': residue.chain.id, 'residue': residue.name,
                     'number': residue.id, 'insertion_code': getattr(residue, 'insertionCode', ''),
                     'missing_atom_names': names,
                     'missing_backbone_atom_names': sorted(set(names) & {'N', 'CA', 'C', 'O'}),
                     'missing_other_atom_names': sorted(set(names) - {'N', 'CA', 'C', 'O'})})
    return rows
