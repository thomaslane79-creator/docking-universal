"""Serialized, versioned application host for desktop and CLI clients."""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import IO, Any
from uuid import uuid4

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows packaging fallback
    fcntl = None

from .application import StudyController
from .models import JobStatus, PocketCandidate, record_to_dict, utc_now
from .orchestration import ProtocolWorkflowRunner
from .state import JsonStudyStore, RevisionConflictError
from .viewer.messages import Command, Response


class HostAlreadyRunning(RuntimeError):
    pass


class ApplicationHostLease:
    """Exclusive process lease; windows connect to one authoritative host."""

    def __init__(self, root: Path | str):
        self.path = Path(root) / ".application-host.lock"
        self.handle: IO[str] | None = None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+")
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                handle.close()
                raise HostAlreadyRunning("Another Docking Universal application host owns this workspace") from exc
        handle.seek(0)
        handle.truncate()
        handle.write(json.dumps({"pid": os.getpid(), "acquired_at": utc_now()}) + "\n")
        handle.flush()
        self.handle = handle

    def release(self) -> None:
        if self.handle is None:
            return
        if fcntl is not None:
            fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
        self.handle.close()
        self.handle = None

    def __enter__(self) -> "ApplicationHostLease":
        self.acquire()
        return self

    def __exit__(self, *_error: object) -> None:
        self.release()


