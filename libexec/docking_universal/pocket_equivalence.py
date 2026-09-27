"""Detect symmetry-related or near-identical predicted pocket copies."""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import numpy as np


def _keyed_atoms(path: Path) -> tuple[str, dict[tuple[str, str, str], np.ndarray]]:
    atoms = {}
    chains = set()
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")) or line[16:17] not in {" ", "A"}:
            continue
        try:
            xyz = np.asarray([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        except ValueError:
            continue
        chain = line[21:22].strip() or "_"
        chains.add(chain)
        key = (line[17:20].strip(), line[22:27].strip(), line[12:16].strip())
        atoms[key] = xyz
    return ",".join(sorted(chains)), atoms


def _fitted_rmsd(left: np.ndarray, right: np.ndarray) -> float:
    left = left - left.mean(axis=0)
    right = right - right.mean(axis=0)
    u, _, vt = np.linalg.svd(left.T @ right)
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    return float(np.sqrt(np.mean(np.sum((left @ rotation - right) ** 2, axis=1))))


def find_pocket_equivalences(
    pockets: list[Path], *, maximum_rmsd_angstrom: float = 1.25,
    minimum_atom_coverage: float = 0.50, minimum_common_atoms: int = 12,
) -> list[dict]:
    """Return review evidence for pocket copies with corresponding atoms."""
    parsed = [(path, *_keyed_atoms(path)) for path in pockets]
    results = []
    for (left_path, left_chain, left), (right_path, right_chain, right) in combinations(parsed, 2):
        common = sorted(set(left) & set(right))
        coverage = len(common) / max(1, min(len(left), len(right)))
        if len(common) < minimum_common_atoms or coverage < minimum_atom_coverage:
            continue
        rmsd = _fitted_rmsd(
            np.asarray([left[key] for key in common]),
            np.asarray([right[key] for key in common]),
        )
        if rmsd > maximum_rmsd_angstrom:
            continue
        left_number = int(left_path.stem.split("pocket", 1)[1].split("_", 1)[0])
        right_number = int(right_path.stem.split("pocket", 1)[1].split("_", 1)[0])
        results.append({
            "pockets": [left_number, right_number],
            "chains": [left_chain, right_chain],
            "fitted_pocket_atom_rmsd_angstrom": round(rmsd, 3),
            "corresponding_atom_count": len(common),
            "atom_coverage_fraction": round(coverage, 4),
            "interpretation": "probable_symmetry-related_or_near-identical_pocket_copies",
            "decision_role": "neutral_evidence_for_existing_box_selection",
            "physiological_assembly_warning": (
                "Equivalent pockets on different chains may both be relevant in a physiological assembly."
            ),
            "automatic_removal": False,
        })
    return results
