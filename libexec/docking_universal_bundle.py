"""Create and open portable Docking Universal protocol bundles."""

import hashlib
import json
import shutil
import tempfile
import zipfile
from pathlib import Path


CONTROL_VALIDATED = "control-validated"
LIGAND_GUIDED_EXPLORATORY = "ligand-guided-exploratory"
SITE_GUIDED_EXPLORATORY = "site-guided-exploratory"
PROTOCOL_TYPES = {
    CONTROL_VALIDATED,
    LIGAND_GUIDED_EXPLORATORY,
    SITE_GUIDED_EXPLORATORY,
}
STANDARD_AMINO_ACIDS = {
    "ALA", "ARG", "ASN", "ASP", "CYS", "GLN", "GLU", "GLY", "HIS", "ILE",
    "LEU", "LYS", "MET", "PHE", "PRO", "SER", "THR", "TRP", "TYR", "VAL",
}


def build_receptor_modification_warning(rows, removal_occurred=True):
    """Create the durable, machine-readable warning stored in a protocol."""
    if not removal_occurred:
        return None
    rows = rows or []
    standard = sum(str(row.get("residue_name", "")).upper() in STANDARD_AMINO_ACIDS for row in rows)
    other = len(rows) - standard
    if rows:
        counts = []
        if standard:
            counts.append(f"{standard} standard amino-acid residue{' was' if standard == 1 else 's were'} removed")
        if other:
            counts.append(f"{other} other residue/component{' was' if other == 1 else 's were'} removed")
        summary = "The receptor model was changed: " + "; ".join(counts) + "."
    else:
        summary = ("The receptor was changed by explicit user-approved removal of unmatched components; "
                   "inspect the retained removal manifest and preparation log.")
    if standard:
        summary += " HIGH-SEVERITY STRUCTURAL MODIFICATION."
    return {
        "code": "user-approved-receptor-component-removal",
        "severity": "high" if standard else "warning",
        "summary": summary,
        "removed_residue_component_count": len(rows) if rows else None,
        "removed_standard_amino_acid_count": standard if rows else None,
        "removed_other_component_count": other if rows else None,
        "structural_review_required": True,
        "control_redocking_required": True,
    }


def protocol_type(record):
    """Return the explicit type, inferring the legacy approved type when safe."""
    value = str(record.get("protocol_type", "")).strip().lower()
    if value in PROTOCOL_TYPES:
        return value
    if record.get("unknown_docking_allowed") and record.get("control_status") == "approved":
        return CONTROL_VALIDATED
    return None


def protocol_can_screen(record):
    """Recognize approved controls and explicitly user-authorized exploration."""
    kind = protocol_type(record)
    if kind == CONTROL_VALIDATED:
        return bool(record.get("unknown_docking_allowed") and record.get("control_status") == "approved")
    return bool(
        kind in {LIGAND_GUIDED_EXPLORATORY, SITE_GUIDED_EXPLORATORY}
        and record.get("exploratory_screening_allowed") is True
        and record.get("screening_authority") == "user-confirmed-exploratory-use"
    )


