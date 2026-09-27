"""Serializable domain records shared by terminal and graphical clients."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CompletionStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    WAITING_FOR_DECISION = "waiting_for_decision"
    COMPLETED = "completed"
    COMPLETED_WITH_WARNINGS = "completed_with_warnings"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ScientificAuthority(str, Enum):
    NOT_ESTABLISHED = "not_established"
    EXPLORATORY_NO_CONTROL = "exploratory_no_control"
    CONTROL_APPROVED = "control_approved"


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_FOR_DECISION = "waiting_for_decision"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True)
class ArtifactRecord:
    id: str
    kind: str
    path: str
    sha256: str | None = None
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ReceptorComponent:
    artifact_id: str
    role: str


@dataclass(frozen=True)
class FlexibleResidueSelection:
    """Future-capable identity; evidence contents remain external artifacts."""

    chain_id: str
    residue_name: str
    residue_number: int
    insertion_code: str = ""
    evidence_artifact_id: str | None = None
    rationale: str | None = None


@dataclass(frozen=True)
class ReceptorConfiguration:
    rigid_component: ReceptorComponent
    flexible_component: ReceptorComponent | None = None
    flexible_residues: tuple[FlexibleResidueSelection, ...] = ()

    @property
    def flexibility_mode(self) -> str:
        return "selected_side_chains" if self.flexible_component else "rigid"

    def validate(self) -> None:
        if self.rigid_component.role != "rigid_receptor":
            raise ValueError("The required receptor component must have role 'rigid_receptor'")
        if (self.flexible_component is None) != (not self.flexible_residues):
            raise ValueError("A flexible component and selected residue records must be supplied together")
        if self.flexible_component and self.flexible_component.role != "flexible_receptor":
            raise ValueError("The optional receptor component must have role 'flexible_receptor'")


@dataclass(frozen=True)
class EngineCapabilities:
    engine: str
    version: str
    supports_selected_side_chains: bool = False
    supports_cpu_limit: bool = False
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DockingRequest:
    receptor: ReceptorConfiguration
    ligand_artifact_ids: tuple[str, ...]
    region_artifact_id: str
    engine: EngineCapabilities
    parameters: dict[str, Any] = field(default_factory=dict)

    def validate(self) -> None:
        self.receptor.validate()
        if self.receptor.flexible_component and not self.engine.supports_selected_side_chains:
            raise ValueError(f"{self.engine.engine} has not declared selected-side-chain support")
        if not self.ligand_artifact_ids:
            raise ValueError("At least one ligand artifact is required")


@dataclass(frozen=True)
class PocketCandidate:
    id: str
    label: str
    rank: int
    box_artifact_id: str
    summary: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Job:
    id: str
    stage: str
    status: JobStatus = JobStatus.QUEUED
    started_at: str | None = None
    finished_at: str | None = None
    progress: float = 0.0
    error: str | None = None
    request_id: str | None = None
    process_id: int | None = None
    progress_phase: str | None = None
    progress_message: str | None = None
    progress_completed: int | None = None
    progress_total: int | None = None


def record_to_dict(record: Any) -> dict[str, Any]:
    """Return a JSON-ready dataclass mapping, converting nested enums."""

    def normalize(value: Any) -> Any:
        if isinstance(value, Enum):
            return value.value
        if isinstance(value, tuple):
            return [normalize(item) for item in value]
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    return normalize(asdict(record))
