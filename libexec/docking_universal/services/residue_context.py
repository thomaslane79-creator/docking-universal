"""Resolve PLIP protein contacts to receptor atoms and residue context."""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path


BACKBONE_ATOMS = frozenset({"N", "CA", "C", "O", "OXT"})


@dataclass(frozen=True)
class ResidueAtom:
    name: str
    element: str
    xyz: tuple[float, float, float]
    serial: int | None = None


@dataclass(frozen=True)
class ResidueContext:
    residue_name: str
    residue_number: str
    chain: str
    atoms: tuple[ResidueAtom, ...]
    interacting_atom: str

    @property
    def interacting_atom_is_backbone(self) -> bool:
        return self.interacting_atom.upper() in BACKBONE_ATOMS

    @property
    def context_kind(self) -> str:
        return "main_chain" if self.interacting_atom_is_backbone else "side_chain"


def _element(atom_name: str, line: str) -> str:
    value = line[76:78].strip() if len(line) >= 78 else ""
    return value.upper() or "".join(char for char in atom_name if char.isalpha())[:1].upper()


def read_receptor_atoms(path: Path | str) -> dict[tuple[str, str, str], tuple[ResidueAtom, ...]]:
    """Read protein atoms keyed by (residue name, residue number, chain)."""
    groups: dict[tuple[str, str, str], list[ResidueAtom]] = {}
    for line in Path(path).read_text(errors="replace").splitlines():
        if not line.startswith("ATOM  "):
            continue
        atom_name = line[12:16].strip()
        residue_name = line[17:20].strip()
        chain = line[21].strip()
        residue_number = line[22:26].strip()
        try:
            xyz = tuple(float(line[start:start + 8]) for start in (30, 38, 46))
        except ValueError:
            continue
        if not atom_name or not residue_name or not residue_number or not all(math.isfinite(v) for v in xyz):
            continue
        serial_text = line[6:11].strip()
        key = (residue_name, residue_number, chain)
        groups.setdefault(key, []).append(ResidueAtom(
            atom_name, _element(atom_name, line), xyz,
            int(serial_text) if serial_text.isdigit() else None,
        ))
    return {key: tuple(value) for key, value in groups.items()}


def resolve_contact(
    receptor_atoms: dict[tuple[str, str, str], tuple[ResidueAtom, ...]],
    *,
    residue_name: str,
    residue_number: str,
    chain: str,
    contact_xyz: tuple[float, float, float],
) -> ResidueContext | None:
    """Map PLIP's protein-side coordinate to the nearest receptor atom."""
    key = (residue_name.strip(), str(residue_number).strip(), chain.strip())
    atoms = receptor_atoms.get(key)
    if not atoms:
        return None
    atom = min(atoms, key=lambda item: math.dist(item.xyz, contact_xyz))
    return ResidueContext(key[0], key[1], key[2], atoms, atom.name)
