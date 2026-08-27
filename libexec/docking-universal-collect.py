#!/usr/bin/env python
"""Collect Vina-family PDBQT results into a tidy CSV."""

import argparse
import csv
from pathlib import Path


def iter_files(path: Path):
    if path.is_file():
        yield path
    else:
        yield from sorted(path.rglob("*.pdbqt"))


def parse_file(path: Path):
    compound_name = ""
    smiles = ""
    model = None
    affinity = ""
    rmsd_lower = ""
    rmsd_upper = ""
    score_format = ""

    with path.open(errors="replace") as handle:
        for line in handle:
            fields = line.split()
            if fields[:2] == ["REMARK", "NAME"]:
                compound_name = " ".join(fields[2:])
            elif fields[:2] == ["REMARK", "SMILES"] and len(fields) >= 3 and fields[2] != "IDX":
                smiles = fields[2]
            elif fields[:1] == ["MODEL"] and len(fields) >= 2:
                model = fields[1]
                affinity = ""
                rmsd_lower = ""
                rmsd_upper = ""
                score_format = ""
            elif fields[:3] == ["REMARK", "VINA", "RESULT:"] and len(fields) >= 6:
                affinity, rmsd_lower, rmsd_upper = fields[-3:]
                score_format = "vina"
            elif fields[:1] == ["ENDMDL"] and model is not None:
                yield {
                    "file_path": str(path.resolve()),
                    "compound_name": compound_name,
                    "model": model,
                    "smiles": smiles,
                    "score_format": score_format,
                    "affinity_kcal_per_mol": affinity,
                    "rmsd_lower_bound": rmsd_lower,
                    "rmsd_upper_bound": rmsd_upper,
                }
                model = None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="PDBQT file or directory")
    parser.add_argument("--out", type=Path, help="Output CSV path")
    args = parser.parse_args()

    if not args.input.exists():
        parser.error(f"input does not exist: {args.input}")
    output = args.out or Path(f"{args.input.resolve().name}.csv")
    fields = [
        "file_path",
        "compound_name",
        "model",
        "smiles",
        "score_format",
        "affinity_kcal_per_mol",
        "rmsd_lower_bound",
        "rmsd_upper_bound",
    ]
    count = 0
    with output.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for file_path in iter_files(args.input):
            for row in parse_file(file_path):
                writer.writerow(row)
                count += 1
    print(f"Wrote {count} models to {output}")


if __name__ == "__main__":
    main()
