"""Build reviewable Meeko polymer templates from local CCD definitions.

GeoStd and the PDB Chemical Component Dictionary (CCD) answer different
questions.  GeoStd supplies the restraints used by Reduce2; the CCD supplies
the explicit bond orders, formal charges, leaving atoms, and polymer identity
needed by Meeko.  This module deliberately requires both local definitions and
never retrieves data implicitly.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from urllib.request import Request, urlopen

from .geostd_components import (
    GEOSTD_REVISION,
    canonical_component_id,
    component_relative_path,
    library_has_component,
)


CCD_ROOT = "https://files.rcsb.org/ligands/download"


def default_ccd_cache() -> Path:
    explicit = os.environ.get("DOCKING_UNIVERSAL_CCD_CACHE")
    if explicit:
        return Path(explicit).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "DockingUniversal" / "ccd"
    if os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "DockingUniversal" / "ccd"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "docking-universal" / "ccd"


def ccd_path(cache: Path | str, component_id: str) -> Path:
    return Path(cache) / f"{canonical_component_id(component_id)}.cif"


def ccd_url(component_id: str) -> str:
    return f"{CCD_ROOT}/{canonical_component_id(component_id)}.cif"


def ccd_network_disclosure(component_ids) -> dict:
    components = sorted({canonical_component_id(value) for value in component_ids})
    return {
        "schema_name": "docking-universal-ccd-network-disclosure",
        "schema_version": 1,
        "purpose": (
            "Download public PDB Chemical Component Dictionary definitions for "
            "reviewed local Meeko template generation"
        ),
        "service": "RCSB Protein Data Bank file service",
        "host": "files.rcsb.org",
        "component_ids": components,
        "request_urls": [ccd_url(value) for value in components],
        "shared": [
            "The listed public chemical-component identifiers in request URLs",
            "Standard connection metadata available to the service, including IP address and request time",
        ],
        "not_shared": [
            "Receptor coordinates or structure files",
            "Ligand files or private chemical structures",
            "Docking boxes, poses, scores, results, study names, or reports",
        ],
    }


def _validate_ccd_payload(component_id: str, payload: bytes) -> None:
    component = canonical_component_id(component_id)
    text = payload.decode("utf-8", errors="replace")
    if (
        f"data_{component}" not in text
        or "_chem_comp_atom.atom_id" not in text
        or "_chem_comp_bond.value_order" not in text
    ):
        raise OSError(f"Downloaded data is not an RCSB CCD definition for {component}")


def download_ccd_components(
    component_ids,
    cache: Path | str,
    *,
    approved: bool,
    opener=urlopen,
) -> dict:
    """Download exact CCD entries after an explicit disclosure approval."""

    components = sorted({canonical_component_id(value) for value in component_ids})
    disclosure = ccd_network_disclosure(components)
    if not approved:
        raise PermissionError("CCD retrieval requires explicit approval of its disclosure")
    root = Path(cache).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    downloads = []
    for component in components:
        output = ccd_path(root, component)
        if output.is_file():
            payload = output.read_bytes()
            _validate_ccd_payload(component, payload)
            status = "already_cached"
        else:
            url = ccd_url(component)
            request = Request(url, headers={"User-Agent": "Docking-Universal/CCD"})
            try:
                with opener(request, timeout=30) as response:
                    payload = response.read()
            except Exception as exc:
                raise OSError(f"Could not download CCD component {component}: {exc}") from exc
            _validate_ccd_payload(component, payload)
            temporary = output.with_suffix(".cif.part")
            temporary.write_bytes(payload)
            temporary.replace(output)
            status = "downloaded"
        downloads.append({
            "component_id": component,
            "status": status,
            "url": ccd_url(component),
            "path": str(output),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    record = {
        "schema_name": "docking-universal-ccd-component-cache",
        "schema_version": 1,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "disclosure": disclosure,
        "downloads": downloads,
    }
    (root / "docking-universal-ccd-provenance.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )
    return record


def installed_meeko_missing_components(component_ids) -> tuple[str, ...]:
    """Return component names absent from the active Meeko template set."""

    try:
        from meeko import ResidueChemTemplates
    except ImportError as exc:
        raise RuntimeError("Meeko is unavailable in the selected scientific Python") from exc
    templates = ResidueChemTemplates.create_from_defaults()
    supported = set(templates.residue_templates) | set(templates.ambiguous)
    return tuple(sorted(
        canonical_component_id(value) for value in set(component_ids)
        if canonical_component_id(value) not in supported
    ))


def _component_metadata(path: Path, component: str) -> dict:
    try:
        import gemmi
    except ImportError as exc:
        raise RuntimeError("Local CCD template generation requires gemmi") from exc
    block = gemmi.cif.read_file(str(path)).find_block(component)
    if block is None:
        raise ValueError(f"CCD file does not contain component {component}")

    def value(tag: str) -> str:
        raw = str(block.find_value(tag) or "").strip().strip("'\"")
        return "" if raw in {".", "?"} else raw

    atoms = block.find(
        "_chem_comp_atom.", ["atom_id", "type_symbol", "charge", "pdbx_leaving_atom_flag"],
    )
    atom_rows = []
    for row in atoms:
        atom_rows.append({
            "atom_id": str(row[0]).strip("'\""),
            "element": str(row[1]).strip("'\"").upper(),
            "formal_charge": int(str(row[2])),
            "leaving": str(row[3]).strip("'\"").upper() == "Y",
        })
    return {
        "component_id": component,
        "name": value("_chem_comp.name"),
        "type": value("_chem_comp.type"),
        "parent_component_id": value("_chem_comp.mon_nstd_parent_comp_id"),
        "formal_charge": int(value("_chem_comp.pdbx_formal_charge") or 0),
        "atoms": atom_rows,
    }


def _meeko_version() -> str:
    try:
        return version("meeko")
    except PackageNotFoundError:
        return "unknown"


def generate_reviewed_polymer_templates(
    component_ids,
    *,
    geostd_library: Path | str,
    ccd_cache: Path | str,
    output_json: Path | str,
    audit_json: Path | str,
) -> dict:
    """Generate and validate Meeko templates for CCD-defined peptide PTMs.

    The function fails closed for non-peptide components, ambiguous backbone
    detection, missing definitions, or incomplete heavy-atom transfer.
    """

    try:
        from rdkit import Chem
        from meeko import ResidueChemTemplates
        from meeko.chemtempgen import (
            AA_recipe,
            ChemicalComponent,
            add_variants,
            export_chem_templates_to_json,
        )
    except ImportError as exc:
        raise RuntimeError("Meeko template generation is unavailable") from exc

    geostd = Path(geostd_library).resolve()
    ccd = Path(ccd_cache).resolve()
    output = Path(output_json).resolve()
    audit = Path(audit_json).resolve()
    components = sorted({canonical_component_id(value) for value in component_ids})
    missing = installed_meeko_missing_components(components)
    combined = {"ambiguous": {}, "residue_templates": {}}
    entries = []
    validation_templates = ResidueChemTemplates.create_from_defaults()

    for component in components:
        if component not in missing:
            entries.append({
                "component_id": component,
                "status": "already_supported_by_meeko",
            })
            continue
        geostd_path = geostd / component_relative_path(component)
        component_ccd = ccd_path(ccd, component)
        if not library_has_component(geostd, component):
            raise FileNotFoundError(f"GeoStd definition is unavailable for {component}")
        if not component_ccd.is_file():
            raise FileNotFoundError(f"Local CCD definition is unavailable for {component}")
        _validate_ccd_payload(component, component_ccd.read_bytes())
        metadata = _component_metadata(component_ccd, component)
        if "PEPTIDE LINKING" not in metadata["type"].upper():
            raise ValueError(
                f"{component} is classified as {metadata['type'] or 'unknown'}; "
                "automatic Meeko template generation is limited to peptide-linking PTMs"
            )
        chemical_component = ChemicalComponent.from_cif(str(component_ccd), component)
        if chemical_component is None:
            raise ValueError(f"Meeko could not construct {component} from its local CCD definition")
        variants = add_variants(
            chemical_component,
            cc_list=[],
            embed_allowed_smarts=AA_recipe.embed_allowed_smarts,
            cap_allowed_smarts=AA_recipe.cap_allowed_smarts,
            cap_protonate=AA_recipe.cap_protonate,
            pattern_to_label_mapping_standard=AA_recipe.pattern_to_label_mapping_standard,
            variant_dict=AA_recipe.variant_dict,
        )
        embedded = next((item for item in variants if item.resname == component), None)
        if embedded is None or set(embedded.link_labels.values()) != {"N-term", "C-term"}:
            raise ValueError(f"{component} did not yield one unambiguous internal peptide template")

        source_elements = {row["atom_id"]: row["element"] for row in metadata["atoms"]}
        expected_heavy = {
            row["atom_id"] for row in metadata["atoms"]
            if row["element"] not in {"H", "D"} and not row["leaving"]
        }
        observed_heavy = {
            name for name in embedded.atom_name
            if source_elements.get(name, "H") not in {"H", "D"}
        }
        if observed_heavy != expected_heavy:
            raise ValueError(
                f"{component} heavy-atom transfer is incomplete: expected "
                f"{sorted(expected_heavy)}, observed {sorted(observed_heavy)}"
            )
        embedded_charge = int(Chem.GetFormalCharge(embedded.rdkit_mol))
        if embedded_charge != metadata["formal_charge"]:
            raise ValueError(
                f"{component} formal charge changed during template generation: CCD "
                f"{metadata['formal_charge']}, generated internal template {embedded_charge}"
            )
        generated = json.loads(export_chem_templates_to_json(variants))
        validation_templates.add_dict(generated)
        combined["ambiguous"].update(generated.get("ambiguous", {}))
        combined["residue_templates"].update(generated.get("residue_templates", {}))
        entries.append({
            "component_id": component,
            "status": "candidate_validated",
            "component_name": metadata["name"],
            "component_type": metadata["type"],
            "parent_component_id": metadata["parent_component_id"],
            "ccd_formal_charge": metadata["formal_charge"],
            "embedded_template_formal_charge": embedded_charge,
            "generated_variants": [item.resname for item in variants],
            "embedded_template": component,
            "embedded_heavy_atoms": sorted(observed_heavy),
            "link_labels": dict(embedded.link_labels),
            "geostd_path": str(geostd_path),
            "geostd_sha256": hashlib.sha256(geostd_path.read_bytes()).hexdigest(),
            "ccd_path": str(component_ccd),
            "ccd_sha256": hashlib.sha256(component_ccd.read_bytes()).hexdigest(),
        })

    if not combined["residue_templates"]:
        raise ValueError("No additional Meeko templates were required or generated")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(combined, indent=2, sort_keys=True) + "\n")
    record = {
        "schema_name": "docking-universal-meeko-template-bridge",
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "review_required",
        "scientific_boundary": (
            "The generated template is a chemically validated candidate derived from public "
            "component definitions. User approval and target-matched control evidence remain required."
        ),
        "meeko_version": _meeko_version(),
        "geostd_revision": GEOSTD_REVISION,
        "template_file": str(output),
        "template_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "components": entries,
    }
    audit.parent.mkdir(parents=True, exist_ok=True)
    audit.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n")
    return record
