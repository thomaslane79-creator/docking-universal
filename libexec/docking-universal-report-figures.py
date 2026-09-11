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

from docking_universal_box_candidates import config_geometry, grouped_fpocket_boxes


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
        summary = read_json(study / "report" / "study_summary.json")
        box = Path(str(summary.get("configured_locked_inputs", {}).get("box", ""))).expanduser()
        candidate = box.parent / "pocket_selection_diagnostics.tsv"
        if candidate.is_file():
            diagnostics = candidate
    if not diagnostics:
        return None, None, None
    manifest = read_key_value_tsv(first(study, [
        "compounds/*/seed_*/docking/run_manifest.tsv", "**/docking/run_manifest.tsv",
    ]))
    selected_config = Path(manifest.get("config", "")).name
    if not selected_config:
        preparation_config = first(diagnostics.parent, ["*_pocket*.conf"])
        selected_config = preparation_config.name if preparation_config else ""
    selected_stem = Path(selected_config).stem if selected_config else ""
    selected_pml = diagnostics.parent / f"{selected_stem}.pml" if selected_stem else None
    if not selected_pml or not selected_pml.is_file():
        selected_pml = first(diagnostics.parent, ["*_pocket*.pml"])
    return diagnostics, selected_config or None, selected_pml


def _selected_pocket_files(selected_rows, selected_configs):
    """Map generated pocket<N> box names to the retained fpocket files."""
    retained = [row for row in selected_rows if row.get("decision") == "selected"]
    retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
    selected = []
    for config in selected_configs or []:
        match = __import__("re").search(r"pocket(\d+)", str(config or ""), __import__("re").I)
        index = int(match.group(1)) - 1 if match else -1
        if 0 <= index < len(retained):
            selected.append((str(config), retained[index].get("pocket_file")))
    return selected


def _displayed_pocket_colors(selected_rows, evidence_site_numbers=()):
    """Assign stable colors to the top three displayed fpocket candidates."""
    retained = [row for row in selected_rows if row.get("decision") == "selected"]
    retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
    display_indexes = set(range(min(3, len(retained))))
    palette = [
        "#d62728", "#1f77b4", "#d9a400", "#d627c1", "#00a6b2",
        "#f28e2b", "#9467bd", "#2ca02c", "#8c564b", "#e377c2",
    ]
    return {
        retained[index].get("pocket_file"): palette[position % len(palette)]
        for position, index in enumerate(sorted(display_indexes))
    }


def _config_geometry(path):
    """Read numeric Vina box geometry from a retained configuration file."""
    values = {}
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return values
    for line in lines:
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            values[key.strip()] = float(value.strip())
        except ValueError:
            continue
    return values


def _geometry_overlap_fraction(left, right):
    """Return intersection as a fraction of the smaller box volume."""
    intersection = 1.0
    for axis in "xyz":
        left_half = left[f"size_{axis}"] / 2.0
        right_half = right[f"size_{axis}"] / 2.0
        intersection *= max(
            0.0,
            min(left[f"center_{axis}"] + left_half,
                right[f"center_{axis}"] + right_half)
            - max(left[f"center_{axis}"] - left_half,
                  right[f"center_{axis}"] - right_half),
        )
    volumes = [math.prod(box[f"size_{axis}"] for axis in "xyz")
               for box in (left, right)]
    return intersection / min(volumes) if min(volumes) > 0 else 0.0


def _pdb_points(path):
    points = []
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return points
    for line in lines:
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        try:
            points.append(tuple(float(line[start:start + 8]) for start in (30, 38, 46)))
        except ValueError:
            continue
    return points


def _points_box(points, minimum=26.0, margin=4.0):
    geometry = {}
    for index, axis in enumerate("xyz"):
        low = min(point[index] for point in points)
        high = max(point[index] for point in points)
        geometry[f"center_{axis}"] = (low + high) / 2.0
        geometry[f"size_{axis}"] = max(minimum, high - low + 2.0 * margin)
    return geometry


def displayed_fpocket_box_groups(diagnostics, retained, displayed_colors,
                                  minimum_overlap=0.35,
                                  maximum_dimension=36.0,
                                  maximum_volume=64000.0):
    """Consolidate displayed fpocket proposals into minimal bounded boxes.

    Separate fpocket score points remain visible, but candidates whose existing
    boxes overlap and whose combined cavity atoms fit within the recorded size
    limits share one rendered search box.
    """
    groups = grouped_fpocket_boxes(
        diagnostics, retained, displayed_colors,
        minimum_overlap=minimum_overlap,
        maximum_dimension=maximum_dimension,
        maximum_volume=maximum_volume,
    )
    for group in groups:
        group["color"] = displayed_colors[group["pocket_files"][0]]
    return groups


# Ligand-defined sites and fpocket candidates are separate evidence types, so
# they use separate palettes. A given site or pocket must nevertheless keep
# its assigned color in every report figure where it appears. Ligand-defined
# sites use the same palette as the approved Figure 1 site panels.
SITE_PYMOL_COLORS = ["forest", "cyan", "tv_orange", "violet", "salmon", "teal", "wheat"]
FPOCKET_PYMOL_COLORS = ["red", "marine", "gold", "magenta", "cyan", "tv_orange", "violet"]
SITE_HEX_COLORS = ["#228b22", "#00a6b2", "#f28e2b", "#9467bd", "#fa8072", "#008080", "#d9a400"]


def _site_color(site_number):
    """Return the stable PyMOL color assigned to one ligand-defined site."""
    index = max(1, int(site_number or 1)) - 1
    return SITE_PYMOL_COLORS[index % len(SITE_PYMOL_COLORS)]


