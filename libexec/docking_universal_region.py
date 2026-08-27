"""Auditable docking-region and engine selection for reusable protocols."""

import math
import re
from pathlib import Path


REGION_BOUND_LIGAND = "bound-ligand"
REGION_FPOCKET = "predicted-pocket"
REGION_RESIDUES = "selected-residues"
REGION_WHOLE_PROTEIN = "whole-protein"
REGION_CHOICES = (
    REGION_BOUND_LIGAND,
    REGION_FPOCKET,
    REGION_RESIDUES,
    REGION_WHOLE_PROTEIN,
)


def choose_region():
    print("How should the docking region be defined?")
    print("  1) Selected bound ligand — investigate its observed binding site")
    print("  2) Predicted pocket — use fpocket candidates")
    print("  3) Selected residue or residue group — propose a surrounding box")
    print("  4) Whole-protein search — do not assume a localized binding site")
    answer = input("Select [1]: ").strip() or "1"
    try:
        return REGION_CHOICES[int(answer) - 1]
    except (ValueError, IndexError):
        raise SystemExit("Choose a docking-region definition from 1 to 4") from None


def choose_fpocket_selection():
    print("How should the fpocket cavity be selected?")
    print("  1) Automatically use the highest-ranked acceptable pocket")
    print("  2) Review the ranked pockets in PyMOL and choose one")
    answer = input("Select [1]: ").strip() or "1"
    if answer not in {"1", "2"}:
        raise SystemExit("Choose fpocket selection 1 or 2")
    return "automatic" if answer == "1" else "reviewed"


def parse_coordinates(path):
    records = []
    for line in Path(path).read_text(errors="replace").splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        try:
            xyz = tuple(float(line[start:end]) for start, end in ((30, 38), (38, 46), (46, 54)))
        except ValueError:
            continue
        records.append({
            "record": line[:6].strip(),
            "atom": line[12:16].strip(),
            "resname": line[17:20].strip(),
            "chain": line[21:22].strip(),
            "resnum": line[22:26].strip(),
            "icode": line[26:27].strip(),
            "xyz": xyz,
        })
    if not records:
        raise SystemExit(f"No atomic coordinates were found in {path}")
    return records


def bounds_box(records, margin):
    axes = list(zip(*(record["xyz"] for record in records)))
    minima = [min(axis) for axis in axes]
    maxima = [max(axis) for axis in axes]
    return {
        **{f"center_{axis}": (low + high) / 2.0 for axis, low, high in zip("xyz", minima, maxima)},
        **{f"size_{axis}": high - low + 2.0 * margin for axis, low, high in zip("xyz", minima, maxima)},
    }


def whole_protein_box(path, margin=4.0):
    records = [record for record in parse_coordinates(path) if record["record"] == "ATOM"]
    if not records:
        raise SystemExit("The prepared receptor has no protein atoms for whole-protein box construction")
    return bounds_box(records, margin)


def parse_residue_identifier(text):
    value = text.strip().upper()
    patterns = (
        r"(?P<chain>[A-Z0-9]):(?:(?P<resname>[A-Z]{3}))?(?P<resnum>-?[0-9]+)(?P<icode>[A-Z]?)",
        r"(?P<resname>[A-Z]{3})(?P<resnum>-?[0-9]+)(?P<icode>[A-Z]?)",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, value)
        if match:
            return {key: (item or "") for key, item in match.groupdict().items()}
    raise ValueError(f"Invalid residue identifier: {text}")


def residue_box(path, identifiers, margin=8.0):
    requested = [parse_residue_identifier(item) for item in identifiers]
    records = parse_coordinates(path)
    selected = []
    resolved = []
    for request in requested:
        matches = [
            record for record in records
            if record["record"] == "ATOM"
            and (not request.get("chain") or record["chain"] == request["chain"])
            and (not request.get("resname") or record["resname"] == request["resname"])
            and record["resnum"] == request["resnum"]
            and (not request.get("icode") or record["icode"] == request["icode"])
        ]
        residue_keys = sorted({(record["chain"], record["resname"], record["resnum"], record["icode"]) for record in matches})
        if not matches:
            raise SystemExit(f"Selected residue was not found: {format_residue(request)}")
        if not request.get("chain") and len(residue_keys) > 1:
            choices = ", ".join(format_residue({
                "chain": chain, "resname": name, "resnum": number, "icode": icode
            }) for chain, name, number, icode in residue_keys)
            raise SystemExit(f"Residue {format_residue(request)} is ambiguous; specify its chain ({choices})")
        selected.extend(matches)
        resolved.extend(residue_keys)
    resolved = list(dict.fromkeys(resolved))
    return bounds_box(selected, margin), [
        format_residue({"chain": chain, "resname": name, "resnum": number, "icode": icode})
        for chain, name, number, icode in resolved
    ]


