#!/usr/bin/env python3
"""Evaluate native mmCIF tool paths without changing the production workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from docking_universal.services.mmcif_preparation_evaluation import (
    compare_structure_paths,
    detect_native_mmcif_capabilities,
    meeko_native_mmcif_command,
    pdbfixer_native_command,
    run_command,
    write_capabilities,
)
from docking_universal.services.structure_input import normalize_structure_input


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_cif", type=Path)
    parser.add_argument("output_directory", type=Path)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--pdbfixer-helper", type=Path, required=True)
    parser.add_argument("--meeko", type=Path, required=True)
    args = parser.parse_args()
    if args.source_cif.suffix.lower() not in {".cif", ".mmcif"}:
        parser.error("source_cif must be a .cif or .mmcif file")
    output = args.output_directory.resolve()
    output.mkdir(parents=True, exist_ok=True)
    capabilities = detect_native_mmcif_capabilities(args.python, args.meeko)
    write_capabilities(output / "capabilities.json", capabilities)

    compatibility = normalize_structure_input(args.source_cif, output / "compatibility")
    structures = {"compatibility_conversion": compatibility.engine_pdb_path}
    routes = {
        "compatibility_conversion": {
            "status": "completed",
            "output": str(compatibility.engine_pdb_path),
        }
    }
    if capabilities.pdbfixer:
        native_pdb = output / "pdbfixer-native.pdb"
        command = pdbfixer_native_command(
            args.python, args.pdbfixer_helper, args.source_cif,
            native_pdb, output / "pdbfixer-native-audit.json",
        )
        result = run_command(command, output / "pdbfixer-native.log")
        if result.returncode == 0 and native_pdb.is_file():
            structures["pdbfixer_native_mmcif"] = native_pdb
        routes["pdbfixer_native_mmcif"] = {
            "status": "completed" if result.returncode == 0 and native_pdb.is_file() else "failed",
            "return_code": result.returncode,
            "output": str(native_pdb) if native_pdb.is_file() else None,
            "log": str(output / "pdbfixer-native.log"),
        }
    else:
        routes["pdbfixer_native_mmcif"] = {"status": "unavailable"}
    if capabilities.direct_meeko_mmcif:
        native_pdbqt = output / "meeko-native.pdbqt"
        command = meeko_native_mmcif_command(
            args.meeko, args.source_cif, output / "meeko-native", native_pdbqt
        )
        result = run_command(command, output / "meeko-native.log")
        routes["meeko_native_mmcif"] = {
            "status": "completed" if result.returncode == 0 and native_pdbqt.is_file() else "failed",
            "return_code": result.returncode,
            "output": str(native_pdbqt) if native_pdbqt.is_file() else None,
            "log": str(output / "meeko-native.log"),
        }
    else:
        routes["meeko_native_mmcif"] = {"status": "unavailable"}
    comparison = compare_structure_paths(structures)
    comparison["routes"] = routes
    (output / "comparison.json").write_text(json.dumps(comparison, indent=2) + "\n")
    print(output / "comparison.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
