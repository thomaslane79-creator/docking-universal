#!/usr/bin/env python3
"""Shared, clearly labeled review of retained fpocket docking boxes."""

import csv
import re
import shutil
import subprocess
from pathlib import Path


POCKET_COLORS = (
    ("du_red", "[0.8392, 0.1529, 0.1569]"),
    ("du_blue", "[0.1216, 0.4667, 0.7059]"),
    ("du_gold", "[0.8510, 0.6431, 0.0000]"),
    ("du_magenta", "[0.8392, 0.1529, 0.7569]"),
    ("du_cyan", "[0.0000, 0.6510, 0.6980]"),
    ("du_orange", "[0.9490, 0.5569, 0.1686]"),
    ("du_purple", "[0.5804, 0.4039, 0.7412]"),
)
SITE_COLORS = (
    ("du_forest", "[0.1333, 0.5451, 0.1333]"),
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


def describe_prepared_boxes(boxes, evidence_summary=None):
    records = prepared_box_records(boxes)
    for index, record in enumerate(records, start=1):
        row = record["row"]
        color = POCKET_COLORS[(index - 1) % len(POCKET_COLORS)][0].removeprefix("du_")
        score = f"{record['score']:.4f}" if record["score"] == record["score"] else "not recorded"
        marker = " - competitive score" if record.get("competitive") else ""
        source = row.get("pocket_file", "fpocket source not recorded")
        evidence = (evidence_summary or {}).get(index) or (evidence_summary or {}).get(str(index))
        evidence_text = ""
        if evidence:
            ligands = ", ".join(evidence.get("ligands", [])) or "identities unavailable"
            evidence_text = (
                f" | PDB evidence: {evidence.get('contained_ligands', 0)} contained, "
                f"{evidence.get('overlapping_ligands', 0)} partially overlapping | ligands: {ligands}"
            )
        print(f"  {index}) Pocket {index} ({color}) | {record['box'].name} | {source} | fpocket score {score}{marker}{evidence_text}")
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
    for color_name, rgb in dict(POCKET_COLORS + SITE_COLORS).items():
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
    """Backward-compatible single-box selector."""
    return choose_prepared_boxes(boxes, interactive=interactive, allow_multiple=False)[0]


def choose_labeled_boxes(candidates, interactive=True, requested=None, allow_multiple=True):
    """Select one or more box candidates by their report-visible labels.

    ``candidates`` is an ordered sequence of mappings containing ``label``,
    ``path``, and ``description``.  Labels are authoritative identifiers: the
    same label must refer to the same geometry in the report, PyMOL scene,
    protocol record, and this prompt.
    """
    if not candidates:
        raise SystemExit("No docking-box candidates are available")
    labels = {str(item["label"]).upper(): item for item in candidates}
    if len(labels) != len(candidates):
        raise SystemExit("Docking-box candidate labels must be unique")
    print("Choose one or more docking boxes:")
    for index, item in enumerate(candidates, 1):
        print(f"  {index}) {item['label']} — {item['description']}")
    if allow_multiple:
        print("Multiple labels run the complete workflow independently at each selected box.")
    choice = requested
    if choice is None:
        default = str(candidates[0]["label"])
        choice = (input(f"Select one or more box labels, separated by commas [{default}]: ").strip()
                  or default) if interactive else default
    tokens = [token.strip() for token in str(choice).split(",") if token.strip()]
    if not allow_multiple and len(tokens) != 1:
        raise SystemExit("This workflow requires exactly one docking-box selection")
    selected = []
    selected_labels = []
    for token in tokens:
        if token.isdigit() and 1 <= int(token) <= len(candidates):
            item = candidates[int(token) - 1]
        else:
            item = labels.get(token.upper())
        if item is None:
            valid = ", ".join(str(candidate["label"]) for candidate in candidates)
            raise SystemExit(f"Unknown docking-box label {token!r}; choose from {valid}")
        if item["label"] not in selected_labels:
            selected.append(Path(item["path"]))
            selected_labels.append(item["label"])
    return selected, selected_labels


def build_labeled_candidate_scene(receptor, candidates, pocket_evidence, evidence_root,
                                  diagnostics, output):
    """Create an interactive PyMOL scene with one toggleable group per label."""
    receptor = Path(receptor)
    evidence_root = Path(evidence_root)
    diagnostics = Path(diagnostics)
    output = Path(output)
    if not receptor.is_file() or not candidates:
        return None
    retained = []
    if diagnostics.is_file():
        with diagnostics.open(newline="") as handle:
            retained = [
                row for row in csv.DictReader(handle, delimiter="\t")
                if row.get("decision") == "selected"
            ]
        retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
    groups = (pocket_evidence or {}).get("ligand_site_groups") or []
    evidence_by_label = {}
    for group in groups:
        pocket = (group.get("fpocket_recovery") or {}).get("best_matching_pocket")
        label = (
            f"P{pocket}" if pocket
            else (group.get("site_identity") or {}).get(
                "canonical_label", f"L{group.get('site_number', '?')}",
            )
        )
        evidence_by_label[label.upper()] = group
    lines = [
        "# Docking Universal labeled docking-box review",
        f'load "{receptor.resolve()}", receptor',
        "hide everything, all", "show cartoon, receptor", "color gray70, receptor",
        "bg_color white", "set transparency_mode, 1", "set internal_gui_width, 360",
    ]
    for color_name, rgb in POCKET_COLORS:
        lines.append(f"set_color {color_name}, {rgb}")
    label_groups = []
    for candidate_index, candidate in enumerate(candidates, 1):
        label = str(candidate["label"])
        safe_label = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")
        group_name = f"Candidate_{safe_label}"
        label_groups.append(group_name)
        pocket_match = re.match(r"P(\d+)", label)
        ligand_match = re.match(r"L(\d+)$", label)
        if ligand_match:
            color = SITE_COLORS[(int(ligand_match.group(1)) - 1) % len(SITE_COLORS)][0]
        elif pocket_match and int(pocket_match.group(1)) <= 3:
            color = POCKET_COLORS[int(pocket_match.group(1)) - 1][0]
        elif pocket_match:
            color = "gray60"
        else:
            color = POCKET_COLORS[(candidate_index - 1) % len(POCKET_COLORS)][0]
        objects = []
        box_pdb = Path(candidate["path"]).with_name(Path(candidate["path"]).stem + "_box.pdb")
        if box_pdb.is_file():
            box_object = f"{safe_label}_box"
            objects.append(box_object)
            lines += [
                f'load "{box_pdb.resolve()}", {box_object}',
                f"hide everything, {box_object}", f"show sticks, {box_object}",
                f"set stick_radius, 0.16, {box_object}", f"color {color}, {box_object}",
            ]
        pocket_numbers = [int(value) for value in re.findall(r"P(\d+)", label)]
        for pocket_number in pocket_numbers:
            if not (1 <= pocket_number <= len(retained)):
                continue
            source = retained[pocket_number - 1].get("pocket_file", "")
            pocket_path = diagnostics.parent / "frozen_pockets" / source
            if not pocket_path.is_file():
                continue
            pocket_object = f"{safe_label}_pocket_{pocket_number}"
            objects.append(pocket_object)
            lines += [
                f'load "{pocket_path.resolve()}", {pocket_object}',
                f"hide everything, {pocket_object}", f"show surface, {pocket_object}",
                f"set transparency, 0.45, {pocket_object}", f"color {color}, {pocket_object}",
            ]
        evidence_group = evidence_by_label.get(label.upper())
        evidence_members = (evidence_group or {}).get("members") or []
        # For a P# candidate, show a ligand that actually matched and is fully
        # contained by that cavity box. A merely same-site pose is not a valid
        # substitute for direct correspondence.
        directly_matched = [
            member for member in evidence_members
            if str(member.get("matched_cavity")) in {str(value) for value in pocket_numbers}
        ]
        representative = (
            max(directly_matched, key=lambda item: int(item.get("ligand_heavy_atom_count", 0) or 0))
            if directly_matched else (evidence_group or {}).get("representative_ligand") or {}
        )
        ligand_path = evidence_root / str(representative.get("aligned_ligand_pdb", ""))
        if ligand_path.is_file():
            ligand_object = f"{safe_label}_representative_ligand"
            ligand_color = "forest" if pocket_match else color
            objects.append(ligand_object)
            lines += [
                f'load "{ligand_path.resolve()}", {ligand_object}',
                f"hide everything, {ligand_object}", f"show sticks, {ligand_object}",
                f"set stick_radius, 0.25, {ligand_object}",
                f"color {ligand_color}, {ligand_object}",
            ]
        if objects:
            lines.append(f"group {group_name}, {' '.join(objects)}")
            lines.append(f"disable {group_name}")
    if label_groups:
        lines.append(f"enable {label_groups[0]}")
    lines += ["orient receptor", "zoom receptor, 8", f"save {output.with_suffix('.pse').resolve()}"]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n")
    return output


def review_labeled_candidate_scene(receptor, candidates, pocket_evidence, evidence_root,
                                   diagnostics, output, pymol_command="pymol",
                                   interactive=False, requested=False):
    """Build and optionally open the same labeled candidates used by the CLI."""
    if interactive:
        answer = input("Open the selectable-box PyMOL review before choosing? [Y/n]: ").strip().lower()
        if answer in {"n", "no"}:
            return None
    elif not requested:
        return None
    executable = shutil.which(pymol_command) or (
        pymol_command if Path(pymol_command).is_file() else None
    )
    if not executable:
        message = f"PyMOL was requested for pocket review but was not found: {pymol_command}"
        if requested:
            raise SystemExit(message)
        print(message)
        return None
    scene = build_labeled_candidate_scene(
        receptor, candidates, pocket_evidence, evidence_root, diagnostics, output,
    )
    if not scene:
        print("Pocket review: the selectable-box PyMOL scene could not be assembled.")
        return None
    subprocess.Popen([str(executable), str(scene)], cwd=str(scene.parent))
    print(f"Opened selectable-box review in PyMOL: {scene}")
    return [str(scene)]


def choose_prepared_boxes(boxes, interactive=True, evidence_summary=None, requested=None,
                          allow_multiple=True):
    """Select one or more reviewed sites without turning evidence into authority."""
    if not boxes:
        raise SystemExit("No prepared docking boxes are available")
    if len(boxes) == 1:
        return [boxes[0]]
    print("Prepared docking boxes available after pocket review:")
    describe_prepared_boxes(boxes, evidence_summary=evidence_summary)
    print("Pocket numbers and colors match the unified PyMOL review.")
    print("Scores prioritize geometric pocket hypotheses; they do not establish the biological binding site.")
    if allow_multiple:
        print("Selecting multiple sites runs the complete docking workflow independently at each site.")
        print(f"For example, three sites require approximately three times as many docking jobs.")
    choice = requested
    if choice is None:
        choice = (input("Select one or more pocket numbers, separated by commas [1]: ").strip() or "1") if interactive else "1"
    tokens = [token.strip() for token in str(choice).split(",") if token.strip()]
    if not allow_multiple and len(tokens) != 1:
        raise SystemExit("This workflow requires exactly one docking-box selection")
    if not tokens or any(not token.isdigit() or not (1 <= int(token) <= len(boxes)) for token in tokens):
        raise SystemExit("Invalid docking-box selection")
    indices = []
    for token in tokens:
        index = int(token) - 1
        if index not in indices:
            indices.append(index)
    selected = [boxes[index] for index in indices]
    overlaps = selected_box_overlaps(selected)
    for left, right, fraction in overlaps:
        print(
            f"Warning: Pocket {boxes.index(left) + 1} and Pocket {boxes.index(right) + 1} "
            f"docking boxes overlap by {fraction * 100:.1f}%; searches may be partly redundant."
        )
    return selected


def _box_values(path):
    values = {}
    if not Path(path).is_file():
        return values
    for line in Path(path).read_text().splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        try:
            values[key.strip()] = float(value)
        except ValueError:
            continue
    return values


def selected_box_overlaps(boxes):
    """Return every nonzero pairwise overlap as a fraction of one box volume."""
    overlaps = []
    for left_index, left in enumerate(boxes):
        a = _box_values(left)
        for right in boxes[left_index + 1:]:
            b = _box_values(right)
            axes = []
            for axis in "xyz":
                a_size, b_size = a.get(f"size_{axis}", 0.0), b.get(f"size_{axis}", 0.0)
                a_center, b_center = a.get(f"center_{axis}", 0.0), b.get(f"center_{axis}", 0.0)
                axes.append(max(0.0, min(a_center + a_size / 2, b_center + b_size / 2) -
                                      max(a_center - a_size / 2, b_center - b_size / 2)))
            intersection = axes[0] * axes[1] * axes[2]
            denominator = min(
                a.get("size_x", 0) * a.get("size_y", 0) * a.get("size_z", 0),
                b.get("size_x", 0) * b.get("size_y", 0) * b.get("size_z", 0),
            )
            if intersection > 0 and denominator > 0:
                overlaps.append((Path(left), Path(right), intersection / denominator))
    return overlaps
