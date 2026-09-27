"""Shared in-process session for every window presenting one scientific study."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from weakref import WeakValueDictionary

from ..models import ArtifactRecord
from ..state import JsonStudyStore, StudyState

try:
    from .qt import QtCore
except ImportError as exc:  # pragma: no cover - reported by the runtime inventory
    QtCore = None
    QT_IMPORT_ERROR = exc
else:
    QT_IMPORT_ERROR = None


@dataclass(frozen=True)
class StudySelection:
    """Recoverable presentation selection; never a scientific approval."""

    compound: str | None = None
    analysis_root: str | None = None
    site: str | None = None
    cluster_id: int | None = None
    pose_id: int | None = None


@dataclass(frozen=True)
class ViewerState:
    connected: bool = False
    report_view_available: bool = False
    detail: str | None = None
    lifecycle: str = "disconnected"
    error: str | None = None


@dataclass(frozen=True)
class OperationState:
    job_id: str | None = None
    stage: str | None = None
    status: str | None = None


if QtCore is not None:
    class ActiveStudySession(QtCore.QObject):
        """One observable GUI session over the host-owned persisted study.

        The session owns cross-window presentation state only. It reads the
        authoritative :class:`StudyState` but never writes scientific state;
        mutations continue to pass through the application host.
        """

        studyChanged = QtCore.pyqtSignal(object)
        artifactsChanged = QtCore.pyqtSignal(object)
        selectionChanged = QtCore.pyqtSignal(object)
        viewerChanged = QtCore.pyqtSignal(object)
        operationChanged = QtCore.pyqtSignal(object)
        detailChanged = QtCore.pyqtSignal(str)

        _shared: WeakValueDictionary = WeakValueDictionary()

        def __init__(self, store: JsonStudyStore, study_id: str, parent=None):
            super().__init__(parent)
            self.store = store
            self.study_id = study_id
            self.state: StudyState = store.load(study_id)
            self.selection = StudySelection()
            self.viewer = ViewerState()
            self.detail_level = "guided"
            self.operation = self._operation_from_state(self.state)
            self._artifact_signature = self._artifacts_signature(self.state.artifacts)

        @classmethod
        def shared(cls, store: JsonStudyStore, study_id: str) -> "ActiveStudySession":
            key = (str(store.root.resolve()), str(study_id))
            session = cls._shared.get(key)
            if session is None:
                session = cls(store, study_id)
                cls._shared[key] = session
            return session

        @staticmethod
        def _artifacts_signature(artifacts: Iterable[ArtifactRecord]) -> tuple:
            return tuple((item.id, item.kind, item.path, item.sha256) for item in artifacts)

        @staticmethod
        def _operation_from_state(state: StudyState) -> OperationState:
            job = state.active_job
            if job is None:
                return OperationState()
            return OperationState(job.id, job.stage, job.status.value)

        def refresh(self) -> bool:
            """Load a newer authoritative revision and notify every observer."""
            latest = self.store.load(self.study_id)
            if latest.revision == self.state.revision:
                return False
            old_artifacts = self._artifact_signature
            old_operation = self.operation
            self.state = latest
            self._artifact_signature = self._artifacts_signature(latest.artifacts)
            self.operation = self._operation_from_state(latest)
            self.studyChanged.emit(latest)
            if self._artifact_signature != old_artifacts:
                self.artifactsChanged.emit(tuple(latest.artifacts))
            if self.operation != old_operation:
                self.operationChanged.emit(self.operation)
            return True

        def artifacts(self, kind: str | None = None, *, existing_only: bool = False) -> tuple[ArtifactRecord, ...]:
            values = self.state.artifacts
            if kind is not None:
                values = [item for item in values if item.kind == kind]
            if existing_only:
                values = [item for item in values if Path(item.path).is_file()]
            return tuple(values)

        def select_compound(self, compound: Path | str | None) -> None:
            value = str(Path(compound).resolve()) if compound is not None else None
            self._set_selection(StudySelection(compound=value))

        def select_cluster(
            self, compound: Path | str, analysis_root: Path | str,
            cluster_id: int, *, site: str | None = None,
        ) -> None:
            if int(cluster_id) < 1:
                raise ValueError("Cluster identifiers must be positive")
            self._set_selection(StudySelection(
                compound=str(Path(compound).resolve()),
                analysis_root=str(Path(analysis_root).resolve()),
                site=site, cluster_id=int(cluster_id),
            ))

        def select_pose(
            self, compound: Path | str, analysis_root: Path | str,
            cluster_id: int, pose_id: int, *, site: str | None = None,
        ) -> None:
            if int(pose_id) < 1:
                raise ValueError("Pose identifiers must be positive")
            if int(cluster_id) < 1:
                raise ValueError("Cluster identifiers must be positive")
            self._set_selection(StudySelection(
                compound=str(Path(compound).resolve()),
                analysis_root=str(Path(analysis_root).resolve()),
                site=site, cluster_id=int(cluster_id), pose_id=int(pose_id),
            ))

        def clear_selection(self) -> None:
            self._set_selection(StudySelection())

        def set_detail_level(self, value: str) -> None:
            detail = str(value).strip().lower()
            if detail not in {"concise", "guided", "teaching", "technical"}:
                raise ValueError(f"Unknown scientific detail level: {value}")
            if detail != self.detail_level:
                self.detail_level = detail
                self.detailChanged.emit(detail)

        def set_viewer_state(
            self, *, connected: bool, report_view_available: bool = False,
            detail: str | None = None, lifecycle: str | None = None,
            error: str | None = None,
        ) -> None:
            phase = lifecycle or ("connected" if connected else "disconnected")
            if phase not in {"disconnected", "connecting", "connected", "failed"}:
                raise ValueError(f"Unknown viewer lifecycle state: {phase}")
            value = ViewerState(
                bool(connected), bool(report_view_available), detail, phase, error,
            )
            if value != self.viewer:
                self.viewer = value
                self.viewerChanged.emit(value)

        def _set_selection(self, value: StudySelection) -> None:
            if value != self.selection:
                self.selection = value
                self.selectionChanged.emit(value)
else:
    class ActiveStudySession:  # pragma: no cover
        def __init__(self, *_args, **_kwargs):
            raise RuntimeError(f"The selected PyQt6 runtime is unavailable: {QT_IMPORT_ERROR}")
