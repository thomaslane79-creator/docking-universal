#!/usr/bin/env python3
"""Generate final report figures directly from retained docking artifacts."""

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import shutil
import subprocess
from docking_universal.sdf_io import read_sdf, sdf_writer, read_mol
import sys
from pathlib import Path

from docking_universal_box_candidates import config_geometry, grouped_fpocket_boxes
from docking_universal.pose_visuals import cluster_color, write_pose_view
from docking_universal.pocket_metadata import POCKET_COLORS, LIGAND_EVIDENCE_GREEN


TOP_COLORS = ("#d62728", "#1f77b4", "#d9a400")
EVIDENCE_GREEN = LIGAND_EVIDENCE_GREEN
POCKET_PYMOL_NAMES = ('red', 'marine', 'gold', 'magenta', 'cyan', 'orange', 'violet', 'brown', 'pink', 'slate') + tuple(f'du_pocket_color_{i}' for i in range(11, len(POCKET_COLORS) + 1))


def pocket_color_definitions():
    """Use identical RGB values in plots and every generated PyMOL scene."""
    return [f"set_color {name}, [{int(color[1:3], 16)/255:.4f},{int(color[3:5], 16)/255:.4f},{int(color[5:7], 16)/255:.4f}]"
            for name, color in zip(POCKET_PYMOL_NAMES, POCKET_COLORS)]


def pocket_engine_name(rows):
    """Return the detector label recorded by a normalized pocket table."""
    engines = {
        str(row.get("pocket_engine", "")).strip().lower()
        for row in rows if str(row.get("pocket_engine", "")).strip()
    }
    if engines == {"p2rank"}:
        return "P2Rank"
    if engines == {"fpocket"} or not engines:
        return "fpocket"
    return "/".join(sorted(engines))


def pocket_score(row):
    """Read the normalized detector score while supporting legacy fpocket tables."""
    return row.get("rank_score", row.get("score"))


def pocket_recovery(group):
    """Read detector-neutral recovery evidence, including legacy studies."""
    return group.get("pocket_recovery") or group.get("fpocket_recovery") or {}


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


def cavity_receptor(diagnostics, recorded_receptor=None):
    """Resolve the receptor from the protocol, including split preparation layouts."""
    if recorded_receptor and Path(recorded_receptor).is_file():
        return Path(recorded_receptor)
    return first(diagnostics.parent.parent, ["receptor/*.pdb"])


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


def selected_box_pocket_grid(cavity, receptor, selected_pairs, additional_regions):
    """Find verified P2Rank pocket grids intersecting any selected box."""
    from docking_universal.services.pocket_space import cached
    from docking_universal.pocket_sites import ligand_fits
    geometries = []
    for config, _ in selected_pairs:
        path = Path(config)
        if not path.is_absolute():
            path = Path(cavity) / path
        if path.is_file():
            geometries.append(config_geometry(path))
    for region in additional_regions:
        geometry = region.get('geometry') or {}
        if all(geometry.get(f'{kind}_{axis}') is not None for kind in ('center', 'size') for axis in 'xyz'):
            geometries.append(geometry)
    if not geometries:
        return None, set()
    for path in (Path(cavity) / 'pocket_space_visuals').glob('*/manifest.json'):
        try:
            record = json.loads(path.read_text())
            if Path(record['receptor']).resolve() != Path(receptor).resolve():
                continue
            manifest = cached(record)
            if not manifest:
                continue
            ranks = set()
            with gzip.open(manifest['grid'], 'rt') as handle:
                for line in handle:
                    if not line.startswith(('ATOM  ', 'HETATM')):
                        continue
                    point = tuple(float(line[i:i + 8]) for i in (30, 38, 46))
                    if any(ligand_fits([point], box) for box in geometries):
                        ranks.add(int(line[22:26]))
            return manifest, ranks
        except (OSError, KeyError, ValueError, TypeError):
            continue
    return None, set()


