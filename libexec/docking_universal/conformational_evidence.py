"""Derive auditable residue-conformation evidence from a retained ensemble."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import numpy as np


SCHEMA_NAME = "docking-universal-conformational-evidence"
SCHEMA_VERSION = 1
BACKBONE = ("N", "CA", "C", "O")
CHI_ATOMS = {
    "ARG": (("N", "CA", "CB", "CG"), ("CA", "CB", "CG", "CD")),
    "ASN": (("N", "CA", "CB", "CG"),), "ASP": (("N", "CA", "CB", "CG"),),
    "CYS": (("N", "CA", "CB", "SG"),),
    "GLN": (("N", "CA", "CB", "CG"), ("CA", "CB", "CG", "CD")),
    "GLU": (("N", "CA", "CB", "CG"), ("CA", "CB", "CG", "CD")),
    "HIS": (("N", "CA", "CB", "CG"),),
    "ILE": (("N", "CA", "CB", "CG1"), ("CA", "CB", "CG1", "CD1")),
    "LEU": (("N", "CA", "CB", "CG"), ("CA", "CB", "CG", "CD1")),
    "LYS": (("N", "CA", "CB", "CG"), ("CA", "CB", "CG", "CD")),
    "MET": (("N", "CA", "CB", "CG"), ("CA", "CB", "CG", "SD")),
    "PHE": (("N", "CA", "CB", "CG"),), "PRO": (("N", "CA", "CB", "CG"),),
    "SER": (("N", "CA", "CB", "OG"),),
    "THR": (("N", "CA", "CB", "OG1"),),
    "TRP": (("N", "CA", "CB", "CG"),), "TYR": (("N", "CA", "CB", "CG"),),
    "VAL": (("N", "CA", "CB", "CG1"),),
}


def _dihedral(points: list[np.ndarray]) -> float:
    p0, p1, p2, p3 = points
    b0, b1, b2 = -(p1 - p0), p2 - p1, p3 - p2
    b1 = b1 / np.linalg.norm(b1)
    v, w = b0 - np.dot(b0, b1) * b1, b2 - np.dot(b2, b1) * b1
    return float(math.degrees(math.atan2(np.dot(np.cross(b1, v), w), np.dot(v, w))))


def _circular_difference(left: float, right: float) -> float:
    return abs((left - right + 180.0) % 360.0 - 180.0)


def _choose_atoms(rows: list[dict[str, Any]], coordinate_key: str) -> dict[str, np.ndarray]:
    chosen: dict[str, tuple[tuple[float, int], np.ndarray]] = {}
    for row in rows:
        alt = str(row.get("alternate_location", ""))
        if alt not in {"", "A"} or not row.get(coordinate_key):
            continue
        priority = (float(row.get("occupancy") or 0.0), 1 if alt == "" else 0)
        name = str(row.get("atom_name"))
        xyz = np.asarray(row[coordinate_key], dtype=float)
        if name not in chosen or priority > chosen[name][0]:
            chosen[name] = (priority, xyz)
    return {name: value[1] for name, value in chosen.items()}


def _local_fit(reference: dict[str, np.ndarray], moving: dict[str, np.ndarray]):
    names = [name for name in ("N", "CA", "C") if name in reference and name in moving]
    if len(names) < 3:
        return None
    target, source = np.vstack([reference[n] for n in names]), np.vstack([moving[n] for n in names])
    tc, sc = target.mean(axis=0), source.mean(axis=0)
    u, _, vt = np.linalg.svd((source - sc).T @ (target - tc))
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    return rotation, tc - sc @ rotation


def _coordinate_file(path: Path) -> np.ndarray:
    coordinates = []
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            try:
                coordinates.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
            except ValueError:
                pass
    return np.asarray(coordinates, dtype=float)


def derive_conformational_evidence(
    manifest: Path | str, output: Path | str | None = None, *,
    ligand_evidence: list[dict[str, Any]] | None = None,
    ligand_evidence_root: Path | str | None = None,
) -> dict[str, Any]:
    """Compare each accepted structure with the prepared receptor residue-by-residue."""
    manifest = Path(manifest).resolve()
    root = manifest.parent
    ensemble = json.loads(manifest.read_text())
    reference_meta = ensemble.get("reference") or {}
    reference_path = root / str(reference_meta.get("atom_observations", ""))
    if not reference_path.is_file():
        raise ValueError("structural ensemble has no retained reference atom observations")
    reference_rows = [json.loads(line) for line in reference_path.read_text().splitlines() if line.strip()]
    reference_by_residue: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in reference_rows:
        reference_by_residue.setdefault((row["chain"], row["residue_name"], row["residue_number"]), []).append(row)

    observations: list[dict[str, Any]] = []
    ligand_root = Path(ligand_evidence_root) if ligand_evidence_root else root.parent
    for alignment in ensemble.get("accepted_alignments", []):
        rows = [json.loads(line) for line in (root / alignment["atom_observations"]).read_text().splitlines() if line.strip()]
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault((row["reference_chain"], row["reference_residue_name"], row["reference_residue_number"]), []).append(row)
        for key, related_rows in grouped.items():
            if key not in reference_by_residue:
                continue
            ref = _choose_atoms(reference_by_residue[key], "xyz")
            related = _choose_atoms(related_rows, "aligned_xyz")
            fit = _local_fit(ref, related)
            if fit is None:
                continue
            rotation, translation = fit
            locally_aligned = {name: xyz @ rotation + translation for name, xyz in related.items()}
            backbone_names = [name for name in BACKBONE if name in ref and name in related]
            backbone_rmsd = math.sqrt(float(np.mean([np.sum((ref[n] - related[n]) ** 2) for n in backbone_names])))
            side_names = sorted(set(ref) & set(locally_aligned) - set(BACKBONE))
            side_rmsd = (math.sqrt(float(np.mean([np.sum((ref[n] - locally_aligned[n]) ** 2) for n in side_names])))
                         if side_names else None)
            residue_name = key[1]
            chi_differences = []
            for atom_names in CHI_ATOMS.get(residue_name, ()):
                if all(name in ref and name in related for name in atom_names):
                    chi_differences.append(round(_circular_difference(
                        _dihedral([ref[n] for n in atom_names]),
                        _dihedral([related[n] for n in atom_names]),
                    ), 2))
            bound_ligands = []
            for ligand in ligand_evidence or []:
                if (ligand.get("entry") == alignment.get("entry")
                        and ligand.get("aligned_chain") == alignment.get("source_chain")
                        and ligand.get("aligned_ligand_pdb")):
                    ligand_atoms = _coordinate_file(ligand_root / ligand["aligned_ligand_pdb"])
                    if len(ligand_atoms) and side_names:
                        current_distance = float(np.min(np.linalg.norm(
                            np.vstack([ref[n] for n in side_names])[:, None, :] - ligand_atoms[None, :, :], axis=2,
                        )))
                        bound_distance = float(np.min(np.linalg.norm(
                            np.vstack([related[n] for n in side_names])[:, None, :] - ligand_atoms[None, :, :], axis=2,
                        )))
                        bound_ligands.append({
                            "source_ligand_id": ligand.get("source_ligand_id"),
                            "current_side_chain_minimum_distance_angstrom": round(current_distance, 3),
                            "bound_side_chain_minimum_distance_angstrom": round(bound_distance, 3),
                            "current_conformation_clashes_with_observed_ligand": current_distance < 2.0,
                            "consistent_with_side_chain_occlusion": (
                                current_distance < 2.0 and bound_distance >= current_distance + 0.5
                            ),
                        })
            observations.append({
                "residue": {"chain": key[0], "name": key[1], "number": key[2]},
                "entry": alignment.get("entry"), "alignment_id": alignment.get("alignment_id"),
                "ligand_context": alignment.get("ligand_context", "not_recorded"),
                "chi_difference_degrees": chi_differences,
                "maximum_chi_difference_degrees": max(chi_differences, default=None),
                "side_chain_rmsd_angstrom": round(side_rmsd, 3) if side_rmsd is not None else None,
                "backbone_rmsd_angstrom": round(backbone_rmsd, 3),
                "matched_side_chain_atoms": side_names,
                "known_ligand_accessibility": bound_ligands,
            })

    aggregates = []
    residue_keys = sorted({(o["residue"]["chain"], o["residue"]["name"], o["residue"]["number"]) for o in observations})
    for key in residue_keys:
        items = [o for o in observations if tuple(o["residue"][field] for field in ("chain", "name", "number")) == key]
        changed = [o for o in items if (o["maximum_chi_difference_degrees"] or 0) >= 30.0 or (o["side_chain_rmsd_angstrom"] or 0) >= 1.0]
        backbone_dominant = [o for o in items if o["backbone_rmsd_angstrom"] >= 0.75]
        occluding = [
            ligand for observation in items for ligand in observation["known_ligand_accessibility"]
            if ligand["consistent_with_side_chain_occlusion"]
        ]
        aggregates.append({
            "residue": items[0]["residue"], "observation_count": len(items),
            "changed_conformation_count": len(changed),
            "changed_conformation_fraction": round(len(changed) / len(items), 4),
            "ligand_bound_changed_count": sum(o["ligand_context"] == "ligand_bound" for o in changed),
            "backbone_displacement_count": len(backbone_dominant),
            "known_ligand_occlusion_count": len(occluding),
            "suggest_for_flexible_residue_review": bool(changed),
            "warning": ("backbone displacement is also present; side-chain flexibility alone may be insufficient"
                        if backbone_dominant else None),
            "interpretation": ("repeated side-chain conformational difference" if len(changed) > 1
                               else "side-chain conformational difference" if changed else "no threshold-crossing difference observed"),
            "accessibility_interpretation": (
                "current conformation is consistent with side-chain occlusion of an observed ligand placement"
                if occluding else "no side-chain occlusion evidence met the recorded geometric rule"
            ),
        })
    record = {
        "schema_name": SCHEMA_NAME, "schema_version": SCHEMA_VERSION,
        "selection_policy": "evidence_only_user_decides",
        "scientific_scope": "differences are consistent with alternate accessibility but do not prove flexibility or induced fit",
        "thresholds": {"chi_difference_degrees": 30.0, "side_chain_rmsd_angstrom": 1.0,
                       "backbone_rmsd_angstrom": 0.75, "ligand_clash_distance_angstrom": 2.0,
                       "minimum_bound_state_clearance_gain_angstrom": 0.5},
        "source_ensemble_manifest": manifest.name,
        "observations": observations, "residue_aggregates": aggregates,
        "flexible_residue_suggestions": [a["residue"] for a in aggregates if a["suggest_for_flexible_residue_review"]],
        "rigid_docking_site_assessment": {
            "status": (
                "conformationally_incompatible_with_observed_ligand_placement"
                if any(a["known_ligand_occlusion_count"] for a in aggregates)
                else "no_geometric_incompatibility_detected"
            ),
            "warning": (
                "The experimentally observed site may not be accessible in the current receptor conformation. "
                "Rigid docking at this site may therefore be an invalid test; review alternate structures and "
                "consider flexible docking or another receptor conformation. Flexible side-chain docking is not "
                "sufficient when the recorded difference is backbone-dominant."
                if any(a["known_ligand_occlusion_count"] for a in aggregates) else None
            ),
            "occluding_residues": [
                a["residue"] for a in aggregates if a["known_ligand_occlusion_count"]
            ],
        },
    }
    destination = Path(output) if output else root / "conformational_evidence.json"
    destination.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record
