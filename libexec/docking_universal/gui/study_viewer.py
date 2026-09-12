"""Translate retained study artifacts into the required PyMOL review scene."""

from __future__ import annotations

from pathlib import Path

from ..state import StudyState
from ..viewer.identities import StructureIdentity
from ..viewer.pymol_adapter import PymolAdapter, RegisteredStructure


POCKET_COLORS = ("marine", "orange", "violet", "cyan", "salmon", "yellow")


class StudyViewerCoordinator:
    def __init__(self, adapter: PymolAdapter):
        self.adapter = adapter
        self.connected = False

    def open(self, state: StudyState) -> None:
        receptor = next(
            (item for item in state.artifacts if item.kind == "prepared_receptor_structure"), None,
        )
        if receptor is None or not receptor.sha256:
            raise ValueError("Required prepared-receptor structure artifact is not available for visual review")
        if not self.connected:
            self.adapter.launch()
            self.connected = True
        structure = StructureIdentity(receptor.id, receptor.sha256, "prepared_receptor")
        self.adapter.register_structure(RegisteredStructure(
            structure, Path(receptor.path), "du_receptor",
        ))
        pockets = [item for item in state.artifacts if item.kind == "pocket_coordinates"]
        for index, artifact in enumerate(pockets):
            self.adapter.show_pocket(
                artifact.path, f"du_pocket_{index + 1}", POCKET_COLORS[index % len(POCKET_COLORS)],
            )
        candidates = state.workflow_data.get("pocket_candidates", [])
        if candidates:
            self.show_candidate(state, str(candidates[0]["id"]))
        self.adapter.capture_view()

    def show_candidate(self, state: StudyState, candidate_id: str) -> None:
        candidate = next(
            (item for item in state.workflow_data.get("pocket_candidates", []) if item.get("id") == candidate_id),
            None,
        )
        if candidate is None:
            raise KeyError(f"Unknown pocket candidate: {candidate_id}")
        geometry = candidate.get("evidence", {}).get("geometry", {})
        center = [geometry.get(f"center_{axis}") for axis in "xyz"]
        size = [geometry.get(f"size_{axis}") for axis in "xyz"]
        self.adapter.show_box(center, size)

    def close(self) -> None:
        self.adapter.close()
        self.connected = False
