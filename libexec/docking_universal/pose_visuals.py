"""Shared retained-pose color semantics and exact 2D/3D artifact identities."""
import csv
import hashlib
import json
from pathlib import Path

RANK_COLORS = ("red", "marine", "gold")
LIGAND_COLORS = (*RANK_COLORS, "gray70", "green", "magenta")


def cluster_color(analysis, cluster_id, *, closest=False):
    """Rank belongs to a cluster, never inferred from a pose's own energy."""
    try:
        control_table = Path(analysis).parent / "control_panel_A_cluster.csv"
        table = control_table if control_table.is_file() else Path(analysis) / "cluster_summary.csv"
        with table.open(newline="") as source:
            rows = list(csv.DictReader(source))
        for row in rows:
            if int(row["cluster_id"]) == int(cluster_id):
                rank = int(row["energy_rank"])
                if 1 <= rank <= 3:
                    return RANK_COLORS[rank - 1]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return "green" if closest else "gray70"


def retained_pose_color(analysis, pose_id):
    try:
        with (Path(analysis) / "pose_inventory.csv").open(newline="") as source:
            row = next(row for row in csv.DictReader(source) if int(row["pose_id"]) == int(pose_id))
        audit_path = Path(analysis).parent / "control_panel_A_cluster.json"
        audit = json.loads(audit_path.read_text()) if audit_path.is_file() else {}
        closest = audit.get("closest_to_crystal_pose_id") == int(pose_id)
        return cluster_color(analysis, row["cluster_id"], closest=closest)
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        return "gray70"


def write_pose_view(diagram, ligand, receptor, interactions, label, color, *, coordinate_kind="docked", **identity):
    """Separate sidecar preserves the renderer's own manifests and hit regions."""
    if color not in LIGAND_COLORS:
        raise ValueError("Unsupported retained-pose color")
    if coordinate_kind not in ("experimental", "docked", "unknown"):
        raise ValueError("Unsupported retained coordinate kind")
    sources = {key: Path(path).resolve() for key, path in dict(
        diagram=diagram, ligand=ligand, receptor=receptor, interactions=interactions).items()}
    if not all(path.is_file() for path in sources.values()):
        return False
    record = dict(schema="docking-universal-pose-view-v1", label=label, ligand_color=color,
                  coordinate_kind=coordinate_kind, identity=identity, files={key: dict(path=str(path), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                                            for key, path in sources.items()})
    Path(str(diagram) + ".view.json").write_text(json.dumps(record, indent=2) + "\n")
    return True


def read_pose_view(diagram):
    """Changed/missing source files invalidate the link instead of guessing."""
    try:
        record = json.loads(Path(str(diagram) + ".view.json").read_text())
        if record["schema"] != "docking-universal-pose-view-v1" or record["ligand_color"] not in LIGAND_COLORS:
            return None
        sources = {}
        for key in ("diagram", "ligand", "receptor", "interactions"):
            entry = record["files"][key]
            path = Path(entry["path"]).resolve()
            if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
                return None
            sources[key] = path
        if sources["diagram"] != Path(diagram).resolve():
            return None
        kind = record.get("coordinate_kind", "unknown")
        if "coordinate_kind" not in record:
            role = record.get("identity", {}).get("role", "")
            if role == "experimental":
                kind = "experimental"
            elif role in ("top_ranked", "lowest_rmsd") or (isinstance(role, str) and role.startswith("energy_rank_")):
                kind = "docked"
        if kind not in ("experimental", "docked", "unknown"):
            return None
        return dict(sources, label=record["label"], ligand_color=record["ligand_color"], coordinate_kind=kind)
    except (OSError, ValueError, KeyError, TypeError):
        return None
