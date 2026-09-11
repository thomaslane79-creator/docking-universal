#!/usr/bin/env python3
"""Collect auditable PDB ligand-site evidence for fpocket candidates.

The module deliberately separates evidence collection from pocket selection.  It
finds PDB polymer entities similar to a receptor chain, superposes compatible
chains onto the receptor using matched C-alpha atoms, and measures deposited
ligands against the full volumes of the prepared fpocket boxes.  A ligand need
not be near a box center: containment and overlap are evaluated against the six
box boundaries.  Callers retain the evidence and leave the scientific choice
to the user.
"""

from __future__ import annotations

import json
import math
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import numpy as np


SEARCH_URL = "https://search.rcsb.org/rcsbsearch/v2/query"
DOWNLOAD_URL = "https://files.rcsb.org/download/{entry}.pdb"
CCD_SDF_URL = "https://files.rcsb.org/ligands/download/{component}_ideal.sdf"
WATER = {"DOD", "HOH", "WAT"}
CRYSTALLIZATION_ADDITIVES = {
    "ACT", "ACE", "BME", "DMS", "DTT", "EDO", "EOH", "GOL", "IPA",
    "MPD", "PEG", "PG4", "PO4", "SO4", "TRS",
}
COMMON_IONS = {
    "AL", "BA", "BR", "CA", "CD", "CL", "CO", "CS", "CU", "F", "FE",
    "HG", "I", "K", "LI", "MG", "MN", "NA", "NI", "PB", "RB", "SR", "ZN",
}
AA3 = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    "MSE": "M", "SEC": "C", "PYL": "K",
}

DEFAULT_MINIMUM_BOX_OVERLAP = 0.35
DEFAULT_MAXIMUM_COMBINED_BOX_VOLUME = 64000.0
DEFAULT_MAXIMUM_BOX_DIMENSION = 36.0


@dataclass(frozen=True)
class ResiduePoint:
    chain: str
    number: str
    name: str
    one_letter: str
    xyz: np.ndarray


@dataclass(frozen=True)
class Ligand:
    entry: str
    chain: str
    number: str
    name: str
    atoms: np.ndarray
    atom_lines: tuple[str, ...]


def _pdb_xyz(line):
    return np.array([float(line[30:38]), float(line[38:46]), float(line[46:54])])


def protein_chains(pdb_text):
    """Return ordered C-alpha residue records for each protein chain."""
    chains = {}
    seen = set()
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM  ") or line[12:16].strip() != "CA":
            continue
        altloc = line[16:17]
        if altloc not in {" ", "A"}:
            continue
        name = line[17:20].strip().upper()
        if name not in AA3:
            continue
        chain = line[21:22].strip() or "_"
        number = line[22:27].strip()
        key = (chain, number)
        if key in seen:
            continue
        seen.add(key)
        chains.setdefault(chain, []).append(
            ResiduePoint(chain, number, name, AA3[name], _pdb_xyz(line))
        )
    return chains


def protein_heavy_atoms_by_chain(pdb_text):
    """Return source-frame protein heavy-atom coordinates for each chain."""
    chains = {}
    for line in pdb_text.splitlines():
        if not line.startswith("ATOM  "):
            continue
        element = line[76:78].strip().upper()
        if element == "H":
            continue
        chain = line[21:22].strip() or "_"
        try:
            chains.setdefault(chain, []).append(_pdb_xyz(line))
        except ValueError:
            continue
    return {
        chain: np.vstack(atoms) for chain, atoms in chains.items() if atoms
    }


def ligand_chain_contact(ligand_atoms, protein_atoms, cutoff=6.0):
    """Quantify whether a deposited ligand belongs to one protein-chain copy."""
    if not len(ligand_atoms) or protein_atoms is None or not len(protein_atoms):
        return {"contact_fraction": 0.0, "minimum_distance_angstrom": float("inf")}
    distances = np.linalg.norm(
        ligand_atoms[:, None, :] - protein_atoms[None, :, :], axis=2,
    ).min(axis=1)
    return {
        "contact_fraction": float(np.mean(distances <= cutoff)),
        "minimum_distance_angstrom": float(distances.min()),
        "contact_cutoff_angstrom": cutoff,
    }


def choose_ligand_alignment(associated, ligand_chain, available_chain_ids=None):
    """Choose the contacted protein-chain alignment without guessing silently.

    A deposited ligand's own chain identifier is preferred when that chain is
    structurally accepted and physically contacted.  When no same-chain match
    exists, contact geometry selects the alignment and near-ties are recorded
    as ambiguous so they cannot authorize an fpocket correspondence.
    """
    same_chain = [item for item in associated if item[0]["chain_id"] == ligand_chain]
    candidates = same_chain or associated
    ordered = sorted(
        candidates,
        key=lambda item: (
            item[1]["contact_fraction"],
            -item[1]["minimum_distance_angstrom"],
            item[0]["rank_score"],
            -item[0]["rmsd"],
        ),
        reverse=True,
    )
    chosen = ordered[0]
    ambiguous = False
    if not same_chain and len(ordered) > 1:
        first, second = ordered[:2]
        ambiguous = (
            abs(first[1]["contact_fraction"] - second[1]["contact_fraction"]) < 0.10
            and abs(first[1]["minimum_distance_angstrom"] - second[1]["minimum_distance_angstrom"]) < 1.0
        )
    # If the ligand's named protein chain exists in the source structure but
    # failed the structural-alignment criteria, do not silently project that
    # ligand through a different subunit.  This matters for related but
    # non-interchangeable subunits such as HIV-1 RT p66 and p51.
    own_chain_rejected = (
        available_chain_ids is not None
        and ligand_chain in set(available_chain_ids)
        and not same_chain
    )
    return chosen, ambiguous or own_chain_rejected, bool(same_chain)


def validated_matched_cavity(row):
    """Return a pocket assignment only when contact and containment agree."""
    pocket = row.get("matched_cavity")
    if pocket is None or row.get("chain_assignment_ambiguous"):
        return None
    relationship = next(
        (
            item for item in row.get("pocket_relationships", [])
            if int(item.get("pocket_number", -1)) == int(pocket)
        ),
        None,
    )
    if not relationship:
        return None
    if not relationship.get("cavity_match") or not relationship.get("all_heavy_atoms_inside"):
        return None
    return int(pocket)


