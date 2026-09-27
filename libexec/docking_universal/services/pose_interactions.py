"""Materialize exact retained poses for lazy, per-pose interaction analysis."""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


@dataclass(frozen=True)
class PoseReviewRecord:
    pose_id: int
    cluster_id: int
    energy_kcal_per_mol: float
    seed: int | None
    conformer: str
    model: int | None
    selected_cluster: bool

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PoseInteractionPlan:
    """Exact local inputs and outputs for one serialized pose-analysis job."""

    record: PoseReviewRecord
    cache: Path
    command: tuple[str, ...]
    diagram: Path
    evidence: Path
    manifest: Path
    cached: bool


def build_pose_interaction_plan(
    analysis_root: Path | str,
    pose_id: int,
    *,
    worker_command: Sequence[str | Path],
) -> PoseInteractionPlan:
    """Materialize an exact pose and construct the approved local-worker call.

    The worker is an explicit command boundary so the application host never
    imports PLIP, GUI, or renderer runtimes into its own Python process.
    """
    if not worker_command:
        raise ValueError("An approved local pose-interaction worker is required")
    record, cache = materialize_pose_interaction_inputs(analysis_root, pose_id)
    diagram = cache / "interaction_diagram.png"
    evidence = cache / "plip" / "report.xml"
    manifest = cache / "interaction_manifest.json"
    cached = all(path.is_file() for path in (diagram, evidence, manifest))
    command = tuple(map(str, worker_command)) + (
        "--cache", str(cache), "--pose-id", str(record.pose_id),
        "--cluster-id", str(record.cluster_id), "--score", str(record.energy_kcal_per_mol),
        "--renderer-policy", "approved-poseedit-local-v1",
    )
    return PoseInteractionPlan(record, cache, command, diagram, evidence, manifest, cached)