def protocol_type_label(value):
    return {
        CONTROL_VALIDATED: "Control-validated",
        LIGAND_GUIDED_EXPLORATORY: "Ligand-guided exploratory",
        SITE_GUIDED_EXPLORATORY: "Site-guided exploratory",
    }.get(value, "Legacy protocol")


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def create_bundle(protocol_path, control_root, output, control_compound=None):
    """Package a reusable protocol and its retained evidence as one file."""
    protocol_path = Path(protocol_path).resolve()
    control_root = Path(control_root).resolve()
    output = Path(output).resolve()
    protocol = json.loads(protocol_path.read_text())
    kind = protocol_type(protocol)
    if not kind or not protocol_can_screen(protocol):
        raise ValueError("protocol is neither control-approved nor explicitly authorized for exploratory reuse")
    protocol["protocol_type"] = kind
    preparation = protocol.setdefault("receptor_preparation", {})
    if preparation.get("user_approved_component_removal") and not preparation.get("receptor_modification_warning"):
        preparation["receptor_modification_warning"] = build_receptor_modification_warning(
            preparation.get("user_approved_removed_components") or []
        )

    with tempfile.TemporaryDirectory(prefix="docking-universal-bundle-") as temporary:
        root = Path(temporary)
        packaged_control = root / ("control" if kind == CONTROL_VALIDATED else "protocol")
        assets = packaged_control / "assets"
        receptor = Path(protocol["locked_inputs"]["receptor"]).expanduser().resolve()
        box = Path(protocol["locked_inputs"]["box"]).expanduser().resolve()
        receptor_copy = _copy(receptor, assets / receptor.name)
        box_copy = _copy(box, assets / box.name)
        protocol["locked_inputs"].update({
            "receptor": f"assets/{receptor_copy.name}",
            "box": f"assets/{box_copy.name}",
        })
        receptor_pdb_value = protocol.get("locked_inputs", {}).get("receptor_pdb")
        if receptor_pdb_value:
            receptor_pdb_source = Path(receptor_pdb_value).expanduser().resolve()
            if receptor_pdb_source.is_file():
                receptor_pdb_copy = _copy(receptor_pdb_source, assets / receptor_pdb_source.name)
                protocol["locked_inputs"]["receptor_pdb"] = f"assets/{receptor_pdb_copy.name}"
        audit_value = protocol.get("receptor_preparation", {}).get("pdbfixer_audit")
        if audit_value:
            audit_source = Path(audit_value).expanduser().resolve()
            if audit_source.is_file():
                audit_copy = _copy(audit_source, assets / "pdbfixer_audit.json")
                protocol["receptor_preparation"]["pdbfixer_audit"] = f"assets/{audit_copy.name}"
        ccd_audit_value = protocol.get("receptor_preparation", {}).get("ccd_modification_audit")
        if ccd_audit_value:
            ccd_audit_source = Path(ccd_audit_value).expanduser().resolve()
            if ccd_audit_source.is_file():
                ccd_audit_copy = _copy(ccd_audit_source, assets / "ccd_modification_audit.json")
                protocol["receptor_preparation"]["ccd_modification_audit"] = f"assets/{ccd_audit_copy.name}"
        adfr_log_value = protocol.get("receptor_preparation", {}).get("adfr_fallback_log")
        if adfr_log_value:
            adfr_log_source = Path(adfr_log_value).expanduser().resolve()
            if adfr_log_source.is_file():
                adfr_log_copy = _copy(adfr_log_source, assets / "receptor_adfr_fallback.log")
                protocol["receptor_preparation"]["adfr_fallback_log"] = f"assets/{adfr_log_copy.name}"
        removal_log_value = protocol.get("receptor_preparation", {}).get("user_approved_component_removal_log")
        if removal_log_value:
            removal_log_source = Path(removal_log_value).expanduser().resolve()
            if removal_log_source.is_file():
                removal_log_copy = _copy(removal_log_source, assets / "receptor_user_approved_removal.log")
                protocol["receptor_preparation"]["user_approved_component_removal_log"] = f"assets/{removal_log_copy.name}"
        removal_record_value = protocol.get("receptor_preparation", {}).get("user_approved_component_removal_record")
        if removal_record_value:
            removal_record_source = Path(removal_record_value).expanduser().resolve()
            if removal_record_source.is_file():
                removal_record_copy = _copy(removal_record_source, assets / "user_approved_component_removal.txt")
                protocol["receptor_preparation"]["user_approved_component_removal_record"] = f"assets/{removal_record_copy.name}"
        removal_manifest_value = protocol.get("receptor_preparation", {}).get("user_approved_component_removal_manifest")
        if removal_manifest_value:
            removal_manifest_source = Path(removal_manifest_value).expanduser().resolve()
            if removal_manifest_source.is_file():
                removal_manifest_copy = _copy(removal_manifest_source, assets / "user_approved_component_removal.tsv")
                protocol["receptor_preparation"]["user_approved_component_removal_manifest"] = f"assets/{removal_manifest_copy.name}"

        evidence = packaged_control / "evidence"
        evidence_files = []
        patterns = (
            "report/control_*.png", "report/control_*.json", "report/control_*.csv",
            "report/*protocol*.pdf", "report/*box*.png", "report/*cavity*.png",
            "**/selected_visuals/*.png", "**/selected_visuals/**/*.png",
            "**/experimental_interactions.png", "**/comparison_summary.json",
        )
        seen = set()
        for pattern in patterns:
            for source in sorted(control_root.glob(pattern)):
                if not source.is_file() or source.resolve() in seen:
                    continue
                seen.add(source.resolve())
                destination = _copy(source, evidence / source.name)
                evidence_files.append({
                    "path": str(destination.relative_to(packaged_control)),
                    "sha256": sha256(destination),
                })

        source_ligand = next(iter(sorted(control_root.glob("**/*_experimental.sdf"))), None)
        if source_ligand is None:
            source_ligand = next(iter(sorted(control_root.glob("**/crystal_ligand.sdf"))), None)
        if source_ligand is None and kind == LIGAND_GUIDED_EXPLORATORY:
            source_ligand = next(iter(sorted(control_root.glob("**/ligand/*.pdb"))), None)
        if source_ligand:
            retained = _copy(source_ligand, packaged_control / "00_inputs" / source_ligand.name)
            evidence_files.append({
                "path": str(retained.relative_to(packaged_control)),
                "sha256": sha256(retained),
            })

        if kind == CONTROL_VALIDATED:
            protocol["control_evidence"] = {
                "compound": control_compound or "not recorded",
                "artifacts": evidence_files,
            }
        else:
            protocol["protocol_evidence"] = {"artifacts": evidence_files}
        bundled_protocol = packaged_control / "protocol.json"
        bundled_protocol.write_text(json.dumps(protocol, indent=2) + "\n")

        manifest_files = []
        for path in sorted(packaged_control.glob("**/*")):
            if path.is_file():
                manifest_files.append({
                    "path": str(path.relative_to(root)), "sha256": sha256(path),
                })
        (root / "bundle_manifest.json").write_text(json.dumps({
            "schema_name": "docking-universal-protocol-bundle",
            "schema_version": 1,
            "protocol_type": kind,
            "protocol": str(bundled_protocol.relative_to(root)),
            "files": manifest_files,
        }, indent=2) + "\n")
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(root.glob("**/*")):
                if path.is_file():
                    archive.write(path, path.relative_to(root))
    return output


