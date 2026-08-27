#!/usr/bin/env python3
"""Shared, clearly labeled review of retained fpocket docking boxes."""

import csv
import re
import shutil
import subprocess
from pathlib import Path


POCKET_COLORS = (
    ("du_blue", "[0.1216, 0.4667, 0.7059]"),
    ("du_gold", "[0.8510, 0.6431, 0.0000]"),
    ("du_magenta", "[0.8392, 0.1529, 0.7569]"),
    ("du_cyan", "[0.0000, 0.6510, 0.6980]"),
    ("du_orange", "[0.9490, 0.5569, 0.1686]"),
    ("du_purple", "[0.5804, 0.4039, 0.7412]"),
)


def prepared_box_records(boxes):
    """Attach retained fpocket provenance and a transparent near-tie flag."""
    if not boxes:
        return []
    cavity = boxes[0].parent
    diagnostics = cavity / "pocket_selection_diagnostics.tsv"
    rows = []
    if diagnostics.is_file():
        with diagnostics.open(newline="") as handle:
            rows = [row for row in csv.DictReader(handle, delimiter="\t") if row.get("decision") == "selected"]
    records = []
    for index, box in enumerate(boxes):
        row = rows[index] if index < len(rows) else {}
        try:
            score = float(row.get("score", "nan"))
        except ValueError:
            score = float("nan")
        records.append({"box": Path(box), "scene": Path(box).with_suffix(".pml"), "row": row, "score": score})
    finite = [record["score"] for record in records if record["score"] == record["score"]]
    if finite:
        best = max(finite)
        tolerance = max(0.05, abs(best) * 0.20)
        for record in records:
            record["competitive"] = record["score"] == record["score"] and record["score"] >= best - tolerance
            record["competitive_tolerance"] = tolerance
    else:
        for record in records:
            record["competitive"] = False
    return records


def describe_prepared_boxes(boxes):
    records = prepared_box_records(boxes)
    for index, record in enumerate(records, start=1):
        row = record["row"]
        color = POCKET_COLORS[(index - 1) % len(POCKET_COLORS)][0].removeprefix("du_")
        score = f"{record['score']:.4f}" if record["score"] == record["score"] else "not recorded"
        marker = " - competitive score" if record.get("competitive") else ""
        source = row.get("pocket_file", "fpocket source not recorded")
        print(f"  {index}) Pocket {index} ({color}) | {record['box'].name} | {source} | fpocket score {score}{marker}")
    return records


def _load_target(line):
    match = re.match(r"\s*load\s+(.+?),\s*([^\s]+)\s*$", line)
    return match.groups() if match else None


