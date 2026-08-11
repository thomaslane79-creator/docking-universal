#!/usr/bin/env python3
"""Generate the polished Docking Universal PDF from completed run artifacts."""
import argparse, csv, json, subprocess, sys
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

def package_version():
    try:
        return (Path(__file__).resolve().parent.parent / "VERSION").read_text().strip()
    except OSError:
        return "unknown"

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

def display_compound_name(name, source=None):
    import re
    value = str(name or "").strip()
    if value and not value.isdigit():
        return value
    stem = Path(str(source or "")).stem
    descriptive = re.sub(r"(?i)_pubchem_?\d+$", "", stem).replace("_", " ").strip()
    return descriptive.title() if descriptive and not descriptive.isdigit() else (value or "Ligand")

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
    match = re.search(r"pocket(\d+)", config, re.I)
    selected_file = f"pocket{match.group(1)}_atm.pdb" if match else None
    rows = read_tsv_rows(selection)
    selected = next((row for row in rows if row.get("pocket_file") == selected_file), {})
    diagnostics = selection.parent / "pocket_diagnostics.tsv"
    diagnostic_rows = read_tsv_rows(diagnostics)
    detail = next((row for row in diagnostic_rows if row.get("pocket_file") == selected_file), {})
    descriptors = read_fpocket_descriptors(selection.parent)
    config_path = selection.parent / config if config else None
    dimensions = read_box_dimensions(config_path) if config_path and config_path.is_file() else None
    return {
        "selection": selection, "rows": rows, "selected": selected,
        "detail": detail, "descriptors": descriptors, "config": config,
        "selected_file": selected_file, "box_dimensions": dimensions,
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

def discover_control(study):
    """Recover the control root recorded by a separately launched screen."""
    for manifest_path in sorted(study.glob("compounds/*/screen_manifest.json")):
        protocol = Path(str(read_json(manifest_path).get("protocol", ""))).expanduser()
        if not protocol.is_file():
            continue
        for parent in protocol.parents:
            if parent.name == "control":
                return parent
    return None

def installed_version(*distribution_names):
    for name in distribution_names:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return "not detected"

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

def reproducibility_record(protocol, study, control):
    """Collect versions and methods from the actual report runtime and protocol."""
    recorded = protocol.get("software", {}) if protocol else {}
    figure_manifest = read_json(study / "report" / "report_figure_manifest.json")
    clustering = read_json(first(study, ["compounds/*/pose_analysis/clustering_manifest.json", "**/clustering_manifest.json"]))
    docking_manifest = read_key_value_tsv(first(study, ["compounds/*/seed_*/docking/run_manifest.tsv", "**/docking/run_manifest.tsv"]))
    engine_version = recorded.get("engine_version") or docking_manifest.get("engine_version", "not recorded")
    engine_source = recorded.get("engine_source") or docking_manifest.get("engine_source")
    if engine_source:
        engine_version += f" ({engine_source})"
    software = [
        {"role": "Workflow", "software": "Docking Universal", "version": recorded.get("docking_universal", package_version())},
        {"role": "Ligand-free cavity detection", "software": "fpocket", "version": fpocket_version()},
        {"role": "Docking scores and poses", "software": "AutoDock Vina", "version": engine_version},
        {"role": "Docking parameterization", "software": "Meeko", "version": recorded.get("meeko", installed_version("meeko"))},
        {"role": "Protonation/conformer preparation", "software": "MolScrub", "version": recorded.get("molscrub", installed_version("molscrub"))},
        {"role": "Molecular graph, RMSD, clustering", "software": "RDKit", "version": recorded.get("rdkit", installed_version("rdkit", "rdkit-pypi"))},
        {"role": "Molecular conversion/PLIP backend", "software": "Open Babel", "version": openbabel_version()},
        {"role": "Interaction calls", "software": "PLIP", "version": installed_version("plip")},
        {"role": "3D rendering", "software": "PyMOL", "version": pymol_version()},
        {"role": "Plots", "software": "Matplotlib", "version": installed_version("matplotlib")},
        {"role": "PDF generation", "software": "ReportLab", "version": installed_version("reportlab")},
        {"role": "Runtime", "software": "Python", "version": recorded.get("python", sys.version.split()[0])},
    ]
    references = [
        {"citation": "Eberhardt J, Santos-Martins D, Tillack AF, Forli S. AutoDock Vina 1.2.0: New Docking Methods, Expanded Force Field, and Python Bindings. J Chem Inf Model. 2021;61:3891-3898.", "url": "https://doi.org/10.1021/acs.jcim.1c00203"},
        {"citation": "Le Guilloux V, Schmidtke P, Tuffery P. Fpocket: an open source platform for ligand pocket detection. BMC Bioinformatics. 2009;10:168.", "url": "https://doi.org/10.1186/1471-2105-10-168"},
        {"citation": "Santos-Martins D, He Y, Eberhardt J, et al. Meeko: molecule parameterization and software interoperability for docking and beyond. J Chem Inf Model. 2025;65:13045-13050.", "url": "https://doi.org/10.1021/acs.jcim.5c02271"},
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
        "methods": {
            "cavity_detection": "fpocket geometric cavity detection, descriptor calculation, and recorded geometry/overlap filtering" if discover_cavity_record(study) else "not used in the retained report study",
            "docking_scores_and_poses": "AutoDock Vina",
            "interaction_detection": "PLIP rule-based calls; retained PLIP XML is authoritative",
            "interaction_diagram": figure_manifest.get("interaction_diagram_renderer", "native SDF plus PLIP XML"),
            "rmsd_and_clustering": clustering.get("method", "RDKit symmetry-aware heavy-atom CalcRMS without fitting; Butina clustering"),
            "cluster_cutoff_angstrom": clustering.get("cluster_rmsd_angstrom", 2.0),
            "single_cluster_policy": "Use the lowest-energy member as the sole representative",
        },
        "references": references,
    }

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("study", type=Path)
    ap.add_argument("--control", type=Path)
    ap.add_argument("--out", type=Path)
    args = ap.parse_args()

    args.study = args.study.expanduser().resolve()
    if args.control:
        args.control = args.control.expanduser().resolve()
    else:
        args.control = discover_control(args.study)

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

    summary = read_json(args.study / "report" / "study_summary.json")
    compounds = summary.get("compounds", [])
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallDU", parent=styles["BodyText"], fontSize=8, leading=10))
    styles.add(ParagraphStyle(name="CaptionDU", parent=styles["Heading2"], alignment=TA_CENTER, fontSize=11, leading=14))

    def image(path, width=7.0, height=4.5):
        item = Image(str(path)); item._restrictSize(width*inch, height*inch); return item
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

    protocol_path = choose_protocol(args.control) if args.control else None
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
    out = args.out or args.study / "report" / descriptive_report_name(target_name, ligand_names, summary)
    out.parent.mkdir(parents=True, exist_ok=True)
    if len(ligand_names) == 1:
        study_descriptor = f"Target: {target_name} | Ligand: {ligand_names[0]}"
    elif ligand_names:
        study_descriptor = f"Target: {target_name} | Ligands: {len(ligand_names)} compounds"
    else:
        study_descriptor = f"Target: {target_name}"

    cavity = discover_cavity_record(args.study) if not protocol else None
    has_docking = bool(protocol or title_manifest_path or compounds)
    report_title = (
        "Docking Universal - Ligand-Free Cavity and Docking Report" if cavity and has_docking
        else "Docking Universal - Ligand-Free Cavity Report" if cavity
        else "Docking Universal - Docking Study Report"
    )
    story = [Paragraph(f"{report_title}<br/><font size=\"12\">Version {package_version()} - Research preview</font>", styles["Title"]),
             Paragraph(study_descriptor, styles["Heading2"]), Spacer(1,8)]
    if cavity:
        story += [Paragraph("Scientific status: exploratory site selection without a bound-ligand pose-recovery control", styles["BodyText"]), Spacer(1,8)]
    figure_number = 1
    section_number = 1

    if cavity:
        selected = cavity["selected"]
        detail = cavity["detail"]
        descriptor = cavity["descriptors"].get(cavity["selected_file"], {})
        box_dimensions = cavity["box_dimensions"]
        box_volume = box_dimensions[0] * box_dimensions[1] * box_dimensions[2] if box_dimensions else None
        selected_count = sum(row.get("decision") == "selected" for row in cavity["rows"])
        skipped_count = sum(row.get("decision") == "skipped" for row in cavity["rows"])
        story += [
            Paragraph(f"{section_number}. Ligand-free cavity selection", styles["Heading1"]),
            Paragraph(
                "No bound-ligand pose-recovery control was available. In its place, this section records how fpocket-generated cavity hypotheses were filtered and which docking box was selected. This documents site selection, but it does not validate the biological site or the accuracy of docked poses.",
                styles["BodyText"],
            ), Spacer(1,6),
            table([
                ["Cavity-selection item", "Recorded result"],
                ["Candidate decisions recorded", len(cavity["rows"])],
                ["Retained non-overlapping candidates", selected_count],
                ["Skipped overlapping candidates", skipped_count],
                ["Selected docking box", cavity["config"] or "Not recorded"],
                ["Selected fpocket cavity", cavity["selected_file"] or "Not resolved"],
                ["fpocket score", selected.get("score", detail.get("score", "NA"))],
                ["fpocket druggability score", descriptor.get("druggability_score", "NA")],
                ["fpocket cavity volume (A^3)", descriptor.get("volume_angstrom3", "NA")],
                ["Geometry-filter rank", selected.get("rank_order", "NA")],
                ["Alpha spheres", detail.get("alpha_spheres", "NA")],
                ["Cavity bounding box (A)", " x ".join(detail.get(key, "NA") for key in ("bbox_x", "bbox_y", "bbox_z"))],
                ["Docking-box center (A)", ", ".join(selected.get(key, "NA") for key in ("center_x", "center_y", "center_z"))],
                ["Docking-box dimensions (A)", " x ".join(f"{value:g}" for value in box_dimensions) if box_dimensions else "NA"],
                ["Docking-box volume (A^3)", f"{box_volume:g}" if box_volume is not None else "NA"],
            ], [2.55*inch, 4.15*inch]), Spacer(1,8),
        ]
        candidate_rows = [["Rank", "Cavity", "fpocket score", "Druggability", "Volume (A^3)", "Decision"]]
        for row in cavity["rows"][:10]:
            descriptor_row = cavity["descriptors"].get(row.get("pocket_file"), {})
            candidate_rows.append([
                row.get("rank_order", "NA"), row.get("pocket_file", "NA"), row.get("score", "NA"),
                descriptor_row.get("druggability_score", "NA"), descriptor_row.get("volume_angstrom3", "NA"),
                "selected box" if row.get("pocket_file") == cavity["selected_file"] else row.get("decision", "NA"),
            ])
        story += [Paragraph("Ranked cavity candidates", styles["Heading2"]), table(candidate_rows, [.45*inch, 1.35*inch, 1.05*inch, 1.05*inch, 1.05*inch, 1.15*inch], compact=True), Spacer(1,8)]
        cavity_ab = args.study / "report" / "cavity_panels_AB.png"
        cavity_a = args.study / "report" / "cavity_panel_A_selection.png"
        cavity_b = args.study / "report" / "cavity_panel_B_structure.png"
        cavity_overview = args.study / "report" / "cavity_selected_box.png"
        if cavity_ab.is_file():
            story += [
                image(cavity_ab, 7.0, 4.1),
                Paragraph(
                    f"<b>Figure {figure_number}. Ligand-free cavity candidates and spatial comparison.</b> (A) Eligible cavities are shown in their integer evaluation order. Order 1 has the highest composite priority, calculated from the fpocket score with a penalty for distance from the protein interior; gray candidates were subsequently removed because their docking boxes overlapped a higher-priority retained box. (B) All retained non-overlapping pocket hypotheses are shown on the complete receptor as translucent surface envelopes generated from their fpocket alpha spheres. Candidate colors correspond between panels; red identifies the candidate selected to define the docking box. These are geometric representations, not experimentally observed molecular surfaces. fpocket scores are not binding-affinity estimates.",
                    styles["SmallDU"],
                ), Spacer(1,8),
            ]
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
            story += [
                image(cavity_overview, 6.5, 4.15),
                Paragraph(
                    f"<b>Figure {figure_number}. Chosen pocket and docking box.</b> The receptor is shown as a gray cartoon, the selected alpha-sphere-derived pocket surface in translucent red, the selected center in yellow, and the docking box as an orange wireframe. Red matches the selected candidate in Figure {figure_number - 1}. This records the region chosen to proceed; it does not establish that the pocket is biologically correct.",
                    styles["SmallDU"],
                ), Spacer(1,8),
            ]
            figure_number += 1
        story.append(PageBreak())
        section_number += 1

    if cavity and not has_docking:
        provenance = reproducibility_record(protocol, args.study, args.control)
        allowed_roles = {"Workflow", "Ligand-free cavity detection", "3D rendering", "Plots", "PDF generation", "Runtime"}
        software = [item for item in provenance["software"] if item["role"] in allowed_roles]
        references = [item for item in provenance["references"] if "Fpocket" in item["citation"] or "PyMOL" in item["citation"]]
        provenance["software"] = software
        provenance["references"] = references
        (args.study / "report" / "software_versions_and_references.json").write_text(json.dumps(provenance, indent=2) + "\n")
        provenance_rows = [["Result element", "Software", "Version used"]]
        for item in software:
            provenance_rows.append([Paragraph(item["role"], styles["SmallDU"]), Paragraph(item["software"], styles["SmallDU"]), Paragraph(str(item["version"]), styles["SmallDU"])])
        story += [
            Paragraph(f"{section_number}. Reproducibility, software, and references", styles["Heading1"]),
            Paragraph("This preparation-only report records fpocket cavity detection, candidate filtering, the selected review box, and PyMOL structural rendering. No ligand docking, scoring, pose clustering, or interaction analysis was performed.", styles["BodyText"]),
            Spacer(1,8), Paragraph("Software versions used for this report", styles["Heading2"]),
            table(provenance_rows, [2.35*inch, 1.55*inch, 2.8*inch], compact=True),
            Spacer(1,10), Paragraph("Scientific and software references", styles["Heading2"]),
        ]
        for index, reference in enumerate(references, start=1):
            story += [Paragraph(f"{index}. {reference['citation']} <link href=\"{reference['url']}\"><font color=\"#1f4e79\">{reference['url']}</font></link>", styles["SmallDU"]), Spacer(1,4)]
        SimpleDocTemplate(str(out),pagesize=letter,leftMargin=.65*inch,rightMargin=.65*inch,topMargin=.6*inch,bottomMargin=.6*inch,title="Docking Universal ligand-free cavity report").build(story)
        print(f"PDF report: {out}")
        return

    if protocol:
        a=protocol.get("acceptance",{}); p=protocol.get("parameters",{}); g=protocol.get("global_top_ranked_pose",{}); b=protocol.get("global_best_sampled_pose",{})
        history=protocol.get("escalation_history",[]); last=history[-1] if history else {}
        passed=bool(a.get("sampling_pass") and a.get("ranking_pass") and a.get("seed_requirement_pass"))
        control_ligand_sdf = first(args.control, ["00_inputs/*_experimental.sdf", "**/crystal_ligand.sdf"]) if args.control else None
        control_ligand_name = (
            control_ligand_sdf.stem.removesuffix("_experimental")
            if control_ligand_sdf
            else "unspecified ligand"
        )
        story += [Paragraph(f"{section_number}. Bound-ligand control: {control_ligand_name}", styles["Heading1"]),
          Paragraph(f"This retrospective control tests whether the protocol reproducibly recovers the experimental pose of {control_ligand_name}. PASS requires sampling, ranking, and independent-seed criteria to pass. It supports use of the selected protocol for this target, but does not establish affinity or prospective pose accuracy.", styles["BodyText"]), Spacer(1,6)]
        rows=[["Control metric","Result"],["Overall protocol status","PASS" if passed else "REVIEW"],
          ["Sampling control","PASS" if a.get("sampling_pass") else "FAIL"],["Ranking control","PASS" if a.get("ranking_pass") else "FAIL"],
          ["Independent-seed requirement",f"{'PASS' if a.get('seed_requirement_pass') else 'FAIL'} - {a.get('independent_seed_count','NA')} observed; {a.get('minimum_independent_seeds','NA')} required"],
          ["RMSD threshold",f"{a.get('threshold_angstrom','NA')} A"],["Best sampled RMSD",f"{b.get('best_rmsd_angstrom','NA')} A"],
          ["Top-ranked pose RMSD",f"{g.get('best_rmsd_angstrom','NA')} A"],["Top-ranked docking score",f"{g.get('top_score_affinity_kcal_per_mol','NA')} kcal/mol"]]
        story += [table(rows,[2.55*inch,4.15*inch]),Spacer(1,8)]
        control_ab=first(args.control,["report/control_panels_AB.png","**/control_panels_AB.png"]) if args.control else None
        control_a=first(args.control,["report/control_panel_A*.png","**/control_panel_A*.png"]) if args.control else None
        control_b=first(args.control,["report/control_panel_B_overlay.png","report/control_panel_B*.png","**/control_panel_B*.png"]) if args.control else None
        experimental_reference=first(args.control,["00_inputs/*_experimental.sdf","**/crystal_ligand.sdf"]) if args.control else None
        experimental_label=experimental_reference.stem.removesuffix("_experimental") if experimental_reference else "experimental ligand"
        if control_ab:
            story += [image(control_ab,7.0,4.1),Paragraph(f"<b>Figure {figure_number}. Retrospective control performance and pose recovery.</b> (A) Control-cluster Vina score versus symmetry-aware, no-fit heavy-atom RMSD to experimental {experimental_label} in the receptor coordinate frame. (B) Experimental ligand (magenta), lowest-energy pose (red), and lowest-RMSD pose (blue) superimposed in that frame; receptor residues within 5 A of the displayed ligands are gray.",styles["SmallDU"]),Spacer(1,8)]
            figure_number += 1
        else:
            if control_a: story += [Paragraph("Control Panel A - score and RMSD landscape",styles["CaptionDU"]),image(control_a),Spacer(1,5)]
            if control_b: story += [KeepTogether([Paragraph("Control Panel B - superimposed experimental and redocked poses",styles["CaptionDU"]),image(control_b,7.0,3.8),Paragraph("Experimental ligand: magenta; lowest-energy docked pose: red; lowest-RMSD docked pose: blue. Nearby receptor residues are gray.",styles["SmallDU"])]),Spacer(1,5)]
        control_diagrams = [
            (first(args.control,["report/control_experimental_plip2d.png"]), f"Experimental {experimental_label} pose used as the control reference."),
            (first(args.control,["report/control_top_ranked_plip2d.png"]), f"Globally lowest-energy redocked pose (Vina score {g.get('top_score_affinity_kcal_per_mol','NA')} kcal/mol; RMSD {g.get('top_score_rmsd_angstrom',g.get('best_rmsd_angstrom','NA'))} A)."),
            (first(args.control,["report/control_lowest_rmsd_plip2d.png"]), f"Globally lowest-RMSD redocked pose (RMSD {b.get('best_rmsd_angstrom','NA')} A)."),
        ] if args.control else []
        control_diagrams = [(path, description) for path, description in control_diagrams if path]
        if control_diagrams:
            story += [PageBreak(), Paragraph("Control interaction diagrams",styles["Heading2"])]
            for diagram, description in control_diagrams:
                story += [KeepTogether([
                    image(diagram,5.2,1.8),
                    Paragraph(f"<b>Figure {figure_number}. SDF-aware PLIP interaction diagram.</b> {description} Ligand chemistry comes from the retained SDF and interaction calls come from the retained PLIP XML.",styles["SmallDU"]),
                    Spacer(1,5),
                ])]
                figure_number += 1
            story.append(PageBreak())
        else:
            story.append(PageBreak())
        story += [Paragraph("Approved protocol",styles["Heading2"]),table([["Parameter","Selected value"],["Engine",protocol.get("engine","NA")],["Tier",protocol.get("calibration_tier","NA")],["Exhaustiveness",p.get("exhaustiveness","NA")],["Modes per job",p.get("num_modes","NA")],["Conformers per state",p.get("conformers_per_state","NA")],["Independent seeds",len(p.get("seeds",[]))],["Charge model",p.get("charge_model","NA")],["pH",p.get("ph","NA")],["Conformer force field",p.get("forcefield","mmff94")],["Tautomers enumerated",p.get("tautomers_enumerated",True)],["Conformer RMSD pruning",f"{p.get('rmsd_prune_angstrom',0.75)} A"],["Runtime",f"{protocol.get('wall_time_seconds',0)/60:.1f} min"],["Calibration jobs",last.get("job_count","NA")]], [2.55*inch,4.15*inch]),PageBreak()]
    else:
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
        story += [Paragraph(f"{section_number}. Configured docking protocol",styles["Heading1"]),
          Paragraph("This section records the settings selected for this study. Control approval applies only when an approved target-matched protocol is identified below.",styles["BodyText"]),Spacer(1,6),
          table([["Parameter","Configured value"],["Validation status",validation_status],["Engine",engine],["Engine version",engine_version],["Exhaustiveness",manifest.get("exhaustiveness") or configured.get("exhaustiveness","NA")],["Modes per job",manifest.get("num_modes") or configured.get("num_modes","NA")],["Energy range",f"{manifest.get('energy_range_kcal_per_mol') or configured.get('energy_range_kcal_per_mol','NA')} kcal/mol"],["Independent seeds",seed_count or "NA"],["Receptor",Path(receptor).name],["Docking box",Path(docking_box).name]], [2.55*inch,4.15*inch]),PageBreak()]

    result_number = section_number + 1
    story += [Paragraph(f"{result_number}. Docking results",styles["Heading1"])]
    shared_panel = first(args.study,["report/study_panels_AB.png"]) if len(compounds) == 1 else None
    inventory = read_json(args.study / "inputs" / "compound_library_inventory.json")
    inventory_rows = inventory.get("compounds", inventory.get("entries", []))
    inventory_by_id = {str(x.get("compound_id")): x for x in inventory_rows}
    display_names = {}
    report_compounds = compounds or [{"compound_name":args.study.name,"compound_id":""}]
    for compound_index, compound in enumerate(report_compounds):
        cid=str(compound.get("compound_id", "")); inventory_row=inventory_by_id.get(cid, {}); name=display_compound_name(compound.get("compound_name") or inventory_row.get("compound_name") or cid, inventory_row.get("source"))
        display_names[cid] = name
        if protocol:
            scope_text = "Docking used the approved target-matched protocol shown above."
        else:
            scope_text = "Docking used the configured protocol shown above. No target-specific bound-ligand control was supplied, so pose-recovery performance for this target was not evaluated."
        story += [Paragraph(f"Ligand: {name}",styles["Heading2"]),Paragraph(scope_text + " More favorable Vina scores are more negative; RMSD and cluster population are separate measures.",styles["BodyText"]),Spacer(1,6)]
        compound_root = args.study / "compounds" / cid
        panel = first(args.study,[f"report/{cid}_panels_AB.png",f"report/{cid}_panel_AB.png",f"report/compound_{cid}_panels_AB.png"])
        if not panel:
            panel = first(compound_root,["pose_analysis/*panels_AB*.png","pose_analysis/*panel_AB*.png"])
        if not panel:
            panel = shared_panel
        cluster_figure_number = None
        if panel:
            cluster_figure_number = figure_number
            story += [image(panel,6.0,3.75),Paragraph(f"<b>Figure {figure_number}. Docking pose-cluster analysis for {name}.</b> (A) Docking score versus symmetry-aware, no-fit heavy-atom RMSD from the lowest-energy cluster representative in the receptor coordinate frame; point size denotes cluster population. (B) Representative structures from the highlighted clusters, using matching cluster colors.",styles["SmallDU"]),Spacer(1,4)]
            figure_number += 1
        cluster_path = compound_root / "pose_analysis" / "cluster_summary.csv"
        snapshot_panel = first(args.study, [f"report/{cid}_top3_3d_snapshots.png"])
        if snapshot_panel:
            snapshot_manifest = read_json(snapshot_panel.with_suffix(".manifest.json"))
            snapshot_count = snapshot_manifest.get("snapshot_count", 3)
            representative_label = "representative" if snapshot_count == 1 else "representatives"
            cluster_reference = (
                f"Figure {cluster_figure_number}"
                if cluster_figure_number is not None
                else "the corresponding docking pose-cluster analysis"
            )
            story += [
                Paragraph("Top-ranked 3D cluster snapshots", styles["Heading2"]),
                image(snapshot_panel, 6.5, 1.8),
                Paragraph(
                    f"<b>Figure {figure_number}. Three-dimensional interaction snapshots for {name}.</b> "
                    f"Shown are {snapshot_count} energy-ranked distinct cluster {representative_label}, ordered by Vina score. "
                    f"Red, blue, and gold match the highlighted clusters in {cluster_reference}. These views support structural inspection; docking score rank does not establish pose correctness.",
                    styles["SmallDU"],
                ), Spacer(1,6),
            ]
            figure_number += 1
        interaction_diagrams=[]
        if cluster_path.is_file():
            diagram_rows=list(csv.DictReader(cluster_path.open(newline="")))
            diagram_rows.sort(key=lambda r: int(r.get("energy_rank",999999)))
            for diagram_row in diagram_rows[:3]:
                cluster_id=str(diagram_row.get("cluster_id",""))
                diagram=compound_root / "pose_analysis" / f"cluster_{int(cluster_id):03d}" / "interactions" / "representative_plip2d.png" if cluster_id.isdigit() else None
                if diagram and diagram.is_file():
                    interaction_diagrams.append((diagram_row,diagram))
        if interaction_diagrams:
            story.append(PageBreak())
            if compound_index:
                story.append(Spacer(1, 60))
            story += [Paragraph("Top-ranked pose interaction diagrams",styles["Heading2"])]
            for diagram_index,(diagram_row,diagram) in enumerate(interaction_diagrams):
                rank=diagram_row.get("energy_rank","NA"); cluster_id=diagram_row.get("cluster_id","NA"); score=diagram_row.get("best_energy_kcal_per_mol","NA")
                story += [KeepTogether([
                    image(diagram,4.6,1.55),
                    Paragraph(f"<b>Figure {figure_number}. SDF-aware PLIP interaction diagram for {name}, energy rank {rank}, cluster {cluster_id} (Vina score {score} kcal/mol).</b> Ligand bond orders, aromaticity, formal charges, and stereochemistry come from the retained pose SDF; interaction calls come from the retained PLIP report.xml. The PLIP XML/text files remain the authoritative interaction records.",styles["SmallDU"]),
                    Spacer(1,5),
                ])]
                figure_number += 1
        elif panel:
            story.append(PageBreak())
        if not panel and cluster_path.is_file():
            cluster_records=list(csv.DictReader(cluster_path.open(newline="")))
            cluster_records.sort(key=lambda r: int(r.get("energy_rank",999999)))
            fallback_images=[]
            for cluster_row in cluster_records[:3]:
                cluster_id=str(cluster_row.get("cluster_id",""))
                interaction_png=compound_root / "pose_analysis" / f"cluster_{int(cluster_id):03d}" / "interactions" / "complex_plip_all_in_one.png" if cluster_id.isdigit() else None
                if interaction_png and interaction_png.is_file():
                    fallback_images.append((cluster_row, interaction_png))
            if fallback_images:
                story += [Paragraph("Top three cluster interaction visuals",styles["CaptionDU"])]
                for cluster_row, interaction_png in fallback_images:
                    story += [Paragraph(f"Cluster {cluster_row.get('cluster_id','NA')} - Vina score {cluster_row.get('best_energy_kcal_per_mol','NA')} kcal/mol", styles["SmallDU"]), image(interaction_png,6.8,3.2), Spacer(1,4)]
        rows=[["Rank","Cluster","Best score","Median score","Poses","Seeds"]]
        cluster_colors={1:"#d62728",2:"#1f77b4",3:"#d9a400"}
        if cluster_path.is_file():
            records=list(csv.DictReader(cluster_path.open(newline="")))
            records.sort(key=lambda r: int(r.get("energy_rank",999999)))
            for row in records[:20]:
                rank=int(row.get("energy_rank",len(rows))); cluster_id=row.get("cluster_id","NA")
                label=f"Cluster {cluster_id}"
                if rank in cluster_colors: label=Paragraph(f'<font color="{cluster_colors[rank]}"><b>{label}</b></font>',styles["SmallDU"])
                rows.append([rank,label,row.get("best_energy_kcal_per_mol","NA"),row.get("median_energy_kcal_per_mol","NA"),row.get("pose_count","NA"),row.get("seed_support","NA")])
        story += [Paragraph("Ranked docking clusters",styles["Heading2"]),table(rows,[.45*inch,1.45*inch,1.25*inch,1.25*inch,.75*inch,.75*inch],compact=True),Spacer(1,8),
          Paragraph("<b>Interpretation and limitations</b><br/>Docking scores are ranking estimates, not measured binding free energies. Rigid-receptor docking does not model induced fit. Cluster population and seed support describe computational convergence, not biological correctness. Protonation, tautomer, receptor preparation, and box choices can affect results. Experimental validation remains necessary.",styles["SmallDU"])]
        if compound_index < len(report_compounds)-1:
            story.append(PageBreak())

    provenance = reproducibility_record(protocol, args.study, args.control)
    (args.study / "report" / "software_versions_and_references.json").write_text(
        json.dumps(provenance, indent=2) + "\n"
    )
    provenance_rows = [["Result element", "Software", "Version used"]]
    for item in provenance["software"]:
        provenance_rows.append([
            Paragraph(item["role"], styles["SmallDU"]),
            Paragraph(item["software"], styles["SmallDU"]),
            Paragraph(str(item["version"]), styles["SmallDU"]),
        ])
    method = provenance["methods"]
    story += [
        PageBreak(), Paragraph(f"{result_number + 1}. Reproducibility, software, and references", styles["Heading1"]),
        Paragraph(
            ("fpocket supplied ligand-free geometric cavity candidates, volumes, and druggability descriptors; the report separately records the selected docking box. " if cavity else "") +
            "Docking scores and poses were produced by AutoDock Vina. PLIP supplied rule-based protein-ligand interaction calls; the retained PLIP XML is the authoritative interaction record. RDKit supplied the retained molecular graph handling and symmetry-aware, no-fit heavy-atom RMSD matrix used by Butina clustering. The clustering cutoff was "
            f"{method['cluster_cutoff_angstrom']} A. If only one cluster is present, its lowest-energy member is reported as the sole representative. PyMOL produced the 3D molecular panels; ReportLab assembled this PDF.",
            styles["BodyText"],
        ), Spacer(1,8),
        Paragraph("Software versions used for this report", styles["Heading2"]),
        table(provenance_rows, [2.35*inch, 1.55*inch, 2.8*inch], compact=True),
        Spacer(1,10), Paragraph("Scientific and software references", styles["Heading2"]),
    ]
    for index, reference in enumerate(provenance["references"], start=1):
        story += [
            Paragraph(
                f"{index}. {reference['citation']} <link href=\"{reference['url']}\"><font color=\"#1f4e79\">{reference['url']}</font></link>",
                styles["SmallDU"],
            ), Spacer(1,4),
        ]

    SimpleDocTemplate(str(out),pagesize=letter,leftMargin=.65*inch,rightMargin=.65*inch,topMargin=.6*inch,bottomMargin=.6*inch,title="Docking Universal report").build(story)
    print(f"PDF report: {out}")

if __name__ == "__main__": main()
