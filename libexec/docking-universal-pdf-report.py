#!/usr/bin/env python3
"""Generate the polished Docking Universal PDF from completed run artifacts."""
import argparse, csv, hashlib, json, re, subprocess, sys
from importlib import metadata
from pathlib import Path

def first(root, patterns):
    for pattern in patterns:
        hits = sorted(root.glob(pattern))
        if hits:
            return hits[0]
    return None

def read_json(path, default=None):
    try:
        return json.loads(path.read_text()) if path else (default or {})
    except (OSError, ValueError, TypeError):
        return default or {}

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def package_version():
    script_dir = Path(__file__).resolve().parent
    for version_file in (script_dir / "VERSION", script_dir.parent / "VERSION"):
        try:
            return version_file.read_text().strip()
        except OSError:
            pass
    return "unknown"

def docking_detail_section_break():
    """Reserve a full detail panel without forcing a blank fresh page."""
    from reportlab.lib.units import inch
    from reportlab.platypus import CondPageBreak
    return CondPageBreak(7.6 * inch)

def read_key_value_tsv(path):
    data = {}
    if not path:
        return data
    try:
        with path.open(newline="") as handle:
            for row in csv.reader(handle, delimiter="\t"):
                if len(row) >= 2:
                    data[row[0]] = row[1]
    except OSError:
        pass
    return data

def read_tsv_rows(path):
    try:
        with path.open(newline="") as handle:
            return list(csv.DictReader(handle, delimiter="\t"))
    except (OSError, TypeError):
        return []

def read_fpocket_descriptors(cavity_dir):
    import re
    info = first(cavity_dir, ["**/*_info.txt"])
    if not info:
        return {}
    records, pocket = {}, None
    for line in info.read_text(errors="replace").splitlines():
        match = re.match(r"\s*Pocket\s+(\d+)\s*:", line)
        if match:
            pocket = f"pocket{match.group(1)}_atm.pdb"
            records[pocket] = {}
            continue
        if not pocket or ":" not in line:
            continue
        key, value = (part.strip() for part in line.split(":", 1))
        normalized = {"Druggability Score": "druggability_score", "Volume": "volume_angstrom3"}.get(key)
        if normalized:
            try:
                records[pocket][normalized] = float(value)
            except ValueError:
                pass
    return records

def read_box_dimensions(config_path):
    values = {}
    try:
        for line in config_path.read_text(errors="replace").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in {"size_x", "size_y", "size_z"}:
                try:
                    values[key.strip()] = float(value.strip())
                except ValueError:
                    continue
    except OSError:
        return None
    dimensions = [values.get(key) for key in ("size_x", "size_y", "size_z")]
    if any(value is None for value in dimensions):
        return None
    return dimensions

def read_box_center(config_path):
    values = {}
    try:
        for line in config_path.read_text(errors="replace").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in {"center_x", "center_y", "center_z"}:
                values[key.strip()] = float(value.strip())
    except OSError:
        return None
    center = [values.get(key) for key in ("center_x", "center_y", "center_z")]
    return None if any(value is None for value in center) else center

def display_compound_name(name, source=None):
    import re
    value = str(name or "").strip()
    value = re.sub(r"(?i)\s+pubchem(?:\s+\d+)?$", "", value).strip()
    if value and not value.isdigit():
        return value
    stem = Path(str(source or "")).stem
    descriptive = re.sub(r"(?i)_pubchem(?:_?\d+)?$", "", stem).replace("_", " ").strip()
    return descriptive.title() if descriptive and not descriptive.isdigit() else (value or "Ligand")

def compound_result_records(study, compounds, ligand_names):
    """Read the retained cluster result independently for every ligand."""
    records = []
    for index, compound in enumerate(compounds):
        cid = str(compound.get("compound_id", ""))
        name = (
            ligand_names[index]
            if index < len(ligand_names)
            else display_compound_name(compound.get("compound_name"), cid)
        )
        cluster_path = study / "compounds" / cid / "pose_analysis" / "cluster_summary.csv"
        try:
            with cluster_path.open(newline="") as handle:
                clusters = list(csv.DictReader(handle))
        except OSError:
            clusters = []
        clusters.sort(key=lambda row: int(row.get("energy_rank", 999999) or 999999))
        leading = clusters[0] if clusters else {}
        records.append({
            "compound_id": cid,
            "name": name,
            "status": str(compound.get("status", "Unavailable") or "Unavailable"),
            "best_energy_kcal_per_mol": str(
                leading.get("best_energy_kcal_per_mol", "Unavailable") or "Unavailable"
            ),
            "top_cluster": str(leading.get("cluster_id", "Unavailable") or "Unavailable"),
            "top_cluster_population": str(leading.get("pose_count", "Unavailable") or "Unavailable"),
            "top_cluster_seed_support": str(leading.get("seed_support", "Unavailable") or "Unavailable"),
            "top_cluster_conformer_support": str(leading.get("conformer_support", "Unavailable") or "Unavailable"),
            "cluster_count": len(clusters),
            "selected_representatives": str(
                compound.get("selected_representatives", "Unavailable") or "Unavailable"
            ),
        })
    return records

def single_compound_summary_rows(result):
    """Use one result-summary format in standalone and multi-ligand reports."""
    best_score = result["best_energy_kcal_per_mol"]
    return [
        ["Summary of docking results", "Recorded result"],
        ["Ligand docked", result["name"]],
        ["Completion status", result["status"]],
        ["Best retained Vina score", f"{best_score} kcal/mol" if best_score != "Unavailable" else best_score],
        ["Top-ranked cluster", result["top_cluster"]],
        ["Top-cluster population", result["top_cluster_population"]],
        ["Independent-seed support", result["top_cluster_seed_support"]],
        ["Conformer support", result["top_cluster_conformer_support"]],
        ["Distinct retained clusters", result["cluster_count"] or "Unavailable"],
        ["Selected representatives", result["selected_representatives"]],
    ]

def safe_filename_component(value, fallback):
    import re
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip()).strip("._-")
    return cleaned or fallback

