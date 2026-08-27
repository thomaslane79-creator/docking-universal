#!/usr/bin/env python3
"""Create a reusable protocol, portable bundle, and scientific PDF report.

Exploratory protocol creation prepares the target and defines the site without
docking a ligand. Control-validated creation runs the established pose-recovery
workflow because that evidence is what authorizes the control protocol.
"""

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from docking_universal_bundle import (  # noqa: E402
    CONTROL_VALIDATED,
    LIGAND_GUIDED_EXPLORATORY,
    SITE_GUIDED_EXPLORATORY,
    build_receptor_modification_warning,
    create_bundle,
    protocol_type_label,
)
from docking_universal_pocket_review import choose_prepared_box, review_pocket_scene  # noqa: E402
from docking_universal_region import (  # noqa: E402
    REGION_BOUND_LIGAND,
    REGION_CHOICES,
    REGION_FPOCKET,
    REGION_RESIDUES,
    REGION_WHOLE_PROTEIN,
    choose_engine,
    choose_fpocket_selection,
    choose_region,
    residue_box,
    whole_protein_box,
    write_box_files,
)


def safe_id(value, fallback="protein"):
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value).strip()).strip("._-")
    return value or fallback


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command, cwd=None, env=None):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run([str(value) for value in command], cwd=cwd, env=env, check=True)


def package_version():
    root = Path(__file__).resolve().parent
    for path in (root / "VERSION", root.parent / "VERSION"):
        if path.is_file():
            return path.read_text().strip()
    return "unknown"


def distribution_version(name):
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not detected"


def conda_package_version(name):
    prefix = Path(sys.executable).resolve().parent.parent
    records = sorted((prefix / "conda-meta").glob(f"{name}-*.json"))
    for record in records:
        try:
            version = json.loads(record.read_text()).get("version")
        except (OSError, json.JSONDecodeError):
            continue
        if version:
            return str(version)
    return "not detected"


def sibling_conda_package_version(environment, name):
    """Read a package version from an isolated engine environment."""
    env_prefix = Path(sys.prefix).parent / environment
    records = sorted((env_prefix / "conda-meta").glob(f"{name}-*.json"))
    for record in records:
        try:
            version = json.loads(record.read_text()).get("version")
        except (OSError, json.JSONDecodeError):
            continue
        if version:
            return str(version)
    return "not detected"


