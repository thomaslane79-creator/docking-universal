"""Materialize P2Rank predictions as Docking Universal pocket artifacts."""

from __future__ import annotations

import csv
import json
import math
import re
from pathlib import Path

from docking_universal.pocket_equivalence import find_pocket_equivalences


def _residue_keys(value: str) -> set[tuple[str, str]]:
    return {(match.group(1), match.group(2)) for match in re.finditer(r"([A-Za-z0-9]+)_(-?\d+[A-Za-z]?)", value)}


def _protein_atoms(path: Path) -> dict[tuple[str, str], list[str]]:
    residues = {}
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("ATOM  ") and line[16:17] in {" ", "A"}:
            residues.setdefault((line[21:22].strip() or "_", line[22:27].strip()), []).append(line)
    return residues


def _overlap(left: dict, right: dict) -> float:
    volume = 1.0
    for axis in "xyz":
        lo = max(left[f"center_{axis}"] - left[f"size_{axis}"] / 2,
                 right[f"center_{axis}"] - right[f"size_{axis}"] / 2)
        hi = min(left[f"center_{axis}"] + left[f"size_{axis}"] / 2,
                 right[f"center_{axis}"] + right[f"size_{axis}"] / 2)
        volume *= max(0.0, hi - lo)
    smaller = min(math.prod(item[f"size_{axis}"] for axis in "xyz") for item in (left, right))
    return volume / smaller if smaller else 0.0


def materialize_p2rank_candidates(
    predictions_csv: Path | str, receptor_pdb: Path | str, cavity_directory: Path | str,
    target: str, *, maximum_pockets: int = 3, minimum_box_size: float = 26.0,
    margin: float = 4.0, maximum_box_size: float = 48.0, maximum_overlap: float = 0.60,
    p2rank_version: str | None = None,
) -> dict:
    """Convert P2Rank rows into the stable downstream pocket contract."""
    if maximum_pockets < 0:
        raise ValueError("Maximum pockets must be nonnegative (0 means all)")
    predictions_csv, receptor_pdb, cavity = Path(predictions_csv), Path(receptor_pdb), Path(cavity_directory)
    cavity.mkdir(parents=True, exist_ok=True)
    frozen = cavity / "frozen_pockets"; frozen.mkdir(exist_ok=True)
    residues = _protein_atoms(receptor_pdb)
    rows = []
    with predictions_csv.open(newline="") as handle:
        for fallback, raw in enumerate(csv.DictReader(handle), 1):
            row = {str(k).strip(): (v or "").strip() for k, v in raw.items() if k}
            rank = int(row.get("rank") or fallback)
            score = float(row["score"])
            probability = float(row["probability"]) if row.get("probability") else None
            center = {axis: float(row[f"center_{axis}"]) for axis in "xyz"}
            keys = _residue_keys(row.get("residue_ids", row.get("residue ids", "")))
            atom_lines = [line for key in keys for line in residues.get(key, [])]
            points = []
            for line in atom_lines:
                points.append(tuple(float(line[start:start + 8]) for start in (30, 38, 46)))
            geometry = {}
            for index, axis in enumerate("xyz"):
                extent = (max(p[index] for p in points) - min(p[index] for p in points) + 2 * margin) if points else minimum_box_size
                geometry[f"center_{axis}"] = center[axis]
                geometry[f"size_{axis}"] = min(maximum_box_size, max(minimum_box_size, extent))
            rows.append({"rank": rank, "score": score, "probability": probability,
                         "name": row.get("name") or f"pocket{rank}", "geometry": geometry,
                         "residue_ids": sorted(f"{c}_{n}" for c, n in keys), "atom_lines": atom_lines})
    rows.sort(key=lambda item: (item["rank"], -item["score"]))
    # Zero means all eligible regions; the default CLI limit remains three.
    limit = maximum_pockets if maximum_pockets > 0 else len(rows)
    retained = []
    diagnostics = []
    for item in rows:
        observed = max((_overlap(item["geometry"], prior["geometry"]) for prior in retained), default=0.0)
        selected = len(retained) < limit and observed <= maximum_overlap
        diagnostics.append((item, selected, observed, "selected" if selected else
                            "maximum_candidates_reached" if len(retained) >= limit else "overlaps_higher_ranked_box"))
        if selected:
            retained.append(item)
    selection = cavity / "pocket_selection_diagnostics.tsv"
    selection.write_text("rank_order\tpocket_file\tscore\tprobability\tdecision\treason\tmax_overlap\tpocket_engine\n")
    selected_records = cavity / "selected_pocket_records.txt"; selected_records.write_text("")
    for item, selected, observed, reason in diagnostics:
        number = item["rank"]
        pocket = frozen / f"pocket{number}_atm.pdb"
        lines = [f"HEADER  Pocket Score : {item['score']}", "REMARK  Pocket Engine : P2Rank",
                 f"REMARK  P2Rank Probability : {item['probability'] if item['probability'] is not None else 'NA'}"]
        if item["atom_lines"]:
            lines.extend(item["atom_lines"])
        else:
            g = item["geometry"]
            lines.append(f"HETATM    1  C   STP P   1    {g['center_x']:8.3f}{g['center_y']:8.3f}{g['center_z']:8.3f}  1.00  0.00           C")
        pocket.write_text("\n".join(lines) + "\nEND\n")
        g = item["geometry"]
        config = cavity / f"{target}_pocket{number}.conf"
        config.write_text("\n".join(f"{key} = {value:.3f}" for key, value in g.items()) + "\n")
        with selection.open("a") as handle:
            handle.write(f"{number}\t{pocket.name}\t{item['score']}\t{item['probability'] if item['probability'] is not None else 'NA'}\t{'selected' if selected else 'skipped'}\t{reason}\t{observed:.4f}\tp2rank\n")
        if selected:
            with selected_records.open("a") as handle:
                handle.write(f"{item['score']}|{pocket}|{g['center_x']}|{g['center_y']}|{g['center_z']}|{item['score']}\n")
    equivalences = find_pocket_equivalences([
        frozen / f"pocket{item['rank']}_atm.pdb" for item in retained
    ])
    provenance = {"schema_name": "docking-universal-pocket-detection", "schema_version": 1,
                  "engine": "p2rank", "source_predictions": str(predictions_csv.resolve()),
                  "engine_version": p2rank_version or "not recorded",
                  "receptor": str(receptor_pdb.resolve()), "candidate_count": len(rows),
                  "retained_count": len(retained), "box_policy": {"minimum_size_angstrom": minimum_box_size,
                  "margin_angstrom": margin, "maximum_size_angstrom": maximum_box_size,
                  "maximum_overlap_fraction": maximum_overlap},
                  "pocket_equivalences": equivalences}
    (cavity / "pocket_detection_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return provenance
