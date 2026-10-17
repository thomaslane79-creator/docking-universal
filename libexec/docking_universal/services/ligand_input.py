"""Shared ligand-source policy for GUI planning and scientific import."""

from pathlib import Path


from .ligand_table import TABLE_SUFFIXES

LIGAND_SUFFIXES = {".sdf", ".mol"} | TABLE_SUFFIXES


def ligand_input_files(source):
    path = Path(source).expanduser().resolve()
    if path.is_dir():
        files = sorted(item for item in path.iterdir()
                       if item.is_file() and item.suffix.lower() in {'.sdf', '.mol'})
    elif path.is_file() and path.suffix.lower() in LIGAND_SUFFIXES:
        files = [path]
    else:
        raise FileNotFoundError(f"Ligand source must be an SDF or MOL file, CSV/TSV/XLSX table, or SDF/MOL directory: {path}")
    if not files:
        raise ValueError(f"No readable SDF or MOL input files found at {path}")
    return files


def read_ligand_molecules(source):
    """Keep coordinates, hydrogens and stereo; normal preparation happens later."""
    from rdkit import Chem

    path = Path(source)
    if path.suffix.lower() in TABLE_SUFFIXES:
        raise ValueError('Tabular SMILES requires approved columns and a reviewed compound selection; use Read/select compounds or --ligand-selection')
    if path.suffix.lower() not in LIGAND_SUFFIXES:
        raise ValueError(f"Ligand input must be an SDF or MOL file: {path}")
    try:
        records = list(Chem.SDMolSupplier(str(path), removeHs=False))
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"Unable to read ligand input {path}: {exc}") from None
    if path.suffix.lower() == ".mol" and (len(records) != 1 or records[0] is None):
        raise ValueError(f"MOL input must contain exactly one readable molecule: {path}; use SDF for a multi-molecule library")
    return [molecule for molecule in records if molecule is not None]
