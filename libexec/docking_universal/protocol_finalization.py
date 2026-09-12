"""Validated inputs and deterministic records for protocol finalization."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .state import StudyState

def sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _box_values(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(errors="replace").splitlines():
        if "=" in line:
            key, value = (item.strip() for item in line.split("=", 1))
            values[key] = value
    return values


@dataclass(frozen=True)
class FinalizationSettings:
    engine: str = "vina"
    ph: float = 7.4
    conformers: int = 3
    seed_count: int = 5
    base_seed: int = 20260808
    exhaustiveness: int = 16
    num_modes: int = 15
    energy_range: float = 8.0

    def validate(self) -> None:
        if self.engine not in {"vina", "qvinaw"}:
            raise ValueError("Protocol engine must be vina or qvinaw")
        if not all(math.isfinite(value) for value in (self.ph, self.energy_range)):
            raise ValueError("Protocol numeric settings must be finite")
        if not 0 < self.ph <= 14:
            raise ValueError("Protocol pH must be greater than zero and at most 14")
        if min(self.conformers, self.seed_count, self.exhaustiveness, self.num_modes) < 1:
            raise ValueError("Conformers, seeds, exhaustiveness, and modes must be positive")
        if self.energy_range <= 0:
            raise ValueError("Energy range must be positive")

    def protocol_parameters(self) -> dict[str, Any]:
        self.validate()
        return {
            "ph": self.ph,
            "conformers_per_state": self.conformers,
            "ensemble_seed": self.base_seed,
            "forcefield": "mmff94",
            "rmsd_prune_angstrom": 0.75,
            "tautomers_enumerated": True,
            "charge_model": "gasteiger",
            "macrocycle_treatment": (
                "flexible_meeko" if self.engine == "vina" else "rigid_conformer_ensemble"
            ),
            "exhaustiveness": self.exhaustiveness,
            "num_modes": self.num_modes,
            "energy_range_kcal_per_mol": self.energy_range,
            "seeds": [self.base_seed + index for index in range(self.seed_count)],
        }


def selected_region_records(
    selected_boxes: Sequence[Path | str],
    candidates: Sequence[Mapping[str, Any]],
    *,
    automatic: bool = False,
    fallback_origin: str = "fpocket-or-user-selection",
) -> list[dict[str, Any]]:
    """Create ordered locked-region records from already selected box files."""
    labels = {
        str(Path(candidate["path"]).resolve()): str(candidate["label"])
        for candidate in candidates
    }
    records = []
    for index, value in enumerate(selected_boxes, 1):
        path = Path(value).resolve()
        if not path.is_file():
            raise FileNotFoundError(f"Approved docking box does not exist: {path}")
        known = str(path) in labels
        records.append({
            "site_number": index,
            "box_label": labels.get(str(path), f"Site {index}"),
            "box": str(path),
            "box_sha256": sha256(path),
            "box_name": path.name,
            "geometry": {
                key: _box_values(path).get(key, "not recorded")
                for key in ("center_x", "center_y", "center_z", "size_x", "size_y", "size_z")
            },
            "definition_origin": (
                "automatic top-ranked fpocket selection" if automatic and known
                else "user-selected labeled candidate" if known
                else fallback_origin
            ),
        })
    if not records:
        raise ValueError("Protocol finalization requires at least one approved docking region")
    return records


@dataclass(frozen=True)
class ProtocolFinalizationRequest:
    study_id: str
    target: str
    preparation_root: Path
    source_structure: Path
    receptor_pdb: Path
    receptor_pdbqt: Path
    regions: tuple[Mapping[str, Any], ...]
    settings: FinalizationSettings
    approval_id: str
    evidence_revision: int
    output_directory: Path
    exploratory_use_approved: bool

    def validate(self) -> None:
        self.settings.validate()
        if not self.approval_id or self.evidence_revision < 1:
            raise ValueError("Finalization requires a persisted approval and evidence revision")
        if not self.exploratory_use_approved:
            raise ValueError("Reusable exploratory protocol creation requires explicit approval")
        if not self.preparation_root.is_dir():
            raise FileNotFoundError(f"Preparation root does not exist: {self.preparation_root}")
        for path in (self.source_structure, self.receptor_pdb, self.receptor_pdbqt):
            if not path.is_file():
                raise FileNotFoundError(f"Required finalization input does not exist: {path}")
        if not self.regions:
            raise ValueError("Finalization requires at least one approved region")
        for region in self.regions:
            path = Path(str(region.get("box", "")))
            if not path.is_file() or sha256(path) != region.get("box_sha256"):
                raise ValueError(f"Approved docking region changed or is missing: {path}")
            geometry = region.get("geometry") or {}
            try:
                centers = [float(geometry[f"center_{axis}"]) for axis in "xyz"]
                sizes = [float(geometry[f"size_{axis}"]) for axis in "xyz"]
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Approved docking region has incomplete geometry: {path}") from exc
            if not all(math.isfinite(value) for value in centers + sizes) or min(sizes) <= 0:
                raise ValueError(f"Approved docking region has invalid geometry: {path}")


def request_from_study(
    state: StudyState,
    settings: FinalizationSettings,
    output_directory: Path | str,
    *,
    exploratory_use_approved: bool,
) -> ProtocolFinalizationRequest:
    """Build a finalization request only from persisted approved study state."""
    decisions = {decision.id: decision for decision in state.decisions}
    approval = next((
        item for item in reversed(state.approvals)
        if decisions.get(item.decision_id) and decisions[item.decision_id].kind == "select_pockets"
    ), None)
    if approval is None:
        raise ValueError("Protocol finalization requires an approved pocket decision")
    artifacts = {artifact.id: artifact for artifact in state.artifacts}
    candidates = {item["id"]: item for item in state.workflow_data.get("pocket_candidates", [])}
    selected = []
    labels = []
    for candidate_id in state.selected_pocket_ids:
        candidate = candidates.get(candidate_id)
        if not candidate or candidate.get("box_artifact_id") not in artifacts:
            raise ValueError(f"Approved pocket has no registered docking box: {candidate_id}")
        artifact = artifacts[candidate["box_artifact_id"]]
        selected.append(Path(artifact.path))
        labels.append({"label": candidate.get("label", candidate_id), "path": artifact.path})
    regions = selected_region_records(selected, labels)
    approved_hashes = {
        item.get("id"): item.get("sha256") for item in approval.evidence.get("artifacts", [])
    }
    for candidate_id, region in zip(state.selected_pocket_ids, regions):
        artifact_id = candidates[candidate_id]["box_artifact_id"]
        if approved_hashes.get(artifact_id) != region["box_sha256"]:
            raise ValueError(f"Approved evidence hash is missing or changed for {candidate_id}")

    def artifact_path(kind: str) -> Path:
        record = next((item for item in state.artifacts if item.kind == kind), None)
        if record is None:
            raise ValueError(f"Study has no registered {kind} artifact")
        path = Path(record.path)
        if not path.is_file() or (record.sha256 and sha256(path) != record.sha256):
            raise ValueError(f"Registered {kind} artifact changed or is missing")
        return path

    preparation_root = state.workflow_data.get("preparation_root")
    if not preparation_root:
        raise ValueError("Study has no registered preparation root")
    request = ProtocolFinalizationRequest(
        study_id=state.study_id,
        target=Path(artifact_path("prepared_receptor_structure")).stem,
        preparation_root=Path(str(preparation_root)),
        source_structure=artifact_path("source_receptor_structure"),
        receptor_pdb=artifact_path("prepared_receptor_structure"),
        receptor_pdbqt=artifact_path("prepared_receptor"),
        regions=tuple(regions), settings=settings, approval_id=approval.id,
        evidence_revision=int(approval.evidence.get("study_revision", 0)),
        output_directory=Path(output_directory),
        exploratory_use_approved=exploratory_use_approved,
    )
    request.validate()
    return request
