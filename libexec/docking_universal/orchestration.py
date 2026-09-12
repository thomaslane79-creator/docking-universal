"""Asynchronous host-owned orchestration for the first GUI protocol workflow."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from .application import ActiveStageError, StudyController
from .events import EventType
from .models import CompletionStatus
from .services.pocket_review import PocketReviewInputs, PocketReviewService, ordered_pocket_boxes
from .services.preparation import (
    ReceptorPreparationOptions,
    ReceptorPreparationService,
    build_receptor_preparation_plan,
)


class ProtocolWorkflowRunner:
    """Start fixed scientific stages without blocking the host command loop."""

    def __init__(self, controller: StudyController, preparation_executable: Path | str):
        self.controller = controller
        self.preparation_executable = Path(preparation_executable).resolve()
        self._guard = threading.Lock()
        self._cancellations: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}

    def start_preparation(
        self,
        study_id: str,
        payload: dict[str, Any],
        *,
        request_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        state = self.controller.get_study(study_id)
        prior = next((job for job in state.jobs if job.request_id == request_id), None)
        if prior:
            return {"job_id": prior.id, "stage": prior.stage, "replayed": True}
        if state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError(
                f"Study {study_id} changed from revision {expected_revision} to {state.revision}"
            )
        if any(
            job.stage == "preparation_and_pocket_detection" and job.status.value == "completed"
            for job in state.jobs
        ):
            raise ActiveStageError(
                "Receptor preparation is already complete for this study; resume its current workflow stage"
            )
        self._assert_no_active_stage()
        allowed = {
            "input_pdb", "working_directory", "site_mode", "ligand_resname",
            "feedback_level", "cavity_mode", "max_pockets", "center_mode",
            "centroid_mode", "pdbfixer", "preparation_backend", "meeko_templates",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown preparation options: {', '.join(sorted(unknown))}")
        values = dict(payload)
        for name in ("input_pdb", "working_directory"):
            if name not in values:
                raise ValueError(f"Preparation option is required: {name}")
            values[name] = Path(values[name])
        options = ReceptorPreparationOptions(**values)
        plan = build_receptor_preparation_plan(self.preparation_executable, options)
        cancellation = threading.Event()

        def work() -> None:
            try:
                result = ReceptorPreparationService(self.controller).run(
                    study_id, plan, cancel_event=cancellation,
                    request_id=request_id, expected_revision=expected_revision,
                )
                if result.status.value == "completed":
                    self._start_review(study_id, plan.output_root)
            except Exception as exc:
                self._record_orchestration_failure(study_id, str(exc))
            finally:
                with self._guard:
                    self._cancellations.pop(study_id, None)
                    self._threads.pop(study_id, None)

        thread = threading.Thread(target=work, name=f"du-workflow-{study_id}", daemon=True)
        with self._guard:
            if self._threads:
                raise ActiveStageError("Another scientific workflow is already running")
            self._cancellations[study_id] = cancellation
            self._threads[study_id] = thread
            thread.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            latest = self.controller.get_study(study_id)
            job = next((item for item in latest.jobs if item.request_id == request_id), None)
            if job:
                return {"job_id": job.id, "stage": job.stage, "output_root": str(plan.output_root)}
            if not thread.is_alive():
                break
            time.sleep(0.01)
        raise RuntimeError("Preparation worker did not persist its job start")

    def cancel(self, study_id: str) -> bool:
        with self._guard:
            cancellation = self._cancellations.get(study_id)
            if not cancellation:
                return False
            cancellation.set()
            return True

    def shutdown(self, timeout_seconds: float = 4.0) -> None:
        """Cancel and reap the one worker before the application host exits."""
        with self._guard:
            workers = list(self._threads.values())
            for cancellation in self._cancellations.values():
                cancellation.set()
        deadline = time.monotonic() + timeout_seconds
        for worker in workers:
            worker.join(max(0.0, deadline - time.monotonic()))

    def _assert_no_active_stage(self) -> None:
        for path in self.controller.store.root.glob("*/application_state.json"):
            state = self.controller.store.load(path.parent.name)
            if state.active_job:
                raise ActiveStageError(
                    f"Study {state.study_id} already has an active stage: {state.active_job.stage}"
                )

    def _start_review(self, study_id: str, output_root: Path) -> None:
        cavity = output_root / "cavity"
        boxes = tuple(ordered_pocket_boxes(cavity))
        if not boxes:
            raise FileNotFoundError(f"Preparation produced no retained docking boxes in {cavity}")
        evidence = cavity / "pdb_site_evidence" / "pdb_ligand_site_evidence.json"
        scenes = sorted(cavity.glob("*_all_retained_pockets_review.pml"))
        PocketReviewService(self.controller).start(study_id, PocketReviewInputs(
            target=output_root.name.removesuffix("_receptor_prep"),
            cavity_directory=cavity,
            boxes=boxes,
            pocket_evidence_record=evidence if evidence.is_file() else None,
            review_scene=scenes[0] if scenes else None,
        ))

    def _record_orchestration_failure(self, study_id: str, error: str) -> None:
        state = self.controller.get_study(study_id)
        # JobService already recorded process failures. This path records only
        # orchestration failures after a successful external stage.
        if state.completion_status in {CompletionStatus.FAILED, CompletionStatus.CANCELLED}:
            return
        state.completion_status = CompletionStatus.FAILED
        state.current_stage = None
        StudyController._event(
            state, EventType.STAGE_FAILED, "GUI protocol orchestration failed",
            explanation=error, technical={"component": "ProtocolWorkflowRunner"}, mandatory=True,
        )
        self.controller.store.save(state)
