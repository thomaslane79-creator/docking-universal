"""Atomic JSON persistence for a single scientific study run."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterator, TypeVar

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows packaging fallback
    fcntl = None

from .decisions import ApprovalRecord, DecisionOption, DecisionRequired, DecisionStatus
from .events import EventType, WorkflowEvent
from .models import ArtifactRecord, CompletionStatus, Job, JobStatus, ScientificAuthority, record_to_dict, utc_now


SCHEMA_NAME = "docking-universal-application-state"
SCHEMA_VERSION = 3
T = TypeVar("T")


class RevisionConflictError(RuntimeError):
    """A client attempted to mutate a stale scientific-state revision."""


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
    revision: int = 0
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    @property
    def pending_decisions(self) -> list[DecisionRequired]:
        return [decision for decision in self.decisions if decision.status is DecisionStatus.PENDING]

    @property
    def active_job(self) -> Job | None:
        active = {JobStatus.QUEUED, JobStatus.RUNNING, JobStatus.WAITING_FOR_DECISION}
        return next((job for job in self.jobs if job.status in active), None)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_name": SCHEMA_NAME,
            "schema_version": SCHEMA_VERSION,
            **record_to_dict(self),
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StudyState":
        if value.get("schema_name") != SCHEMA_NAME or value.get("schema_version") not in {1, 2, SCHEMA_VERSION}:
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
            revision=int(value.get("revision", 0)),
            created_at=value["created_at"],
            updated_at=value["updated_at"],
        )


class JsonStudyStore:
    """Persist each study independently so every window sees the same run."""

    _registry_guard = threading.Lock()
    _thread_locks: dict[str, threading.RLock] = {}

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, study_id: str) -> Path:
        if not study_id or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for character in study_id):
            raise ValueError("Study IDs may contain only letters, digits, '.', '_', and '-'")
        return self.root / study_id / "application_state.json"

    def create(self, state: StudyState) -> StudyState:
        path = self.path_for(state.study_id)
        with self._lock(state.study_id):
            if path.exists():
                raise FileExistsError(f"Study already exists: {state.study_id}")
            state.revision = 1
            self._write_unlocked(state)
        return state

    def load(self, study_id: str) -> StudyState:
        return StudyState.from_dict(json.loads(self.path_for(study_id).read_text()))

    def list_studies(self) -> list[StudyState]:
        """Return valid studies newest-first, ignoring unrelated directories."""
        studies = []
        if not self.root.is_dir():
            return studies
        for path in self.root.glob("*/application_state.json"):
            try:
                state = StudyState.from_dict(json.loads(path.read_text()))
                if state.workflow_data.get("removed_from_library_at"):
                    continue
                studies.append(state)
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                continue
        return sorted(studies, key=lambda item: item.updated_at, reverse=True)

    def remove_from_library(self, study_id: str) -> StudyState:
        """Hide a retained study from the active desktop library.

        Scientific outputs often live outside the application-state directory.
        Removing a study from the library must never silently delete those
        reports, protocol bundles, or docking results.  The retained state is
        therefore marked as removed instead of being unlinked, which also
        leaves a recoverable audit record on disk.
        """
        from .models import utc_now

        state, _result = self.update(
            study_id,
            lambda value: value.workflow_data.update({
                "removed_from_library_at": utc_now(),
                "removed_from_library_policy": "external_scientific_outputs_preserved",
            }),
        )
        return state

    def save(self, state: StudyState, *, expected_revision: int | None = None) -> None:
        """Save one loaded state using optimistic revision validation."""
        with self._lock(state.study_id):
            path = self.path_for(state.study_id)
            current_revision = self._read_revision(path) if path.exists() else 0
            expected = state.revision if expected_revision is None else expected_revision
            if current_revision != expected:
                raise RevisionConflictError(
                    f"Study {state.study_id} changed from revision {expected} to {current_revision}"
                )
            state.revision = current_revision + 1
            self._write_unlocked(state)

    def update(
        self,
        study_id: str,
        mutation: Callable[[StudyState], T],
        *,
        expected_revision: int | None = None,
    ) -> tuple[StudyState, T]:
        """Atomically load, validate, mutate, and replace a study record."""
        with self._lock(study_id):
            state = self.load(study_id)
            if expected_revision is not None and state.revision != expected_revision:
                raise RevisionConflictError(
                    f"Study {study_id} changed from revision {expected_revision} to {state.revision}"
                )
            result = mutation(state)
            state.revision += 1
            self._write_unlocked(state)
            return state, result

    @contextmanager
    def _lock(self, study_id: str) -> Iterator[None]:
        path = self.path_for(study_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        key = str(path.parent.resolve())
        with self._registry_guard:
            thread_lock = self._thread_locks.setdefault(key, threading.RLock())
        with thread_lock:
            lock_path = path.parent / ".application_state.lock"
            with lock_path.open("a+") as handle:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _read_revision(path: Path) -> int:
        value = json.loads(path.read_text())
        return int(value.get("revision", 0))

    def _write_unlocked(self, state: StudyState) -> None:
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
