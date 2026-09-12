"""Persisted job orchestration built on the cancellable process adapter."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable

from .application import ActiveStageError, StudyController
from .events import EventType
from .models import ArtifactRecord, CompletionStatus, Job, JobStatus, utc_now
from .processes import ProcessOutput, ProcessRequest, ProcessResult, ProcessRunner, ProcessStatus


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
    ) -> ProcessResult:
        state = self.controller.get_study(study_id)
        if state.active_job:
            raise ActiveStageError(
                f"Study {study_id} already has an active stage: {state.active_job.stage}"
            )
        job = Job(
            id=self.controller._id("job"),
            stage=stage,
            status=JobStatus.RUNNING,
            started_at=utc_now(),
        )
        state.jobs.append(job)
        state.current_stage = stage
        state.completion_status = CompletionStatus.RUNNING
        StudyController._event(
            state,
            EventType.STAGE_STARTED,
            f"{stage} started",
            explanation="The scientific stage is running outside the application event loop.",
            technical={"job_id": job.id, "command": list(map(str, request.command))},
        )
        self.controller.store.save(state)

        try:
            result = self.runner.run(request, cancel_event=cancel_event, on_output=on_output)
        except OSError as exc:
            # A missing executable is a structured stage failure, not an
            # untracked exception in a GUI worker.
            result = None
            stdout_log = Path(request.log_directory) / f"{request.log_name}.stdout.log"
            stderr_log = Path(request.log_directory) / f"{request.log_name}.stderr.log"
            stdout_log.parent.mkdir(parents=True, exist_ok=True)
            stdout_log.touch()
            stderr_log.write_text(str(exc) + "\n")
            self._finish_spawn_failure(study_id, job.id, request, exc, stdout_log, stderr_log)
            raise

        self._finish(study_id, job.id, request, result)
        return result

    def _finish_spawn_failure(
        self,
        study_id: str,
        job_id: str,
        request: ProcessRequest,
        error: OSError,
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
            ProcessStatus.COMPLETED: (JobStatus.COMPLETED, CompletionStatus.COMPLETED),
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
            if not path.is_file() or f"{job.id}-{suffix}" in existing:
                continue
            state.artifacts.append(ArtifactRecord(
                id=f"{job.id}-{suffix}",
                kind=kind,
                path=str(path.resolve()),
                description=f"Complete {job.stage} {suffix} log",
                metadata={"job_id": job.id, "command_log_name": request.log_name},
            ))
