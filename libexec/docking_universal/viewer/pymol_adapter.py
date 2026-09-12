"""Supervised PyMOL adapter using stable viewer-neutral identities."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
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

    def __init__(self, pymol: Path | str, bridge_script: Path | str, log_directory: Path | str):
        self.controller = PymolSpikeController(pymol, bridge_script, log_directory)
        self.client: PymolSpikeClient | None = None
        self.session_id = f"viewer-{uuid4().hex}"
        self.structures: dict[str, RegisteredStructure] = {}
        self.snapshot: dict[str, Any] = {"structures": [], "pockets": [], "selections": {}, "box": None, "view": None}

    def launch(self, *, headless: bool = False) -> str:
        self.client = self.controller.start(headless=headless)
        return self.session_id

    def register_structure(self, structure: RegisteredStructure) -> dict[str, Any]:
        client = self._client()
        if structure.object_name in self.structures and self.structures[structure.object_name] != structure:
            raise ValueError(f"PyMOL object name is already registered: {structure.object_name}")
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
        result = self._client().request("load_pocket", {
            "path": str(Path(path).resolve()), "object_name": object_name, "color": color,
        })
        retained = {"path": result["path"], "object_name": object_name, "color": color}
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

    def show_box(self, center, size) -> dict[str, Any]:
        result = self._client().request("show_box", {"name": "du_box", "center": list(center), "size": list(size)})
        self.snapshot["box"] = result
        return result

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
        self.structures.clear()
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
        return self.session_id

    def close(self) -> None:
        self.controller.stop()
        self.client = None

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