def source_ligand_id(row):
    """Return the stable deposited-ligand identity used across all artifacts."""
    recorded = row.get("source_ligand_id")
    if recorded:
        return recorded
    fields = ("entry", "ligand", "ligand_chain", "ligand_residue")
    if not all(row.get(field) not in (None, "") for field in fields):
        return None
    return "/".join(str(row[field]) for field in fields)


def protein_database_identifiers(pdb_text):
    """Return chain-specific authoritative protein accessions from DBREF.

    UniProt mappings are preferred because a shared accession is a stronger
    same-protein check than sequence resemblance alone.  DBREF2 is supported
    for extended accessions; its database identity is supplied by DBREF1.
    """
    identifiers = {}
    dbref1_databases = {}
    for line in pdb_text.splitlines():
        fields = line.split()
        if line.startswith("DBREF ") and len(fields) >= 7:
            chain, database, accession = fields[2], fields[5].upper(), fields[6]
            if database == "UNP":
                identifiers.setdefault(chain or "_", set()).add(f"UNP:{accession}")
        elif line.startswith("DBREF1") and len(fields) >= 7:
            dbref1_databases[fields[2] or "_"] = fields[6].upper()
        elif line.startswith("DBREF2") and len(fields) >= 4:
            chain, accession = fields[2] or "_", fields[3]
            if dbref1_databases.get(chain) == "UNP":
                identifiers.setdefault(chain, set()).add(f"UNP:{accession}")
    return identifiers


def deposited_ligands(pdb_text, entry="unknown", minimum_heavy_atoms=6):
    """Extract plausible organic ligands while excluding solvent and simple ions."""
    modified_polymer = {
        line[12:15].strip().upper()
        for line in pdb_text.splitlines()
        if line.startswith("MODRES")
    }
    grouped = {}
    atom_names = {}
    atom_lines = {}
    for line in pdb_text.splitlines():
        if not line.startswith("HETATM"):
            continue
        altloc = line[16:17]
        if altloc not in {" ", "A"}:
            continue
        name = line[17:20].strip().upper()
        element = line[76:78].strip().upper()
        if name in WATER or name in COMMON_IONS or name in CRYSTALLIZATION_ADDITIVES or element == "H":
            continue
        chain = line[21:22].strip() or "_"
        number = line[22:27].strip()
        grouped.setdefault((name, chain, number), []).append(_pdb_xyz(line))
        atom_names.setdefault((name, chain, number), set()).add(line[12:16].strip().upper())
        atom_lines.setdefault((name, chain, number), []).append(line)
    return [
        Ligand(entry.upper(), chain, number, name, np.vstack(atoms), tuple(atom_lines[(name, chain, number)]))
        for (name, chain, number), atoms in grouped.items()
        if len(atoms) >= minimum_heavy_atoms
        and name not in modified_polymer
        # Some legacy PDB files omit MODRES records.  A complete peptide
        # backbone is therefore a second conservative indication that the HET
        # group is a modified polymer residue rather than a free ligand.
        and not {"N", "CA", "C", "O"}.issubset(atom_names[(name, chain, number)])
    ]