def validate_pose_interaction_outputs(plan: PoseInteractionPlan) -> dict:
    """Reject missing, mismatched, or non-local renderer output."""
    missing = [str(path) for path in (plan.diagram, plan.evidence, plan.manifest) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Pose interaction worker omitted required output: " + ", ".join(missing))
    try:
        manifest = json.loads(plan.manifest.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Invalid pose interaction manifest: {exc}") from None
    expected = {
        "pose_id": plan.record.pose_id,
        "cluster_id": plan.record.cluster_id,
        "renderer_policy": "approved-poseedit-local-v1",
        "network_used": False,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"Pose interaction manifest mismatch for {key}: expected {value!r}")
    return manifest


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _optional_int(value: str | None) -> int | None:
    return int(value) if value not in {None, ""} else None


def read_pose_inventory(analysis_root: Path | str) -> list[PoseReviewRecord]:
    """Read every retained pose in stable pose-ID order."""
    analysis = Path(analysis_root).resolve()
    inventory = analysis / "pose_inventory.csv"
    poses = analysis / "all_poses.sdf"
    receptor = analysis / "receptor.pdb"
    missing = [path.name for path in (inventory, poses, receptor) if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            f"Expanded pose review is missing retained inputs: {', '.join(missing)}"
        )
    records = []
    try:
        with inventory.open(newline="") as handle:
            for row in csv.DictReader(handle):
                records.append(PoseReviewRecord(
                    pose_id=int(row["pose_id"]), cluster_id=int(row["cluster_id"]),
                    energy_kcal_per_mol=float(row["energy_kcal_per_mol"]),
                    seed=_optional_int(row.get("seed")), conformer=str(row.get("conformer") or ""),
                    model=_optional_int(row.get("model")),
                    selected_cluster=str(row.get("selected_cluster", "")).lower() == "yes",
                ))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"Invalid retained pose inventory: {exc}") from None
    if not records or len({record.pose_id for record in records}) != len(records):
        raise ValueError("Retained pose inventory is empty or contains duplicate pose IDs")
    return sorted(records, key=lambda record: record.pose_id)


def pose_cache_directory(analysis_root: Path | str, pose_id: int) -> Path:
    if pose_id < 1:
        raise ValueError("Pose ID must be positive")
    return Path(analysis_root).resolve() / "pose_interactions" / f"pose_{pose_id:04d}"


def _set_ligand_pdb_info(molecule) -> None:
    from collections import defaultdict
    from rdkit import Chem

    counters = defaultdict(int)
    for atom in molecule.GetAtoms():
        symbol = atom.GetSymbol().upper()
        counters[symbol] += 1
        info = Chem.AtomPDBResidueInfo()
        info.SetName(f"{symbol}{counters[symbol]}"[:4].rjust(4))
        info.SetResidueName("UNL")
        info.SetResidueNumber(1)
        info.SetChainId("Z")
        info.SetIsHeteroAtom(True)
        atom.SetMonomerInfo(info)


def _write_complex(receptor: Path, ligand_pdb: Path, output: Path) -> None:
    receptor_lines = [
        line for line in receptor.read_text(errors="replace").splitlines()
        if line.startswith(("ATOM  ", "HETATM", "TER"))
    ]
    max_serial = max((
        int(line[6:11]) for line in receptor_lines
        if line.startswith(("ATOM  ", "HETATM")) and line[6:11].strip().isdigit()
    ), default=0)
    ligand_source = ligand_pdb.read_text(errors="replace").splitlines()
    serial_map = {}
    for line in ligand_source:
        if line.startswith(("ATOM  ", "HETATM")) and line[6:11].strip().isdigit():
            serial_map[int(line[6:11])] = max_serial + len(serial_map) + 1
    ligand_lines = []
    for line in ligand_source:
        if line.startswith(("ATOM  ", "HETATM")):
            old = int(line[6:11])
            ligand_lines.append("HETATM" + f"{serial_map[old]:5d}" + line[11:])
        elif line.startswith("CONECT"):
            values = [
                int(line[index:index + 5]) for index in range(6, len(line), 5)
                if line[index:index + 5].strip().isdigit()
            ]
            mapped = [serial_map[value] for value in values if value in serial_map]
            if len(mapped) >= 2:
                ligand_lines.append("CONECT" + "".join(f"{value:5d}" for value in mapped))
    output.write_text("\n".join(receptor_lines + ligand_lines + ["END"]) + "\n")


def materialize_pose_interaction_inputs(
    analysis_root: Path | str, pose_id: int,
) -> tuple[PoseReviewRecord, Path]:
    """Write the exact selected pose and complex into its content-checked cache."""
    from rdkit import Chem

    analysis = Path(analysis_root).resolve()
    records = read_pose_inventory(analysis)
    record = next((item for item in records if item.pose_id == pose_id), None)
    if record is None:
        raise ValueError(f"Pose {pose_id} is not present in the retained pose inventory")
    pose_source = analysis / "all_poses.sdf"
    receptor = analysis / "receptor.pdb"
    cache = pose_cache_directory(analysis, pose_id)
    cache.mkdir(parents=True, exist_ok=True)
    provenance = {
        "schema_name": "docking-universal-pose-interaction-input",
        "schema_version": 1,
        "pose": record.to_dict(),
        "pose_source": str(pose_source), "pose_source_sha256": _sha256(pose_source),
        "receptor": str(receptor), "receptor_sha256": _sha256(receptor),
    }
    manifest = cache / "input_manifest.json"
    expected = (cache / "pose.sdf", cache / "pose.pdb", cache / "complex.pdb")
    if manifest.is_file() and all(path.is_file() for path in expected):
        try:
            if json.loads(manifest.read_text()) == provenance:
                return record, cache
        except (OSError, json.JSONDecodeError):
            pass
    molecules = list(Chem.SDMolSupplier(str(pose_source), removeHs=False))
    if pose_id > len(molecules) or molecules[pose_id - 1] is None:
        raise ValueError(f"Pose {pose_id} cannot be decoded from {pose_source}")
    molecule = Chem.Mol(molecules[pose_id - 1])
    molecule.SetProp("_Name", f"pose_{pose_id:04d}")
    writer = Chem.SDWriter(str(cache / "pose.sdf"))
    writer.write(molecule)
    writer.close()
    _set_ligand_pdb_info(molecule)
    Chem.MolToPDBFile(molecule, str(cache / "pose.pdb"))
    _write_complex(receptor, cache / "pose.pdb", cache / "complex.pdb")
    manifest.write_text(json.dumps(provenance, indent=2) + "\n")
    return record, cache
