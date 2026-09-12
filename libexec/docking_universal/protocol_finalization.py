"""Validated inputs and deterministic records for protocol finalization."""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from .state import StudyState


@dataclass(frozen=True)
class FinalizationOutputs:
    protocol: Path
    report: Path
    bundle: Path
    sha256: Mapping[str, str]


@dataclass(frozen=True)
class ProtocolRecordInputs:
    protocol_type: str
    target: str
    site_anchor: str
    evidence_basis: str
    created_utc: str
    engine: str
    software: Mapping[str, Any]
    region_definition: str
    fpocket_selection: str | None
    pocket_evidence: Mapping[str, Any]
    selected_residues: Sequence[str]
    engine_selection: Mapping[str, Any]
    parameters: Mapping[str, Any]
    receptor_pdbqt: Path
    receptor_pdb: Path
    regions: Sequence[Mapping[str, Any]]
    selectable_boxes: Sequence[Mapping[str, Any]]
    docking_box: Mapping[str, Any]
    receptor_preparation: Mapping[str, Any]
    receptor_preparation_summary: str
    cavity_score_threshold_used: float | None
    pocket_review_scene: str | None
    bundle_file_name: str


def build_protocol_record(inputs: ProtocolRecordInputs) -> dict[str, Any]:
    """Build the stable-v1 protocol mapping shared by CLI and GUI clients."""
    if not inputs.regions:
        raise ValueError("A protocol record requires at least one approved docking region")
    first = inputs.regions[0]
    return {
        "schema_name": "docking-universal-protocol",
        "schema_version": 1,
        "schema_status": "stable_v1",
        "protocol_type": inputs.protocol_type,
        "target": inputs.target,
        "site_anchor": inputs.site_anchor,
        "evidence_basis": inputs.evidence_basis,
        "screening_authority": "user-confirmed-exploratory-use",
        "created_utc": inputs.created_utc,
        "control_status": "not_performed",
        "unknown_docking_allowed": False,
        "exploratory_screening_allowed": True,
        "engine": inputs.engine,
        "software": dict(inputs.software),
        "region_definition": inputs.region_definition,
        "fpocket_selection": inputs.fpocket_selection,
        "pdb_pocket_evidence": dict(inputs.pocket_evidence),
        "selected_residues": list(inputs.selected_residues),
        "engine_selection": dict(inputs.engine_selection),
        "parameters": dict(inputs.parameters),
        "locked_inputs": {
            "receptor": str(inputs.receptor_pdbqt),
            "receptor_sha256": sha256(inputs.receptor_pdbqt),
            "receptor_pdb": str(inputs.receptor_pdb),
            "box": str(first["box"]),
            "box_sha256": first["box_sha256"],
            "boxes": list(inputs.regions),
        },
        "docking_regions": list(inputs.regions),
        "selectable_docking_boxes": list(inputs.selectable_boxes),
        "docking_box": dict(inputs.docking_box),
        "receptor_preparation": dict(inputs.receptor_preparation),
        "receptor_preparation_summary": inputs.receptor_preparation_summary,
        "cavity_score_threshold_used": inputs.cavity_score_threshold_used,
        "pocket_review_scene": inputs.pocket_review_scene,
        "bundle_file_name": inputs.bundle_file_name,
        "scientific_scope": {
            "purpose": "reusable exploratory site definition",
            "does_not_establish": [
                "pose-recovery validation", "binding affinity accuracy", "biological activity",
            ],
        },
    }


def build_site_guided_report_manifest(
    protocol: Mapping[str, Any],
    source_structure: Path | str,
    docking_universal_version: str,
    scientific_software: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the existing report manifest without changing report content."""
    return {
        "schema_name": "docking-universal-study",
        "schema_version": 1,
        "workflow": "exploratory",
        "study_name": (
            f"{protocol['target']}_{protocol['protocol_type']}_{protocol['engine']}_"
            f"{str(protocol['created_utc'])[:10]}"
        ),
        "study_status": "EXPLORATORY_NO_CONTROL",
        "completion_status": "COMPLETED",
        "created_utc": protocol["created_utc"],
        "target": protocol["target"],
        "target_source": str(source_structure),
        "compound_count": 0,
        "cavity_score_threshold_used": protocol.get("cavity_score_threshold_used"),
        "protocol_type": protocol["protocol_type"],
        "protocol_validation_status": (
            "Site-guided exploratory protocol; not evaluated by bound-ligand control"
        ),
        "region_definition": protocol["region_definition"],
        "fpocket_selection": protocol.get("fpocket_selection"),
        "pdb_pocket_evidence": protocol["pdb_pocket_evidence"],
        "engine_selection": protocol["engine_selection"],
        "configured_engine": protocol["engine"],
        "configured_engine_version": "recorded when screening runs",
        "bundle_file_name": protocol["bundle_file_name"],
        "configured_docking_parameters": protocol["parameters"],
        "configured_locked_inputs": protocol["locked_inputs"],
        "selected_docking_regions": protocol["docking_regions"],
        "selectable_docking_boxes": protocol["selectable_docking_boxes"],
        "docking_universal_version": docking_universal_version,
        "scientific_software": dict(scientific_software),
        "compounds": [],
    }


def write_protocol_record(path: Path | str, protocol: Mapping[str, Any]) -> Path:
    """Atomically write the stable protocol record used by reports and bundles."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(protocol, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        if temporary.exists():
            temporary.unlink()
    return destination


def publish_final_outputs(
    protocol_path: Path | str,
    protocol: Mapping[str, Any],
    report_path: Path | str,
    bundle_path: Path | str,
    bundle_root: Path | str,
    bundle_writer: Callable[[Path, Path, Path], Path],
) -> FinalizationOutputs:
    """Publish and verify the three required final protocol artifacts."""
    protocol_file = write_protocol_record(protocol_path, protocol)
    report_file = Path(report_path)
    if not report_file.is_file():
        raise FileNotFoundError(f"Final protocol report was not created: {report_file}")
    bundle_file = Path(bundle_writer(protocol_file, Path(bundle_root), Path(bundle_path)))
    if not bundle_file.is_file():
        raise FileNotFoundError(f"Final protocol bundle was not created: {bundle_file}")
    return FinalizationOutputs(
        protocol_file.resolve(), report_file.resolve(), bundle_file.resolve(),
        {
            "protocol": sha256(protocol_file),
            "report": sha256(report_file),
            "bundle": sha256(bundle_file),
        },
    )

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
