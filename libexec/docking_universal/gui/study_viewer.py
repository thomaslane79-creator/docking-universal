"""Translate retained study artifacts into the required PyMOL review scene."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..state import StudyState
from ..viewer.identities import StructureIdentity
from ..viewer.pymol_adapter import PymolAdapter, RegisteredStructure


# This is the permanent pocket palette used by the retained report figures.
# Interactive selection may change edge thickness, but never candidate color.
POCKET_COLORS = ("red", "marine", "gold", "magenta", "cyan", "orange", "violet")


class StudyViewerCoordinator:
    def __init__(self, adapter: PymolAdapter):
        self.adapter = adapter
        self.backend_kind = getattr(adapter, "backend_kind", "companion")
        self.backend_name = getattr(adapter, "backend_name", "PyMOL companion")
        self.connected = False
        self.report_view_available = False
        self.report_view_name: str | None = None
        self.status = "disconnected"
        self.last_error: str | None = None
        self.structure_context: str | None = None

    def set_context(self, state: StudyState) -> str | None:
        receptor = next((
            item for item in state.artifacts
            if item.kind == "prepared_receptor_structure" and item.sha256
        ), None)
        self.structure_context = receptor.sha256 if receptor is not None else None
        if hasattr(self.adapter, "set_structure_context"):
            self.adapter.set_structure_context(self.structure_context)
        return self.structure_context

    def open(self, state: StudyState) -> None:
        self.set_context(state)
        self.status = "connecting"
        self.last_error = None
        try:
            self._open(state)
        except Exception as exc:
            had_connection = self.connected
            self.connected = False
            self.report_view_available = False
            self.status = "failed"
            self.last_error = str(exc)
            if had_connection:
                try:
                    self.adapter.close()
                except Exception:
                    pass
            raise
        self.status = "connected"

    def _open(self, state: StudyState) -> None:
        report_view = self._preferred_report_view(state)
        if report_view is not None:
            actual_sha256 = self._sha256(Path(report_view.path))
            if not report_view.sha256 or actual_sha256 != report_view.sha256:
                raise ValueError(
                    "Retained report-view session no longer matches its registered artifact hash"
                )
            if not self.connected:
                self.adapter.launch()
                self.connected = True
            self.adapter.load_report_session(report_view.path)
            self.report_view_available = True
            self.report_view_name = Path(report_view.path).stem
            return
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

    def reconnect(self, state: StudyState) -> None:
        """Replace a failed viewer process and replay only retained visual state."""
        self.set_context(state)
        report_view = self._preferred_report_view(state)
        if report_view is not None:
            actual_sha256 = self._sha256(Path(report_view.path))
            if not report_view.sha256 or actual_sha256 != report_view.sha256:
                raise ValueError(
                    "Retained report-view session no longer matches its registered artifact hash"
                )
        self.status = "connecting"
        self.last_error = None
        try:
            self.adapter.reconnect()
        except Exception as exc:
            self.connected = False
            self.report_view_available = False
            self.status = "failed"
            self.last_error = str(exc)
            raise
        self.connected = True
        self.report_view_available = bool(self.adapter.report_session)
        self.report_view_name = (
            self.adapter.report_session.stem if self.adapter.report_session else None
        )
        self.status = "connected"

    def open_scene(self, path: Path | str) -> None:
        """Open the retained 3D session paired with the selected report figure."""
        scene = Path(path).resolve()
        if not scene.is_file() or scene.suffix.lower() != ".pse":
            raise FileNotFoundError(f"Retained PyMOL scene is missing: {scene}")
        if not self.connected:
            self.adapter.launch()
            self.connected = True
        self.adapter.load_report_session(scene)
        if hasattr(self.adapter, "bring_to_front"):
            self.adapter.bring_to_front()
        self.report_view_available = True
        self.report_view_name = scene.stem
        self.status = "connected"
        self.last_error = None

    @staticmethod
    def _preferred_report_view(state: StudyState):
        sessions = [
            item for item in state.artifacts
            if item.kind == "report_view_session" and Path(item.path).is_file()
        ]
        return next(
            (item for item in sessions if Path(item.path).name == "cavity_selected_box.pse"),
            sessions[0] if sessions else None,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def reset_report_view(self) -> None:
        if not self.connected or not self.report_view_available:
            raise ValueError("No connected retained report view is available to reset")
        self.adapter.reset_report_view()

    def refresh_health(self) -> bool:
        """Detect a stopped viewer backend before the next visual command."""
        if not self.connected:
            return False
        if self.adapter.is_alive():
            return True
        self.connected = False
        self.report_view_available = False
        self.status = "failed"
        self.last_error = f"{self.backend_name} stopped unexpectedly"
        return False

    def show_candidate(self, state: StudyState, candidate_id: str) -> None:
        candidates = state.workflow_data.get("pocket_candidates", [])
        candidate = next(
            (item for item in candidates if item.get("id") == candidate_id),
            None,
        )
        if candidate is None:
            raise KeyError(f"Unknown pocket candidate: {candidate_id}")
        geometry = candidate.get("evidence", {}).get("geometry", {})
        center = [geometry.get(f"center_{axis}") for axis in "xyz"]
        size = [geometry.get(f"size_{axis}") for axis in "xyz"]
        rank = int(candidate.get("rank") or (candidates.index(candidate) + 1))
        color = POCKET_COLORS[(rank - 1) % len(POCKET_COLORS)]
        evidence = candidate.get("evidence") or {}
        ligand_evidence = evidence.get("experimental_ligand_evidence") or {}
        has_corresponding_ligand_evidence = bool(
            ligand_evidence.get("observation_count")
            or "direct deposited-ligand correspondence" in str(candidate.get("summary", ""))
        )
        self.adapter.show_box(
            center, size, color=color,
            source_object_name=f"candidate_box_{candidate_id}",
            redundant_object_names=("ligand_site_box",) if has_corresponding_ligand_evidence else (),
            visible_associated_object_names=(
                ("ligand_site_representative",)
                if has_corresponding_ligand_evidence else ()
            ),
        )

    def show_pose(self, analysis_root: Path | str, pose_id: int) -> Path:
        if not self.connected:
            raise ValueError("Open the live PyMOL review before synchronizing a pose")
        if pose_id < 1:
            raise ValueError("Pose ID must be positive")
        pose = Path(analysis_root).resolve() / "pose_interactions" / f"pose_{pose_id:04d}" / "pose.sdf"
        if not pose.is_file():
            raise FileNotFoundError(f"Exact retained pose has not been materialized: {pose}")
        self.adapter.show_review_pose(pose)
        return pose

    def show_evidence_ligand(self, path: Path | str, receptor_path: Path | str | None = None) -> Path:
        if not self.connected:
            raise ValueError("Open the live PyMOL review before showing experimental evidence")
        ligand = Path(path).resolve()
        self.adapter.show_evidence_ligand(ligand, receptor_path)
        return ligand

    def show_evidence_ligands(self, paths: list[Path | str], receptor_path: Path | str | None = None) -> list[Path]:
        if not self.connected:
            raise ValueError("Open the live PyMOL review before showing experimental evidence")
        ligands = [Path(path).resolve() for path in paths]
        self.adapter.show_evidence_ligands(ligands, receptor_path)
        return ligands

    def sync_evidence_ligands(self, paths: list[Path | str]) -> list[Path]:
        if not self.connected:
            raise ValueError("Open the live PyMOL review before synchronizing evidence")
        ligands = [Path(path).resolve() for path in paths]
        self.adapter.sync_evidence_ligands(ligands)
        return ligands

    def close(self) -> None:
        self.adapter.close()
        self.connected = False
        self.report_view_available = False
        self.report_view_name = None
        self.status = "disconnected"
        self.last_error = None
