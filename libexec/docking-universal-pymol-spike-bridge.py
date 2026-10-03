#!/usr/bin/env python3
"""Restricted localhost bridge loaded inside PyMOL for the GUI spike."""

from __future__ import annotations

import json
import math
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from pymol import cgo, cmd
from pymol.wizard import Wizard


PROTOCOL_VERSION = 1
SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
SAFE_SUFFIXES = {".pdb", ".pdbqt", ".mol2", ".sdf", ".pqr"}
# Match the report/GUI palette while keeping arbitrary expressions forbidden.
SAFE_COLORS = {"red", "marine", "gold", "magenta", "cyan", "orange", "violet", "salmon", "yellow"}


class BridgeCore:
    def __init__(self, pymol_cmd=cmd):
        self.cmd = pymol_cmd
        self.boxes: dict[str, dict[str, list[float]]] = {}
        self.pick_sequence = 0
        self.last_pick: dict[str, Any] | None = None

    @staticmethod
    def _name(value: Any) -> str:
        value = str(value)
        if not SAFE_NAME.fullmatch(value):
            raise ValueError("Names must begin with a letter and contain only letters, digits, and underscores")
        return value

    @staticmethod
    def _vector(value: Any, label: str, *, positive: bool = False) -> list[float]:
        if not isinstance(value, list) or len(value) != 3:
            raise ValueError(f"{label} must contain three numbers")
        result = [float(item) for item in value]
        if not all(math.isfinite(item) for item in result):
            raise ValueError(f"{label} values must be finite")
        if positive and not all(item > 0 for item in result):
            raise ValueError(f"{label} values must be positive")
        return result

    @staticmethod
    def _identity(atom: dict[str, Any]) -> dict[str, Any]:
        resi = str(atom.get("resi", ""))
        match = re.fullmatch(r"(-?\d+)(.*)", resi)
        return {
            "model": str(atom.get("model", "")),
            "segi": str(atom.get("segi", "")),
            "chain": str(atom.get("chain", "")),
            "residue_number": match.group(1) if match else resi,
            "insertion_code": match.group(2) if match else "",
            "residue_name": str(atom.get("resn", "")),
            "atom_name": str(atom.get("name", "")),
            "altloc": str(atom.get("alt", "")),
            "index": int(atom.get("index", 0)),
        }

    def _atoms(self, selection: str) -> list[dict[str, Any]]:
        rows: list[list[Any]] = []
        expression = "rows.append([model,segi,chain,resi,resn,name,alt,index])"
        self.cmd.iterate(selection, expression, space={"rows": rows})
        keys = ("model", "segi", "chain", "resi", "resn", "name", "alt", "index")
        return [dict(zip(keys, row)) for row in rows]

    def capture_pick(self) -> dict[str, Any]:
        picked = [self._identity(atom) for atom in self._atoms("pk1")]
        if not picked:
            raise ValueError("PyMOL did not provide a picked atom")
        self.cmd.select("du_user_pick", "byres pk1")
        residue = [self._identity(atom) for atom in self._atoms("du_user_pick")]
        self.cmd.show("sticks", "du_user_pick")
        self.cmd.color("yellow", "du_user_pick")
        self.pick_sequence += 1
        self.last_pick = {"sequence": self.pick_sequence, "picked_atoms": picked, "residue_atoms": residue}
        return self.last_pick

    def dispatch(self, operation: str, payload: dict[str, Any]) -> dict[str, Any]:
        if operation == "ping":
            return {"protocol_version": PROTOCOL_VERSION, "pymol_version": self.cmd.get_version()[0]}
        if operation == "load_structure":
            path = Path(str(payload.get("path", ""))).expanduser().resolve()
            name = self._name(payload.get("object_name", ""))
            if not path.is_file() or path.suffix.lower() not in SAFE_SUFFIXES:
                raise ValueError("Structure path does not name a supported existing file")
            self.cmd.load(str(path), name)
            return {"object_name": name, "path": str(path), "atoms": int(self.cmd.count_atoms(name))}
        if operation == "load_report_session":
            path = Path(str(payload.get("path", ""))).expanduser().resolve()
            if not path.is_file() or path.suffix.lower() != ".pse":
                raise ValueError("Report view must name an existing PyMOL session")
            if payload.get("replace") is True:
                self.cmd.delete("all")
            self.cmd.load(str(path))
            return {"path": str(path), "report_view_restored": True}
        if operation == "show_review_pose":
            path = Path(str(payload.get("path", ""))).expanduser().resolve()
            name = self._name(payload.get("object_name", "du_review_pose"))
            if not path.is_file() or path.suffix.lower() != ".sdf":
                raise ValueError("Review pose must name an existing retained SDF")
            self.cmd.delete(name)
            self.cmd.load(str(path), name)
            self.cmd.hide("everything", name)
            self.cmd.show("sticks", name)
            self.cmd.color("gray70", f"{name} and elem C")
            self.cmd.zoom(name, buffer=5)
            return {"object_name": name, "path": str(path), "atoms": int(self.cmd.count_atoms(name))}
        if operation == "show_evidence_ligand":
            path = Path(str(payload.get("path", ""))).expanduser().resolve()
            name = self._name(payload.get("object_name", "du_evidence_ligand"))
            if not path.is_file() or path.suffix.lower() != ".pdb":
                raise ValueError("Evidence ligand must name an existing retained PDB")
            receptor_path = Path(str(payload.get("receptor_path", ""))).expanduser().resolve()
            if receptor_path.is_file() and receptor_path.suffix.lower() in SAFE_SUFFIXES:
                # Rebuild from coordinates, rather than trying to identify every
                # generated surface/box object in an arbitrary report session.
                if hasattr(self.cmd, "reinitialize"):
                    self.cmd.reinitialize()
                else:
                    self.cmd.delete("all")
                self.cmd.load(str(receptor_path), "receptor")
            self.cmd.hide("everything", "all")
            # Report sessions may use generated names for cavity surfaces and
            # boxes, so pattern deletion alone is insufficient. Preserve the
            # receptor object and remove every other object before loading the
            # one evidence ligand requested by the user.
            if hasattr(self.cmd, "get_names"):
                for object_name in list(self.cmd.get_names("objects") or []):
                    if object_name != "receptor":
                        self.cmd.delete(object_name)
            self.cmd.show("cartoon", "receptor")
            self.cmd.color("gray70", "receptor")
            # Replace, rather than accumulate, experimental observations when
            # the user double-clicks different evidence rows.  The wildcard
            # also clears suffixed variants left by repeated scene loads.
            for stale_name in (
                f"{name}*", "supporting_ligand*", "representative_ligand*",
                "evidence_ligand*", "du_pocket*", "du_box*", "docking_box*",
                "selected_pocket*", "cavity_core*", "pocket_surface*",
            ):
                self.cmd.delete(stale_name)
            self.cmd.load(str(path), name)
            self.cmd.hide("everything", name)
            self.cmd.show("sticks", name)
            self.cmd.color("green", f"{name} and elem C")
            self.cmd.set("stick_radius", 0.32, name)
            # Recenter on the complete receptor so repeated evidence choices
            # never leave a ligand-only, tightly magnified camera.
            self.cmd.orient("receptor")
            self.cmd.zoom("receptor", buffer=12)
            self.cmd.set("clip_mode", 0)
            self.cmd.clip("near", 0)
            self.cmd.clip("far", 0)
            return {"object_name": name, "path": str(path), "atoms": int(self.cmd.count_atoms(name))}
        if operation == "show_evidence_ligands":
            paths = [Path(str(value)).expanduser().resolve() for value in (payload.get("paths") or [])]
            if not paths or any(not path.is_file() or path.suffix.lower() != ".pdb" for path in paths):
                raise ValueError("Evidence comparison requires existing retained PDB ligands")
            receptor_path = Path(str(payload.get("receptor_path", ""))).expanduser().resolve()
            if receptor_path.is_file() and receptor_path.suffix.lower() in SAFE_SUFFIXES:
                if hasattr(self.cmd, "reinitialize"):
                    self.cmd.reinitialize()
                else:
                    self.cmd.delete("all")
                self.cmd.load(str(receptor_path), "receptor")
            # Start from a clean evidence presentation.  Hiding everything
            # first guarantees stale surfaces/boxes cannot remain visible even
            # if a scene used an unexpected generated object name.
            self.cmd.hide("everything", "all")
            if hasattr(self.cmd, "get_names"):
                for object_name in list(self.cmd.get_names("objects") or []):
                    if object_name != "receptor":
                        self.cmd.delete(object_name)
            self.cmd.show("cartoon", "receptor")
            self.cmd.color("gray70", "receptor")
            for index, path in enumerate(paths, 1):
                name = f"du_evidence_ligand_{index}"
                self.cmd.load(str(path), name)
                self.cmd.hide("everything", name)
                self.cmd.show("sticks", name)
                self.cmd.color("green", f"{name} and elem C")
                self.cmd.set("stick_radius", 0.32, name)
            self.cmd.orient("receptor")
            self.cmd.zoom("receptor", buffer=12)
            self.cmd.set("clip_mode", 0)
            self.cmd.clip("near", 0)
            self.cmd.clip("far", 0)
            return {"object_names": [f"du_evidence_ligand_{index}" for index in range(1, len(paths) + 1)]}
        if operation == "sync_evidence_ligands":
            paths = [Path(str(value)).expanduser().resolve() for value in (payload.get("paths") or [])]
            if any(not path.is_file() or path.suffix.lower() != ".pdb" for path in paths):
                raise ValueError("Evidence selection contains a missing PDB")
            # Keep the report scene loaded, but visually push all prior content
            # into the background while the evidence browser has focus.
            self.cmd.hide("everything", "all")
            self.cmd.show("cartoon", "receptor")
            self.cmd.color("gray70", "receptor")
            # Keep the report receptor/pockets/boxes intact; only replace the
            # evidence objects managed by this interaction panel.
            for object_name in list(self.cmd.get_names("objects") or []):
                if object_name.startswith("du_evidence_ligand"):
                    self.cmd.delete(object_name)
            for index, path in enumerate(paths, 1):
                name = f"du_evidence_ligand_{index}"
                self.cmd.load(str(path), name)
                self.cmd.hide("everything", name)
                self.cmd.show("sticks", name)
                self.cmd.color("green", f"{name} and elem C")
                self.cmd.set("stick_radius", 0.32, name)
            return {"object_names": [f"du_evidence_ligand_{i}" for i in range(1, len(paths) + 1)]}
        if operation == "load_pocket":
            path = Path(str(payload.get("path", ""))).expanduser().resolve()
            name = self._name(payload.get("object_name", ""))
            color = str(payload.get("color", "cyan"))
            if not path.is_file() or path.suffix.lower() not in SAFE_SUFFIXES:
                raise ValueError("Pocket path does not name a supported existing coordinate file")
            if color not in SAFE_COLORS:
                raise ValueError("Pocket color is not supported")
            self.cmd.load(str(path), name)
            self.cmd.hide("everything", name)
            self.cmd.show("spheres", name)
            self.cmd.color(color, name)
            self.cmd.set("sphere_scale", 0.35, name)
            return {"object_name": name, "path": str(path), "atoms": int(self.cmd.count_atoms(name)), "color": color}
        if operation in {"apply_selection", "get_selection"}:
            name = self._name(payload.get("name", ""))
            if operation == "apply_selection":
                residues = payload.get("residues")
                if not isinstance(residues, list) or not residues:
                    raise ValueError("A nonempty residue list is required")
                allowed_fields = {
                    "model", "segi", "chain", "residue_number", "insertion_code",
                    "residue_name", "altloc",
                }
                for residue in residues:
                    if not isinstance(residue, dict) or not residue or not set(residue).issubset(allowed_fields):
                        raise ValueError("Residue selectors must contain only supported structural identity fields")
                all_atoms = self._atoms("all")
                matched = []
                for atom in all_atoms:
                    identity = self._identity(atom)
                    if any(all(str(identity.get(key, "")) == str(value) for key, value in residue.items()) for residue in residues):
                        matched.append(atom)
                if not matched:
                    raise ValueError("Selection identities did not match any loaded atoms")
                temporary = []
                for sequence, model in enumerate(sorted({str(atom["model"]) for atom in matched})):
                    temp_name = f"du_temp_{sequence}"
                    indices = [int(atom["index"]) for atom in matched if atom["model"] == model]
                    self.cmd.select_list(temp_name, model, indices, mode="index")
                    temporary.append(temp_name)
                self.cmd.select(name, " or ".join(temporary))
                for temp_name in temporary:
                    self.cmd.delete(temp_name)
                self.cmd.show("sticks", name)
                self.cmd.color("yellow", name)
            elif name not in self.cmd.get_names("selections"):
                raise ValueError(f"Selection does not exist: {name}")
            return {"name": name, "atoms": [self._identity(atom) for atom in self._atoms(name)]}
        if operation == "show_box":
            name = self._name(payload.get("name", ""))
            center = self._vector(payload.get("center"), "center")
            size = self._vector(payload.get("size"), "size", positive=True)
            color_name = str(payload.get("color", "red"))
            colors = {
                "red": (1.0, 0.0, 0.0), "marine": (0.0, 0.5, 1.0),
                "gold": (1.0, 0.65, 0.0), "magenta": (1.0, 0.0, 1.0),
                "cyan": (0.0, 1.0, 1.0), "orange": (1.0, 0.5, 0.0),
                "violet": (0.56, 0.37, 0.6),
            }
            if color_name not in colors:
                raise ValueError(f"Unsupported docking-box color: {color_name}")
            source_object_name = payload.get("source_object_name")
            if source_object_name is not None:
                source_object_name = self._name(str(source_object_name))
            redundant_object_names = [
                self._name(str(item)) for item in payload.get("redundant_object_names", [])
            ]
            visible_associated = {
                self._name(str(item))
                for item in payload.get("visible_associated_object_names", [])
            }
            associated_objects = [
                object_name for object_name in self.cmd.get_names("objects")
                if object_name == "ligand_site_representative"
                or object_name.startswith("ligand_site_representative_")
            ]
            for object_name in associated_objects:
                if object_name in visible_associated:
                    self.cmd.enable(object_name)
                else:
                    self.cmd.disable(object_name)
            previous_source = self.boxes.get(name, {}).get("replaces")
            if previous_source and previous_source in self.cmd.get_names("objects"):
                self.cmd.enable(previous_source)
            if source_object_name and source_object_name in self.cmd.get_names("objects"):
                self.cmd.disable(source_object_name)
            hidden_redundant = list(self.boxes.get(name, {}).get("hides_redundant", []))
            for object_name in redundant_object_names:
                if object_name in self.cmd.get_names("objects"):
                    self.cmd.disable(object_name)
                    if object_name not in hidden_redundant:
                        hidden_redundant.append(object_name)
            low = [center[index] - size[index] / 2.0 for index in range(3)]
            high = [center[index] + size[index] / 2.0 for index in range(3)]
            corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
            edges = [(a, b) for a in range(8) for b in range(a + 1, 8) if sum(corners[a][i] != corners[b][i] for i in range(3)) == 1]
            graphic = [cgo.BEGIN, cgo.LINES, cgo.COLOR, *colors[color_name]]
            for first, second in edges:
                graphic.extend((cgo.VERTEX, *corners[first], cgo.VERTEX, *corners[second]))
            graphic.append(cgo.END)
            self.cmd.delete(name)
            self.cmd.load_cgo(graphic, name)
            self.boxes[name] = {
                "center": center, "size": size, "color": color_name,
                "replaces": source_object_name,
                "hides_redundant": hidden_redundant,
                "visible_associated": sorted(visible_associated),
            }
            return {"name": name, **self.boxes[name]}
        if operation == "get_view":
            return {"view": list(self.cmd.get_view())}
        if operation == "set_view":
            view = payload.get("view")
            if not isinstance(view, list) or len(view) != 18 or not all(math.isfinite(float(item)) for item in view):
                raise ValueError("view must contain 18 finite numbers")
            self.cmd.set_view([float(item) for item in view])
            return {"view": list(self.cmd.get_view())}
        if operation == "start_pick":
            self.last_pick = None
            self.cmd.set_wizard(DockingUniversalPickWizard(self))
            self.cmd.refresh_wizard()
            return {"waiting_for_pick": True, "after_sequence": self.pick_sequence}
        if operation == "get_pick":
            return {"pick": self.last_pick, "sequence": self.pick_sequence}
        if operation == "stop_pick":
            self.cmd.set_wizard()
            self.cmd.refresh_wizard()
            return {"waiting_for_pick": False}
        if operation == "close":
            threading.Timer(0.1, self.cmd.quit).start()
            return {"closing": True}
        raise ValueError(f"Unsupported operation: {operation}")