def descriptive_report_name(target_name, ligand_names, summary):
    import re
    target = safe_filename_component(target_name, "protein")
    target = re.sub(r"(?i)(?:_receptor|_prepared|_protein)+$", "", target) or "protein"
    names = [safe_filename_component(name, "ligand") for name in ligand_names]
    if len(names) <= 3 and names:
        subject = "_".join(names)
    elif names:
        subject = f"{len(names)}-ligands"
    else:
        subject = "cavity"
    created = str(summary.get("created_utc", ""))[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", created):
        from datetime import datetime
        created = datetime.now().strftime("%Y-%m-%d")
    workflow = summary.get("workflow", "")
    kind = "control_report" if workflow == "control" else "cavity_report" if not names else "docking_report"
    return f"{target}_{subject}_{created}_{kind}.pdf"

def discover_cavity_record(study):
    selection = first(study, [
        "preparation/*_receptor_prep/cavity/pocket_selection_diagnostics.tsv",
        "**/cavity/pocket_selection_diagnostics.tsv",
    ])
    # Exploratory docking can use a receptor-preparation directory selected
    # outside the study directory.  The locked box path is the authoritative
    # link to its corresponding fpocket diagnostics.
    if not selection:
        summary = read_json(study / "report" / "study_summary.json")
        box = Path(str(summary.get("configured_locked_inputs", {}).get("box", ""))).expanduser()
        candidate = box.parent / "pocket_selection_diagnostics.tsv"
        if candidate.is_file():
            selection = candidate
    if not selection:
        return None
    manifest = read_key_value_tsv(first(study, [
        "compounds/*/seed_*/docking/run_manifest.tsv", "**/docking/run_manifest.tsv",
    ]))
    config = Path(manifest.get("config", "")).name
    if not config:
        preparation_config = first(selection.parent, ["*_pocket*.conf"])
        config = preparation_config.name if preparation_config else ""
    import re
    rows = read_tsv_rows(selection)
    # `target_pocket1.conf` is the first generated output box, not necessarily
    # fpocket's source identifier (for example it can be made from pocket5).
    # Resolve it through the recorded selection order.
    match = re.search(r"pocket(\d+)", config, re.I)
    output_index = int(match.group(1)) if match else 1
    selected = next((row for row in rows if int(row.get("rank_order", 0) or 0) == output_index), {})
    selected_file = selected.get("pocket_file")
    diagnostics = selection.parent / "pocket_diagnostics.tsv"
    diagnostic_rows = read_tsv_rows(diagnostics)
    detail = next((row for row in diagnostic_rows if row.get("pocket_file") == selected_file), {})
    descriptors = read_fpocket_descriptors(selection.parent)
    config_path = selection.parent / config if config else None
    dimensions = read_box_dimensions(config_path) if config_path and config_path.is_file() else None
    center = read_box_center(config_path) if config_path and config_path.is_file() else None
    return {
        "selection": selection, "rows": rows, "selected": selected,
        "detail": detail, "descriptors": descriptors, "config": config,
        "selected_file": selected_file, "box_dimensions": dimensions, "box_center": center,
    }

def choose_protocol(root):
    candidates = list(root.glob("**/protocol.json")) if root else []
    if not candidates:
        return None
    def rank(path):
        record = read_json(path)
        acceptance = record.get("acceptance", {})
        return (
            1 if record.get("unknown_docking_allowed") else 0,
            1 if acceptance.get("requires_both") and acceptance.get("sampling_pass") and acceptance.get("ranking_pass") and acceptance.get("seed_requirement_pass") else 0,
            int(acceptance.get("independent_seed_count", 0) or 0),
            int(record.get("variant_count", 0) or 0),
        )
    return max(candidates, key=rank)

def protocol_lookup_filename(study, control, protocol_path, summary):
    """Return the exact human-usable protocol filename retained for this run."""
    recorded = str(summary.get("approved_protocol_file_name", "")).strip()
    if recorded:
        return Path(recorded).name
    for manifest_path in sorted(study.glob("compounds/*/screen_manifest.json")):
        manifest = read_json(manifest_path)
        recorded = str(manifest.get("protocol_source_file_name", "")).strip()
        if recorded:
            return Path(recorded).name
    if control:
        bundle_roots = [control, control.parent]
        bundles = []
        for root in bundle_roots:
            bundles.extend(path for path in root.glob("*.duprotocol") if path.is_file())
        unique = sorted({path.resolve() for path in bundles}, key=lambda path: path.stat().st_mtime)
        if len(unique) == 1:
            return unique[0].name
    return protocol_path.name if protocol_path else "not recorded by this older run"

def discover_control(study):
    """Recover the control root recorded by a separately launched screen."""
    # A standalone control study retains its protocol beneath `control/`.
    # Discover it without requiring the caller to pass the study back to itself.
    local_control = study / "control"
    if choose_protocol(local_control):
        return local_control
    if choose_protocol(study):
        return study
    for manifest_path in sorted(study.glob("compounds/*/screen_manifest.json")):
        protocol = Path(str(read_json(manifest_path).get("protocol", ""))).expanduser()
        if not protocol.is_file():
            continue
        for parent in protocol.parents:
            if parent.name == "control" or parent.name.startswith("control_"):
                return parent
    return None

def installed_version(*distribution_names):
    for name in distribution_names:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return "not detected"


SCIENTIFIC_VERSION_LABELS = {
    "Docking Universal": "docking_universal",
    "Python": "python",
    "RDKit": "rdkit",
    "MolScrub": "molscrub",
    "Meeko": "meeko",
    "PDBFixer": "pdbfixer",
    "AutoDock Vina": "engine_version",
}

SCIENTIFIC_SOFTWARE_KEYS = {
    "Docking Universal": "docking_universal",
    "Python": "python",
    "RDKit": "rdkit",
    "MolScrub": "molscrub",
    "Meeko": "meeko",
    "PDBFixer": "pdbfixer",
    "fpocket": "fpocket",
    "Open Babel": "openbabel",
    "PLIP": "plip",
    "AutoDock Vina": "engine_version",
}


def retained_artifact_versions(study):
    """Recover historical tool versions embedded in retained result files.

    Older study manifests did not record Open Babel or PLIP explicitly, but
    their generated artifacts do: Open Babel writes its version into the PDB
    AUTHOR record and PLIP writes ``plipversion`` into report.xml.  Use these
    immutable run products instead of the environment regenerating the PDF.
    """
    found = {"openbabel": set(), "plip": set()}
    for path in sorted(study.glob("**/interactions/*.pdb")):
        try:
            header = "\n".join(path.read_text(errors="replace").splitlines()[:20])
        except OSError:
            continue
        match = re.search(r"GENERATED BY OPEN BABEL\s+([0-9][^\s]*)", header, re.IGNORECASE)
        if match:
            found["openbabel"].add(match.group(1))
    for path in sorted(study.glob("**/interactions/report.xml")):
        try:
            xml = path.read_text(errors="replace")
        except OSError:
            continue
        match = re.search(r"<plipversion>\s*([^<]+?)\s*</plipversion>", xml, re.IGNORECASE)
        if match:
            found["plip"].add(match.group(1).strip())
    recovered = {}
    for key, versions in found.items():
        if len(versions) == 1:
            recovered[key] = next(iter(versions))
        elif len(versions) > 1:
            recovered[key] = "multiple retained versions: " + ", ".join(sorted(versions))
    return recovered


def retained_scientific_versions(study, summary=None, docking_manifest=None):
    """Read software versions that belong to the scientific run.

    New studies store these values directly.  Legacy studies retain at least
    the Docking Universal and Vina versions.  A prior report comparison is a
    compatible migration source only when its new-run Docking Universal value
    agrees with the immutable study summary; this rejects stale reports made
    later in a different environment.
    """
    summary = summary or read_json(study / "report" / "study_summary.json")
    docking_manifest = docking_manifest or read_key_value_tsv(first(study, [
        "compounds/*/seed_*/docking/run_manifest.tsv", "**/docking/run_manifest.tsv",
    ]))
    retained = dict(summary.get("scientific_software", {}) or {})
    if not retained:
        previous = read_json(study / "report" / "software_versions_and_references.json")
        previous_software = {
            item.get("software"): item.get("version")
            for item in previous.get("software", [])
        }
        entries = (previous.get("control_to_new_run_version_check") or {}).get("entries", [])
        by_label = {entry.get("software"): entry.get("new_run_version") for entry in entries}
        expected_workflow = str(summary.get("docking_universal_version", "") or "")
        if expected_workflow and str(by_label.get("Docking Universal", "")) == expected_workflow:
            retained.update({
                key: by_label[label]
                for label, key in SCIENTIFIC_VERSION_LABELS.items()
                if by_label.get(label)
            })
        elif expected_workflow and str(previous_software.get("Docking Universal", "")) == expected_workflow:
            retained.update({
                key: previous_software[label]
                for label, key in SCIENTIFIC_SOFTWARE_KEYS.items()
                if previous_software.get(label)
            })
    for key, version in retained_artifact_versions(study).items():
        if str(retained.get(key, "") or "").lower() in {
            "", "unknown", "not recorded", "not detected",
        }:
            retained[key] = version
    retained["docking_universal"] = str(
        summary.get("docking_universal_version")
        or retained.get("docking_universal")
        or "not recorded"
    )
    retained["engine_version"] = str(
        docking_manifest.get("engine_version")
        or retained.get("engine_version")
        or summary.get("configured_engine_version")
        or "not recorded"
    )
    for key in (
        "python", "rdkit", "molscrub", "meeko", "pdbfixer",
        "fpocket", "openbabel", "plip",
    ):
        retained[key] = str(retained.get(key) or "not recorded")
    return retained

def receptor_preparation_record(study, control=None):
    """Describe the receptor-conversion path from retained preparation artifacts."""
    roots = [root for root in (study, control) if root]
    # A `run` study may deliberately reuse a receptor prepared elsewhere.  Its
    # docking manifest records the PDBQT path, so follow that path back to the
    # preparation root instead of incorrectly reporting the route as unknown.
    for root in list(roots):
        manifest = first(root, ["compounds/*/seed_*/docking/run_manifest.tsv", "**/docking/run_manifest.tsv"])
        receptor_path = Path(read_key_value_tsv(manifest).get("receptor", "")).expanduser()
        if receptor_path.is_file():
            receptor_root = receptor_path.parent.parent if receptor_path.parent.name == "receptor" else receptor_path.parent
            if receptor_root not in roots:
                roots.append(receptor_root)
    def retained(patterns):
        return next((path for root in roots if (path := first(root, patterns))), None)
    audit_path = retained(["preparation/**/receptor/pdbfixer_audit.json", "**/receptor/pdbfixer_audit.json", "**/assets/pdbfixer_audit.json"])
    ccd_audit_path = retained(["preparation/**/receptor/ccd_modification_audit.json", "**/receptor/ccd_modification_audit.json", "**/assets/ccd_modification_audit.json"])
    post_fix_log = retained(["preparation/**/receptor/receptor_after_pdbfixer.log", "**/receptor/receptor_after_pdbfixer.log"])
    removal_log = retained(["preparation/**/receptor/receptor_user_approved_removal.log", "**/receptor/receptor_user_approved_removal.log", "**/assets/receptor_user_approved_removal.log"])
    removal_record = retained(["preparation/**/receptor/user_approved_component_removal.txt", "**/receptor/user_approved_component_removal.txt", "**/assets/user_approved_component_removal.txt"])
    adfr_log = retained(["preparation/**/receptor/receptor_adfr_fallback.log", "**/receptor/receptor_adfr_fallback.log", "**/assets/receptor_adfr_fallback.log"])
    disulfide_log = retained(["preparation/**/receptor/receptor_disulfide_retry.log", "**/receptor/receptor_disulfide_retry.log", "**/assets/receptor_disulfide_retry.log"])
    receptor_dir = retained(["preparation/**/receptor", "**/receptor"])
    audit = read_json(audit_path)
    ccd_audit = read_json(ccd_audit_path)
    if adfr_log and adfr_log.stat().st_size:
        path = "legacy ADFRsuite fallback after Meeko rejected a linked deposited component"
        used = bool(audit_path)
    elif disulfide_log and disulfide_log.stat().st_size:
        path = "strict Meeko succeeded after a CYX disulfide-template retry"
        used = False
    elif removal_log and removal_log.stat().st_size:
        path = "user-approved removal of unmatched receptor components after safe preparation fallbacks failed"
        used = bool(audit_path)
    elif post_fix_log and post_fix_log.stat().st_size:
        path = "conservative PDBFixer repair followed by strict Meeko"
        used = True
    elif audit_path:
        path = "PDBFixer repair attempted; inspect the retained audit and preparation logs"
        used = True
    elif receptor_dir:
        path = "strict Meeko succeeded; PDBFixer was not needed"
        used = False
    else:
        path = "prepared receptor supplied; receptor preparation occurred outside this recorded run"
        used = None
    return {
        "path": path,
        "pdbfixer_used": used,
        "pdbfixer_audit": str(audit_path) if audit_path else None,
        "user_approved_component_removal_log": str(removal_log) if removal_log else None,
        "user_approved_component_removal_record": str(removal_record) if removal_record else None,
        "adfr_fallback_log": str(adfr_log) if adfr_log else None,
        "disulfide_retry_log": str(disulfide_log) if disulfide_log else None,
        "changes": audit,
        "ccd_modification_audit": str(ccd_audit_path) if ccd_audit_path else None,
        "ccd_modifications": ccd_audit,
    }

def pdbfixer_report_note(record, out, styles):
    """Create a concise repair summary; detailed changes remain in the JSON audit."""
    from reportlab.platypus import Paragraph, Spacer
    if not record.get("pdbfixer_used") or not record.get("pdbfixer_audit"):
        return []
    audit = record.get("changes", {})
    added = audit.get("missing_heavy_atoms_added", "not recorded")
    terminal = audit.get("missing_terminal_atoms_detected_not_added", "not recorded")
    replacements = len(audit.get("nonstandard_residue_replacements", []))
    gaps = len(audit.get("missing_residue_segments_detected_not_built", []))
    if record.get("user_approved_component_removal_log"):
        disposition = "The repaired intermediate was rejected by strict Meeko, so these changes were not used in the final receptor; the user explicitly approved removal of unmatched components from the filtered original."
    else:
        disposition = "The repaired structure was accepted by strict Meeko and used to create the final receptor."
    changes = []
    if isinstance(added, int) and added:
        changes.append(f"added {added} missing side-chain heavy atoms")
    if replacements:
        changes.append(f"replaced {replacements} recognized nonstandard residues")
    if gaps:
        changes.append(f"reported but did not build {gaps} missing residue segments")
    if isinstance(terminal, int) and terminal:
        changes.append(f"detected but did not add {terminal} terminal atoms")
    change_text = "; ".join(changes) if changes else "no structural changes were recorded"
    text = f"<b>PDBFixer audit:</b> {change_text}. {disposition}"
    return [Paragraph(text, styles["BodyText"]), Spacer(1, 8)]

def adfr_fallback_report_note(record, out, styles):
    """State the limited legacy route explicitly in generated reports."""
    from reportlab.platypus import Paragraph, Spacer
    if not record.get("adfr_fallback_log"):
        return []
    text = ("<b>Linked-component preparation fallback:</b> strict Meeko rejected a deposited, "
            "covalently linked component, so legacy ADFRsuite created the final receptor PDBQT. "
            "This compatibility route is limited to that diagnosed case; a target-matched control "
            "redocking is required before the protocol can be approved.")
    return [Paragraph(text, styles["BodyText"]), Spacer(1, 8)]

def user_approved_removal_report_note(record, out, styles):
    """Make model-changing component removal unambiguous in every report."""
    from reportlab.platypus import Paragraph, Spacer
    if not record.get("user_approved_component_removal_log"):
        return []
    text = ("<b>User-approved receptor component removal:</b> safe preparation fallbacks failed, "
            "and the user explicitly approved Meeko's removal of unmatched components. The final "
            "receptor model may omit deposited material; inspect the retained removal log and run a "
            "target-matched bound-ligand control before prospective screening.")
    return [Paragraph(text, styles["BodyText"]), Spacer(1, 8)]

def ccd_modification_report_note(record, out, styles):
    """Summarize retained MODRES/CCD handling without expanding the report."""
    from reportlab.platypus import Paragraph, Spacer
    audit = record.get("ccd_modifications") or {}
    residues = audit.get("residues", [])
    if not residues:
        return []
    summaries = []
    for item in residues:
        summaries.append(
            f"{item.get('residue', '?')} {item.get('component', '?')} → "
            f"{item.get('standard_parent', '?')} ({item.get('resolution', 'not recorded')})"
        )
    text = "<b>CCD/MODRES audit:</b> " + "; ".join(summaries) + "."
    return [Paragraph(text, styles["BodyText"]), Spacer(1, 8)]

def pymol_version():
    try:
        result = subprocess.run(
            [sys.executable, "-c", "from pymol import cmd; print(cmd.get_version()[0])"],
            check=True, capture_output=True, text=True, timeout=20,
        )
        return result.stdout.strip().splitlines()[-1]
    except (OSError, subprocess.SubprocessError, IndexError):
        return "not detected"

def openbabel_version():
    executable = Path(sys.executable).resolve().parent / "obabel"
    try:
        result = subprocess.run(
            [str(executable), "-V"], check=True, capture_output=True, text=True, timeout=20,
        )
        words = result.stdout.strip().split()
        return words[2] if len(words) >= 3 and words[:2] == ["Open", "Babel"] else result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "not detected"

def fpocket_version():
    prefix = Path(sys.executable).resolve().parent.parent
    records = sorted((prefix / "conda-meta").glob("fpocket-*.json"))
    for record in records:
        version = read_json(record).get("version")
        if version:
            return str(version)
    return "detected; version not recorded" if (prefix / "bin" / "fpocket").is_file() else "not detected"

def compare_scientific_versions(recorded, current):
    """Compare the software that can change preparation, docking, or analysis."""
    fields = [
        ("Docking Universal", "docking_universal"),
        ("Python", "python"),
        ("RDKit", "rdkit"),
        ("MolScrub", "molscrub"),
        ("Meeko", "meeko"),
        ("PDBFixer", "pdbfixer"),
        ("AutoDock Vina", "engine_version"),
    ]
    entries = []
    for label, key in fields:
        control_version = str(recorded.get(key, "") or "")
        current_version = str(current.get(key, "") or "")
        if not control_version or control_version in {"unknown", "not recorded", "not detected"}:
            status = "NOT VERIFIED"
        elif not current_version or current_version in {"unknown", "not recorded", "not detected"}:
            status = "NOT VERIFIED"
        else:
            status = "SAME" if control_version == current_version else "DIFFERENT"
        entries.append({
            "software": label, "control_version": control_version or "not recorded",
            "new_run_version": current_version or "not detected", "status": status,
        })
    statuses = {entry["status"] for entry in entries}
    overall = "SAME" if statuses == {"SAME"} else "NOT THE SAME" if "DIFFERENT" in statuses else "NOT VERIFIED"
    return {"overall": overall, "entries": entries}

def reproducibility_record(protocol, study, control):
    """Separate retained scientific-run versions from report-runtime versions."""
    recorded = protocol.get("software", {}) if protocol else {}
    summary = read_json(study / "report" / "study_summary.json")
    figure_manifest = read_json(study / "report" / "report_figure_manifest.json")
    clustering = read_json(first(study, ["compounds/*/pose_analysis/clustering_manifest.json", "**/clustering_manifest.json"]))
    docking_manifest = read_key_value_tsv(first(study, ["compounds/*/seed_*/docking/run_manifest.tsv", "**/docking/run_manifest.tsv"]))
    receptor_preparation = receptor_preparation_record(study, control)
    retained_preparation_summary = summary.get("protocol_receptor_preparation_summary")
    if retained_preparation_summary and receptor_preparation.get("pdbfixer_used") is None:
        receptor_preparation["path"] = retained_preparation_summary
        if "PDBFixer was not needed" in retained_preparation_summary:
            receptor_preparation["pdbfixer_used"] = False
        elif "PDBFixer" in retained_preparation_summary:
            receptor_preparation["pdbfixer_used"] = True
    run_versions = retained_scientific_versions(study, summary, docking_manifest)
    report_runtime = {
        "docking_universal": package_version(),
        "python": sys.version.split()[0],
        "pymol": pymol_version(),
        "matplotlib": installed_version("matplotlib"),
        "reportlab": installed_version("reportlab"),
    }
    engine_version = run_versions["engine_version"]
    engine_source = docking_manifest.get("engine_source")
    if engine_source:
        engine_version += f" ({engine_source})"
    software = [
        {"role": "Scientific workflow", "software": "Docking Universal", "version": run_versions["docking_universal"]},
        {"role": "Ligand-free cavity detection", "software": "fpocket", "version": run_versions["fpocket"]},
        {"role": "Docking scores and poses", "software": "AutoDock Vina", "version": engine_version},
        {"role": "Receptor and ligand parameterization", "software": "Meeko", "version": run_versions["meeko"]},
        {"role": "Conditional conservative receptor repair", "software": "PDBFixer", "version": run_versions["pdbfixer"]},
        {"role": "Protonation/conformer preparation", "software": "MolScrub", "version": run_versions["molscrub"]},
        {"role": "Molecular graph, RMSD, clustering", "software": "RDKit", "version": run_versions["rdkit"]},
        {"role": "Molecular conversion/PLIP backend", "software": "Open Babel", "version": run_versions["openbabel"]},
        {"role": "Interaction calls", "software": "PLIP", "version": run_versions["plip"]},
        {"role": "3D rendering", "software": "PyMOL", "version": report_runtime["pymol"]},
        {"role": "Plots", "software": "Matplotlib", "version": report_runtime["matplotlib"]},
        {"role": "PDF generation", "software": "ReportLab", "version": report_runtime["reportlab"]},
        {"role": "Scientific workflow runtime", "software": "Python", "version": run_versions["python"]},
    ]
    references = [
        {"citation": "Eberhardt J, Santos-Martins D, Tillack AF, Forli S. AutoDock Vina 1.2.0: New Docking Methods, Expanded Force Field, and Python Bindings. J Chem Inf Model. 2021;61:3891-3898.", "url": "https://doi.org/10.1021/acs.jcim.1c00203"},
        {"citation": "Le Guilloux V, Schmidtke P, Tuffery P. Fpocket: an open source platform for ligand pocket detection. BMC Bioinformatics. 2009;10:168.", "url": "https://doi.org/10.1186/1471-2105-10-168"},
        {"citation": "Santos-Martins D, He Y, Eberhardt J, et al. Meeko: molecule parameterization and software interoperability for docking and beyond. J Chem Inf Model. 2025;65:13045-13050.", "url": "https://doi.org/10.1021/acs.jcim.5c02271"},
        {"citation": "PDBFixer: a tool for preparing PDB files for molecular simulation (version recorded above).", "url": "https://github.com/openmm/pdbfixer"},
        {"citation": "Eastman P, Swails J, Chodera JD, et al. OpenMM 7: Rapid development of high performance algorithms for molecular dynamics. PLoS Comput Biol. 2017;13:e1005659.", "url": "https://doi.org/10.1371/journal.pcbi.1005659"},
        {"citation": "Salentin S, Schreiber S, Haupt VJ, Adasme MF, Schroeder M. PLIP: fully automated protein-ligand interaction profiler. Nucleic Acids Res. 2015;43:W443-W447.", "url": "https://doi.org/10.1093/nar/gkv315"},
        {"citation": "Butina D. Unsupervised Data Base Clustering Based on Daylight's Fingerprint and Tanimoto Similarity: A Fast and Automated Way To Cluster Small and Large Data Sets. J Chem Inf Comput Sci. 1999;39:747-750.", "url": "https://doi.org/10.1021/ci9803381"},
        {"citation": "O'Boyle NM, Banck M, James CA, Morley C, Vandermeersch T, Hutchison GR. Open Babel: An open chemical toolbox. J Cheminform. 2011;3:33.", "url": "https://doi.org/10.1186/1758-2946-3-33"},
        {"citation": "RDKit: Open-source cheminformatics software.", "url": "https://www.rdkit.org/"},
        {"citation": f"The PyMOL Molecular Graphics System, Version {next(item['version'] for item in software if item['software'] == 'PyMOL')}, Schrodinger, LLC.", "url": "https://www.pymol.org/support.html"},
    ]
    return {
        "schema_name": "docking-universal-report-provenance", "schema_version": 1,
        "study": str(study), "control": str(control) if control else None,
        "software": software,
        "receptor_preparation": receptor_preparation,
        "control_to_new_run_version_check": compare_scientific_versions(recorded, run_versions) if protocol else None,
        "report_generation": report_runtime,
        "methods": {
            "cavity_detection": "fpocket geometric cavity detection, descriptor calculation, and recorded geometry/overlap filtering" if discover_cavity_record(study) else "not used in the retained report study",
            "docking_scores_and_poses": "AutoDock Vina",
            "interaction_detection": "PLIP rule-based calls; retained PLIP XML is authoritative",
            "interaction_diagram": figure_manifest.get("interaction_diagram_renderer", "native SDF plus PLIP XML"),
            "rmsd_and_clustering": clustering.get("method", "RDKit symmetry-aware heavy-atom CalcRMS without fitting; Butina clustering"),
            "cluster_cutoff_angstrom": clustering.get("cluster_rmsd_angstrom", 2.0),
            "single_cluster_policy": "Use the lowest-energy member as the sole representative",
            "receptor_preparation": receptor_preparation["path"],
        },
        "references": references,
    }


def retain_used_report_methods(provenance, cavity, has_docking):
    """Keep only software and references supported by retained run evidence."""
    preparation = provenance.get("receptor_preparation", {})
    used_software = {
        "Docking Universal", "Meeko", "PyMOL", "Matplotlib", "ReportLab", "Python",
    }
    if cavity:
        used_software.add("fpocket")
    if has_docking:
        used_software.update({"AutoDock Vina", "MolScrub", "RDKit", "Open Babel", "PLIP"})
    if preparation.get("pdbfixer_used"):
        used_software.add("PDBFixer")

    version_check = provenance.get("control_to_new_run_version_check")
    if version_check and not preparation.get("pdbfixer_used"):
        version_check["entries"] = [
            entry for entry in version_check.get("entries", [])
            if entry.get("software") != "PDBFixer"
        ]
        statuses = {entry["status"] for entry in version_check["entries"]}
        version_check["overall"] = (
            "SAME" if statuses == {"SAME"}
            else "NOT THE SAME" if "DIFFERENT" in statuses
            else "NOT VERIFIED"
        )

    provenance["software"] = [
        item for item in provenance.get("software", [])
        if item.get("software") in used_software
    ]
    for item in provenance["software"]:
        if item.get("software") == "Meeko":
            item["role"] = (
                "Receptor and ligand parameterization"
                if has_docking else "Receptor preparation"
            )

    def reference_was_used(reference):
        citation = reference.get("citation", "")
        if "AutoDock Vina" in citation:
            return has_docking
        if "Fpocket" in citation:
            return bool(cavity)
        if "Meeko:" in citation:
            return True
        if "PDBFixer:" in citation or "OpenMM 7:" in citation:
            return bool(preparation.get("pdbfixer_used"))
        if any(name in citation for name in ("PLIP:", "Butina D.", "Open Babel", "RDKit:")):
            return has_docking
        if "PyMOL Molecular Graphics System" in citation:
            return True
        return False

    provenance["references"] = [
        reference for reference in provenance.get("references", [])
        if reference_was_used(reference)
    ]
    return provenance


def require_complete_used_versions(provenance):
    """Refuse to publish a report with incomplete used-software provenance."""
    missing_values = {
        "", "unknown", "not recorded", "not detected",
        "detected; version not recorded",
    }
    problems = []
    for item in provenance.get("software", []):
        version = str(item.get("version", "") or "").strip()
        normalized = version.lower()
        if normalized in missing_values or normalized.startswith("multiple retained versions:"):
            problems.append(f"{item.get('software', 'unknown software')}: {version or 'missing'}")
    comparison = provenance.get("control_to_new_run_version_check") or {}
    for entry in comparison.get("entries", []):
        for side, key in (("control", "control_version"), ("new run", "new_run_version")):
            version = str(entry.get(key, "") or "").strip()
            normalized = version.lower()
            if normalized in missing_values or normalized.startswith("multiple retained versions:"):
                problems.append(
                    f"{entry.get('software', 'unknown software')} ({side}): "
                    f"{version or 'missing'}"
                )
    if problems:
        raise SystemExit(
            "PDF report error: complete version provenance is required for every "
            "software component used. Recover or record versions for: " + "; ".join(problems)
        )


def reproducibility_summary(provenance, cavity, has_docking):
    preparation = provenance["receptor_preparation"]
    sentences = []
    if cavity:
        sentences.append(
            "fpocket supplied ligand-free geometric cavity candidates and descriptors; "
            "the report records the selected docking box separately."
        )
    sentences.append(f"Receptor preparation path: {preparation['path']}.")
    if has_docking:
        cutoff = provenance["methods"]["cluster_cutoff_angstrom"]
        sentences.append(
            "AutoDock Vina produced docking scores and poses. PLIP supplied rule-based "
            "protein-ligand interaction calls, with retained PLIP XML as the authoritative "
            "interaction record. RDKit supplied symmetry-aware heavy-atom RMSD calculations "
            f"and Butina clustering at a {cutoff} A cutoff. PyMOL produced the molecular "
            "panels, and ReportLab assembled this PDF."
        )
    else:
        sentences.append(
            "No ligand docking, scoring, pose clustering, or interaction analysis was performed. "
            "PyMOL produced the structural panels, and ReportLab assembled this PDF."
        )
    return " ".join(sentences)


def combine_horizontal_diagrams(diagrams, output):
    """Make the compact horizontal A/B/C interaction panel used in reports."""
    from PIL import Image, ImageChops, ImageDraw, ImageFont

    images = []
    trim_padding = 24
    for _, path in diagrams[:3]:
        source = Image.open(path).convert("RGB")
        difference = ImageChops.difference(source, Image.new("RGB", source.size, "white"))
        content_bbox = difference.getbbox()
        if content_bbox:
            left, top, right, bottom = content_bbox
            source = source.crop((
                max(0, left - trim_padding),
                max(0, top - trim_padding),
                min(source.width, right + trim_padding),
                min(source.height, bottom + trim_padding),
            ))
        images.append(source)
    if not images:
        return False
    width = 2400
    side_margin, gap = 35, 22
    top_margin, bottom_margin, label_height = 10, 18, 46
    slot_width = (width - 2 * side_margin - gap * (len(images) - 1)) // len(images)
    font_path = Path("/System/Library/Fonts/Helvetica.ttc")
    font = ImageFont.truetype(str(font_path), 42) if font_path.is_file() else ImageFont.load_default()
    resized = []
    for source in images:
        ratio = min(1.0, slot_width / source.width)
        resized.append(source.resize(
            (max(1, int(source.width * ratio)), max(1, int(source.height * ratio))),
            Image.Resampling.LANCZOS,
        ))
    panel_height = max(source.height for source in resized)
    height = top_margin + label_height + panel_height + bottom_margin
    canvas = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(canvas)
    for index, source in enumerate(resized):
        x = side_margin + index * (slot_width + gap) + (slot_width - source.width) // 2
        y = top_margin + label_height + (panel_height - source.height) // 2
        canvas.paste(source, (x, y))
        draw.text((x + 4, top_margin), "ABC"[index], fill="black", font=font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, dpi=(220, 220))
    return True

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("study", type=Path)
    ap.add_argument("--control", type=Path)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--include-control-appendix", action="store_true", help="include detailed control interactions and protocol provenance")
    args = ap.parse_args()

    args.study = args.study.expanduser().resolve()
    if args.control:
        args.control = args.control.expanduser().resolve()
    else:
        args.control = discover_control(args.study)

    summary = read_json(args.study / "report" / "study_summary.json")
    workflow_is_exploratory = summary.get("workflow") == "exploratory"
    summary_protocol_type = str(summary.get("protocol_type", "")).strip().lower()
    reuses_control_protocol = (
        summary_protocol_type == "control-validated"
        or (not summary_protocol_type and summary.get("study_status") == "CONTROL_APPROVED")
    )
    # High-level screening materializes a selected .duprotocol bundle and
    # records the resulting protocol.json in the summary.  Infer that control
    # root while it is still available so inherited pose-recovery evidence is
    # included without requiring a second, manual --control argument.
    if not args.control and not workflow_is_exploratory and reuses_control_protocol:
        recorded_protocol = Path(str(summary.get("approved_protocol", ""))).expanduser()
        if recorded_protocol.is_file():
            args.control = recorded_protocol.resolve().parent

    # Figures are first-class report outputs. Rebuild them from retained run
    # artifacts so the final PDF never depends on manually prepared images.
    figure_script = Path(__file__).with_name("docking-universal-report-figures.py")
    figure_command = [sys.executable, str(figure_script), str(args.study)]
    if args.control:
        figure_command += ["--control", str(args.control)]
    figure_result = subprocess.run(figure_command, capture_output=True, text=True)
    if figure_result.returncode != 0:
        detail = figure_result.stderr.strip() or figure_result.stdout.strip() or f"exit status {figure_result.returncode}"
        raise SystemExit(f"Automatic report-figure generation failed: {detail}")

    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, KeepTogether

    # A standalone control report is the run that established the protocol and
    # therefore carries the full control evidence automatically.  The same
    # conditional detail break used by combined reports prevents blank pages.
    if summary.get("workflow") == "control":
        args.include_control_appendix = True
    compounds = summary.get("compounds", [])
    styles = getSampleStyleSheet()
    # One spacing system is shared by every report scenario.  Scenario logic
    # changes content, never typography, heading gaps, or block rhythm.
    styles["Title"].fontSize = 20
    styles["Title"].leading = 24
    styles["Title"].spaceAfter = 18
    styles["Heading1"].fontSize = 18
    styles["Heading1"].leading = 22
    styles["Heading1"].spaceBefore = 10
    styles["Heading1"].spaceAfter = 6
    styles["Heading1"].keepWithNext = True
    styles["Heading2"].fontSize = 14
    styles["Heading2"].leading = 17
    styles["Heading2"].spaceBefore = 8
    styles["Heading2"].spaceAfter = 5
    styles["Heading2"].keepWithNext = True
    styles["BodyText"].fontSize = 10
    styles["BodyText"].leading = 13
    styles["BodyText"].spaceBefore = 0
    styles["BodyText"].spaceAfter = 0
    styles.add(ParagraphStyle(name="SmallDU", parent=styles["BodyText"], fontSize=8, leading=10, spaceBefore=0, spaceAfter=0))
    styles.add(ParagraphStyle(name="ReferenceDU", parent=styles["BodyText"], fontSize=7, leading=8, spaceBefore=0, spaceAfter=2))
    styles.add(ParagraphStyle(name="CaptionDU", parent=styles["Heading2"], alignment=TA_CENTER, fontSize=11, leading=14, spaceBefore=8, spaceAfter=5))

    def image(path, width=7.0, height=4.5):
        item = Image(str(path))
        item._restrictSize(width*inch, height*inch)
        item.hAlign = "CENTER"
        return item
    def table(rows, widths, compact=False):
        item = Table(rows, colWidths=widths, repeatRows=1, hAlign="CENTER")
        item.setStyle(TableStyle([
            ("BACKGROUND",(0,0),(-1,0),colors.HexColor("#d9e2f3")),
            ("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),
            ("GRID",(0,0),(-1,-1),.35,colors.HexColor("#777777")),
            ("FONTSIZE",(0,0),(-1,-1),7 if compact else 8), ("LEADING",(0,0),(-1,-1),8 if compact else 10),
            ("VALIGN",(0,0),(-1,-1),"TOP"),
            ("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#f7f7f7")]),
            ("LEFTPADDING",(0,0),(-1,-1),6), ("RIGHTPADDING",(0,0),(-1,-1),6),
            ("TOPPADDING",(0,0),(-1,-1),2.5 if compact else 4), ("BOTTOMPADDING",(0,0),(-1,-1),2.5 if compact else 4)]))
        return item

    # A screen that reuses an exploratory protocol still begins with protocol
    # provenance, not a newly performed cavity-search section. Only a direct
    # raw exploratory workflow owns the cavity results in this study folder.
    protocol_path = choose_protocol(args.control) if args.control and not workflow_is_exploratory else None
    protocol = read_json(protocol_path)

    # Build a human-readable report heading from run metadata. Directory-style
    # study identifiers remain machine metadata and are not used as titles.
    inventory = read_json(args.study / "inputs" / "compound_library_inventory.json")
    inventory_rows = inventory.get("compounds", inventory.get("entries", []))
    inventory_by_id = {str(x.get("compound_id")): x for x in inventory_rows}
    ligand_names = []
    for compound in summary.get("compounds", []):
        cid = str(compound.get("compound_id", ""))
        inventory_row = inventory_by_id.get(cid, {})
        name = display_compound_name(compound.get("compound_name") or inventory_row.get("compound_name") or cid, inventory_row.get("source"))
        ligand_names.append(name)

    receptor_source = protocol.get("locked_inputs", {}).get("receptor", "") if protocol else ""
    if not receptor_source:
        receptor_source = summary.get("configured_locked_inputs", {}).get("receptor", "")
    title_manifest_path = first(args.study,["compounds/*/seed_*/docking/run_manifest.tsv","**/docking/run_manifest.tsv"])
    if not receptor_source:
        receptor_source = read_key_value_tsv(title_manifest_path).get("receptor", "")
    if not receptor_source:
        input_receptor = first(args.study, ["inputs/*.pdb"])
        receptor_source = str(input_receptor or "")
    if not receptor_source:
        prepared_receptor = first(args.study, ["preparation/*_receptor_prep/receptor/*.pdb", "**/*_receptor_prep/receptor/*.pdb"])
        receptor_source = str(prepared_receptor or "")
    target_name = Path(receptor_source).stem if receptor_source else "Unspecified target"
    if not ligand_names and summary.get("workflow") == "control" and args.control:
        control_values = read_key_value_tsv(args.control / "run_manifest.tsv")
        ligand_names = [control_values.get("ligand_id", "ligand").split(":", 1)[0]]
    control_title_sdf = first(args.control, ["00_inputs/*_experimental.sdf", "**/crystal_ligand.sdf"]) if args.control else None
    control_title_name = control_title_sdf.stem.removesuffix("_experimental") if control_title_sdf else None
    out = args.out or args.study / "report" / descriptive_report_name(target_name, ligand_names, summary)
    out.parent.mkdir(parents=True, exist_ok=True)
    if protocol and control_title_name:
        study_descriptor = f"Target: {target_name} | Ligand: {control_title_name}"
    elif protocol or workflow_is_exploratory:
        # Protocol, control, and exploratory pocket-selection sections are
        # target-level records.  A subsequently docked ligand is named only
        # within its own docking-results section.
        study_descriptor = f"Target: {target_name}"
    elif len(ligand_names) == 1:
        study_descriptor = f"Target: {target_name} | Ligand: {ligand_names[0]}"
    elif ligand_names:
        study_descriptor = f"Target: {target_name} | Ligands: {len(ligand_names)} compounds"
    else:
        study_descriptor = f"Target: {target_name}"

    cavity = discover_cavity_record(args.study) if workflow_is_exploratory or not protocol else None
    # Inventories and study manifests describe intended inputs, not completed
    # docking.  Require retained pose-cluster results before adding docking
    # sections to a preparation-only report.
    has_docking = any(
        path.is_file() and path.stat().st_size > 0
        for path in args.study.glob("compounds/*/pose_analysis/cluster_summary.csv")
    )
    report_title = (
        "Docking Universal - Ligand-Free Cavity and Docking Report" if cavity and has_docking
        else "Docking Universal - Ligand-Free Cavity Report" if cavity
        else "Docking Universal - Docking Study Report"
    )
    story = [Paragraph(f"{report_title}<br/><font size=\"12\">Report generator version {package_version()}</font>", styles["Title"])]
    if study_descriptor:
        story += [Paragraph(study_descriptor, styles["Heading2"]), Spacer(1,8)]
    if cavity:
        story += [Paragraph("Interpretive status: exploratory site selection without a bound-ligand pose-recovery control", styles["BodyText"]), Spacer(1,8)]
    # An exploratory report begins with the pocket configuration and its A/B
    # cavity figure.  A docking-at-a-glance table before that figure implies
    # an approved protocol and reverses the actual workflow order.
    at_a_glance = None
    at_a_glance_widths = [2.55*inch, 4.15*inch]
    at_a_glance_note = None
    compound_results = []
    if has_docking and compounds:
        compound_results = compound_result_records(args.study, compounds, ligand_names)
        if len(compound_results) == 1:
            at_a_glance = single_compound_summary_rows(compound_results[0])
        else:
            at_a_glance = [["Ligand", "Best Vina score", "Top cluster", "Clusters", "Status"]]
            for result in compound_results:
                score = result["best_energy_kcal_per_mol"]
                at_a_glance.append([
                    result["name"],
                    f"{score} kcal/mol" if score != "Unavailable" else score,
                    result["top_cluster"],
                    result["cluster_count"] or "Unavailable",
                    result["status"],
                ])
            at_a_glance_widths = [2.2*inch, 1.4*inch, 1.05*inch, .85*inch, 1.2*inch]
            at_a_glance_note = (
                "Each row is the best retained result for that ligand. Docking scores are "
                "ranking estimates and are not cross-ligand binding-affinity measurements."
            )
    figure_number = 1
    section_number = 1

    # Every workflow begins by recording the actual docking configuration.
    # Exploratory studies have no approved control protocol, but their
    # configured Vina inputs are still the first scientific record.
    if workflow_is_exploratory:
        manifest_path = first(args.study,["compounds/*/seed_*/docking/run_manifest.tsv","**/docking/run_manifest.tsv"])
        manifest = read_key_value_tsv(manifest_path)
        configured = summary.get("configured_docking_parameters", {})
        locked = summary.get("configured_locked_inputs", {})
        seed_count = len(list(args.study.glob("compounds/*/seed_*"))) or len(configured.get("seeds", []))
        engine = manifest.get("engine") or summary.get("configured_engine", "NA")
        engine_version = manifest.get("engine_version") or summary.get("configured_engine_version", "NA")
        receptor = manifest.get("receptor") or locked.get("receptor", "NA")
        docking_box = manifest.get("config") or locked.get("box", "NA")
        story += [Paragraph(f"{section_number}. Configured docking protocol",styles["Heading1"]),
          Paragraph("This section records the settings used for this exploratory study. No target-specific bound-ligand pose-recovery control was available.",styles["BodyText"]),Spacer(1,6),
          table([["Parameter","Configured value"],["Validation status",summary.get("protocol_validation_status", "Not evaluated by bound-ligand control")],["Engine",engine],["Engine version",engine_version],["Exhaustiveness",manifest.get("exhaustiveness") or configured.get("exhaustiveness","NA")],["Modes per job",manifest.get("num_modes") or configured.get("num_modes","NA")],["Energy range",f"{manifest.get('energy_range_kcal_per_mol') or configured.get('energy_range_kcal_per_mol','NA')} kcal/mol"],["Independent seeds",seed_count or "NA"],["Receptor",Path(receptor).name],["Docking box",Path(docking_box).name]], [2.55*inch,4.15*inch], compact=True),Spacer(1,10)]
        section_number += 1

    if cavity:
        selected = cavity["selected"]
        detail = cavity["detail"]
        descriptor = cavity["descriptors"].get(cavity["selected_file"], {})
        box_dimensions = cavity["box_dimensions"]
        box_volume = box_dimensions[0] * box_dimensions[1] * box_dimensions[2] if box_dimensions else None
        selected_count = sum(row.get("decision") == "selected" for row in cavity["rows"])
        skipped_count = sum(row.get("decision") == "skipped" for row in cavity["rows"])
        story += [
            Paragraph(f"{section_number}. Exploratory pocket configuration", styles["Heading1"]),
            Paragraph(
                "No bound-ligand pose-recovery control was available. In its place, this section records how fpocket-generated cavity hypotheses were filtered and which docking box was selected. This documents site selection, but it does not validate the biological site or the accuracy of docked poses.",
                styles["BodyText"],
            ), Spacer(1,6),
            table([
                ["Pocket configuration", "Recorded value"],
                ["Interpretive status", "Exploratory; not evaluated by a bound-ligand pose-recovery control"],
                ["Selected docking pocket", cavity["selected_file"] or "Not resolved"],
                ["fpocket eligibility threshold used", summary.get("cavity_score_threshold_used", "not recorded")],
                ["fpocket pocket score (Figure 1A)", selected.get("score", "NA")],
                ["Composite selection priority", selected.get("rank_score", "NA")],
                ["fpocket druggability descriptor", descriptor.get("druggability_score", "NA")],
                ["Docking-box center (A)", ", ".join(selected.get(key, "NA") for key in ("center_x", "center_y", "center_z"))],
                ["Docking-box dimensions (A)", " x ".join(f"{value:g}" for value in box_dimensions) if box_dimensions else "NA"],
            ], [2.55*inch, 4.15*inch], compact=True), Spacer(1,8),
        ]
        cavity_ab = args.study / "report" / "cavity_panels_AB.png"
        cavity_a = args.study / "report" / "cavity_panel_A_selection.png"
        cavity_b = args.study / "report" / "cavity_panel_B_structure.png"
        cavity_overview = args.study / "report" / "cavity_selected_box.png"
        if cavity_ab.is_file():
            story += [KeepTogether([
                image(cavity_ab, 7.0, 4.1),
                Paragraph(
                    f"<b>Figure {figure_number}. Exploratory pocket analysis.</b> (A) Weighted fpocket composite priority for all candidates that passed the score and geometry eligibility filters, ordered by that priority. The weighting is <i>fpocket pocket score × exp(−distance from the protein centroid / 10 A)</i>; it favors interior pockets. The colored candidates are the three retained for review and color-match Panel B; gray candidates were not retained for review. The unweighted fpocket pocket score is recorded in the configuration table. (B) The retained pocket hypotheses are shown as color-matched surfaces on the receptor. These geometric pocket surfaces are not experimentally observed molecular surfaces, and fpocket scores are not binding-affinity estimates.",
                    styles["SmallDU"],
                ),
            ]), Spacer(1,8)]
            figure_number += 1
        elif cavity_a.is_file():
            story += [
                image(cavity_a, 6.5, 3.8),
                Paragraph(
                    f"<b>Figure {figure_number}. Ligand-free cavity selection.</b> Eligible cavities are shown in their integer evaluation order. Order 1 has the highest composite priority, calculated from the fpocket score with a penalty for distance from the protein interior; gray candidates were subsequently removed because their docking boxes overlapped a higher-priority retained box. The red point identifies the cavity selected to define the docking box. fpocket scores are geometric pocket-ranking outputs, not binding-affinity estimates.",
                    styles["SmallDU"],
                ), Spacer(1,8),
            ]
            figure_number += 1
        if cavity_b.is_file() and not cavity_ab.is_file():
            story += [image(cavity_b, 6.5, 3.8), Paragraph(f"<b>Figure {figure_number}. Selected cavity and docking box structural review.</b>", styles["SmallDU"]), Spacer(1,8)]
            figure_number += 1
        if cavity_overview.is_file():
            story += [KeepTogether([
                # This is a verification view subordinate to the primary A/B
                # pocket-analysis panel, so keep it visibly smaller.
                image(cavity_overview, 5.25, 3.35),
                Paragraph(
                    f"<b>Figure {figure_number}. Chosen pocket and docking box.</b> The receptor is shown as a gray cartoon, the selected alpha-sphere-derived pocket surface in translucent red, the selected center in yellow, and the docking box as an orange wireframe. Red matches the selected candidate in Figure {figure_number - 1}. This records the region chosen to proceed; it does not establish that the pocket is biologically correct.",
                    styles["SmallDU"],
                ),
            ]), Spacer(1,8)]
            figure_number += 1
        story.append(PageBreak() if not has_docking else Spacer(1,10))
        section_number += 1

    if cavity and not has_docking:
        provenance = retain_used_report_methods(
            reproducibility_record(protocol, args.study, args.control), cavity, has_docking
        )
        require_complete_used_versions(provenance)
        software = provenance["software"]
        references = provenance["references"]
        (args.study / "report" / "software_versions_and_references.json").write_text(json.dumps(provenance, indent=2) + "\n")
        provenance_rows = [["Result element", "Software", "Version used"]]
        for item in software:
            provenance_rows.append([Paragraph(item["role"], styles["SmallDU"]), Paragraph(item["software"], styles["SmallDU"]), Paragraph(str(item["version"]), styles["SmallDU"])])
        story += [
            # A receptor-only report has no docking-results section, so the
            # reproducibility record follows the two preparation sections.
            Paragraph(f"{section_number}. Reproducibility, software, and references", styles["Heading1"]),
            Paragraph(reproducibility_summary(provenance, cavity, has_docking), styles["BodyText"]),
            Spacer(1,8),
        ]
        story += pdbfixer_report_note(provenance["receptor_preparation"], out, styles)
        story += adfr_fallback_report_note(provenance["receptor_preparation"], out, styles)
        story += user_approved_removal_report_note(provenance["receptor_preparation"], out, styles)
        story += ccd_modification_report_note(provenance["receptor_preparation"], out, styles)
        story += [Paragraph("Software versions used for this report", styles["Heading2"]),
            table(provenance_rows, [2.5*inch, 1.65*inch, 3.05*inch], compact=True),
            Spacer(1,10), Paragraph("Scientific and software references", styles["Heading2"]),
        ]
        for index, reference in enumerate(references, start=1):
            story += [Paragraph(f"{index}. {reference['citation']} <link href=\"{reference['url']}\"><font color=\"#1f4e79\">{reference['url']}</font></link>", styles["ReferenceDU"])]
        SimpleDocTemplate(str(out),pagesize=letter,leftMargin=.65*inch,rightMargin=.65*inch,topMargin=.6*inch,bottomMargin=.6*inch,title="Docking Universal ligand-free cavity report").build(story)
        print(f"PDF report: {out}")
        return

    if protocol:
        a=protocol.get("acceptance",{}); p=protocol.get("parameters",{}); g=protocol.get("global_top_ranked_pose",{}); b=protocol.get("global_best_sampled_pose",{})
        recorded_software = protocol.get("software", {})
        locked_inputs = protocol.get("locked_inputs", {})
        history=protocol.get("escalation_history",[]); last=history[-1] if history else {}
        passed=bool(a.get("sampling_pass") and a.get("ranking_pass") and a.get("seed_requirement_pass"))
        control_ligand_sdf = first(args.control, ["00_inputs/*_experimental.sdf", "**/crystal_ligand.sdf"]) if args.control else None
        control_ligand_name = (
            control_ligand_sdf.stem.removesuffix("_experimental")
            if control_ligand_sdf
            else protocol.get("control_evidence", {}).get("compound", "unspecified ligand")
        )
        approval_origin = "Approved during this run" if args.include_control_appendix else "Approved previously and reused for this run"
        rows=[["Approved docking protocol","Selected value"],
          ["Protocol file name", protocol_lookup_filename(args.study, args.control, protocol_path, summary)],
          ["Approval provenance", approval_origin],
          ["Control approval date (UTC)", protocol.get("created_utc", "not recorded by this older protocol")],
          ["Prepared receptor", Path(locked_inputs.get("receptor", "NA")).name],
          ["Locked docking box / pocket",Path(locked_inputs.get("box", "NA")).name],
          ["Engine",protocol.get("engine","NA")],
          ["Tier",protocol.get("calibration_tier","NA")],
          ["Exhaustiveness",p.get("exhaustiveness","NA")],
          ["Modes per job",p.get("num_modes","NA")],
          ["Conformers per state",p.get("conformers_per_state","NA")],
          ["Independent seeds",len(p.get("seeds",[]))],
          ["Charge model",p.get("charge_model","NA")],
          ["pH",p.get("ph","NA")],
          ["Conformer force field",p.get("forcefield","mmff94")],
          ["Tautomers enumerated",p.get("tautomers_enumerated",True)],
          ["Conformer RMSD pruning",f"{p.get('rmsd_prune_angstrom',0.75)} A"]]
        story += [
          Paragraph(f"{section_number}. Configured docking protocol", styles["Heading1"]),
          Paragraph("This table identifies the reusable target-matched protocol, records whether it was approved during this run or reused from an earlier run, and lists its locked docking settings.", styles["BodyText"]), Spacer(1,6),
          table(rows,[2.55*inch,4.15*inch], compact=True),
        ]
        if args.include_control_appendix:
            story += [PageBreak(),
              Paragraph(f"{section_number + 1}. Experimental control redocking results: {control_ligand_name}", styles["Heading1"]),
              Paragraph(f"This retrospective control tests whether the protocol reproducibly recovers the experimental pose of {control_ligand_name}. PASS requires sampling, ranking, and independent-seed criteria to pass. It supports use of the selected protocol for this target, but does not establish affinity or prospective pose accuracy.", styles["BodyText"]), Spacer(1,6),
            ]
        control_ab=first(args.control,["report/control_panels_AB.png","**/control_panels_AB.png"]) if args.control else None
        control_a=first(args.control,["report/control_panel_A*.png","**/control_panel_A*.png"]) if args.control else None
        control_b=first(args.control,["report/control_panel_B_overlay.png","report/control_panel_B*.png","**/control_panel_B*.png"]) if args.control else None
        experimental_reference=first(args.control,["00_inputs/*_experimental.sdf","**/crystal_ligand.sdf"]) if args.control else None
        experimental_label=experimental_reference.stem.removesuffix("_experimental") if experimental_reference else "experimental ligand"
        # A continued screen carries the control result as compact provenance.
        # Repeating its figures is reserved for an explicitly requested appendix.
        if args.include_control_appendix and control_ab:
            story += [KeepTogether([image(control_ab,7.0,4.1),Paragraph(f"<b>Figure {figure_number}. Retrospective control performance and pose recovery.</b> (A) Control-cluster Vina score versus symmetry-aware, no-fit heavy-atom RMSD to experimental {experimental_label} in the receptor coordinate frame. (B) Experimental ligand (magenta), lowest-energy pose (red), and lowest-RMSD pose (blue) superimposed in that frame; receptor residues within 5 A of the displayed ligands are gray.",styles["SmallDU"])]),Spacer(1,8)]
            figure_number += 1
        elif control_ab:
            # Reused protocols retain the single approved A/B control figure
            # as validation evidence, without repeating the detailed control
            # PLIP interaction diagrams.
            story += [KeepTogether([
                Paragraph("Control pose-recovery results", styles["Heading2"]),
                image(control_ab,7.0,3.6),
                Paragraph(f"<b>Figure {figure_number}. Retrospective control performance and pose recovery.</b> (A) Control-cluster Vina score versus symmetry-aware, no-fit heavy-atom RMSD to experimental {experimental_label} in the receptor coordinate frame. (B) Experimental ligand (magenta), lowest-energy pose (red), and lowest-RMSD pose (blue) superimposed in that frame; receptor residues within 5 A of the displayed ligands are gray.",styles["SmallDU"]),
            ]), PageBreak()]
            figure_number += 1
        elif args.include_control_appendix:
            if control_a: story += [Paragraph("Control Panel A - score and RMSD landscape",styles["CaptionDU"]),image(control_a),Spacer(1,5)]
            if control_b: story += [KeepTogether([Paragraph("Control Panel B - superimposed experimental and redocked poses",styles["CaptionDU"]),image(control_b,7.0,3.8),Paragraph("Experimental ligand: magenta; lowest-energy docked pose: red; lowest-RMSD docked pose: blue. Nearby receptor residues are gray.",styles["SmallDU"])]),Spacer(1,5)]
            if not control_a and not control_b:
                top_ranked_control = first(args.control, ["**/selected_visuals/top_ranked.png", "**/evidence/top_ranked.png"])
                best_sampled_control = first(args.control, ["**/selected_visuals/best_sampled.png", "**/evidence/best_sampled.png"])
                if top_ranked_control:
                    story += [image(top_ranked_control, 6.5, 3.8), Paragraph(f"<b>Figure {figure_number}. Top-ranked retained control pose.</b> This is the globally lowest-energy redocked control pose retained by the approved protocol.", styles["SmallDU"]), Spacer(1,8)]
                    figure_number += 1
                if best_sampled_control:
                    story += [image(best_sampled_control, 6.5, 3.8), Paragraph(f"<b>Figure {figure_number}. Best-sampled retained control pose.</b> This is the globally lowest-RMSD redocked control pose retained by the approved protocol.", styles["SmallDU"]), Spacer(1,8)]
                    figure_number += 1
        control_diagrams = [
            (first(args.control,["report/control_experimental_plip2d.png", "**/control_experimental_plip2d.png", "**/experimental_interactions.png"]), f"Experimental {experimental_label} pose used as the control reference."),
            (first(args.control,["report/control_top_ranked_plip2d.png", "**/control_top_ranked_plip2d.png", "**/top_ranked_interactions.png"]), f"Globally lowest-energy redocked pose (Vina score {g.get('top_score_affinity_kcal_per_mol','NA')} kcal/mol; RMSD {g.get('top_score_rmsd_angstrom',g.get('best_rmsd_angstrom','NA'))} A)."),
            (first(args.control,["report/control_lowest_rmsd_plip2d.png", "**/control_lowest_rmsd_plip2d.png", "**/best_sampled_interactions.png"]), f"Globally lowest-RMSD redocked pose (RMSD {b.get('best_rmsd_angstrom','NA')} A)."),
        ] if args.control and args.include_control_appendix else []
        control_diagrams = [(path, description) for path, description in control_diagrams if path]
        if control_diagrams:
            # The approved control presentation is one compact A/B/C panel,
            # matching the new-docking interaction panel.  Individual PLIP
            # images remain available as retained artifacts, but are not
            # expanded into three inconsistent report figures.
            composite = args.control / "report" / "control_interactions_ABC.png"
            if combine_horizontal_diagrams([(None, path) for path, _ in control_diagrams], composite):
                story += [Paragraph("Control interaction diagrams",styles["Heading2"]),
                    image(composite,6.8,2.45),
                    Paragraph(f"<b>Figure {figure_number}. SDF-aware PLIP interaction diagrams for control ligand {experimental_label}.</b> A is the experimental reference pose, B is the globally lowest-energy redocked pose, and C is the lowest-RMSD redocked pose. Ligand chemistry comes from the retained SDF files; interaction calls come from the retained PLIP XML.",styles["SmallDU"]), Spacer(1,6)]
                figure_number += 1
            story.append(PageBreak())
        elif args.include_control_appendix:
            story.append(PageBreak())
    elif not workflow_is_exploratory:
        manifest_path = first(args.study,["compounds/*/seed_*/docking/run_manifest.tsv","**/docking/run_manifest.tsv"])
        manifest = read_key_value_tsv(manifest_path)
        configured = summary.get("configured_docking_parameters", {})
        locked = summary.get("configured_locked_inputs", {})
        configured_seeds = configured.get("seeds", [])
        seed_count = len(list(args.study.glob("compounds/*/seed_*"))) or len(configured_seeds)
        engine = manifest.get("engine") or summary.get("configured_engine", "NA")
        engine_version = manifest.get("engine_version") or summary.get("configured_engine_version", "NA")
        validation_status = summary.get("protocol_validation_status", "Not evaluated by bound-ligand control")
        receptor = manifest.get("receptor") or locked.get("receptor", "NA")
        docking_box = manifest.get("config") or locked.get("box", "NA")
        configured_rows = [["Parameter", "Configured value"]]
        if summary.get("protocol_type"):
            configured_rows += [
                ["Protocol file name", summary.get("approved_protocol_file_name", "not recorded")],
                ["Protocol type", {
                    "control-validated": "Control-validated",
                    "ligand-guided-exploratory": "Ligand-guided exploratory",
                    "site-guided-exploratory": "Site-guided exploratory",
                }.get(summary["protocol_type"], str(summary["protocol_type"]))],
                ["Evidence basis", summary.get("protocol_evidence_basis", "not recorded")],
                ["Screening authority", summary.get("protocol_screening_authority", "not recorded")],
            ]
        configured_rows += [
            ["Validation status", validation_status], ["Engine", engine], ["Engine version", engine_version],
            ["Exhaustiveness", manifest.get("exhaustiveness") or configured.get("exhaustiveness", "NA")],
            ["Modes per job", manifest.get("num_modes") or configured.get("num_modes", "NA")],
            ["Energy range", f"{manifest.get('energy_range_kcal_per_mol') or configured.get('energy_range_kcal_per_mol', 'NA')} kcal/mol"],
            ["Independent seeds", seed_count or "NA"], ["Receptor", Path(receptor).name],
            ["Docking box", Path(docking_box).name],
        ]
        story += [Paragraph(f"{section_number}. Configured docking protocol",styles["Heading1"]),
          Paragraph("This section records the reusable protocol, its scientific evidence basis, and the locked settings selected for this study.",styles["BodyText"]),Spacer(1,6),
          table(configured_rows, [2.55*inch,4.15*inch], compact=True),PageBreak()]

    result_number = section_number if workflow_is_exploratory else section_number + (2 if protocol and args.include_control_appendix else 1)
    result_heading = "Ligand docking results"
    story += [Paragraph(f"{result_number}. {result_heading}",styles["Heading1"])]
    if at_a_glance:
        story += [
            Paragraph("Summary of docking results", styles["Heading2"]),
            table(at_a_glance, at_a_glance_widths, compact=len(compounds) > 1),
        ]
        if at_a_glance_note:
            story += [Spacer(1,4), Paragraph(at_a_glance_note, styles["SmallDU"])]
        story += [Spacer(1,10)]
    shared_panel = first(args.study,["report/study_panels_AB.png"]) if len(compounds) == 1 else None
    inventory = read_json(args.study / "inputs" / "compound_library_inventory.json")
    inventory_rows = inventory.get("compounds", inventory.get("entries", []))
    inventory_by_id = {str(x.get("compound_id")): x for x in inventory_rows}
    display_names = {}
    compound_results_by_id = {record["compound_id"]: record for record in compound_results}
    report_compounds = compounds or [{"compound_name":args.study.name,"compound_id":""}]
    for compound_index, compound in enumerate(report_compounds):
        cid=str(compound.get("compound_id", "")); inventory_row=inventory_by_id.get(cid, {}); name=display_compound_name(compound.get("compound_name") or inventory_row.get("compound_name") or cid, inventory_row.get("source"))
        display_names[cid] = name
        summary_protocol_type = summary.get("protocol_type")
        if protocol:
            scope_text = (
                "Docking used the target-matched protocol established and approved by the control reported above."
                if args.include_control_appendix
                else "Docking used the existing approved target-matched protocol shown above."
            )
        elif summary_protocol_type == "control-validated":
            scope_text = "Docking used the control-validated target-matched protocol identified above."
        elif summary_protocol_type in {"ligand-guided-exploratory", "site-guided-exploratory"}:
            scope_text = (
                "Docking used the explicitly selected exploratory protocol identified above. "
                "No target-specific bound-ligand pose-recovery control was supplied, so pose-recovery performance for this target was not evaluated."
            )
        else:
            scope_text = "Docking used the configured protocol shown above. No target-specific bound-ligand control was supplied, so pose-recovery performance for this target was not evaluated."
        result_subject = f"Target: {target_name} | Ligand: {name}" if protocol else f"Ligand: {name}"
        story += [Paragraph(result_subject,styles["Heading2"]),Paragraph(scope_text + " More favorable Vina scores are more negative; RMSD and cluster population are separate measures.",styles["BodyText"]),Spacer(1,6)]
        if len(report_compounds) > 1 and cid in compound_results_by_id:
            ligand_result = compound_results_by_id[cid]
            story += [
                Paragraph("Summary of docking results", styles["Heading2"]),
                table(
                    single_compound_summary_rows(ligand_result),
                    [2.55*inch, 4.15*inch],
                    compact=True,
                ),
                Spacer(1,8),
            ]
        compound_root = args.study / "compounds" / cid
        panel = first(args.study,[f"report/{cid}_panels_AB.png",f"report/{cid}_panel_AB.png",f"report/compound_{cid}_panels_AB.png",f"report/{cid}_panel_A_clusters.png"])
        if not panel:
            panel = first(compound_root,["pose_analysis/*panels_AB*.png","pose_analysis/*panel_AB*.png"])
        if not panel:
            panel = shared_panel
        cluster_figure_number = None
        if panel:
            cluster_figure_number = figure_number
            is_cluster_plot = panel.name.endswith("_panel_A_clusters.png")
            caption = (
                f"<b>Figure {figure_number}. Docking pose-cluster analysis for {name}.</b> "
                "Docking score versus symmetry-aware, no-fit heavy-atom RMSD from the lowest-energy cluster representative in the receptor coordinate frame; point size denotes cluster population."
                if is_cluster_plot else
                f"<b>Figure {figure_number}. Docking pose-cluster analysis for {name}.</b> (A) Docking score versus symmetry-aware, no-fit heavy-atom RMSD from the lowest-energy cluster representative in the receptor coordinate frame; point size denotes cluster population. (B) Representative structures from the highlighted clusters, using matching cluster colors."
            )
            story += [KeepTogether([image(panel,6.0,3.75),Paragraph(caption,styles["SmallDU"])]),Spacer(1,4)]
            figure_number += 1
        # This table is deliberately read from Panel A's exported data, not
        # re-derived from a different summary.  It therefore lists the same
        # maximum 20 clusters, scores, RMSDs, and population values as the plot.
        rows=[["Rank","Cluster","Vina score","RMSD (A)","Population"]]
        cluster_colors={1:"#d62728",2:"#1f77b4",3:"#d9a400"}
        plotted_cluster_path = args.study / "report" / f"{cid}_panel_A_clusters.csv"
        if plotted_cluster_path.is_file():
            records=list(csv.DictReader(plotted_cluster_path.open(newline="")))
            records.sort(key=lambda r: int(r.get("energy_rank",999999)))
            for row in records[:20]:
                rank=int(row.get("energy_rank",len(rows))); cluster_id=row.get("cluster_id","NA")
                label=f"Cluster {cluster_id}"
                if rank in cluster_colors:
                    label=Paragraph(f'<font color="{cluster_colors[rank]}"><b>{label}</b></font>',styles["SmallDU"])
                rows.append([rank,label,row.get("best_energy_kcal_per_mol","NA"),row.get("rmsd_angstrom","NA"),row.get("pose_count","NA")])
        if len(rows) > 1:
            if protocol and args.include_control_appendix:
                # The preceding summary panel can end exactly at a page
                # boundary.  An unconditional PageBreak would then consume
                # the newly opened page and leave it blank.  Reserve enough
                # space for the cluster table and snapshot panel, but do
                # nothing when ReportLab has already advanced to a fresh page.
                story.append(docking_detail_section_break())
            story += [Paragraph("Clusters represented in the docking plot",styles["Heading2"]),table(rows,[.6*inch,1.65*inch,1.45*inch,1.45*inch,1.35*inch],compact=True),Spacer(1,8)]
        cluster_path = compound_root / "pose_analysis" / "cluster_summary.csv"
        snapshot_panel = first(args.study, [f"report/{cid}_top3_3d_snapshots.png"])
        selected_representative_count = 3
        if snapshot_panel:
            snapshot_manifest = read_json(snapshot_panel.with_suffix(".manifest.json"))
            snapshot_count = snapshot_manifest.get("snapshot_count", 3)
            selected_representative_count = max(1, int(snapshot_count or 1))
            representative_label = "representative" if snapshot_count == 1 else "representatives"
            panel_labels = ["A", "B", "C"][:selected_representative_count]
            if len(panel_labels) == 1:
                panel_description = "Panel A shows energy rank 1."
            elif len(panel_labels) == 2:
                panel_description = "Panels A and B show energy ranks 1 and 2, respectively."
            else:
                panel_description = "Panels A, B, and C show energy ranks 1, 2, and 3, respectively."
            if selected_representative_count == 1:
                color_description = "Red matches the highlighted cluster"
            elif selected_representative_count == 2:
                color_description = "Red and blue match the highlighted clusters"
            else:
                color_description = "Red, blue, and gold match the highlighted clusters"
            cluster_reference = (
                f"Figure {cluster_figure_number}"
                if cluster_figure_number is not None
                else "the corresponding docking pose-cluster analysis"
            )
            story += [KeepTogether([
                Paragraph(f"Energy-ranked 3D cluster {representative_label}", styles["Heading2"]),
                image(snapshot_panel, 6.5, 4.4),
                Paragraph(
                    f"<b>Figure {figure_number}. Three-dimensional interaction snapshots for {name}.</b> "
                    f"Shown are {snapshot_count} energy-ranked distinct cluster {representative_label}, ordered by Vina score. "
                    f"{panel_description} {color_description} in {cluster_reference}. These views support structural inspection; docking score rank does not establish pose correctness.",
                    styles["SmallDU"],
                ), Spacer(1,6),
            ])]
            figure_number += 1
        interaction_diagrams=[]
        if cluster_path.is_file():
            diagram_rows=list(csv.DictReader(cluster_path.open(newline="")))
            diagram_rows.sort(key=lambda r: int(r.get("energy_rank",999999)))
            for diagram_row in diagram_rows[:selected_representative_count]:
                cluster_id=str(diagram_row.get("cluster_id",""))
                diagram=compound_root / "pose_analysis" / f"cluster_{int(cluster_id):03d}" / "interactions" / "representative_plip2d.png" if cluster_id.isdigit() else None
                if diagram and diagram.is_file():
                    interaction_diagrams.append((diagram_row,diagram))
        if interaction_diagrams:
            composite = args.study / "report" / f"{cid}_selected_interactions_ABC.png"
            if combine_horizontal_diagrams(interaction_diagrams, composite):
                interaction_count = len(interaction_diagrams)
                if interaction_count == 1:
                    interaction_panel_description = "A is the red energy-ranked cluster representative shown above."
                elif interaction_count == 2:
                    interaction_panel_description = "A and B are the red and blue energy-ranked cluster representatives shown above."
                else:
                    interaction_panel_description = "A, B, and C are the red, blue, and gold energy-ranked cluster representatives shown above."
                story += [KeepTogether([
                    Paragraph("Selected 2D pose interaction diagrams",styles["Heading2"]),
                    image(composite,6.8,2.45),
                    Paragraph(f"<b>Figure {figure_number}. SDF-aware PLIP interaction diagrams for {name}.</b> {interaction_panel_description} Ligand chemistry comes from each retained SDF; interaction calls come from the retained PLIP report.xml.",styles["SmallDU"]),Spacer(1,6),
                ])]
                figure_number += 1
        elif panel:
            story.append(PageBreak())
        if not panel and cluster_path.is_file():
            cluster_records=list(csv.DictReader(cluster_path.open(newline="")))
            cluster_records.sort(key=lambda r: int(r.get("energy_rank",999999)))
            fallback_images=[]
            for cluster_row in cluster_records[:selected_representative_count]:
                cluster_id=str(cluster_row.get("cluster_id",""))
                interaction_png=compound_root / "pose_analysis" / f"cluster_{int(cluster_id):03d}" / "interactions" / "complex_plip_all_in_one.png" if cluster_id.isdigit() else None
                if interaction_png and interaction_png.is_file():
                    fallback_images.append((cluster_row, interaction_png))
            if fallback_images:
                visual_label = "view" if len(fallback_images) == 1 else "views"
                story += [Paragraph(f"Selected cluster structural {visual_label}",styles["CaptionDU"])]
                for cluster_row, interaction_png in fallback_images:
                    story += [Paragraph(f"Cluster {cluster_row.get('cluster_id','NA')} - Vina score {cluster_row.get('best_energy_kcal_per_mol','NA')} kcal/mol", styles["SmallDU"]), image(interaction_png,6.8,3.2), Spacer(1,4)]
        story += [Paragraph("<b>Interpretation and limitations</b><br/>Docking scores are ranking estimates, not measured binding free energies. Rigid-receptor docking does not model induced fit. Cluster population and seed support describe computational convergence, not biological correctness. Protonation, tautomer, receptor preparation, and box choices can affect results. Experimental validation remains necessary.",styles["SmallDU"])]
        if compound_index < len(report_compounds)-1:
            story.append(PageBreak())

    provenance = retain_used_report_methods(
        reproducibility_record(protocol, args.study, args.control), cavity, has_docking
    )
    require_complete_used_versions(provenance)
    (args.study / "report" / "software_versions_and_references.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    version_check = provenance.get("control_to_new_run_version_check")
    compared_software = {entry["software"] for entry in version_check["entries"]} if version_check else set()
    displayed_software = [
        item for item in provenance["software"]
        if item["software"] not in compared_software
        and not (version_check and item["software"] == "fpocket")
    ]
    provenance_rows = [["Result element", "Software", "Version used"]]
    for item in displayed_software:
        provenance_rows.append([
            Paragraph(item["role"], styles["SmallDU"]),
            Paragraph(item["software"], styles["SmallDU"]),
            Paragraph(str(item["version"]), styles["SmallDU"]),
        ])
    story += [
        PageBreak(), Paragraph(f"{result_number + 1}. Reproducibility, software, and references", styles["Heading1"]),
        Paragraph(reproducibility_summary(provenance, cavity, has_docking), styles["BodyText"]),
        Spacer(1,8),
    ]
    story += pdbfixer_report_note(provenance["receptor_preparation"], out, styles)
    story += adfr_fallback_report_note(provenance["receptor_preparation"], out, styles)
    story += user_approved_removal_report_note(provenance["receptor_preparation"], out, styles)
    story += ccd_modification_report_note(provenance["receptor_preparation"], out, styles)
    if version_check:
        verdict = version_check["overall"]
        verdict_text = (
            "Checked: no software version differences detected."
            if verdict == "SAME" else
            "Checked: software version differences detected."
            if verdict == "NOT THE SAME" else
            "Checked: software version comparison could not be fully verified."
        )
        story += [
            Paragraph("Control-to-new-run software check", styles["Heading2"]),
            Paragraph(f"<b>{verdict_text}</b>", styles["BodyText"]),
        ]
        comparison_rows = [["Software", "Control", "New run", "Result"]]
        comparison_rows += [[entry["software"], entry["control_version"], entry["new_run_version"], entry["status"]] for entry in version_check["entries"]]
        story += [Spacer(1,6), table(comparison_rows, [1.65*inch, 2.15*inch, 2.15*inch, 1.25*inch], compact=True), Spacer(1,10)]
    story += [
        Paragraph("Additional software used for analysis and reporting", styles["Heading2"]),
        table(provenance_rows, [2.5*inch, 1.65*inch, 3.05*inch], compact=True),
        Spacer(1,6), Paragraph("Scientific and software references", styles["Heading2"]),
    ]
    for index, reference in enumerate(provenance["references"], start=1):
        story += [
            Paragraph(
                f"{index}. {reference['citation']} <link href=\"{reference['url']}\"><font color=\"#1f4e79\">{reference['url']}</font></link>",
                styles["ReferenceDU"],
            ),
        ]

    SimpleDocTemplate(str(out),pagesize=letter,leftMargin=.65*inch,rightMargin=.65*inch,topMargin=.6*inch,bottomMargin=.6*inch,title="Docking Universal report").build(story)
    print(f"PDF report: {out}")

if __name__ == "__main__": main()
