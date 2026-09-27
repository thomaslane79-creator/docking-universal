"""Readable deposited-coordinate evidence shared by the GUI and reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


WATER = {"HOH", "WAT", "DOD", "H2O"}
COMMON_CRYSTALLIZATION_ADDITIVES = {
    "GOL", "EDO", "PEG", "PGE", "MPD", "SO4", "PO4", "ACT", "FMT",
    "ACE", "MES", "TRS", "HEP", "DMS", "IOD", "CL", "NA", "K",
}


def read_coordinate_evidence(path: Path | str) -> dict[str, Any] | None:
    source = Path(path)
    if source.suffix.lower() not in {".cif", ".mmcif"} or not source.is_file():
        return None
    from .structure_input import _deposited_metadata, _read_mmcif_assemblies

    return {
        "source_format": "mmcif",
        "assemblies": list(_read_mmcif_assemblies(source)),
        "deposited_metadata": _deposited_metadata(source),
    }


def read_retained_evidence(metadata_path: Path | str) -> dict[str, Any] | None:
    path = Path(metadata_path)
    if not path.is_file():
        return None
    record = json.loads(path.read_text())
    return record if record.get("source_format") == "mmcif" else None


def evidence_summary(record: dict[str, Any]) -> dict[str, Any]:
    metadata = record.get("deposited_metadata") or {}
    atoms = metadata.get("deposited_hetero_atoms") or []
    asym = metadata.get("struct_asym") or {}
    entities = metadata.get("entity") or {}
    entity_details = {
        str(identifier): {"type": str(kind), "name": str(name)}
        for identifier, kind, name in zip(
            entities.get("id", []), entities.get("type", []),
            entities.get("pdbx_description", []),
        )
    }
    nonpoly = metadata.get("pdbx_entity_nonpoly") or {}
    known_names = {
        str(comp): str(name)
        for comp, name in zip(nonpoly.get("comp_id", []), nonpoly.get("name", []))
    }
    ligand_codes = set(known_names) - WATER
    nonpoly_entities = set(map(str, nonpoly.get("entity_id", [])))
    instances: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    for atom in atoms:
        code = str(atom.get("label_comp_id") or "")
        if not code or code in WATER:
            continue
        entity_id = _clean(atom.get("label_entity_id"))
        if nonpoly_entities and entity_id not in nonpoly_entities:
            continue
        if ligand_codes and code not in ligand_codes:
            continue
        label_chain = _clean(atom.get("label_asym_id"))
        author_chain = _clean(atom.get("auth_asym_id"))
        residue_number = _clean(atom.get("auth_seq_id"))
        insertion = _clean(atom.get("pdbx_PDB_ins_code"))
        model = _clean(atom.get("pdbx_PDB_model_num")) or "1"
        key = (code, label_chain, author_chain, residue_number + insertion, model)
        item = instances.setdefault(key, {
            "code": code, "name": known_names.get(code, ""),
            "label_chain": label_chain, "author_chain": author_chain,
            "residue": residue_number + insertion, "model": model,
            "atom_count": 0, "occupancies": [], "b_factors": [],
        })
        item["atom_count"] += 1
        for source_key, destination in (("occupancy", "occupancies"),
                                        ("B_iso_or_equiv", "b_factors")):
            value = _number(atom.get(source_key))
            if value is not None:
                item[destination].append(value)
    for item in instances.values():
        for field, output in (("occupancies", "occupancy_range"),
                              ("b_factors", "b_factor_range")):
            values = item.pop(field)
            item[output] = [min(values), max(values)] if values else None

    chain_entities = [
        {"label_chain": str(chain), "entity_id": str(entity)}
        for chain, entity in zip(asym.get("id", []), asym.get("entity_id", []))
    ]
    author_chains: dict[str, set[str]] = {}
    for mapping in metadata.get("chain_identifier_map") or []:
        label = _clean(mapping.get("label_chain"))
        author = _clean(mapping.get("author_chain"))
        if label:
            author_chains.setdefault(label, set()).add(author)
    for item in chain_entities:
        item["author_chains"] = sorted(author_chains.get(item["label_chain"], set()))
        item.update(entity_details.get(item["entity_id"], {}))
    return {
        "assemblies": record.get("assemblies") or [],
        "chain_entities": chain_entities,
        "ligands": sorted(instances.values(), key=lambda item: (
            item["code"], item["author_chain"], item["residue"])),
    }


def evidence_lines(record: dict[str, Any], *, detailed: bool = False) -> list[str]:
    summary = evidence_summary(record)
    assemblies = summary["assemblies"]
    if assemblies:
        assembly_text = "; ".join(
            f"{item.get('id', '?')}: {item.get('oligomeric_details') or item.get('details') or 'deposited assembly'}"
            for item in assemblies
        )
        lines = [f"Deposited biological assemblies: {assembly_text}."]
    else:
        lines = ["No biological assembly annotation was present in this coordinate file."]
    chain_entities = summary["chain_entities"]
    if chain_entities:
        polymers = [item for item in chain_entities if item.get("type") == "polymer"]
        if polymers:
            chain_text = ", ".join(
                f"author chain {','.join(item['author_chains']) or '?'}"
                for item in polymers[:8]
            )
            lines.append(f"Supplied coordinate model: {len(polymers)} polymer chain"
                         + ("s" if len(polymers) != 1 else "") + f" ({chain_text})"
                         + (f", +{len(polymers) - 8} more." if len(polymers) > 8 else "."))
        if detailed:
            lines.append("Coordinate components: " + ", ".join(
                f"mmCIF {item['label_chain']} (entity {item['entity_id']}, "
                f"author {','.join(item['author_chains']) or '?'})"
                for item in chain_entities[:12]
            ) + ".")
    ligands = summary["ligands"]
    if ligands:
        additives = [item for item in ligands if item["code"] in COMMON_CRYSTALLIZATION_ADDITIVES]
        candidate_ligands = [item for item in ligands if item["code"] not in COMMON_CRYSTALLIZATION_ADDITIVES]
        if candidate_ligands:
            lines.append(f"Deposited candidate ligand instances: {len(candidate_ligands)}; "
                         + ", ".join(_ligand_short(item) for item in candidate_ligands[:5])
                         + (f", +{len(candidate_ligands) - 5} more." if len(candidate_ligands) > 5 else "."))
        else:
            lines.append("No deposited candidate binding ligands were identified from the non-polymer components.")
        if additives:
            counts = _component_counts(additives)
            names = []
            for code, count in counts.items():
                label = {"GOL": "glycerol", "EDO": "1,2-ethanediol"}.get(code, code)
                names.append(f"{label} ({code}) ×{count}")
            lines.append("Deposited non-polymer components classified as likely "
                         "crystallization/solvent additives: " + ", ".join(names)
                         + "; not treated as binding-ligand evidence.")
    else:
        lines.append("No deposited non-water ligand instances were identified from mmCIF annotations.")
    lines.append("The assembly annotation may include symmetry-generated copies absent from the supplied "
                 "coordinates. Preparation uses the supplied coordinates; no assembly is selected automatically.")
    if detailed:
        lines.append("A ligand missing from another copy is not proof that the site cannot bind.")
        lines.append("Occupancy describes how much of a modeled site is represented in the deposited "
                     "structure; it is not a binding-affinity measurement. B-factors are not direct proof of flexibility.")
        for item in assemblies:
            generators = item.get("generators") or []
            if generators:
                lines.append(f"Assembly {item.get('id', '?')} generators: " + "; ".join(
                    f"asym {part.get('asym_ids', '?')}, operation {part.get('operation_expression', '?')}"
                    for part in generators))
        for item in ligands:
            occupancy = _range_text(item.get("occupancy_range"))
            b_factor = _range_text(item.get("b_factor_range"))
            lines.append(
                f"{item['code']} {item['name']} — author chain {item['author_chain'] or '?'}, "
                f"residue {item['residue'] or '?'}, label asym {item['label_chain'] or '?'}, "
                f"model {item['model']}; occupancy {occupancy}, B-factor {b_factor} Å²."
            )
    return lines


def _ligand_short(item: dict[str, Any]) -> str:
    occupancy = item.get("occupancy_range")
    return (f"{item['code']} {item['author_chain'] or '?'}:{item['residue'] or '?'}"
            + (f" (occupancy {_range_text(occupancy)})" if occupancy else ""))


def _component_counts(items: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        counts[item["code"]] = counts.get(item["code"], 0) + 1
    return counts


def _clean(value: Any) -> str:
    text = str(value or "").strip()
    return "" if text in {"?", ".", "None"} else text


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _range_text(values: list[float] | None) -> str:
    if not values:
        return "unavailable"
    if values[0] == values[1]:
        return f"{values[0]:g}"
    return f"{values[0]:g}–{values[1]:g}"
