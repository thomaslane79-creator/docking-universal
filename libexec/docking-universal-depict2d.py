#!/usr/bin/env python
"""Create generic 2D molecular depictions from existing coordinate files.

These images communicate connectivity only; they neither place a ligand in a
pocket nor represent docking or PLIP interaction results.
"""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def rdkit_molecule(path: Path):
    from rdkit import Chem

    suffix = path.suffix.lower()
    if suffix == ".sdf":
        return next((mol for mol in Chem.SDMolSupplier(str(path), removeHs=False) if mol), None)
    if suffix in {".mol", ".mdl"}:
        return Chem.MolFromMolFile(str(path), removeHs=False)
    if suffix == ".mol2":
        return Chem.MolFromMol2File(str(path), removeHs=False)
    if suffix == ".pdb":
        return Chem.MolFromPDBFile(str(path), removeHs=False)
    return None


def draw_with_rdkit(source: Path, output: Path, width: int, height: int, legend: str):
    """Read supported coordinates, generate 2D geometry, and draw with RDKit."""
    from rdkit import Chem
    from rdkit.Chem import AllChem, Draw

    molecule = rdkit_molecule(source)
    converted = None
    if molecule is None and shutil.which("obabel"):
        converted = tempfile.NamedTemporaryFile(suffix=".sdf", delete=False)
        converted.close()
        with tempfile.TemporaryDirectory(prefix="docking-universal-2d-") as tmp:
            safe_source = Path(tmp) / f"input{source.suffix.lower()}"
            shutil.copy2(source, safe_source)
            result = subprocess.run(["obabel", str(safe_source), "-O", converted.name], capture_output=True, text=True)
            if result.returncode == 0:
                molecule = next((mol for mol in Chem.SDMolSupplier(converted.name, removeHs=False) if mol), None)
    if molecule is None:
        raise ValueError("coordinate file could not be parsed; install Open Babel for format conversion")

    molecule = Chem.RemoveHs(molecule)
    AllChem.Compute2DCoords(molecule)
    if output.suffix.lower() == ".svg":
        drawer = Draw.MolDraw2DSVG(width, height)
        drawer.DrawMolecule(molecule, legend=legend)
        drawer.FinishDrawing()
        output.write_text(drawer.GetDrawingText())
    else:
        image = Draw.MolToImage(molecule, size=(width, height), legend=legend)
        image.save(output)
    if converted:
        Path(converted.name).unlink(missing_ok=True)


def draw_with_obabel(source: Path, output: Path):
    executable = shutil.which("obabel")
    if not executable:
        raise RuntimeError("neither RDKit nor Open Babel is available")
    with tempfile.TemporaryDirectory(prefix="docking-universal-2d-") as tmp:
        safe_source = Path(tmp) / f"input{source.suffix.lower()}"
        safe_output = Path(tmp) / f"output{output.suffix.lower()}"
        shutil.copy2(source, safe_source)
        result = subprocess.run([executable, str(safe_source), "-O", str(safe_output), "--gen2d"], text=True, capture_output=True)
        if result.returncode != 0 or not safe_output.is_file() or safe_output.stat().st_size == 0:
            raise RuntimeError(result.stderr.strip() or "Open Babel did not create the depiction")
        shutil.copy2(safe_output, output)


def main():
    """Create generic 2D depictions with RDKit and an Open Babel fallback."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="Existing PDB, PDBQT, SDF, MOL, or MOL2 files")
    parser.add_argument("--out-dir", type=Path, default=Path("2d_depictions"))
    parser.add_argument("--format", choices=["png", "svg"], default="png")
    parser.add_argument("--width", type=int, default=900)
    parser.add_argument("--height", type=int, default=700)
    parser.add_argument("--legend", choices=["filename", "none"], default="filename")
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    try:
        __import__("rdkit")
        backend = "rdkit"
    except ImportError:
        backend = "obabel"

    for item in args.inputs:
        source = item.expanduser().resolve()
        if not source.is_file():
            parser.error(f"input does not exist: {source}")
        output = args.out_dir / f"{source.stem}.{args.format}"
        legend = source.stem if args.legend == "filename" else ""
        try:
            if backend == "rdkit":
                draw_with_rdkit(source, output, args.width, args.height, legend)
            else:
                draw_with_obabel(source, output)
        except (OSError, RuntimeError, ValueError) as exc:
            raise SystemExit(f"Could not depict {source.name}: {exc}") from exc
        print(f"Depicted {output}")


if __name__ == "__main__":
    main()
