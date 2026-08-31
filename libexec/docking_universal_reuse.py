"""Scientific-output comparison for immediate and later protocol reuse."""

import csv
import hashlib
import json
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def csv_without_path(path, omitted):
    with Path(path).open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    return [
        {key: value for key, value in row.items() if key not in omitted}
        for row in rows
    ]


def one_compound(study):
    compounds = sorted(path for path in (Path(study) / "compounds").iterdir() if path.is_dir())
    if len(compounds) != 1:
        raise ValueError(f"reuse comparison requires exactly one compound in {study}")
    return compounds[0]


def compare_reuse_studies(first, second):
    """Compare stable scientific results while excluding paths and timestamps."""
    first_compound = one_compound(first)
    second_compound = one_compound(second)
    if first_compound.name != second_compound.name:
        raise ValueError("compound identifiers differ between reuse studies")

    first_manifest = json.loads((first_compound / "screen_manifest.json").read_text())
    second_manifest = json.loads((second_compound / "screen_manifest.json").read_text())
    stable_manifest_keys = (
        "workflow", "completion_status", "protocol_type", "protocol_sha256",
        "ligand_sha256", "receptor", "box", "engine", "seeds",
        "ensemble_parameters", "docking_job_count",
    )
    for key in stable_manifest_keys:
        if first_manifest.get(key) != second_manifest.get(key):
            raise ValueError(f"protocol-reuse manifest differs for {key}")

    exact_relative = (
        "independent_ensemble.sdf",
        "ligand_preparation/pdbqt_ligands/independent_ensemble_1.pdbqt",
        "pose_analysis/cluster_summary.csv",
    )
    for relative in exact_relative:
        if sha256(first_compound / relative) != sha256(second_compound / relative):
            raise ValueError(f"protocol-reuse artifact differs: {relative}")

    engine = first_manifest["engine"]
    first_poses = sorted(first_compound.glob(f"seed_*/docking/*_{engine}.pdbqt"))
    second_poses = sorted(second_compound.glob(f"seed_*/docking/*_{engine}.pdbqt"))
    if len(first_poses) != len(second_poses) or not first_poses:
        raise ValueError("protocol-reuse docking-output counts differ or are empty")
    for left, right in zip(first_poses, second_poses):
        if left.relative_to(first_compound).parts[0] != right.relative_to(second_compound).parts[0]:
            raise ValueError("protocol-reuse seed directories differ")
        if sha256(left) != sha256(right):
            raise ValueError(f"protocol-reuse poses differ for {left.parent.parent.name}")

    if csv_without_path(first_compound / "all_scores.csv", {"file_path"}) != csv_without_path(
        second_compound / "all_scores.csv", {"file_path"}
    ):
        raise ValueError("protocol-reuse docking scores differ")
    if csv_without_path(first_compound / "pose_analysis/pose_inventory.csv", {"source"}) != csv_without_path(
        second_compound / "pose_analysis/pose_inventory.csv", {"source"}
    ):
        raise ValueError("protocol-reuse pose clusters differ")
    return {
        "compound": first_compound.name,
        "engine": first_manifest["engine"],
        "seeds": first_manifest["seeds"],
        "docking_outputs": len(first_poses),
        "status": "equivalent",
    }
