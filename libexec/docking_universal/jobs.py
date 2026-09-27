"""Persisted job orchestration built on the cancellable process adapter."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

from .application import ActiveStageError, StudyController
from .events import EventType
from .models import ArtifactRecord, CompletionStatus, Job, JobStatus, utc_now
from .processes import ProcessExecutionError, ProcessOutput, ProcessRequest, ProcessResult, ProcessRunner, ProcessStatus
from .workflow import record_stage_completion


class JobService:
    """Run one scientific stage while leaving a durable state trail."""

    def __init__(self, controller: StudyController, runner: ProcessRunner | None = None):
        self.controller = controller
        self.runner = runner or ProcessRunner()

    def run(
        self,
        study_id: str,
        stage: str,
        request: ProcessRequest,
        *,
        cancel_event: threading.Event | None = None,
        on_output: Callable[[ProcessOutput], None] | None = None,
        progress_probe: Callable[[], tuple[str, str, int | None, int | None]] | None = None,
        intervention_probe: Callable[[], object | None] | None = None,
        required_outputs: tuple[Path | str, ...] = (),
        request_id: str | None = None,
        expected_revision: int | None = None,
    ) -> ProcessResult:
        with _ScientificJobLease(self.controller.store):
            return self._run_owned(
                study_id, stage, request, cancel_event=cancel_event,
                on_output=on_output, progress_probe=progress_probe, required_outputs=required_outputs,
                intervention_probe=intervention_probe, request_id=request_id,
                expected_revision=expected_revision, existing_job_id=None,
            )

    def resume(
        self,
        study_id: str,
        job_id: str,
        request: ProcessRequest,
        *,
        cancel_event: threading.Event | None = None,
        on_output: Callable[[ProcessOutput], None] | None = None,
        progress_probe: Callable[[], tuple[str, str, int | None, int | None]] | None = None,
        intervention_probe: Callable[[], object | None] | None = None,
        required_outputs: tuple[Path | str, ...] = (),
    ) -> ProcessResult:
        """Resume the exact queued stage after a persisted scientific decision."""

        with _ScientificJobLease(self.controller.store, allowed_active=(study_id, job_id)):
            return self._run_owned(
                study_id, "", request, cancel_event=cancel_event,
                on_output=on_output, progress_probe=progress_probe,
                intervention_probe=intervention_probe, required_outputs=required_outputs,
                request_id=None, expected_revision=None, existing_job_id=job_id,
            )

    def _run_owned(
        self,
        study_id: str,
        stage: str,
        request: ProcessRequest,
        *,
        cancel_event: threading.Event | None,
        on_output: Callable[[ProcessOutput], None] | None,
        progress_probe: Callable[[], tuple[str, str, int | None, int | None]] | None,
        intervention_probe: Callable[[], object | None] | None,
        required_outputs: tuple[Path | str, ...],
        request_id: str | None,
        expected_revision: int | None,
        existing_job_id: str | None,
    ) -> ProcessResult:
        state = self.controller.get_study(study_id)
        if request_id and existing_job_id is None:
            prior = next((item for item in state.jobs if item.request_id == request_id), None)
            if prior is not None:
                raise ActiveStageError(f"Scientific job request was already recorded: {request_id}")
        if expected_revision is not None and state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError(
                f"Study {study_id} changed from revision {expected_revision} to {state.revision}"
            )
        if existing_job_id is not None:
            job = self._job(state, existing_job_id)
            if state.active_job is None or state.active_job.id != existing_job_id:
                raise ActiveStageError("The queued scientific stage is no longer active")
            if job.status is not JobStatus.QUEUED:
                raise ActiveStageError("Only a queued decision continuation can be resumed")
            job.status = JobStatus.RUNNING
            job.process_id = None
            job.error = None
            state.current_stage = job.stage
            state.completion_status = CompletionStatus.RUNNING
        elif state.active_job:
            raise ActiveStageError(
                f"Study {study_id} already has an active stage: {state.active_job.stage}"
            )
        else:
            job = Job(
                id=self.controller._id("job"),
                stage=stage,
                status=JobStatus.RUNNING,
                started_at=utc_now(),
                request_id=request_id,
            )
            state.jobs.append(job)
            state.current_stage = stage
            state.completion_status = CompletionStatus.RUNNING
        log_directory = Path(request.log_directory)
        log_directory.mkdir(parents=True, exist_ok=True)
        stdout_log = log_directory / f"{request.log_name}.stdout.log"
        stderr_log = log_directory / f"{request.log_name}.stderr.log"
        stdout_log.touch()
        stderr_log.touch()
        self._add_log_artifacts(state, job, request, stdout_log, stderr_log)
        StudyController._event(
            state,
            EventType.STAGE_STARTED,
            f"{job.stage} {'resumed' if existing_job_id else 'started'}",
            explanation=(
                "The retained scientific stage resumed after the recorded decision."
                if existing_job_id else
                "The scientific stage is running outside the application event loop."
            ),
            technical={
                "job_id": job.id, "command": list(map(str, request.command)),
                "resumed": existing_job_id is not None,
            },
        )
        self.controller.store.save(state, expected_revision=expected_revision)

        def record_process_id(process_id: int) -> None:
            def mutation(latest):
                self._job(latest, job.id).process_id = process_id
            self.controller.store.update(study_id, mutation)

        last_feedback = None

        def record_progress() -> None:
            nonlocal last_feedback
            if progress_probe is None:
                return
            try:
                feedback = progress_probe()
            except Exception:
                # Feedback is advisory; it must never stop the scientific process.
                return
            if feedback == last_feedback:
                return
            phase, message, completed, total = feedback
            if total is not None and (total <= 0 or completed is None or not 0 <= completed <= total):
                return

            def mutation(latest):
                current = self._job(latest, job.id)
                current.progress_phase = phase
                current.progress_message = message
                current.progress_completed = completed
                current.progress_total = total
                if total is not None:
                    current.progress = completed / total

            try:
                self.controller.store.update(study_id, mutation)
            except Exception:
                # Progress persistence is advisory; terminal job recording is not.
                return
            last_feedback = feedback

        try:
            result = self.runner.run(
                request, cancel_event=cancel_event, on_output=on_output,
                on_started=record_process_id, on_tick=record_progress,
            )
        except ProcessExecutionError as exc:
            self._finish(study_id, job.id, request, exc.result)
            raise
        except Exception as exc:
            # Spawn and process-tracking failures are structured stage
            # failures, not untracked exceptions in a GUI worker.
            result = None
            with stderr_log.open("a") as handle:
                handle.write(str(exc) + "\n")
            self._finish_spawn_failure(study_id, job.id, request, exc, stdout_log, stderr_log)
            raise

        if result.status is ProcessStatus.COMPLETED:
            missing = [str(Path(path)) for path in required_outputs if not Path(path).is_file()]
            if missing:
                message = "Required stage output was not created: " + ", ".join(missing)
                stderr_log = Path(result.stderr_log)
                with stderr_log.open("a") as handle:
                    handle.write(message + "\n")
                result = replace(result, status=ProcessStatus.FAILED, returncode=1, stderr_tail=message)
        if result.status is ProcessStatus.FAILED and intervention_probe is not None:
            decision = intervention_probe()
            if decision is not None:
                self.controller.pause_for_decision(study_id, decision)
                return result
        self._finish(study_id, job.id, request, result)
        if request.check and result.status is not ProcessStatus.COMPLETED:
            raise ProcessExecutionError(result)
        return result

    def _finish_spawn_failure(
        self,
        study_id: str,
        job_id: str,
        request: ProcessRequest,
        error: Exception,
        stdout_log: Path,
        stderr_log: Path,
    ) -> None:
        state = self.controller.get_study(study_id)
        job = self._job(state, job_id)
        job.status = JobStatus.FAILED
        job.error = str(error)
        job.finished_at = utc_now()
        state.current_stage = None
        state.completion_status = CompletionStatus.FAILED
        self._add_log_artifacts(state, job, request, stdout_log, stderr_log)
        StudyController._event(
            state,
            EventType.STAGE_FAILED,
            f"{job.stage} failed to start",
            explanation=str(error),
            technical={"job_id": job.id, "error_type": type(error).__name__},
            mandatory=True,
        )
        self.controller.store.save(state)

    def _finish(self, study_id: str, job_id: str, request: ProcessRequest, result: ProcessResult) -> None:
        state = self.controller.get_study(study_id)
        job = self._job(state, job_id)
        job.finished_at = result.finished_at
        job.progress = 1.0 if result.status is ProcessStatus.COMPLETED else job.progress
        status_map = {
            ProcessStatus.COMPLETED: (JobStatus.COMPLETED, CompletionStatus.RUNNING),
            ProcessStatus.FAILED: (JobStatus.FAILED, CompletionStatus.FAILED),
            ProcessStatus.CANCELLED: (JobStatus.CANCELLED, CompletionStatus.CANCELLED),
            ProcessStatus.TIMED_OUT: (JobStatus.INTERRUPTED, CompletionStatus.INTERRUPTED),
        }
        job.status, state.completion_status = status_map[result.status]
        if result.status is not ProcessStatus.COMPLETED:
            job.error = result.stderr_tail or result.status.value
        state.current_stage = None
        stdout_log = Path(result.stdout_log)
        stderr_log = Path(result.stderr_log)
        self._add_log_artifacts(state, job, request, stdout_log, stderr_log)
        if result.status is ProcessStatus.COMPLETED:
            record_stage_completion(state, job.stage)
            StudyController._event(
                state,
                EventType.STAGE_COMPLETED,
                f"{job.stage} completed",
                explanation="The stage completed and its raw logs were retained as artifacts.",
                technical={"job_id": job.id, "duration_seconds": result.duration_seconds},
            )
        else:
            StudyController._event(
                state,
                EventType.STAGE_FAILED,
                f"{job.stage} {result.status.value}",
                explanation=(result.stderr_tail or "The stage did not complete successfully.").strip(),
                technical={
                    "job_id": job.id,
                    "status": result.status.value,
                    "returncode": result.returncode,
                },
                mandatory=True,
            )
        self.controller.store.save(state)

    @staticmethod
    def _job(state, job_id: str) -> Job:
        job = next((item for item in state.jobs if item.id == job_id), None)
        if job is None:
            raise KeyError(f"Unknown job: {job_id}")
        return job

    @staticmethod
    def _add_log_artifacts(state, job: Job, request: ProcessRequest, stdout_log: Path, stderr_log: Path) -> None:
        existing = {artifact.id for artifact in state.artifacts}
        for suffix, kind, path in (
            ("stdout", "job_stdout_log", stdout_log),
            ("stderr", "job_stderr_log", stderr_log),
        ):
            if not path.is_file():
                continue
            artifact_id = f"{job.id}-{suffix}"
            if artifact_id in existing:
                prior = next(item for item in state.artifacts if item.id == artifact_id)
                if Path(prior.path) == path.resolve():
                    continue
                safe_name = "".join(
                    character if character.isalnum() or character in {"-", "_"} else "-"
                    for character in request.log_name
                ).strip("-")
                artifact_id = f"{job.id}-{suffix}-{safe_name}"
                if artifact_id in existing:
                    continue
            state.artifacts.append(ArtifactRecord(
                id=artifact_id,
                kind=kind,
                path=str(path.resolve()),
                description=f"Complete {job.stage} {suffix} log",
                metadata={"job_id": job.id, "command_log_name": request.log_name},
            ))


class _ScientificJobLease:
    """One scientific process across all studies in an application workspace."""

    _registry_guard = threading.Lock()
    _locks: dict[str, threading.Lock] = {}

    def __init__(self, store, allowed_active: tuple[str, str] | None = None):
        self.store = store
        self.path = store.root / ".scientific-job.lock"
        self.handle = None
        self.allowed_active = allowed_active
        key = str(store.root.resolve())
        with self._registry_guard:
            self.thread_lock = self._locks.setdefault(key, threading.Lock())

    def __enter__(self):
        if not self.thread_lock.acquire(blocking=False):
            raise ActiveStageError("Another scientific stage is already running in this application")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.handle = self.path.open("a+")
            if fcntl is not None:
                try:
                    fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise ActiveStageError("Another scientific stage is already running in this application") from exc
            for path in self.store.root.glob("*/application_state.json"):
                state = self.store.load(path.parent.name)
                if state.active_job:
                    if self.allowed_active == (state.study_id, state.active_job.id):
                        continue
                    raise ActiveStageError(
                        f"Study {state.study_id} already has an active stage: {state.active_job.stage}"
                    )
            return self
        except Exception:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_error):
        if self.handle is not None:
            if fcntl is not None:
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None
        if self.thread_lock.locked():
            self.thread_lock.release()