def _displayed_pocket_colors(selected_rows, evidence_site_numbers=()):
    """Assign stable, non-green colors to the ten displayed predictions."""
    retained = [row for row in selected_rows if row.get("decision") == "selected"]
    retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
    display_indexes = set(range(len(retained)))
    return {
        retained[index].get("pocket_file"): POCKET_COLORS[(int(retained[index].get('rank_order') or index + 1) - 1) % len(POCKET_COLORS)]
        for index in sorted(display_indexes)
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


def approved_region_plot_note(regions):
    notes = []
    for region in regions:
        note = "Approved box " + str(region.get('box_label') or region.get('box_name') or 'unlabeled')
        if region.get('site_source') == 'input_bound_ligand':
            predictions = [str(member.get('label') or member.get('id'))
                           for member in (region.get('site_group') or {}).get('members', [])
                           if member.get('pocket_prediction') and (member.get('label') or member.get('id'))]
            note += (" = input ligand; merged with " + ", ".join(predictions)
                     if predictions else " = input ligand; no prediction score")
        notes.append(note)
    return "\n".join(notes)


def plot_cavity_selection(
    diagnostics, selected_config, output, selected_configs=None,
    evidence_site_numbers=(), unmatched_ligand_region_labels=(), approved_region_note="",
):
    """Plot prediction scores, keeping approved-region identity separate."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    with Path(diagnostics).open(newline="") as handle:
        selected_rows = list(csv.DictReader(handle, delimiter="\t"))
    rows = [row for row in selected_rows if pocket_score(row) not in {None, "", "NA"}]
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
    shared_box_numbers = {
        int(number)
        for group in shared_box_groups if len(group["numbers"]) > 1
        for number in group["numbers"]
    }
    pocket_numbers = {
        row.get("pocket_file"): int(row.get("rank_order", index + 1) or index + 1)
        for index, row in enumerate(retained_rows)
    }
    ranks = [int(row["rank_order"]) for row in rows]
    scores = [float(pocket_score(row)) for row in rows]
    engine = pocket_engine_name(selected_rows)
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
        if pocket_number and pocket_number not in shared_box_numbers and row.get("pocket_file") in displayed_colors:
            color = displayed_colors.get(row.get("pocket_file"), "#333333")
            ax.annotate(
                f"Box P{pocket_number}", (rank, score), xytext=(0, -18),
                textcoords="offset points", ha="center", va="top",
                fontsize=10, color=color,
            )
    row_by_display_number = {
        pocket_numbers.get(row.get("pocket_file")): row for row in retained_rows
    }
    for group in shared_box_groups:
        numbers = [int(number) for number in group["numbers"]]
        if len(numbers) < 2:
            continue
        points = [
            (int(row_by_display_number[number]["rank_order"]),
             float(pocket_score(row_by_display_number[number])))
            for number in numbers
            if number in row_by_display_number
            and pocket_score(row_by_display_number[number]) not in {None, "", "NA"}
        ]
        if not points:
            continue
        anchor = (sum(point[0] for point in points) / len(points),
                  sum(point[1] for point in points) / len(points))
        label = "/".join(f"P{number}" for number in numbers)
        ax.annotate(
            f"Shared box {label}", anchor, xytext=(0, -34),
            textcoords="offset points", ha="center", va="top", fontsize=10,
            color=group["color"], bbox=dict(fc="white", ec=group["color"], alpha=.96),
            arrowprops=dict(arrowstyle="->", color=group["color"]),
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
        f"candidate rank (P# = {engine}; L# = ligand-defined, unscored)",
        fontsize=13,
    )
    ax.set_ylabel(f"{engine} score", fontsize=14)
    ax.set_title(
        f"{engine} ranking and structural evidence"
        if selected_pairs else f"{engine} ranking with structural-evidence overlay",
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
        f"Colored P# = retained {engine} predictions\n"
        f"Gray = other {engine} candidates\n"
        + (f"Green ring = ligand correspondence ({ligand_evidence_labels})\n" if ligand_evidence_labels else "")
        + (f"Shared proposed box = {', '.join(shared_box_labels)}\n" if shared_box_labels else "")
        + ("L# X at 0 = ligand-defined box; no detector score" if unmatched_ligand_region_labels else "")
    )
    if approved_region_note:
        legend_text = approved_region_note + "\n" + legend_text
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
    ligand_site_groups=(), show_labels=False, additional_selected_regions=(), *, receptor_path=None,
):
    """Show retained pockets and boxes with stable colors across report panels.

    Report images identify pockets through the shared color key, keeping text
    labels out of the molecular view.  Labels remain available only when a
    caller explicitly requests them for a specialized review artifact.
    """
    if not pymol:
        return False
    receptor = cavity_receptor(diagnostics, receptor_path)
    if not receptor:
        return False
    with Path(diagnostics).open(newline="") as handle:
        retained = [row for row in csv.DictReader(handle, delimiter="\t") if row.get("decision") == "selected"]
    retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
    if not retained:
        return False
    pocket_numbers = {row.get("pocket_file"): int(row.get('rank_order') or index + 1) for index, row in enumerate(retained)}
    receptor_center = pdb_centroid(receptor)
    selected_pairs = _selected_pocket_files(
        retained, [selected_config] if selected_configs is None else selected_configs
    )
    selected_by_file = {pocket: config for config, pocket in selected_pairs}
    displayed_colors = _displayed_pocket_colors(retained, evidence_site_numbers)
    grid_manifest, inside_ranks = (selected_box_pocket_grid(diagnostics.parent, receptor, selected_pairs,
                                                            additional_selected_regions)
                                   if selected_only else (None, set()))
    if selected_only:
        retained = [row for row in retained if row.get("pocket_file") in selected_by_file
                    or (grid_manifest and pocket_numbers.get(row.get('pocket_file')) in inside_ranks)]
    else:
        # Show the top ten surfaces for spatial context, while only the first
        # three receive distinguishing colors and proposed-box wireframes.
        retained = retained[:10]
    pymol_colors = dict(zip(POCKET_COLORS, POCKET_PYMOL_NAMES))
    lines = [
        "reinitialize", *pocket_color_definitions(), f'load "{receptor.resolve()}", receptor', "hide everything, all",
        "show cartoon, receptor", "color gray70, receptor", "set cartoon_transparency, 0.12, receptor",
    ]
    if grid_manifest:
        lines += [f'load "{grid_manifest["grid"]}", selected_grid_source',
                  'hide everything, selected_grid_source', 'disable selected_grid_source']
    for row in retained:
        pocket_key = row.get("pocket_file", "")
        pocket = diagnostics.parent / "frozen_pockets" / pocket_key
        if not pocket.is_file():
            continue
        pocket_number = pocket_numbers[pocket_key]
        obj = f"retained_pocket_{pocket_number}"
        color = pymol_colors.get(displayed_colors.get(pocket_key), "gray60")
        source = (f'create {obj}, selected_grid_source and resi {pocket_number}' if grid_manifest
                  else f'load "{pocket.resolve()}", {obj}')
        if grid_manifest:
            color = POCKET_PYMOL_NAMES[(pocket_number - 1) % len(POCKET_PYMOL_NAMES)]
        lines += [
            source, f"hide everything, {obj}",
            *([f'alter {obj}, vdw={float(grid_manifest["display_radius_angstrom"])}', f'rebuild {obj}'] if grid_manifest else []),
            f"show surface, {obj}",
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
    if selected_only:
        for index, region in enumerate(additional_selected_regions, 1):
            geometry = region.get('geometry') or {}
            members = (region.get('site_group') or {}).get('members') or []
            # Use the first source pocket with an established figure color.
            # Other pockets merged into the site share its selected-box color.
            region_color = next((pymol_colors[displayed_colors[name]] for member in members
                                 for name in [Path(str((member.get('pocket_prediction') or {}).get('pocket_file') or '')).name]
                                 if name in displayed_colors and displayed_colors[name] in pymol_colors), 'orange')
            if not all(geometry.get(f'{kind}_{axis}') is not None for kind in ('center', 'size') for axis in 'xyz'):
                raise ValueError('Selected docking region is missing box geometry')
            box_path = output.with_name(f'{output.stem}_additional_{index}_box.pdb')
            write_box_coordinate_file(box_path, geometry)
            obj = f'additional_selected_box_{index}'
            lines += [f'load "{box_path.resolve()}", {obj}', f'hide everything, {obj}',
                      f'show sticks, {obj}', f'set stick_radius, 0.08, {obj}', f'color {region_color}, {obj}']
            for ligand_index, ligand in enumerate((region.get('site_group') or {}).get('ligands') or [], 1):
                observation = ligand.get('observation') or {}
                ligand_path = Path(str(observation.get('aligned_ligand_pdb') or ligand.get('path') or ''))
                if not ligand_path.is_file():
                    continue
                ligand_obj = f'additional_ligand_{index}_{ligand_index}'
                lines += [f'load "{ligand_path.resolve()}", {ligand_obj}',
                          f'hide everything, {ligand_obj}', f'show sticks, {ligand_obj}',
                          f'color green, {ligand_obj}', f'set stick_radius, 0.24, {ligand_obj}']
            # A ligand-defined box may have absorbed predicted pockets during
            # site merging. Show those retained surfaces without adding their
            # original boxes or altering the selected box geometry.
            for pocket_index, member in enumerate(() if grid_manifest else members, 1):
                prediction = member.get('pocket_prediction') or {}
                pocket_name = Path(str(prediction.get('pocket_file') or '')).name
                if not pocket_name:
                    continue
                pocket_path = diagnostics.parent / 'frozen_pockets' / pocket_name
                if not pocket_path.is_file():
                    raise ValueError(f'Merged pocket surface is unavailable: {pocket_name}')
                pocket_obj = f'additional_pocket_{index}_{pocket_index}'
                lines += [f'load "{pocket_path.resolve()}", {pocket_obj}', f'hide everything, {pocket_obj}',
                          f'show surface, {pocket_obj}', f'set transparency, 0.62, {pocket_obj}',
                          f'color {region_color}, {pocket_obj}']
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
    # With one ligand-defined site, integrate its representative into the main
    # pocket panel.  When it corresponds to a predicted pocket, that pocket's
    # candidate box is the only box: drawing the evidence-derived bounds as a
    # second same-colored box is visually ambiguous and creates an unlisted
    # pseudo-candidate.  Only an unmatched ligand-defined site gets its own box.
    if ligand_site_group:
        matched_number = pocket_recovery(ligand_site_group).get("best_matching_pocket")
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
            if matched_number:
                # Remove the coordinate artifact emitted by older versions.
                # The matched pocket's candidate box is authoritative.
                stale_ligand_box = output.with_name(output.stem + "_ligand_site_box.pdb")
                if stale_ligand_box.is_file():
                    stale_ligand_box.unlink()
            if not selected_only and not matched_number:
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
        molecule = read_mol(ligand_sdf, removeHs=True)
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
    from docking_universal.services.molecule_inspection import is_supporting_component_observation
    supporting = []
    for row in record.get("evidence", []):
        if is_supporting_component_observation(row):
            continue
        if any(
            int(item.get("pocket_number", -1)) == pocket_number
            and bool(item.get("cavity_match", False))
            and bool(item.get("all_heavy_atoms_inside", False))
            for item in row.get("pocket_relationships", [])
        ):
            supporting.append(row)
    return supporting


def build_pocket_evidence_figure(diagnostics, selected_config, output, pymol, pocket_color="red", *, receptor_path=None):
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
    receptor = cavity_receptor(diagnostics, receptor_path)
    with Path(diagnostics).open(newline="") as handle:
        retained = [row for row in csv.DictReader(handle, delimiter="\t") if row.get("decision") == "selected"]
    retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
    pocket_row = retained[pocket_number - 1] if pocket_number <= len(retained) else retained[0]
    pocket = diagnostics.parent / "frozen_pockets" / pocket_row.get("pocket_file", "")
    if not receptor or not ligand.is_file() or not pocket.is_file():
        return False
    panel_3d = output.with_name(output.stem + "_3D.png")
    panel_2d = output.with_name(output.stem + "_2D.png")
    pml = output.with_suffix(".pml")
    session = output.with_suffix(".pse")
    lines = [
        "reinitialize", *pocket_color_definitions(), f'load "{receptor.resolve()}", receptor',
        f'load "{pocket.resolve()}", selected_pocket',
        f'load "{ligand.resolve()}", supporting_ligand',
        "hide everything, all", "show cartoon, receptor", "color gray70, receptor",
        "set cartoon_transparency, 0.72, receptor",
        "show surface, selected_pocket",
        f"color {pocket_color}, selected_pocket", "set transparency, 0.72, selected_pocket",
        "show sticks, supporting_ligand", "color tv_orange, supporting_ligand",
        "set stick_radius, 0.24, supporting_ligand",
    ]
    lines += [
        "bg_color white", "set ray_opaque_background, off", "set depth_cue, 0",
        "orient (selected_pocket or supporting_ligand)", "zoom (selected_pocket or supporting_ligand), 5",
        f"png {panel_3d.resolve()}, 2800, 2200, dpi=480, ray=1",
        f"save {session.resolve()}", "quit",
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
             "hide everything, all", "show cartoon, receptor", "color gray70, receptor",
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


def overview_evidence(diagnostics, retained, groups, selected_regions):
    """Map retained ligand observations to a site, without inventing matches.

    The stored ligand-defined identifier is kept in the source record.  When a
    group contains a pocket, the displayed identity is that pocket; B labels
    are reserved for ligand-only groups.
    """
    import re
    by_file = {Path(str(row.get('pocket_file', ''))).name: i
               for i, row in enumerate(retained, 1)}
    sites = []
    evidence_root = diagnostics.parent / 'pdb_site_evidence'

    def add(label, path, description, member_numbers=()):
        path = Path(path) if path else None
        existing = next((item for item in sites if item['label'] == label), None)
        observation = {'path': path, 'description': description}
        if existing:
            existing['observations'].append(observation)
            existing['member_numbers'] = sorted(set(existing['member_numbers']) | set(member_numbers))
        else:
            sites.append({'label': label, 'observations': [observation],
                          'member_numbers': list(member_numbers)})

    unmatched = 0
    for region in selected_regions:
        if region.get('site_source') != 'input_bound_ligand':
            continue
        group = region.get('site_group') or {}
        numbers = sorted({by_file[name] for member in group.get('members', [])
                          for name in [Path(str((member.get('pocket_prediction') or {}).get('pocket_file') or '')).name]
                          if name in by_file})
        if numbers:
            label = f'P{numbers[0]}'
        else:
            unmatched += 1
            label = f'B{unmatched}'
        ligands = group.get('ligands') or []
        for ligand in ligands:
            obs = ligand.get('observation') or {}
            name = str(obs.get('ligand') or 'Input ligand')
            add(label, obs.get('aligned_ligand_pdb') or ligand.get('path'),
                f'{name} · input structure', numbers)
        if not ligands:
            add(label, None, 'Input ligand coordinates unavailable', numbers)

    for group in groups:
        recovery = pocket_recovery(group)
        number = recovery.get('best_matching_pocket')
        match = re.search(r'(\d+)', str(number or ''))
        source_name = f'pocket{int(match.group(1))}_atm.pdb' if match else ''
        index = by_file.get(source_name)
        if index:
            label = f'P{index}'
        else:
            unmatched += 1
            label = f'B{unmatched}'
        representative = group.get('representative_ligand') or {}
        if not representative:
            representative = next(iter(group.get('members') or []), {})
        relative = representative.get('aligned_ligand_pdb')
        path = evidence_root / relative if relative else None
        source = str(representative.get('entry') or 'Related structure')
        ligand = str(representative.get('ligand') or 'ligand')
        add(label, path, f'{ligand} · {source} (related structure)', [index] if index else [])
    return sites


def overview_visible_indices(retained, sites, selected_regions=()):
    """Keep top ten plus any selected or ligand-supported pocket, in rank order."""
    import re
    wanted = set(range(1, min(10, len(retained)) + 1))
    labels = [site['label'] for site in sites]
    labels += [str(region.get('box_label') or '') for region in selected_regions]
    for label in labels:
        match = re.fullmatch(r'P(\d+)', label, re.I)
        if match and 1 <= int(match.group(1)) <= len(retained):
            wanted.add(int(match.group(1)))
    return sorted(wanted)


def plot_evidence_overview(diagnostics, retained, sites, output, visible_indices=None):
    """Render scored predictions and explicitly unscored ligand-only sites."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    indices = visible_indices if visible_indices is not None else overview_visible_indices(retained, sites)
    scored = [(i, retained[i-1], float(pocket_score(retained[i-1]))) for i in indices
              for row in [retained[i-1]]
              if pocket_score(row) not in (None, '', 'NA')]
    unmatched = [site for site in sites if site['label'].startswith('B')]
    if not scored and not unmatched:
        return False
    engine = pocket_engine_name(retained) if retained else None
    fig, ax = plt.subplots(figsize=(8, 7))
    for position, (index, row, score) in enumerate(scored, 1):
        ax.scatter(position, score, s=160, c=POCKET_COLORS[(index-1) % len(POCKET_COLORS)],
                   edgecolors='#222222', linewidths=.7, zorder=3)
        if any(site['label'] == f'P{index}' for site in sites):
            ax.scatter(position, score, s=295, facecolors='none', edgecolors=EVIDENCE_GREEN,
                       linewidths=2.8, zorder=4)
        ax.annotate(f'{score:g}', (position, score), xytext=(0, 10), textcoords='offset points',
                    ha='center', fontsize=13, fontweight='bold')
    positions = list(range(1, len(scored) + 1))
    labels = [f'P{item[0]}' for item in scored]
    # Ligand-only sites are labeled in the structural panel. They do not
    # belong on a numeric score axis, including at its zero baseline.
    if scored:
        max_score = max(value for _, _, value in scored)
        min_score = min(value for _, _, value in scored)
        ax.set_ylim(min(0, min_score - abs(max_score)*.08), max_score + max(1, abs(max_score)*.18))
    else:
        ax.set_ylim(0, 1)
        ax.set_yticks([])
        ax.text(.5, .55, 'No scored pocket predictions', transform=ax.transAxes,
                ha='center', va='center', fontsize=18)
    ax.set_xlim(.3, max([1] + positions) + .7)
    ax.set_xticks(positions, labels, rotation=45 if len(labels) > 12 else 0)
    ax.set_ylabel(f'{engine} score' if engine else 'Pocket score', fontsize=18)
    ax.tick_params(axis='both', labelsize=17)
    if any(site['label'] in labels for site in sites):
        ax.text(.02, 1.075, 'Green ring = ligand evidence for the site', transform=ax.transAxes,
                ha='left', va='top', fontsize=17, color='#126337',
                bbox=dict(boxstyle='round,pad=.4', fc='#edf9f1', ec='#9bd1aa', linewidth=1.25))
    if unmatched:
        ax.text(.02, .89, 'Unscored ligand-only sites are shown in panel B',
                transform=ax.transAxes, ha='left', va='top', fontsize=12, color='#126337')
    missing = [site['label'] for site in sites if not any(
        o['path'] and o['path'].is_file() for o in site['observations'])]
    if missing:
        ax.text(.02, .83 if unmatched else .89, 'Ligand coordinates unavailable: ' + ', '.join(missing),
                transform=ax.transAxes, ha='left', va='top', fontsize=12, color='#8b3d16')
    ax.grid(axis='y', color='#e1e6ea')
    ax.set_axisbelow(True)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.subplots_adjust(left=.12, right=.98, bottom=.19, top=.9)
    fig.savefig(output, dpi=240, facecolor='white')
    plt.close(fig)
    return True


def render_evidence_overview(diagnostics, retained, sites, output, session, pymol, receptor_path=None,
                             visible_indices=None):
    """Render pocket surfaces and representatives in their retained coordinate frame."""
    if not pymol:
        return False
    receptor = cavity_receptor(diagnostics, receptor_path)
    if not receptor:
        return False
    lines = ['reinitialize', f'load "{receptor.resolve()}", receptor', 'hide everything, all',
             'show cartoon, receptor', 'color gray70, receptor', 'set cartoon_transparency, 0.12, receptor']
    indices = visible_indices if visible_indices is not None else overview_visible_indices(retained, sites)
    for layer, index in enumerate(indices):
        row = retained[index-1]
        pocket = diagnostics.parent / 'frozen_pockets' / str(row.get('pocket_file') or '')
        if not pocket.is_file():
            continue
        color = POCKET_COLORS[(index-1) % len(POCKET_COLORS)]
        rgb = [int(color[j:j+2], 16) / 255 for j in (1, 3, 5)]
        # Pockets can share lining atoms. Slightly separate coincident
        # rendered surfaces in depth without moving any atoms.
        offset = 0.08 * layer / max(1, len(indices) - 1)
        lines += [f'set_color du_pocket_{index}, [{rgb[0]:.4f},{rgb[1]:.4f},{rgb[2]:.4f}]',
                  f'load "{pocket.resolve()}", du_pocket_{index}',
                  f'hide everything, du_pocket_{index}',
                  f'alter du_pocket_{index}, vdw=vdw+{offset:.5f}',
                  f'show surface, du_pocket_{index}',
                  f'color du_pocket_{index}, du_pocket_{index}', f'set transparency, 0.32, du_pocket_{index}']
    rendered = []
    for index, site in enumerate(sites, 1):
        obs = next((o for o in site['observations'] if o['path'] and o['path'].is_file()), None)
        if not obs:
            continue
        # Input/related identities are kept in the label; alternate ligands
        # remain in the evidence record rather than being silently overlaid.
        obj = f'du_evidence_ligand_{index}'
        lines += [f'load "{obs["path"].resolve()}", {obj}', f'hide everything, {obj}',
                  f'show sticks, {obj}', f'show spheres, {obj}', f'color green, {obj}',
                  f'set stick_radius, 0.38, {obj}', f'set sphere_scale, 0.18, {obj}']
        rendered.append(index)
    lines += ['bg_color white', 'set ray_opaque_background, on', 'set depth_cue, 0',
              'orient receptor', 'zoom all, 12', 'set ray_clip_near, 0',
              'python', 'from pymol import cmd',
              f'cmd.png({str(output.resolve())!r}, 2400, 1800, dpi=240, ray=1)',
              f'cmd.save({str(session.resolve())!r})', 'python end']
    for index in rendered:
        lines += ['disable all', f'enable du_evidence_ligand_{index}',
                  'python', f'cmd.png({str(output.with_name(output.stem + f"_marker_{index}.png").resolve())!r}, 2400, 1800, dpi=240, ray=1)', 'python end']
    lines += ['quit']
    wrapper = output.with_suffix('.pml')
    wrapper.write_text('\n'.join(lines) + '\n')
    result = subprocess.run([str(pymol), '-cq', str(wrapper)], text=True, capture_output=True)
    if result.returncode or not output.is_file():
        print(f'Report figure warning: evidence overview failed: {result.stderr.strip()}', file=sys.stderr)
        return False
    if rendered:
        from PIL import Image, ImageChops, ImageDraw, ImageFont
        picture = Image.open(output).convert('RGB')
        structure_bounds = ImageChops.difference(
            picture, Image.new('RGB', picture.size, 'white')).getbbox()
        # Locate ligand silhouettes in the same camera view, then place labels in
        # separate columns with leaders. This avoids PyMOL text colliding with
        # the structure or running off the edge at different image sizes.
        markers = []
        for index in rendered:
            marker = output.with_name(output.stem + f'_marker_{index}.png')
            if not marker.is_file():
                continue
            image = Image.open(marker).convert('RGB')
            bounds = ImageChops.difference(image, Image.new('RGB', image.size, 'white')).getbbox()
            if bounds:
                markers.append((index, (bounds[0]+bounds[2])//2, (bounds[1]+bounds[3])//2))
        markers.sort(key=lambda item: item[1])
        if markers:
            import textwrap
            draw = ImageDraw.Draw(picture)
            font_path = Path('/System/Library/Fonts/Helvetica.ttc')
            if not font_path.is_file():
                from matplotlib import font_manager
                font_path = Path(font_manager.findfont('DejaVu Sans'))
            font = ImageFont.truetype(str(font_path), 52)
            columns = min(5, len(markers))
            slot = picture.width / columns
            for position, (index, x, y) in enumerate(markers):
                site = sites[index-1]
                obs = next(o for o in site['observations'] if o['path'] and o['path'].is_file())
                heading = site['label'] + (' · no matching pocket recorded' if site['label'].startswith('B') else '')
                # Wrap long source names into the available column so several
                # evidence labels do not overwrite one another.
                chars = max(12, int((slot - 34) / 29))
                label = '\n'.join(textwrap.wrap(heading, chars) + textwrap.wrap(obs['description'], chars))
                bounds = draw.multiline_textbbox((0, 0), label, font=font, spacing=3)
                width = bounds[2] - bounds[0] + 22
                height = bounds[3] - bounds[1] + 18
                left = int(max(8, min(picture.width-width-8, (position%columns+.5)*slot-width/2)))
                # Anchor the first row near the structure rather than at the
                # top of a large blank render canvas. Multiple rows remain
                # staggered when many sites need labels.
                structure_top = structure_bounds[1] if structure_bounds else 100
                top = max(15, structure_top - height - 16) + (position//columns) * 160
                draw.line((left+width//2, top+height, x, y), fill=EVIDENCE_GREEN, width=5)
                draw.rounded_rectangle((left, top, left+width, top+height), radius=9,
                                       fill='white', outline='#9bd1aa', width=3)
                draw.multiline_text((left+11, top+7), label, font=font, fill='#125d32', spacing=3)
        picture.save(output)
    trim_white_png(output, padding=50)
    return True


def pocket_surface_legend(diagnostics, retained, displayed_colors):
    """Describe exactly the pocket surfaces drawn in the overview."""
    visible = [(index, row) for index, row in enumerate(retained[:10], start=1)
               if (diagnostics.parent / 'frozen_pockets' / row.get('pocket_file', '')).is_file()]
    entries = [(f"Cavity P{int(row.get('rank_order', index) or index)}",
                displayed_colors[row['pocket_file']], 'surface')
               for index, row in visible if row.get('pocket_file') in displayed_colors]
    if any(row.get('pocket_file') not in displayed_colors for _, row in visible):
        entries.append(('Other pockets', '#999999', 'surface'))
    return entries


def draw_report_panel_heading(fig, left, top, letter, title, *, printed_scale):
    """Draw matching label and title sizes after the PDF scales each panel."""
    width = fig.get_figwidth()
    fig.text(left, top, letter, fontsize=11 / printed_scale,
             weight='bold', va='baseline', color='#17212b')
    fig.text(left + 16 / (printed_scale * width * 72), top, title,
             fontsize=9 / printed_scale, weight='bold', va='baseline', color='#17212b')


def combine_evidence_panels(panel_a, panel_b, output, retained, visible_indices=None, *, ligand_markers=False):
    """Lay out the cropped images at equal height with a centered pocket key."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from PIL import Image, ImageChops

    pictures = []
    for path in (panel_a, panel_b):
        with Image.open(path) as source:
            picture = source.convert('RGB')
        bounds = ImageChops.difference(picture, Image.new('RGB', picture.size, 'white')).getbbox()
        pictures.append(picture.crop(bounds) if bounds else picture)

    indices = visible_indices if visible_indices is not None else list(range(1, min(10, len(retained)) + 1))
    handles = [Line2D([], [], marker='o', color='none', markerfacecolor=POCKET_COLORS[(i-1) % len(POCKET_COLORS)],
                      markeredgecolor='#333333', markersize=11, label=f'P{i}') for i in indices]
    panel_height, margin, heading = 5.6, .22, .64
    key_height = (.46 if handles else 0) + (.36 if ligand_markers else 0)
    # Bound each panel's footprint so a wide structure cannot shrink the whole
    # page figure. imshow fits the full image within the slot at its own aspect.
    plot_aspect, structure_aspect = (picture.width / picture.height for picture in pictures)
    widths = [panel_height * plot_aspect, panel_height * min(1.75, max(.65, structure_aspect))]
    gap = sum(widths) * .085
    width = sum(widths) + 2 * margin + gap
    height = panel_height + heading + key_height + 2 * margin
    fig = plt.figure(figsize=(width, height), facecolor='white')
    left = margin
    printed_scale = min(7 / width, 4.15 / height)
    titles = ('Pocket prediction scores' if handles else 'Pocket predictions',
              'Pocket surfaces' if handles else 'Receptor overview')
    for label, title, picture, panel_width in zip(('A', 'B'), titles, pictures, widths):
        ax = fig.add_axes((left / width, (margin + key_height) / height,
                           panel_width / width, panel_height / height))
        ax.imshow(picture)
        ax.axis('off')
        label_left = left - gap * .48 if label == 'B' else left
        draw_report_panel_heading(fig, label_left / width, 1 - (margin + .22) / height,
                                  label, title, printed_scale=printed_scale)
        left += panel_width + gap
    if handles:
        # Measure the single ranked row so even high-numbered pockets fit.
        legend_options = dict(handles=handles, loc='lower center', ncol=len(handles),
                              bbox_to_anchor=(.5, (.07 + (.36 if ligand_markers else 0)) / height),
                              borderaxespad=0, frameon=False, columnspacing=1.0,
                              handletextpad=.35)
        legend = fig.legend(fontsize=19, **legend_options)
        fig.canvas.draw()
        available = fig.bbox.width * (width - 2 * margin) / width
        legend_width = legend.get_window_extent().width
        if legend_width > available:
            scale = available / legend_width
            legend.remove()
            for handle in handles:
                handle.set_markersize(11 * scale)
            fig.legend(fontsize=19 * scale, **legend_options)
    if ligand_markers:
        fig.text(.5, .07 / height, 'Green sticks show aligned ligand evidence',
                 ha='center', va='bottom', fontsize=16, color='#126337')
    fig.savefig(output, dpi=240, facecolor='white')
    plt.close(fig)
    return True


def render_ligand_only_selected_boxes(receptor, regions, output, pymol):
    """Show the actual approved geometry when no pocket detector was run."""
    if not pymol or not regions:
        return False
    lines = ['reinitialize', *pocket_color_definitions(), f'load "{receptor.resolve()}", receptor',
             'hide everything, all', 'show cartoon, receptor', 'color gray70, receptor']
    rendered = 0
    for index, region in enumerate(regions, 1):
        geometry = region.get('geometry') or {}
        try:
            values = {f'{part}_{axis}': float(geometry[f'{part}_{axis}'])
                      for part in ('center', 'size') for axis in 'xyz'}
        except (KeyError, TypeError, ValueError):
            continue
        box = output.with_name(f'{output.stem}_{index}_box.pdb')
        write_box_coordinate_file(box, values)
        obj = f'selected_box_{index}'
        lines += [f'load "{box.resolve()}", {obj}', f'hide everything, {obj}',
                  f'show sticks, {obj}', f'color {POCKET_PYMOL_NAMES[(index-1) % len(POCKET_PYMOL_NAMES)]}, {obj}',
                  f'set stick_radius, 0.08, {obj}']
        for ligand in (region.get('site_group') or {}).get('ligands') or []:
            obs = ligand.get('observation') or {}
            path = Path(str(obs.get('aligned_ligand_pdb') or ligand.get('path') or ''))
            if path.is_file():
                name = f'selected_ligand_{index}'
                lines += [f'load "{path.resolve()}", {name}', f'hide everything, {name}',
                          f'show sticks, {name}', f'color green, {name}', f'set stick_radius, 0.24, {name}']
                break
        rendered += 1
    if not rendered:
        return False
    lines += ['bg_color white', 'set ray_opaque_background, on', 'orient receptor', 'zoom all, 12',
              'python', 'from pymol import cmd',
              f'cmd.png({str(output.resolve())!r}, 2400, 1800, dpi=240, ray=1)',
              f'cmd.save({str(output.with_suffix(".pse").resolve())!r})', 'python end', 'quit']
    wrapper = output.with_suffix('.pml')
    wrapper.write_text('\n'.join(lines) + '\n')
    result = subprocess.run([str(pymol), '-cq', str(wrapper)], text=True, capture_output=True)
    if result.returncode or not output.is_file():
        return False
    trim_white_png(output, padding=50)
    return True


def build_cavity_figures(study, pymol):
    """Build cavity figures solely from retained preparation evidence."""
    diagnostics, selected_config, scene = cavity_artifacts(study)
    if not diagnostics:
        # A ligand-defined site can exist without a detector run or any
        # prediction table. Produce an explicitly unscored evidence overview.
        report = study / 'report'
        summary = read_json(report / 'study_summary.json')
        regions = summary.get('selected_docking_regions') or []
        evidence = summary.get('pdb_pocket_evidence') or {}
        receptor_name = (summary.get('configured_locked_inputs') or {}).get('receptor_pdb')
        receptor = Path(receptor_name) if receptor_name else first(study, ['**/receptor/*.pdb'])
        box_name = next((r.get('box') for r in regions if r.get('box')), None)
        if not receptor or not receptor.is_file() or not box_name:
            return []
        from docking_universal.services.molecule_inspection import split_ligand_site_groups
        groups, _ = split_ligand_site_groups(evidence.get('ligand_site_groups') or [])
        diagnostic_location = Path(box_name).parent / 'pocket_selection_diagnostics.tsv'
        sites = overview_evidence(diagnostic_location, [], groups, regions)
        report.mkdir(parents=True, exist_ok=True)
        a = report / 'cavity_panel_A_selection.png'
        b = report / 'cavity_panel_B_structure.png'
        combined = report / 'cavity_panels_AB.png'
        ligand_markers = any(obs['path'] and obs['path'].is_file()
                             for site in sites for obs in site['observations'])
        if (plot_evidence_overview(diagnostic_location, [], sites, a)
                and render_evidence_overview(diagnostic_location, [], sites, b,
                                             report / 'cavity_panel_B_structure.pse', pymol, receptor)
                and combine_evidence_panels(a, b, combined, [], ligand_markers=ligand_markers)):
            (report / 'cavity_panels_AB.metadata.json').write_text(json.dumps({
                'figure_style': 'ligand_evidence_v3', 'visible_pockets': [],
                'ligand_rings': False, 'ligand_markers': ligand_markers,
                'sha256': hashlib.sha256(combined.read_bytes()).hexdigest(),
            }, indent=2) + '\n')
            outputs = [str(a), str(b), str(combined)]
            selected = report / 'cavity_selected_box.png'
            if render_ligand_only_selected_boxes(receptor, regions, selected, pymol):
                outputs.append(str(selected))
            return outputs
        return []
    report = study / "report"
    report.mkdir(parents=True, exist_ok=True)
    outputs = []
    summary = read_json(report / "study_summary.json")
    recorded_receptor = (summary.get("configured_locked_inputs") or {}).get("receptor_pdb")
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
    from docking_universal.services.molecule_inspection import split_ligand_site_groups
    ligand_site_groups, _ = split_ligand_site_groups(pocket_evidence.get("ligand_site_groups") or [])
    supported_numbers = {str(number) for group in ligand_site_groups for number in [
        (group.get('pocket_recovery') or group.get('fpocket_recovery') or {}).get('best_matching_pocket')]
        if number is not None}
    evidence_site_numbers = sorted(
        int(number) for number, item in evidence_summary.items()
        if str(number).isdigit() and str(number) in supported_numbers and int(item.get("contained_ligands", 0)) > 0
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
        recovery = pocket_recovery(group)
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
                recovered_pocket_numbers.append(
                    int(row.get("rank_order", display_index) or display_index)
                )
                break
    evidence_site_numbers = sorted(set(evidence_site_numbers + recovered_pocket_numbers))
    display_site_numbers = sorted(set(evidence_site_numbers + selected_site_numbers))
    displayed_colors = _displayed_pocket_colors(diagnostic_rows, display_site_numbers)
    retained_rows = [row for row in diagnostic_rows if row.get("decision") == "selected"]
    retained_rows.sort(key=lambda row: int(row.get("rank_order", 999999)))
    pymol_colors = dict(zip(POCKET_COLORS, POCKET_PYMOL_NAMES))
    panel_a = report / "cavity_panel_A_selection.png"
    unmatched_ligand_region_labels = [
        (group.get("site_identity") or {}).get(
            "canonical_label", f"L{group.get('site_number', index + 1)}",
        )
        for index, group in enumerate(ligand_site_groups)
        if (group.get("site_identity") or {}).get(
            "is_separate_from_predicted_pocket",
            group.get("site_identity", {}).get("is_separate_from_fpocket", pocket_recovery(group).get("status") == "not_recovered"),
        )
    ]
    selected_paths = {str(region.get('box') or region.get('box_name') or '') for region in selected_regions}
    candidate_evidence = list(selected_regions) + [
        region for region in summary.get('selectable_docking_boxes') or []
        if str(region.get('box') or region.get('box_name') or '') not in selected_paths
        and region.get('site_group')
    ]
    overview_sites = overview_evidence(diagnostics, retained_for_display, ligand_site_groups, candidate_evidence)
    visible_indices = overview_visible_indices(retained_for_display, overview_sites, selected_regions)
    panel_a_rendered = plot_evidence_overview(diagnostics, retained_for_display, overview_sites, panel_a, visible_indices)
    if panel_a_rendered:
        outputs.append(str(panel_a))
    panel_b = report / "cavity_panel_B_structure.png"
    selected_ligand_site_group = (
        (pocket_evidence.get("user_evidence_decision") or {}).get("selected_ligand_site_group")
    )
    if selected_ligand_site_group:
        selected_groups, _ = split_ligand_site_groups([selected_ligand_site_group])
        selected_ligand_site_group = selected_groups[0] if selected_groups else None
    single_ligand_site_group = (
        selected_ligand_site_group or ligand_site_groups[0]
        if len(ligand_site_groups) == 1 else None
    )
    unmatched_ligand_site_groups = [
        group for group in ligand_site_groups
        if (group.get("site_identity") or {}).get(
            "is_separate_from_predicted_pocket",
            group.get("site_identity", {}).get("is_separate_from_fpocket", pocket_recovery(group).get("status") == "not_recovered"),
        )
    ]
    panel_b_rendered = render_evidence_overview(diagnostics, retained_for_display, overview_sites, panel_b,
                                                report / 'cavity_panel_B_structure.pse', pymol,
                                                receptor_path=recorded_receptor, visible_indices=visible_indices)
    if panel_b_rendered:
        outputs.append(str(panel_b))
    # Keep selected regions and their boxes in a dedicated figure so the
    # multi-pocket comparison remains unobstructed.
    selected_box = report / "cavity_selected_box.png"
    fpocket_selected_configs = [
        config for config in selected_configs
        if __import__("re").search(r"pocket\d+", str(config), __import__("re").I)
    ]
    additional_selected_regions = [region for region in selected_regions
        if not __import__('re').search(r'pocket\d+', str(region.get('box_name') or region.get('box') or ''), __import__('re').I)]
    selected_evidence_group = None
    if selected_configs:
        selected_match = __import__("re").search(
            r"pocket(\d+)", str(selected_configs[0]), __import__("re").I,
        )
        if selected_match:
            selected_number = selected_match.group(1)
            selected_evidence_group = next((
                group for group in ligand_site_groups
                if str(pocket_recovery(group).get("best_matching_pocket"))
                == selected_number
            ), None)
    if (fpocket_selected_configs or additional_selected_regions) and render_all_cavity_candidates(
        diagnostics, selected_config, selected_box, report / "cavity_selected_box.pse",
        pymol, fpocket_selected_configs, display_site_numbers, selected_only=True,
        ligand_site_group=selected_evidence_group, show_labels=False,
        additional_selected_regions=additional_selected_regions, receptor_path=recorded_receptor,
    ):
        outputs.append(str(selected_box))
    elif selected_box.is_file():
        # A ligand-defined site is already visualized with its aligned ligands,
        # complete box, and corresponding fpocket surfaces. A receptor-only
        # placeholder is both redundant and scientifically uninformative.
        selected_box.unlink()
    combined = report / "cavity_panels_AB.png"
    if panel_a_rendered and panel_b_rendered:
        ligand_markers = any(obs['path'] and obs['path'].is_file()
                             for site in overview_sites for obs in site['observations'])
        ligand_rings = any(site['label'] == f'P{index}' and pocket_score(retained_for_display[index-1])
                           not in (None, '', 'NA') for site in overview_sites for index in visible_indices)
        combine_evidence_panels(panel_a, panel_b, combined, retained_for_display, visible_indices,
                                ligand_markers=ligand_markers)
        (report / 'cavity_panels_AB.metadata.json').write_text(json.dumps({
            'figure_style': 'ligand_evidence_v3', 'visible_pockets': visible_indices,
            'ligand_rings': ligand_rings, 'ligand_markers': ligand_markers,
            'sha256': hashlib.sha256(combined.read_bytes()).hexdigest(),
        }, indent=2) + '\n')
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
        if build_pocket_evidence_figure(diagnostics, config_name, evidence_figure, pymol, pocket_color,
                                        receptor_path=recorded_receptor):
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
        # Clustering granularity is not the experimental recovery threshold.
        "--cluster-rmsd", "1.5",
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
    return next((mol for mol in read_sdf(path, removeHs=False) if mol), None)


def same_retained_pose(first_path, second_path):
    """Require matching chemistry and receptor-frame geometry, without fitting."""
    from rdkit import Chem
    try:
        a, b = read_molecule(first_path), read_molecule(second_path)
        if a is None or b is None:
            return False
        if Chem.MolToSmiles(Chem.RemoveHs(a)) != Chem.MolToSmiles(Chem.RemoveHs(b)):
            return False
        distance = rmsd_between(a, b)
        return math.isfinite(distance) and distance < .001
    except (OSError, RuntimeError, ValueError):
        return False


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
    molecules = list(read_sdf(all_poses_path, removeHs=False))
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
        writer = sdf_writer(destination)
        writer.write(molecule)
        writer.close()
        paths.append(destination)
    return paths


def control_pose_points(analysis, reference):
    """Evaluate every retained control pose, never just cluster representatives."""
    import math
    from rdkit import Chem

    inventory = analysis / "pose_inventory.csv"
    poses = analysis / "all_poses.sdf"
    if not inventory.is_file() or not poses.is_file():
        raise ValueError("All-pose control figure requires retained inventory and all_poses.sdf")
    with inventory.open(newline="") as handle:
        records = list(csv.DictReader(handle))
    molecules = list(read_sdf(poses, removeHs=False))
    points, excluded, seen = [], [], set()
    for row in records:
        try:
            pose_id = int(row["pose_id"])
            if pose_id in seen:
                raise ValueError(f"Duplicate retained pose ID: {pose_id}")
            seen.add(pose_id)
            if not 1 <= pose_id <= len(molecules) or molecules[pose_id - 1] is None:
                raise ValueError("Unreadable or missing retained pose geometry")
            score = float(row["energy_kcal_per_mol"])
            rmsd = float(rmsd_between(reference, molecules[pose_id - 1]))
            if not math.isfinite(score) or not math.isfinite(rmsd):
                raise ValueError("Non-finite score or experimental RMSD")
            points.append({"pose_id": pose_id, "cluster_id": row.get("cluster_id", ""),
                           "seed": row.get("seed", ""), "conformer": row.get("conformer", ""),
                           "model": row.get("model", ""), "energy_kcal_per_mol": score,
                           "rmsd_angstrom": rmsd})
        except (KeyError, TypeError, ValueError, RuntimeError) as error:
            excluded.append({"pose_id": row.get("pose_id"), "cluster_id": row.get("cluster_id"), "reason": str(error)})
    return points, {"inventory_count": len(records), "plotted_count": len(points), "excluded": excluded}


def control_cluster_points(analysis, reference):
    """One point per cluster: independent energy and crystal-RMSD minima.

    A point summarizes a cluster, not necessarily one realizable pose. Retain
    both winning pose IDs and each winner's other metric in the audit table.
    """
    from collections import defaultdict

    poses, audit = control_pose_points(analysis, reference)
    groups = defaultdict(list)
    invalid_clusters = {str(row.get("cluster_id", "")) for row in audit["excluded"]}
    for pose in poses:
        try:
            cid = int(pose["cluster_id"])
            if cid < 1:
                raise ValueError("Cluster ID must be positive")
            groups[cid].append(pose)
        except (TypeError, ValueError) as error:
            audit["excluded"].append({"pose_id": pose["pose_id"], "cluster_id": pose["cluster_id"],
                                      "reason": f"Invalid cluster assignment: {error}"})
    points = []
    for cid, members in groups.items():
        # Missing members could contain either minimum. Do not falsely claim
        # an exact cluster minimum from only its evaluable members.
        if str(cid) in invalid_clusters:
            continue
        energy_pose = min(members, key=lambda pose: (pose["energy_kcal_per_mol"], pose["pose_id"]))
        rmsd_pose = min(members, key=lambda pose: (pose["rmsd_angstrom"], pose["pose_id"]))
        points.append({"cluster_id": cid, "pose_count": len(members),
            "best_energy_kcal_per_mol": energy_pose["energy_kcal_per_mol"],
            "rmsd_angstrom": rmsd_pose["rmsd_angstrom"],
            "lowest_energy_pose_id": energy_pose["pose_id"],
            "lowest_energy_pose_rmsd_angstrom": energy_pose["rmsd_angstrom"],
            "lowest_rmsd_pose_id": rmsd_pose["pose_id"],
            "lowest_rmsd_pose_energy_kcal_per_mol": rmsd_pose["energy_kcal_per_mol"],
            "minima_from_same_pose": energy_pose["pose_id"] == rmsd_pose["pose_id"]})
    points.sort(key=lambda point: (point["best_energy_kcal_per_mol"], point["cluster_id"]))
    for rank, point in enumerate(points, 1):
        point["energy_rank"] = rank
    closest_pose = min(poses, key=lambda pose: (pose["rmsd_angstrom"], pose["energy_kcal_per_mol"], pose["pose_id"])) if poses else None
    audit.update(closest_to_crystal_pose=closest_pose,
                 evaluated_pose_count=len(poses), plotted_count=len(points),
                 plotted_pose_count=sum(point["pose_count"] for point in points),
                 excluded_cluster_ids=sorted(invalid_clusters),
                 plot_scope="all_retained_control_clusters_independent_minima",
                 point_meaning="one cluster; minimum energy and minimum experimental RMSD may come from different poses")
    return points, audit


def plot_control_clusters(analysis, output, reference_sdf, control_label):
    """Plot cluster minima; leave all-pose plotting as a separate diagnostic."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    reference = read_molecule(reference_sdf)
    if reference is None:
        return False
    try:
        points, audit = control_cluster_points(analysis, reference)
    except (ValueError, OSError) as error:
        print(f"Report figure warning: {error}", file=sys.stderr)
        return False
    if not points:
        return False
    displayed = points[:20]  # Top twenty cluster summaries plus the actual closest pose.
    closest_pose = audit["closest_to_crystal_pose"]
    clustering = read_json(analysis / "clustering_manifest.json")
    cutoff = clustering.get("cluster_rmsd_angstrom")
    top = displayed[0]
    displayed_ids = {point["cluster_id"] for point in displayed}
    for point in points:
        point["displayed_in_plot"] = point["cluster_id"] in displayed_ids
    audit.update(reference=str(Path(reference_sdf).resolve()),
        rmsd_method="symmetry-aware heavy-atom RMSD in receptor frame; no fitting",
        cluster_rmsd_angstrom=cutoff, lowest_energy_cluster_id=top["cluster_id"],
        closest_to_crystal_pose_id=closest_pose["pose_id"],
        highlight_scope="three lowest-energy displayed clusters",
        highlight_style="energy_rank_colors",
        lowest_rmsd_highlight=None,
        highlighted_cluster_ids=[point["cluster_id"] for point in displayed[:3]],
        point_size="70 + 8 * pose_count; marker area in points squared",
        all_evaluable_cluster_count=len(points),
        all_evaluable_cluster_pose_count=audit["plotted_pose_count"],
        plotted_count=len(displayed), plotted_pose_count=sum(point["pose_count"] for point in displayed),
        plotted_cluster_ids=[point["cluster_id"] for point in displayed],
        plot_scope="top20_control_clusters_independent_minima",
        selection="top 20 clusters by lowest cluster energy, then cluster ID",
        csv_scope="all_evaluable_control_clusters",
        score_cutoff=None, rmsd_cutoff=None, cluster_limit=20)
    fig, ax = plt.subplots(figsize=(11, 6.5))
    # Preserve the original cluster presentation: energy on x, RMSD on y,
    # circle area tracks pose population, and only energy rank sets color.
    xs = [point["best_energy_kcal_per_mol"] for point in displayed]
    ys = [point["rmsd_angstrom"] for point in displayed]
    colors = list(TOP_COLORS[:min(3, len(displayed))]) + ["#b8c0c8"] * max(0, len(displayed) - 3)
    closest_fill = next((color for point, color in zip(displayed[:3], TOP_COLORS)
                         if str(point["cluster_id"]) == str(closest_pose["cluster_id"])), "#b8c0c8")
    audit["closest_pose_marker_fill"] = closest_fill
    audit["closest_pose_marker_outline"] = "#008a45"
    audit["closest_pose_marker_white_gap_points"] = 3.0
    ax.scatter(xs, ys, s=[70 + 8 * point["pose_count"] for point in displayed],
               c=colors, marker="o", edgecolor="black", linewidth=.7, alpha=.9)
    ax.set_xlabel("Estimated binding energy (kcal/mol)", fontsize=13)
    ax.set_ylabel("Experimental RMSD (Å)", fontsize=13)
    ax.set_title(f"{control_label}: pose recovery", fontsize=16, pad=15)
    x_range = xs
    xpad, ypad = max(.15, (max(x_range) - min(x_range)) * .07), max(.25, max(ys) * .04)
    ax.set_xlim(min(x_range) - xpad, max(x_range) + xpad)
    ax.set_ylim(-ypad, max(ys) + ypad)
    ax.set_yticks([tick for tick in ax.get_yticks() if tick >= 0])
    ax.axhline(0, color=".45", linewidth=.8, zorder=0)
    ax.grid(alpha=.2)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=12)
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], marker="o", linestyle="none", markerfacecolor=color,
                      markeredgecolor="black", markersize=8,
                      label=f"#{rank}: C{point['cluster_id']}")
               for rank, (point, color) in enumerate(zip(displayed[:3], TOP_COLORS), 1)]
    legend_title = "Top 20 clusters by energy"
    if isinstance(cutoff, (int, float)):
        legend_title += f" · {cutoff:g} Å clustering"
    ax.legend(handles=handles,
              loc="upper left", bbox_to_anchor=(0, -.18),
              ncol=4, frameon=False, fontsize=11, title=legend_title, title_fontsize=11)
    fig.text(.5, .075, "Cluster circle size = number of poses", ha="center", fontsize=11)
    fig.subplots_adjust(left=.13, right=.97, top=.88, bottom=.32)
    fig.text(.5, .02,
             "Each circle shows the cluster's minimum energy and minimum experimental RMSD;\n"
             "these values may come from different poses within the same cluster.",
             ha="center", va="bottom", fontsize=11, color="#333333")
    fig.savefig(output, dpi=240)
    plt.close(fig)
    with output.with_suffix(".csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(points[0]))
        writer.writeheader()
        writer.writerows(points)
    output.with_suffix(".json").write_text(json.dumps(audit, indent=2) + "\n")
    return True


def plot_control_poses(analysis, output, reference_sdf, control_label):
    """Full retained-pose landscape with independent sampling/ranking markers."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    reference = read_molecule(reference_sdf)
    if reference is None:
        return False
    try:
        points, audit = control_pose_points(analysis, reference)
    except (ValueError, OSError) as error:
        print(f"Report figure warning: {error}", file=sys.stderr)
        return False
    if not points:
        return False
    top = min(points, key=lambda point: point["energy_kcal_per_mol"])
    best = min(points, key=lambda point: point["rmsd_angstrom"])
    audit.update(plot_scope="all_retained_control_poses", reference=str(Path(reference_sdf).resolve()),
                 rmsd_method="symmetry-aware heavy-atom RMSD in receptor frame; no fitting",
                 lowest_score_pose_id=top["pose_id"], closest_to_crystal_pose_id=best["pose_id"],
                 score_cutoff=None, rmsd_cutoff=None, cluster_limit=None)
    fig, ax = plt.subplots(figsize=(11, 6.5))
    ax.scatter([point["energy_kcal_per_mol"] for point in points],
               [point["rmsd_angstrom"] for point in points],
               s=22, c="#a1aab3", alpha=.5, edgecolor="none", label=f"All retained poses ({len(points)})")
    ax.scatter(top["energy_kcal_per_mol"], top["rmsd_angstrom"], s=78, marker="o",
               c="#d62728", edgecolor="black", zorder=4,
               label=f"Lowest energy: {top['energy_kcal_per_mol']:.2f} kcal/mol; {top['rmsd_angstrom']:.2f} Å")
    ax.scatter(best["energy_kcal_per_mol"], best["rmsd_angstrom"], s=(math.sqrt(78)+.7+6+1.8)**2,
               facecolors="white", edgecolors="#008a45", linewidths=1.8, zorder=5)
    ax.scatter(best["energy_kcal_per_mol"], best["rmsd_angstrom"], s=78,
               c="#d62728" if best is top else "#b8c0c8", edgecolor="black", linewidth=.7, zorder=6)
    from matplotlib.lines import Line2D
    handles, labels = ax.get_legend_handles_labels()
    handles.append(Line2D([], [], linestyle="none", marker="o", markerfacecolor="white",
                          markeredgecolor="#008a45", markeredgewidth=1.8, markersize=12))
    labels.append(f"Global lowest experimental RMSD: {best['rmsd_angstrom']:.2f} Å; {best['energy_kcal_per_mol']:.2f} kcal/mol")
    ax.set_xlabel("Estimated binding energy (kcal/mol)", fontsize=13)
    ax.set_ylabel(f"Experimental {control_label} heavy-atom RMSD (Å)\nReceptor frame; no fitting", fontsize=12)
    ax.set_title(f"{control_label}: all-pose diagnostic", fontsize=16)
    # Place the legend outside the data area so no pose is obscured by it.
    ax.legend(handles, labels, loc="upper left", bbox_to_anchor=(0, -.17), frameon=False, fontsize=11)
    x = [point["energy_kcal_per_mol"] for point in points]
    y = [point["rmsd_angstrom"] for point in points]
    xpad = max(.15, (max(x)-min(x))*.07)
    ypad = max(.25, max(y)*.07)
    ax.set_xlim(min(x)-xpad, max(x)+xpad)
    ax.set_ylim(-ypad, max(y)+ypad)
    ax.set_yticks([tick for tick in ax.get_yticks() if tick >= 0])
    ax.axhline(0, color=".5", linewidth=.8, zorder=0)
    ax.tick_params(labelsize=12)
    ax.grid(alpha=.2)
    if audit["excluded"]:
        fig.text(.14, .015, f"{len(audit['excluded'])} unevaluable records excluded; reasons retained in figure audit.", fontsize=10)
    fig.tight_layout(rect=[.08, .10, .99, .98])
    fig.savefig(output, dpi=240)
    plt.close(fig)
    with output.with_suffix(".csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[*points[0], "lowest_score", "closest_to_crystal"])
        writer.writeheader()
        for point in points:
            writer.writerow(dict(point, lowest_score=point is top, closest_to_crystal=point is best))
    output.with_suffix(".json").write_text(json.dumps(audit, indent=2) + "\n")
    return True


def plot_clusters(analysis, output, reference_sdf=None, control_label=None):
    """Plot retained pose clusters with score, population, and structural distance."""
    import math
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    if control_label:
        # Never label distance from another docked pose as crystal recovery.
        if not reference_sdf:
            print("Report figure warning: experimental reference missing for control landscape", file=sys.stderr)
            return False
        return plot_control_clusters(analysis, output, reference_sdf, control_label)

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
    # Preserve global energy rank across chemical states. A missing RMSD has
    # its own categorical strip, never a fabricated distance or a new rank.
    valid_energy = [i for i, value in enumerate(energies) if math.isfinite(value)]
    if len(valid_energy) != len(entries):
        print("Report figure warning: nonfinite cluster energies prevent a complete ranked plot", file=sys.stderr)
        return False
    evaluated = [i for i, value in enumerate(rmsds) if math.isfinite(value)]
    unavailable = [i for i, value in enumerate(rmsds) if not math.isfinite(value)]
    if not evaluated:
        return False
    sizes = [70 + int(row.get("pose_count", 1)) * 8 for row, _ in entries]
    colors = [TOP_COLORS[int(row.get('energy_rank', i + 1)) - 1]
              if 1 <= int(row.get('energy_rank', i + 1)) <= 3 else '#b8c0c8'
              for i, (row, _) in enumerate(entries)]
    if unavailable:
        fig, (ax, unknown_ax) = plt.subplots(2, 1, sharex=True, figsize=(10.4, 7.7),
            gridspec_kw={'height_ratios': [5, 1], 'hspace': .09})
        unknown_ax.scatter([energies[i] for i in unavailable], [0] * len(unavailable),
                          s=[sizes[i] for i in unavailable], c=[colors[i] for i in unavailable],
                          edgecolor='black', linewidth=.7, alpha=.9)
        unknown_ax.set_ylim(-1, 1)
        unknown_ax.set_yticks([])
        unknown_ax.set_ylabel('RMSD\nunavailable', fontsize=11)
        unknown_ax.set_xlabel('Estimated binding energy (kcal/mol)', fontsize=19)
        unknown_ax.tick_params(labelsize=17)
        unknown_ax.grid(axis='x', alpha=.25)
        unknown_ax.text(.99, .88, 'N/A strip: no RMSD assigned', transform=unknown_ax.transAxes,
                        ha='right', va='top', fontsize=10)
    else:
        fig, ax = plt.subplots(figsize=(10.4, 7.7))
        ax.set_xlabel('Estimated binding energy (kcal/mol)', fontsize=19)
    ax.scatter([energies[i] for i in evaluated], [rmsds[i] for i in evaluated],
               s=[sizes[i] for i in evaluated], c=[colors[i] for i in evaluated],
               edgecolor='black', linewidth=.7, alpha=.9)
    ax.set_ylabel("No-fit heavy-atom RMSD (Å)", fontsize=19)
    ax.annotate(
        "Point size indicates cluster population. Gray points are other clusters.",
        xy=(.5, 1), xycoords="axes fraction", xytext=(0, 9),
        textcoords="offset points", ha="center", va="bottom",
        fontsize=13, color="#465560",
    )
    # RMSD cannot be negative, but a small display margin below zero keeps an
    # exact 0 A reference point fully visible instead of clipping it against
    # the lower plot boundary. Keep the labeled ticks scientifically valid.
    max_rmsd = max(rmsds[i] for i in evaluated)
    margin = max(.25, max_rmsd * .045)
    upper = max_rmsd + margin
    ax.set_ylim(-margin, upper)
    ax.set_yticks([tick for tick in ax.get_yticks() if 0 <= tick <= upper])
    ax.axhline(0, color="0.45", linewidth=0.8, zorder=0)
    ax.tick_params(labelsize=17)
    ax.grid(alpha=.25)
    fig.subplots_adjust(left=.14, right=.98, bottom=.10, top=.94, hspace=.12)
    fig.savefig(output, dpi=240)
    plt.close(fig)
    # Keep all ranked entries, including the explicitly unvalued N/A strip.
    with output.with_suffix(".csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=[
            "energy_rank", "cluster_id", "best_energy_kcal_per_mol",
            "rmsd_angstrom", "pose_count", "rmsd_status",
        ])
        writer.writeheader()
        for (row, _), rmsd in zip(entries, rmsds):
            writer.writerow({
                "energy_rank": row.get("energy_rank", ""),
                "cluster_id": row.get("cluster_id", ""),
                "best_energy_kcal_per_mol": row.get("best_energy_kcal_per_mol", ""),
                "rmsd_angstrom": f"{rmsd:.6f}" if math.isfinite(rmsd) else 'NA',
                "pose_count": row.get("pose_count", ""),
                "rmsd_status": 'evaluated' if math.isfinite(rmsd) else 'unavailable',
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
    image.crop(bbox).save(path, dpi=(220, 220))


def render_poseedit_plip2d(interactions, ligand_sdf, output, ligand_id=None, alignment_reference=None):
    """Build the current interaction diagram from retained PLIP contacts."""
    from docking_universal.runtime_inventory import discover_poseedit_runtime
    from docking_universal.poseedit_renderer import LAYOUT_REVISION

    report_xml = interactions / "report.xml"
    receptor = first(interactions, ["complex_protonated.pdb", "plipfixed*.pdb", "*.pdb"])
    renderer = Path(__file__).with_name("docking-universal-render-poseedit.py")
    if not report_xml.is_file() or not ligand_sdf.is_file() or not receptor or not renderer.is_file():
        return False
    runtime = discover_poseedit_runtime()
    if runtime["status"] != "available":
        (interactions / "plip2d.log").write_text(
            "Approved PoseEdit-style renderer unavailable: " + runtime["detail"] + "\n"
        )
        return False
    existing = read_json(output.with_suffix(".manifest.json"))
    dependencies = (report_xml, ligand_sdf, receptor, renderer)
    if (output.is_file() and existing.get("renderer_policy") == "approved-poseedit-local-v1"
            and existing.get("layout_revision") == LAYOUT_REVISION
            and existing.get('alignment_reference_sha256') == (hashlib.sha256(alignment_reference.read_bytes()).hexdigest() if alignment_reference else None)
            and output.stat().st_mtime >= max(path.stat().st_mtime for path in dependencies)):
        return True
    components = runtime["components"]
    command = [
        sys.executable, str(renderer), "--ligand", str(ligand_sdf),
        "--receptor", str(receptor), "--plip-xml", str(report_xml),
        "--output", str(output), "--scale", "3",
        "--renderer-policy", "approved-poseedit-local-v1",
        "--node", components["node"]["path"], "--chrome", components["chrome"]["path"],
    ]
    if ligand_id:
        command.extend(("--ligand-id", str(ligand_id)))
    if alignment_reference:
        command.extend(("--alignment-reference", str(alignment_reference)))
    result = subprocess.run(command, text=True, capture_output=True)
    base_command = list(command)
    previous_spacing = 15
    for spacing in (20, 25, 30):
        if not result.returncode or 'collision-free unambiguous layout' not in result.stderr:
            break
        # A bounded display-only retry, not different PLIP calls or chemistry.
        # Keep the failed attempt and its audits rather than hiding its failure.
        (interactions / f'plip2d.approved-spacing-{previous_spacing}.log').write_text(
            f'RETURN CODE: {result.returncode}\n{result.stdout}\n{result.stderr}')
        for suffix in ('.collision-audit.json', '.packing-audit.json', '.crop-audit.json'):
            audit = Path(str(output) + suffix)
            if audit.is_file():
                shutil.copy2(audit, Path(str(output) + f'.spacing-{previous_spacing}' + suffix))
        command = base_command + ['--ligand-spacing', str(spacing)]
        result = subprocess.run(command, text=True, capture_output=True)
        previous_spacing = spacing
    (interactions / "plip2d.log").write_text(
        f"RENDERER: approved-poseedit-local-v1\nCOMMAND: {' '.join(command)}\n"
        f"RETURN CODE: {result.returncode}\n\nSTDOUT:\n{result.stdout}\n\nSTDERR:\n{result.stderr}\n"
    )
    if result.returncode != 0 or not output.is_file():
        print(f"Report figure warning: approved local interaction renderer failed for {interactions}", file=sys.stderr)
        return False
    return read_json(output.with_suffix(".manifest.json")).get("renderer_policy") == "approved-poseedit-local-v1"


def combine_docking_cluster_panels(panel_a, panel_b, output):
    """Use the report width for paired docking panels and a shared cluster key."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from PIL import Image, ImageChops

    panels = []
    for path in (panel_a, panel_b):
        with Image.open(path) as source:
            layer = source.convert("RGBA")
        white = Image.new("RGBA", layer.size, "white")
        picture = Image.alpha_composite(white, layer).convert("RGB")
        bounds = ImageChops.difference(picture, white.convert("RGB")).getbbox()
        panels.append(picture.crop(bounds) if bounds else picture)

    with panel_a.with_suffix(".csv").open(newline="") as source:
        top_clusters = [row for row in csv.DictReader(source)
                        if row["energy_rank"] in ("1", "2", "3")]

    fig = plt.figure(figsize=(16, 8.85), facecolor="white")
    panel_bottoms = []
    for picture, left, width, letter, title in (
        (panels[0], .022, .495, "A", "Docked pose clusters"),
        (panels[1], .555, .425, "B", "Cluster representatives"),
    ):
        draw_report_panel_heading(fig, left, .941, letter, title, printed_scale=7 / 16)
        axes = fig.add_axes((left, .132, width, .785), anchor="C")
        axes.imshow(picture)
        axes.set_axis_off()
        axes.apply_aspect()
        panel_bottoms.append(axes.get_position().y0)

    legend_top = min(panel_bottoms) - .006
    for row in top_clusters:
        rank = int(row["energy_rank"])
        x = .022 + (rank - 1) * .33
        rmsd = row["rmsd_angstrom"]
        distance = "RMSD N/A" if rmsd == "NA" else f"{float(rmsd):.2f} Å RMSD"
        fig.text(x, legend_top, "●", color=TOP_COLORS[rank - 1], fontsize=15, va="top")
        fig.text(x + .021, legend_top, f"Cluster {row['cluster_id']}",
                 fontsize=16, weight="bold", va="top")
        fig.text(x + .021, legend_top - .040, f"{float(row['best_energy_kcal_per_mol']):.2f} kcal/mol  ·  {distance}",
                 fontsize=15, va="top")

    from matplotlib.transforms import Bbox

    fig.savefig(output, dpi=240, facecolor="white", bbox_inches=Bbox.from_extents(0, (legend_top - .095) * 8.85, 16, 8.85))
    plt.close(fig)
    return True


def combine_panels(panel_a, panel_b, output, control=False, panel_b_legend=(), *, docking_clusters=False):
    """Compose labeled report panels without changing scientific content."""
    if docking_clusters:
        return combine_docking_cluster_panels(panel_a, panel_b, output)

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
    left_w = 1880 if control else 1800
    legend_col_w = 0 if control else 480
    right_w = canvas_w - 2 * margin - gap - left_w - legend_col_w - (0 if control else gap)

    def fit(image, width, height):
        ratio = min(width / image.width, height / image.height)
        return image.resize((int(image.width * ratio), int(image.height * ratio)), Image.Resampling.LANCZOS)

    a = fit(a, left_w, canvas_h - 2 * margin - label_h)
    b = fit(
        b, right_w - 80,
        a.height if control else 1600,
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
    b_y = margin + label_h + (group_height - b.height) // 2
    if control:
        # Align the visible panel contents, not their raster frames. Plot A
        # retains Matplotlib margins while molecular panel B is tightly
        # cropped, so a fixed pixel offset cannot remain correct across runs.
        white_a = Image.new("RGB", a.size, "white")
        white_b = Image.new("RGB", b.size, "white")
        a_bounds = ImageChops.difference(a, white_a).getbbox()
        b_bounds = ImageChops.difference(b, white_b).getbbox()
        if a_bounds and b_bounds:
            a_center = a_y + (a_bounds[1] + a_bounds[3]) / 2
            b_center = b_y + (b_bounds[1] + b_bounds[3]) / 2
            b_y += round(a_center - b_center)
    canvas.paste(a, (a_x, a_y))
    canvas.paste(b, (b_x, b_y))
    draw = ImageDraw.Draw(canvas)
    font_path = Path("/System/Library/Fonts/Helvetica.ttc")
    font = ImageFont.truetype(str(font_path), 80) if font_path.is_file() else ImageFont.load_default()
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
            # Anchor the legend to the visible molecular panel.  Positioning it
            # after the full reserved panel slot created a large meaningless
            # white band whenever the tightly cropped structure was narrow.
            else b_x + b.width + 35
        )
        legend_y = 18 if control else margin + label_h + (group_height - legend_h) // 2
        draw.rounded_rectangle(
            (legend_x, legend_y, legend_x + legend_w, legend_y + legend_h),
            radius=16, fill="white", outline="#777777", width=3,
        )
        legend_heading = (
            "Filled P = fpocket surface   |   outline = proposed search box"
            if control else "Filled: predicted pocket\nOutline: proposed box"
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
        # Retain the complete labeled snapshot. Filling a wider panel with
        # ImageOps.fit crops top/bottom callouts even though the PyMOL PNG is
        # intact. White-only trimming above keeps the framing compact.
        inner_w = int((cell_w - 72) * 0.92)
        # Reserve a clear header inside the border for the panel letter.
        header_h = 260
        inner_h = int((image_h - header_h - 48) * 0.92)
        snapshot = ImageOps.contain(
            snapshot, (inner_w, inner_h),
            method=Image.Resampling.LANCZOS,
        )
        frame = Image.new("RGB", (cell_w, image_h), "white")
        frame.paste(snapshot, ((cell_w - snapshot.width) // 2,
                               header_h + (image_h - header_h - snapshot.height) // 2))
        frame = ImageOps.expand(frame, border=32, fill="white")
        frame_draw = ImageDraw.Draw(frame)
        frame_draw.rounded_rectangle((16, 16, frame.width - 17, frame.height - 17),
                                     radius=120, outline=color, width=32)
        canvas.paste(frame, (x, y))
        draw.text((x + 144, y + 100), panel_letters[index], fill=color, font=label_font)
        score = row.get("best_energy_kcal_per_mol", "NA")
        caption = f"Energy rank {row.get('energy_rank', index + 1)} | Cluster {row.get('cluster_id', 'NA')} | Energy {score} kcal/mol"
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
    # Use the exact experimental ligand recorded by PLIP, including its
    # chain and residue number; complexes can contain multiple copies.
    ligand_filter = read_json(experimental / "run_manifest.json").get("ligand_filter") or {}
    identity = [str(ligand_filter.get(key) or "").strip() for key in ("resname", "chain", "position")]
    experimental_id = ":".join(identity) if all(identity) else None
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
        ("experimental", experimental, experimental_sdf, experimental_id),
        ("top_ranked", top, top_sdf, "UNL:Z:1"),
        ("lowest_rmsd", best, best_sdf, "UNL:Z:1"),
    ]


def build_related_control_diagrams(study, control):
    """Regenerate exact retained control views using the current display policy.

    This writes only under the new report's own folder. It verifies the prior
    pose-view hashes and reuses its PLIP XML; no docking or PLIP job is rerun.
    """
    from docking_universal.pose_visuals import read_pose_view
    from docking_universal.poseedit_renderer import LAYOUT_REVISION
    report = study / 'report'
    cache = report / 'related_control_diagram_inputs'
    outputs = []
    reference_view = read_pose_view(control / 'report' / 'control_experimental_plip2d.png')
    if not reference_view:
        return []
    alignment_reference = reference_view['ligand']
    for name in ('experimental', 'energy_rank_1', 'lowest_rmsd'):
        original = control / 'report' / f'control_{name}_plip2d.png'
        view = read_pose_view(original)
        if not view:
            return []
        sources = view
        interaction_dir = sources['interactions'].parent
        ligand_id = 'UNL:Z:1'
        if name == 'experimental':
            identity = read_json(interaction_dir / 'run_manifest.json').get('ligand_filter') or {}
            values = [str(identity.get(key) or '').strip() for key in ('resname', 'chain', 'position')]
            if not all(values):
                return []
            ligand_id = ':'.join(values)
        snapshot = cache / name
        snapshot.mkdir(parents=True, exist_ok=True)
        for source, dest in ((sources['interactions'], snapshot / 'report.xml'),
                             (sources['receptor'], snapshot / 'complex_protonated.pdb')):
            if not dest.is_file() or hashlib.sha256(dest.read_bytes()).digest() != hashlib.sha256(source.read_bytes()).digest():
                shutil.copy2(source, dest)
        output = report / f'related_control_{name}_plip2d.png'
        if not render_poseedit_plip2d(snapshot, sources['ligand'], output, ligand_id=ligand_id,
                                      alignment_reference=alignment_reference):
            return []
        outputs.append(str(output))
    (report / 'related_control_diagrams.json').write_text(json.dumps({
        'schema': 'docking-universal-related-control-diagrams-v3',
        'layout_revision': LAYOUT_REVISION,
        'outputs': [{'path': path, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()} for path in outputs],
    }, indent=2) + '\n')
    return outputs


def build_related_control_3d(study, control, pymol):
    """Render the same verified experimental, energy, and RMSD poses in 3D."""
    from docking_universal.pose_visuals import read_pose_view
    if not pymol:
        return []
    report = study / 'report'
    outputs = []
    renderer = Path(__file__).with_name('docking-universal-render3d.py')
    palette = {'magenta': '#b638a0', 'red': '#d62728', 'marine': '#1f77b4', 'gold': '#d9a400'}
    for name in ('experimental', 'energy_rank_1', 'lowest_rmsd'):
        view = read_pose_view(control / 'report' / f'control_{name}_plip2d.png')
        if not view:
            return []
        scenes = sorted(view['interactions'].parent.glob('*_plip_all_in_one.pml'))
        if len(scenes) != 1:
            return []
        output = report / f'related_control_{name}_3d.png'
        result = subprocess.run([sys.executable, str(renderer), str(scenes[0]), '--out', str(output),
                                 '--contact-residue-labels', '--ligand-color', palette.get(view['ligand_color'], '#777777'),
                                 '--pymol', str(pymol)], capture_output=True, text=True)
        if result.returncode or not output.is_file():
            return []
        outputs.append(str(output))
    (report / 'related_control_3d.json').write_text(json.dumps({
        'schema': 'docking-universal-control-comparison-3d-v2',
        'outputs': [{'path': path, 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()} for path in outputs],
    }, indent=2) + '\n')
    return outputs


def build_control_figures(control, protocol_path, pymol, plip):
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

    receptor = analysis / "receptor.pdb"
    panel_b = report / "control_panel_B_overlay.png"
    ligands, colors, overlay_audit = control_overlay_poses(analysis, panel_a, report)
    overlay_rendered = False
    if ligands:
        if render_overlay(receptor, [reference, *ligands], ["magenta", *colors], panel_b,
                          report / "control_panel_B_overlay.pse", pymol):
            overlay_rendered = True
            panel_b.with_suffix(".manifest.json").write_text(json.dumps(overlay_audit, indent=2) + "\n")
    combined = report / "control_panels_AB.png"
    if overlay_rendered:
        combine_panels(panel_a, panel_b, combined, control=True)
    outputs = [str(panel_a)] + ([str(panel_b), str(combined)] if overlay_rendered and combined.is_file() else [])
    for label, interactions, ligand_sdf, ligand_id in ensure_control_interactions(control, protocol, protocol_path, plip):
        if label not in ("experimental", "lowest_rmsd"):
            continue
        if not interactions or not ligand_sdf:
            continue
        diagram = report / f"control_{label}_plip2d.png"
        # Source identity, not energy/rank coincidence, connects the diagram to
        # the exact actual pose in the global landscape and 3D overlay.
        identity = next((item for item, path in zip(overlay_audit.get("poses", []), ligands)
                         if same_retained_pose(ligand_sdf, path)), None)
        if render_poseedit_plip2d(interactions, ligand_sdf, diagram, ligand_id=ligand_id):
            color = "magenta" if label == "experimental" else identity["color"] if identity else "gray70"
            title = {"experimental": "Experimental control ligand", "top_ranked": "Lowest-energy control pose",
                     "lowest_rmsd": "Global lowest experimental-RMSD pose"}[label]
            write_pose_view(diagram, ligand_sdf, receptor, interactions / "report.xml", title, color,
                            coordinate_kind="experimental" if label == "experimental" else "docked",
                            role=label, pose_id=identity["pose_id"] if identity else None)
            outputs.append(str(diagram))
    # Preserve the experimental/lowest-energy/closest A/B/C presentation, and
    # also retain exact individual diagrams for every top-three representative.
    with panel_a.with_suffix(".csv").open(newline="") as source:
        selected_rows = list(csv.DictReader(source))[:3]
    for rank, row in enumerate(selected_rows, 1):
        cluster = analysis / f"cluster_{int(row['cluster_id']):03d}"
        pose_id = int(row["lowest_energy_pose_id"])
        ligand_sdf = report / f"control_overlay_pose_{pose_id:04d}.sdf"
        if not same_retained_pose(cluster / "representative.sdf", ligand_sdf):
            print(f"Report figure warning: control rank {rank} interaction complex does not match exact plot pose", file=sys.stderr)
            continue
        interactions = cluster / "interactions"
        if not (interactions / "report.xml").is_file() and not interactions.exists() and plip and (cluster / "complex.pdb").is_file():
            result = subprocess.run([
                sys.executable, str(Path(__file__).with_name("docking-universal-interactions.py")),
                str(cluster / "complex.pdb"), "--out-dir", str(interactions),
                "--plip-command", str(plip), "--skip-native-visuals", "--typed-ligand-sdf", str(ligand_sdf),
                "--ligand-resname", "UNL", "--ligand-chain", "Z", "--ligand-position", "1",
            ], text=True, capture_output=True)
            if result.returncode:
                print(f"Report figure warning: control rank {rank} PLIP failed: {result.stderr.strip()}", file=sys.stderr)
        diagram = report / f"control_energy_rank_{rank}_plip2d.png"
        if (interactions / "report.xml").is_file() and render_poseedit_plip2d(interactions, ligand_sdf, diagram, ligand_id="UNL:Z:1"):
            write_pose_view(diagram, ligand_sdf, receptor, interactions / "report.xml",
                            f"Control energy rank {rank} · Cluster {row['cluster_id']}",
                            ("red", "marine", "gold")[rank-1], role=f"energy_rank_{rank}", cluster_id=row["cluster_id"], pose_id=pose_id)
            outputs.append(str(diagram))
    outputs.extend(build_control_paired_views(control, pymol))
    return outputs


def build_control_paired_views(control, pymol):
    """Prepare paired control views only when their exact ligand identity verifies."""
    from docking_universal.pose_visuals import read_pose_view
    report = Path(control) / 'report'
    receipt = report / 'control_paired_interactions.json'
    reference_view = read_pose_view(report / 'control_experimental_plip2d.png')
    if not pymol or not reference_view:
        receipt.unlink(missing_ok=True)
        return []
    reference = reference_view['ligand']
    entries, outputs = [], []
    palette = {'magenta': '#b638a0', 'red': '#d62728', 'marine': '#1f77b4', 'gold': '#d9a400'}
    for index, (name, title) in enumerate((('experimental', 'Experimental reference'),
                                           ('energy_rank_1', 'Lowest-energy control pose'),
                                           ('lowest_rmsd', 'Lowest-RMSD control pose')), 1):
        view = read_pose_view(report / f'control_{name}_plip2d.png')
        if not view:
            continue
        scenes = sorted(view['interactions'].parent.glob('*_plip_all_in_one.pml'))
        if len(scenes) != 1:
            continue
        load_lines = [line[5:].rsplit(', typed_ligand', 1)[0].strip().strip('"')
                      for line in scenes[0].read_text().splitlines()
                      if line.startswith('load ') and line.endswith(', typed_ligand')]
        if len(load_lines) != 1 or not same_retained_pose(Path(load_lines[0]), view['ligand']):
            continue
        ligand_id = 'UNL:Z:1'
        if name == 'experimental':
            identity = read_json(view['interactions'].parent / 'run_manifest.json').get('ligand_filter') or {}
            parts = [str(identity.get(key) or '').strip() for key in ('resname', 'chain', 'position')]
            if not all(parts):
                continue
            ligand_id = ':'.join(parts)
        diagram = report / f'control_paired_{name}_2d.png'
        if not render_poseedit_plip2d(view['interactions'].parent, view['ligand'], diagram,
                                      ligand_id=ligand_id, alignment_reference=reference):
            continue
        color = palette.get(view.get('ligand_color'), '#777777')
        scene = report / f'control_paired_{name}_3d.png'
        renderer = Path(__file__).with_name('docking-universal-render3d.py')
        result = subprocess.run([sys.executable, str(renderer), str(scenes[0]), '--out', str(scene),
                                 '--contact-residue-labels', '--ligand-color', color, '--pymol', str(pymol)],
                                capture_output=True, text=True)
        if result.returncode or not scene.is_file():
            continue
        entries.append({'role': name, 'heading': title, 'energy_rank': index, 'color': color,
                        'scene': str(scene), 'diagram': str(diagram),
                        'scene_sha256': hashlib.sha256(scene.read_bytes()).hexdigest(),
                        'diagram_sha256': hashlib.sha256(diagram.read_bytes()).hexdigest()})
        outputs.extend((str(scene), str(diagram)))
    if entries:
        receipt.write_text(json.dumps({'schema': 'docking-universal-paired-control-v1', 'pairs': entries}, indent=2) + '\n')
        outputs.append(str(receipt))
    else:
        receipt.unlink(missing_ok=True)
    return outputs


def control_overlay_poses(analysis, panel_a, report):
    """Show one lowest-energy representative for each of the top clusters."""
    from rdkit import Chem

    audit = read_json(panel_a.with_suffix(".json"))
    with panel_a.with_suffix(".csv").open(newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["displayed_in_plot"] == "True"]
    selected = [{"pose_id": int(row["lowest_energy_pose_id"]), "cluster_id": int(row["cluster_id"]),
                 "role": f"energy_rank_{rank}", "color": color}
                for rank, (row, color) in enumerate(zip(rows[:3], ("red", "marine", "gold")), 1)]
    closest = audit["closest_to_crystal_pose"]
    molecules = list(read_sdf(analysis / "all_poses.sdf", removeHs=False))
    paths = []
    for row in selected:
        molecule = molecules[row["pose_id"] - 1]
        if molecule is None:
            raise ValueError("Control overlay pose is unreadable")
        path = report / f"control_overlay_pose_{row['pose_id']:04d}.sdf"
        with sdf_writer(path) as writer:
            writer.write(molecule)
        paths.append(path)
    return paths, [row["color"] for row in selected], {
        "selection": "one lowest-energy representative per top-three energy-ranked cluster",
        "experimental_color": "magenta", "poses": selected,
        "closest_to_crystal_pose": closest,
    }


def build_compound_figures(study, pymol):
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
            render_overlay(receptor, ligands, ["red", "marine", "gold"], panel_b, report / f"{asset_id}_panel_B_representatives.pse", pymol)
            combined = report / f"{asset_id}_panels_AB.png"
            if panel_b.is_file():
                combine_panels(panel_a, panel_b, combined, docking_clusters=True)
            outputs.extend(str(path) for path in (panel_a, panel_b, combined) if path.is_file())
            snapshots = report / f"{asset_id}_top3_3d_snapshots.png"
            if combine_cluster_snapshots(analysis, selected, snapshots):
                outputs.append(str(snapshots))
            alignment_reference = (analysis / f"cluster_{int(selected[0]['cluster_id']):03d}" / 'representative.sdf') if selected else None
            if alignment_reference is not None and not alignment_reference.is_file():
                alignment_reference = None
            for row in selected:
                cluster = analysis / f"cluster_{int(row['cluster_id']):03d}"
                diagram = cluster / "interactions" / "representative_plip2d.png"
                if render_poseedit_plip2d(cluster / "interactions", cluster / "representative.sdf", diagram,
                                 alignment_reference=alignment_reference):
                    outputs.append(str(diagram))
            # Render color-matched interaction scenes into the report folder;
            # the original docking artifacts remain untouched.
            paired = []
            for rank, row in enumerate(selected, 1):
                cluster = analysis / f"cluster_{int(row['cluster_id']):03d}"
                interactions = cluster / 'interactions'
                scene = interactions / 'complex_plip_all_in_one.pml'
                ligand = cluster / 'representative.sdf'
                diagram = interactions / 'representative_plip2d.png'
                manifest = read_json(diagram.with_suffix('.manifest.json'))
                if not (pymol and scene.is_file() and ligand.is_file() and diagram.is_file() and alignment_reference):
                    continue
                load_lines = [line[5:].rsplit(', typed_ligand', 1)[0].strip().strip('"')
                              for line in scene.read_text().splitlines()
                              if line.startswith('load ') and line.endswith(', typed_ligand')]
                if (manifest.get('renderer_policy') != 'approved-poseedit-local-v1'
                        or manifest.get('ligand') != str(ligand.resolve())
                        or manifest.get('alignment_reference_sha256') != hashlib.sha256(alignment_reference.read_bytes()).hexdigest()
                        or len(load_lines) != 1 or Path(load_lines[0]).resolve() != ligand.resolve()):
                    continue
                rendered = report / f'{asset_id}_paired_cluster_{int(row["cluster_id"]):03d}_3d.png'
                command = [sys.executable, str(Path(__file__).with_name('docking-universal-render3d.py')),
                           str(scene), '--out', str(rendered), '--contact-residue-labels',
                           '--ligand-color', TOP_COLORS[rank - 1], '--pymol', str(pymol)]
                result = subprocess.run(command, capture_output=True, text=True)
                if result.returncode == 0 and rendered.is_file():
                    paired.append({'cluster_id': int(row['cluster_id']), 'energy_rank': rank,
                                   'score': row.get('best_energy_kcal_per_mol'),
                                   'color': TOP_COLORS[rank - 1], 'scene': str(rendered), 'diagram': str(diagram)})
                    outputs.append(str(rendered))
            receipt = report / f'{asset_id}_paired_interactions.json'
            if paired:
                included = {item['cluster_id'] for item in paired}
                missing = [int(row['cluster_id']) for row in selected if int(row['cluster_id']) not in included]
                receipt.write_text(json.dumps({'schema': 'docking-universal-paired-interactions-v1',
                                               'pairs': paired, 'missing_clusters': missing}, indent=2) + '\n')
                outputs.append(str(receipt))
            else:
                receipt.unlink(missing_ok=True)
    return outputs


def main():
    """Generate every applicable report figure from a completed study folder."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("study", type=Path)
    parser.add_argument("--control", type=Path)
    parser.add_argument("--pymol", default="pymol")
    args = parser.parse_args()
    study = args.study.expanduser().resolve()
    study_summary = read_json(study / "report" / "study_summary.json")
    workflow_is_exploratory = (
        study_summary.get("workflow") == "exploratory"
        or study_summary.get("study_status") == "EXPLORATORY_NO_CONTROL"
    )
    control = args.control.expanduser().resolve() if args.control and not workflow_is_exploratory else (None if workflow_is_exploratory else discover_control(study))
    pymol = pymol_executable(args.pymol)
    plip = plip_executable()
    outputs = build_compound_figures(study, pymol)
    if not control:
        outputs.extend(build_cavity_figures(study, pymol))
    if workflow_is_exploratory:
        related = study_summary.get('related_site_control') or {}
        record = related.get('record')
        related_control = Path(record).parent / 'control' / 'control' if record else None
        if related_control and related_control.is_dir():
            outputs.extend(build_related_control_diagrams(study, related_control))
            outputs.extend(build_related_control_3d(study, related_control, pymol))
    protocol = choose_protocol(control) if control else None
    if control and protocol:
        outputs.extend(build_control_figures(control, protocol, pymol, plip))
    interaction_manifests = [
        read_json(path) for path in study.glob(
            "compounds/*/pose_analysis/cluster_*/interactions/representative_plip2d.manifest.json"
        )
    ]
    renderer_policies = sorted({
        item["renderer_policy"] for item in interaction_manifests
        if item.get("renderer_policy") == "approved-poseedit-local-v1"
    })
    manifest = {
        "schema_name": "docking-universal-report-figures", "schema_version": 2,
        "study": str(study), "control": str(control) if control else None,
        "pymol": str(pymol) if pymol else None,
        "plip": str(plip) if plip else None,
        "interaction_diagram_renderer": (
            renderer_policies[0] if len(renderer_policies) == 1 else renderer_policies
        ) if renderer_policies else None,
        "outputs": outputs,
    }
    report = study / "report"
    report.mkdir(parents=True, exist_ok=True)
    (report / "report_figure_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Report figures: {len(outputs)} artifacts")


if __name__ == "__main__":
    main()
