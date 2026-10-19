"""Validate UTF-8 argument transport against unchanged direct P2Rank predictions.

Public fixtures and generated prediction files stay local. Only equality/status
metadata belongs in exported summaries; this is not a pocket-accuracy benchmark.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def validate_transport(p2rank, java, source, out):
    from docking_universal.p2rank_runtime import JAVA_ARGUMENT_SOURCE, java_invocation
    out.mkdir(parents=True, exist_ok=False)
    if not str(out).isascii() or not str(p2rank).isascii():
        raise ValueError("The direct baseline requires ASCII fixture/runtime paths")
    bridge = p2rank / "docking-universal-launcher"
    if not (bridge / "NativeArguments.class").is_file():
        bridge.mkdir(exist_ok=True)
        source_file = bridge / "NativeArguments.java"
        source_file.write_text(JAVA_ARGUMENT_SOURCE, encoding="utf-8")
        javac = java.with_name("javac.exe" if java.suffix == ".exe" else "javac")
        subprocess.run([str(javac), "-encoding", "UTF-8", "-d", str(bridge), str(source_file)], check=True)
    tables = []
    for name, transport in (("ascii-baseline", False), ("Unicode Ω 蛋白", True)):
        folder = out / name; folder.mkdir()
        receptor = folder / "2R8N.pdb"
        shutil.copyfile(source, receptor)
        result = folder / "prediction"
        command, environment = java_invocation(p2rank, java,
            ["predict", "-f", str(receptor), "-c", "default", "-visualizations", "0", "-o", str(result)], windows=transport)
        with (folder / "runtime.local.log").open("w", encoding="utf-8") as log:
            subprocess.run(command, env=environment, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=180)
        files = sorted([*result.glob("*_predictions.csv"), *result.glob("*_residues.csv")])
        if len(files) != 2:
            raise ValueError("P2Rank argument transport test did not produce both tables")
        tables.append({path.name: path.read_bytes() for path in files})
    if tables[0] != tables[1]:
        raise ValueError("UTF-8 argument transport changed direct P2Rank prediction/residue tables")
    return {"exact_prediction_and_residue_table_equality": True, "table_count": 2,
            "unicode_paths_exercised": True, "same_main_class_and_primary_model": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--p2rank", required=True, type=Path)
    parser.add_argument("--java", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT / "libexec"))
    print(json.dumps(validate_transport(args.p2rank, args.java,
        ROOT / "examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb", args.out)))