class DockingUniversalPickWizard(Wizard):
    def __init__(self, core: BridgeCore):
        super().__init__(_self=core.cmd)
        self.core = core

    def get_prompt(self):
        return ["Docking Universal: click an atom to select its complete residue."]

    def get_panel(self):
        return [[1, "Docking Universal residue selection", ""], [2, "Cancel selection", "cmd.set_wizard()"]]

    def do_pick(self, _bond_flag):
        try:
            self.core.capture_pick()
        finally:
            self.cmd.unpick()
            self.cmd.refresh_wizard()
        return 1


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "DockingUniversalPyMOLSpike/1"

    def log_message(self, _format: str, *_args: object) -> None:
        return

    def do_POST(self) -> None:
        if self.path != "/v1" or self.headers.get("X-Docking-Universal-Token") != self.server.token:
            self.send_error(404)
            return
        request_id = None
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > 1_000_000:
                raise ValueError("Invalid request size")
            request = json.loads(self.rfile.read(length))
            request_id = request.get("request_id")
            if request.get("version") != PROTOCOL_VERSION or not request_id:
                raise ValueError("Unsupported protocol version or missing request ID")
            operation = str(request.get("operation", ""))
            payload = dict(request.get("payload") or {})
            result = self.server.call(lambda: self.server.core.dispatch(operation, payload))
            response = {"version": PROTOCOL_VERSION, "request_id": request_id, "status": "ok", "result": result}
            status = 200
        except Exception as exc:
            response = {"version": PROTOCOL_VERSION, "request_id": request_id, "status": "error", "error": str(exc)}
            status = 400
        body = json.dumps(response).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class BridgeServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], token: str, core: BridgeCore, call):
        super().__init__(address, BridgeHandler)
        self.token = token
        self.core = core
        self.call = call


