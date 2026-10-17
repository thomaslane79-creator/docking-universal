#!/usr/bin/env python3
"""Verify a site-first control contract and expose native-script input paths."""
import argparse
from pathlib import Path

from docking_universal.services.control_review import read_reviewed_control_inputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("record", type=Path)
    parser.add_argument("--complex", type=Path, required=True)
    parser.add_argument("--ligand-id", required=True)
    parser.add_argument("--engine", required=True)
    parser.add_argument("--sha256")
    args = parser.parse_args()
    record = read_reviewed_control_inputs(args.record, complex_path=args.complex,
        ligand_id=args.ligand_id, engine=args.engine, expected_sha256=args.sha256)
    values = [record["preparation_root"], *(record["assets"][key]["path"]
              for key in ("receptor_pdb", "receptor_pdbqt", "box", "source_pdb"))]
    if any("\n" in value or "\r" in value for value in values):
        raise ValueError("Native control paths cannot contain newlines")
    print("\n".join(values))


if __name__ == "__main__":
    main()
