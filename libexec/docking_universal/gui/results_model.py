"""Read-only projection of retained screening artifacts for GUI presentation."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from ..services.pose_interactions import read_pose_inventory
from ..state import StudyState


@dataclass(frozen=True)
class CompoundResult:
    path: Path
    name: str
    status: str
    site_count: object
    planned_jobs: object
    best_score: object
    cluster_count: int


@dataclass(frozen=True)
class ClusterInteraction:
    diagram: Path
    analysis_root: Path
    cluster_id: str
    site: str
    rank: object
    score: object
    population: object

    @property
    def label(self) -> str:
        return (
            f"Energy rank {self.rank} · Cluster {self.cluster_id} · {self.site} · "
            f"{self.score} kcal/mol · {self.population} poses"
        )

    @property
    def order_key(self) -> tuple:
        try:
            rank = int(self.rank)
        except (TypeError, ValueError):
            rank = 10**9
        try:
            cluster = int(self.cluster_id)
        except (TypeError, ValueError):
            cluster = 10**9
        return self.site, rank, cluster, str(self.diagram)


class ResultsReviewModel:
    """Parse retained files without Qt, host calls, viewer calls, or mutations."""

    @staticmethod
    def compounds(state: StudyState) -> tuple[CompoundResult, ...]:
        manifests = sorted(
            Path(item.path) for item in state.artifacts
            if item.kind == "screening_compound_manifest" and Path(item.path).is_file()
        )
        results = []
        for manifest_path in manifests:
            try:
                manifest = json.loads(manifest_path.read_text())
            except (OSError, json.JSONDecodeError):
                manifest = {}
            compound = manifest_path.parent
            scores = []
            score_path = compound / "all_scores.csv"
            if score_path.is_file():
                try:
                    with score_path.open(newline="") as handle:
                        for row in csv.DictReader(handle):
                            value = row.get("affinity") or row.get("score")
                            if value not in {None, ""}:
                                scores.append(float(value))
                except (OSError, ValueError):
                    scores = []
            clusters = 0
            for summary in compound.glob("**/cluster_summary.csv"):
                try:
                    with summary.open(newline="") as handle:
                        clusters += sum(1 for _row in csv.DictReader(handle))
                except OSError:
                    pass
            results.append(CompoundResult(
                compound, compound.name,
                manifest.get("completion_status") or manifest.get("run_status") or "retained",
                manifest.get("docking_site_count", "NA"),
                manifest.get("docking_job_count", "NA"),
                min(scores) if scores else "NA", clusters,
            ))
        return tuple(results)

    @staticmethod
    def cluster_interaction(diagram: Path, compound: Path) -> ClusterInteraction:
        cluster = diagram.parent.parent
        analysis = cluster.parent
        cluster_id = cluster.name.removeprefix("cluster_")
        site = analysis.parent.name if analysis.parent != compound else "primary site"
        values = {}
        summary = analysis / "cluster_summary.csv"
        if summary.is_file():
            try:
                with summary.open(newline="") as handle:
                    values = next((
                        row for row in csv.DictReader(handle)
                        if str(row.get("cluster_id", "")).lstrip("0") == cluster_id.lstrip("0")
                    ), {})
            except OSError:
                pass
        return ClusterInteraction(
            diagram, analysis, cluster_id, site,
            values.get("energy_rank") or "?",
            values.get("best_energy_kcal_per_mol") or "NA",
            values.get("pose_count") or values.get("count") or "NA",
        )

    @classmethod
    def cluster_interactions(
        cls, state: StudyState, compound: Path,
    ) -> tuple[ClusterInteraction, ...]:
        values = (
            cls.cluster_interaction(Path(item.path), compound)
            for item in state.artifacts
            if item.kind == "screening_interaction_diagram"
            and Path(item.path).is_file() and compound in Path(item.path).parents
        )
        return tuple(sorted(values, key=lambda item: item.order_key))

    @staticmethod
    def poses(compound: Path | None) -> tuple:
        rows = []
        if compound is not None:
            for inventory in sorted(compound.glob("**/pose_analysis/pose_inventory.csv")):
                try:
                    rows.extend((inventory.parent, record) for record in read_pose_inventory(inventory.parent))
                except (OSError, ValueError):
                    continue
        return tuple(rows)

    @staticmethod
    def cached_pose_diagram(analysis: Path, pose_id: int) -> Path | None:
        cache = analysis / "pose_interactions" / f"pose_{pose_id:04d}"
        return next((
            path for name in (
                "interaction_diagram.png", "pose_plip2d.png", "representative_plip2d.png",
            ) if (path := cache / name).is_file()
        ), None)
