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
from pathlib import Path


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
    # Source-tree installs keep the open-source monomer library beside the
    # python-conversion checkout. This avoids requiring a shell export for the
    # normal repository layout while still allowing packaged installations to
    # provide an explicit path.
    here = Path(__file__).resolve()
    candidates.append(str(here.parents[2] / "third_party" / "geostd"))
    prefix = os.environ.get("CONDA_PREFIX")
    if prefix:
        candidates.extend([str(Path(prefix) / "share" / "geostd"), str(Path(prefix) / "geostd")])
    for candidate in candidates:
        if candidate and Path(candidate).is_dir():
            return Path(candidate)
    return None


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
            args.audit_json.write_text(json.dumps({"tool": "CCTBX reduce2", "status": "failed", "command": " ".join(cmd)}, indent=2) + "\n")
            return completed.returncode or 1
        reduced = candidates[0]
        after = Counter(atoms(reduced))
        missing = list((before - after).elements())
        record = {
            "tool": "CCTBX reduce2", "status": "incompatible" if missing else "compatible",
            "command": " ".join(cmd), "input": str(args.input_pdb.resolve()),
            "output": str(args.output_pdb.resolve()), "input_heavy_atom_count": sum(before.values()),
            "output_heavy_atom_count": sum(after.values()), "missing_input_heavy_atoms": [list(x) for x in missing],
            "added_hydrogen_count": sum(1 for line in reduced.read_text(errors="replace").splitlines() if line.startswith(("ATOM  ", "HETATM")) and (line[76:78].strip().upper() == "H" or line[12:16].strip().upper().startswith("H"))),
        }
        args.audit_json.write_text(json.dumps(record, indent=2) + "\n")
        if missing:
            return 2
        shutil.copyfile(reduced, args.output_pdb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
