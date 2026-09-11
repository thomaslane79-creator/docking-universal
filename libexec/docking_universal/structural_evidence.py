"""Retain related-structure evidence once for present and future analyses.

The pocket workflow discovers and validates related PDB structures.  This
module preserves those source coordinates, accepted alignments, residue maps,
and atom-level observations in a central ensemble record.  Pocket comparison,
B-factor analysis, and future rotamer analysis can therefore share exactly the
same accepted evidence instead of repeating a search with potentially different
results.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


SCHEMA_NAME = "docking-universal-structural-ensemble"
SCHEMA_VERSION = 1


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _float_field(line: str, start: int, end: int) -> float | None:
    try:
        return float(line[start:end])
    except ValueError:
        return None


def retain_source_structure(root: Path | str, entry: str, pdb_text: str) -> dict[str, Any]:
    """Retain an unmodified downloaded structure and its basic provenance."""
    root = Path(root)
    data = pdb_text.encode("utf-8")
    path = root / "source_structures" / f"{entry.upper()}.pdb"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    methods = [line[10:].strip() for line in pdb_text.splitlines() if line.startswith("EXPDTA")]
    return {
        "entry": entry.upper(),
        "source_coordinates": str(path.relative_to(root)),
        "sha256": _sha256_bytes(data),
        "experimental_method": " ".join(methods) or "not recorded in PDB text",
    }


def retain_accepted_alignment(
    root: Path | str,
    *,
    entry: str,
    pdb_text: str,
    reference_chain: str,
    reference_residues: list[Any],
    source_chain: str,
    source_residues: list[Any],
    pairs: Iterable[tuple[int, int]],
    rotation: Any,
    translation: Any,
    sequence_identity: float,
    query_coverage: float,
    ca_rmsd_angstrom: float,
    protein_identity_basis: str,
    shared_protein_identifiers: Iterable[str],
) -> dict[str, Any]:
    """Retain an accepted chain in the reference frame plus lossless atom data."""
    root = Path(root)
    alignment_id = f"{entry.upper()}_{source_chain}_to_{reference_chain}"
    pair_list = list(pairs)
    source_to_reference = {
        source_residues[source_index].number: reference_residues[reference_index]
        for reference_index, source_index in pair_list
    }
    residue_mapping = []
    mutations = []
    for reference_index, source_index in pair_list:
        reference = reference_residues[reference_index]
        source = source_residues[source_index]
        item = {
            "reference_chain": reference_chain,
            "reference_residue_number": reference.number,
            "reference_residue_name": reference.name,
            "source_chain": source_chain,
            "source_residue_number": source.number,
            "source_residue_name": source.name,
            "identity": reference.one_letter == source.one_letter,
        }
        residue_mapping.append(item)
        if not item["identity"]:
            mutations.append(item)

    aligned_path = root / "aligned_chains" / f"{alignment_id}.pdb"
    atom_path = root / "atom_observations" / f"{alignment_id}.jsonl"
    aligned_path.parent.mkdir(parents=True, exist_ok=True)
    atom_path.parent.mkdir(parents=True, exist_ok=True)
    aligned_lines = []
    atom_rows = []
    for line in pdb_text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        chain = line[21:22].strip() or "_"
        if chain != source_chain:
            continue
        source_number = line[22:27].strip()
        reference = source_to_reference.get(source_number)
        if reference is None:
            continue
        try:
            source_xyz = [float(line[30:38]), float(line[38:46]), float(line[46:54])]
        except ValueError:
            continue
        aligned_xyz_array = source_xyz @ rotation + translation
        aligned_xyz = [round(float(value), 6) for value in aligned_xyz_array]
        padded = line.ljust(80)
        aligned_lines.append(
            f"{padded[:30]}{aligned_xyz[0]:8.3f}{aligned_xyz[1]:8.3f}{aligned_xyz[2]:8.3f}{padded[54:]}".rstrip()
        )
        atom_rows.append({
            "entry": entry.upper(),
            "alignment_id": alignment_id,
            "record_type": line[:6].strip(),
            "atom_name": line[12:16].strip(),
            "alternate_location": line[16:17].strip(),
            "source_residue_name": line[17:20].strip(),
            "source_chain": source_chain,
            "source_residue_number": source_number,
            "reference_chain": reference_chain,
            "reference_residue_name": reference.name,
            "reference_residue_number": reference.number,
            "occupancy": _float_field(line, 54, 60),
            "b_factor": _float_field(line, 60, 66),
            "element": line[76:78].strip(),
            "source_xyz": source_xyz,
            "aligned_xyz": aligned_xyz,
        })
    aligned_path.write_text("\n".join(aligned_lines) + "\nEND\n")
    with atom_path.open("w") as handle:
        for row in atom_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")

    return {
        "alignment_id": alignment_id,
        "entry": entry.upper(),
        "reference_chain": reference_chain,
        "source_chain": source_chain,
        "sequence_identity": round(float(sequence_identity), 4),
        "query_coverage": round(float(query_coverage), 4),
        "ca_rmsd_angstrom": round(float(ca_rmsd_angstrom), 3),
        "protein_identity_basis": protein_identity_basis,
        "shared_protein_identifiers": sorted(shared_protein_identifiers),
        "rotation_source_to_reference": [[round(float(value), 10) for value in row] for row in rotation],
        "translation_source_to_reference": [round(float(value), 10) for value in translation],
        "residue_mapping": residue_mapping,
        "mutations": mutations,
        "aligned_chain_coordinates": str(aligned_path.relative_to(root)),
        "atom_observations": str(atom_path.relative_to(root)),
        "atom_observation_count": len(atom_rows),
        "available_for": [
            "pocket_and_ligand_context",
            "per_structure_b_factor_analysis",
            "cross_structure_rotamer_analysis",
        ],
    }


def write_ensemble_manifest(
    root: Path | str,
    *,
    reference_file: str,
    sources: list[dict[str, Any]],
    alignments: list[dict[str, Any]],
    qualification: dict[str, Any],
) -> Path:
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_name": SCHEMA_NAME,
        "schema_version": SCHEMA_VERSION,
        "purpose": "shared retained evidence; no flexibility conclusion is implied",
        "reference_file": reference_file,
        "qualification": qualification,
        "sources": sources,
        "accepted_alignments": alignments,
        "future_analysis_inputs": {
            "b_factors": "raw atom B-factor and occupancy fields retained per accepted structure",
            "rotamers": "mapped, reference-frame side-chain coordinates retained per accepted structure",
        },
    }
    path = root / "structural_ensemble_manifest.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return path
