"""Build shared fpocket-box candidates for figures and interactive selection.

The report and command-line interface must derive consolidated P#/P# boxes
from the same geometry.  Keeping that rule here prevents a displayed box from
becoming an unselectable illustration or a label from referring to different
coordinates in different workflow stages.
"""

import math
from pathlib import Path


def config_geometry(path):
    """Read numeric Vina box geometry from a configuration file."""
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


def geometry_overlap_fraction(left, right):
    """Return intersection volume as a fraction of the smaller box."""
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


def pdb_points(path):
    """Read Cartesian atom positions from a PDB-formatted pocket file."""
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


def points_box(points, minimum=26.0, margin=4.0):
    """Return the minimum bounded Vina box containing the supplied points."""
    geometry = {}
    for index, axis in enumerate("xyz"):
        low = min(point[index] for point in points)
        high = max(point[index] for point in points)
        geometry[f"center_{axis}"] = (low + high) / 2.0
        geometry[f"size_{axis}"] = max(minimum, high - low + 2.0 * margin)
    return geometry


def grouped_fpocket_boxes(diagnostics, retained, included_pocket_files,
                          minimum_overlap=0.35, maximum_dimension=36.0,
                          maximum_volume=64000.0):
    """Consolidate eligible fpocket boxes using the report's bounded rule."""
    diagnostics = Path(diagnostics)
    included_pocket_files = set(included_pocket_files)
    items = []
    for fallback_number, row in enumerate(retained, 1):
        number = int(row.get("rank_order", fallback_number) or fallback_number)
        pocket_key = row.get("pocket_file", "")
        if pocket_key not in included_pocket_files:
            continue
        configs = sorted(diagnostics.parent.glob(f"*_pocket{number}.conf"))
        config = configs[0] if configs else None
        pocket = diagnostics.parent / "frozen_pockets" / pocket_key
        geometry = config_geometry(config) if config else {}
        points = pdb_points(pocket)
        if geometry and points:
            items.append({
                "numbers": [number], "geometry": geometry, "points": points,
                "pocket_files": [pocket_key],
            })
    groups = list(items)
    while True:
        choices = []
        for left in range(len(groups)):
            for right in range(left + 1, len(groups)):
                overlap = geometry_overlap_fraction(
                    groups[left]["geometry"], groups[right]["geometry"],
                )
                if overlap < minimum_overlap:
                    continue
                geometry = points_box(groups[left]["points"] + groups[right]["points"])
                volume = math.prod(geometry[f"size_{axis}"] for axis in "xyz")
                if (max(geometry[f"size_{axis}"] for axis in "xyz") <= maximum_dimension
                        and volume <= maximum_volume):
                    choices.append((overlap, -volume, left, right, geometry))
        if not choices:
            break
        _, _, left, right, geometry = max(choices)
        groups[left] = {
            "numbers": sorted(groups[left]["numbers"] + groups[right]["numbers"]),
            "geometry": geometry,
            "points": groups[left]["points"] + groups[right]["points"],
            "pocket_files": groups[left]["pocket_files"] + groups[right]["pocket_files"],
        }
        groups.pop(right)
    return groups
