"""Minimal, consent-gated GeoStd component acquisition.

Only public chemical-component identifiers are sent to the pinned upstream
repository.  Receptor coordinates and Docking Universal study data are never
part of a request.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


GEOSTD_REVISION = "6b9ef76b4167e27c1530745e0311e8c5ac59338c"
GEOSTD_REPOSITORY = "phenix-project/geostd"
GEOSTD_RAW_ROOT = (
    "https://raw.githubusercontent.com/phenix-project/geostd/"
    f"{GEOSTD_REVISION}"
)
COMPONENT_ID = re.compile(r"^[A-Z0-9]{1,8}$")
WATER_COMPONENTS = frozenset({"HOH", "WAT", "DOD"})
SUPPORTED_METALS = frozenset({"ZN", "MG", "MN", "CA", "FE", "CU"})


def bundled_minimal_library() -> Path:
    return Path(__file__).resolve().parents[1] / "data" / "geostd"


def default_component_cache() -> Path:
    explicit = os.environ.get("DOCKING_UNIVERSAL_COMPONENT_CACHE")
    if explicit:
        parent = Path(explicit).expanduser()
    elif sys.platform == "darwin":
        parent = Path.home() / "Library" / "Caches" / "DockingUniversal" / "components"
    elif os.name == "nt" and os.environ.get("LOCALAPPDATA"):
        parent = Path(os.environ["LOCALAPPDATA"]) / "DockingUniversal" / "components"
    else:
        parent = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "docking-universal" / "components"
    return parent / GEOSTD_REVISION / "geostd"


def available_library(component_ids) -> Path | None:
    """Find one local library that covers every retained component."""
    requested = tuple({canonical_component_id(value) for value in component_ids})
    explicit = os.environ.get("DOCKING_UNIVERSAL_GEOSTD") or os.environ.get("MMTBX_CCP4_MONOMER_LIB")
    here = Path(__file__).resolve()
    candidates = [
        Path(explicit).expanduser() if explicit else None,
        default_component_cache(),
        here.parents[4] / "third_party" / "geostd",
        bundled_minimal_library(),
    ]
    for candidate in candidates:
        if candidate and candidate.is_dir() and not missing_components(candidate, requested):
            return candidate.resolve()
    return None


def canonical_component_id(value: str) -> str:
    component = str(value).strip().upper()
    if not COMPONENT_ID.fullmatch(component):
        raise ValueError(
            "A GeoStd component identifier must contain 1-8 ASCII letters or numbers"
        )
    return component


def component_relative_path(component_id: str) -> Path:
    component = canonical_component_id(component_id)
    return Path(component[0].lower()) / f"data_{component}.cif"


def component_url(component_id: str) -> str:
    return f"{GEOSTD_RAW_ROOT}/{component_relative_path(component_id).as_posix()}"


def library_has_component(library: Path | str, component_id: str) -> bool:
    return (Path(library) / component_relative_path(component_id)).is_file()


def materialize_minimal_library(destination: Path | str) -> Path:
    """Create a writable library from the bundled standard-protein core."""
    source = bundled_minimal_library()
    if not (source / "list" / "mon_lib_list.cif").is_file():
        raise FileNotFoundError(f"Bundled minimal GeoStd library is incomplete: {source}")
    target = Path(destination).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)
    return target


def network_disclosure(component_ids) -> dict:
    components = sorted({canonical_component_id(value) for value in component_ids})
    return {
        "schema_name": "docking-universal-network-disclosure",
        "schema_version": 1,
        "purpose": "Download missing public GeoStd chemical-component restraints for local Reduce2 preparation",
        "service": "GitHub raw content service",
        "repository": GEOSTD_REPOSITORY,
        "revision": GEOSTD_REVISION,
        "host": "raw.githubusercontent.com",
        "component_ids": components,
        "request_urls": [component_url(value) for value in components],
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


def _validated_component_payload(component_id: str, payload: bytes) -> None:
    component = canonical_component_id(component_id)
    text = payload.decode("utf-8", errors="replace")
    # GeoStd restraint files contain a component-list block and the exact
    # component block.  An ordinary CCD definition is deliberately rejected:
    # it lacks the geometry/tree fields expected by CCTBX Reduce2.
    if f"data_comp_{component}" not in text or "_chem_comp_tree.comp_id" not in text:
        raise OSError(
            f"Downloaded data is not a GeoStd restraint definition for {component}"
        )


def download_components(
    component_ids,
    library: Path | str,
    *,
    approved: bool,
    opener=urlopen,
) -> dict:
    """Download exact pinned GeoStd components after explicit authorization."""
    components = sorted({canonical_component_id(value) for value in component_ids})
    disclosure = network_disclosure(components)
    if not approved:
        raise PermissionError(
            "Network component retrieval requires explicit approval of its disclosure"
        )
    root = materialize_minimal_library(library)
    downloads = []
    for component in components:
        relative = component_relative_path(component)
        output = root / relative
        if output.is_file():
            payload = output.read_bytes()
            _validated_component_payload(component, payload)
            downloads.append({
                "component_id": component,
                "status": "already_cached",
                "path": str(output),
                "sha256": hashlib.sha256(payload).hexdigest(),
            })
            continue
        url = component_url(component)
        request = Request(url, headers={"User-Agent": "Docking-Universal/GeoStd"})
        try:
            with opener(request, timeout=30) as response:
                payload = response.read()
        except Exception as exc:
            raise OSError(f"Could not download GeoStd component {component}: {exc}") from exc
        _validated_component_payload(component, payload)
        output.parent.mkdir(parents=True, exist_ok=True)
        temporary = output.with_suffix(".cif.part")
        temporary.write_bytes(payload)
        temporary.replace(output)
        downloads.append({
            "component_id": component,
            "status": "downloaded",
            "url": url,
            "path": str(output),
            "sha256": hashlib.sha256(payload).hexdigest(),
        })
    record = {
        "schema_name": "docking-universal-geostd-component-cache",
        "schema_version": 1,
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "disclosure": disclosure,
        "downloads": downloads,
    }
    (root / "docking-universal-component-provenance.json").write_text(
        json.dumps(record, indent=2) + "\n"
    )
    return record


def retained_component_ids_from_pdb(path: Path | str) -> tuple[str, ...]:
    """Mirror the receptor filter's retained component policy for a legacy PDB."""
    lines = Path(path).read_text(errors="replace").splitlines()
    modified = {
        line[12:15].strip().upper() for line in lines if line.startswith("MODRES")
    }
    linked = set()
    for line in lines:
        if not line.startswith("LINK  "):
            continue
        linked.add((line[17:20].strip().upper(), line[21:22].strip(),
                    line[22:26].strip(), line[26:27].strip()))
        linked.add((line[47:50].strip().upper(), line[51:52].strip(),
                    line[52:56].strip(), line[56:57].strip()))
    hetero_counts = {}
    for line in lines:
        if line.startswith("HETATM"):
            key = (line[17:20].strip().upper(), line[21:22].strip(),
                   line[22:26].strip(), line[26:27].strip())
            hetero_counts[key] = hetero_counts.get(key, 0) + 1
    retained = set()
    for line in lines:
        if line.startswith("ATOM  "):
            retained.add(line[17:20].strip().upper())
        elif line.startswith("HETATM"):
            component = line[17:20].strip().upper()
            key = (component, line[21:22].strip(), line[22:26].strip(),
                   line[26:27].strip())
            element = line[76:78].strip().upper()
            if component in modified:
                retained.add(component)
            elif key in linked and hetero_counts.get(key, 0) > 1 and component not in WATER_COMPONENTS:
                retained.add(component)
            elif element in SUPPORTED_METALS:
                retained.add(component)
    return tuple(sorted(value for value in retained if value))


