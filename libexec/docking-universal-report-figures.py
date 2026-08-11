#!/usr/bin/env python3
"""Generate final report figures directly from retained docking artifacts."""

import argparse
import csv
import io
import json
import math
import os
import shutil
import subprocess
import sys
from pathlib import Path


TOP_COLORS = ("#d62728", "#1f77b4", "#d9a400")


def read_json(path):
    try:
        return json.loads(Path(path).read_text()) if path and Path(path).is_file() else {}
    except (OSError, ValueError, TypeError):
        return {}


def choose_protocol(control):
    candidates = list(control.glob("**/protocol.json")) if control else []
    if not candidates:
        return None

    def rank(path):
        record = read_json(path)
        acceptance = record.get("acceptance", {})
        return (
            int(bool(record.get("unknown_docking_allowed"))),
            int(bool(acceptance.get("sampling_pass") and acceptance.get("ranking_pass") and acceptance.get("seed_requirement_pass"))),
            int(acceptance.get("independent_seed_count", 0) or 0),
        )

    return max(candidates, key=rank)


def discover_control(study):
    for manifest_path in sorted(study.glob("compounds/*/screen_manifest.json")):
        protocol = Path(str(read_json(manifest_path).get("protocol", ""))).expanduser()
        if not protocol.is_file():
            continue
        for parent in protocol.parents:
            if parent.name == "control":
                return parent
    return None


def pymol_executable(requested):
    explicit = Path(requested).expanduser()
    if explicit.is_file():
        return explicit
    found = shutil.which(requested)
    if found:
        return Path(found)
    adjacent = Path(sys.executable).resolve().parent / "pymol"
    return adjacent if adjacent.is_file() else None


def plip2d_executable(requested=None):
    """Locate the optional GPL plip_to_2D runner without vendoring it."""
    candidates = [
        requested,
        os.environ.get("DOCKING_UNIVERSAL_PLIP2D_RUNNER"),
        str(Path.home() / "tools" / "plip_to_2D" / "plip_2D_direct_unl.py"),
        shutil.which("plip_2D_direct_unl.py"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).expanduser().is_file():
            return Path(candidate).expanduser().resolve()
    return None


def plip_executable():
    candidates = [shutil.which("plip"), Path(sys.executable).resolve().parent / "plip"]
    return next((Path(value).resolve() for value in candidates if value and Path(value).is_file()), None)


def first(root, patterns):
    for pattern in patterns:
        hits = sorted(root.glob(pattern))
        if hits:
            return hits[0]
    return None


def read_key_value_tsv(path):
    values = {}
    if not path:
        return values
    try:
        with Path(path).open(newline="") as handle:
            for row in csv.reader(handle, delimiter="\t"):
                if len(row) >= 2:
                    values[row[0]] = row[1]
    except OSError:
        pass
    return values


def cavity_artifacts(study):
    diagnostics = first(study, [
        "preparation/*_receptor_prep/cavity/pocket_selection_diagnostics.tsv",
        "**/cavity/pocket_selection_diagnostics.tsv",
    ])
    if not diagnostics:
        return None, None, None
    manifest = read_key_value_tsv(first(study, [
        "compounds/*/seed_*/docking/run_manifest.tsv", "**/docking/run_manifest.tsv",
    ]))
    selected_config = Path(manifest.get("config", "")).name
    selected_stem = Path(selected_config).stem if selected_config else ""
    selected_pml = diagnostics.parent / f"{selected_stem}.pml" if selected_stem else None
    if not selected_pml or not selected_pml.is_file():
        selected_pml = first(diagnostics.parent, ["*_pocket*.pml"])
    return diagnostics, selected_config or None, selected_pml


def plot_cavity_selection(diagnostics, selected_config, output):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with Path(diagnostics).open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    if not rows:
        return False
    selected_pocket = None
    match = __import__("re").search(r"pocket(\d+)", selected_config or "", __import__("re").I)
    if match:
        selected_pocket = f"pocket{match.group(1)}_atm.pdb"
    ranks = [int(row.get("rank_order", index + 1)) for index, row in enumerate(rows)]
    scores = [float(row.get("score", "nan")) for row in rows]
    colors = ["#1f77b4" if row.get("decision") == "selected" else "#b8c0c8" for row in rows]
    if selected_pocket:
        colors = ["#d62728" if row.get("pocket_file") == selected_pocket else color for row, color in zip(rows, colors)]
    fig, ax = plt.subplots(figsize=(10.5, 6.2))
    ax.scatter(ranks, scores, c=colors, s=105, edgecolor="black", linewidth=.6, zorder=3)
    for rank, score, row in zip(ranks, scores, rows):
        if row.get("pocket_file") == selected_pocket:
            ax.annotate(
                f"Docking box: {Path(selected_config).stem}", (rank, score), xytext=(18, 18),
                textcoords="offset points", fontsize=11,
                bbox=dict(fc="white", ec="#d62728", alpha=.96),
                arrowprops=dict(arrowstyle="->", color="#d62728"),
            )
    ax.set_xlabel("Cavity rank after geometry and overlap filtering", fontsize=14)
    ax.set_ylabel("fpocket score", fontsize=14)
    ax.set_title("Ligand-free cavity candidates and selected docking region", fontsize=16)
    ax.grid(alpha=.25)
    ax.tick_params(labelsize=11)
    ax.text(
        .98, .97, "Red = box used for docking\nBlue = retained candidate\nGray = skipped overlapping candidate",
        transform=ax.transAxes, ha="right", va="top", fontsize=10,
        bbox=dict(fc="white", ec="0.6", alpha=.95),
    )
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=240)
    plt.close(fig)
    return True