def command_version(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "not detected"
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[-1].strip() if lines else "not detected"


def scientific_software_record(engine):
    """Capture the versions that define later protocol-locked screening."""
    openbabel = command_version(["obabel", "-V"])
    if openbabel.startswith("Open Babel "):
        openbabel = openbabel.removeprefix("Open Babel ").split()[0]
    if engine == "qvinaw":
        engine_version = sibling_conda_package_version("docking-universal-qvinaw", "qvina")
        if engine_version != "not detected":
            engine_version = f"QuickVina-W 1.1 (qvina package {engine_version})"
    else:
        engine_version = sibling_conda_package_version("docking-universal-vina", "vina")
        if engine_version != "not detected":
            engine_version = f"AutoDock Vina v{engine_version}"
    return {
        "docking_universal": package_version(),
        "python": sys.version.split()[0],
        "rdkit": distribution_version("rdkit"),
        "molscrub": distribution_version("molscrub"),
        "meeko": distribution_version("meeko"),
        "pdbfixer": distribution_version("pdbfixer"),
        "fpocket": conda_package_version("fpocket"),
        "openbabel": openbabel,
        "plip": distribution_version("plip"),
        "engine_version": engine_version,
    }


def preparation_summary(prep_root):
    text = (prep_root / "run.log").read_text(errors="replace") if (prep_root / "run.log").is_file() else ""
    removal_record = next(iter(sorted(prep_root.glob("receptor/user_approved_component_removal.txt"))), None)
    if removal_record and removal_record.is_file():
        return "User explicitly approved removal of unmatched receptor components after safe preparation fallbacks failed; the retained record identifies the altered model"
    if "Initial receptor preparation succeeded; PDBFixer was not needed" in text:
        return "Strict Meeko succeeded; PDBFixer was not needed"
    if "PDBFixer" in text and "succeeded" in text:
        return "Strict Meeko required conditional PDBFixer repair; the retained audit records the changes"
    return "Receptor preparation completed; the retained preparation log records the applied path"


def read_removal_manifest(manifest):
    rows = []
    if manifest and Path(manifest).is_file():
        lines = Path(manifest).read_text(errors="replace").splitlines()
        if lines:
            headings = lines[0].split("\t")
            rows = [dict(zip(headings, line.split("\t"))) for line in lines[1:] if line.strip()]
    return rows


def approved_removal_summary(protocol):
    preparation = protocol.get("receptor_preparation", {})
    if not preparation.get("user_approved_component_removal"):
        return None
    rows = preparation.get("user_approved_removed_components") or read_removal_manifest(
        preparation.get("user_approved_component_removal_manifest")
    )
    warning = preparation.get("receptor_modification_warning") or build_receptor_modification_warning(rows)
    inventory = " " + warning["summary"]
    severity = (" <b>High-severity structural warning:</b> standard protein/peptide residues, not merely solvent or "
                "optional hetero components, were omitted from the final receptor.") if warning["severity"] == "high" else ""
    return ("<b>User-approved receptor component removal:</b> all safe preparation fallbacks failed, and the user explicitly "
            "approved omission of unmatched components." + inventory +
            severity + " The complete removal manifest and raw preparation log are retained in the protocol bundle and this warning "
            "must be carried into every subsequent screening report.")


def choose_type():
    print("Create a reusable docking protocol:")
    print("  1) Control-validated — run the existing bound-ligand pose-recovery workflow")
    print("  2) Ligand-guided exploratory — use a ligand in the selected structure only to define the site")
    print("  3) Site-guided exploratory — use fpocket cavity analysis and a user-reviewed box")
    choice = input("Select [2]: ").strip() or "2"
    value = {"1": CONTROL_VALIDATED, "2": LIGAND_GUIDED_EXPLORATORY, "3": SITE_GUIDED_EXPLORATORY}.get(choice)
    if not value:
        raise SystemExit("Choose protocol type 1, 2, or 3")
    return value


def graphical_chooser_available():
    if platform.system() == "Darwin":
        return bool(shutil.which("osascript"))
    if platform.system() == "Linux" and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        if shutil.which("zenity"):
            return True
        try:
            import tkinter as tk
        except ImportError:
            return False
        try:
            probe = tk.Tk(); probe.withdraw(); probe.destroy()
            return True
        except tk.TclError:
            return False
    return False


def choose_path_graphically(prompt, folder=False):
    if platform.system() == "Darwin" and shutil.which("osascript"):
        chooser = "choose folder" if folder else "choose file"
        script = f'POSIX path of ({chooser} with prompt "{prompt}")'
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise SystemExit("Finder selection cancelled")
        selected_text = result.stdout.strip()
    elif platform.system() == "Linux" and shutil.which("zenity"):
        command = ["zenity", "--file-selection", f"--title={prompt}"]
        if folder:
            command.append("--directory")
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise SystemExit("Graphical file selection cancelled")
        selected_text = result.stdout.strip()
    elif graphical_chooser_available():
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk(); root.withdraw()
        try:
            root.attributes("-topmost", True)
            selected_text = (
                filedialog.askdirectory(title=prompt, mustexist=True)
                if folder else filedialog.askopenfilename(title=prompt, filetypes=[("PDB files", "*.pdb"), ("All files", "*")])
            )
        finally:
            root.destroy()
        if not selected_text:
            raise SystemExit("Graphical file selection cancelled")
    else:
        raise SystemExit("A graphical chooser is unavailable; enter an exact path instead")
    selected = Path(selected_text).expanduser().resolve()
    if folder and not selected.is_dir():
        raise SystemExit(f"Selection is not a readable folder: {selected}")
    if not folder and not selected.is_file():
        raise SystemExit(f"Selection is not a readable file: {selected}")
    return selected


def finder_file(prompt):
    """Backward-compatible name for the macOS or Ubuntu graphical chooser."""
    return choose_path_graphically(prompt)


def choose_output_parent():
    current = Path.cwd().resolve()
    if graphical_chooser_available():
        return choose_path_graphically("Choose where Docking Universal should save this protocol study", folder=True)
    print("\nWhere should the protocol study be saved?")
    print("Docking Universal will create a new, clearly named folder there.")
    entered = input(f"Parent folder [{current}]: ").strip()
    parent = Path(entered).expanduser() if entered else current
    if not parent.is_absolute():
        parent = current / parent
    return parent.resolve()


def choose_structure(inputs):
    finder = graphical_chooser_available()
    print("Choose the input structure:")
    print("  1) Download from RCSB by PDB ID")
    if finder:
        print("  2) Choose a local PDB file graphically")
        print("  3) Enter an exact local PDB path")
    else:
        print("  2) Enter an exact local PDB path")
    choice = input("Select [1]: ").strip() or "1"
    if choice == "1":
        pdb_id = input("Four-character PDB ID: ").strip().upper()
        if not re.fullmatch(r"[0-9][A-Z0-9]{3}", pdb_id):
            raise SystemExit("A PDB ID must contain four characters and begin with a number")
        destination = inputs / f"{pdb_id}.pdb"
        urllib.request.urlretrieve(f"https://files.rcsb.org/download/{pdb_id}.pdb", destination)
        return destination
    if choice == "2" and finder:
        return finder_file("Choose the structure PDB file")
    manual_choice = "3" if finder else "2"
    if choice != manual_choice:
        raise SystemExit("Invalid structure selection")
    value = input("Exact local PDB path: ").strip()
    if not value:
        raise SystemExit("No PDB path entered")
    return Path(value).expanduser().resolve()


def detected_ligands(preparation):
    manifest = next(iter(sorted(preparation.glob("*_receptor_prep/ligand/detected_ligands.tsv"))), None)
    if not manifest:
        return []
    rows = []
    for line in manifest.read_text().splitlines()[1:]:
        fields = line.split("\t")
        if len(fields) >= 3:
            ligand_path = Path(fields[2])
            if not ligand_path.is_absolute():
                ligand_path = manifest.parents[2] / ligand_path
            rows.append({"resname": fields[0], "atoms": fields[1], "path": ligand_path.resolve()})
    return rows


def choose_box(boxes, interactive):
    if not boxes:
        raise SystemExit("Preparation completed without a docking-box configuration")
    return choose_prepared_box(boxes, interactive)


def choose_ligand(rows, requested, interactive):
    if requested:
        match = next((row for row in rows if row["resname"] == requested), None)
        if not match:
            raise SystemExit(f"Requested ligand {requested} was not detected")
        return match
    if len(rows) == 1:
        return rows[0]
    if not rows:
        raise SystemExit("No eligible ligand was detected for ligand-guided protocol creation")
    if not interactive:
        raise SystemExit("Multiple ligands were detected; provide --ligand-resname")
    print("Ligands available as structural site anchors:")
    for index, row in enumerate(rows, 1):
        print(f"  {index}) {row['resname']} ({row['atoms']} atoms)")
    raw = input("Select ligand [1]: ").strip() or "1"
    try:
        return rows[int(raw) - 1]
    except (ValueError, IndexError):
        raise SystemExit(f"Choose a ligand from 1 to {len(rows)}") from None


def retry_fpocket_fallback(non_interactive):
    print("\nNo cavity met the default fpocket score threshold (0.10).")
    print("A target-adaptive fallback can retry at 0.0 while retaining geometry, broad-pocket, and overlap filters.")
    print("Scientific implication: lower-scoring geometric hypotheses enter review; this does not validate them as binding sites.")
    if non_interactive:
        return True
    return input("Retry cavity preparation with the documented 0.0 threshold? [Y/n]: ").strip().lower() not in {"n", "no"}


def box_values(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        if "=" not in line:
            continue
        key, value = (item.strip() for item in line.split("=", 1))
        values[key] = value
    return values


def crop_balanced(source, destination):
    try:
        from PIL import Image, ImageChops, ImageOps
        picture = Image.open(source).convert("RGB")
        background = Image.new("RGB", picture.size, "white")
        difference = ImageChops.difference(picture, background).convert("L")
        difference = difference.point(lambda value: 255 if value > 8 else 0)
        bounds = difference.getbbox()
        if not bounds:
            shutil.copy2(source, destination)
            return
        cropped = picture.crop(bounds)
        padding = max(24, round(min(cropped.size) * 0.035))
        ImageOps.expand(cropped, border=padding, fill="white").save(destination)
    except Exception:
        shutil.copy2(source, destination)


def render_box_figure(cli, preparation, report, no_visuals, receptor_pdb=None, ligand_pdb=None, box_conf=None):
    if no_visuals:
        return None
    if not receptor_pdb or not box_conf:
        return None
    box_pdb = Path(box_conf).with_name(f"{Path(box_conf).stem}_box.pdb")
    if not box_pdb.is_file():
        return None
    pml = report / "selected_docking_box.pml"
    def quoted(path):
        return str(Path(path).resolve()).replace("\\", "/").replace('"', '\\"')
    commands = [
        f'load "{quoted(receptor_pdb)}", receptor',
        "hide everything, receptor", "show cartoon, receptor", "color gray70, receptor",
        "remove (receptor and hydro and neighbor elem C)",
    ]
    if ligand_pdb:
        commands += [
            f'load "{quoted(ligand_pdb)}", site_anchor', "hide everything, site_anchor",
            "show sticks, site_anchor", "color magenta, site_anchor", "set stick_radius, 0.22, site_anchor",
            "select site_residues, byres (receptor within 5.0 of site_anchor)",
            "show sticks, site_residues", "color gray40, site_residues", "set stick_radius, 0.14, site_residues",
        ]
    commands += [
        f'load "{quoted(box_pdb)}", docking_box', "hide everything, docking_box", "show lines, docking_box",
        "color orange, docking_box", "set line_width, 3, docking_box", "bg_color white",
        "set ray_opaque_background, on", "set antialias, 2", "set cartoon_transparency, 0.10",
        "orient receptor", "zoom receptor, 4", "set orthoscopic, on",
    ]
    pml.write_text("\n".join(commands) + "\n")
    raw = report / "selected_docking_box_raw.png"
    final = report / "selected_docking_box.png"
    try:
        run([cli, "render3d", pml, "--out", raw])
        crop_balanced(raw, final)
        return final
    except subprocess.CalledProcessError:
        return None


def report_table(Table, TableStyle, Paragraph, rows, widths, styles, colors):
    table = Table([[Paragraph(str(value), styles["SmallDU"]) for value in row] for row in rows], colWidths=widths)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#d9e3f3")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#6c737d")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f6f6")]),
    ]))
    return table