def build_combined_review_scene(root, records):
    """Write one PyMOL scene with every retained pocket labeled and color-matched."""
    if not records:
        return None
    root = Path(root)
    cavity = records[0]["box"].parent
    receptor = next(iter(sorted(root.glob("*_receptor_prep/receptor/*.pdb"))), None)
    if receptor is None:
        receptor = next(iter(sorted(root.glob("receptor/*.pdb"))), None)
    if receptor is None:
        return None
    target = re.sub(r"[^A-Za-z0-9_]", "_", receptor.stem)
    scene = cavity / f"{receptor.stem}_all_retained_pockets_review.pml"
    lines = [
        "# Unified Docking Universal retained-pocket review",
        f"load {receptor.resolve()}, {target}",
        "hide everything, all",
        f"show cartoon, {target}",
        f"color gray70, {target}",
        "bg_color white",
        "set transparency_mode, 1",
        "set label_size, 18",
        "set label_outline_color, black",
    ]
    for color_name, rgb in POCKET_COLORS:
        lines.append(f"set_color {color_name}, {rgb}")
    ligand_dir = next(iter(sorted(root.glob("*_receptor_prep/ligand"))), None)
    if ligand_dir is None and (root / "ligand").is_dir():
        ligand_dir = root / "ligand"
    ligand_objects = []
    if ligand_dir:
        for ligand_path in sorted(ligand_dir.glob("*.pdb")):
            ligand_name = re.sub(r"[^A-Za-z0-9_]", "_", ligand_path.stem)
            object_name = f"deposited_ligand_{ligand_name}"
            ligand_objects.append(object_name)
            lines += [
                f"load {ligand_path.resolve()}, {object_name}",
                f"show sticks, {object_name}",
                f"color magenta, {object_name}",
                f"set stick_radius, 0.22, {object_name}",
                f'label first {object_name}, "{ligand_path.stem}"',
            ]
    for index, record in enumerate(records, start=1):
        color_name = POCKET_COLORS[(index - 1) % len(POCKET_COLORS)][0]
        row = record["row"]
        source = row.get("pocket_file")
        core = None
        if source:
            candidates = sorted(cavity.glob(f"**/{source}"))
            core = candidates[0] if candidates else None
        center = record["box"].with_name(record["box"].stem + "_center.pdb")
        box_pdb = record["box"].with_name(record["box"].stem + "_box.pdb")
        if core and core.is_file():
            lines += [
                f"load {core.resolve()}, pocket_{index}_cavity",
                f"hide everything, pocket_{index}_cavity",
                f"show surface, pocket_{index}_cavity",
                f"set transparency, 0.45, pocket_{index}_cavity",
                f"color {color_name}, pocket_{index}_cavity",
            ]
        if box_pdb.is_file():
            lines += [
                f"load {box_pdb.resolve()}, pocket_{index}_box",
                f"show sticks, pocket_{index}_box",
                f"set stick_radius, 0.18, pocket_{index}_box",
                f"color {color_name}, pocket_{index}_box",
                f"disable pocket_{index}_box",
            ]
        if center.is_file():
            score = f"{record['score']:.4f}" if record["score"] == record["score"] else "not recorded"
            rank = row.get("rank_order") or str(index)
            group_score = re.sub(r"[^A-Za-z0-9]+", "_", score).strip("_")
            lines += [
                f"load {center.resolve()}, pocket_{index}_center",
                f"show spheres, pocket_{index}_center",
                f"set sphere_scale, 0.35, pocket_{index}_center",
                f"color {color_name}, pocket_{index}_center",
                f'label pocket_{index}_center, "Pocket {index}"',
                f"set label_color, white, pocket_{index}_center",
                f"set label_position, [0.0, 0.0, 2.5], pocket_{index}_center",
            ]
            lines.append(
                f"group Pocket_{index}__fpocket_{group_score}__priority_{rank}, pocket_{index}_*"
            )
        else:
            lines.append(f"group Pocket_{index}, pocket_{index}_*")
    pocket_selection = " or ".join(f"pocket_{index}_cavity" for index in range(1, len(records) + 1))
    review_selection = pocket_selection
    if ligand_objects:
        review_selection += " or " + " or ".join(ligand_objects)
    lines += [f"orient ({review_selection})", f"zoom ({review_selection}), 8"]
    scene.write_text("\n".join(lines) + "\n")
    return scene


def review_pocket_scene(root, pymol_command="pymol", interactive=False, requested=False):
    """Open one labeled PyMOL scene containing all retained candidates."""
    prep_roots = sorted(Path(root).glob("*_receptor_prep"))
    boxes = sorted(prep_roots[0].glob("cavity/*.conf")) if len(prep_roots) == 1 else []
    records = prepared_box_records(boxes)
    if not records:
        print("Pocket review: no generated PyMOL cavity scene was found.")
        return None
    print("Pocket review candidates (colors and numbers match the unified PyMOL scene):")
    describe_prepared_boxes(boxes)
    if interactive:
        answer = input("Open the labeled all-pocket PyMOL review before selecting? [Y/n]: ").strip().lower()
        if answer in {"n", "no"}:
            return None
    elif not requested:
        return None
    executable = shutil.which(pymol_command) or (pymol_command if Path(pymol_command).is_file() else None)
    if not executable:
        message = f"PyMOL was requested for pocket review but was not found: {pymol_command}"
        if requested:
            raise SystemExit(message)
        print(message)
        return None
    scene = build_combined_review_scene(root, records)
    if not scene:
        print("Pocket review: the unified PyMOL scene could not be assembled.")
        return None
    subprocess.Popen([str(executable), str(scene)], cwd=str(scene.parent))
    print(f"Opened labeled all-pocket review in PyMOL: {scene}")
    return [str(scene)]


def choose_prepared_box(boxes, interactive=True):
    if len(boxes) == 1:
        return boxes[0]
    print("Prepared docking boxes available after pocket review:")
    describe_prepared_boxes(boxes)
    print("Pocket numbers and colors match the unified PyMOL review.")
    print("Scores prioritize geometric pocket hypotheses; they do not establish the biological binding site.")
    choice = input("Select the reviewed pocket/box number [1]: ").strip() or "1" if interactive else "1"
    if not choice.isdigit() or not (1 <= int(choice) <= len(boxes)):
        raise SystemExit("Invalid docking-box selection")
    return boxes[int(choice) - 1]
