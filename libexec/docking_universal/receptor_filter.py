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


def filter_receptor_pdb(source: Path, destination: Path, *, bound_reference=None) -> dict:
    if source.resolve() == destination.resolve():
        raise ValueError("The deposited receptor source cannot be overwritten by filtering")
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    modified = {line[12:15].strip() for line in lines if line.startswith("MODRES") and line[12:15].strip()}
    linked = _linked(lines)
    counts = Counter(_identity(line) for line in lines if line.startswith("HETATM"))
    reference = None
    reference_count = 0
    if bound_reference:
        # The reference remains in the full source used for ligand extraction
        # and evidence. Its exact instance must not become part of the scored
        # receptor merely because it coordinates a retained metal.
        row = bound_reference
        reference = (str(row['resname']).strip(), str(row['chain']).strip(),
                     str(row['number']).strip() + str(row.get('insertion_code') or '').strip())
        if reference[1] in {'.', '_'}:
            reference = (reference[0], '', reference[2])
        matching = [line for line in lines if line.startswith(('ATOM  ', 'HETATM'))
                    and _identity(line) == reference]
        if not matching or any(line.startswith('ATOM  ') for line in matching):
            raise ValueError('The exact bound reference must be a retained non-polymer instance in the full source')
        reference_count = len(matching)
        for line in lines:
            if not line.startswith('LINK  '):
                continue
            endpoints = (_identity(line), _identity(line, 30))
            if reference not in endpoints:
                continue
            other = endpoints[1] if endpoints[0] == reference else endpoints[0]
            atoms = [value for value in lines if value.startswith('HETATM') and _identity(value) == other]
            # A standalone coordination ion can stay while its chosen ligand
            # is withheld. Do not silently cleave a ligand-protein or other
            # multi-atom covalent/adduct link for noncovalent redocking.
            if len(atoms) != 1 or atoms[0][76:78].strip().upper() not in {
                    'ZN', 'MG', 'MN', 'CA', 'FE', 'CU', 'CO', 'NI', 'CD', 'HG'}:
                raise ValueError('The selected bound reference has a link to a protein or multi-atom component; '
                                 'explicit covalent-reference review is required before noncovalent preparation')
    retained = []
    for line in lines:
        if line.startswith(("CRYST1", "SCALE1", "SCALE2", "SCALE3", "ORIGX1", "ORIGX2", "ORIGX3", "ATOM  ")):
            retained.append(line)
        elif line.startswith("HETATM"):
            identity = _identity(line)
            if identity == reference:
                continue
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
            "bound_reference_separation": ({'identity': dict(bound_reference),
                'withheld_from_scored_receptor_atom_records': reference_count,
                'original_reference_coordinates_retained': True} if reference else None),
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
