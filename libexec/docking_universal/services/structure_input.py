"""Retain modern coordinate input while deriving legacy engine inputs explicitly."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


SUPPORTED_STRUCTURE_SUFFIXES = {".pdb", ".cif", ".mmcif"}


@dataclass(frozen=True)
class NormalizedStructureInput:
    source_path: Path
    engine_pdb_path: Path
    source_format: str
    source_sha256: str
    derived_for_legacy_engine: bool
    metadata_path: Path
    assemblies: tuple[dict[str, Any], ...] = ()

    def record(self) -> dict[str, Any]:
        value = asdict(self)
        value["source_path"] = str(self.source_path)
        value["engine_pdb_path"] = str(self.engine_pdb_path)
        value["metadata_path"] = str(self.metadata_path)
        value["assemblies"] = list(self.assemblies)
        return value


def normalize_structure_input(path: Path | str, destination: Path | str) -> NormalizedStructureInput:
    """Validate a PDB/mmCIF input and create a PDB only when an engine needs it."""
    source = Path(path).expanduser().resolve()
    if not source.is_file() or source.suffix.lower() not in SUPPORTED_STRUCTURE_SUFFIXES:
        raise FileNotFoundError(f"Structure input must be an existing PDB or mmCIF file: {source}")
    directory = Path(destination).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    digest = _sha256(source)
    source_format = "mmcif" if source.suffix.lower() in {".cif", ".mmcif"} else "pdb"
    assemblies: tuple[dict[str, Any], ...] = ()
    if source_format == "mmcif":
        try:
            import gemmi
        except ImportError as exc:
            raise RuntimeError(
                "mmCIF input requires gemmi in the scientific host environment"
            ) from exc
        structure = gemmi.read_structure(str(source))
        if not structure or not any(model for model in structure):
            raise ValueError(f"mmCIF file contains no coordinate models: {source}")
        # Keep the basename stable: the legacy engine derives its run directory
        # from it. Hash isolation belongs in the parent directory.
        directory = directory / digest
        directory.mkdir(parents=True, exist_ok=True)
        retained = directory / source.name
        if retained != source:
            shutil.copy2(source, retained)
        source = retained
        if len(structure) != 1:
            raise ValueError("Select one coordinate model before preparing this mmCIF structure")
        for chain in structure[0]:
            if len(chain.name) > 1:
                raise ValueError("This structure requires an explicit chain mapping for legacy PDB tools")
            for residue in chain:
                if len(residue.name) > 3 or not -999 <= residue.seqid.num <= 9999:
                    raise ValueError("Residue identity cannot be represented losslessly by the legacy PDB tools")
        if sum(1 for chain in structure[0] for residue in chain for atom in residue) > 99999:
            raise ValueError("This structure exceeds the legacy engine atom limit")
        engine_pdb = directory / f"{source.stem}.pdb"
        structure.write_pdb(str(engine_pdb))
        assemblies = _read_mmcif_assemblies(source)
        derived = True
    else:
        if not any(
            line.startswith(("ATOM  ", "HETATM"))
            for line in source.read_text(errors="replace").splitlines()
        ):
            raise ValueError(f"PDB file contains no coordinate records: {source}")
        engine_pdb = source
        derived = False
    metadata_path = directory / f"{source.stem}-{digest[:12]}-structure-input.json"
    record = {
        "schema_name": "docking-universal-structure-input",
        "schema_version": 1,
        "source_path": str(source),
        "source_format": source_format,
        "source_sha256": digest,
        "engine_pdb_path": str(engine_pdb),
        "derived_for_legacy_engine": derived,
        "assemblies": list(assemblies),
        "deposited_metadata": _deposited_metadata(source) if source_format == "mmcif" else {},
        "interpretation_limit": (
            "Assembly annotations and ligand placement are deposited evidence; they do not "
            "establish why a ligand is absent from another structural copy."
        ),
    }
    metadata_path.write_text(json.dumps(record, indent=2) + "\n")
    return NormalizedStructureInput(
        source, engine_pdb, source_format, digest, derived, metadata_path, assemblies
    )


def _deposited_metadata(source: Path) -> dict[str, Any]:
    import gemmi
    block = gemmi.cif.read_file(str(source)).sole_block()
    # Preserve the deposited vocabulary and identity relationships verbatim.
    categories = (
        "entity", "entity_poly", "struct_asym", "pdbx_entity_nonpoly",
        "chem_comp", "pdbx_nonpoly_scheme", "pdbx_struct_oper_list",
        "struct_conn", "pdbx_struct_mod_residue", "struct_site",
        "struct_site_gen", "exptl", "exptl_crystal_grow", "refine",
        "em_3d_reconstruction",
    )
    evidence = {name: block.get_mmcif_category("_" + name + ".") for name in categories}
    atoms = block.get_mmcif_category("_atom_site.")
    label_chains = atoms.get("label_asym_id", [])
    author_chains = atoms.get("auth_asym_id", [])
    evidence["chain_identifier_map"] = [
        {"label_chain": label, "author_chain": author}
        for label, author in sorted(set(zip(label_chains, author_chains)))
    ]
    fields = ("id", "label_asym_id", "auth_asym_id", "label_entity_id",
              "label_comp_id", "auth_seq_id", "pdbx_PDB_ins_code",
              "label_atom_id", "label_alt_id", "occupancy", "B_iso_or_equiv",
              "pdbx_PDB_model_num")
    evidence["deposited_hetero_atoms"] = [
        {field: atoms[field][index] for field in fields if field in atoms}
        for index, group in enumerate(atoms.get("group_PDB", []))
        if group == "HETATM"
    ]
    return evidence


def _read_mmcif_assemblies(path: Path) -> tuple[dict[str, Any], ...]:
    import gemmi

    block = gemmi.cif.read_file(str(path)).sole_block()
    ids = list(block.find_values("_pdbx_struct_assembly.id"))
    details = list(block.find_values("_pdbx_struct_assembly.details"))
    oligomers = list(block.find_values("_pdbx_struct_assembly.oligomeric_details"))
    counts = list(block.find_values("_pdbx_struct_assembly.oligomeric_count"))
    generated: dict[str, list[dict[str, str]]] = {}
    table = block.find([
        "_pdbx_struct_assembly_gen.assembly_id",
        "_pdbx_struct_assembly_gen.oper_expression",
        "_pdbx_struct_assembly_gen.asym_id_list",
    ])
    for row in table:
        generated.setdefault(str(row[0]), []).append({
            "operation_expression": str(row[1]),
            "asym_ids": str(row[2]),
        })
    result = []
    for index, assembly_id in enumerate(ids):
        result.append({
            "id": str(assembly_id),
            "details": _at(details, index),
            "oligomeric_details": _at(oligomers, index),
            "oligomeric_count": _at(counts, index),
            "generators": generated.get(str(assembly_id), []),
        })
    return tuple(result)


def _at(values: list[Any], index: int) -> str:
    if index >= len(values):
        return ""
    value = str(values[index])
    return "" if value in {"?", "."} else value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    result = normalize_structure_input(args.source, args.destination)
    print(result.source_path)
    print(result.metadata_path)
    print(result.engine_pdb_path)
