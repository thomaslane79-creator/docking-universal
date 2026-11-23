#!/usr/bin/env python3
"""Conservatively repair a receptor PDB or mmCIF before Meeko parameterization."""

import argparse
import json
from pathlib import Path

from pdbfixer import PDBFixer
from openmm import unit
from openmm.app import PDBFile
from docking_universal.services.repair_geometry import (
    _heavy_atoms, introduced_heavy_atom_overlaps, introduced_interresidue_bond_contacts,
)
from docking_universal.services.preparation_atom_inventory import missing_atom_inventory


def atom_count(residues):
    return sum(len(atoms) for atoms in residues.values())


def generated_bond_contacts(source, fixer):
    from meeko.polymer import covalent_radius

    original = {identity for identity, _ in _heavy_atoms(source)}
    positions = fixer.positions.value_in_unit(unit.angstrom)

    def identity(atom):
        residue = atom.residue
        return (residue.chain.id, residue.id + residue.insertionCode.strip(), residue.name, atom.name)

    atoms = []
    for atom in fixer.topology.atoms():
        if atom.element is None or atom.element.atomic_number < 2:
            continue
        radius = covalent_radius.get(atom.element.atomic_number)
        if radius is not None:
            atoms.append((identity(atom), positions[atom.index], radius))
    bonds = {frozenset((identity(first), identity(second))) for first, second in fixer.topology.bonds()
             if first.residue is not second.residue}
    return introduced_interresidue_bond_contacts(original, atoms, bonds)


def main():
    """Apply conservative PDBFixer repair and retain an exact change audit."""
    parser = argparse.ArgumentParser()
    parser.add_argument("input_structure")
    parser.add_argument("output_pdb")
    parser.add_argument("audit_json")
    parser.add_argument("--sidechains-only", action="store_true")
    args = parser.parse_args()

    source = Path(args.input_structure)
    if source.suffix.lower() in {".cif", ".mmcif"}:
        with source.open() as handle:
            fixer = PDBFixer(pdbxfile=handle)
        input_format = "mmcif"
    else:
        fixer = PDBFixer(filename=str(source))
        input_format = "pdb"
    fixer.findMissingResidues()
    missing_residues = [
        {"chain_index": chain, "insertion_index": index,
         "residue_names": list(names)}
        for (chain, index), names in sorted(fixer.missingResidues.items())
    ]
    # Missing loops are deliberately not built automatically. Coordinates
    # inferred without target-specific review could alter the docking pocket.
    fixer.missingResidues = {}

    fixer.findNonstandardResidues()
    replacements = [
        {"chain": residue.chain.id, "residue": residue.name,
         "residue_id": residue.id, "replacement": replacement}
        for residue, replacement in fixer.nonstandardResidues
    ]
    if replacements and not args.sidechains_only:
        fixer.replaceNonstandardResidues()

    fixer.findMissingAtoms()
    missing_heavy_atoms = atom_count(fixer.missingAtoms)
    missing_inventory = missing_atom_inventory(fixer.missingAtoms)
    if any(row['missing_backbone_atom_names'] for row in missing_inventory):
        # Existing partial residues can be missing backbone atoms even though
        # missingResidues was cleared. Do not disguise backbone construction as
        # the previously documented side-chain-only fallback.
        audit = {'status': 'review_required_missing_backbone_atoms',
                 'input_structure': str(source.resolve()), 'input_format': input_format,
                 'missing_atom_inventory': missing_inventory,
                 'nonstandard_residue_replacements_not_adopted': replacements,
                 'missing_residue_segments_detected_not_built': missing_residues,
                 'missing_heavy_atoms_added': 0, 'output_created': False,
                 'policy': {'missing_backbone_atoms': 'not built; explicit external model review required',
                            'missing_residues': 'reported but not built'}}
        Path(args.audit_json).write_text(json.dumps(audit, indent=2) + '\n')
        raise RuntimeError('Observed partial residues require missing backbone atoms; automatic backbone completion is disabled. Review the retained missing-atom inventory.')
    missing_terminals = atom_count(fixer.missingTerminals)
    # Meeko assigns receptor termini itself. PDBFixer's terminal additions can
    # create OXT/CONECT combinations that RDKit reads as invalid oxygen valence.
    fixer.missingTerminals = {}
    if missing_heavy_atoms:
        fixer.addMissingAtoms()

    output = Path(args.output_pdb)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w") as handle:
        PDBFile.writeFile(fixer.topology, fixer.positions, handle, keepIds=True)

    audit = {
        "input_pdb": str(source.resolve()),
        "input_structure": str(source.resolve()),
        "input_format": input_format,
        "output_pdb": str(output.resolve()),
        "missing_residue_segments_detected_not_built": missing_residues,
        "nonstandard_residue_replacements": [] if args.sidechains_only else replacements,
        "nonstandard_residue_replacements_not_adopted": replacements if args.sidechains_only else [],
        "missing_heavy_atoms_added": missing_heavy_atoms,
        "missing_atom_inventory": missing_inventory,
        "missing_terminal_atoms_detected_not_added": missing_terminals,
        "policy": {
            "alternate_locations": "PDBFixer selected one location",
            "missing_residues": "reported but not built",
            "nonstandard_residues": "preserved" if args.sidechains_only else "recognized mappings replaced",
            "missing_sidechain_atoms": "added",
            "missing_backbone_atoms": "not built",
            "missing_terminal_atoms": "reported but not added",
            "hydrogens": "left for the receptor backend",
        },
    }
    overlaps = introduced_heavy_atom_overlaps(source, output)
    audit['introduced_gross_heavy_atom_overlaps'] = overlaps
    contacts = generated_bond_contacts(source, fixer) if missing_heavy_atoms else []
    audit['introduced_unassigned_interresidue_bond_contacts'] = contacts
    original_changed = False
    if args.sidechains_only:
        original = set(_heavy_atoms(source))
        retained = set(_heavy_atoms(output))
        original_changed = not original <= retained
        audit['reviewed_heavy_atom_coordinates_changed'] = original_changed
    audit['status'] = 'rejected_generated_geometry' if overlaps or contacts or original_changed else 'completed_conservative_repair'
    Path(args.audit_json).write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))
    if original_changed:
        raise RuntimeError('PDBFixer changed reviewed heavy-atom coordinates or identities; repair rejected')
    if overlaps or contacts:
        raise RuntimeError('PDBFixer generated unsafe heavy-atom contacts; repair is retained for review but not accepted for parameterization')


if __name__ == "__main__":
    main()