def start_from_environment() -> BridgeServer:
    host = os.environ.get("DU_PYMOL_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ["DU_PYMOL_BRIDGE_PORT"])
    token = os.environ["DU_PYMOL_BRIDGE_TOKEN"]
    if host not in {"127.0.0.1", "localhost"} or len(token) < 32:
        raise RuntimeError("Refusing insecure PyMOL bridge configuration")
    if os.environ.get("DU_PYMOL_BRIDGE_HEADLESS") == "1":
        call = lambda operation: operation()
    else:
        # PyMOL supplies this compatibility helper for Qt 5 and older bindings.
        # The object is created while the startup script is on PyMOL's GUI
        # thread; bridge requests block their worker until GUI work completes.
        from pymol.Qt.utils import MainThreadCaller
        call = MainThreadCaller()
    server = BridgeServer((host, port), token, BridgeCore(), call)
    thread = threading.Thread(target=server.serve_forever, name="du-pymol-spike", daemon=True)
    thread.start()
    print(f"Docking Universal PyMOL spike bridge listening on {host}:{port}")
    return server


SERVER = (
    start_from_environment()
    if os.environ.get("DU_PYMOL_BRIDGE_PORT") and os.environ.get("DU_PYMOL_BRIDGE_TOKEN")
    else None
)
