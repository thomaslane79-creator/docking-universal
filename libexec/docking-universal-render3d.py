#!/usr/bin/env python
"""Render an existing PyMOL scene or coordinate file without opening a GUI.

This visualization stage writes PNG and optional PSE files from existing data;
it performs no docking or scientific parameter selection.
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def main():
    """Render an existing scene or coordinate file reproducibly with PyMOL."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Existing .pml, .pse, .pdb, .pdbqt, .mol2, or .sdf file")
    parser.add_argument("--out", type=Path, help="PNG output path")
    parser.add_argument("--width", type=int, default=1800)
    parser.add_argument("--height", type=int, default=1400)
    parser.add_argument("--dpi", type=int, default=200)
    parser.add_argument("--pymol", default="pymol", help="PyMOL executable")
    parser.add_argument("--transparent", action="store_true", help="Use a transparent background")
    parser.add_argument("--session-out", type=Path, help="Also save a self-contained PyMOL .pse session")
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    if not source.is_file():
        parser.error(f"input does not exist: {source}")
    executable = shutil.which(args.pymol) if Path(args.pymol).name == args.pymol else args.pymol
    if not executable or not Path(executable).exists():
        parser.error(f"PyMOL executable not found: {args.pymol}")

    output = (args.out or source.with_suffix(".png")).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    session_output = args.session_out.expanduser().resolve() if args.session_out else None
    if session_output:
        if session_output.suffix.lower() != ".pse":
            parser.error("--session-out must end in .pse")
        session_output.parent.mkdir(parents=True, exist_ok=True)
    suffix = source.suffix.lower()

    commands = ["cmd.reinitialize()"]
    if suffix == ".pml":
        # Execute the scene synchronously before the render commands. Passing a
        # PML as a positional PyMOL input alongside `-r` can run the Python
        # render driver first, producing a valid but blank PNG.
        commands.append(f"cmd.do({('@' + str(source))!r})")
    elif suffix == ".pse":
        commands.append(f"cmd.load({str(source)!r})")
    else:
        commands.extend([
            f"cmd.load({str(source)!r}, 'structure')",
            "cmd.hide('everything', 'all')",
            "cmd.show('cartoon', 'structure and polymer.protein')",
            "cmd.color('slate', 'structure and polymer.protein')",
            "cmd.show('sticks', 'structure and organic')",
            "cmd.util.cbag('structure and organic')",
            "cmd.show('spheres', 'structure and inorganic')",
            "cmd.set('sphere_scale', 0.35, 'structure and inorganic')",
            "cmd.orient('structure')",
            "cmd.zoom('structure', 4)",
        ])
    commands.extend([
        "cmd.bg_color('white')",
        "cmd.set('antialias', 2)",
        "cmd.set('ray_shadows', 0)",
        f"cmd.set('ray_opaque_background', {0 if args.transparent else 1})",
        f"cmd.viewport({args.width}, {args.height})",
        f"cmd.png({str(output)!r}, width={args.width}, height={args.height}, dpi={args.dpi}, ray=1)",
        *([f"cmd.save({str(session_output)!r})"] if session_output else []),
        "cmd.quit()",
    ])

    with tempfile.TemporaryDirectory(prefix="docking-universal-pymol-") as tmp:
        driver = Path(tmp) / "render.py"
        driver.write_text("from pymol import cmd\n" + "\n".join(commands) + "\n")
        result = subprocess.run([str(executable), "-cq", "-r", str(driver)], text=True, capture_output=True)
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        detail = result.stderr.strip() or result.stdout.strip() or "PyMOL did not create the PNG"
        raise SystemExit(f"Render failed: {detail}")
    if session_output and (not session_output.is_file() or session_output.stat().st_size == 0):
        raise SystemExit(f"Render completed but PyMOL did not create the requested session: {session_output}")
    print(f"Rendered {output}")
    if session_output:
        print(f"Saved session {session_output}")


if __name__ == "__main__":
    main()
