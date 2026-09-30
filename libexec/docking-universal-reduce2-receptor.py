#!/usr/bin/env python3
"""Run CCTBX reduce2 and audit the resulting receptor model."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import site
import subprocess
import tempfile
from collections import Counter
from math import dist
from pathlib import Path

try:
    from docking_universal.services.geostd_components import (
        GEOSTD_REVISION, bundled_minimal_library,
    )
except ImportError:  # installed/script diagnostics remain usable without package import
    GEOSTD_REVISION = ""
    bundled_minimal_library = None


def atom_key(line: str):
    return (line[21:22].strip(), line[22:26].strip(), line[26:27].strip(),
            line[17:20].strip(), line[12:16].strip(), line[0:6].strip())


def atoms(path: Path):
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            element = line[76:78].strip().upper()
            if element != "H" and not line[12:16].strip().upper().startswith("H"):
                rows.append(atom_key(line))
    return rows


def backbone_nitrogen_hydrogen_conflicts(path: Path) -> list[dict]:
    """Find peptide nitrogens that Reduce2 has made over-valent.

    A backbone nitrogen covalently connected to the preceding residue carbonyl
    carbon can carry at most one hydrogen in the neutral peptide templates
    consumed by Meeko.  This coordinate-based check deliberately avoids atom
    naming conventions for added hydrogens while retaining residue identity in
    the audit record.
    """

    residues: dict[tuple[str, str, str, str], list[dict]] = {}
    order: dict[str, list[tuple[str, str, str, str]]] = {}
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        altloc = line[16:17]
        if altloc not in {" ", "A"}:
            continue
        chain = line[21:22].strip()
        key = (chain, line[22:26].strip(), line[26:27].strip(), line[17:20].strip())
        try:
            xyz = (float(line[30:38]), float(line[38:46]), float(line[46:54]))
        except ValueError:
            continue
        atom_name = line[12:16].strip()
        element = line[76:78].strip().upper()
        if not element:
            element = "H" if atom_name.upper().startswith("H") else atom_name[:1].upper()
        if key not in residues:
            residues[key] = []
            order.setdefault(chain, []).append(key)
        residues[key].append({"name": atom_name, "element": element, "xyz": xyz})

    conflicts = []
    for chain, keys in order.items():
        for previous_key, key in zip(keys, keys[1:]):
            previous_c = next((atom for atom in residues[previous_key] if atom["name"] == "C"), None)
            nitrogen = next((atom for atom in residues[key] if atom["name"] == "N"), None)
            alpha_carbon = next((atom for atom in residues[key] if atom["name"] == "CA"), None)
            if previous_c is None or nitrogen is None or alpha_carbon is None:
                continue
            if dist(previous_c["xyz"], nitrogen["xyz"]) > 1.8:
                continue
            if dist(nitrogen["xyz"], alpha_carbon["xyz"]) > 1.8:
                continue
            bonded_hydrogens = sorted(
                atom["name"] for atom in residues[key]
                if atom["element"] in {"H", "D"} and dist(nitrogen["xyz"], atom["xyz"]) <= 1.3
            )
            if len(bonded_hydrogens) > 1:
                conflicts.append({
                    "residue": f"{chain or '_'}:{key[1]}{key[2]}",
                    "component": key[3],
                    "backbone_nitrogen_hydrogen_count": len(bonded_hydrogens),
                    "hydrogen_atoms": bonded_hydrogens,
                    "reason": "internal peptide backbone nitrogen has more than one bonded hydrogen",
                })
    return conflicts


def locate_reduce2() -> Path | None:
    explicit = os.environ.get("REDUCE2_SCRIPT")
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    for root in site.getsitepackages() + [site.getusersitepackages()]:
        candidate = Path(root) / "mmtbx" / "command_line" / "reduce2.py"
        if candidate.is_file():
            return candidate
    return None


def locate_geostd() -> Path | None:
    explicit = os.environ.get("DOCKING_UNIVERSAL_GEOSTD") or os.environ.get("MMTBX_CCP4_MONOMER_LIB")
    candidates = [explicit] if explicit else []
    here = Path(__file__).resolve()
    # Source-tree installs keep the open-source monomer library beside the
    # python-conversion checkout. This avoids requiring a shell export for the
    # normal repository layout while still allowing packaged installations to
    # provide an explicit path.
    candidates.append(str(here.parents[2] / "third_party" / "geostd"))
    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        candidates.extend([str(Path(prefix) / "share" / "geostd"), str(Path(prefix) / "geostd")])
    # The installed application carries a small standard-protein restraint
    # core. Additional public components can be placed in a writable copy of
    # this layout after the GUI's explicit network disclosure and approval.
    candidates.append(str(here.parent / "docking_universal" / "data" / "geostd"))
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return None


def geostd_provenance(path: Path) -> dict:
    manifest = path / "docking-universal-component-provenance.json"
    if manifest.is_file():
        try:
            record = json.loads(manifest.read_text())
            disclosure = record.get("disclosure") or {}
            return {
                "component_library_mode": "minimal_core_with_approved_components",
                "geostd_revision": disclosure.get("revision"),
                "component_provenance": str(manifest.resolve()),
            }
        except (OSError, ValueError):
            pass
    if bundled_minimal_library is not None:
        try:
            if path.resolve() == bundled_minimal_library().resolve():
                return {
                    "component_library_mode": "bundled_minimal_core",
                    "geostd_revision": GEOSTD_REVISION,
                }
        except OSError:
            pass
    return {"component_library_mode": "external_library", "geostd_revision": None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_pdb", type=Path)
    parser.add_argument("output_pdb", type=Path)
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("log", type=Path)
    args = parser.parse_args(argv)
    reduce2 = locate_reduce2()
    if reduce2 is None:
        args.audit_json.write_text(json.dumps({"tool": "CCTBX reduce2", "status": "unavailable"}, indent=2) + "\n")
        args.log.write_text("CCTBX reduce2.py was not found in the active Python environment.\n")
        return 3
    geostd = locate_geostd()
    if geostd is None:
        args.audit_json.write_text(json.dumps({"tool": "CCTBX reduce2", "status": "unavailable", "reason": "CCP4 monomer library (geostd) not configured"}, indent=2) + "\n")
        args.log.write_text("CCTBX reduce2.py is installed, but the CCP4 monomer library is not configured. Set DOCKING_UNIVERSAL_GEOSTD or MMTBX_CCP4_MONOMER_LIB.\n")
        return 3
    args.output_pdb.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    before = Counter(atoms(args.input_pdb))
    with tempfile.TemporaryDirectory(prefix="docking-universal-reduce2-") as directory:
        work = Path(directory) / args.input_pdb.name
        work.write_text(args.input_pdb.read_text(errors="replace"))
        # reduce2 currently expects crystallographic context when available.
        if not any(line.startswith("CRYST1") for line in work.read_text(errors="replace").splitlines()):
            for line in args.input_pdb.read_text(errors="replace").splitlines():
                if line.startswith("CRYST1"):
                    work.write_text(line + "\n" + work.read_text())
                    break
        env = dict(os.environ)
        env["MMTBX_CCP4_MONOMER_LIB"] = str(geostd)
        cmd = [str(__import__("sys").executable), str(reduce2), str(work), "approach=add", "add_flip_movers=True"]
        completed = subprocess.run(cmd, cwd=directory, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        args.log.write_text(completed.stdout or "")
        candidates = sorted(Path(directory).glob(f"{work.stem}*H.pdb"))
        if completed.returncode != 0 or not candidates:
            missing = []
            match = __import__("re").search(
                r"Restraints were not found for the following residues:\s*([^\n]+)",
                completed.stdout or "",
            )
            if match:
                missing = sorted(set(match.group(1).split()))
            status = "component_definitions_required" if missing else "failed"
            args.audit_json.write_text(json.dumps({
                "tool": "CCTBX reduce2", "status": status,
                "command": " ".join(cmd), "component_library": str(geostd.resolve()),
                "missing_components": missing,
                **geostd_provenance(geostd),
            }, indent=2) + "\n")
            return completed.returncode or 1
        reduced = candidates[0]
        after = Counter(atoms(reduced))
        missing = list((before - after).elements())
        backbone_conflicts = backbone_nitrogen_hydrogen_conflicts(reduced)
        record = {
            "tool": "CCTBX reduce2",
            "status": "incompatible" if missing or backbone_conflicts else "compatible",
            "command": " ".join(cmd), "input": str(args.input_pdb.resolve()),
            "component_library": str(geostd.resolve()),
            **geostd_provenance(geostd),
            "output": str(args.output_pdb.resolve()), "input_heavy_atom_count": sum(before.values()),
            "output_heavy_atom_count": sum(after.values()), "missing_input_heavy_atoms": [list(x) for x in missing],
            "backbone_nitrogen_hydrogen_conflicts": backbone_conflicts,
            "added_hydrogen_count": sum(1 for line in reduced.read_text(errors="replace").splitlines() if line.startswith(("ATOM  ", "HETATM")) and (line[76:78].strip().upper() == "H" or line[12:16].strip().upper().startswith("H"))),
        }
        args.audit_json.write_text(json.dumps(record, indent=2) + "\n")
        if missing or backbone_conflicts:
            return 2
        shutil.copyfile(reduced, args.output_pdb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