class CommandDispatcher:
    """Apply a small command whitelist under one serialized mutation lock."""

    MUTATIONS = {
        "create_study", "start_pocket_review", "resolve_decision",
        "start_receptor_preparation", "start_protocol_finalization", "start_screening",
        "start_control_validation",
        "start_pose_interaction",
        "cancel_active_job",
    }

    def __init__(
        self,
        controller: StudyController,
        session_id: str | None = None,
        preparation_executable: Path | str | None = None,
    ):
        self.controller = controller
        self.session_id = session_id or f"session-{uuid4().hex}"
        self._lock = threading.RLock()
        self._responses: dict[str, Response] = {}
        self.workflow_runner = (
            ProtocolWorkflowRunner(controller, preparation_executable)
            if preparation_executable is not None else None
        )

    def dispatch(self, command: Command) -> Response:
        if command.session_id != self.session_id:
            return Response(command.request_id, "rejected", error="Stale or unknown application session")
        with self._lock:
            if command.request_id in self._responses:
                prior = self._responses[command.request_id]
                return Response(prior.request_id, "replayed", prior.revision, prior.result)
            try:
                response = self._apply(command)
            except (KeyError, ValueError, RuntimeError, FileNotFoundError) as exc:
                revision = self._revision_if_available(command.study_id)
                response = Response(command.request_id, "rejected", revision, error=str(exc))
            if command.operation in self.MUTATIONS and response.status == "applied":
                self._responses[command.request_id] = response
            return response

    def shutdown(self) -> None:
        if self.workflow_runner is not None:
            self.workflow_runner.shutdown()

    def _apply(self, command: Command) -> Response:
        if command.operation == "create_study":
            try:
                state = self.controller.get_study(command.study_id)
            except FileNotFoundError:
                state = self.controller.create_study(
                    command.study_id,
                    str(command.payload.get("name") or command.study_id),
                    str(command.payload.get("workflow") or "site_guided_protocol"),
                    request_id=command.request_id,
                )
            else:
                if state.workflow_data.get("creation_request_id") != command.request_id:
                    raise FileExistsError(f"Study already exists: {command.study_id}")
            return Response(command.request_id, "applied", state.revision, {"study": state.to_dict()})
        if command.operation == "snapshot":
            state = self.controller.get_study(command.study_id)
            return Response(command.request_id, "applied", state.revision, {"study": state.to_dict()})
        if command.operation == "screening_plan":
            if self.workflow_runner is None:
                raise RuntimeError("Screening is not configured in this application host")
            result = self.workflow_runner.screening_plan(
                command.study_id, Path(str(command.payload.get("ligand_source", ""))),
            )
            state = self.controller.get_study(command.study_id)
            return Response(command.request_id, "applied", state.revision, {"plan": result})
        if command.operation == "events_after":
            state = self.controller.get_study(command.study_id)
            cursor = int(command.payload.get("sequence", 0))
            events = [record_to_dict(event) for event in state.events if event.sequence > cursor]
            return Response(command.request_id, "applied", state.revision, {"events": events})
        if command.operation == "start_receptor_preparation":
            if command.expected_revision is None:
                raise RevisionConflictError("A state revision is required for scientific mutations")
            if self.workflow_runner is None:
                raise RuntimeError("Receptor preparation is not configured in this application host")
            result = self.workflow_runner.start_preparation(
                command.study_id, command.payload,
                request_id=command.request_id, expected_revision=command.expected_revision,
            )
            state = self.controller.get_study(command.study_id)
            return Response(command.request_id, "applied", state.revision, result)
        if command.operation == "start_control_validation":
            if command.expected_revision is None:
                raise RevisionConflictError("A state revision is required for scientific mutations")
            if self.workflow_runner is None:
                raise RuntimeError("Known-ligand control is not configured in this application host")
            result = self.workflow_runner.start_control_validation(
                command.study_id, command.payload,
                request_id=command.request_id, expected_revision=command.expected_revision,
            )
            state = self.controller.get_study(command.study_id)
            return Response(command.request_id, "applied", state.revision, result)
        if command.operation == "start_protocol_finalization":
            if command.expected_revision is None:
                raise RevisionConflictError("A state revision is required for scientific mutations")
            if self.workflow_runner is None:
                raise RuntimeError("Protocol finalization is not configured in this application host")
            result = self.workflow_runner.start_finalization(
                command.study_id, command.payload,
                request_id=command.request_id, expected_revision=command.expected_revision,
            )
            state = self.controller.get_study(command.study_id)
            return Response(command.request_id, "applied", state.revision, result)
        if command.operation == "start_screening":
            if command.expected_revision is None:
                raise RevisionConflictError("A state revision is required for scientific mutations")
            if self.workflow_runner is None:
                raise RuntimeError("Screening is not configured in this application host")
            result = self.workflow_runner.start_screening(
                command.study_id, command.payload,
                request_id=command.request_id, expected_revision=command.expected_revision,
            )
            state = self.controller.get_study(command.study_id)
            return Response(command.request_id, "applied", state.revision, result)
        if command.operation == "start_pose_interaction":
            if command.expected_revision is None:
                raise RevisionConflictError("A state revision is required for scientific mutations")
            if self.workflow_runner is None:
                raise RuntimeError("Pose interaction analysis is not configured in this application host")
            result = self.workflow_runner.start_pose_interaction(
                command.study_id, command.payload, request_id=command.request_id,
                expected_revision=command.expected_revision,
            )
            state = self.controller.get_study(command.study_id)
            return Response(command.request_id, "applied", state.revision, result)
        if command.operation == "cancel_active_job":
            if command.expected_revision is None:
                raise RevisionConflictError("A state revision is required to cancel scientific work")
            state = self.controller.get_study(command.study_id)
            job_id = str(command.payload.get("job_id") or "")
            if job_id and (state.active_job is None or state.active_job.id != job_id):
                raise ValueError("The scientific job changed before cancellation; refresh the study")
            if not job_id and state.revision != command.expected_revision:
                raise RevisionConflictError(
                    f"Study {command.study_id} changed from revision {command.expected_revision} to {state.revision}"
                )
            if self.workflow_runner is None or not self.workflow_runner.cancel(command.study_id):
                raise RuntimeError("No cancellable scientific job is active for this study")
            return Response(command.request_id, "applied", state.revision, {"cancellation_requested": True})
        if command.operation == "start_pocket_review":
            if command.expected_revision is None:
                raise RevisionConflictError("A state revision is required for scientific mutations")
            raw_candidates = command.payload.get("candidates")
            if not isinstance(raw_candidates, list):
                raise ValueError("Pocket candidates must be a list")
            candidates = [PocketCandidate(**item) for item in raw_candidates]
            self._assert_no_other_active_study(command.study_id)
            decision = self.controller.start_pocket_review(
                command.study_id,
                candidates,
                request_id=command.request_id,
                expected_revision=command.expected_revision,
            )
            state = self.controller.get_study(command.study_id)
            return Response(command.request_id, "applied", state.revision, {"decision": record_to_dict(decision)})
        if command.operation == "resolve_decision":
            if command.expected_revision is None:
                raise RevisionConflictError("A state revision is required for scientific mutations")
            selections = command.payload.get("selections")
            if not isinstance(selections, list):
                raise ValueError("Decision selections must be a list")
            decision_id = str(command.payload.get("decision_id", ""))
            decision = self.controller.get_decision(command.study_id, decision_id)
            approval = self.controller.resolve_decision(
                command.study_id,
                decision_id,
                tuple(map(str, selections)),
                actor=str(command.payload.get("actor") or "desktop-user"),
                rationale=command.payload.get("rationale"),
                policy_id=command.payload.get("policy_id"),
                request_id=command.request_id,
                expected_revision=command.expected_revision,
            )
            continuation = None
            if self.workflow_runner is not None:
                continuation = self.workflow_runner.resume_after_decision(
                    command.study_id, decision, approval,
                )
            state = self.controller.get_study(command.study_id)
            result = {"approval": record_to_dict(approval)}
            if continuation is not None:
                result["continuation"] = continuation
            return Response(command.request_id, "applied", state.revision, result)
        raise ValueError(f"Unsupported application-host operation: {command.operation}")

    def _assert_no_other_active_study(self, requested_study_id: str) -> None:
        for path in self.controller.store.root.glob("*/application_state.json"):
            state = self.controller.store.load(path.parent.name)
            if state.study_id != requested_study_id and state.active_job:
                raise RuntimeError(
                    f"Study {state.study_id} already owns the active scientific stage: {state.active_job.stage}"
                )

    def _revision_if_available(self, study_id: str) -> int | None:
        try:
            return self.controller.get_study(study_id).revision
        except (FileNotFoundError, ValueError):
            return None