def render_cavity_scene(scene, output, session, pymol):
    if not pymol or not scene or not Path(scene).is_file():
        return False
    wrapper = output.with_suffix(".pml")
    output_arg = str(output.resolve()).replace(" ", "\\ ")
    session_arg = str(session.resolve()).replace(" ", "\\ ")
    wrapper.write_text(Path(scene).read_text(errors="replace") + "\n" + "\n".join([
        "bg_color white",
        "set ray_opaque_background, off", "set depth_cue, 0", "zoom all, 4",
        f"png {output_arg}, 1800, 1200, dpi=220, ray=1",
        f"save {session_arg}", "quit",
    ]) + "\n")
    result = subprocess.run([str(pymol), "-cq", str(wrapper)], cwd=str(Path(scene).parent), text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Report figure warning: cavity PyMOL render failed: {result.stderr.strip()}", file=sys.stderr)
    return result.returncode == 0 and output.is_file()


def build_cavity_figures(study, pymol):
    diagnostics, selected_config, scene = cavity_artifacts(study)
    if not diagnostics:
        return []
    report = study / "report"
    report.mkdir(parents=True, exist_ok=True)
    outputs = []
    panel_a = report / "cavity_panel_A_selection.png"
    if plot_cavity_selection(diagnostics, selected_config, panel_a):
        outputs.append(str(panel_a))
    panel_b = report / "cavity_panel_B_structure.png"
    if render_cavity_scene(scene, panel_b, report / "cavity_panel_B_structure.pse", pymol):
        outputs.append(str(panel_b))
    combined = report / "cavity_panels_AB.png"
    if panel_a.is_file() and panel_b.is_file():
        combine_panels(panel_a, panel_b, combined, control=False)
        outputs.append(str(combined))
    return outputs


def ensure_control_clusters(control, protocol_path):
    output = control / "report" / "control_pose_analysis"
    if (output / "cluster_summary.csv").is_file():
        return output
    protocol = read_json(protocol_path)
    receptor_pdbqt = Path(str(protocol.get("locked_inputs", {}).get("receptor", "")))
    receptor = receptor_pdbqt.with_suffix(".pdb")
    if not receptor.is_file():
        receptor = first(control, ["01_preparation/*_receptor_prep/receptor/*.pdb", "**/receptor.pdb"])
    if not receptor or not receptor.is_file():
        return None
    script = Path(__file__).with_name("docking-universal-cluster-poses.py")
    command = [
        sys.executable, str(script), "--comparison-root", str(protocol_path.parent),
        "--receptor", str(receptor), "--out", str(output),
        "--cluster-rmsd", str(protocol.get("acceptance", {}).get("threshold_angstrom", 2.0)),
        "--representatives", "20",
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Report figure warning: control clustering failed: {result.stderr.strip()}", file=sys.stderr)
        return None
    return output


def cluster_rows(analysis):
    path = analysis / "cluster_summary.csv"
    if not path.is_file():
        return []
    with path.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    return sorted(rows, key=lambda row: int(row.get("energy_rank", 999999)))


def rmsd_between(reference, molecule):
    from rdkit import Chem
    from rdkit.Chem import rdMolAlign

    reference = Chem.RemoveHs(reference)
    molecule = Chem.RemoveHs(molecule)
    if reference.GetNumAtoms() != molecule.GetNumAtoms():
        return float("nan")
    return rdMolAlign.CalcRMS(molecule, reference, maxMatches=100000)


def read_molecule(path):
    from rdkit import Chem

    path = Path(path)
    if not path.is_file():
        return None
    return next((mol for mol in Chem.SDMolSupplier(str(path), removeHs=False) if mol), None)


def retained_cluster_representatives(analysis):
    """Recover every lowest-energy cluster member from retained pose artifacts."""
    from rdkit import Chem

    representatives = {}
    inventory_path = analysis / "pose_inventory.csv"
    all_poses_path = analysis / "all_poses.sdf"
    if not inventory_path.is_file() or not all_poses_path.is_file():
        return representatives
    with inventory_path.open(newline="") as handle:
        inventory = list(csv.DictReader(handle))
    best_by_cluster = {}
    for row in inventory:
        try:
            cluster_id = int(row["cluster_id"])
            energy = float(row["energy_kcal_per_mol"])
            pose_id = int(row["pose_id"])
        except (KeyError, TypeError, ValueError):
            continue
        previous = best_by_cluster.get(cluster_id)
        if previous is None or energy < previous[0]:
            best_by_cluster[cluster_id] = (energy, pose_id)
    molecules = list(Chem.SDMolSupplier(str(all_poses_path), removeHs=False))
    for cluster_id, (_, pose_id) in best_by_cluster.items():
        if 1 <= pose_id <= len(molecules) and molecules[pose_id - 1] is not None:
            representatives[cluster_id] = molecules[pose_id - 1]
    return representatives


def plot_clusters(analysis, output, reference_sdf=None, control_label=None):
    import math
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import FancyBboxPatch

    rows = cluster_rows(analysis)[:20]
    retained = retained_cluster_representatives(analysis)
    entries = []
    for row in rows:
        cid = int(row["cluster_id"])
        molecule = read_molecule(analysis / f"cluster_{cid:03d}" / "representative.sdf") or retained.get(cid)
        if molecule:
            entries.append((row, molecule))
    if not entries:
        return False

    reference = read_molecule(reference_sdf) if reference_sdf else entries[0][1]
    if reference is None:
        return False
    energies = [float(row["best_energy_kcal_per_mol"]) for row, _ in entries]
    rmsds = []
    for _, molecule in entries:
        try:
            value = rmsd_between(reference, molecule)
        except Exception:
            value = float("nan")
        rmsds.append(value)
    finite = [value for value in rmsds if math.isfinite(value)]
    replacement = sorted(finite)[len(finite) // 2] if finite else 0.0
    rmsds = [value if math.isfinite(value) else replacement for value in rmsds]
    sizes = [70 + int(row.get("pose_count", 1)) * 8 for row, _ in entries]
    colors = list(TOP_COLORS[:min(3, len(entries))]) + ["#b8c0c8"] * max(0, len(entries) - 3)

    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.scatter(energies, rmsds, s=sizes, c=colors, edgecolor="black", linewidth=0.7, alpha=0.9)
    ax.set_xlabel("Best cluster Vina score (kcal/mol)", fontsize=15)
    if control_label:
        ax.set_ylabel(f"No-fit heavy-atom RMSD to experimental {control_label} (A)", fontsize=15)
        ax.set_title("Top 20 control pose clusters and experimental-pose recovery", fontsize=17)
        ax.text(
            .98, .98,
            "One point = one control cluster\nPoint size = cluster population\nRed/blue/gold = three most favorable scores",
            transform=ax.transAxes, ha="right", va="top", fontsize=11,
            bbox=dict(fc="white", ec="0.6", alpha=.95),
        )
    else:
        ax.set_ylabel("No-fit heavy-atom RMSD from lowest-energy representative (A)", fontsize=15)
        ax.set_title("Top 20 clusters: docking score, population, and structural distance", fontsize=17)
        ax.add_patch(FancyBboxPatch((.54, .02), .44, .22, transform=ax.transAxes, boxstyle="round,pad=.012", fc="white", ec="0.6", alpha=.95, zorder=5))
        ax.text(.95, .22, "Top clusters", transform=ax.transAxes, fontsize=12, va="top", ha="right", zorder=6)
        for y, index, color in zip((.185, .158, .131), range(min(3, len(entries))), TOP_COLORS):
            row = entries[index][0]
            ax.text(.95, y, f"C{row['cluster_id']}: {energies[index]:.2f} kcal/mol | {rmsds[index]:.2f} A", transform=ax.transAxes, fontsize=11, va="top", ha="right", color=color, zorder=6)
        ax.text(.95, .095, "Point size = cluster population\nRMSD reference: lowest-energy cluster representative", transform=ax.transAxes, fontsize=10, va="top", ha="right", zorder=6)
    # RMSD cannot be negative, but a small display margin below zero keeps an
    # exact 0 A reference point fully visible instead of clipping it against
    # the lower plot boundary. Keep the labeled ticks scientifically valid.
    upper = ax.get_ylim()[1]
    lower_margin = max(0.25, upper * 0.04)
    ax.set_ylim(bottom=-lower_margin)
    ax.set_yticks([tick for tick in ax.get_yticks() if tick >= 0])
    ax.axhline(0, color="0.45", linewidth=0.8, zorder=0)
    ax.tick_params(labelsize=12)
    ax.grid(alpha=.25)
    fig.tight_layout(rect=[.04, .06, .99, .97])
    fig.savefig(output, dpi=240)
    plt.close(fig)
    return True


def render_overlay(receptor, ligands, colors, output, session, pymol):
    if not pymol or not receptor or not Path(receptor).is_file() or any(not Path(path).is_file() for path in ligands):
        return False
    pml = output.with_suffix(".pml")
    objects = []
    lines = ["reinitialize", f'load "{Path(receptor).resolve()}", receptor', "hide everything, all"]
    for index, (ligand, color) in enumerate(zip(ligands, colors), start=1):
        obj = f"report_ligand_{index}"
        objects.append(obj)
        lines += [f'load "{Path(ligand).resolve()}", {obj}', f"show sticks, {obj}", f"color {color}, {obj} and elem C", f"util.cnc {obj}"]
    selection = " or ".join(objects)
    lines += [
        f"select nearby_residues, byres (receptor within 5 of ({selection}))",
        "show sticks, nearby_residues", "color gray60, nearby_residues",
        "set stick_radius, 0.18", "set ray_opaque_background, off", "bg_color white",
        f"orient {selection}", f"zoom {selection}, 8",
        f"png {output.resolve()}, 1800, 1200, dpi=220, ray=1",
        f"save {session.resolve()}", "quit",
    ]
    pml.write_text("\n".join(lines) + "\n")
    result = subprocess.run([str(pymol), "-cq", str(pml)], text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Report figure warning: PyMOL render failed: {result.stderr.strip()}", file=sys.stderr)
    return result.returncode == 0 and output.is_file()


def plip_ligand_id(report_xml):
    import xml.etree.ElementTree as ET

    try:
        root = ET.parse(report_xml).getroot()
    except (ET.ParseError, OSError):
        return None
    identifiers = []
    for site in root.findall(".//bindingsite"):
        block = site.find("identifiers")
        if block is None:
            continue
        hetid = (block.findtext("hetid") or "").strip()
        chain = (block.findtext("chain") or "").strip()
        position = (block.findtext("position") or "").strip()
        if hetid and chain and position:
            identifiers.append(f"{hetid}:{chain}:{position}")
    return next((value for value in identifiers if value.startswith("UNL:")), identifiers[0] if identifiers else None)


def trim_white_png(path, padding=45):
    from PIL import Image, ImageChops

    image = Image.open(path).convert("RGB")
    bbox = ImageChops.difference(image, Image.new("RGB", image.size, "white")).getbbox()
    if not bbox:
        return
    bbox = (
        max(0, bbox[0] - padding), max(0, bbox[1] - padding),
        min(image.width, bbox[2] + padding), min(image.height, bbox[3] + padding),
    )
    image = image.crop(bbox)

    # plip_to_2D places its legend at the canvas bottom. Preserve it, but remove
    # the often very large empty band between the interaction drawing and legend.
    pixels = image.load()
    occupied = []
    for y in range(image.height):
        if sum(1 for x in range(image.width) if min(pixels[x, y]) < 245) > 2:
            occupied.append(y)
    spans = []
    for y in occupied:
        if not spans or y > spans[-1][1] + 1:
            spans.append([y, y])
        else:
            spans[-1][1] = y
    if len(spans) >= 2 and spans[-1][0] - spans[-2][1] > 180 and spans[-1][1] - spans[-1][0] < 120:
        main_bottom = min(image.height, spans[-2][1] + 35)
        legend_top = max(0, spans[-1][0] - 25)
        main = image.crop((0, 0, image.width, main_bottom))
        legend = image.crop((0, legend_top, image.width, image.height))
        compact = Image.new("RGB", (image.width, main.height + 20 + legend.height), "white")
        compact.paste(main, (0, 0))
        compact.paste(legend, (0, main.height + 20))
        image = compact
    image.save(path, dpi=(220, 220))


def _draw_dashed_line(draw, start, end, fill, width=4, dash=16, gap=10):
    dx, dy = end[0] - start[0], end[1] - start[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    offset = 0.0
    while offset < length:
        stop = min(length, offset + dash)
        draw.line(
            (start[0] + ux * offset, start[1] + uy * offset,
             start[0] + ux * stop, start[1] + uy * stop),
            fill=fill, width=width,
        )
        offset += dash + gap


def render_sdf_plip2d(interactions, ligand_sdf, output, ligand_id=None):
    """Draw PLIP calls on the authoritative SDF molecular graph.

    PLIP receives a PDB complex, which cannot reliably retain ligand bond order
    or aromaticity. Interaction coordinates are therefore read from PLIP XML
    but mapped onto the retained, chemically typed representative SDF before
    any 2D coordinates are generated.
    """
    import xml.etree.ElementTree as ET
    from PIL import Image, ImageDraw, ImageFont
    from rdkit import Chem
    from rdkit.Chem import rdDepictor
    from rdkit.Chem.Draw import rdMolDraw2D

    report_xml = interactions / "report.xml"
    if not report_xml.is_file() or not ligand_sdf.is_file():
        return False
    dependencies = [report_xml, ligand_sdf, Path(__file__)]
    if output.is_file() and output.stat().st_mtime >= max(path.stat().st_mtime for path in dependencies):
        return True

    try:
        root = ET.parse(report_xml).getroot()
        sites = []
        for site in root.findall(".//bindingsite"):
            identifiers = site.find("identifiers")
            if identifiers is None:
                continue
            key = ":".join((
                (identifiers.findtext("hetid") or "").strip(),
                (identifiers.findtext("chain") or "").strip(),
                (identifiers.findtext("position") or "").strip(),
            ))
            sites.append((key, site))
        if not sites:
            return False
        if not ligand_id:
            ligand_filter = read_json(interactions / "run_manifest.json").get("ligand_filter", {})
            if all(ligand_filter.get(key) for key in ("resname", "chain", "position")):
                ligand_id = f"{ligand_filter['resname']}:{ligand_filter['chain']}:{ligand_filter['position']}"
        site_key, site = next(
            ((key, value) for key, value in sites if ligand_id and key == ligand_id),
            next(((key, value) for key, value in sites if key.startswith("UNL:")), sites[0]),
        )
    except (ET.ParseError, OSError, StopIteration):
        return False

    molecule = next((mol for mol in Chem.SDMolSupplier(str(ligand_sdf), removeHs=False) if mol), None)
    if molecule is None or molecule.GetNumConformers() == 0:
        return False
    heavy_indices = [atom.GetIdx() for atom in molecule.GetAtoms() if atom.GetAtomicNum() > 1]
    conf3d = molecule.GetConformer()
    xyz = {
        index: (conf3d.GetAtomPosition(index).x, conf3d.GetAtomPosition(index).y, conf3d.GetAtomPosition(index).z)
        for index in heavy_indices
    }

    styles = {
        "hydrophobic_interactions": ("Hydrophobic", "#8a8a8a"),
        "hydrogen_bonds": ("H-bond", "#d39b00"),
        "water_bridges": ("Water bridge", "#3584c5"),
        "salt_bridges": ("Salt bridge", "#d43fbc"),
        "pi_stacks": ("Pi-stacking", "#28a745"),
        "pi_cation_interactions": ("Cation-pi", "#ef8a17"),
        "halogen_bonds": ("Halogen bond", "#00a6a6"),
        "metal_complexes": ("Metal coordination", "#7b61a8"),
    }
    residue_calls = {}
    mapping_distances = []
    interaction_block = site.find("interactions")
    if interaction_block is not None:
        for family in interaction_block:
            family_name = family.tag.split("}")[-1]
            if family_name not in styles:
                continue
            display_name, color = styles[family_name]
            for call in family:
                restype = (call.findtext("restype") or call.findtext("metal_type") or "Contact").strip()
                resnr = (call.findtext("resnr") or call.findtext("metal_idx") or "").strip()
                chain = (call.findtext("reschain") or "").strip()
                coordinate = call.find("ligcoo")
                if coordinate is None:
                    coordinate = call.find(".//ligcoo")
                try:
                    point = tuple(float(coordinate.findtext(axis)) for axis in ("x", "y", "z"))
                except (AttributeError, TypeError, ValueError):
                    continue
                atom_index, distance = min(
                    ((index, math.dist(point, xyz[index])) for index in heavy_indices),
                    key=lambda item: item[1],
                )
                mapping_distances.append(distance)
                residue = f"{restype}{resnr}" + (f":{chain}" if chain else "")
                record = residue_calls.setdefault(residue, {})
                record.setdefault(display_name, {"color": color, "atoms": []})["atoms"].append(atom_index)

    draw_molecule = Chem.Mol(molecule)
    rdDepictor.Compute2DCoords(draw_molecule, canonOrient=True, clearConfs=True)
    width, height = 2000, 1050
    drawer = rdMolDraw2D.MolDraw2DCairo(width, height)
    options = drawer.drawOptions()
    options.padding = 0.24
    options.bondLineWidth = 3
    options.minFontSize = 20
    options.maxFontSize = 34
    options.addStereoAnnotation = True
    drawer.DrawMolecule(draw_molecule)
    draw_coordinates = {index: drawer.GetDrawCoords(index) for index in heavy_indices}
    drawer.FinishDrawing()
    image = Image.open(io.BytesIO(drawer.GetDrawingText())).convert("RGB")
    draw = ImageDraw.Draw(image)
    font_path = Path("/System/Library/Fonts/Helvetica.ttc")
    label_font = ImageFont.truetype(str(font_path), 28) if font_path.is_file() else ImageFont.load_default()
    legend_font = ImageFont.truetype(str(font_path), 24) if font_path.is_file() else ImageFont.load_default()

    center_x = sum(point.x for point in draw_coordinates.values()) / len(draw_coordinates)
    center_y = sum(point.y for point in draw_coordinates.values()) / len(draw_coordinates)
    molecule_min_x = min(point.x for point in draw_coordinates.values())
    molecule_max_x = max(point.x for point in draw_coordinates.values())
    molecule_min_y = min(point.y for point in draw_coordinates.values())
    molecule_max_y = max(point.y for point in draw_coordinates.values())
    positioned = []
    for residue, calls in residue_calls.items():
        atom_set = sorted({atom for record in calls.values() for atom in record["atoms"]})
        anchor_x = sum(draw_coordinates[atom].x for atom in atom_set) / len(atom_set)
        anchor_y = sum(draw_coordinates[atom].y for atom in atom_set) / len(atom_set)
        positioned.append({"residue": residue, "calls": calls, "anchor": (anchor_x, anchor_y), "side": "left" if anchor_x < center_x else "right"})
    for side in ("left", "right"):
        entries = sorted((entry for entry in positioned if entry["side"] == side), key=lambda item: item["anchor"][1])
        if not entries:
            continue
        top = max(85, molecule_min_y - 190)
        bottom = min(height - 125, molecule_max_y + 190)
        slots = [(top + bottom) / 2] if len(entries) == 1 else [top + i * (bottom - top) / (len(entries) - 1) for i in range(len(entries))]
        for entry, label_y in zip(entries, slots):
            label_x = max(55, molecule_min_x - 240) if side == "left" else min(width - 55, molecule_max_x + 240)
            anchor_mode = "lm" if side == "left" else "rm"
            call_items = sorted(entry["calls"].items())
            for call_index, (_, record) in enumerate(call_items):
                atoms = record["atoms"]
                start = (
                    sum(draw_coordinates[atom].x for atom in atoms) / len(atoms),
                    sum(draw_coordinates[atom].y for atom in atoms) / len(atoms),
                )
                line_y = label_y + (call_index - (len(call_items) - 1) / 2) * 12
                line_x = label_x + (12 if side == "left" else -12)
                _draw_dashed_line(draw, start, (line_x, line_y), record["color"], width=4)
            bounds = draw.textbbox((label_x, label_y), entry["residue"], font=label_font, anchor=anchor_mode)
            draw.rounded_rectangle((bounds[0]-10, bounds[1]-7, bounds[2]+10, bounds[3]+7), radius=8, fill="white", outline="#b8b8b8", width=2)
            draw.text((label_x, label_y), entry["residue"], fill="black", font=label_font, anchor=anchor_mode)

    present = []
    for entry in positioned:
        for name, record in entry["calls"].items():
            if name not in [item[0] for item in present]:
                present.append((name, record["color"]))
    if present:
        widths = []
        for name, _ in present:
            bounds = draw.textbbox((0, 0), name, font=legend_font)
            widths.append(52 + bounds[2] - bounds[0] + 34)
        legend_width = sum(widths)
        x = max(40, (width - legend_width) / 2)
        y = height - 48
        for (name, color), item_width in zip(present, widths):
            _draw_dashed_line(draw, (x, y), (x + 38, y), color, width=4, dash=10, gap=7)
            draw.text((x + 50, y), name, fill="black", font=legend_font, anchor="lm")
            x += item_width

    output.parent.mkdir(parents=True, exist_ok=True)
    image.save(output, dpi=(220, 220))
    trim_white_png(output, padding=40)
    manifest = {
        "schema_name": "docking-universal-sdf-plip2d", "schema_version": 1,
        "ligand": site_key, "chemistry_source": str(ligand_sdf.resolve()),
        "interaction_source": str(report_xml.resolve()),
        "chemistry_policy": "bond orders, aromaticity, formal charges, and stereochemistry from retained SDF",
        "interaction_policy": "residue calls and ligand contact coordinates from retained PLIP XML",
        "mapped_interactions": sum(len(record["atoms"]) for calls in residue_calls.values() for record in calls.values()),
        "maximum_coordinate_mapping_distance_angstrom": max(mapping_distances) if mapping_distances else None,
    }
    output.with_suffix(".manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (interactions / "plip2d.log").write_text(
        "Renderer: Docking Universal SDF-aware PLIP diagram\n"
        f"Chemistry: {ligand_sdf}\nInteractions: {report_xml}\nOutput: {output}\n"
    )
    return True


def render_plip2d(interactions, ligand_sdf, output, runner, ligand_id=None):
    if render_sdf_plip2d(interactions, ligand_sdf, output, ligand_id=ligand_id):
        return True
    if not runner:
        return False
    report_xml = interactions / "report.xml"
    input_pdb = first(interactions, ["complex_protonated.pdb", "plipfixed*.pdb", "*.pdb"])
    ligand_id = plip_ligand_id(report_xml) if report_xml.is_file() else None
    if not input_pdb or not ligand_id:
        return False
    if output.is_file() and output.stat().st_mtime >= max(report_xml.stat().st_mtime, input_pdb.stat().st_mtime, runner.stat().st_mtime):
        trim_white_png(output)
        return True
    command = [
        sys.executable, str(runner), "-f", str(input_pdb), "-o", output.name,
        "--ligand", ligand_id, "--report-xml", str(report_xml),
        "--canvas_width", "2400", "--canvas_height", "2200",
    ]
    result = subprocess.run(command, cwd=str(interactions), text=True, capture_output=True)
    (interactions / "plip2d.log").write_text(
        f"COMMAND: {' '.join(command)}\nRETURN CODE: {result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n"
    )
    folder = ligand_id.replace(":", "_")
    generated = interactions / f"{input_pdb.stem}_output" / folder / output.name
    if result.returncode != 0 or not generated.is_file():
        print(f"Report figure warning: plip_to_2D failed for {interactions}", file=sys.stderr)
        return False
    shutil.copy2(generated, output)
    trim_white_png(output)
    return True


def combine_panels(panel_a, panel_b, output, control=False):
    from PIL import Image, ImageChops, ImageDraw, ImageFont

    a = Image.open(panel_a).convert("RGB")
    b = Image.open(panel_b).convert("RGB")
    bbox = ImageChops.difference(b, Image.new("RGB", b.size, "white")).getbbox()
    if bbox:
        pad = 65
        b = b.crop((max(0, bbox[0]-pad), max(0, bbox[1]-pad), min(b.width, bbox[2]+pad), min(b.height, bbox[3]+pad)))
    canvas_w, canvas_h = 2400, 1200
    margin, gap, label_h = 35, 30, 75
    left_w = 940 if control else 1250
    right_w = canvas_w - 2 * margin - gap - left_w

    def fit(image, width, height):
        ratio = min(width / image.width, height / image.height)
        return image.resize((int(image.width * ratio), int(image.height * ratio)), Image.Resampling.LANCZOS)

    a = fit(a, left_w, canvas_h - 2 * margin - label_h)
    b = fit(b, right_w - 70, 700)
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    a_x, a_y = margin + (left_w - a.width) // 2, margin + label_h
    b_x = margin + left_w + gap + (right_w - b.width) // 2 - (45 if control else 0)
    b_y = a_y + (a.height - b.height) // 2
    canvas.paste(a, (a_x, a_y))
    canvas.paste(b, (b_x, b_y))
    draw = ImageDraw.Draw(canvas)
    font_path = Path("/System/Library/Fonts/Helvetica.ttc")
    font = ImageFont.truetype(str(font_path), 48) if font_path.is_file() else ImageFont.load_default()
    draw.text((margin, 18), "A", fill="black", font=font)
    draw.text((b_x, 18), "B", fill="black", font=font)
    content = ImageChops.difference(canvas, Image.new("RGB", canvas.size, "white")).getbbox()
    if content:
        canvas = canvas.crop((0, 0, canvas.width, min(canvas.height, content[3] + 35)))
    canvas.save(output, quality=95, dpi=(220, 220))
    return True


def combine_cluster_snapshots(analysis, rows, output):
    """Build a compact, consistently labeled figure from up to three 3D renders."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps

    colors = TOP_COLORS
    entries = []
    for index, row in enumerate(rows[:3]):
        try:
            cluster_id = int(row["cluster_id"])
        except (KeyError, TypeError, ValueError):
            continue
        source = analysis / f"cluster_{cluster_id:03d}" / "interactions" / "complex_plip_all_in_one.png"
        if source.is_file():
            entries.append((row, source, colors[index]))
    if not entries:
        return False

    font_path = Path("/System/Library/Fonts/Helvetica.ttc")
    label_font = ImageFont.truetype(str(font_path), 42) if font_path.is_file() else ImageFont.load_default()
    caption_font = ImageFont.truetype(str(font_path), 30) if font_path.is_file() else ImageFont.load_default()
    cell_w, cell_h, image_h = 1050, 760, 650
    if len(entries) == 1:
        canvas_w, canvas_h = 1400, 920
        positions = [(175, 70)]
        cell_w, cell_h, image_h = 1050, 780, 660
    elif len(entries) == 2:
        canvas_w, canvas_h = 2200, 850
        positions = [(40, 45), (1110, 45)]
    else:
        canvas_w, canvas_h = 2200, 1660
        positions = [(40, 45), (1110, 45), (575, 855)]
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    panel_letters = "ABC"
    sources = []
    for index, ((row, source, color), (x, y)) in enumerate(zip(entries, positions)):
        snapshot = Image.open(source).convert("RGB")
        snapshot.thumbnail((cell_w - 36, image_h - 24), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (cell_w, image_h), "white")
        frame.paste(snapshot, ((cell_w - snapshot.width) // 2, (image_h - snapshot.height) // 2))
        frame = ImageOps.expand(frame, border=7, fill=color)
        canvas.paste(frame, (x, y))
        draw.text((x + 16, y + 12), panel_letters[index], fill=color, font=label_font)
        score = row.get("best_energy_kcal_per_mol", "NA")
        caption = f"Energy rank {row.get('energy_rank', index + 1)} | Cluster {row.get('cluster_id', 'NA')} | Vina {score} kcal/mol"
        bounds = draw.textbbox((0, 0), caption, font=caption_font)
        draw.text((x + (cell_w - (bounds[2] - bounds[0])) / 2, y + image_h + 28), caption, fill=color, font=caption_font)
        sources.append(str(source.resolve()))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, dpi=(220, 220))
    output.with_suffix(".manifest.json").write_text(json.dumps({
        "schema_name": "docking-universal-top-cluster-snapshots", "schema_version": 1,
        "selection": "up to three lowest-energy distinct clusters",
        "snapshot_count": len(entries), "sources": sources,
        "color_order": list(colors[:len(entries)]),
    }, indent=2) + "\n")
    return True


def ensure_control_interactions(control, protocol, protocol_path, plip):
    """Return experimental/top/best control interaction sources, creating the
    lowest-RMSD PLIP analysis from retained artifacts when it is absent."""
    experimental = control / "02_experimental_pose" / "interactions"
    experimental_sdf = first(control, ["00_inputs/*_experimental.sdf"])
    selected_root = protocol_path.parent / "selected_visuals"
    top = selected_root / "top_ranked_interactions"
    top_comparison = Path(str(protocol.get("global_top_ranked_pose", {}).get("summary", ""))).parent
    best_comparison = Path(str(protocol.get("global_best_sampled_pose", {}).get("summary", ""))).parent
    top_sdf = top_comparison / "top_score_pose.sdf"
    best_sdf = best_comparison / "best_rmsd_pose.sdf"
    best = selected_root / "best_sampled_interactions"
    if not (best / "report.xml").is_file() and plip and (best_comparison / "best_rmsd_complex.pdb").is_file() and best_sdf.is_file() and not best.exists():
        script = Path(__file__).with_name("docking-universal-interactions.py")
        command = [
            sys.executable, str(script), str(best_comparison / "best_rmsd_complex.pdb"),
            "--out-dir", str(best), "--plip-command", str(plip), "--skip-native-visuals",
            "--typed-ligand-sdf", str(best_sdf),
            "--ligand-resname", "UNL", "--ligand-chain", "Z", "--ligand-position", "1",
        ]
        result = subprocess.run(command, text=True, capture_output=True)
        if result.returncode != 0:
            print(f"Report figure warning: lowest-RMSD control PLIP analysis failed: {result.stderr.strip()}", file=sys.stderr)
    return [
        ("experimental", experimental, experimental_sdf, None),
        ("top_ranked", top, top_sdf, "UNL:Z:1"),
        ("lowest_rmsd", best, best_sdf, "UNL:Z:1"),
    ]


def build_control_figures(control, protocol_path, pymol, plip2d, plip):
    protocol = read_json(protocol_path)
    report = control / "report"
    report.mkdir(parents=True, exist_ok=True)
    analysis = ensure_control_clusters(control, protocol_path)
    reference = first(control, ["00_inputs/*_experimental.sdf", "**/crystal_ligand.sdf"])
    if not analysis or not reference:
        return []
    label = reference.stem.removesuffix("_experimental")
    panel_a = report / "control_panel_A_cluster.png"
    if not plot_clusters(analysis, panel_a, reference_sdf=reference, control_label=label):
        return []

    top = Path(str(protocol.get("global_top_ranked_pose", {}).get("summary", ""))).parent / "top_score_pose.sdf"
    best = Path(str(protocol.get("global_best_sampled_pose", {}).get("summary", ""))).parent / "best_rmsd_pose.sdf"
    receptor = analysis / "receptor.pdb"
    panel_b = report / "control_panel_B_overlay.png"
    render_overlay(receptor, [reference, top, best], ["magenta", "red", "blue"], panel_b, report / "control_panel_B_overlay.pse", pymol)
    combined = report / "control_panels_AB.png"
    if panel_b.is_file():
        combine_panels(panel_a, panel_b, combined, control=True)
    outputs = [str(path) for path in (panel_a, panel_b, combined) if path.is_file()]
    for label, interactions, ligand_sdf, ligand_id in ensure_control_interactions(control, protocol, protocol_path, plip):
        if not interactions or not ligand_sdf:
            continue
        diagram = report / f"control_{label}_plip2d.png"
        if render_plip2d(interactions, ligand_sdf, diagram, plip2d, ligand_id=ligand_id):
            outputs.append(str(diagram))
    return outputs


def build_compound_figures(study, pymol, plip2d):
    outputs = []
    report = study / "report"
    report.mkdir(parents=True, exist_ok=True)
    for compound in sorted((study / "compounds").glob("*")):
        analysis = compound / "pose_analysis"
        rows = cluster_rows(analysis)
        if not rows:
            continue
        cid = compound.name
        panel_a = report / f"{cid}_panel_A_clusters.png"
        if not plot_clusters(analysis, panel_a):
            continue
        selected = rows[:3]
        ligands = [analysis / f"cluster_{int(row['cluster_id']):03d}" / "representative.sdf" for row in selected]
        receptor = analysis / "receptor.pdb"
        panel_b = report / f"{cid}_panel_B_representatives.png"
        render_overlay(receptor, ligands, ["red", "blue", "yellow"], panel_b, report / f"{cid}_panel_B_representatives.pse", pymol)
        combined = report / f"{cid}_panels_AB.png"
        if panel_b.is_file():
            combine_panels(panel_a, panel_b, combined, control=False)
        outputs.extend(str(path) for path in (panel_a, panel_b, combined) if path.is_file())
        snapshots = report / f"{cid}_top3_3d_snapshots.png"
        if combine_cluster_snapshots(analysis, selected, snapshots):
            outputs.append(str(snapshots))
        for row in selected:
            cluster = analysis / f"cluster_{int(row['cluster_id']):03d}"
            diagram = cluster / "interactions" / "representative_plip2d.png"
            if render_plip2d(cluster / "interactions", cluster / "representative.sdf", diagram, plip2d):
                outputs.append(str(diagram))
    return outputs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--pymol", default="pymol")
    parser.add_argument("--plip2d-runner", type=Path, help="optional plip_to_2D direct runner")
    args = parser.parse_args()
    study = args.study.expanduser().resolve()
    control = args.control.expanduser().resolve() if args.control else discover_control(study)
    pymol = pymol_executable(args.pymol)
    plip2d = plip2d_executable(args.plip2d_runner)
    plip = plip_executable()
    outputs = build_compound_figures(study, pymol, plip2d)
    if not control:
        outputs.extend(build_cavity_figures(study, pymol))
    protocol = choose_protocol(control) if control else None
    if control and protocol:
        outputs.extend(build_control_figures(control, protocol, pymol, plip2d, plip))
    manifest = {
        "schema_name": "docking-universal-report-figures", "schema_version": 2,
        "study": str(study), "control": str(control) if control else None,
        "pymol": str(pymol) if pymol else None,
        "plip": str(plip) if plip else None,
        "interaction_diagram_renderer": "native_sdf_plip_xml",
        "plip_to_2d_fallback": str(plip2d) if plip2d else None, "outputs": outputs,
    }
    report = study / "report"
    report.mkdir(parents=True, exist_ok=True)
    (report / "report_figure_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Report figures: {len(outputs)} artifacts")


if __name__ == "__main__":
    main()
