#!/usr/bin/env python3
"""Run local PLIP and the approved renderer for one retained docking pose."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

APPROVED_POLICY = "approved-poseedit-local-v1"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--pose-id", type=int, required=True)
    parser.add_argument("--cluster-id", type=int, required=True)
    parser.add_argument("--score", type=float, required=True)
    parser.add_argument("--renderer-policy", required=True)
    parser.add_argument("--plip-command", default=os.environ.get("DOCKING_UNIVERSAL_PLIP", "plip"))
    parser.add_argument("--renderer", type=Path)
    args = parser.parse_args()
    if args.renderer_policy != APPROVED_POLICY:
        raise ValueError(f"Unsupported interaction renderer policy: {args.renderer_policy}")
    cache = args.cache.expanduser().resolve()
    pose, complex_pdb = cache / "pose.sdf", cache / "complex.pdb"
    receptor = cache.parent.parent / "receptor.pdb"
    missing = [str(path) for path in (pose, complex_pdb, receptor) if not path.is_file()]
    if missing:
        raise FileNotFoundError("Retained exact-pose input is missing: " + ", ".join(missing))
    script_root = Path(__file__).resolve().parent
    interactions = script_root / "docking-universal-interactions.py"
    renderer = args.renderer.expanduser().resolve() if args.renderer else script_root / "docking-universal-render-poseedit.py"
    if not renderer.is_file():
        raise FileNotFoundError(f"Approved local PoseEdit-style renderer is not installed: {renderer}")
    plip = cache / "plip"
    subprocess.run([
        sys.executable, str(interactions), str(complex_pdb), "--out-dir", str(plip),
        "--ligand-resname", "UNL", "--ligand-chain", "Z", "--ligand-position", "1",
        "--typed-ligand-sdf", str(pose), "--plip-command", args.plip_command,
        "--skip-native-visuals",
    ], check=True)
    diagram = cache / "interaction_diagram.png"
    subprocess.run([
        sys.executable, str(renderer), "--ligand", str(pose), "--receptor", str(receptor),
        "--plip-xml", str(plip / "report.xml"), "--output", str(diagram),
        "--scale", "3", "--renderer-policy", APPROVED_POLICY,
    ], check=True)
    renderer_manifest = diagram.with_suffix(".manifest.json")
    if not diagram.is_file() or not renderer_manifest.is_file():
        raise FileNotFoundError("Approved renderer omitted its diagram or provenance manifest")
    if json.loads(renderer_manifest.read_text()).get("renderer_policy") != APPROVED_POLICY:
        raise ValueError("Approved renderer returned a mismatched policy")
    (cache / "interaction_manifest.json").write_text(json.dumps({
        "schema_name": "docking-universal-pose-interaction-result", "schema_version": 1,
        "pose_id": args.pose_id, "cluster_id": args.cluster_id,
        "score_kcal_per_mol": args.score, "renderer_policy": APPROVED_POLICY,
        "network_used": False, "ligand": str(pose), "receptor": str(receptor),
        "plip_xml": str((plip / "report.xml").resolve()), "diagram": str(diagram),
    }, indent=2) + "\n")
    print(json.dumps({"pose_id": args.pose_id, "diagram": str(diagram)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
