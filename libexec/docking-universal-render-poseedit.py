#!/usr/bin/env python3
"""Render the approved local PoseEdit-style PLIP interaction diagram."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

POLICY = "approved-poseedit-local-v1"


def command(*values, env=None):
    subprocess.run(tuple(map(str, values)), check=True, env=env)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ligand", type=Path, required=True)
    parser.add_argument("--receptor", type=Path, required=True)
    parser.add_argument("--plip-xml", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--scale", type=int, choices=(1, 2, 3, 4), default=3)
    parser.add_argument("--renderer-policy", default=POLICY)
    parser.add_argument("--ligand-id", default="UNL")
    parser.add_argument("--node", default=os.environ.get("DOCKING_UNIVERSAL_NODE", "node"))
    parser.add_argument("--chrome", default=os.environ.get("DOCKING_UNIVERSAL_CHROME"))
    args = parser.parse_args()
    if args.renderer_policy != POLICY:
        raise ValueError(f"Unsupported renderer policy: {args.renderer_policy}")
    for path in (args.ligand, args.receptor, args.plip_xml):
        if not path.is_file():
            raise FileNotFoundError(path)
    node = shutil.which(args.node) or (Path(args.node) if Path(args.node).is_file() else None)
    if not node:
        raise FileNotFoundError("Node.js is required for the approved local renderer")
    chrome_candidates = [args.chrome, shutil.which("google-chrome"), shutil.which("chromium"),
                         "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"]
    chrome = next((Path(item) for item in chrome_candidates if item and Path(item).is_file()), None)
    if chrome is None:
        raise FileNotFoundError("A local Chromium/Chrome executable is required for rendering")
    root = Path(__file__).resolve().parent / "docking_universal" / "poseedit_renderer"
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="du-poseedit-") as temporary:
        work = Path(temporary)
        command(sys.executable, root / "ligand_scene.py", args.ligand, "--output", work / "actual-pose-base.json")
        command(sys.executable, root / "plip_scene.py", "--report", args.plip_xml,
                "--ligand", args.ligand, "--receptor", args.receptor,
                "--output-root", work, "--ligand-id", args.ligand_id.split(":", 1)[0])
        command(sys.executable, root / "boundary_scene.py", "--output-root", work)
        command(node, root / "build_page.mjs", work, root / "assets")
        environment = os.environ.copy()
        environment["CHROME_PATH"] = str(chrome)
        environment["RENDER_SCALE"] = str(args.scale)
        command(node, root / "render.cjs", work, output, env=environment)
    collision = json.loads(Path(str(output) + ".collision-audit.json").read_text())
    packing = json.loads(Path(str(output) + ".packing-audit.json").read_text())
    crop = json.loads(Path(str(output) + ".crop-audit.json").read_text())
    failures = [item for item in packing.get("labels", []) if
                item.get("remainingGeometryHits", 0) or item.get("ambiguous") or item.get("contourGap", 0) > 12]
    if collision.get("overlapCount") or failures:
        output.unlink(missing_ok=True)
        raise RuntimeError("Approved renderer could not produce a collision-free unambiguous layout")
    manifest = {
        "schema_name": "docking-universal-poseedit-render", "schema_version": 1,
        "renderer_policy": POLICY, "network_used": False, "scale": args.scale,
        "ligand": str(args.ligand.resolve()), "receptor": str(args.receptor.resolve()),
        "plip_xml": str(args.plip_xml.resolve()), "collision_count": 0,
        "layout_failure_count": 0, "crop": crop,
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