def write_aligned_ligand(ligand, transformed_atoms, output):
    """Retain the deposited ligand in the reference-receptor coordinate frame."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for source, xyz in zip(ligand.atom_lines, transformed_atoms):
        # Preserve deposited atom identity, occupancy, element, and residue
        # metadata; replace only the coordinates produced by the audited fit.
        lines.append(
            f"{source[:30]}{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}{source[54:]}"
        )
    output.write_text("\n".join(line.rstrip("\n") for line in lines) + "\nEND\n")


def download_ccd_sdf(component, output, opener=urllib.request.urlopen):
    """Retain the official CCD ideal structure used for a 2D identity panel."""
    request = urllib.request.Request(
        CCD_SDF_URL.format(component=component.upper()),
        headers={"User-Agent": "Docking-Universal"},
    )
    with opener(request, timeout=30) as response:
        data = response.read()
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    return output


def _alignment_pairs(first, second):
    """Needleman-Wunsch residue-index mapping for two protein sequences."""
    a = "".join(item.one_letter for item in first)
    b = "".join(item.one_letter for item in second)
    rows, cols = len(a) + 1, len(b) + 1
    score = np.zeros((rows, cols), dtype=int)
    trace = np.zeros((rows, cols), dtype=np.int8)
    score[:, 0] = -2 * np.arange(rows)
    score[0, :] = -2 * np.arange(cols)
    trace[1:, 0] = 1
    trace[0, 1:] = 2
    for i in range(1, rows):
        for j in range(1, cols):
            choices = (score[i - 1, j - 1] + (2 if a[i - 1] == b[j - 1] else -1),
                       score[i - 1, j] - 2, score[i, j - 1] - 2)
            trace[i, j] = int(np.argmax(choices))
            score[i, j] = choices[trace[i, j]]
    pairs = []
    i, j = len(a), len(b)
    while i or j:
        direction = trace[i, j]
        if direction == 0:
            pairs.append((i - 1, j - 1))
            i -= 1; j -= 1
        elif direction == 1:
            i -= 1
        else:
            j -= 1
    return list(reversed(pairs))


def chain_match(reference, candidate):
    """Return matched residue indices, identity, and query coverage."""
    pairs = _alignment_pairs(reference, candidate)
    if not pairs:
        return pairs, 0.0, 0.0
    identical = sum(reference[i].one_letter == candidate[j].one_letter for i, j in pairs)
    return pairs, identical / len(pairs), len(pairs) / max(1, len(reference))


def choose_alignment_candidate(ranked, reference_chain, reference_identifiers):
    """Choose a chain without arbitrarily flipping symmetric homooligomers."""
    accession_matches = [item for item in ranked if reference_identifiers & item[6]]
    candidates = accession_matches or ranked
    return max(
        enumerate(candidates),
        key=lambda indexed: (
            indexed[1][0], indexed[1][1], indexed[1][2],
            indexed[1][3] == reference_chain,
            -indexed[0],
        ),
    )[1]


def superposition(reference, candidate, pairs):
    """Return rotation, translation, and C-alpha RMSD mapping candidate to reference."""
    target = np.vstack([reference[i].xyz for i, _ in pairs])
    moving = np.vstack([candidate[j].xyz for _, j in pairs])
    moving_center = moving.mean(axis=0)
    target_center = target.mean(axis=0)
    u, _, vt = np.linalg.svd((moving - moving_center).T @ (target - target_center))
    rotation = u @ vt
    if np.linalg.det(rotation) < 0:
        u[:, -1] *= -1
        rotation = u @ vt
    translation = target_center - moving_center @ rotation
    fitted = moving @ rotation + translation
    rmsd = math.sqrt(float(np.mean(np.sum((fitted - target) ** 2, axis=1))))
    return rotation, translation, rmsd


def read_box_geometry(path):
    """Read the center and full dimensions of an AutoDock/Vina box."""
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if key in {"center_x", "center_y", "center_z", "size_x", "size_y", "size_z"}:
            values[key] = float(value)
    center = np.array([values[key] for key in ("center_x", "center_y", "center_z")])
    size = np.array([values[key] for key in ("size_x", "size_y", "size_z")])
    if np.any(size <= 0):
        raise ValueError(f"docking box has non-positive dimensions: {path}")
    return center, size


def ligand_box_relationship(atoms, center, size, tolerance=0.25):
    """Measure containment against box boundaries, not distance to its center."""
    half = size / 2.0
    offsets = np.abs(atoms - center)
    inside = np.all(offsets <= half + tolerance, axis=1)
    outside_displacement = np.maximum(offsets - half, 0.0)
    return {
        "centroid_inside": bool(np.all(np.abs(atoms.mean(axis=0) - center) <= half + tolerance)),
        "heavy_atom_fraction_inside": round(float(np.mean(inside)), 4),
        "all_heavy_atoms_inside": bool(np.all(inside)),
        "minimum_distance_to_box_angstrom": round(
            float(np.min(np.linalg.norm(outside_displacement, axis=1))), 3
        ),
        "centroid_distance_angstrom": round(float(np.linalg.norm(atoms.mean(axis=0) - center)), 3),
    }


def pdb_atom_coordinates(path):
    """Read Cartesian coordinates from an ATOM/HETATM coordinate file."""
    coordinates = []
    for line in Path(path).read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        try:
            coordinates.append([float(line[30:38]), float(line[38:46]), float(line[46:54])])
        except ValueError:
            continue
    return np.asarray(coordinates, dtype=float)


def classify_cavity_match(ligand_atoms, pocket_atoms_by_number, contact_cutoff=6.0):
    """Identify one clear ligand-matched cavity from lining-atom proximity.

    A broad docking box can incidentally contain a ligand far from its cavity.
    Cavity support therefore comes from ligand proximity to the fpocket lining
    atoms, independently of box containment.  Ambiguous matches are left
    unresolved for user review instead of promoting several pockets.
    """
    scored = []
    for number, pocket_atoms in pocket_atoms_by_number.items():
        if not len(pocket_atoms):
            continue
        distances = np.linalg.norm(
            ligand_atoms[:, None, :] - pocket_atoms[None, :, :], axis=2,
        ).min(axis=1)
        scored.append({
            "pocket_number": number,
            "cavity_minimum_distance_angstrom": round(float(distances.min()), 3),
            "ligand_contact_fraction": round(float(np.mean(distances <= contact_cutoff)), 4),
            "cavity_contact_cutoff_angstrom": contact_cutoff,
        })
    scored.sort(key=lambda item: (-item["ligand_contact_fraction"],
                                  item["cavity_minimum_distance_angstrom"],
                                  item["pocket_number"]))
    if not scored:
        return {}, None, "cavity coordinates unavailable"
    best = scored[0]
    runner_up = scored[1] if len(scored) > 1 else None
    fraction = best["ligand_contact_fraction"]
    gap = fraction - (runner_up["ligand_contact_fraction"] if runner_up else 0.0)
    clear = fraction >= 0.10 and (runner_up is None or gap >= 0.10 or
                                 fraction >= 2 * max(runner_up["ligand_contact_fraction"], 0.0001))
    reason = (
        "unique cavity match by ligand-to-pocket contact geometry"
        if clear else "no unique cavity match; retain for user review"
    )
    return {item["pocket_number"]: item for item in scored}, (
        best["pocket_number"] if clear else None
    ), reason


def evidence_class(shared_identifiers, identity, coverage):
    """Classify how directly a related structure represents the target."""
    if shared_identifiers:
        return "same_protein"
    if identity >= 0.999 and coverage >= 0.95:
        return "exact_sequence_match"
    return "close_structural_homolog"


def _ligand_box(atoms, minimum_box_size, ligand_margin):
    """Return the complete-containment box proposed for one aligned ligand."""
    lower, upper = atoms.min(axis=0), atoms.max(axis=0)
    return (lower + upper) / 2.0, np.maximum(
        minimum_box_size, (upper - lower) + 2 * ligand_margin,
    )


def _ligand_overlap_fraction(left_atoms, right_atoms, contact_cutoff):
    """Return how completely either ligand occupies the other's local region.

    The fraction is evaluated in both directions and the larger value is
    retained.  This lets a small fragment be recognized as occupying the same
    site as a larger ligand without allowing two merely adjacent 26 A docking
    boxes to create a false site match.
    """
    distances = np.sqrt(
        np.sum((left_atoms[:, None, :] - right_atoms[None, :, :]) ** 2, axis=2)
    )
    left_fraction = float(np.mean(distances.min(axis=1) <= contact_cutoff))
    right_fraction = float(np.mean(distances.min(axis=0) <= contact_cutoff))
    return max(left_fraction, right_fraction)


def _evidence_box(atom_sets, minimum_box_size, margin):
    """Return the smallest padded box containing every supplied evidence atom."""
    all_atoms = np.vstack([atoms for atoms in atom_sets if len(atoms)])
    lower, upper = all_atoms.min(axis=0), all_atoms.max(axis=0)
    center = (lower + upper) / 2.0
    size = np.maximum(minimum_box_size, (upper - lower) + 2 * margin)
    return center, size


def _box_overlap_fraction(left, right):
    """Return intersection volume as a fraction of the smaller box."""
    left_center, left_size = left
    right_center, right_size = right
    overlap = np.maximum(
        0.0,
        np.minimum(left_center + left_size / 2, right_center + right_size / 2)
        - np.maximum(left_center - left_size / 2, right_center - right_size / 2),
    )
    intersection = float(np.prod(overlap))
    if intersection <= 0:
        return 0.0
    return intersection / min(float(np.prod(left_size)), float(np.prod(right_size)))


def group_ligand_sites(record, evidence_root, atom_contact_cutoff=4.0,
                       minimum_ligand_overlap=0.25, minimum_box_size=26.0,
                       ligand_margin=4.0,
                       minimum_box_overlap=DEFAULT_MINIMUM_BOX_OVERLAP,
                       maximum_combined_box_volume=DEFAULT_MAXIMUM_COMBINED_BOX_VOLUME,
                       maximum_box_dimension=DEFAULT_MAXIMUM_BOX_DIMENSION):
    """Merge aligned ligand observations into unified spatial sites.

    Two observations describe the same site when a meaningful fraction of one
    ligand's heavy atoms lies within ``atom_contact_cutoff`` of the other, or
    when both observations have the same unique fpocket-cavity assignment.
    Those direct molecular relationships first define preliminary sites.
    Preliminary sites are then consolidated when their evidence boxes overlap
    by at least ``minimum_box_overlap`` and the recomputed combined box remains
    below ``maximum_combined_box_volume`` and no dimension exceeds
    ``maximum_box_dimension``.  Every recomputed box contains the accepted
    ligand atoms.  Uniquely corresponding retained fpocket geometry is also
    included when doing so remains within those limits; otherwise it remains
    supporting evidence without inflating the docking region.
    """
    evidence_root = Path(evidence_root)
    usable = []
    for row in record.get("evidence", []):
        if row.get("chain_assignment_ambiguous"):
            continue
        ligand_path = evidence_root / str(row.get("aligned_ligand_pdb", ""))
        if not ligand_path.is_file():
            continue
        atoms = pdb_atom_coordinates(ligand_path)
        if len(atoms):
            center, size = _ligand_box(atoms, minimum_box_size, ligand_margin)
            usable.append((row, atoms, center, size))
    compatible = {index: set() for index in range(len(usable))}
    for left in range(len(usable)):
        for right in range(left + 1, len(usable)):
            left_atoms, right_atoms = usable[left][1], usable[right][1]
            ligand_overlap = _ligand_overlap_fraction(
                left_atoms, right_atoms, atom_contact_cutoff,
            )
            left_pocket = validated_matched_cavity(usable[left][0])
            right_pocket = validated_matched_cavity(usable[right][0])
            shared_unique_cavity = (
                left_pocket is not None and left_pocket == right_pocket
            )
            # A cavity identifier alone is not enough to merge observations:
            # stale or chain-mismatched fpocket assignments can associate
            # spatially distant ligands with the same numbered pocket.  A
            # shared cavity may support grouping only when the two
            # ligand-centered evidence boxes also overlap at the configured
            # minimum.  This preserves separate exploratory boxes for
            # genuinely different sites while retaining the compact box for
            # aligned ligands that occupy the same region.
            boxes_overlap = _box_overlap_fraction(
                (usable[left][2], usable[left][3]),
                (usable[right][2], usable[right][3]),
            )
            if ((ligand_overlap >= minimum_ligand_overlap and
                 boxes_overlap >= minimum_box_overlap) or
                    (shared_unique_cavity and boxes_overlap >= minimum_box_overlap)):
                compatible[left].add(right); compatible[right].add(left)

    # Complete-link clustering prevents transitive site inflation.  A chain of
    # pairwise contacts (A near B, B near C) is not enough to place A and C in
    # one docking region: every observation admitted to a site must be
    # compatible with every observation already in that site.  When this is
    # not true, retain multiple exploratory boxes for user review.
    components = []
    for index in range(len(usable)):
        candidates = [
            component_index for component_index, component in enumerate(components)
            if all(member in compatible[index] for member in component)
        ]
        if candidates:
            # Prefer the largest established compatible site; stable index is
            # the deterministic tie-breaker.
            chosen = max(candidates, key=lambda item: (len(components[item]), -item))
            components[chosen].append(index)
        else:
            components.append([index])

    cavity_atoms = {}

    def component_evidence(component):
        ligand_atom_sets = [usable[index][1] for index in component]
        pockets = sorted({
            validated_matched_cavity(usable[index][0]) for index in component
        } - {None})
        atom_sets = list(ligand_atom_sets)
        included_pockets = []
        for pocket in pockets:
            if pocket not in cavity_atoms:
                path = evidence_root.parent / "frozen_pockets" / f"pocket{pocket}_atm.pdb"
                cavity_atoms[pocket] = (
                    pdb_atom_coordinates(path) if path.is_file() else np.empty((0, 3))
                )
            if len(cavity_atoms[pocket]):
                proposed = atom_sets + [cavity_atoms[pocket]]
                _, proposed_size = _evidence_box(
                    proposed, minimum_box_size, ligand_margin,
                )
                if (max(proposed_size) <= maximum_box_dimension and
                        float(np.prod(proposed_size)) <= maximum_combined_box_volume):
                    atom_sets = proposed
                    included_pockets.append(pocket)
        return atom_sets, included_pockets

    def component_box(component):
        atom_sets, _ = component_evidence(component)
        return _evidence_box(atom_sets, minimum_box_size, ligand_margin)

    # Preserve direct ligand/cavity groupings, then merge overlapping
    # preliminary evidence regions in descending-overlap order.  Cross-cluster
    # overlap is the strongest original pairwise overlap, while the volume cap
    # is evaluated on the complete proposed merged region.  This permits a
    # compact chain of mutually supported sites without allowing transitive
    # growth into an unbounded whole-protein box.
    preliminary = list(components)
    preliminary_boxes = [component_box(component) for component in preliminary]
    clusters = [{index} for index in range(len(preliminary))]
    while True:
        choices = []
        for left in range(len(clusters)):
            for right in range(left + 1, len(clusters)):
                # Complete-link overlap avoids recreating the same transitive
                # growth across preliminary groups.
                overlap = min(
                    _box_overlap_fraction(preliminary_boxes[a], preliminary_boxes[b])
                    for a in clusters[left] for b in clusters[right]
                )
                if overlap < minimum_box_overlap:
                    continue
                merged_component = sorted({
                    member
                    for preliminary_index in clusters[left] | clusters[right]
                    for member in preliminary[preliminary_index]
                })
                _, merged_size = component_box(merged_component)
                merged_volume = float(np.prod(merged_size))
                if (max(merged_size) <= maximum_box_dimension and
                        merged_volume <= maximum_combined_box_volume):
                    choices.append((overlap, -merged_volume, -left, -right,
                                    left, right, merged_component))
        if not choices:
            break
        _, _, _, _, left, right, _ = max(choices)
        clusters[left] |= clusters[right]
        clusters.pop(right)
    components = [
        sorted({member for preliminary_index in cluster
                for member in preliminary[preliminary_index]})
        for cluster in clusters
    ]
    groups = []
    for component in components:
        members = [usable[index] for index in component]
        # Prefer the most target-specific evidence class before using molecular
        # size as the visual tie-breaker.  A larger homolog ligand must not
        # displace an exact-sequence or same-protein representative when the
        # homolog evidence has not been approved for the protocol decision.
        evidence_priority = {
            "same_protein": 3,
            "exact_sequence_match": 2,
            "close_structural_homolog": 1,
        }
        representative_row = max(
            (row for row, _, _, _ in members),
            key=lambda row: (
                evidence_priority.get(row.get("evidence_class"), 0),
                int(row.get("ligand_heavy_atom_count", 0)),
                row.get("ligand", ""), row.get("entry", ""),
                row.get("ligand_chain", ""), row.get("ligand_residue", ""),
            ),
        )
        evidence_atoms, included_cavities = component_evidence(component)
        center, size = _evidence_box(
            evidence_atoms, minimum_box_size, ligand_margin,
        )
        class_counts, cavity_counts = {}, {}
        for row, _, _, _ in members:
            category = row.get("evidence_class", "identity_uncertain")
            class_counts[category] = class_counts.get(category, 0) + 1
            pocket = validated_matched_cavity(row)
            if pocket is not None:
                cavity_counts[str(pocket)] = cavity_counts.get(str(pocket), 0) + 1
        groups.append({
            "site_number": 0, "member_count": len(members),
            "members": [{"entry": row.get("entry"), "ligand": row.get("ligand"),
                         "ligand_chain": row.get("ligand_chain"),
                         "ligand_residue": row.get("ligand_residue"),
                         "aligned_chain": row.get("aligned_chain"),
                         "ligand_heavy_atom_count": row.get("ligand_heavy_atom_count", 0),
                         "aligned_ligand_pdb": row.get("aligned_ligand_pdb"),
                         "evidence_class": row.get("evidence_class"),
                         "matched_cavity": validated_matched_cavity(row),
                         "source_ligand_id": source_ligand_id(row),
                         "chain_assignment_ambiguous": row.get("chain_assignment_ambiguous", False)}
                        for row, _, _, _ in members],
            "representative_ligand": {
                "entry": representative_row.get("entry"),
                "ligand": representative_row.get("ligand"),
                "ligand_chain": representative_row.get("ligand_chain"),
                "ligand_residue": representative_row.get("ligand_residue"),
                "ligand_heavy_atom_count": representative_row.get("ligand_heavy_atom_count", 0),
                "aligned_ligand_pdb": representative_row.get("aligned_ligand_pdb"),
                "evidence_class": representative_row.get("evidence_class"),
                "source_ligand_id": source_ligand_id(representative_row),
            },
            "evidence_class_counts": class_counts,
            "matched_cavity_counts": cavity_counts,
            "box": {f"center_{axis}": round(float(center[index]), 3)
                    for index, axis in enumerate("xyz")},
            "minimum_box_size_angstrom": minimum_box_size,
            "ligand_margin_angstrom": ligand_margin,
            "site_grouping_rule": (
                "aligned heavy-atom overlap, shared unique fpocket cavity, or "
                "overlapping evidence boxes within the recorded volume limit"
            ),
            "atom_contact_cutoff_angstrom": atom_contact_cutoff,
            "minimum_ligand_overlap_fraction": minimum_ligand_overlap,
            "minimum_box_overlap_fraction": minimum_box_overlap,
            "maximum_combined_box_volume_angstrom3": maximum_combined_box_volume,
            "maximum_box_dimension_angstrom": maximum_box_dimension,
            "box_evidence": {
                "aligned_ligand_pose_count": len(members),
                "included_fpocket_candidates": included_cavities,
                "margin_angstrom": ligand_margin,
                "volume_angstrom3": round(float(np.prod(size)), 3),
                "basis": (
                    "aligned ligand heavy atoms plus corresponding fpocket cavity atoms"
                    if included_cavities else "aligned ligand heavy atoms"
                ),
                "search_classification": (
                    "broad" if max(size) >= 40.0 or float(np.prod(size)) >= 64000.0
                    else "localized"
                ),
                "recommended_engine": (
                    # Engine choice is deliberately independent of box size.
                    # Exploratory studies may retain multiple evidence-backed
                    # boxes; QuickVina-W is the default for each, while Vina
                    # remains an explicit compatibility override.
                    "qvinaw"
                ),
            },
        })
        groups[-1]["box"].update({f"size_{axis}": round(float(size[index]), 3)
                                  for index, axis in enumerate("xyz")})
        top_count = max(cavity_counts.values(), default=0)
        recovered_fraction = top_count / max(1, len(members))
        groups[-1]["fpocket_recovery"] = {
            "status": (
                "recovered" if recovered_fraction >= 0.5
                else "partial_correspondence" if recovered_fraction > 0
                else "not_recovered"
            ),
            "best_matching_pocket": (
                int(max(cavity_counts, key=lambda key: (cavity_counts[key], -int(key))))
                if cavity_counts else None
            ),
            "supporting_pose_fraction": round(recovered_fraction, 4),
        }
    groups.sort(key=lambda group: (
        -(group["evidence_class_counts"].get("same_protein", 0)
          + group["evidence_class_counts"].get("exact_sequence_match", 0)),
        -group["member_count"],
    ))
    ligand_only_number = 0
    for number, group in enumerate(groups, 1):
        group["site_number"] = number
        matching_pocket = (group.get("fpocket_recovery") or {}).get("best_matching_pocket")
        if not matching_pocket:
            ligand_only_number += 1
        group["site_identity"] = {
            "canonical_label": (
                f"P{matching_pocket}" if matching_pocket else f"L{ligand_only_number}"
            ),
            "evidence_sources": (
                ["aligned deposited ligands", "fpocket cavity"]
                if matching_pocket else ["aligned deposited ligands"]
            ),
            "is_separate_from_fpocket": not bool(matching_pocket),
        }
    return groups


def sequence_search(sequence, identity_cutoff=0.9, rows=40, opener=urllib.request.urlopen):
    """Query the official RCSB sequence service for related polymer entities."""
    payload = {
        "query": {"type": "terminal", "service": "sequence", "parameters": {
            "evalue_cutoff": 1e-5, "identity_cutoff": identity_cutoff,
            "sequence_type": "protein", "value": sequence,
        }},
        "request_options": {"paginate": {"start": 0, "rows": rows},
                            "scoring_strategy": "sequence"},
        "return_type": "polymer_entity",
    }
    request = urllib.request.Request(
        SEARCH_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": "Docking-Universal"},
        method="POST",
    )
    with opener(request, timeout=30) as response:
        result = json.load(response)
    return [item["identifier"] for item in result.get("result_set", [])]


def download_entry(entry, opener=urllib.request.urlopen):
    """Download coordinates, converting modern mmCIF-only entries to PDB text."""
    request = urllib.request.Request(
        DOWNLOAD_URL.format(entry=entry.upper()), headers={"User-Agent": "Docking-Universal"}
    )
    try:
        with opener(request, timeout=30) as response:
            return response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        if exc.code != 404:
            raise
    cif_request = urllib.request.Request(
        f"https://files.rcsb.org/download/{entry.upper()}.cif",
        headers={"User-Agent": "Docking-Universal"},
    )
    with opener(cif_request, timeout=30) as response:
        cif_text = response.read().decode("utf-8", errors="replace")
    try:
        import gemmi
    except ImportError as exc:
        raise OSError("RCSB entry is mmCIF-only and gemmi is unavailable") from exc
    document = gemmi.cif.read_string(cif_text)
    return gemmi.make_structure_from_block(document.sole_block()).make_pdb_string()


def collect_pocket_evidence(
    receptor_pdb,
    boxes,
    output_dir,
    *,
    query_identity_cutoff=0.90,
    minimum_alignment_identity=0.90,
    minimum_query_coverage=0.70,
    maximum_ca_rmsd_angstrom=2.0,
    max_entries=20,
    opener=urllib.request.urlopen,
):
    """Collect sequence-screened, backbone-verified ligand-site evidence.

    The RCSB sequence search is deliberately a broad first pass.  A hit can
    contribute ligand evidence only after its coordinate model passes the
    explicit sequence-identity, query-coverage, and C-alpha RMSD limits below.
    This prevents an exact database-sequence cutoff from discarding useful
    structures while keeping the final structural comparison auditable.
    """
    receptor_pdb = Path(receptor_pdb)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    reference_chains = protein_chains(receptor_pdb.read_text(errors="replace"))
    reference_identifiers_by_chain = protein_database_identifiers(
        receptor_pdb.read_text(errors="replace")
    )
    if not reference_chains:
        raise ValueError("prepared receptor contains no protein C-alpha atoms")
    reference_id, reference = max(reference_chains.items(), key=lambda item: len(item[1]))
    reference_identifiers = reference_identifiers_by_chain.get(reference_id, set())
    sequence = "".join(item.one_letter for item in reference)
    identifiers = sequence_search(sequence, query_identity_cutoff, max_entries * 2, opener)
    entries = []
    for identifier in identifiers:
        entry = identifier.split("_", 1)[0].upper()
        if entry not in entries:
            entries.append(entry)
        if len(entries) >= max_entries:
            break
    print(f"  Verifying {len(entries)} candidate related PDB entr{'y' if len(entries) == 1 else 'ies'}...", flush=True)
    geometries = [
        (index, Path(box), *read_box_geometry(box))
        for index, box in enumerate(boxes, 1)
    ]
    pocket_atoms_by_number = {}
    for pocket_number, box, _, _ in geometries:
        pocket_file = box.parent / "frozen_pockets" / f"pocket{pocket_number}_atm.pdb"
        if pocket_file.is_file():
            pocket_atoms_by_number[pocket_number] = pdb_atom_coordinates(pocket_file)
    evidence = []
    skipped = []
    downloaded_components = {}
    for index, entry in enumerate(entries, 1):
        print(f"  Checking related structure {index}/{len(entries)}: {entry}", flush=True)
        try:
            text = download_entry(entry, opener)
        except (OSError, urllib.error.URLError) as exc:
            skipped.append({"entry": entry, "reason": f"download failed: {exc}"})
            continue
        candidates = protein_chains(text)
        protein_atoms_by_chain = protein_heavy_atoms_by_chain(text)
        candidate_identifiers_by_chain = protein_database_identifiers(text)
        ranked = []
        for chain_id, chain in candidates.items():
            pairs, identity, coverage = chain_match(reference, chain)
            candidate_ids = candidate_identifiers_by_chain.get(chain_id, set())
            ranked.append((identity * coverage, identity, coverage, chain_id, chain, pairs, candidate_ids))
        if not ranked:
            skipped.append({"entry": entry, "reason": "no compatible protein chain"})
            continue
        valid_alignments = []
        for rank_score, identity, coverage, chain_id, chain, pairs, candidate_identifiers in ranked:
            if (identity < minimum_alignment_identity
                    or coverage < minimum_query_coverage
                    or len(pairs) < 12):
                continue
            rotation, translation, rmsd = superposition(reference, chain, pairs)
            if rmsd > maximum_ca_rmsd_angstrom:
                continue
            shared_identifiers = reference_identifiers & candidate_identifiers
            protein_identity_basis = (
                "shared authoritative accession"
                if shared_identifiers
                else "high sequence identity and C-alpha similarity despite accession mismatch"
                if reference_identifiers and candidate_identifiers
                else "accession unavailable; sequence and C-alpha fallback"
            )
            valid_alignments.append({
                "rank_score": rank_score, "identity": identity, "coverage": coverage,
                "chain_id": chain_id, "rotation": rotation, "translation": translation,
                "rmsd": rmsd, "candidate_identifiers": candidate_identifiers,
                "shared_identifiers": shared_identifiers,
                "protein_identity_basis": protein_identity_basis,
            })
        if not valid_alignments:
            selected_rank = choose_alignment_candidate(
                ranked, reference_id, reference_identifiers,
            )
            _, identity, coverage, _, chain, pairs, _ = selected_rank
            if (identity < minimum_alignment_identity
                    or coverage < minimum_query_coverage
                    or len(pairs) < 12):
                skipped.append({
                    "entry": entry,
                    "reason": "insufficient aligned-chain identity or coverage",
                    "sequence_identity": round(identity, 4),
                    "query_coverage": round(coverage, 4),
                })
                continue
            _, _, rmsd = superposition(reference, chain, pairs)
            skipped.append({
                "entry": entry,
                "reason": "C-alpha backbone RMSD exceeds structural-similarity limit",
                "sequence_identity": round(identity, 4),
                "query_coverage": round(coverage, 4),
                "ca_rmsd_angstrom": round(rmsd, 3),
                "maximum_ca_rmsd_angstrom": maximum_ca_rmsd_angstrom,
            })
            continue
        for ligand in deposited_ligands(text, entry):
            associated = []
            for alignment in valid_alignments:
                contact = ligand_chain_contact(
                    ligand.atoms,
                    protein_atoms_by_chain.get(alignment["chain_id"]),
                )
                if contact["minimum_distance_angstrom"] <= contact["contact_cutoff_angstrom"]:
                    associated.append((alignment, contact))
            if not associated:
                skipped.append({
                    "entry": entry, "ligand": ligand.name,
                    "ligand_chain": ligand.chain, "ligand_residue": ligand.number,
                    "reason": "ligand does not contact any structurally accepted aligned protein chain",
                })
                continue
            (alignment, chain_contact), chain_assignment_ambiguous, same_chain_assignment = (
                choose_ligand_alignment(associated, ligand.chain, candidates)
            )
            identity = alignment["identity"]
            coverage = alignment["coverage"]
            chain_id = alignment["chain_id"]
            rotation = alignment["rotation"]
            translation = alignment["translation"]
            rmsd = alignment["rmsd"]
            shared_identifiers = alignment["shared_identifiers"]
            protein_identity_basis = alignment["protein_identity_basis"]
            transformed = ligand.atoms @ rotation + translation
            safe_residue = "".join(character if character.isalnum() else "_" for character in ligand.number)
            ligand_file = (
                output_dir / "aligned_ligands"
                / f"{entry}_{ligand.name}_{ligand.chain}_{safe_residue}.pdb"
            )
            write_aligned_ligand(ligand, transformed, ligand_file)
            ccd_file = output_dir / "ccd" / f"{ligand.name}_ideal.sdf"
            ccd_error = None
            if ligand.name not in downloaded_components:
                try:
                    download_ccd_sdf(ligand.name, ccd_file, opener)
                    downloaded_components[ligand.name] = ccd_file
                except (OSError, urllib.error.URLError, ValueError) as exc:
                    downloaded_components[ligand.name] = None
                    ccd_error = str(exc)
            retained_ccd = downloaded_components[ligand.name]
            relationships = []
            cavity_scores, matched_pocket, cavity_match_reason = classify_cavity_match(
                transformed, pocket_atoms_by_number,
            )
            for pocket_number, box, center, size in geometries:
                relationships.append({
                    "pocket_number": pocket_number, "box": box.name,
                    **ligand_box_relationship(transformed, center, size),
                    **cavity_scores.get(pocket_number, {}),
                    "cavity_match": pocket_number == matched_pocket,
                })
            # Contact-only matches are insufficient when alignment or symmetry
            # placement leaves the ligand outside the candidate's box.  Keep
            # such evidence ligand-defined rather than assigning it to a
            # spatially unrelated pocket.
            if matched_pocket is not None:
                matched_relationship = next(
                    (item for item in relationships if item["pocket_number"] == matched_pocket),
                    None,
                )
                if not matched_relationship or not matched_relationship["all_heavy_atoms_inside"]:
                    matched_pocket = None
                    cavity_match_reason = "contact match rejected because ligand is not fully contained in the candidate box"
                    for item in relationships:
                        item["cavity_match"] = False
            if chain_assignment_ambiguous and matched_pocket is not None:
                matched_pocket = None
                cavity_match_reason = "cavity match withheld because the ligand-to-protein chain assignment is ambiguous"
                for item in relationships:
                    item["cavity_match"] = False
            nearest = min(
                relationships,
                key=lambda item: (-item["heavy_atom_fraction_inside"],
                                  item["minimum_distance_to_box_angstrom"],
                                  item["centroid_distance_angstrom"]),
            )
            evidence.append({
                "entry": entry, "reference_chain": reference_id, "aligned_chain": chain_id,
                "source_ligand_id": f"{entry}/{ligand.name}/{ligand.chain}/{ligand.number}",
                "sequence_identity": round(identity, 4), "query_coverage": round(coverage, 4),
                "ca_rmsd_angstrom": round(rmsd, 3), "ligand": ligand.name,
                "ligand_heavy_atom_count": int(len(ligand.atoms)),
                "aligned_ligand_pdb": str(ligand_file.relative_to(output_dir)),
                "ccd_ideal_sdf": str(retained_ccd.relative_to(output_dir)) if retained_ccd else None,
                "ccd_ideal_sdf_error": ccd_error,
                "protein_identity_basis": protein_identity_basis,
                "evidence_class": evidence_class(shared_identifiers, identity, coverage),
                "shared_protein_identifiers": sorted(shared_identifiers),
                "ligand_chain": ligand.chain, "ligand_residue": ligand.number,
                "source_chain_contact_fraction": round(chain_contact["contact_fraction"], 4),
                "source_chain_minimum_distance_angstrom": round(
                    chain_contact["minimum_distance_angstrom"], 3
                ),
                "source_chain_contact_cutoff_angstrom": chain_contact["contact_cutoff_angstrom"],
                "alignment_selection_basis": "ligand contact to structurally accepted protein chain",
                "ligand_chain_matches_aligned_chain": same_chain_assignment,
                "chain_assignment_ambiguous": chain_assignment_ambiguous,
                "nearest_pocket": nearest["pocket_number"],
                "ligand_centroid_inside_box": nearest["centroid_inside"],
                "ligand_heavy_atom_fraction_inside_box": nearest["heavy_atom_fraction_inside"],
                "ligand_fully_inside_box": nearest["all_heavy_atoms_inside"],
                "minimum_distance_to_box_angstrom": nearest["minimum_distance_to_box_angstrom"],
                "matched_cavity": matched_pocket,
                "cavity_match_reason": cavity_match_reason,
                "pocket_relationships": relationships,
            })
    record = {
        "schema_name": "docking-universal-pocket-evidence", "schema_version": 1,
        "status": "completed", "selection_policy": "evidence_only_user_decides",
        "query": {
            "reference_file": receptor_pdb.name,
            "reference_chain": reference_id,
            "reference_protein_identifiers": sorted(reference_identifiers),
            "sequence_length": len(sequence),
            "query_identity_cutoff": query_identity_cutoff,
            "minimum_alignment_identity": minimum_alignment_identity,
            "minimum_query_coverage": minimum_query_coverage,
            "maximum_ca_rmsd_angstrom": maximum_ca_rmsd_angstrom,
            "maximum_entries": max_entries,
            "filter_order": [
                "sequence search",
                "authoritative protein-accession comparison when available",
                "coordinate-sequence alignment",
                "C-alpha RMSD",
                "ligand-chain identifier preference with contact verification",
                "ambiguous chain-assignment detection",
                "ligand transformation into the reference frame",
                "unique fpocket contact and full-box-containment agreement",
            ],
        },
        "candidate_entries": entries, "evidence": evidence, "skipped": skipped,
    }
    record["ligand_site_groups"] = group_ligand_sites(record, output_dir)
    ambiguous_rows = [row for row in evidence if row.get("chain_assignment_ambiguous")]
    record["site_grouping_audit"] = {
        "minimum_box_overlap_fraction": DEFAULT_MINIMUM_BOX_OVERLAP,
        "maximum_combined_box_volume_angstrom3": DEFAULT_MAXIMUM_COMBINED_BOX_VOLUME,
        "maximum_box_dimension_angstrom": DEFAULT_MAXIMUM_BOX_DIMENSION,
        "box_basis": "accepted aligned ligand heavy atoms, with corresponding fpocket geometry included only within the recorded size limits",
        "ambiguous_chain_assignments_excluded": [
            source_ligand_id(row) for row in ambiguous_rows if source_ligand_id(row)
        ],
    }
    json_path = output_dir / "pdb_ligand_site_evidence.json"
    json_path.write_text(json.dumps(record, indent=2) + "\n")
    tsv_path = output_dir / "pdb_ligand_site_evidence.tsv"
    headings = ("entry", "source_ligand_id", "aligned_chain", "sequence_identity", "query_coverage",
                "ca_rmsd_angstrom", "protein_identity_basis", "evidence_class", "shared_protein_identifiers",
                "ligand", "ligand_heavy_atom_count", "ligand_chain", "ligand_residue",
                "source_chain_contact_fraction", "source_chain_minimum_distance_angstrom",
                "source_chain_contact_cutoff_angstrom", "alignment_selection_basis",
                "ligand_chain_matches_aligned_chain", "chain_assignment_ambiguous",
                "nearest_pocket", "ligand_centroid_inside_box",
                "ligand_heavy_atom_fraction_inside_box", "ligand_fully_inside_box",
                "minimum_distance_to_box_angstrom", "matched_cavity", "cavity_match_reason")
    with tsv_path.open("w") as handle:
        handle.write("\t".join(headings) + "\n")
        for row in evidence:
            values = [
                ";".join(str(item) for item in row[key])
                if isinstance(row[key], list) else str(row[key])
                for key in headings
            ]
            handle.write("\t".join(values) + "\n")
    return record


def summarize_pocket_evidence(record):
    """Summarize box evidence, requiring full ligand containment for support.

    Partial overlap is retained as a warning because such a box would truncate
    the aligned deposited pose.  It must not promote a pocket, contribute its
    ligand identity to the supporting set, or supply the displayed example.
    """
    summary = {}
    for row in record.get("evidence", []):
        # A ligand may fit fully inside more than one candidate box. Credit
        # every such box; record lesser overlap only as a diagnostic warning.
        relationships = row.get("pocket_relationships") or [{
            "pocket_number": row.get("nearest_pocket"),
            "heavy_atom_fraction_inside": row.get("ligand_heavy_atom_fraction_inside_box", 0.0),
            "all_heavy_atoms_inside": row.get("ligand_fully_inside_box", False),
        }]
        has_cavity_classification = any("cavity_match" in item for item in relationships)
        for relationship in relationships:
            if has_cavity_classification and not relationship.get("cavity_match", False):
                continue
            fraction = float(relationship.get("heavy_atom_fraction_inside", 0.0))
            pocket_number = relationship.get("pocket_number")
            if fraction <= 0 or pocket_number is None:
                continue
            bucket = summary.setdefault(
                pocket_number,
                {"contained_ligands": 0, "overlapping_ligands": 0,
                 "entries": set(), "ligands": set(),
                 "source_pairs": set(), "partial_entries": set(),
                 "partial_ligands": set(), "partial_source_pairs": set(),
                 "representative": None},
            )
            fully_contained = bool(relationship.get("all_heavy_atoms_inside"))
            if not fully_contained:
                bucket["overlapping_ligands"] += 1
                bucket["partial_entries"].add(row["entry"])
                bucket["partial_ligands"].add(row.get("ligand", "unknown"))
                bucket["partial_source_pairs"].add((row["entry"], row.get("ligand", "unknown")))
                continue
            bucket["contained_ligands"] += 1
            bucket["entries"].add(row["entry"])
            bucket["ligands"].add(row.get("ligand", "unknown"))
            bucket["source_pairs"].add((row["entry"], row.get("ligand", "unknown")))
            candidate_key = (
                int(row.get("ligand_heavy_atom_count", 0)),
                row.get("ligand", ""), row.get("entry", ""),
                row.get("ligand_chain", ""), row.get("ligand_residue", ""),
            )
            current = bucket["representative"]
            if current is None or candidate_key > current[0]:
                bucket["representative"] = (candidate_key, row)
    result = {}
    for pocket, value in summary.items():
        representative = value["representative"][1] if value["representative"] else {}
        result[pocket] = {
            "contained_ligands": value["contained_ligands"],
            "overlapping_ligands": value["overlapping_ligands"],
            "entries": sorted(value["entries"]),
            "ligands": sorted(value["ligands"]),
            "source_pairs": [
                {"pdb_id": entry, "ligand_id": ligand}
                for entry, ligand in sorted(value["source_pairs"])
            ],
            "partial_entries": sorted(value["partial_entries"]),
            "partial_ligands": sorted(value["partial_ligands"]),
            "partial_source_pairs": [
                {"pdb_id": entry, "ligand_id": ligand}
                for entry, ligand in sorted(value["partial_source_pairs"])
            ],
            "example_ligand": representative.get("ligand"),
            "example_entry": representative.get("entry"),
            "example_heavy_atom_count": representative.get("ligand_heavy_atom_count", 0),
            "example_aligned_ligand_pdb": representative.get("aligned_ligand_pdb"),
            "example_ccd_ideal_sdf": representative.get("ccd_ideal_sdf"),
        }
    return result
