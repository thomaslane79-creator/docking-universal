"""Typed, auditable scientific decision requests and responses."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .models import utc_now


class DecisionStatus(str, Enum):
    PENDING = "pending"
    RESOLVED = "resolved"
    DECLINED = "declined"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class DecisionOption:
    value: str
    label: str
    consequence: str
    recommended: bool = False
    automation_eligible: bool = True


@dataclass
class DecisionRequired:
    id: str
    kind: str
    prompt: str
    detected: str
    why_stopped: str
    consequences: tuple[str, ...]
    options: tuple[DecisionOption, ...]
    artifact_ids: tuple[str, ...] = ()
    minimum_selections: int = 1
    maximum_selections: int | None = 1
    changes_molecular_model: bool = False
    grants_scientific_authority: bool = False
    automation_eligible: bool = False
    payload: dict[str, Any] = field(default_factory=dict)
    presentation: dict[str, Any] = field(default_factory=dict)
    continuation: dict[str, Any] = field(
        default_factory=lambda: {"action": "complete_stage"}
    )
    status: DecisionStatus = DecisionStatus.PENDING
    created_at: str = field(default_factory=utc_now)
    resolved_at: str | None = None

    @property
    def requires_explicit_user(self) -> bool:
        return self.changes_molecular_model or self.grants_scientific_authority or not self.automation_eligible

    def validate_response(self, selections: tuple[str, ...]) -> None:
        if self.status is not DecisionStatus.PENDING:
            raise ValueError(f"Decision {self.id} has already been resolved")
        if len(selections) < self.minimum_selections:
            raise ValueError(f"Decision {self.id} requires at least {self.minimum_selections} selection(s)")
        if self.maximum_selections is not None and len(selections) > self.maximum_selections:
            raise ValueError(f"Decision {self.id} permits at most {self.maximum_selections} selection(s)")
        allowed = {option.value for option in self.options}
        unknown = set(selections) - allowed
        if unknown:
            raise ValueError(f"Unknown decision option(s): {', '.join(sorted(unknown))}")
        if len(set(selections)) != len(selections):
            raise ValueError("A decision response cannot repeat an option")

    def validate_continuation(self) -> None:
        action = self.continuation.get("action", "complete_stage")
        if action not in {"complete_stage", "continue_stage", "none"}:
            raise ValueError(f"Unsupported decision continuation action: {action}")
        if action == "continue_stage" and not str(
            self.continuation.get("checkpoint", "")
        ).strip():
            raise ValueError("A continuing decision requires a checkpoint")


@dataclass(frozen=True)
class ApprovalRecord:
    id: str
    decision_id: str
    selections: tuple[str, ...]
    actor: str
    method: str
    rationale: str | None = None
    policy_id: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    request_id: str | None = None
    created_at: str = field(default_factory=utc_now)