def write_ligand_guided_pdf(out, protocol, figure):
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TitleDU", parent=styles["Title"], fontSize=20, leading=23, alignment=TA_CENTER, spaceAfter=4))
    styles.add(ParagraphStyle(name="SubtitleDU", parent=styles["BodyText"], fontSize=10, leading=13, alignment=TA_CENTER, textColor=colors.HexColor("#3d4652"), spaceAfter=13))
    styles.add(ParagraphStyle(name="SectionDU", parent=styles["Heading1"], fontSize=15, leading=18, spaceBefore=8, spaceAfter=6))
    styles.add(ParagraphStyle(name="BodyDU", parent=styles["BodyText"], fontSize=9.2, leading=12.2, spaceAfter=7))
    styles.add(ParagraphStyle(name="SmallDU", parent=styles["BodyText"], fontSize=8.2, leading=10.5))
    styles.add(ParagraphStyle(name="CaptionDU", parent=styles["BodyText"], fontSize=8.5, leading=11, spaceBefore=10, spaceAfter=7))
    P = lambda text, style="BodyDU": Paragraph(text, styles[style])
    parameters = protocol["parameters"]
    locked = protocol["locked_inputs"]
    box = protocol["docking_box"]
    provenance = [
        ["Protocol provenance", "Recorded value"],
        ["Target", protocol["target"]], ["Protocol filename", protocol["bundle_file_name"]],
        ["Protocol type", protocol_type_label(protocol["protocol_type"])],
        ["Evidence basis", protocol["evidence_basis"]], ["Screening authority", "User-confirmed exploratory use"],
        ["Created", protocol["created_utc"][:10]], ["Protein preparation", protocol["receptor_preparation_summary"]],
        ["Docking region", f"{protocol['site_anchor']} centered; {box['size_x']} × {box['size_y']} × {box['size_z']} Å"],
    ]
    settings = [
        ["Parameter", "Recorded value", "Parameter", "Recorded value"],
        ["Engine", protocol["engine"], "Exhaustiveness", parameters["exhaustiveness"]],
        ["Seeds per ligand (future)", len(parameters["seeds"]), "Modes per job", parameters["num_modes"]],
        ["Energy range", f"{parameters['energy_range_kcal_per_mol']} kcal/mol", "Conformers per state", parameters["conformers_per_state"]],
        ["pH", parameters["ph"], "Charge model", parameters["charge_model"]],
        ["Force field", parameters["forcefield"], "Tautomers enumerated", parameters["tautomers_enumerated"]],
        ["Conformer RMSD pruning", f"{parameters['rmsd_prune_angstrom']} Å", "Box center", f"{box['center_x']}, {box['center_y']}, {box['center_z']}"],
    ]
    use = [
        ["Use record", "Recorded meaning"],
        ["Intended use", "Screen one or multiple new ligands without redefining the prepared receptor or docking box"],
        ["Evidence boundary", "Exploratory site definition from a ligand in the selected structure; no pose-recovery control"],
    ]
    pdbfixer_version = distribution_version("pdbfixer")
    if "PDBFixer was not needed" in protocol["receptor_preparation_summary"]:
        pdbfixer_version += " (not used)"
    software = [
        ["Result element", "Software", "Version used"],
        ["Workflow", "Docking Universal", package_version()], ["Docking parameterization", "Meeko", distribution_version("meeko")],
        ["Conditional receptor repair", "PDBFixer", pdbfixer_version],
        ["Docking engine specified", "AutoDock Vina" if protocol["engine"] == "vina" else "QuickVina-W", protocol.get("engine_version", "recorded when screening runs")],
        ["3D rendering", "PyMOL Open-Source", protocol.get("pymol_version", "not used")], ["PDF generation", "ReportLab", distribution_version("reportlab")],
    ]
    story = [
        P("Docking Universal - Protocol Development Report", "TitleDU"),
        P(f"Ligand-guided exploratory protocol | Version {package_version()}", "SubtitleDU"),
        P("1. Protocol definition", "SectionDU"),
        P(f"This protocol defines a reusable docking configuration for {protocol['target']} using the coordinates of {protocol['site_anchor']} in the selected structure to position the search region. {protocol['site_anchor']} served only as a structural reference for site selection; no retrospective redocking or pose-recovery evaluation was performed. Accordingly, this is a ligand-informed exploratory screening configuration and does not claim target-specific pose-recovery validation."),
        report_table(Table, TableStyle, Paragraph, provenance, [2.15*inch, 4.2*inch], styles, colors),
        P("2. Configuration reserved for future screening", "SectionDU"),
        P("These parameters are recorded for later ligand screening; they were not executed while creating this protocol. No ligand docking, docking seeds, pose generation, clustering, or interaction analysis was performed."),
        report_table(Table, TableStyle, Paragraph, settings, [1.63*inch, 1.55*inch, 1.63*inch, 1.55*inch], styles, colors),
        Spacer(1, 6), P("<b>Protocol interpretation.</b> This configuration is technically complete and reproducible. Its selected site and future docking results remain structural hypotheses because bound-ligand pose recovery was not evaluated."),
        Spacer(1, 9), P("<b>Protocol use summary</b>", "SmallDU"), Spacer(1, 4),
        report_table(Table, TableStyle, Paragraph, use, [2.15*inch, 4.2*inch], styles, colors),
        PageBreak(), P("3. Ligand-defined docking region", "SectionDU"),
        P(f"{protocol['site_anchor']} was used only as a structural site anchor. The prepared receptor and exact ligand-centered box shown below are retained in the portable protocol. No ligand redocking, RMSD analysis, pose clustering, or interaction analysis was performed while creating this protocol."),
    ]
    removal_note = approved_removal_summary(protocol)
    if removal_note:
        story.insert(5, P(removal_note, "SmallDU"))
    if figure and Path(figure).is_file():
        item = Image(str(figure)); item._restrictSize(3.6*inch, 2.72*inch); item.hAlign = "CENTER"; story.append(item)
        story.append(P(f"<b>Figure 1. Ligand-guided docking region for {protocol['target']}.</b> {protocol['site_anchor']} from the selected structure is shown within the prepared receptor. The wireframe records the {box['size_x']} × {box['size_y']} × {box['size_z']} Å Vina-format search box. The ligand identifies the region of interest but does not constitute pose-recovery validation.", "CaptionDU"))
    references = [
        P("1. Eberhardt J, Santos-Martins D, Tillack AF, Forli S. AutoDock Vina 1.2.0. J Chem Inf Model. 2021;61:3891-3898. doi:10.1021/acs.jcim.1c00203", "SmallDU"),
    ]
    if protocol["engine"] == "qvinaw":
        references.append(P("2. Hassan NM, Alhossary AA, Mu Y, Kwoh CK. Protein-Ligand Blind Docking Using QuickVina-W With Inter-Process Spatio-Temporal Integration. Sci Rep. 2017;7:15451. doi:10.1038/s41598-017-15571-7", "SmallDU"))
    references.append(P(f"{len(references) + 1}. Santos-Martins D, He Y, Eberhardt J, et al. Meeko: molecule parameterization and software interoperability for docking and beyond. J Chem Inf Model. 2025;65:13045-13050. doi:10.1021/acs.jcim.5c02271", "SmallDU"))
    story += [
        P("4. Reproducibility, software, and references", "SectionDU"),
        P("The protocol retains the prepared receptor, docking-box configuration, source ligand coordinates, preparation audits, selected settings, and recorded software versions needed to reproduce and review later use."),
        report_table(Table, TableStyle, Paragraph, software, [2.15*inch, 2.25*inch, 1.95*inch], styles, colors),
        Spacer(1, 7), P("<b>Selected references</b>", "SmallDU"),
        *references,
    ]
    SimpleDocTemplate(str(out), pagesize=letter, leftMargin=.58*inch, rightMargin=.58*inch, topMargin=.38*inch, bottomMargin=.56*inch, title="Docking Universal protocol development report").build(story)


