"""Typed, deterministic atom-selection operations."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from .identities import AtomIdentity


SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")


class SelectionOperation(str, Enum):
    UNION = "union"
    INTERSECTION = "intersection"
    EXCLUSION = "exclusion"


@dataclass(frozen=True)
class AtomPoint:
    atom: AtomIdentity
    xyz: tuple[float, float, float]

    def __post_init__(self) -> None:
        if len(self.xyz) != 3 or not all(math.isfinite(float(value)) for value in self.xyz):
            raise ValueError("Atom coordinates must contain three finite values")


@dataclass(frozen=True)
class Selection:
    name: str
    atoms: tuple[AtomIdentity, ...]
    origin_request_id: str | None = None

    def __post_init__(self) -> None:
        if not SAFE_NAME.fullmatch(self.name):
            raise ValueError("Selection name must be a safe viewer identifier")
        object.__setattr__(self, "atoms", tuple(sorted(set(self.atoms))))

    def combine(self, other: "Selection", operation: SelectionOperation, *, name: str | None = None) -> "Selection":
        left, right = set(self.atoms), set(other.atoms)
        if operation is SelectionOperation.UNION:
            atoms = left | right
        elif operation is SelectionOperation.INTERSECTION:
            atoms = left & right
        elif operation is SelectionOperation.EXCLUSION:
            atoms = left - right
        else:  # pragma: no cover - Enum prevents this for typed callers
            raise ValueError(f"Unsupported selection operation: {operation}")
        return Selection(name or self.name, tuple(atoms), self.origin_request_id)

    def whole_residues(self, universe: Iterable[AtomIdentity], *, name: str | None = None) -> "Selection":
        residues = {atom.residue_key for atom in self.atoms}
        return Selection(name or self.name, tuple(atom for atom in universe if atom.residue_key in residues), self.origin_request_id)

    @classmethod
    def within_distance(
        cls,
        name: str,
        candidates: Iterable[AtomPoint],
        anchors: Iterable[AtomPoint],
        distance: float,
        *,
        origin_request_id: str | None = None,
    ) -> "Selection":
        if not math.isfinite(distance) or distance < 0:
            raise ValueError("Selection distance must be finite and nonnegative")
        anchor_list = list(anchors)
        cutoff_squared = distance * distance
        atoms = []
        for candidate in candidates:
            if any(sum((candidate.xyz[index] - anchor.xyz[index]) ** 2 for index in range(3)) <= cutoff_squared for anchor in anchor_list):
                atoms.append(candidate.atom)
        return cls(name, tuple(atoms), origin_request_id)
