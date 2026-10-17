"""Protein identity from the supplied coordinates only; never a network lookup."""

from __future__ import annotations

from pathlib import Path
from typing import Any


IDENTITY_CATEGORIES = (
    "entry", "struct", "entity", "entity_poly", "entity_src_gen",
    "entity_src_nat", "pdbx_entity_src_syn",
)


def _clean(value: Any) -> str:
    text = " ".join(str(value or "").split())
    return "" if text in {"?", ".", "None"} else text


def _rows(category):
    count = max((len(values) for values in category.values()), default=0)
    return [{key: _clean(values[i]) if i < len(values) else ""
             for key, values in category.items()} for i in range(count)]


def _unique(values):
    return list(dict.fromkeys(value for value in values if value))


def identity_from_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    polymers = {row["entity_id"]: row for row in _rows(metadata.get("entity_poly") or {})
                if row.get("type", "").lower().startswith("polypeptide")}
    sources: dict[str, list[dict]] = {}
    for category, species_key, host_key in (
        ("entity_src_gen", "pdbx_gene_src_scientific_name", "pdbx_host_org_scientific_name"),
        ("entity_src_nat", "pdbx_organism_scientific", ""),
        ("pdbx_entity_src_syn", "organism_scientific", ""),
    ):
        for row in _rows(metadata.get(category) or {}):
            sources.setdefault(row.get("entity_id", ""), []).append({
                "species": row.get(species_key, ""),
                "expression_host": row.get(host_key, "") if host_key else "",
            })
    proteins = []
    for row in _rows(metadata.get("entity") or {}):
        identifier = row.get("id", "")
        if identifier not in polymers:
            continue  # Non-protein polymers, water and ligands are not targets.
        source = sources.get(identifier, [])
        proteins.append({
            "entity_id": identifier,
            "name": row.get("pdbx_description", ""),
            "fragment": row.get("pdbx_fragment", ""),
            "mutations": row.get("pdbx_mutation", ""),
            "chains": _unique(part.strip() for part in polymers[identifier].get("pdbx_strand_id", "").split(",")),
            "source_species": _unique(item["species"] for item in source),
            "expression_hosts": _unique(item["expression_host"] for item in source),
        })
    entry = _rows(metadata.get("entry") or {})
    structure = _rows(metadata.get("struct") or {})
    return {
        "structure_id": (entry[0].get("id", "") if entry else ""),
        "structure_title": (structure[0].get("title", "") if structure else ""),
        "proteins": proteins,
        "basis": "deposited coordinate-file annotations",
    }


def _pdb_fields(lines, record):
    text = " ".join(line[10:80].strip() for line in lines if line.startswith(record))
    entities = {}
    current = None
    for field in text.split(";"):
        key, separator, value = field.partition(":")
        if not separator:
            continue
        key, value = key.strip(), _clean(value)
        if key == "MOL_ID":
            current = entities.setdefault(value, {})
        elif current is not None:
            current[key] = value
    return entities


def _pdb_identity(source):
    lines = source.read_text(errors="replace").splitlines()
    compounds, sources = _pdb_fields(lines, "COMPND"), _pdb_fields(lines, "SOURCE")
    proteins = []
    for identifier, compound in compounds.items():
        # PDB COMPND can include RNA/DNA. Require an actual amino-acid chain.
        chains = _unique(part.strip() for part in compound.get("CHAIN", "").split(","))
        atoms = [line for line in lines if line.startswith("ATOM  ")
                 and line[21:22].strip() in chains]
        amino_acids = {"ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS",
                       "ILE", "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP",
                       "TYR", "VAL", "MSE", "SEC", "PYL", "ASX", "GLX", "UNK"}
        if not any(line[17:20].strip() in amino_acids for line in atoms):
            continue
        organism = sources.get(identifier, {})
        proteins.append({
            "entity_id": identifier, "name": compound.get("MOLECULE", ""),
            "fragment": compound.get("FRAGMENT", ""), "mutations": compound.get("MUTATION", ""),
            "chains": chains,
            "source_species": _unique([organism.get("ORGANISM_SCIENTIFIC", "")]),
            "expression_hosts": _unique([organism.get("EXPRESSION_SYSTEM", "")]),
        })
    return {
        "structure_id": next((_clean(line[62:66]) for line in lines if line.startswith("HEADER")), ""),
        "structure_title": _clean(" ".join(line[10:80] for line in lines if line.startswith("TITLE "))),
        "proteins": proteins, "basis": "deposited coordinate-file annotations",
    }


def read_protein_identity(source: Path | str | None = None, *, evidence=None) -> dict[str, Any]:
    """Read exact local input; older metadata may lack source-organism categories."""
    retained = identity_from_metadata((evidence or {}).get("deposited_metadata") or {})
    path = Path(source) if source else None
    if path is not None and path.is_file():
        try:
            if path.suffix.lower() in {".cif", ".mmcif"}:
                import gemmi
                block = gemmi.cif.read_file(str(path)).sole_block()
                return identity_from_metadata({
                    name: block.get_mmcif_category("_" + name + ".") for name in IDENTITY_CATEGORIES
                })
            if path.suffix.lower() == ".pdb":
                return _pdb_identity(path)
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            retained["read_warning"] = f"Coordinate identity metadata could not be read: {exc}"
    return retained


def target_identity_text(identity: dict[str, Any], fallback: str) -> tuple[str, str]:
    """Plain text, escaped by the renderer; species remain tied to their protein."""
    proteins = identity.get("proteins") or []
    names, organisms = [], []
    for protein in proteins:
        name = protein.get("name") or "Protein name not recorded"
        if protein.get("fragment"):
            name += f" ({protein['fragment']})"
        chain = ",".join(protein.get("chains") or [])
        if len(proteins) > 1:
            name += f" [chains {chain or 'not recorded'}]"
        names.append(name)
        species = "; ".join(protein.get("source_species") or []) or "Not recorded in the supplied structure"
        organisms.append((f"Chains {chain or '?'}: " if len(proteins) > 1 else "") + species)
    target = "; ".join(names) if names else fallback
    structure_id = identity.get("structure_id")
    if structure_id and structure_id != target:
        target += f" [{structure_id}]"
    if not names:
        target += " (protein name not recorded in the supplied structure)"
    return target, "; ".join(organisms) or "Not recorded in the supplied structure"