def write_site_guided_report(cli, study, manifest):
    report = study / "report"
    report.mkdir(exist_ok=True)
    (report / "study_summary.json").write_text(json.dumps(manifest, indent=2) + "\n")
    try:
        run([sys.executable, Path(__file__).with_name("docking-universal-report-figures.py"), study])
        out = report / f"{safe_id(manifest['target'])}_site-guided-exploratory_{manifest['created_utc'][:10]}_cavity_report.pdf"
        run([sys.executable, Path(__file__).with_name("docking-universal-pdf-report.py"), study, "--out", out])
        return out
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f"Site-guided report generation failed with exit status {exc.returncode}") from None


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", choices=(CONTROL_VALIDATED, LIGAND_GUIDED_EXPLORATORY, SITE_GUIDED_EXPLORATORY))
    parser.add_argument("--complex", type=Path, help="selected structure PDB")
    parser.add_argument("--region-definition", choices=REGION_CHOICES)
    parser.add_argument("--fpocket-selection", choices=("automatic", "reviewed"))
    parser.add_argument("--residues", help="comma-separated residues such as A:HIS57,A:ASP102")
    parser.add_argument("--ligand-resname")
    parser.add_argument("--ligand-id", help="exact RESNAME:CHAIN:RESNUM for non-interactive control validation")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--accept-exploratory", action="store_true", help="authorize creation of a reusable exploratory protocol")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--no-visuals", action="store_true")
    parser.add_argument("--pymol", default="pymol", help="PyMOL executable used for interactive pocket review")
    parser.add_argument("--box-size", type=float, default=26.0)
    parser.add_argument("--exhaustiveness", type=int, default=16)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--num-modes", type=int, default=15)
    parser.add_argument("--energy-range", type=float, default=8.0)
    parser.add_argument("--conformers", type=int, default=3)
    parser.add_argument("--engine", choices=("vina", "qvinaw"), help="override the engine recommended from the approved docking box")
    parser.add_argument("--ph", type=float, default=7.4)
    parser.add_argument("--base-seed", type=int, default=20260808)
    parser.add_argument("--control-tier", choices=("quick", "repeatability", "broader", "conformers", "robust"), default="repeatability", help="control-validated sampling tier (default: repeatability)")
    parser.add_argument("--conformers-override", type=int, help="control conformers per state; overrides the selected tier")
    return parser.parse_args()


