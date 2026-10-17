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
from math import dist, isfinite
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


def pdb_for_audit(path: Path, destination: Path) -> Path:
    """Convert native mmCIF without silently truncating author identifiers."""
    if path.suffix.lower() not in {".cif", ".mmcif"}:
        return path
    import gemmi

    structure = gemmi.read_structure(str(path))
    if len(structure) != 1:
        raise ValueError("Reduce2 input/output must contain exactly one model")
    count = 0
    for chain in structure[0]:
        if len(chain.name) > 1:
            raise ValueError("Reduce2 author chain cannot be represented in the engine PDB")
        for residue in chain:
            if len(residue.name) > 3 or not -999 <= residue.seqid.num <= 9999:
                raise ValueError("Reduce2 author residue cannot be represented in the engine PDB")
            for atom in residue:
                count += 1
                if len(atom.name) > 4:
                    raise ValueError("Reduce2 atom name cannot be represented in the engine PDB")
    if not 0 < count <= 99999:
        raise ValueError("Reduce2 atom count cannot be represented in the engine PDB")
    structure.write_pdb(str(destination))
    if len(atom_records(destination)) != count:
        raise ValueError("Reduce2 mmCIF to PDB conversion changed the atom inventory")
    return destination


def atom_records(path: Path):
    rows = []
    lines = path.read_text(errors="replace").splitlines()
    if sum(line.startswith("MODEL ") for line in lines) > 1:
        raise ValueError("Reduce2 input/output must contain exactly one model")
    for line in lines:
        if line.startswith(("ATOM  ", "HETATM")):
            element = line[76:78].strip().upper()
            if not element:
                element = "H" if line[12:16].strip().upper().startswith("H") else line[12:16].strip()[:1].upper()
            xyz = tuple(float(line[start:start + 8]) for start in (30, 38, 46))
            if not all(isfinite(value) for value in xyz):
                raise ValueError("Reduce2 model contains non-finite coordinates")
            rows.append({"key": atom_key(line) + (line[16:17].strip(), element),
                         "element": element, "xyz": xyz})
    return rows


def atoms(path: Path):
    return [row["key"] for row in atom_records(path) if row["element"] not in {"H", "D"}]


def coordinate_frame_audit(before: Path, after: Path) -> dict:
    """Check fixed backbone anchors without fitting away a translation/rotation.

    Reduce2 may optimize side chains. It must not move the coordinate frame used
    by pockets and deposited-ligand evidence. For non-protein-only inputs use
    all matching heavy atoms instead of accepting an empty anchor set.
    """
    original = {row["key"]: row for row in atom_records(before) if row["element"] not in {"H", "D"}}
    reduced = {row["key"]: row for row in atom_records(after) if row["element"] not in {"H", "D"}}
    shared = original.keys() & reduced.keys()
    anchors = [key for key in shared if key[4] in {"N", "CA", "C", "O"}]
    mode = "protein_backbone" if anchors else "all_shared_heavy_atoms"
    if not anchors:
        anchors = list(shared)
    maximum = max((dist(original[key]["xyz"], reduced[key]["xyz"]) for key in anchors), default=None)
    return {"status": "preserved" if maximum is not None and maximum <= 0.01 else "changed",
            "anchor_kind": mode, "anchor_count": len(anchors),
            "maximum_anchor_displacement_angstrom": maximum, "tolerance_angstrom": 0.01,
            "alignment_applied": False}


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
    args.output_pdb.parent.mkdir(parents=True, exist_ok=True)
    args.audit_json.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
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
    with tempfile.TemporaryDirectory(prefix="docking-universal-reduce2-") as directory:
        work = Path(directory) / args.input_pdb.name
        shutil.copyfile(args.input_pdb, work)
        try:
            input_pdb = pdb_for_audit(work, Path(directory) / "audit-input.pdb")
            before = Counter(atoms(input_pdb))
            if not before:
                raise ValueError("Reduce2 input has no heavy atoms")
        except (ImportError, ValueError, RuntimeError) as error:
            args.audit_json.write_text(json.dumps({"tool": "CCTBX reduce2", "status": "incompatible",
                                                  "reason": str(error)}, indent=2) + "\n")
            args.log.write_text(f"Reduce2 input review failed: {error}\n")
            return 2
        env = dict(os.environ)
        env["MMTBX_CCP4_MONOMER_LIB"] = str(geostd)
        cmd = [str(__import__("sys").executable), str(reduce2), str(work), "approach=add", "add_flip_movers=True"]
        completed = subprocess.run(cmd, cwd=directory, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
        args.log.write_text(completed.stdout or "")
        suffix = work.suffix if work.suffix.lower() in {".cif", ".mmcif"} else ".pdb"
        candidates = sorted(Path(directory).glob(f"{work.stem}*H{suffix}"))
        if completed.returncode != 0 or len(candidates) != 1:
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
                "process_returncode": completed.returncode,
                "reason": ("Reduce2 process failed" if completed.returncode else
                           "Reduce2 output missing" if not candidates else "Reduce2 output ambiguous"),
                "output_candidates": [path.name for path in candidates],
                **geostd_provenance(geostd),
            }, indent=2) + "\n")
            return completed.returncode or 1
        native_output = candidates[0]
        try:
            reduced = pdb_for_audit(native_output, Path(directory) / "audit-output.pdb")
            after = Counter(atoms(reduced))
            frame = coordinate_frame_audit(input_pdb, reduced)
        except (ImportError, ValueError, RuntimeError) as error:
            args.audit_json.write_text(json.dumps({"tool": "CCTBX reduce2", "status": "incompatible",
                                                  "reason": str(error), "native_output_name": native_output.name}, indent=2) + "\n")
            return 2
        missing = list((before - after).elements())
        unexpected = list((after - before).elements())
        backbone_conflicts = backbone_nitrogen_hydrogen_conflicts(reduced)
        incompatible = bool(missing or unexpected or backbone_conflicts or frame["status"] != "preserved")
        record = {
            "tool": "CCTBX reduce2",
            "status": "incompatible" if incompatible else "compatible",
            "native_output_name": native_output.name,
            "command": " ".join(cmd), "input": str(args.input_pdb.resolve()),
            "component_library": str(geostd.resolve()),
            **geostd_provenance(geostd),
            "output": str(args.output_pdb.resolve()), "input_heavy_atom_count": sum(before.values()),
            "output_heavy_atom_count": sum(after.values()), "missing_input_heavy_atoms": [list(x) for x in missing],
            "unexpected_output_heavy_atoms": [list(x) for x in unexpected],
            "coordinate_frame": frame,
            "backbone_nitrogen_hydrogen_conflicts": backbone_conflicts,
            "added_hydrogen_count": sum(row["element"] in {"H", "D"} for row in atom_records(reduced))
                                    - sum(row["element"] in {"H", "D"} for row in atom_records(input_pdb)),
        }
        if native_output != reduced and not incompatible:
            retained_native = args.output_pdb.with_suffix(".cif")
            shutil.copyfile(native_output, retained_native)
            record["native_output"] = str(retained_native.resolve())
        args.audit_json.write_text(json.dumps(record, indent=2) + "\n")
        if incompatible:
            return 2
        shutil.copyfile(reduced, args.output_pdb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
