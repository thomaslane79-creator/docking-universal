#!/usr/bin/env python3
"""Conservatively repair a receptor PDB before Meeko parameterization."""

import argparse
import json
from pathlib import Path

from pdbfixer import PDBFixer
from openmm.app import PDBFile


def atom_count(residues):
    return sum(len(atoms) for atoms in residues.values())


def main():
    """Apply conservative PDBFixer repair and retain an exact change audit."""
    parser = argparse.ArgumentParser()
    parser.add_argument("input_pdb")
    parser.add_argument("output_pdb")
    parser.add_argument("audit_json")
    args = parser.parse_args()

    fixer = PDBFixer(filename=args.input_pdb)
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
    if replacements:
        fixer.replaceNonstandardResidues()

    fixer.findMissingAtoms()
    missing_heavy_atoms = atom_count(fixer.missingAtoms)
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
        "input_pdb": str(Path(args.input_pdb).resolve()),
        "output_pdb": str(output.resolve()),
        "missing_residue_segments_detected_not_built": missing_residues,
        "nonstandard_residue_replacements": replacements,
        "missing_heavy_atoms_added": missing_heavy_atoms,
        "missing_terminal_atoms_detected_not_added": missing_terminals,
        "policy": {
            "alternate_locations": "PDBFixer selected one location",
            "missing_residues": "reported but not built",
            "nonstandard_residues": "recognized mappings replaced",
            "missing_sidechain_atoms": "added",
            "missing_terminal_atoms": "reported but not added",
            "hydrogens": "left for the receptor backend",
        },
    }
    Path(args.audit_json).write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps(audit, indent=2))


if __name__ == "__main__":
    main()
