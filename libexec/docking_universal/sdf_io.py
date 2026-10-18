"""Unicode-safe RDKit file boundaries without changing molecular operations.

Pinned Windows RDKit uses narrow C++ filename APIs. Python-opened streams avoid
that limitation; the same supplier/writer chemistry options remain authoritative.
Unix retains the existing RDKit filename APIs unchanged.
"""
from __future__ import annotations

import os
from pathlib import Path

WINDOWS = os.name == "nt"


def read_sdf(path, **options):
    from rdkit import Chem
    if not WINDOWS:
        return Chem.SDMolSupplier(str(path), **options)

    def records():
        with Path(path).open("rb") as stream:
            yield from Chem.ForwardSDMolSupplier(stream, **options)
    return records()


class _StreamWriter:
    def __init__(self, path):
        from rdkit import Chem
        self.stream = Path(path).open("w", encoding="utf-8", newline="")
        try:
            self.writer = Chem.SDWriter(self.stream)
        except BaseException:
            self.stream.close()
            raise

    def __getattr__(self, name):
        return getattr(self.writer, name)

    def close(self):
        try:
            self.writer.close()
        finally:
            self.stream.close()

    def __enter__(self):
        return self

    def __exit__(self, *exception):
        self.close()


def sdf_writer(path):
    from rdkit import Chem
    return _StreamWriter(path) if WINDOWS else Chem.SDWriter(str(path))


def write_pdb(molecule, path):
    from rdkit import Chem
    if WINDOWS:
        Path(path).write_text(Chem.MolToPDBBlock(molecule), encoding="utf-8")
    else:
        Chem.MolToPDBFile(molecule, str(path))


def read_mol(path, **options):
    from rdkit import Chem
    return Chem.MolFromMolBlock(Path(path).read_text(encoding="utf-8"), **options) if WINDOWS else Chem.MolFromMolFile(str(path), **options)


def read_pdb(path, **options):
    from rdkit import Chem
    return Chem.MolFromPDBBlock(Path(path).read_text(encoding="utf-8"), **options) if WINDOWS else Chem.MolFromPDBFile(str(path), **options)