def format_residue(record):
    prefix = f"{record.get('chain')}:" if record.get("chain") else ""
    return f"{prefix}{record.get('resname', '')}{record.get('resnum', '')}{record.get('icode', '')}"


def numeric_box(values):
    try:
        box = {key: float(values[key]) for key in (
            "center_x", "center_y", "center_z", "size_x", "size_y", "size_z"
        )}
    except (KeyError, TypeError, ValueError):
        raise SystemExit("Docking-box center and dimensions must all be numeric") from None
    if min(box[key] for key in ("size_x", "size_y", "size_z")) <= 0:
        raise SystemExit("Docking-box dimensions must be positive")
    return box


def recommend_engine(values, region_definition):
    box = numeric_box(values)
    dimensions = [box[f"size_{axis}"] for axis in "xyz"]
    volume = math.prod(dimensions)
    broad = region_definition == REGION_WHOLE_PROTEIN or max(dimensions) >= 40.0 or volume >= 64000.0
    if broad:
        return "qvinaw", "large-region or whole-protein search"
    return "vina", "localized docking region"


def choose_engine(values, region_definition, requested=None, interactive=True):
    recommended, basis = recommend_engine(values, region_definition)
    if requested:
        selected = requested
    elif not interactive:
        selected = recommended
    else:
        box = numeric_box(values)
        volume = math.prod(box[f"size_{axis}"] for axis in "xyz")
        print("\nApproved docking region:")
        print(
            f"  Center: {box['center_x']:.3f}, {box['center_y']:.3f}, "
            f"{box['center_z']:.3f} Å"
        )
        print(
            f"  Dimensions: {box['size_x']:.3f} × {box['size_y']:.3f} × "
            f"{box['size_z']:.3f} Å"
        )
        print(f"  Search volume: approximately {volume:,.0f} Å³")
        labels = {"vina": "AutoDock Vina", "qvinaw": "QuickVina-W"}
        alternate = "qvinaw" if recommended == "vina" else "vina"
        print(f"Recommended engine: {labels[recommended]} ({basis})")
        print(f"  1) {labels[recommended]} — recommended")
        print(f"  2) {labels[alternate]}")
        answer = input("Select [1]: ").strip() or "1"
        if answer not in {"1", "2"}:
            raise SystemExit("Choose docking engine 1 or 2")
        selected = recommended if answer == "1" else alternate
    return {
        "recommended_engine": recommended,
        "selected_engine": selected,
        "recommendation_basis": basis,
        "user_overrode_recommendation": selected != recommended,
    }


def write_box_files(conf, values):
    box = numeric_box(values)
    conf = Path(conf)
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("\n".join(f"{key} = {box[key]:.3f}" for key in (
        "center_x", "center_y", "center_z", "size_x", "size_y", "size_z"
    )) + "\n")
    cx, cy, cz = (box[f"center_{axis}"] for axis in "xyz")
    hx, hy, hz = (box[f"size_{axis}"] / 2.0 for axis in "xyz")
    corners = [
        (cx + sx * hx, cy + sy * hy, cz + sz * hz)
        for sx, sy, sz in (
            (-1, -1, -1), (1, -1, -1), (1, 1, -1), (-1, 1, -1),
            (-1, -1, 1), (1, -1, 1), (1, 1, 1), (-1, 1, 1),
        )
    ]
    edges = ((1,2),(2,3),(3,4),(4,1),(5,6),(6,7),(7,8),(8,5),(1,5),(2,6),(3,7),(4,8))
    lines = [
        f"HETATM{index:5d}  C   BOX A{index:4d}    {x:8.3f}{y:8.3f}{z:8.3f}  1.00  0.00           C"
        for index, (x, y, z) in enumerate(corners, 1)
    ]
    lines.extend(f"CONECT{left:5d}{right:5d}" for left, right in edges)
    conf.with_name(conf.stem + "_box.pdb").write_text("\n".join(lines + ["END"]) + "\n")
    return conf