def reconcile_interrupted_jobs(store: JsonStudyStore) -> int:
    """Mark work left running by a previous host as interrupted, never successful."""
    changed = 0
    for path in sorted(store.root.glob("*/application_state.json")):
        study_id = path.parent.name

        def mutation(state):
            nonlocal changed
            running = [job for job in state.jobs if job.status is JobStatus.RUNNING]
            for job in running:
                job.status = JobStatus.INTERRUPTED
                job.finished_at = utc_now()
                job.error = "Application host restarted while this stage was running"
                changed += 1
            if running:
                from .models import CompletionStatus
                state.completion_status = CompletionStatus.INTERRUPTED
                state.current_stage = None

        state = store.load(study_id)
        if any(job.status is JobStatus.RUNNING for job in state.jobs):
            store.update(study_id, mutation)
    return changed


def serve_json_lines(dispatcher: CommandDispatcher, input_stream: IO[str], output_stream: IO[str]) -> None:
    """Reserve stdout for one JSON response per input command."""
    for line in input_stream:
        try:
            if len(line.encode("utf-8")) > 1_000_000:
                raise ValueError("Application-host command exceeds the 1 MB limit")
            command = Command.from_dict(json.loads(line))
            response = dispatcher.dispatch(command)
        except Exception as exc:
            response = Response("invalid-request", "error", error=str(exc))
        output_stream.write(json.dumps(response.to_dict(), sort_keys=True) + "\n")
        output_stream.flush()
