"""Stable structural identities; viewer indexes are deliberately excluded."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


SAFE_TOKEN = re.compile(r"^[^\x00-\x1f\x7f]*$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _text(value: Any, label: str, *, required: bool = False) -> str:
    result = str(value)
    if not SAFE_TOKEN.fullmatch(result) or (required and not result):
        raise ValueError(f"Invalid {label}")
    return result


@dataclass(frozen=True, order=True)
class StructureIdentity:
    artifact_id: str
    sha256: str
    model: str
    state: int = 1
    assembly_copy: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _text(self.artifact_id, "artifact ID", required=True))
        object.__setattr__(self, "model", _text(self.model, "model", required=True))
        object.__setattr__(self, "assembly_copy", _text(self.assembly_copy, "assembly-copy identity"))
        if not SHA256.fullmatch(self.sha256):
            raise ValueError("Structure sha256 must contain 64 lowercase hexadecimal characters")
        if self.state < 1:
            raise ValueError("Structure state must be at least 1")


@dataclass(frozen=True, order=True)
class AtomIdentity:
    structure: StructureIdentity
    segment: str
    chain: str
    residue_number: str
    insertion_code: str
    residue_name: str
    atom_name: str
    altloc: str = ""

    def __post_init__(self) -> None:
        for field_name in (
            "segment", "chain", "insertion_code", "residue_name", "atom_name", "altloc",
        ):
            object.__setattr__(self, field_name, _text(getattr(self, field_name), field_name))
        object.__setattr__(self, "residue_number", _text(self.residue_number, "residue number", required=True))
        if not self.atom_name:
            raise ValueError("Atom name is required")

    @property
    def residue_key(self) -> tuple[Any, ...]:
        return (
            self.structure, self.segment, self.chain, self.residue_number,
            self.insertion_code, self.residue_name,
        )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AtomIdentity":
        item = dict(value)
        structure = item.get("structure")
        if not isinstance(structure, dict):
            raise ValueError("Atom identity requires a structure identity")
        item["structure"] = StructureIdentity(**structure)
        return cls(**item)


class IdentityMapping:
    """Explicit one-to-one source/target mapping with ambiguity rejection."""

    def __init__(self, pairs: Iterable[tuple[AtomIdentity, AtomIdentity]]):
        self._forward: dict[AtomIdentity, AtomIdentity] = {}
        self._reverse: dict[AtomIdentity, AtomIdentity] = {}
        for source, target in pairs:
            if source in self._forward and self._forward[source] != target:
                raise ValueError(f"Ambiguous target mapping for {source}")
            if target in self._reverse and self._reverse[target] != source:
                raise ValueError(f"Ambiguous source mapping for {target}")
            self._forward[source] = target
            self._reverse[target] = source

    def map(self, atoms: Iterable[AtomIdentity], *, reverse: bool = False) -> tuple[AtomIdentity, ...]:
        table = self._reverse if reverse else self._forward
        result = []
        for atom in atoms:
            if atom not in table:
                raise KeyError(f"No exact structural mapping for {atom}")
            result.append(table[atom])
        return tuple(result)
