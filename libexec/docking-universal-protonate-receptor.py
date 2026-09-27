#!/usr/bin/env python3
"""Run PDB2PQR/PROPKA and audit that it did not change receptor chemistry.

PDB2PQR is useful for pH-aware hydrogen placement, but it can legally return
success while omitting unsupported modified residues.  This wrapper therefore
publishes a machine-readable audit and exits non-zero when any input heavy atom
is absent from the proposed model.  Meeko must never receive an unchecked model.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path


def _atom_key(line: str) -> tuple[str, str, str, str, str, str]:
    record = line[0:6].strip()
    atom = line[12:16].strip()
    res = line[17:20].strip()
    chain = line[21:22].strip()
    seq = line[22:26].strip()
    icode = line[26:27].strip()
    return chain, seq, icode, res, atom, record


def _atoms(path: Path) -> list[tuple[str, str, str, str, str, str]]:
    rows = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        element = line[76:78].strip().upper()
        if element == "H" or line[12:16].strip().upper().startswith("H"):
            continue
        rows.append(_atom_key(line))
    return rows


def _states(path: Path) -> list[dict[str, str]]:
    states = []
    for line in path.read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        res = line[17:20].strip().upper()
        if res not in {"ASH", "GLH", "HID", "HIE", "HIP", "LYN", "CYM", "TYM"}:
            continue
        states.append({"chain": line[21:22].strip(), "residue": line[22:26].strip(), "icode": line[26:27].strip(), "state": res})
    unique = sorted({tuple(sorted(item.items())) for item in states})
    return [dict(item) for item in unique]


def audit(input_pdb: Path, output_pdb: Path, *, ph: float, command: str, log: Path) -> dict:
    before = Counter(_atoms(input_pdb))
    after = Counter(_atoms(output_pdb)) if output_pdb.is_file() else Counter()
    missing = list((before - after).elements())
    added = list((after - before).elements())
    warnings = [line for line in log.read_text(errors="replace").splitlines()
                if ("unable to find" in line.lower() or "ignored" in line.lower())
                and "header lines in output" not in line.lower()]
    status = "incompatible" if missing else ("review_required" if warnings else "compatible")
    return {
        "tool": "PDB2PQR",
        "command": command,
        "pH": ph,
        "input": str(input_pdb.resolve()),
        "output": str(output_pdb.resolve()),
        "status": status,
        "input_heavy_atom_count": sum(before.values()),
        "output_heavy_atom_count": sum(after.values()),
        "missing_input_heavy_atoms": [list(row) for row in missing],
        "added_heavy_atoms": [list(row) for row in added],
        "assigned_states": _states(output_pdb) if output_pdb.is_file() else [],
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_pdb", type=Path)
    parser.add_argument("output_pdb", type=Path)
    parser.add_argument("output_pqr", type=Path)
    parser.add_argument("audit_json", type=Path)
    parser.add_argument("log", type=Path)
    parser.add_argument("--ph", type=float, default=7.4)
    parser.add_argument("--command", default=os.environ.get("PDB2PQR_COMMAND", ""))
    args = parser.parse_args(argv)
    command = args.command or shutil.which("pdb2pqr30") or shutil.which("pdb2pqr")
    if not command:
        args.log.write_text("PDB2PQR command not found\n")
        args.audit_json.write_text(json.dumps({"tool": "PDB2PQR", "status": "unavailable", "pH": args.ph}, indent=2) + "\n")
        return 3
    args.output_pdb.parent.mkdir(parents=True, exist_ok=True)
    args.output_pqr.parent.mkdir(parents=True, exist_ok=True)
    args.log.parent.mkdir(parents=True, exist_ok=True)
    cmd = [command, "--ff=AMBER", "--ffout=AMBER", "--keep-chain", "--drop-water", "--titration-state-method=propka", "--with-ph", str(args.ph), "--pdb-output", str(args.output_pdb), str(args.input_pdb), str(args.output_pqr)]
    completed = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    args.log.write_text(completed.stdout or "")
    if completed.returncode != 0:
        args.audit_json.write_text(json.dumps({"tool": "PDB2PQR", "status": "failed", "pH": args.ph, "command": " ".join(cmd)}, indent=2) + "\n")
        return completed.returncode or 1
    record = audit(args.input_pdb, args.output_pdb, ph=args.ph, command=" ".join(cmd), log=args.log)
    args.audit_json.write_text(json.dumps(record, indent=2) + "\n")
    return 2 if record["status"] == "incompatible" else 0


if __name__ == "__main__":
    raise SystemExit(main())
