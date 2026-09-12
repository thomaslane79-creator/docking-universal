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


PROTOCOL_VERSION = 1
SAFE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
SAFE_SUFFIXES = {".pdb", ".pdbqt", ".mol2", ".sdf", ".pqr"}
SAFE_COLORS = {"cyan", "marine", "orange", "salmon", "yellow", "violet"}


class BridgeCore:
    def __init__(self, pymol_cmd=cmd):
        self.cmd = pymol_cmd
        self.boxes: dict[str, dict[str, list[float]]] = {}

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
            low = [center[index] - size[index] / 2.0 for index in range(3)]
            high = [center[index] + size[index] / 2.0 for index in range(3)]
            corners = [(x, y, z) for x in (low[0], high[0]) for y in (low[1], high[1]) for z in (low[2], high[2])]
            edges = [(a, b) for a in range(8) for b in range(a + 1, 8) if sum(corners[a][i] != corners[b][i] for i in range(3)) == 1]
            graphic = [cgo.BEGIN, cgo.LINES, cgo.COLOR, 0.2, 0.8, 1.0]
            for first, second in edges:
                graphic.extend((cgo.VERTEX, *corners[first], cgo.VERTEX, *corners[second]))
            graphic.append(cgo.END)
            self.cmd.delete(name)
            self.cmd.load_cgo(graphic, name)
            self.boxes[name] = {"center": center, "size": size}
            return {"name": name, **self.boxes[name]}
        if operation == "get_view":
            return {"view": list(self.cmd.get_view())}
        if operation == "set_view":
            view = payload.get("view")
            if not isinstance(view, list) or len(view) != 18 or not all(math.isfinite(float(item)) for item in view):
                raise ValueError("view must contain 18 finite numbers")
            self.cmd.set_view([float(item) for item in view])
            return {"view": list(self.cmd.get_view())}
        if operation == "close":
            threading.Timer(0.1, self.cmd.quit).start()
            return {"closing": True}
        raise ValueError(f"Unsupported operation: {operation}")


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
            result = self.server.core.dispatch(str(request.get("operation", "")), dict(request.get("payload") or {}))
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
    def __init__(self, address: tuple[str, int], token: str, core: BridgeCore):
        super().__init__(address, BridgeHandler)
        self.token = token
        self.core = core


def start_from_environment() -> BridgeServer:
    host = os.environ.get("DU_PYMOL_BRIDGE_HOST", "127.0.0.1")
    port = int(os.environ["DU_PYMOL_BRIDGE_PORT"])
    token = os.environ["DU_PYMOL_BRIDGE_TOKEN"]
    if host not in {"127.0.0.1", "localhost"} or len(token) < 32:
        raise RuntimeError("Refusing insecure PyMOL bridge configuration")
    server = BridgeServer((host, port), token, BridgeCore())
    thread = threading.Thread(target=server.serve_forever, name="du-pymol-spike", daemon=True)
    thread.start()
    print(f"Docking Universal PyMOL spike bridge listening on {host}:{port}")
    return server


SERVER = (
    start_from_environment()
    if os.environ.get("DU_PYMOL_BRIDGE_PORT") and os.environ.get("DU_PYMOL_BRIDGE_TOKEN")
    else None
)
