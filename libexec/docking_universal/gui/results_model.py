"""Read-only projection of retained screening artifacts for GUI presentation."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from ..services.pose_interactions import read_pose_inventory, PoseInteractionPlan, validate_pose_interaction_outputs
from ..reporting import scoring_function_label
from ..pose_visuals import approved_interaction_diagram
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
    scoring_function: str = "Not recorded"


@dataclass(frozen=True)
class ClusterInteraction:
    diagram: Path
    analysis_root: Path
    cluster_id: str
    site: str
    rank: object
    score: object
    population: object
    pose_id: int | None = None

    @property
    def label(self) -> str:
        return (
            f"Energy rank {self.rank} · Cluster {self.cluster_id} · {self.site} · "
            f"{self.score} kcal/mol · {self.population} poses"
            + (f" · pose {self.pose_id} (on demand)" if self.pose_id is not None else "")
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
                            value = row.get("affinity_kcal_per_mol") or row.get("affinity") or row.get("score")
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
            from ..services.compound_identity import retained_compound_name_for_path
            results.append(CompoundResult(
                compound, retained_compound_name_for_path(compound),
                manifest.get("completion_status") or manifest.get("run_status") or "retained",
                manifest.get("docking_site_count", "NA"),
                manifest.get("docking_job_count", "NA"),
                min(scores) if scores else "NA", clusters,
                scoring_function_label(manifest.get("engine")),
            ))
        return tuple(results)

    @staticmethod
    def cluster_comparison(compound: Path) -> tuple[dict, ...]:
        """Return every retained cluster, including those without diagrams."""
        rows = []
        for summary in sorted(Path(compound).glob('**/cluster_summary.csv')):
            analysis = summary.parent
            site = analysis.parent.name if analysis.parent != Path(compound) else 'primary site'
            try:
                with summary.open(newline='') as handle:
                    for row in csv.DictReader(handle):
                        rows.append({**row, 'site': site, 'analysis': str(analysis)})
            except OSError:
                continue
        def ordering(row):
            try:
                rank = int(row.get('energy_rank') or 999999)
            except ValueError:
                rank = 999999
            return (str(row['site']), rank)
        return tuple(sorted(rows, key=ordering))

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
        values = list(
            cls.cluster_interaction(Path(item.path), compound)
            for item in state.artifacts
            if item.kind == "screening_interaction_diagram"
            and compound in Path(item.path).parents and approved_interaction_diagram(item.path)
        )
        for item in state.artifacts:
            if item.kind != 'pose_interaction_diagram' or not approved_interaction_diagram(item.path):
                continue
            metadata = item.metadata or {}
            analysis = Path(str(metadata.get('analysis_root') or ''))
            if compound not in analysis.parents:
                continue
            try:
                cluster_id, pose_id = int(metadata['cluster_id']), int(metadata['pose_id'])
            except (KeyError, TypeError, ValueError):
                continue
            placeholder = analysis / f'cluster_{cluster_id:03d}' / 'interactions' / 'diagram.png'
            cluster = cls.cluster_interaction(placeholder, compound)
            values.append(ClusterInteraction(Path(item.path), analysis, cluster.cluster_id, cluster.site,
                                             cluster.rank, metadata.get('score', 'NA'), cluster.population, pose_id))
        # A worker can finish writing a valid result before the host disconnects
        # while registering it. Recover such results directly from the cache.
        existing = {item.diagram.resolve() for item in values}
        for analysis, record in cls.poses(compound):
            cache = analysis / 'pose_interactions' / f'pose_{record.pose_id:04d}'
            diagram = cache / 'interaction_diagram.png'
            if not approved_interaction_diagram(diagram) or diagram.resolve() in existing:
                continue
            plan = PoseInteractionPlan(record, cache, (), diagram, cache / 'plip' / 'report.xml',
                                       cache / 'interaction_manifest.json', True)
            try:
                validate_pose_interaction_outputs(plan)
            except (OSError, ValueError):
                continue
            placeholder = analysis / f'cluster_{record.cluster_id:03d}' / 'interactions' / 'diagram.png'
            cluster = cls.cluster_interaction(placeholder, compound)
            values.append(ClusterInteraction(diagram, analysis, cluster.cluster_id, cluster.site,
                                             cluster.rank, str(record.energy_kcal_per_mol), cluster.population, record.pose_id))
            existing.add(diagram.resolve())
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
        diagram = cache / "interaction_diagram.png"
        return diagram if approved_interaction_diagram(diagram) else None
