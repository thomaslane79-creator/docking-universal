"""Stateful coordination for exact-pose review without UI or workflow ownership."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..state import StudyState
from .results_model import ResultsReviewModel


@dataclass(frozen=True)
class PoseLoadDecision:
    key: tuple[str, str, int]
    analysis_root: Path
    action: str
    diagram: Path | None = None


class ResultsReviewController:
    """Own transient pose-loading identity and decide whether work is required."""

    def __init__(self, model: ResultsReviewModel | None = None):
        self.model = model or ResultsReviewModel()
        self.pending_key: tuple[str, str, int] | None = None
        self.pending_analysis: str | None = None

    def select_pose(
        self, *, compound: str, site: str, analysis_root: Path,
        pose_id: int, mirrored: bool, host_available: bool,
        renderer_available: bool,
    ) -> PoseLoadDecision:
        key = (str(compound), str(site), int(pose_id))
        analysis = Path(analysis_root)
        self.pending_key = key
        self.pending_analysis = str(analysis.resolve())
        diagram = self.model.cached_pose_diagram(analysis, int(pose_id))
        if diagram is not None:
            action = "cached"
        elif mirrored:
            action = "wait"
        elif not host_available:
            action = "host_unavailable"
        elif not renderer_available:
            action = "renderer_unavailable"
        else:
            action = "request"
        return PoseLoadDecision(key, analysis, action, diagram)

    def accepts(self, key: tuple[str, str, int]) -> bool:
        return key == self.pending_key

    def clear(self) -> None:
        self.pending_key = None
        self.pending_analysis = None

    def completed_artifact(self, state: StudyState):
        if self.pending_key is None or self.pending_analysis is None:
            return None
        pose_id = self.pending_key[2]
        return next((
            item for item in reversed(state.artifacts)
            if item.kind == "pose_interaction_diagram"
            and item.metadata.get("pose_id") == pose_id
            and item.metadata.get("analysis_root") == self.pending_analysis
            and Path(item.path).is_file()
        ), None)
