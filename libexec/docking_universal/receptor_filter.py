"""Native, fixed-width translation of the established receptor input filter.

This is the same component policy as prepare.d/receptor.sh, not a new cleanup
policy. The original deposited file stays unchanged and remains audit evidence.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path


def _identity(line: str, offset: int = 0):
    return (line[17 + offset:20 + offset].strip(), line[21 + offset:22 + offset].strip(),
            line[22 + offset:26 + offset].strip() + line[26 + offset:27 + offset].strip())


def _linked(lines):
    return {identity for line in lines if line.startswith("LINK  ")
            for identity in (_identity(line), _identity(line, 30))}


def filter_receptor_pdb(source: Path, destination: Path) -> dict:
    if source.resolve() == destination.resolve():
        raise ValueError("The deposited receptor source cannot be overwritten by filtering")
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    modified = {line[12:15].strip() for line in lines if line.startswith("MODRES") and line[12:15].strip()}
    linked = _linked(lines)
    counts = Counter(_identity(line) for line in lines if line.startswith("HETATM"))
    retained = []
    for line in lines:
        if line.startswith(("CRYST1", "SCALE1", "SCALE2", "SCALE3", "ORIGX1", "ORIGX2", "ORIGX3", "ATOM  ")):
            retained.append(line)
        elif line.startswith("HETATM"):
            identity = _identity(line)
            if identity[0] in modified:
                retained.append("ATOM  " + line[6:])
            elif identity in linked and counts[identity] > 1 and identity[0] not in {"HOH", "WAT", "DOD"}:
                retained.append(line)
            elif line[76:78].strip().upper() in {"ZN", "MG", "MN", "CA", "FE", "CU"}:
                retained.append(line)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8", newline="\n") as output:
        output.write("".join(retained))
    components = []
    for line in retained:
        identity = _identity(line)
        if line.startswith("HETATM") and identity in linked and identity[0] not in {"HOH", "WAT", "DOD"}:
            label = ":".join(identity)
            if label not in components:
                components.append(label)
    return {"policy": "established receptor component filter", "retained_linked_components": components,
            "source_modified": False, "crystal_context_preserved": True}


def disulfide_templates(source: Path) -> str:
    assignments = set()
    for line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.startswith("SSBOND"):
            continue
        first = (line[11:14].strip(), line[15:16].strip(), line[17:21].strip(), line[21:22].strip())
        second = (line[25:28].strip(), line[29:30].strip(), line[31:35].strip(), line[35:36].strip())
        if first[0] == second[0] == "CYS" and first[2] and second[2]:
            for _, chain, number, insertion in (first, second):
                assignments.add(f"{chain}:{number}{insertion}=CYX")
    return ",".join(sorted(assignments))
