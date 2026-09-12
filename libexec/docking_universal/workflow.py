"""Explicit scientific workflow transitions independent of any user interface."""

from __future__ import annotations

from dataclasses import dataclass

from .models import CompletionStatus


@dataclass(frozen=True)
class StageTransition:
    stage: str
    next_stage: str | None
    completes_workflow: bool = False


SITE_GUIDED_PROTOCOL = (
    StageTransition("receptor_input", "receptor_preparation"),
    StageTransition("receptor_preparation", "pocket_detection"),
    StageTransition("pocket_detection", "pocket_review"),
    StageTransition("fpocket", "pocket_review"),
    StageTransition("pocket_review", "region_approval"),
    StageTransition("region_approval", "final_report"),
    StageTransition("final_report", "bundle"),
    StageTransition("bundle", None, True),
)

WORKFLOWS = {"site_guided_protocol": {item.stage: item for item in SITE_GUIDED_PROTOCOL}}


def record_stage_completion(state, stage: str) -> None:
    """Advance workflow state without confusing stage success with study completion."""
    completed = state.workflow_data.setdefault("completed_stages", [])
    if stage not in completed:
        completed.append(stage)
    transition = WORKFLOWS.get(state.workflow, {}).get(stage)
    if transition is None:
        # Compatibility for standalone component jobs which have no workflow
        # definition yet. Their process completed, but scientific authority is
        # still independent of process status.
        state.workflow_data["next_stage"] = None
        state.completion_status = CompletionStatus.COMPLETED
        return
    state.workflow_data["next_stage"] = transition.next_stage
    state.completion_status = (
        CompletionStatus.COMPLETED if transition.completes_workflow else CompletionStatus.RUNNING
    )