def extract_bundle(bundle_path):
    """Verify and extract a .duprotocol, returning its internal protocol path."""
    bundle_path = Path(bundle_path).expanduser().resolve()
    root = Path(tempfile.mkdtemp(prefix="docking-universal-protocol-")).resolve()
    try:
        with zipfile.ZipFile(bundle_path) as archive:
            for member in archive.infolist():
                destination = (root / member.filename).resolve()
                if root not in destination.parents and destination != root:
                    raise ValueError("unsafe path in protocol bundle")
            archive.extractall(root)
        manifest = json.loads((root / "bundle_manifest.json").read_text())
        if manifest.get("schema_name") != "docking-universal-protocol-bundle" or manifest.get("schema_version") != 1:
            raise ValueError("unsupported Docking Universal protocol bundle")
        for record in manifest.get("files", []):
            path = root / record["path"]
            if not path.is_file() or sha256(path) != record["sha256"]:
                raise ValueError(f"protocol bundle file failed verification: {record['path']}")
        protocol = root / manifest["protocol"]
        if not protocol.is_file():
            raise ValueError("protocol bundle does not contain protocol.json")
        return protocol
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def resolve_locked_path(protocol_path, stored_path):
    path = Path(stored_path).expanduser()
    if not path.is_absolute():
        path = Path(protocol_path).resolve().parent / path
    return path.resolve()