def main():
    args = parse_args()
    project = Path(__file__).resolve().parent.parent
    cli = Path(os.environ.get("DOCKING_UNIVERSAL_CLI", project / "bin/docking-universal"))
    region_definition = args.region_definition
    if not region_definition:
        if args.non_interactive:
            region_definition = (
                REGION_BOUND_LIGAND
                if args.type in {CONTROL_VALIDATED, LIGAND_GUIDED_EXPLORATORY}
                else REGION_FPOCKET
            )
        else:
            region_definition = choose_region()
    kind = args.type
    if region_definition == REGION_BOUND_LIGAND:
        if not kind:
            if args.non_interactive:
                raise SystemExit("A bound-ligand region requires --type control-validated or ligand-guided-exploratory")
            print("\nHow should the selected bound ligand be used?")
            print("  1) Pose-recovery control — remove and redock it to validate the protocol")
            print("  2) Site reference only — define the box without redocking it")
            answer = input("Select [1]: ").strip() or "1"
            kind = {"1": CONTROL_VALIDATED, "2": LIGAND_GUIDED_EXPLORATORY}.get(answer)
            if not kind:
                raise SystemExit("Choose bound-ligand use 1 or 2")
        if kind not in {CONTROL_VALIDATED, LIGAND_GUIDED_EXPLORATORY}:
            raise SystemExit("A bound-ligand region must be control-validated or ligand-guided exploratory")
    else:
        if kind and kind != SITE_GUIDED_EXPLORATORY:
            raise SystemExit("Predicted-pocket, selected-residue, and whole-protein regions are site-guided exploratory")
        kind = SITE_GUIDED_EXPLORATORY
    if kind == CONTROL_VALIDATED:
        provisional_box = {
            "center_x": 0, "center_y": 0, "center_z": 0,
            "size_x": args.box_size, "size_y": args.box_size, "size_z": args.box_size,
        }
        engine_selection = choose_engine(
            provisional_box, region_definition, requested=args.engine,
            interactive=not args.non_interactive,
        )
        command = [
            sys.executable, Path(__file__).with_name("docking-universal-run.py"),
            "--mode", "control", "--control-tier", args.control_tier,
            "--ph", args.ph, "--base-seed", args.base_seed,
            "--engine", engine_selection["selected_engine"],
        ]
        if args.complex: command += ["--complex", args.complex]
        if args.out: command += ["--out", args.out]
        if args.ligand_id: command += ["--control-ligand-id", args.ligand_id]
        if args.conformers_override: command += ["--conformers-override", args.conformers_override]
        if args.non_interactive: command.append("--non-interactive")
        if args.no_visuals: command.append("--no-visuals")
        if args.non_interactive and not args.ligand_id:
            raise SystemExit("control-validated creation requires --ligand-id RESNAME:CHAIN:RESNUM in non-interactive mode")
        try:
            run(command)
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"Control-validated protocol creation stopped (exit status {exc.returncode}); completed outputs were retained for review") from None
        return
    if args.non_interactive and not args.accept_exploratory:
        raise SystemExit("Exploratory protocol creation requires --accept-exploratory in non-interactive mode")
    if not args.non_interactive and not args.accept_exploratory:
        print("This protocol will record site selection without bound-ligand pose-recovery validation.")
        if input("Create it for explicitly exploratory screening? [y/N]: ").strip().lower() not in {"y", "yes"}:
            raise SystemExit("Protocol creation cancelled")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temporary_target = safe_id(args.complex.stem if args.complex else "protein")
    output_parent = choose_output_parent() if args.out is None and not args.non_interactive else Path.cwd()
    study = (args.out or output_parent / f"protocol_{temporary_target}_{kind}_{timestamp}").expanduser().resolve()
    if study.exists():
        raise SystemExit(f"Output directory already exists: {study}")
    inputs = study / "inputs"; preparation = study / "preparation"; report = study / "report"
    inputs.mkdir(parents=True); preparation.mkdir(); report.mkdir()
    source = args.complex.expanduser().resolve() if args.complex else choose_structure(inputs)
    if not source.is_file():
        raise SystemExit(f"Structure file does not exist: {source}")
    local_structure = inputs / source.name
    if source.resolve() != local_structure.resolve():
        shutil.copy2(source, local_structure)
    target = safe_id(local_structure.stem)
    environment = os.environ.copy()
    environment.update({
        "FEEDBACK_LEVEL": "concise",
        "DOCKING_UNIVERSAL_SITE_MODE": "ligand" if region_definition == REGION_BOUND_LIGAND else "pockets",
        "DOCKING_UNIVERSAL_CAVITY_MODE": "1", "DOCKING_UNIVERSAL_MAX_POCKETS": "3", "DOCKING_UNIVERSAL_CENTER_MODE": "centroid",
        "DOCKING_UNIVERSAL_CENTROID_MODE": "2", "DOCKING_UNIVERSAL_LOG_MODE": "file", "STRICT_LOCAL_POCKETS": "1",
        "BOX_SIZE": str(args.box_size),
    })
    if args.ligand_resname:
        environment["DOCKING_UNIVERSAL_LIGAND_RESNAME"] = args.ligand_resname
    run([cli, "prepare", local_structure], cwd=preparation, env=environment)
    prep_root = next(iter(sorted(preparation.glob("*_receptor_prep"))), None)
    if not prep_root:
        raise SystemExit("Preparation output could not be located")
    receptor_pdbqt = next(iter(sorted(prep_root.glob("receptor/*.pdbqt"))), None)
    receptor_pdb = next(iter(sorted(prep_root.glob("receptor/*.pdb"))), None)
    boxes = sorted(prep_root.glob("cavity/*.conf"))
    score_threshold_used = 0.10 if region_definition in {REGION_FPOCKET, REGION_WHOLE_PROTEIN} else None
    if region_definition == REGION_FPOCKET and not boxes:
        if not retry_fpocket_fallback(args.non_interactive):
            raise SystemExit("No docking box was selected; cavity preparation was retained for review")
        fallback_environment = environment.copy()
        fallback_environment["SCORE_THRESHOLD"] = "0.0"
        run([cli, "prepare", local_structure], cwd=preparation, env=fallback_environment)
        prep_root = next(iter(sorted(preparation.glob("*_receptor_prep"))), None)
        receptor_pdbqt = next(iter(sorted(prep_root.glob("receptor/*.pdbqt"))), None)
        receptor_pdb = next(iter(sorted(prep_root.glob("receptor/*.pdb"))), None)
        boxes = sorted(prep_root.glob("cavity/*.conf"))
        score_threshold_used = 0.0
    if not receptor_pdbqt or not receptor_pdb:
        raise SystemExit("Prepared receptor outputs are incomplete")
    pocket_review_scene = None
    fpocket_selection = args.fpocket_selection
    if region_definition == REGION_FPOCKET and not fpocket_selection:
        fpocket_selection = "automatic" if args.non_interactive else choose_fpocket_selection()
    if region_definition == REGION_FPOCKET and fpocket_selection == "reviewed":
        pocket_review_scene = review_pocket_scene(
            preparation,
            args.pymol,
            interactive=not args.non_interactive and not args.no_visuals,
        )
    elif region_definition == REGION_WHOLE_PROTEIN:
        pocket_review_scene = review_pocket_scene(preparation, args.pymol, interactive=False, requested=False)
    if region_definition == REGION_WHOLE_PROTEIN:
        selected_box = write_box_files(
            prep_root / "cavity" / f"{target}_whole-protein.conf",
            whole_protein_box(receptor_pdbqt),
        )
    elif region_definition == REGION_RESIDUES:
        residue_text = args.residues
        if not residue_text:
            if args.non_interactive:
                raise SystemExit("--residues is required for a non-interactive selected-residue protocol")
            residue_text = input("Residues (for example A:HIS57,A:ASP102): ").strip()
        residue_values, selected_residues = residue_box(
            local_structure, [item.strip() for item in residue_text.split(",") if item.strip()]
        )
        selected_box = write_box_files(
            prep_root / "cavity" / f"{target}_selected-residues.conf", residue_values
        )
    elif region_definition == REGION_FPOCKET and fpocket_selection == "automatic":
        selected_box = choose_box(boxes, False)
    else:
        selected_box = choose_box(boxes, not args.non_interactive)
    ligand = choose_ligand(detected_ligands(preparation), args.ligand_resname, not args.non_interactive) if region_definition == REGION_BOUND_LIGAND else None
    values = box_values(selected_box)
    if not args.non_interactive:
        print("\nProposed docking box:")
        print(f"  Center: {values.get('center_x')}, {values.get('center_y')}, {values.get('center_z')} Å")
        print(f"  Dimensions: {values.get('size_x')} × {values.get('size_y')} × {values.get('size_z')} Å")
        if input("Approve this docking region? [Y/n]: ").strip().lower() in {"n", "no"}:
            raise SystemExit("Docking-region approval declined; no protocol was created")
    engine_selection = choose_engine(
        values, region_definition, requested=args.engine, interactive=not args.non_interactive
    )
    engine = engine_selection["selected_engine"]
    if region_definition == REGION_BOUND_LIGAND:
        evidence_basis = f"Coordinates of {ligand['resname']} in the selected structure used for site definition"
    elif region_definition == REGION_FPOCKET:
        evidence_basis = f"fpocket cavity analysis and {fpocket_selection} pocket selection"
    elif region_definition == REGION_RESIDUES:
        evidence_basis = "User-selected residues: " + ", ".join(selected_residues)
    else:
        evidence_basis = (
            "Prepared receptor coordinate bounds with a 4 Angstrom margin; "
            "fpocket characterized cavities but did not constrain the box"
        )
    date = datetime.now(timezone.utc).isoformat()
    subject = f"{target}_{safe_id(ligand['resname'])}_" if ligand else f"{target}_"
    base = f"{subject}{kind}_{engine}_{date[:10]}"
    bundle_name = f"{base}.duprotocol"
    audit = next(iter(sorted(prep_root.glob("receptor/pdbfixer_audit.json"))), None)
    ccd_audit = next(iter(sorted(prep_root.glob("receptor/ccd_modification_audit.json"))), None)
    removal_log = next(iter(sorted(prep_root.glob("receptor/receptor_user_approved_removal.log"))), None)
    removal_record = next(iter(sorted(prep_root.glob("receptor/user_approved_component_removal.txt"))), None)
    removal_manifest = next(iter(sorted(prep_root.glob("receptor/user_approved_component_removal.tsv"))), None)
    removed_components = read_removal_manifest(removal_manifest)
    modification_warning = build_receptor_modification_warning(removed_components, bool(removal_record))
    ligand_pdb = ligand["path"] if ligand else None
    protocol = {
        "schema_name": "docking-universal-protocol", "schema_version": 1, "schema_status": "stable_v1",
        "protocol_type": kind, "target": target, "site_anchor": ligand["resname"] if ligand else Path(selected_box).stem,
        "evidence_basis": evidence_basis, "screening_authority": "user-confirmed-exploratory-use",
        "created_utc": date, "control_status": "not_performed", "unknown_docking_allowed": False,
        "exploratory_screening_allowed": True, "engine": engine,
        "software": scientific_software_record(engine),
        "region_definition": region_definition,
        "fpocket_selection": fpocket_selection,
        "selected_residues": selected_residues if region_definition == REGION_RESIDUES else [],
        "engine_selection": engine_selection,
        "parameters": {
            "ph": args.ph, "conformers_per_state": args.conformers, "ensemble_seed": args.base_seed,
            "forcefield": "mmff94", "rmsd_prune_angstrom": 0.75, "tautomers_enumerated": True,
            "charge_model": "gasteiger", "macrocycle_treatment": "flexible_meeko" if engine == "vina" else "rigid_conformer_ensemble",
            "exhaustiveness": args.exhaustiveness, "num_modes": args.num_modes,
            "energy_range_kcal_per_mol": args.energy_range,
            "seeds": [args.base_seed + index for index in range(args.seeds)],
        },
        "locked_inputs": {
            "receptor": str(receptor_pdbqt), "receptor_sha256": sha256(receptor_pdbqt),
            "receptor_pdb": str(receptor_pdb), "box": str(selected_box), "box_sha256": sha256(selected_box),
        },
        "docking_box": {key: values.get(key, "not recorded") for key in ("center_x", "center_y", "center_z", "size_x", "size_y", "size_z")},
        "receptor_preparation": {
            "pdbfixer_audit": str(audit) if audit else None,
            "ccd_modification_audit": str(ccd_audit) if ccd_audit else None,
            "user_approved_component_removal": bool(removal_record),
            "user_approved_component_removal_log": str(removal_log) if removal_log else None,
            "user_approved_component_removal_record": str(removal_record) if removal_record else None,
            "user_approved_component_removal_manifest": str(removal_manifest) if removal_manifest else None,
            "user_approved_removed_components": removed_components,
            "receptor_modification_warning": modification_warning,
        },
        "receptor_preparation_summary": preparation_summary(prep_root),
        "cavity_score_threshold_used": score_threshold_used,
        "pocket_review_scene": pocket_review_scene,
        "bundle_file_name": bundle_name,
        "scientific_scope": {"purpose": "reusable exploratory site definition", "does_not_establish": ["pose-recovery validation", "binding affinity accuracy", "biological activity"]},
    }
    protocol_path = study / f"{base}_protocol.json"
    protocol_path.write_text(json.dumps(protocol, indent=2) + "\n")
    figure = render_box_figure(
        cli,
        preparation,
        report,
        args.no_visuals,
        receptor_pdb=receptor_pdb,
        ligand_pdb=ligand_pdb,
        box_conf=selected_box,
    )
    if figure:
        protocol["pymol_version"] = command_version([
            sys.executable, "-c", "from pymol import cmd; print(cmd.get_version()[0])",
        ])
        protocol_path.write_text(json.dumps(protocol, indent=2) + "\n")
    if kind == LIGAND_GUIDED_EXPLORATORY:
        report_pdf = report / f"{base}_protocol_report.pdf"
        write_ligand_guided_pdf(report_pdf, protocol, figure)
    else:
        manifest = {
            "schema_name": "docking-universal-study", "schema_version": 1, "workflow": "exploratory",
            "study_name": base, "study_status": "EXPLORATORY_NO_CONTROL", "completion_status": "COMPLETED",
            "created_utc": date, "target": target, "target_source": str(local_structure), "compound_count": 0,
            "cavity_score_threshold_used": score_threshold_used,
            "protocol_type": kind, "protocol_validation_status": "Site-guided exploratory protocol; not evaluated by bound-ligand control",
            "region_definition": region_definition,
            "fpocket_selection": fpocket_selection,
            "engine_selection": engine_selection,
            "configured_engine": engine, "configured_engine_version": "recorded when screening runs",
            "configured_docking_parameters": protocol["parameters"], "configured_locked_inputs": protocol["locked_inputs"],
            "docking_universal_version": package_version(),
            "scientific_software": {
                "docking_universal": package_version(),
                "python": sys.version.split()[0],
                "meeko": distribution_version("meeko"),
                "pdbfixer": distribution_version("pdbfixer"),
                "fpocket": conda_package_version("fpocket"),
                "engine_version": "recorded when screening runs",
            },
            "compounds": [],
        }
        report_pdf = write_site_guided_report(cli, study, manifest)
    bundle = create_bundle(protocol_path, study, study / bundle_name)
    print("\nSelected protocol:")
    print(f"  Target: {target}")
    print(f"  Protocol type: {protocol_type_label(kind)}")
    print(f"  Evidence basis: {evidence_basis}")
    print(f"  Region definition: {region_definition}")
    print(f"  Docking engine: {'AutoDock Vina' if engine == 'vina' else 'QuickVina-W'}")
    print("  Screening authority: User-confirmed exploratory use")
    print(f"  Created: {date[:10]}")
    print(f"  Docking box: {selected_box.name}, {values.get('size_x', 'NA')} × {values.get('size_y', 'NA')} × {values.get('size_z', 'NA')} Å")
    print(f"  Protocol bundle: {bundle.name}")
    print(f"Protocol report: {report_pdf}")
    print("No ligand docking was performed.")


if __name__ == "__main__":
    main()
