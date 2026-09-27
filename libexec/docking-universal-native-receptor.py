#!/usr/bin/env python3
"""Project the established receptor filter onto retained mmCIF coordinates."""
import argparse
from pathlib import Path
import gemmi


def filtered_mmcif(source, filtered_pdb, destination):
    original = gemmi.read_structure(str(source))
    filtered = gemmi.read_structure(str(filtered_pdb))
    def key(chain, residue, atom):
        return (chain.name, residue.seqid.num, residue.seqid.icode,
                residue.name, atom.name, atom.altloc)
    wanted = {key(c, r, a) for m in filtered for c in m for r in c for a in r}
    found = set()
    for model in original:
        for chain in model:
            for index in range(len(chain) - 1, -1, -1):
                residue = chain[index]
                for atom_index in range(len(residue) - 1, -1, -1):
                    identity = key(chain, residue, residue[atom_index])
                    if identity not in wanted:
                        del residue[atom_index]
                    else:
                        found.add(identity)
                if not len(residue):
                    del chain[index]
                else:
                    # Engine identifiers must match the compatibility PDB,
                    # including exact ligand selectors and template assignments.
                    residue.subchain = chain.name
    if found != wanted:
        raise ValueError("Filtered receptor identities do not map to the retained mmCIF")
    original.make_mmcif_document().write_file(str(destination))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("filtered_pdb", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    filtered_mmcif(args.source, args.filtered_pdb, args.destination)
