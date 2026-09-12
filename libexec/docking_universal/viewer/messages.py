"""Versioned command, acknowledgement, error, and event envelopes."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from typing import Any


PROTOCOL_VERSION = 1


def _required(value: str, label: str) -> str:
    if not value or any(ord(character) < 32 for character in value):
        raise ValueError(f"{label} is required and may not contain control characters")
    return value


@dataclass(frozen=True)
class Command:
    study_id: str
    session_id: str
    request_id: str
    operation: str
    payload: dict[str, Any] = field(default_factory=dict)
    expected_revision: int | None = None
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.version != PROTOCOL_VERSION:
            raise ValueError(f"Unsupported protocol version: {self.version}")
        for value, label in (
            (self.study_id, "Study ID"), (self.session_id, "Session ID"),
            (self.request_id, "Request ID"), (self.operation, "Operation"),
        ):
            _required(value, label)
        if self.expected_revision is not None and self.expected_revision < 0:
            raise ValueError("Expected revision cannot be negative")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Command":
        allowed = {item.name for item in fields(cls)}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Unknown command fields: {', '.join(sorted(unknown))}")
        return cls(**value)


@dataclass(frozen=True)
class Response:
    request_id: str
    status: str
    revision: int | None = None
    result: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        _required(self.request_id, "Request ID")
        if self.status not in {"applied", "replayed", "rejected", "error"}:
            raise ValueError(f"Unsupported response status: {self.status}")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Event:
    study_id: str
    session_id: str
    sequence: int
    event: str
    payload: dict[str, Any] = field(default_factory=dict)
    origin_request_id: str | None = None
    version: int = PROTOCOL_VERSION

    def __post_init__(self) -> None:
        if self.version != PROTOCOL_VERSION or self.sequence < 1:
            raise ValueError("Invalid viewer event version or sequence")
        _required(self.study_id, "Study ID")
        _required(self.session_id, "Session ID")
        _required(self.event, "Event name")

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
