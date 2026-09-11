"""Lossless workflow events with presentation-specific views."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import utc_now


class EventType(str, Enum):
    STAGE_STARTED = "stage_started"
    PROGRESS_UPDATED = "progress_updated"
    WARNING_RAISED = "warning_raised"
    DECISION_REQUIRED = "decision_required"
    DECISION_RESOLVED = "decision_resolved"
    ARTIFACT_CREATED = "artifact_created"
    STAGE_FAILED = "stage_failed"
    STAGE_COMPLETED = "stage_completed"


class ScientificDetail(str, Enum):
    CONCISE = "concise"
    GUIDED = "guided"
    TEACHING = "teaching"
    TECHNICAL = "technical"


@dataclass(frozen=True)
class WorkflowEvent:
    id: str
    sequence: int
    type: EventType
    message: str
    created_at: str = field(default_factory=utc_now)
    explanation: str = ""
    teaching: str = ""
    technical: dict[str, Any] = field(default_factory=dict)
    data: dict[str, Any] = field(default_factory=dict)
    mandatory: bool = False

    def presented(self, detail: ScientificDetail) -> dict[str, Any]:
        """Create a display projection without modifying retained evidence."""
        view: dict[str, Any] = {
            "id": self.id,
            "sequence": self.sequence,
            "type": self.type.value,
            "message": self.message,
            "mandatory": self.mandatory,
        }
        # Mandatory warnings and decision consequences remain visible even in
        # Concise mode.  Detail settings may reduce presentation density, but
        # must never become a way to conceal why scientific work stopped.
        if self.mandatory or detail in {ScientificDetail.GUIDED, ScientificDetail.TEACHING, ScientificDetail.TECHNICAL}:
            view["explanation"] = self.explanation
        if detail in {ScientificDetail.TEACHING, ScientificDetail.TECHNICAL}:
            view["teaching"] = self.teaching
        if detail is ScientificDetail.TECHNICAL:
            view["technical"] = self.technical
            view["data"] = self.data
        return view