def pdb_centroid(path):
    """Return the heavy-atom centroid used to place an unobstructed label."""
    coordinates = []
    try:
        lines = Path(path).read_text(errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        if not line.startswith(("ATOM  ", "HETATM")) or line[76:78].strip().upper() == "H":
            continue
        try:
            coordinates.append(tuple(float(line[start:start + 8]) for start in (30, 38, 46)))
        except ValueError:
            continue
    if not coordinates:
        return None
    return tuple(sum(point[axis] for point in coordinates) / len(coordinates) for axis in range(3))


def ligand_artifact_matches_member(path, member):
    """Require an exact PDB/ligand/chain/residue artifact identity match."""
    identity = (
        member.get("entry"), member.get("ligand"),
        member.get("ligand_chain"), member.get("ligand_residue"),
    )
    if any(value in (None, "") for value in identity):
        return False
    expected = "{}_{}_{}_{}.pdb".format(*(str(value) for value in identity))
    return Path(path).is_file() and Path(path).name == expected


def ligand_artifact_inside_box(path, geometry, tolerance=0.25):
    """Confirm that every displayed ligand atom lies inside its recorded box."""
    center = [float(geometry[f"center_{axis}"]) for axis in "xyz"]
    half = [float(geometry[f"size_{axis}"]) / 2.0 + tolerance for axis in "xyz"]
    found = False
    for line in Path(path).read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        try:
            point = [float(line[i:i + 8]) for i in (30, 38, 46)]
        except ValueError:
            continue
        found = True
        if any(abs(point[i] - center[i]) > half[i] for i in range(3)):
            return False
    return found


def pocket_label_commands(pocket_path, pocket_number, color, receptor_center=None, box_geometry=None):
    """Build color-matched PyMOL commands identifying one pocket surface."""
    center = pdb_centroid(pocket_path)
    if center is None:
        return []
    position = list(center)
    if receptor_center is not None:
        direction = [center[index] - receptor_center[index] for index in range(3)]
        length = math.sqrt(sum(value * value for value in direction))
        if length > 0.01:
            position = [center[index] + 16.0 * direction[index] / length for index in range(3)]
    if box_geometry:
        # Labels are annotations, not contents of the selected box.  If the
        # radial position still falls inside the box, move it to the nearest
        # face plus a small clearance so the box cannot obscure its label.
        try:
            box_center = [float(box_geometry[f"center_{axis}"]) for axis in "xyz"]
            half_size = [float(box_geometry[f"size_{axis}"]) / 2.0 for axis in "xyz"]
            delta = [position[index] - box_center[index] for index in range(3)]
            if all(abs(delta[index]) <= half_size[index] for index in range(3)):
                norm = math.sqrt(sum(value * value for value in delta))
                if norm < 0.01:
                    delta = [center[index] - box_center[index] for index in range(3)]
                    norm = math.sqrt(sum(value * value for value in delta))
                if norm < 0.01:
                    delta = [1.0, 0.0, 0.0]
                    norm = 1.0
                direction = [value / norm for value in delta]
                clearance = max(
                    (half_size[index] + 3.0) / max(abs(direction[index]), 1e-6)
                    for index in range(3)
                )
                position = [box_center[index] + clearance * direction[index] for index in range(3)]
        except (KeyError, TypeError, ValueError):
            pass
    label_object = f"pocket_label_{int(pocket_number)}"
    return [
        f"pseudoatom {label_object}, pos=[{position[0]:.3f},{position[1]:.3f},{position[2]:.3f}]",
        f'label {label_object}, "Pocket {int(pocket_number)}"',
        f"color {color}, {label_object}", f"set label_color, {color}, {label_object}",
        f"set label_size, 16, {label_object}",
        f"set label_font_id, 7, {label_object}",
        f"set label_outline_color, white, {label_object}",
    ]


def plot_cavity_selection(
    diagnostics, selected_config, output, selected_configs=None,
    evidence_site_numbers=(), unmatched_ligand_region_labels=(),
):
    """Plot retained fpocket candidates and distinguish the approved region."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with Path(diagnostics).open(newline="") as handle:
        selected_rows = list(csv.DictReader(handle, delimiter="\t"))
    rows = [row for row in selected_rows if row.get("rank_score") not in {None, "", "NA"}]
    if not rows:
        return False
    if selected_configs is None:
        selected_configs = [selected_config]
    selected_pairs = _selected_pocket_files(selected_rows, selected_configs)
    displayed_colors = _displayed_pocket_colors(selected_rows, evidence_site_numbers)
    # Panel A records every eligible cavity candidate using raw fpocket score
    # order. Panel B is intentionally
    # limited to the retained review candidates.
    rows.sort(key=lambda row: int(row.get("rank_order", 999999)))
    rows = rows[:10]
    retained_rows = [row for row in selected_rows if row.get("decision") == "selected"]
    retained_rows.sort(key=lambda row: int(row.get("rank_order", 999999)))
    shared_box_groups = displayed_fpocket_box_groups(
        Path(diagnostics), retained_rows, displayed_colors,
    )
    pocket_numbers = {
        row.get("pocket_file"): index + 1 for index, row in enumerate(retained_rows)
    }
    ranks = [int(row["rank_order"]) for row in rows]
    scores = [float(row["rank_score"]) for row in rows]
    colors = [displayed_colors.get(row.get("pocket_file"), "#b8c0c8") for row in rows]
    # A taller plot better matches the structural companion panel and keeps
    # labels legible when the A/B/legend composite is placed on a PDF page.
    fig, ax = plt.subplots(figsize=(8.0, 7.0))
    ax.scatter(ranks, scores, c=colors, s=105, edgecolor="black", linewidth=.6, zorder=3)
    for rank, score, row in zip(ranks, scores, rows):
        pocket_number = pocket_numbers.get(row.get("pocket_file"))
        if pocket_number in set(evidence_site_numbers):
            # A green outer ring is an evidence annotation, not a change to
            # the fpocket score. It denotes full containment of at least one
            # aligned deposited ligand in this candidate's proposed box.
            ax.scatter(
                [rank], [score], s=205, facecolors="none",
                edgecolors="#008b45", linewidths=2.6, zorder=4,
            )
        if pocket_number and row.get("pocket_file") in displayed_colors:
            ax.annotate(
                f"P{pocket_number}", (rank, score), xytext=(0, 10),
                textcoords="offset points", ha="center", va="bottom",
                fontsize=11, fontweight="bold",
                color=displayed_colors[row.get("pocket_file")],
            )
        matching = [(config, pocket) for config, pocket in selected_pairs if pocket == row.get("pocket_file")]
        if matching:
            config, pocket = matching[0]
            color = displayed_colors.get(pocket, "#333333")
            ax.annotate(
                f"Box P{pocket_number}", (rank, score), xytext=(18, -32),
                textcoords="offset points", fontsize=11,
                bbox=dict(fc="white", ec=color, alpha=.96),
                arrowprops=dict(arrowstyle="->", color=color),
            )
    tick_positions = list(ranks)
    tick_labels = [str(rank) for rank in ranks]
    unmatched_x = None
    for offset, region_label in enumerate(unmatched_ligand_region_labels, start=1):
        unmatched_x = max(ranks) + offset
        label_match = __import__("re").match(r"L(\d+)$", str(region_label))
        site_number = int(label_match.group(1)) if label_match else offset
        # Keep the L marker's color identical to the outlined ligand-defined
        # box in Panel B; the X shape still distinguishes it from fpocket dots.
        ligand_color = SITE_HEX_COLORS[(site_number - 1) % len(SITE_HEX_COLORS)]
        ax.scatter(
            [unmatched_x], [0.0], marker="X", s=150,
            c=ligand_color, edgecolor="black", linewidth=.9, zorder=5,
        )
        ax.annotate(
            str(region_label), (unmatched_x, 0.0), xytext=(0, 9),
            textcoords="offset points", ha="center", va="bottom",
            fontsize=9, fontweight="bold", color=ligand_color,
        )
        tick_positions.append(unmatched_x)
        tick_labels.append(str(region_label))
    ax.set_xticks(tick_positions, tick_labels)
    ax.set_xlim(min(ranks) - 0.4, (unmatched_x or max(ranks)) + 0.4)
    # Retained pockets in Panel B must all remain visible in Panel A.  In
    # particular, the highest fpocket score can otherwise sit on or just above
    # Matplotlib's automatic upper boundary and appear to be absent.
    if scores:
        span = max(scores) - min(scores)
        margin = max(0.01, span * 0.12)
        ax.set_ylim(min(scores) - margin, max(scores) + margin)
    ax.set_xlabel(
        "candidate identifier (P# = fpocket rank; L# = ligand-defined box without fpocket score)",
        fontsize=13,
    )
    ax.set_ylabel("fpocket score", fontsize=14)
    ax.set_title(
        "Fpocket ranking and structural evidence"
        if selected_pairs else "Fpocket ranking with structural-evidence overlay",
        fontsize=16,
    )
    ax.grid(alpha=.25)
    ax.tick_params(labelsize=11)
    ligand_evidence_labels = ", ".join(
        f"P{int(number)}" for number in evidence_site_numbers
        if 0 < int(number) <= len(retained_rows)
    )
    shared_box_labels = [
        "/".join(f"P{number}" for number in group["numbers"])
        for group in shared_box_groups if len(group["numbers"]) > 1
    ]
    legend_text = (
        "P# = raw fpocket rank; colors match Panel B\n"
        "Gray = other retained fpocket candidates\n"
        + (f"Green ring = ligand correspondence ({ligand_evidence_labels})\n" if ligand_evidence_labels else "")
        + (f"Shared proposed box = {', '.join(shared_box_labels)}\n" if shared_box_labels else "")
        + ("L# X at 0 = ligand-defined box; no fpocket score" if unmatched_ligand_region_labels else "")
    )
    ax.text(
        .98, .97, legend_text,
        transform=ax.transAxes, ha="right", va="top", fontsize=10,
        bbox=dict(fc="white", ec="0.6", alpha=.95),
    )
    fig.tight_layout()
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=240)
    plt.close(fig)
    return True


def render_cavity_scene(scene, output, session, pymol, overview=False):
    """Render a retained cavity-review scene for the scientific report."""
    if not pymol or not scene or not Path(scene).is_file():
        return False
    wrapper = output.with_suffix(".pml")
    output_arg = str(output.resolve()).replace(" ", "\\ ")
    session_arg = str(session.resolve()).replace(" ", "\\ ")
    view_commands = []
    if overview:
        view_commands = [
            "color gray70, polymer.protein",
            "set cartoon_transparency, 0.15, polymer.protein",
            "hide spheres, cavity_core*",
            "show surface, cavity_core*",
            "set transparency, 0.35, cavity_core*",
            "color red, cavity_core*",
            "hide spheres, *_box*",
            "show sticks, *_box*",
            "set stick_radius, 0.08, *_box*",
            "color orange, *_box*",
            "hide labels, all",
            "orient polymer.protein",
            "zoom polymer.protein, 12",
        ]
    else:
        view_commands = ["zoom all, 4"]
    wrapper.write_text(Path(scene).read_text(errors="replace") + "\n" + "\n".join([
        "bg_color white",
        "set ray_opaque_background, off", "set depth_cue, 0", *view_commands,
        "hide sticks, (nearby_residues and hydro and neighbor elem C)",
        f"png {output_arg}, 3600, 2400, dpi=440, ray=1",
        f"save {session_arg}", "quit",
    ]) + "\n")
    result = subprocess.run([str(pymol), "-cq", str(wrapper)], cwd=str(Path(scene).parent), text=True, capture_output=True)
    if result.returncode != 0:
        print(f"Report figure warning: cavity PyMOL render failed: {result.stderr.strip()}", file=sys.stderr)
    if result.returncode == 0 and output.is_file() and overview:
        trim_white_png(output, padding=70)
    return result.returncode == 0 and output.is_file()


def render_all_cavity_candidates(
    diagnostics, selected_config, output, session, pymol, selected_configs=None,
    evidence_site_numbers=(), selected_only=False, ligand_site_group=None,
    ligand_site_groups=(), show_labels=True,
):
    """Show retained pockets and boxes with stable colors across report panels."""
    if not pymol:
        return False
    receptor = first(diagnostics.parent.parent, ["receptor/*.pdb"])
    if not receptor:
        return False
    with Path(diagnostics).open(newline="") as handle:
        retained = [row for row in csv.DictReader(handle, delimiter="\t") if row.get("decision") == "selected"]
    retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
    if not retained:
        return False
    pocket_numbers = {row.get("pocket_file"): index + 1 for index, row in enumerate(retained)}
    receptor_center = pdb_centroid(receptor)
    selected_pairs = _selected_pocket_files(
        retained, [selected_config] if selected_configs is None else selected_configs
    )
    selected_by_file = {pocket: config for config, pocket in selected_pairs}
    displayed_colors = _displayed_pocket_colors(retained, evidence_site_numbers)
    if selected_only:
        retained = [row for row in retained if row.get("pocket_file") in selected_by_file]
    else:
        # Show the top ten surfaces for spatial context, while only the first
        # three receive distinguishing colors and proposed-box wireframes.
        retained = retained[:10]
    pymol_colors = {
        "#d62728": "red", "#1f77b4": "marine", "#d9a400": "gold",
        "#d627c1": "magenta", "#00a6b2": "cyan", "#f28e2b": "orange", "#9467bd": "violet",
        "#2ca02c": "green", "#8c564b": "brown", "#e377c2": "pink",
    }
    lines = [
        "reinitialize", f'load "{receptor.resolve()}", receptor', "hide everything, all",
        "show cartoon, receptor", "color gray70, receptor", "set cartoon_transparency, 0.12, receptor",
    ]
    for row in retained:
        pocket_key = row.get("pocket_file", "")
        pocket = diagnostics.parent / "frozen_pockets" / pocket_key
        if not pocket.is_file():
            continue
        pocket_number = pocket_numbers[pocket_key]
        obj = f"retained_pocket_{pocket_number}"
        color = pymol_colors.get(displayed_colors.get(pocket_key), "gray60")
        lines += [
            f'load "{pocket.resolve()}", {obj}', f"hide everything, {obj}", f"show surface, {obj}",
            f"set transparency, {0.62 if selected_only else 0.35}, {obj}", f"color {color}, {obj}",
        ]
        label_box_geometry = None
        if ligand_site_group and not selected_only:
            label_box_geometry = ligand_site_group.get("box")
        if show_labels:
            lines += pocket_label_commands(pocket, pocket_number, color, receptor_center, label_box_geometry)
        if selected_only and pocket_key in selected_by_file:
            config = selected_by_file[pocket_key]
            box = diagnostics.parent / f"{Path(config).stem}_box.pdb"
            if box.is_file():
                box_obj = f"selected_box_{pocket_number}"
                lines += [
                    f'load "{box.resolve()}", {box_obj}', f"hide everything, {box_obj}", f"show sticks, {box_obj}",
                    f"set stick_radius, 0.04, {box_obj}", f"color {color}, {box_obj}",
                ]
    if not selected_only:
        # Draw each bounded fpocket search region once. Candidates that occupy
        # the same region keep separate score points/surfaces but share a
        # single box keyed to the higher-ranked member's color.
        for group in displayed_fpocket_box_groups(
                Path(diagnostics), retained, displayed_colors):
            label = "_".join(f"P{number}" for number in group["numbers"])
            box_path = output.with_name(f"{output.stem}_{label}_box.pdb")
            write_box_coordinate_file(box_path, group["geometry"])
            box_object = f"candidate_box_{label}"
            color = pymol_colors[group["color"]]
            lines += [
                f'load "{box_path.resolve()}", {box_object}',
                f"hide everything, {box_object}", f"show sticks, {box_object}",
                f"set stick_radius, 0.08, {box_object}",
                f"set stick_transparency, 0.10, {box_object}",
                f"color {color}, {box_object}",
            ]
    # Ligand-defined regions without fpocket correspondence remain selectable
    # docking hypotheses. Show their complete boxes and identifiers directly
    # in the structural panel so the L# markers on Panel A have spatial meaning.
    if ligand_site_groups and not selected_only:
        required_geometry = {
            f"{field}_{axis}" for field in ("center", "size") for axis in "xyz"
        }
        for fallback_number, group in enumerate(ligand_site_groups, start=1):
            geometry = group.get("box") or {}
            if not required_geometry.issubset(geometry):
                continue
            site_number = int(group.get("site_number", fallback_number) or fallback_number)
            site_label = (group.get("site_identity") or {}).get(
                "canonical_label", f"L{site_number}",
            )
            label_match = __import__("re").match(r"L(\d+)$", str(site_label))
            display_site_number = int(label_match.group(1)) if label_match else site_number
            site_color = _site_color(display_site_number)
            box_path = output.with_name(f"{output.stem}_{site_label}_box.pdb")
            write_box_coordinate_file(box_path, geometry)
            box_object = f"ligand_defined_box_{site_label}"
            lines += [
                f'load "{box_path.resolve()}", {box_object}',
                f"hide everything, {box_object}", f"show sticks, {box_object}",
                f"set stick_radius, 0.13, {box_object}", f"set stick_transparency, 0.18, {box_object}",
                f"color {site_color}, {box_object}",
            ]
    # With one ligand-defined site, integrate its single representative and
    # complete proposed box into the main fpocket structural panel.  A separate
    # site figure would repeat the same spatial information.  Multi-site cases
    # retain their dedicated overview because the separation among sites is
    # itself scientifically informative.
    if ligand_site_group:
        matched_number = (ligand_site_group.get("fpocket_recovery") or {}).get("best_matching_pocket")
        direct_members = [
            member for member in ligand_site_group.get("members", [])
            if str(member.get("matched_cavity")) == str(matched_number)
        ] if matched_number else []
        representative = (
            max(direct_members, key=lambda item: int(item.get("ligand_heavy_atom_count", 0) or 0))
            if direct_members else ligand_site_group.get("representative_ligand") or {}
        )
        evidence_root = diagnostics.parent / "pdb_site_evidence"
        ligand = evidence_root / str(representative.get("aligned_ligand_pdb", ""))
        geometry = ligand_site_group.get("box") or {}
        required_geometry = {
            f"{field}_{axis}" for field in ("center", "size") for axis in "xyz"
        }
        if ligand.is_file() and (selected_only or required_geometry.issubset(geometry)):
            # Use the same color as the fpocket site that supports this
            # ligand-defined region.  The box is therefore identifiable in
            # every panel without adding a separate PyMOL annotation.
            matched_row = next(
                (item for item in retained
                 if pocket_numbers.get(item.get("pocket_file")) == int(matched_number or 0)),
                None,
            )
            site_color = pymol_colors.get(
                displayed_colors.get((matched_row or {}).get("pocket_file")),
                "forest",
            )
            lines += [
                f'load "{ligand.resolve()}", ligand_site_representative',
                "hide everything, ligand_site_representative",
                "show sticks, ligand_site_representative",
                "show spheres, ligand_site_representative",
                "color green, ligand_site_representative",
                "set stick_radius, 0.38, ligand_site_representative",
                "set sphere_scale, 0.18, ligand_site_representative",
                "set stick_transparency, 0.0, ligand_site_representative",
            ]
            if not selected_only:
                ligand_box = output.with_name(output.stem + "_ligand_site_box.pdb")
                write_box_coordinate_file(ligand_box, geometry)
                lines += [
                    f'load "{ligand_box.resolve()}", ligand_site_box',
                    "hide everything, ligand_site_box", "show sticks, ligand_site_box",
                    # Keep the proposed box distinct from the representative
                    # ligand in the main candidate overview.
                    f"color {site_color}, ligand_site_box", "set stick_radius, 0.18, ligand_site_box",
                ]
    lines += [
        "bg_color white", "set ray_opaque_background, off", "set depth_cue, 0",
        "hide sticks, (nearby_residues and hydro and neighbor elem C)",
        "orient all" if selected_only else "orient receptor",
        # Include a generous camera margin around every box; a box edge must
        # never be clipped in a report figure.
        # The extra margin and disabled near-plane clipping keep every corner
        # of a selected box in frame across different receptor orientations.
        "set ray_clip_near, 0",
        "zoom all, 20" if selected_only or ligand_site_group else "zoom receptor, 8",
        f"png {output.resolve()}, 3600, 2400, dpi=440, ray=1",
        f"save {session.resolve()}", "quit",
    ]
    wrapper = output.with_suffix(".pml")
    wrapper.write_text("\n".join(lines) + "\n")
    result = subprocess.run([str(pymol), "-cq", str(wrapper)], text=True, capture_output=True)
    if result.returncode == 0 and output.is_file():
        trim_white_png(output, padding=70)
        return True
    if result.returncode != 0:
        print(f"Report figure warning: all-pocket PyMOL render failed: {result.stderr.strip()}", file=sys.stderr)
    return False


def render_ligand_identity(image_path, ligand_sdf, ligand_id):
    """Render an unobstructed CCD-derived 2D identity panel."""
    try:
        from PIL import Image
        from rdkit import Chem
        from rdkit.Chem import Draw
        from rdkit.Chem import rdDepictor
        molecule = Chem.MolFromMolFile(str(ligand_sdf), removeHs=True)
        if molecule is None:
            return False
        # CCD ideal SDFs can retain nonplanar coordinates. Generate a fresh
        # planar depiction so stereochemistry is legible without distorting
        # the molecular graph used as the identity authority.
        rdDepictor.Compute2DCoords(molecule, clearConfs=True)
        canvas = Image.new("RGB", (1000, 900), "white")
        molecule_image = Draw.MolToImage(molecule, size=(920, 820)).convert("RGB")
        canvas.paste(molecule_image, (40, 40))
        canvas.save(image_path, dpi=(240, 240))
        trim_white_png(image_path, padding=70)
        return True
    except (ImportError, OSError, ValueError):
        return False


def supporting_ligand_rows(record, pocket_number):
    """Return only ligands that match the cavity and fit completely in its box."""
    supporting = []
    for row in record.get("evidence", []):
        if any(
            int(item.get("pocket_number", -1)) == pocket_number
            and bool(item.get("cavity_match", False))
            and bool(item.get("all_heavy_atoms_inside", False))
            for item in row.get("pocket_relationships", [])
        ):
            supporting.append(row)
    return supporting


def build_pocket_evidence_figure(diagnostics, selected_config, output, pymol, pocket_color="red"):
    """Pair a close 3D pocket/ligand view with a separate 2D identity panel."""
    if not pymol:
        return False
    match = __import__("re").search(r"pocket(\d+)", selected_config or "", __import__("re").I)
    pocket_number = int(match.group(1)) if match else 1
    record = read_json(diagnostics.parent / "pdb_site_evidence" / "pdb_ligand_site_evidence.json")
    supporting = supporting_ligand_rows(record, pocket_number)
    representative = max(
        supporting,
        key=lambda row: (int(row.get("ligand_heavy_atom_count", 0)), row.get("ligand", "")),
        default=None,
    )
    if not representative:
        return False
    evidence_root = diagnostics.parent / "pdb_site_evidence"
    ligand = evidence_root / representative.get("aligned_ligand_pdb", "")
    sdf = evidence_root / representative.get("ccd_ideal_sdf", "")
    receptor = first(diagnostics.parent.parent, ["receptor/*.pdb"])
    with Path(diagnostics).open(newline="") as handle:
        retained = [row for row in csv.DictReader(handle, delimiter="\t") if row.get("decision") == "selected"]
    retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
    pocket_row = retained[pocket_number - 1] if pocket_number <= len(retained) else retained[0]
    pocket = diagnostics.parent / "frozen_pockets" / pocket_row.get("pocket_file", "")
    box = diagnostics.parent / f"{Path(selected_config).stem}_box.pdb"
    if not receptor or not ligand.is_file() or not pocket.is_file():
        return False
    panel_3d = output.with_name(output.stem + "_3D.png")
    panel_2d = output.with_name(output.stem + "_2D.png")
    pml = output.with_suffix(".pml")
    lines = [
        "reinitialize", f'load "{receptor.resolve()}", receptor',
        f'load "{pocket.resolve()}", selected_pocket',
        f'load "{ligand.resolve()}", supporting_ligand',
        "hide everything, all", "show cartoon, receptor", "color gray80, receptor",
        "set cartoon_transparency, 0.72, receptor",
        "show surface, selected_pocket",
        f"color {pocket_color}, selected_pocket", "set transparency, 0.72, selected_pocket",
        "show sticks, supporting_ligand", "color tv_orange, supporting_ligand",
        "set stick_radius, 0.24, supporting_ligand",
    ]
    if box.is_file():
        lines += [f'load "{box.resolve()}", docking_box', "hide everything, docking_box", "show sticks, docking_box",
                  f"color {pocket_color}, docking_box", "set stick_radius, 0.035, docking_box"]
    lines += [
        "bg_color white", "set ray_opaque_background, off", "set depth_cue, 0",
        "orient (selected_pocket or supporting_ligand or docking_box)" if box.is_file() else "orient (selected_pocket or supporting_ligand)",
        "zoom (selected_pocket or supporting_ligand or docking_box), 14" if box.is_file() else "zoom (selected_pocket or supporting_ligand), 5",
        f"png {panel_3d.resolve()}, 2800, 2200, dpi=480, ray=1", "quit",
    ]
    pml.write_text("\n".join(lines) + "\n")
    result = subprocess.run([str(pymol), "-cq", str(pml)], text=True, capture_output=True)
    if result.returncode != 0 or not panel_3d.is_file() or not sdf.is_file():
        return False
    trim_white_png(panel_3d, padding=80)
    if not render_ligand_identity(panel_2d, sdf, representative.get("ligand", "ligand")):
        return False
    combine_panels(panel_3d, panel_2d, output, control=False)
    return output.is_file()


def write_box_coordinate_file(path, geometry):
    """Write a connected-corner PDB used only to render a proposed box."""
    center = [float(geometry[f"center_{axis}"]) for axis in "xyz"]
    half = [float(geometry[f"size_{axis}"]) / 2.0 for axis in "xyz"]
    corners = [
        (center[0] + sx * half[0], center[1] + sy * half[1], center[2] + sz * half[2])
        for sx, sy, sz in ((-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),
                           (-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1))
    ]
    edges = ((1,2),(2,3),(3,4),(4,1),(5,6),(6,7),(7,8),(8,5),(1,5),(2,6),(3,7),(4,8))
    lines = [f"HETATM{index:5d}  C   BOX A{index:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C"
             for index, (x, y, z) in enumerate(corners, 1)]
    lines += [f"CONECT{left:5d}{right:5d}" for left, right in edges]
    Path(path).write_text("\n".join(lines + ["END"]) + "\n")


def ligand_site_group_deserves_figure(group):
    """Promote only structurally interpretable site evidence to a full figure.

    A remote singleton with no fpocket correspondence remains scientifically
    relevant as an audit-table observation, but a receptor-free box around one
    ligand is not informative enough to consume a standalone report figure.
    """
    return (
        int(group.get("member_count", len(group.get("members", []))) or 0) > 1
        or bool(group.get("matched_cavity_counts"))
    )


def build_ligand_site_overview(diagnostics, groups, output, pymol):
    """Build one labeled multipanel figure covering every ligand-bearing site."""
    if not pymol or len(groups) < 2:
        return False
    receptor = first(diagnostics.parent.parent, ["receptor/*.pdb"])
    evidence_root = diagnostics.parent / "pdb_site_evidence"
    if not receptor:
        return False
    receptor_center = pdb_centroid(receptor)
    with Path(diagnostics).open(newline="") as handle:
        retained_pockets = [
            row for row in csv.DictReader(handle, delimiter="\t")
            if row.get("decision") == "selected"
        ]
    retained_pockets.sort(key=lambda row: int(row.get("rank_order", 999999)))
    rendered_panels = []
    for position, group in enumerate(groups):
        members = group.get("members") or []
        if not members or not group.get("box"):
            continue
        matching_pocket = (group.get("fpocket_recovery") or {}).get("best_matching_pocket")
        directly_matched = [
            member for member in members
            if str(member.get("matched_cavity")) == str(matching_pocket)
        ] if matching_pocket else []
        # Prefer direct protein evidence for the representative when present;
        # homolog evidence remains visible when it is the only evidence.
        priority = {"same_protein": 0, "exact_sequence_match": 1,
                    "close_structural_homolog": 2, "identity_uncertain": 3}
        member = (
            max(directly_matched, key=lambda item: int(item.get("ligand_heavy_atom_count", 0) or 0))
            if directly_matched else group.get("representative_ligand")
            or min(members, key=lambda item: (
                priority.get(item.get("evidence_class", "identity_uncertain"), 3),
                item.get("entry", ""), item.get("ligand", ""),
            ))
        )
        recorded_path = evidence_root / str(member.get("aligned_ligand_pdb", ""))
        expected_prefix = "{}_{}_{}_".format(
            member.get("entry", ""), member.get("ligand", ""), member.get("ligand_chain", ""),
        )
        matches = [recorded_path] if ligand_artifact_matches_member(recorded_path, member) else []
        if not matches:
            print(
                f"Report figure warning: rejected mismatched ligand artifact for site {group.get('site_number')}: "
                f"expected {expected_prefix}*, recorded {recorded_path.name or 'none'}",
                file=sys.stderr,
            )
            continue
        site_number = int(group.get("site_number", position + 1))
        color = (
            FPOCKET_PYMOL_COLORS[(int(matching_pocket) - 1) % len(FPOCKET_PYMOL_COLORS)]
            if matching_pocket else _site_color(site_number)
        )
        ligand_color = "forest" if matching_pocket else color
        panel = output.with_name(f"{output.stem}_site_{site_number}.png")
        pml = panel.with_suffix(".pml")
        box = output.with_name(f"{output.stem}_site_{site_number}_box.pdb")
        panel_geometry = group["box"]
        if matching_pocket:
            configs = sorted(diagnostics.parent.glob(f"*_pocket{matching_pocket}.conf"))
            matched_geometry = config_geometry(configs[0]) if configs else {}
            if matched_geometry:
                panel_geometry = matched_geometry
        write_box_coordinate_file(box, panel_geometry)
        # Rendering must never repair a coordinate-frame mismatch silently.
        # If the retained ligand is outside its own recorded site box, omit
        # the misleading panel; the evidence collector must be rerun.
        if not ligand_artifact_inside_box(matches[0], panel_geometry):
            print(
                f"Report figure warning: site {site_number} ligand lies outside its recorded box; "
                "panel omitted pending evidence regeneration",
                file=sys.stderr,
            )
            continue
        lines = [
            "reinitialize", f'load "{receptor.resolve()}", receptor', "hide everything, all",
            "show cartoon, receptor", "color gray70, receptor", "set cartoon_transparency, 0.25, receptor",
            "set transparency_mode, 1", "set ray_transparency_contrast, 0.25",
            "set ray_transparency_oblique, 0.0",
        ]
        # Repeat the complete fpocket context in every panel so A/B/C can be
        # interpreted independently while still sharing the same receptor
        # orientation and surface-color convention.
        for pocket_index, row in enumerate(retained_pockets):
            pocket = diagnostics.parent / "frozen_pockets" / row.get("pocket_file", "")
            if not pocket.is_file():
                continue
            pocket_object = f"fpocket_{pocket_index + 1}"
            pocket_color = FPOCKET_PYMOL_COLORS[pocket_index % len(FPOCKET_PYMOL_COLORS)]
            lines += [
                f'load "{pocket.resolve()}", {pocket_object}', f"hide everything, {pocket_object}",
                f"show surface, {pocket_object}", f"color {pocket_color}, {pocket_object}",
                f"set transparency, 0.88, {pocket_object}",
            ]
            # Color links cavities across figures; 3D text obscures surfaces.
        lines += [
            f'load "{matches[0].resolve()}", site_ligand', "hide everything, site_ligand",
            "show sticks, site_ligand", f"color {ligand_color}, site_ligand",
            "set stick_radius, 0.32, site_ligand",
            f'load "{box.resolve()}", site_box', "hide everything, site_box",
            "show sticks, site_box", "set stick_radius, 0.10, site_box", "set stick_transparency, 0.18, site_box",
            f"color {color}, site_box",
            "bg_color white", "set ray_opaque_background, off", "set depth_cue, 0",
            # Orient every panel by the same receptor, then frame the receptor,
            # selected ligand, complete box, and all cavity surfaces together.
            "orient receptor", "set ray_clip_near, 0", "zoom all, 16", "clip slab, 200",
            f"png {panel.resolve()}, 3000, 2100, dpi=480, ray=1", "quit",
        ]
        pml.write_text("\n".join(lines) + "\n")
        result = subprocess.run([str(pymol), "-cq", str(pml)], text=True, capture_output=True)
        if result.returncode == 0 and panel.is_file():
            trim_white_png(panel, padding=30)
            rendered_panels.append((panel, color, site_number))
    if len(rendered_panels) < 2:
        return False
    # Bound the number of views per PDF page; nine panels in one tall bitmap
    # made every molecule unreadably small when fitted onto a report page.
    # Six equal panels (two across by three rows) fit a report page without
    # shrinking one site relative to another or wasting a half-empty page.
    panels_per_page = 6
    for start in range(0, len(rendered_panels), panels_per_page):
        page = output.with_name(f"{output.stem}_page_{start // panels_per_page + 1}.png")
        combine_ligand_site_panels(
            rendered_panels[start:start + panels_per_page], page, start,
        )
    return combine_ligand_site_panels(rendered_panels, output)


def combine_ligand_site_panels(panels, output, label_offset=0):
    """Arrange site views as A/B/C/... panels without distorting them."""
    from PIL import Image, ImageDraw, ImageFont, ImageOps
    panel_w, panel_h = 3200, 2240
    gap, outer = 80, 32
    # Keep a universal two-across panel scale, including an odd final panel.
    columns = 2
    rows = (len(panels) + columns - 1) // columns
    canvas_w = columns * panel_w + gap + 2 * outer
    canvas_h = rows * panel_h + max(0, rows - 1) * gap + 2 * outer
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    font_path = Path("/System/Library/Fonts/Helvetica.ttc")
    label_font = ImageFont.truetype(str(font_path), 164) if font_path.is_file() else ImageFont.load_default()
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    color_values = {"red": "#D62728", "marine": "#1F77B4", "gold": "#D9A400",
                    "forest": "#228B22", "cyan": "#00A6B2", "tv_orange": "#F28E2B",
                    "violet": "#9467BD", "salmon": "#FA8072", "teal": "#008080", "wheat": "#D8B26E"}
    for index, (source, color, _site_number) in enumerate(panels):
        row, column = divmod(index, columns)
        # Center the final panel when an odd number of sites is present.
        if len(panels) % 2 and index == len(panels) - 1:
            x = (canvas_w - panel_w) // 2
        else:
            x = outer + column * (panel_w + gap)
        y = outer + row * (panel_h + gap)
        panel = Image.open(source).convert("RGB")
        inner_w, inner_h = panel_w - 40, panel_h - 40
        # `thumbnail` never enlarges a tightly cropped source and therefore
        # left most of each fixed panel blank.  Fit both smaller and larger
        # renders to the same bounded area while preserving aspect ratio.
        target_w, target_h = inner_w - 72, inner_h - 72
        scale = min(target_w / panel.width, target_h / panel.height)
        panel = panel.resize(
            (max(1, round(panel.width * scale)), max(1, round(panel.height * scale))),
            Image.Resampling.LANCZOS,
        )
        frame = Image.new("RGB", (inner_w, inner_h), "white")
        frame.paste(panel, ((inner_w - panel.width) // 2, (inner_h - panel.height) // 2))
        border = color_values.get(color, "#333333")
        frame = ImageOps.expand(frame, border=20, fill=border)
        canvas.paste(frame, (x, y))
        draw.text((x + 64, y + 48), letters[index + label_offset], fill=border, font=label_font)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, dpi=(480, 480))
    return True


def build_ligand_site_group_figure(diagnostics, group, output, pymol):
    """Render one representative ligand for a spatial group and its box."""
    if not pymol or not group.get("members") or not group.get("box"):
        return False
    receptor = first(diagnostics.parent.parent, ["receptor/*.pdb"])
    evidence_root = diagnostics.parent / "pdb_site_evidence"
    if not receptor:
        return False
    receptor_center = pdb_centroid(receptor)
    ligand_candidates = []
    for member in group["members"]:
        recorded_path = evidence_root / str(member.get("aligned_ligand_pdb", ""))
        if not ligand_artifact_matches_member(recorded_path, member):
            continue
        if not ligand_artifact_inside_box(recorded_path, group["box"]):
            continue
        heavy_atoms = int(member.get("ligand_heavy_atom_count", 0) or 0)
        if not heavy_atoms:
            heavy_atoms = sum(
                line.startswith(("ATOM  ", "HETATM"))
                for line in recorded_path.read_text(errors="replace").splitlines()
            )
        ligand_candidates.append((recorded_path, member, heavy_atoms))
    if not ligand_candidates:
        return False
    ligand, representative, _ = max(
        ligand_candidates,
        key=lambda item: (
            item[2], item[1].get("ligand", ""), item[1].get("entry", ""),
            item[1].get("ligand_chain", ""), item[1].get("ligand_residue", ""),
        ),
    )
    box = output.with_name(output.stem + "_box.pdb")
    write_box_coordinate_file(box, group["box"])
    pml = output.with_suffix(".pml")
    lines = ["reinitialize", f'load "{receptor.resolve()}", receptor',
             "hide everything, all", "show cartoon, receptor", "color gray80, receptor",
             "set cartoon_transparency, 0.72, receptor",
             # Make ray-traced cavity surfaces visibly translucent rather than
             # merely assigning an object transparency value that can still
             # read as opaque under the default ray settings.
             "set transparency_mode, 1", "set ray_transparency_contrast, 0.25",
             "set ray_transparency_oblique, 0.0"]
    site_number = int(group.get("site_number", 1) or 1)
    site_color = _site_color(site_number)
    lines += [f'load "{ligand.resolve()}", representative_ligand',
              "show sticks, representative_ligand",
              f"color {site_color}, representative_ligand",
              "set stick_radius, 0.24, representative_ligand"]
    # fpocket remains an independent geometric hypothesis. Show every cavity
    # that corresponds to at least one ligand in this spatial group as a
    # translucent surface so the deposited ligands remain visible through it.
    with Path(diagnostics).open(newline="") as handle:
        retained = [row for row in csv.DictReader(handle, delimiter="\t") if row.get("decision") == "selected"]
    retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
    for pocket_number in sorted(int(number) for number in (group.get("matched_cavity_counts") or {})):
        if pocket_number < 1 or pocket_number > len(retained):
            continue
        pocket = diagnostics.parent / "frozen_pockets" / retained[pocket_number - 1].get("pocket_file", "")
        if not pocket.is_file():
            continue
        pocket_object = f"fpocket_{pocket_number}"
        pocket_color = FPOCKET_PYMOL_COLORS[(pocket_number - 1) % len(FPOCKET_PYMOL_COLORS)]
        lines += [
            f'load "{pocket.resolve()}", {pocket_object}', f"hide everything, {pocket_object}",
            f"show surface, {pocket_object}", f"color {pocket_color}, {pocket_object}",
            f"set transparency, 0.86, {pocket_object}",
        ]
        lines += pocket_label_commands(
            pocket, pocket_number, pocket_color, receptor_center, group.get("box"),
        )
    lines += [f'load "{box.resolve()}", proposed_box', "hide everything, proposed_box",
              "show sticks, proposed_box", "set stick_radius, 0.10, proposed_box", "set stick_transparency, 0.18, proposed_box",
              f"color {site_color}, proposed_box",
              "bg_color white", "set ray_opaque_background, off", "set depth_cue, 0",
              # Preserve the receptor-frame orientation used by the site
              # overview and cavity figures so colors and spatial positions
              # can be compared directly across report pages.
              "orient receptor", "zoom all, 14",
              f"png {output.resolve()}, 3200, 2200, dpi=480, ray=1", "quit"]
    pml.write_text("\n".join(lines) + "\n")
    result = subprocess.run([str(pymol), "-cq", str(pml)], text=True, capture_output=True)
    if result.returncode != 0 or not output.is_file():
        return False
    trim_white_png(output, padding=90)
    return True


def build_cavity_figures(study, pymol):
    """Build cavity figures solely from retained preparation evidence."""
    diagnostics, selected_config, scene = cavity_artifacts(study)
    if not diagnostics:
        return []
    report = study / "report"
    report.mkdir(parents=True, exist_ok=True)
    outputs = []
    summary = read_json(report / "study_summary.json")
    selected_regions = summary.get("selected_docking_regions") or []
    selected_configs = [
        region.get("box_name") or Path(str(region.get("box", ""))).name
        for region in selected_regions
        if region.get("box_name") or region.get("box")
    ]
    if not selected_configs and summary.get("report_purpose") != "pocket-review":
        selected_configs = [selected_config]
    pocket_evidence = summary.get("pdb_pocket_evidence") or {}
    evidence_summary = pocket_evidence.get("summary") or {}
    ligand_site_groups = pocket_evidence.get("ligand_site_groups") or []
    evidence_site_numbers = sorted(
        int(number) for number, item in evidence_summary.items()
        if str(number).isdigit() and int(item.get("contained_ligands", 0)) > 0
    )
    selected_site_numbers = []
    for config_name in selected_configs:
        match = __import__("re").search(r"pocket(\d+)", str(config_name), __import__("re").I)
        if match:
            selected_site_numbers.append(int(match.group(1)))
    display_site_numbers = sorted(set(evidence_site_numbers + selected_site_numbers))
    with Path(diagnostics).open(newline="") as handle:
        diagnostic_rows = list(csv.DictReader(handle, delimiter="\t"))
    # Related-structure recovery stores the original fpocket number (for
    # example, pocket 6), whereas the plot labels retained candidates by
    # their post-filter display order (P1, P2, ...). Translate the recovered
    # pocket numbers so Figure 2 marks the actual ligand-supported candidates.
    retained_for_display = [
        row for row in diagnostic_rows if row.get("decision") == "selected"
    ]
    retained_for_display.sort(key=lambda row: int(row.get("rank_order", 999999)))
    recovered_pocket_numbers = []
    for group in ligand_site_groups:
        recovery = group.get("fpocket_recovery") or {}
        # Any explicit cavity correspondence makes this one combined site.
        # The supporting-pose fraction communicates strength; it must not be
        # drawn again as an independent L# region merely because fewer than
        # half of a spatial group's observations received a unique match.
        if not recovery.get("best_matching_pocket"):
            continue
        match = __import__("re").search(r"pocket(\d+)", str(recovery.get("best_matching_pocket") or ""), __import__("re").I)
        if not match:
            # The evidence record may store the numeric pocket directly.
            number = recovery.get("best_matching_pocket")
            if str(number).isdigit():
                match = __import__("re").match(r"(\d+)", str(number))
        if not match:
            continue
        source_name = f"pocket{int(match.group(1))}_atm.pdb"
        for display_index, row in enumerate(retained_for_display, start=1):
            if Path(str(row.get("pocket_file", ""))).name == source_name:
                recovered_pocket_numbers.append(display_index)
                break
    evidence_site_numbers = sorted(set(evidence_site_numbers + recovered_pocket_numbers))
    display_site_numbers = sorted(set(evidence_site_numbers + selected_site_numbers))
    displayed_colors = _displayed_pocket_colors(diagnostic_rows, display_site_numbers)
    retained_rows = [row for row in diagnostic_rows if row.get("decision") == "selected"]
    retained_rows.sort(key=lambda row: int(row.get("rank_order", 999999)))
    pymol_colors = {
        "#d62728": "red", "#1f77b4": "marine", "#d9a400": "gold",
        "#d627c1": "magenta", "#00a6b2": "cyan", "#f28e2b": "orange", "#9467bd": "violet",
    }
    panel_a = report / "cavity_panel_A_selection.png"
    unmatched_ligand_region_labels = [
        (group.get("site_identity") or {}).get(
            "canonical_label", f"L{group.get('site_number', index + 1)}",
        )
        for index, group in enumerate(ligand_site_groups)
        if (group.get("site_identity") or {}).get(
            "is_separate_from_fpocket",
            (group.get("fpocket_recovery") or {}).get("status") == "not_recovered",
        )
    ]
    if plot_cavity_selection(
        diagnostics, selected_config, panel_a, selected_configs,
        evidence_site_numbers, unmatched_ligand_region_labels,
    ):
        outputs.append(str(panel_a))
    panel_b = report / "cavity_panel_B_structure.png"
    selected_ligand_site_group = (
        (pocket_evidence.get("user_evidence_decision") or {}).get("selected_ligand_site_group")
    )
    single_ligand_site_group = (
        selected_ligand_site_group or ligand_site_groups[0]
        if len(ligand_site_groups) == 1 else None
    )
    unmatched_ligand_site_groups = [
        group for group in ligand_site_groups
        if (group.get("site_identity") or {}).get(
            "is_separate_from_fpocket",
            (group.get("fpocket_recovery") or {}).get("status") == "not_recovered",
        )
    ]
    if render_all_cavity_candidates(
        diagnostics, selected_config, panel_b,
        report / "cavity_panel_B_structure.pse", pymol, selected_configs,
        display_site_numbers, ligand_site_group=single_ligand_site_group,
        ligand_site_groups=unmatched_ligand_site_groups,
        show_labels=False,
    ):
        outputs.append(str(panel_b))
    # Keep selected regions and their boxes in a dedicated figure so the
    # multi-pocket comparison remains unobstructed.
    selected_box = report / "cavity_selected_box.png"
    fpocket_selected_configs = [
        config for config in selected_configs
        if __import__("re").search(r"pocket\d+", str(config), __import__("re").I)
    ]
    selected_evidence_group = None
    if selected_configs:
        selected_match = __import__("re").search(
            r"pocket(\d+)", str(selected_configs[0]), __import__("re").I,
        )
        if selected_match:
            selected_number = selected_match.group(1)
            selected_evidence_group = next((
                group for group in ligand_site_groups
                if str((group.get("fpocket_recovery") or {}).get("best_matching_pocket"))
                == selected_number
            ), None)
    if fpocket_selected_configs and render_all_cavity_candidates(
        diagnostics, selected_config, selected_box, report / "cavity_selected_box.pse",
        pymol, fpocket_selected_configs, display_site_numbers, selected_only=True,
        ligand_site_group=selected_evidence_group, show_labels=False,
    ):
        outputs.append(str(selected_box))
    elif selected_box.is_file():
        # A ligand-defined site is already visualized with its aligned ligands,
        # complete box, and corresponding fpocket surfaces. A receptor-only
        # placeholder is both redundant and scientifically uninformative.
        selected_box.unlink()
    combined = report / "cavity_panels_AB.png"
    if panel_a.is_file() and panel_b.is_file():
        panel_b_legend = []
        for display_index, row in enumerate(retained_for_display, start=1):
            pocket_file = row.get("pocket_file")
            if pocket_file in displayed_colors:
                panel_b_legend.append((
                    f"Cavity P{display_index}", displayed_colors[pocket_file], "surface",
                ))
        for group in displayed_fpocket_box_groups(
                diagnostics, retained_rows, displayed_colors):
            group_label = "/".join(f"P{number}" for number in group["numbers"])
            panel_b_legend.append((
                f"Box {group_label}", group["color"], "box",
            ))
        for fallback_number, group in enumerate(unmatched_ligand_site_groups, start=1):
            site_number = int(group.get("site_number", fallback_number) or fallback_number)
            site_label = (group.get("site_identity") or {}).get(
                "canonical_label", f"L{site_number}",
            )
            label_match = __import__("re").match(r"L(\d+)$", str(site_label))
            display_site_number = int(label_match.group(1)) if label_match else site_number
            panel_b_legend.append((
                f"Box {site_label}",
                SITE_HEX_COLORS[(display_site_number - 1) % len(SITE_HEX_COLORS)],
                "box",
            ))
        combine_panels(
            panel_a, panel_b, combined, control=False,
            panel_b_legend=panel_b_legend,
        )
        outputs.append(str(combined))
    evidence_configs = [
        f"{Path(selected_config).stem.rsplit('_pocket', 1)[0]}_pocket{number}.conf"
        for number in evidence_site_numbers
    ]
    figure_configs = list(dict.fromkeys(selected_configs + evidence_configs))
    for fallback_number, config_name in enumerate(figure_configs, start=1):
        match = __import__("re").search(r"pocket(\d+)", str(config_name), __import__("re").I)
        site_number = int(match.group(1)) if match else fallback_number
        evidence_figure = report / f"pocket_evidence_site_{site_number}_AB.png"
        pocket_file = retained_rows[site_number - 1].get("pocket_file") if 0 < site_number <= len(retained_rows) else ""
        pocket_color = pymol_colors.get(displayed_colors.get(pocket_file), "gray50")
        if build_pocket_evidence_figure(diagnostics, config_name, evidence_figure, pymol, pocket_color):
            outputs.append(str(evidence_figure))
    # One ligand-defined site is incorporated directly into Panel B above.
    # Multiple sites are compared in the overview below.  Standalone per-site
    # images duplicate those primary figures, so remove artifacts left by an
    # earlier rendering pass rather than allowing them into a regenerated report.
    for group in ligand_site_groups:
        group_number = int(group.get("site_number", 1))
        group_figure = report / f"ligand_site_group_{group_number}.png"
        for stale in (group_figure, group_figure.with_suffix(".pml"),
                      group_figure.with_name(group_figure.stem + "_box.pdb")):
            if stale.is_file():
                stale.unlink()
    site_overview = report / "ligand_site_overview.png"
    if build_ligand_site_overview(diagnostics, ligand_site_groups, site_overview, pymol):
        outputs.append(str(site_overview))
    elif site_overview.is_file():
        site_overview.unlink()
    return outputs


def ensure_control_clusters(control, protocol_path):
    """Recover reportable control clusters without rerunning docking."""
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


def materialize_cluster_representatives(analysis, rows, report, compound_id):
    """Return report-local SDFs for selected clusters, recovering pruned files.

    Compact workflows may retain interaction files for fewer than three
    clusters, even though ``all_poses.sdf`` still retains every clustered pose.
    The report's A/B figure must nevertheless show the same selected clusters
    as Panel A, so recover their representatives into the report directory.
    """
    from rdkit import Chem

    recovered = retained_cluster_representatives(analysis)
    paths = []
    for row in rows[:3]:
        try:
            cluster_id = int(row["cluster_id"])
        except (KeyError, TypeError, ValueError):
            continue
        source = analysis / f"cluster_{cluster_id:03d}" / "representative.sdf"
        if source.is_file():
            paths.append(source)
            continue
        molecule = recovered.get(cluster_id)
        if molecule is None:
            continue
        destination = report / f"{compound_id}_cluster_{cluster_id:03d}_representative.sdf"
        writer = Chem.SDWriter(str(destination))
        writer.write(molecule)
        writer.close()
        paths.append(destination)
    return paths


def plot_clusters(analysis, output, reference_sdf=None, control_label=None):
    """Plot retained pose clusters with score, population, and structural distance."""
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
        except (RuntimeError, ValueError):
            value = float("nan")
        rmsds.append(value)
    finite = [value for value in rmsds if math.isfinite(value)]
    replacement = sorted(finite)[len(finite) // 2] if finite else 0.0
    rmsds = [value if math.isfinite(value) else replacement for value in rmsds]
    sizes = [70 + int(row.get("pose_count", 1)) * 8 for row, _ in entries]
    colors = list(TOP_COLORS[:min(3, len(entries))]) + ["#b8c0c8"] * max(0, len(entries) - 3)

    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.scatter(energies, rmsds, s=sizes, c=colors, edgecolor="black", linewidth=0.7, alpha=0.9)
    ax.set_xlabel("Best cluster docking score (kcal/mol)", fontsize=15)
    if control_label:
        ax.set_ylabel(f"No-fit heavy-atom RMSD to experimental {control_label} (A)", fontsize=13)
        ax.set_title("Top 20 control pose clusters and experimental-pose recovery", fontsize=17)
        ax.text(
            .98, .98,
            "One point = one control cluster\nPoint size = cluster population\nRed/blue/gold = three most favorable scores",
            transform=ax.transAxes, ha="right", va="top", fontsize=11,
            bbox=dict(fc="white", ec="0.6", alpha=.95),
        )
    else:
        # Keep the axis label compact enough to remain fully visible when the
        # figure is reduced into the PDF; the caption and in-plot legend state
        # the RMSD reference explicitly.
        ax.set_ylabel("No-fit heavy-atom RMSD (A)", fontsize=15)
        ax.set_title("Top 20 clusters: docking score, population, and structural distance", fontsize=17)
        ax.add_patch(FancyBboxPatch((.54, .015), .44, .28, transform=ax.transAxes, boxstyle="round,pad=.012", fc="white", ec="0.6", alpha=.95, zorder=5))
        ax.text(.95, .265, "Top clusters", transform=ax.transAxes, fontsize=12, va="top", ha="right", zorder=6)
        for y, index, color in zip((.215, .175, .135), range(min(3, len(entries))), TOP_COLORS):
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
    # Leave enough left margin for the long vertical RMSD label.  The compact
    # figure is embedded at reduced size in the PDF, so a default tight layout
    # can clip the first characters even when the source PNG looks acceptable.
    fig.tight_layout(rect=[.10, .06, .99, .97])
    fig.savefig(output, dpi=240)
    plt.close(fig)
    # Keep a tabular record of exactly the values drawn in the cluster plot so
    # PDF tables cannot silently diverge from their corresponding figure.
    with output.with_suffix(".csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "energy_rank", "cluster_id", "best_energy_kcal_per_mol",
            "rmsd_angstrom", "pose_count",
        ])
        writer.writeheader()
        for (row, _), rmsd in zip(entries, rmsds):
            writer.writerow({
                "energy_rank": row.get("energy_rank", ""),
                "cluster_id": row.get("cluster_id", ""),
                "best_energy_kcal_per_mol": row.get("best_energy_kcal_per_mol", ""),
                "rmsd_angstrom": f"{rmsd:.6f}",
                "pose_count": row.get("pose_count", ""),
            })
    return True


def render_overlay(receptor, ligands, colors, output, session, pymol, ligand_surfaces=False):
    """Render selected poses in one receptor frame for structural comparison."""
    if not pymol or not receptor or not Path(receptor).is_file() or any(not Path(path).is_file() for path in ligands):
        return False
    pml = output.with_suffix(".pml")
    objects = []
    lines = [
        "reinitialize", f'load "{Path(receptor).resolve()}", receptor', "hide everything, all",
        "remove (receptor and polymer.protein and hydro and neighbor elem C)",
    ]
    for index, (ligand, color) in enumerate(zip(ligands, colors), start=1):
        obj = f"report_ligand_{index}"
        objects.append(obj)
        lines += [f'load "{Path(ligand).resolve()}", {obj}', f"color {color}, {obj} and elem C", f"util.cnc {obj}"]
        if ligand_surfaces:
            lines += [f"show surface, {obj}", f"set transparency, 0.20, {obj}"]
        else:
            lines += [f"show sticks, {obj}"]
    selection = " or ".join(objects)
    lines += [
        f"select nearby_residues, byres (receptor within 5 of ({selection}))",
        "show sticks, nearby_residues", "color gray60, nearby_residues",
        # Keep the pocket readable without changing the receptor used for
        # docking or interaction analysis. Polar hydrogens remain visible.
        "hide sticks, (nearby_residues and hydro and neighbor elem C)",
        "set stick_radius, 0.18", "set ray_opaque_background, off", "bg_color white",
        f"orient {selection}", f"zoom {selection}, 8",
        f"png {output.resolve()}, 3600, 2400, dpi=440, ray=1",
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
    """Crop empty margins while retaining consistent report-panel padding."""
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
    """Draw a compact 2D diagram using retained PLIP calls as authority."""
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


def combine_panels(panel_a, panel_b, output, control=False, panel_b_legend=()):
    """Compose labeled report panels without changing scientific content."""
    from PIL import Image, ImageChops, ImageDraw, ImageFont

    a = Image.open(panel_a).convert("RGB")
    b = Image.open(panel_b).convert("RGB")
    bbox = ImageChops.difference(b, Image.new("RGB", b.size, "white")).getbbox()
    if bbox:
        # Keep only a narrow visual margin around the receptor.  The source
        # render's former wide margin made the protein appear misaligned even
        # when the composite frames had identical bounds.
        pad = 30
        b = b.crop((max(0, bbox[0]-pad), max(0, bbox[1]-pad), min(b.width, bbox[2]+pad), min(b.height, bbox[3]+pad)))
    canvas_w, canvas_h = 4800, 2400
    margin, gap, label_h = 70, 60, 150
    # The cavity-review layout uses A -> B -> vertical legend. The ranking plot
    # is tall enough to match the structural view, while the legend occupies a
    # dedicated right-hand column and can never obscure the receptor.
    left_w = 1880 if control else 1800
    legend_col_w = 0 if control else 480
    right_w = canvas_w - 2 * margin - gap - left_w - legend_col_w - (0 if control else gap)

    def fit(image, width, height):
        ratio = min(width / image.width, height / image.height)
        return image.resize((int(image.width * ratio), int(image.height * ratio)), Image.Resampling.LANCZOS)

    a = fit(a, left_w, canvas_h - 2 * margin - label_h)
    b_offset = 55 if control else 0
    b = fit(
        b, right_w - 80,
        max(300, a.height - b_offset) if control else 1600,
    )
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    group_height = max(a.height, b.height)
    a_x = margin + (left_w - a.width) // 2
    a_y = margin + label_h + (group_height - a.height) // 2
    # Preserve the approved compact control-panel spacing.  The final
    # equal-padding crop below centers the complete A/B group on the page;
    # centering must not be achieved by spreading the panels apart.
    b_x = (
        margin + left_w + gap + (right_w - b.width) // 2 - 90
        if control else
        margin + left_w + gap + (right_w - b.width) // 2
    )
    # A and B now share the same frame height and top baseline.  Keep the
    # legend attached to this same B group below the aligned frame.
    # The receptor's visible extrema sit a little inside its frame after the
    # tight crop; place that frame slightly lower so the extrema align with
    # the plotted data region in A while the legend remains bottom-aligned.
    b_y = margin + label_h + (group_height - b.height) // 2 + b_offset
    canvas.paste(a, (a_x, a_y))
    canvas.paste(b, (b_x, b_y))
    draw = ImageDraw.Draw(canvas)
    font_path = Path("/System/Library/Fonts/Helvetica.ttc")
    font = ImageFont.truetype(str(font_path), 96) if font_path.is_file() else ImageFont.load_default()
    legend_font_size = 28 if control else 40
    legend_heading_size = 26 if control else 32
    legend_font = ImageFont.truetype(str(font_path), legend_font_size) if font_path.is_file() else ImageFont.load_default()
    legend_heading_font = ImageFont.truetype(str(font_path), legend_heading_size) if font_path.is_file() else ImageFont.load_default()
    label_y = 36 if control else max(36, min(a_y, b_y) - 115)
    draw.text((margin, label_y), "A", fill="black", font=font)
    draw.text((b_x, label_y), "B", fill="black", font=font)
    if panel_b_legend:
        columns = 6 if control else 1
        rows = (len(panel_b_legend) + columns - 1) // columns
        legend_w = min(right_w - 80, 2380) if control else legend_col_w - 30
        row_h, heading_h, legend_pad = (38, 32, 12) if control else (58, 80, 14)
        legend_h = heading_h + rows * row_h + 2 * legend_pad
        legend_x = (
            b_x + b.width - legend_w - 18 if control
            else margin + left_w + gap + right_w + gap + (legend_col_w - legend_w) // 2
        )
        legend_y = 18 if control else margin + label_h + (group_height - legend_h) // 2
        draw.rounded_rectangle(
            (legend_x, legend_y, legend_x + legend_w, legend_y + legend_h),
            radius=16, fill="white", outline="#777777", width=3,
        )
        legend_heading = (
            "Filled P = fpocket surface   |   outline = proposed search box"
            if control else "Filled: fpocket surface\nOutline: proposed box"
        )
        draw.multiline_text(
            (legend_x + legend_pad, legend_y + legend_pad), legend_heading,
            fill="black", font=legend_heading_font, spacing=4,
        )
        column_w = (legend_w - 2 * legend_pad) // columns
        for index, (label, color, kind) in enumerate(panel_b_legend):
            row = index // columns
            column = index % columns
            item_x = legend_x + legend_pad + column * column_w
            item_y = legend_y + legend_pad + heading_h + row * row_h
            swatch_w = 40 if control else 48
            swatch_h = 26 if control else 32
            swatch = (item_x, item_y + 6, item_x + swatch_w, item_y + 6 + swatch_h)
            if kind == "surface":
                draw.rounded_rectangle(swatch, radius=6, fill=color, outline="#333333", width=2)
            else:
                draw.rectangle(swatch, fill="white", outline=color, width=5)
            draw.text((item_x + (54 if control else 62), item_y), str(label), fill="black", font=legend_font)
    content = ImageChops.difference(canvas, Image.new("RGB", canvas.size, "white")).getbbox()
    if content:
        # Trim the composite to equal visible padding on every horizontal side.
        # ReportLab centers the resulting image frame; retaining the original
        # 2400 px canvas here made unequal internal whitespace look like a page-
        # placement error even when the frame itself was mathematically centered.
        side_pad = 35 if not control else 70
        canvas = canvas.crop((
            max(0, content[0] - side_pad),
            0,
            min(canvas.width, content[2] + side_pad),
            min(canvas.height, content[3] + 70),
        ))
    canvas.save(output, quality=95, dpi=(440, 440))
    return True


def combine_cluster_snapshots(analysis, rows, output):
    """Build a compact, consistently labeled figure from up to three 3D renders."""
    from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageOps

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
    label_font = ImageFont.truetype(str(font_path), 168) if font_path.is_file() else ImageFont.load_default()
    caption_font = ImageFont.truetype(str(font_path), 120) if font_path.is_file() else ImageFont.load_default()
    cell_w, image_h = 3600, 2400
    if len(entries) == 1:
        canvas_w, canvas_h = 2800, 1940
        positions = [(350, 140)]
        cell_w, image_h = 2100, 1320
    elif len(entries) == 2:
        canvas_w, canvas_h = 7544, 2780
        positions = [(20, 60), (3860, 60)]
    else:
        # Three selected clusters need enough area for inspection.  Put two
        # panels across the top and the third beneath them rather than making
        # three unreadably narrow horizontal thumbnails.
        # The 16 px border expands each 1800 px panel to 1832 px.  Use the
        # same 88 px frame-to-frame spacing horizontally and vertically.
        canvas_w, canvas_h = 7544, 5440
        image_h = 2400
        positions = [(20, 60), (3860, 60), (1940, 2700)]
    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)
    panel_letters = "ABC"
    sources = []
    for index, ((row, source, color), (x, y)) in enumerate(zip(entries, positions)):
        snapshot = Image.open(source).convert("RGB")
        content = ImageChops.difference(snapshot, Image.new("RGB", snapshot.size, "white")).getbbox()
        if content:
            pad = 64
            snapshot = snapshot.crop((
                max(0, content[0] - pad), max(0, content[1] - pad),
                min(snapshot.width, content[2] + pad), min(snapshot.height, content[3] + pad),
            ))
        # Fill the wide report panel instead of preserving the source aspect
        # ratio and leaving large horizontal white bands.
        inner_w = int((cell_w - 72) * 0.92)
        inner_h = int((image_h - 48) * 0.92)
        crop_center = (0.65, 0.5) if index == 1 else (0.5, 0.5)
        snapshot = ImageOps.fit(
            snapshot, (inner_w, inner_h),
            method=Image.Resampling.LANCZOS, centering=crop_center,
        )
        frame = Image.new("RGB", (cell_w, image_h), "white")
        frame.paste(snapshot, ((cell_w - snapshot.width) // 2, (image_h - snapshot.height) // 2))
        frame = ImageOps.expand(frame, border=32, fill=color)
        canvas.paste(frame, (x, y))
        draw.text((x + 64, y + 56), panel_letters[index], fill=color, font=label_font)
        score = row.get("best_energy_kcal_per_mol", "NA")
        caption = f"Energy rank {row.get('energy_rank', index + 1)} | Cluster {row.get('cluster_id', 'NA')} | Vina {score} kcal/mol"
        bounds = draw.textbbox((0, 0), caption, font=caption_font)
        draw.text((x + (cell_w - (bounds[2] - bounds[0])) / 2, y + image_h + 96), caption, fill=color, font=caption_font)
        sources.append(str(source.resolve()))
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, dpi=(440, 440))
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
    """Build pose-recovery and interaction figures for a retained control."""
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
    """Build cluster and interaction figures independently for each compound."""
    outputs = []
    report = study / "report"
    report.mkdir(parents=True, exist_ok=True)
    for compound in sorted((study / "compounds").glob("*")):
        direct = compound / "pose_analysis"
        analyses = [(compound.name, direct)] if cluster_rows(direct) else []
        if not analyses:
            for site in sorted(
                compound.glob("site_*"),
                key=lambda path: int(path.name.split("_", 1)[1])
                if path.name.split("_", 1)[1].isdigit() else 10**9,
            ):
                analysis = site / "pose_analysis"
                if cluster_rows(analysis):
                    analyses.append((f"{compound.name}_{site.name}", analysis))
        for asset_id, analysis in analyses:
            rows = cluster_rows(analysis)
            panel_a = report / f"{asset_id}_panel_A_clusters.png"
            if not plot_clusters(analysis, panel_a):
                continue
            selected = rows[:3]
            # Keep Panel B structurally synchronized with the selected clusters
            # in Panel A. Multi-site analyses deliberately receive distinct
            # asset names so figures from one box cannot overwrite another.
            ligands = materialize_cluster_representatives(analysis, selected, report, asset_id)
            receptor = analysis / "receptor.pdb"
            panel_b = report / f"{asset_id}_panel_B_representatives.png"
            # Docked compounds are shown as molecular sticks; only exploratory
            # fpocket hypotheses are rendered as surfaces in their separate figure.
            render_overlay(receptor, ligands, ["red", "blue", "yellow"], panel_b, report / f"{asset_id}_panel_B_representatives.pse", pymol)
            combined = report / f"{asset_id}_panels_AB.png"
            if panel_b.is_file():
                combine_panels(panel_a, panel_b, combined, control=False)
            outputs.extend(str(path) for path in (panel_a, panel_b, combined) if path.is_file())
            snapshots = report / f"{asset_id}_top3_3d_snapshots.png"
            if combine_cluster_snapshots(analysis, selected, snapshots):
                outputs.append(str(snapshots))
            for row in selected:
                cluster = analysis / f"cluster_{int(row['cluster_id']):03d}"
                diagram = cluster / "interactions" / "representative_plip2d.png"
                if render_plip2d(cluster / "interactions", cluster / "representative.sdf", diagram, plip2d):
                    outputs.append(str(diagram))
    return outputs


def main():
    """Generate every applicable report figure from a completed study folder."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--pymol", default="pymol")
    parser.add_argument("--plip2d-runner", type=Path, help="optional plip_to_2D direct runner")
    args = parser.parse_args()
    study = args.study.expanduser().resolve()
    study_summary = read_json(study / "report" / "study_summary.json")
    workflow_is_exploratory = (
        study_summary.get("workflow") == "exploratory"
        or study_summary.get("study_status") == "EXPLORATORY_NO_CONTROL"
    )
    control = args.control.expanduser().resolve() if args.control and not workflow_is_exploratory else (None if workflow_is_exploratory else discover_control(study))
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
