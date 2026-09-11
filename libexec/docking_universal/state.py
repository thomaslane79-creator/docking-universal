"""Atomic JSON persistence for a single scientific study run."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .decisions import ApprovalRecord, DecisionOption, DecisionRequired, DecisionStatus
from .events import EventType, WorkflowEvent
from .models import ArtifactRecord, CompletionStatus, Job, JobStatus, ScientificAuthority, record_to_dict, utc_now


SCHEMA_NAME = "docking-universal-application-state"
SCHEMA_VERSION = 1


@dataclass
class StudyState:
    study_id: str
    name: str
    workflow: str
    completion_status: CompletionStatus = CompletionStatus.DRAFT
    scientific_authority: ScientificAuthority = ScientificAuthority.NOT_ESTABLISHED
    current_stage: str | None = None
    selected_pocket_ids: list[str] = field(default_factory=list)
    decisions: list[DecisionRequired] = field(default_factory=list)
    approvals: list[ApprovalRecord] = field(default_factory=list)
    jobs: list[Job] = field(default_factory=list)
    artifacts: list[ArtifactRecord] = field(default_factory=list)
    events: list[WorkflowEvent] = field(default_factory=list)
    workflow_data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @property
    def pending_decisions(self) -> list[DecisionRequired]:
        return [decision for decision in self.decisions if decision.status is DecisionStatus.PENDING]

    @property
    def active_job(self) -> Job | None:
        active = {JobStatus.RUNNING, JobStatus.WAITING_FOR_DECISION}
        return next((job for job in self.jobs if job.status in active), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            **record_to_dict(self),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StudyState":
        if value.get("schema_name") != SCHEMA_NAME or value.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("Unsupported Docking Universal application-state schema")
        decisions = []
        for item in value.get("decisions", []):
            item = dict(item)
            item["options"] = tuple(DecisionOption(**option) for option in item.get("options", []))
            item["consequences"] = tuple(item.get("consequences", []))
            item["artifact_ids"] = tuple(item.get("artifact_ids", []))
            item["status"] = DecisionStatus(item["status"])
            decisions.append(DecisionRequired(**item))
        approvals = []
        for item in value.get("approvals", []):
            item = dict(item)
            item["selections"] = tuple(item.get("selections", []))
            approvals.append(ApprovalRecord(**item))
        jobs = [Job(**{**item, "status": JobStatus(item["status"])}) for item in value.get("jobs", [])]
        artifacts = [ArtifactRecord(**item) for item in value.get("artifacts", [])]
        events = [
            WorkflowEvent(**{**item, "type": EventType(item["type"])})
            for item in value.get("events", [])
        ]
        return cls(
            study_id=value["study_id"],
            name=value["name"],
            workflow=value["workflow"],
            completion_status=CompletionStatus(value["completion_status"]),
            scientific_authority=ScientificAuthority(value["scientific_authority"]),
            current_stage=value.get("current_stage"),
            selected_pocket_ids=list(value.get("selected_pocket_ids", [])),
            decisions=decisions,
            approvals=approvals,
            jobs=jobs,
            artifacts=artifacts,
            events=events,
            workflow_data=dict(value.get("workflow_data", {})),
            created_at=value["created_at"],
            updated_at=value["updated_at"],
        )


class JsonStudyStore:
    """Persist each study independently so every window sees the same run."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, study_id: str) -> Path:
        if not study_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in study_id):
            raise ValueError("Study IDs may contain only letters, digits, '.', '_', and '-'")
        return self.root / study_id / "application_state.json"

    def create(self, state: StudyState) -> StudyState:
        path = self.path_for(state.study_id)
        if path.exists():
            raise FileExistsError(f"Study already exists: {state.study_id}")
        self.save(state)
        return state

    def load(self, study_id: str) -> StudyState:
        return StudyState.from_dict(json.loads(self.path_for(study_id).read_text()))

    def save(self, state: StudyState) -> None:
        path = self.path_for(state.study_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        state.updated_at = utc_now()
        descriptor, temporary_name = tempfile.mkstemp(prefix=".application_state.", suffix=".tmp", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w") as handle:
                json.dump(state.to_dict(), handle, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()
