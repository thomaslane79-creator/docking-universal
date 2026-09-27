"""Supervised PyMOL adapter using stable viewer-neutral identities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import subprocess
import sys
from typing import Any
from uuid import uuid4

from ..pymol_spike import PymolSpikeClient, PymolSpikeController, PymolSpikeError
from .identities import AtomIdentity, StructureIdentity
from .selections import Selection


@dataclass(frozen=True)
class RegisteredStructure:
    identity: StructureIdentity
    path: Path
    object_name: str

    def __post_init__(self) -> None:
        if not self.path.is_file():
            raise FileNotFoundError(f"Registered structure is missing: {self.path}")


class PymolAdapter:
    """Own one viewer session and replay only validated registered state."""

    backend_kind = "companion"
    backend_name = "PyMOL companion"

    def __init__(self, pymol: Path | str, bridge_script: Path | str, log_directory: Path | str):
        self.controller = PymolSpikeController(pymol, bridge_script, log_directory)
        self.client: PymolSpikeClient | None = None
        self.session_id = f"viewer-{uuid4().hex}"
        self.structures: dict[str, RegisteredStructure] = {}
        self.pockets: dict[str, dict[str, Any]] = {}
        self.snapshot: dict[str, Any] = {"structures": [], "pockets": [], "selections": {}, "box": None, "view": None}
        self.report_session: Path | None = None
        self.review_pose: Path | None = None
        self.evidence_ligand: Path | None = None

    def launch(self, *, headless: bool = False) -> str:
        self.client = self.controller.start(headless=headless)
        return self.session_id

    def register_structure(self, structure: RegisteredStructure) -> dict[str, Any]:
        client = self._client()
        if structure.object_name in self.structures and self.structures[structure.object_name] != structure:
            raise ValueError(f"PyMOL object name is already registered: {structure.object_name}")
        if structure.object_name in self.structures:
            return {
                "object_name": structure.object_name, "path": str(structure.path.resolve()),
                "already_loaded": True,
            }
        loaded = client.request("load_structure", {
            "path": str(structure.path.resolve()), "object_name": structure.object_name,
        })
        self.structures[structure.object_name] = structure
        self.snapshot["structures"] = [
            {"identity": item.identity, "path": str(item.path.resolve()), "object_name": item.object_name}
            for item in self.structures.values()
        ]
        return loaded

    def show_pocket(self, path: Path | str, object_name: str, color: str) -> dict[str, Any]:
        retained = {"path": str(Path(path).resolve()), "object_name": object_name, "color": color}
        if object_name in self.pockets:
            if self.pockets[object_name] != retained:
                raise ValueError(f"PyMOL pocket object name is already registered: {object_name}")
            return {**retained, "already_loaded": True}
        result = self._client().request("load_pocket", {
            **retained,
        })
        retained["path"] = result["path"]
        self.pockets[object_name] = retained
        self.snapshot["pockets"] = [item for item in self.snapshot["pockets"] if item["object_name"] != object_name]
        self.snapshot["pockets"].append(retained)
        return result

    def apply_selection(self, selection: Selection) -> Selection:
        residues = []
        seen = set()
        for atom in selection.atoms:
            registered = self._registered(atom)
            identity = {
                "model": registered.object_name,
                "segi": atom.segment,
                "chain": atom.chain,
                "residue_number": atom.residue_number,
                "insertion_code": atom.insertion_code,
                "residue_name": atom.residue_name,
                "altloc": atom.altloc,
            }
            key = tuple(identity.items())
            if key not in seen:
                seen.add(key)
                residues.append(identity)
        result = self._client().request("apply_selection", {"name": selection.name, "residues": residues})
        returned = self._convert_atoms(result.get("atoms", []))
        applied = Selection(selection.name, tuple(returned), selection.origin_request_id)
        self.snapshot["selections"][selection.name] = applied
        return applied

    def start_pick(self) -> dict[str, Any]:
        return self._client().request("start_pick")

    def get_pick(self, *, origin_request_id: str | None = None) -> Selection | None:
        result = self._client().request("get_pick")
        pick = result.get("pick")
        if not pick:
            return None
        atoms = self._convert_atoms(pick.get("residue_atoms", []))
        selection = Selection("du_user_pick", tuple(atoms), origin_request_id)
        self.snapshot["selections"][selection.name] = selection
        return selection

    def show_box(
        self, center, size, color: str = "red", source_object_name: str | None = None,
        redundant_object_names: tuple[str, ...] = (),
        visible_associated_object_names: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        result = self._client().request("show_box", {
            "name": "du_box", "center": list(center), "size": list(size), "color": color,
            "source_object_name": source_object_name,
            "redundant_object_names": list(redundant_object_names),
            "visible_associated_object_names": list(visible_associated_object_names),
        })
        self.snapshot["box"] = result
        return result

    def load_report_session(self, path: Path | str) -> dict[str, Any]:
        """Load the retained PyMOL session used to render a report figure."""
        session = Path(path).resolve()
        if not session.is_file() or session.suffix.lower() != ".pse":
            raise FileNotFoundError(f"Retained report-view session is missing: {session}")
        result = self._client().request(
            "load_report_session", {"path": str(session), "replace": True},
        )
        self.report_session = session
        return result

    def bring_to_front(self) -> None:
        """Raise the exact companion process after a scene update on macOS."""
        if sys.platform != "darwin":
            return
        # The host terminal is a separate macOS application and cannot be
        # lowered through Qt; hide it while the interactive viewer is active.
        for app_name in ("Terminal", "iTerm2"):
            subprocess.run(
                ["osascript", "-e", f'tell application "{app_name}" to hide'],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        process = getattr(self.controller, "process", None)
        pid = getattr(process, "pid", None)
        if not pid:
            return
        try:
            result = subprocess.run(
                [
                    "osascript", "-e",
                    "tell application \"System Events\" to set frontmost of "
                    f"first process whose unix id is {int(pid)} to true",
                ],
                check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass

    def reset_report_view(self) -> dict[str, Any]:
        """Restore the immutable session that generated the selected report view."""
        if self.report_session is None:
            raise PymolSpikeError("No retained report view is available to restore")
        return self._client().request(
            "load_report_session", {"path": str(self.report_session), "replace": True},
        )

    def show_review_pose(self, path: Path | str) -> dict[str, Any]:
        pose = Path(path).resolve()
        if not pose.is_file() or pose.suffix.lower() != ".sdf":
            raise FileNotFoundError(f"Retained SDF review pose is missing: {pose}")
        result = self._client().request(
            "show_review_pose", {"path": str(pose), "object_name": "du_review_pose"},
        )
        self.review_pose = pose
        return result

    def show_evidence_ligand(self, path: Path | str, receptor_path: Path | str | None = None) -> dict[str, Any]:
        ligand = Path(path).resolve()
        if not ligand.is_file() or ligand.suffix.lower() != ".pdb":
            raise FileNotFoundError(f"Aligned deposited ligand is missing: {ligand}")
        payload = {"path": str(ligand), "object_name": "du_evidence_ligand"}
        if receptor_path:
            payload["receptor_path"] = str(receptor_path)
        result = self._client().request("show_evidence_ligand", payload)
        self.evidence_ligand = ligand
        return result

    def show_evidence_ligands(self, paths: list[Path | str], receptor_path: Path | str | None = None) -> dict[str, Any]:
        ligands = [Path(path).resolve() for path in paths]
        if not ligands or any(not path.is_file() or path.suffix.lower() != ".pdb" for path in ligands):
            raise FileNotFoundError("Evidence comparison requires existing retained PDB ligands")
        result = self._client().request(
            "show_evidence_ligands", {"paths": [str(path) for path in ligands], "receptor_path": str(receptor_path) if receptor_path else ""},
        )
        self.evidence_ligand = ligands[-1]
        self.bring_to_front()
        return result

    def sync_evidence_ligands(self, paths: list[Path | str]) -> dict[str, Any]:
        ligands = [Path(path).resolve() for path in paths]
        if any(not path.is_file() or path.suffix.lower() != ".pdb" for path in ligands):
            raise FileNotFoundError("Evidence selection contains a missing PDB")
        return self._client().request("sync_evidence_ligands", {"paths": [str(path) for path in ligands]})

    def capture_view(self) -> dict[str, Any]:
        result = self._client().request("get_view")
        self.snapshot["view"] = result
        return result

    def reconnect(self, *, headless: bool = False) -> str:
        self.controller.stop()
        self.session_id = f"viewer-{uuid4().hex}"
        self.client = self.controller.start(headless=headless)
        structures = list(self.structures.values())
        selections = list(self.snapshot["selections"].values())
        pockets = list(self.snapshot["pockets"])
        box = self.snapshot["box"]
        view = self.snapshot["view"]
        report_session = self.report_session
        review_pose = self.review_pose
        evidence_ligand = self.evidence_ligand
        self.structures.clear()
        self.pockets.clear()
        for structure in structures:
            self.register_structure(structure)
        for pocket in pockets:
            self.show_pocket(**pocket)
        for selection in selections:
            self.apply_selection(selection)
        if box:
            self._client().request("show_box", box)
        if view:
            self._client().request("set_view", view)
        if report_session:
            self.load_report_session(report_session)
        if review_pose:
            self.show_review_pose(review_pose)
        if evidence_ligand:
            self.show_evidence_ligand(evidence_ligand)
        return self.session_id

    def close(self) -> None:
        self.controller.stop()
        self.client = None

    def is_alive(self) -> bool:
        """Cheap lifecycle check that does not mutate the viewer scene."""
        return bool(self.client is not None and self.controller.running)

    def _client(self) -> PymolSpikeClient:
        if self.client is None:
            raise PymolSpikeError("PyMOL viewer is not connected")
        return self.client

    def _registered(self, atom: AtomIdentity) -> RegisteredStructure:
        matches = [item for item in self.structures.values() if item.identity == atom.structure]
        if len(matches) != 1:
            raise ValueError("Selection atom does not map to exactly one registered structure")
        return matches[0]

    def _convert_atoms(self, values: list[dict[str, Any]]) -> list[AtomIdentity]:
        result = []
        for value in values:
            model = str(value.get("model", ""))
            if model not in self.structures:
                raise ValueError(f"PyMOL returned an unregistered model: {model}")
            result.append(AtomIdentity(
                self.structures[model].identity,
                str(value.get("segi", "")), str(value.get("chain", "")),
                str(value.get("residue_number", "")), str(value.get("insertion_code", "")),
                str(value.get("residue_name", "")), str(value.get("atom_name", "")),
                str(value.get("altloc", "")),
            ))
        return result