def retained_component_ids(path: Path | str) -> tuple[str, ...]:
    """Return components retained by the receptor policy from PDB or mmCIF."""
    source = Path(path)
    if source.suffix.lower() not in {".cif", ".mmcif"}:
        return retained_component_ids_from_pdb(source)
    try:
        import gemmi
    except ImportError as exc:
        raise RuntimeError("mmCIF component review requires gemmi") from exc
    block = gemmi.cif.read_file(str(source)).sole_block()
    atoms = block.get_mmcif_category("_atom_site.")
    groups = atoms.get("group_PDB", [])
    count = len(groups)

    def values(category: str, fields: tuple[str, ...]) -> set[str]:
        table = block.get_mmcif_category(category)
        result = set()
        for field in fields:
            result.update(
                str(value).strip().upper() for value in table.get(field, [])
                if str(value).strip() not in {"", ".", "?"}
            )
        return result

    modified = values(
        "_pdbx_struct_mod_residue.",
        ("label_comp_id", "auth_comp_id", "parent_comp_id"),
    )
    linked = values(
        "_struct_conn.",
        ("ptnr1_label_comp_id", "ptnr1_auth_comp_id",
         "ptnr2_label_comp_id", "ptnr2_auth_comp_id"),
    )
    retained = set()
    for index in range(count):
        component_columns = atoms.get("auth_comp_id", []) or atoms.get("label_comp_id", [])
        component = str(component_columns[index]).strip().upper() if index < len(component_columns) else ""
        if not component:
            continue
        if str(groups[index]).upper() == "ATOM":
            retained.add(component)
            continue
        element_column = atoms.get("type_symbol", [])
        element = str(element_column[index]).strip().upper() if index < len(element_column) else ""
        if component in modified or (component in linked and component not in WATER_COMPONENTS):
            retained.add(component)
        elif element in SUPPORTED_METALS:
            retained.add(component)
    return tuple(sorted(retained))


def modified_polymer_component_ids(path: Path | str) -> tuple[str, ...]:
    """Return deposited modified-polymer component names, excluding parents."""

    source = Path(path)
    if source.suffix.lower() not in {".cif", ".mmcif"}:
        values = {
            line[12:15].strip().upper()
            for line in source.read_text(errors="replace").splitlines()
            if line.startswith("MODRES") and line[12:15].strip()
        }
        return tuple(sorted(values))
    try:
        import gemmi
    except ImportError as exc:
        raise RuntimeError("mmCIF modified-residue review requires gemmi") from exc
    block = gemmi.cif.read_file(str(source)).sole_block()
    table = block.get_mmcif_category("_pdbx_struct_mod_residue.")
    values = set()
    for field in ("auth_comp_id", "label_comp_id"):
        values.update(
            str(value).strip().upper() for value in table.get(field, [])
            if str(value).strip() not in {"", ".", "?"}
        )
    return tuple(sorted(values))


def missing_components(library: Path | str, component_ids) -> tuple[str, ...]:
    return tuple(sorted(
        component for component in {canonical_component_id(value) for value in component_ids}
        if not library_has_component(library, component)
    ))
