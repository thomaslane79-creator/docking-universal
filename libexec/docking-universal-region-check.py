#!/usr/bin/env python3
"""Command-line preflight for receptor and docking-box consistency."""

import argparse

from docking_universal_region import receptor_atoms_in_box, validate_protein_pdb


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate-protein-pdb")
    parser.add_argument("--receptor")
    parser.add_argument("--config")
    args = parser.parse_args()
    if args.validate_protein_pdb:
        if args.receptor or args.config:
            parser.error("--validate-protein-pdb cannot be combined with box preflight inputs")
        validate_protein_pdb(args.validate_protein_pdb)
        return
    if not args.receptor or not args.config:
        parser.error("--receptor and --config are required for box preflight")
    count = receptor_atoms_in_box(args.receptor, args.config)
    print(f"Docking-box preflight passed: {count} receptor atoms are inside the search box.")


if __name__ == "__main__":
    main()
