"""Feasibility controller for the required two-way PyMOL review bridge."""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import uuid4


PROTOCOL_VERSION = 1


class PymolSpikeError(RuntimeError):
    pass


def reserve_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


@dataclass
class PymolSpikeClient:
    port: int
    token: str
    timeout_seconds: float = 5.0

    def request(self, operation: str, payload: Mapping[str, Any] | None = None) -> dict[str, Any]:
        request_id = f"request-{uuid4().hex}"
        body = json.dumps({
            "version": PROTOCOL_VERSION,
            "request_id": request_id,
            "operation": operation,
            "payload": dict(payload or {}),
        }).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.port}/v1",
            data=body,
            headers={"Content-Type": "application/json", "X-Docking-Universal-Token": self.token},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                result = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                result = json.loads(exc.read())
            except json.JSONDecodeError:
                raise PymolSpikeError(f"PyMOL bridge request failed: HTTP {exc.code}") from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise PymolSpikeError(f"PyMOL bridge request failed: {exc}") from exc
        if result.get("request_id") != request_id:
            raise PymolSpikeError("PyMOL bridge returned a mismatched request ID")
        if result.get("status") != "ok":
            raise PymolSpikeError(str(result.get("error", "unknown PyMOL bridge error")))
        return dict(result.get("result") or {})


class PymolSpikeController:
    """Launch and supervise the spike bridge; production supervision is task 06."""

    def __init__(self, pymol: Path | str, bridge_script: Path | str, log_directory: Path | str):
        self.pymol = Path(pymol)
        self.bridge_script = Path(bridge_script)
        self.log_directory = Path(log_directory)
        self.process: subprocess.Popen | None = None
        self.client: PymolSpikeClient | None = None
        self._stdout = None
        self._stderr = None

    def start(self, *, headless: bool = False, timeout_seconds: float = 15.0) -> PymolSpikeClient:
        if self.process and self.process.poll() is None:
            raise PymolSpikeError("PyMOL spike is already running")
        if not self.pymol.is_file() or not self.bridge_script.is_file():
            raise PymolSpikeError("PyMOL executable and bridge script must exist")
        self.log_directory.mkdir(parents=True, exist_ok=True)
        self._stdout = (self.log_directory / "pymol-spike.stdout.log").open("w")
        self._stderr = (self.log_directory / "pymol-spike.stderr.log").open("w")
        port = reserve_local_port()
        token = secrets.token_urlsafe(32)
        environment = os.environ.copy()
        for name in ("QT_API", "QT_PLUGIN_PATH", "QML2_IMPORT_PATH", "PYTHONPATH"):
            environment.pop(name, None)
        environment.update({
            "DU_PYMOL_BRIDGE_HOST": "127.0.0.1",
            "DU_PYMOL_BRIDGE_PORT": str(port),
            "DU_PYMOL_BRIDGE_TOKEN": token,
        })
        command = [str(self.pymol), "-q"]
        if headless:
            command.extend(("-c", "-K"))
        command.extend(("-r", str(self.bridge_script)))
        self.process = subprocess.Popen(
            command,
            env=environment,
            stdout=self._stdout,
            stderr=self._stderr,
            start_new_session=os.name != "nt",
        )
        self.client = PymolSpikeClient(port=port, token=token)
        deadline = time.monotonic() + timeout_seconds
        last_error = "bridge did not respond"
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self._close_logs()
                raise PymolSpikeError(f"PyMOL exited before bridge handshake (status {self.process.returncode})")
            try:
                self.client.request("ping")
                return self.client
            except PymolSpikeError as exc:
                last_error = str(exc)
                time.sleep(0.1)
        self.stop()
        raise PymolSpikeError(f"Timed out waiting for PyMOL bridge: {last_error}")

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            try:
                if self.client:
                    self.client.request("close")
            except PymolSpikeError:
                pass
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait()
        self._close_logs()

    def _close_logs(self) -> None:
        for handle in (self._stdout, self._stderr):
            if handle and not handle.closed:
                handle.close()

    def __enter__(self) -> "PymolSpikeController":
        return self

    def __exit__(self, *_error: object) -> None:
        self.stop()


def run_spike(
    client: PymolSpikeClient,
    structure: Path | str,
    selections: Sequence[Mapping[str, str]],
    center: Sequence[float],
    size: Sequence[float],
) -> dict[str, Any]:
    loaded = client.request("load_structure", {"path": str(Path(structure).resolve()), "object_name": "du_receptor"})
    selected = client.request("apply_selection", {"name": "du_candidate", "residues": list(selections)})
    box = client.request("show_box", {"name": "du_box", "center": list(center), "size": list(size)})
    view = client.request("get_view")
    return {"loaded": loaded, "selection": selected, "box": box, "view": view}


def restore_spike(client: PymolSpikeClient, snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Replay the minimal review state after a viewer relaunch."""
    loaded = snapshot["loaded"]
    selected_atoms = snapshot["selection"]["atoms"]
    residues = []
    seen = set()
    for atom in selected_atoms:
        identity = {
            key: atom[key]
            for key in ("model", "segi", "chain", "residue_number", "insertion_code", "residue_name")
        }
        # The object is recreated with the same stable name during this spike.
        identity["model"] = loaded["object_name"]
        key = tuple(identity.items())
        if key not in seen:
            seen.add(key)
            residues.append(identity)
    client.request("load_structure", {"path": loaded["path"], "object_name": loaded["object_name"]})
    selection = client.request("apply_selection", {"name": snapshot["selection"]["name"], "residues": residues})
    box = client.request("show_box", snapshot["box"])
    view = client.request("set_view", snapshot["view"])
    return {"loaded": loaded, "selection": selection, "box": box, "view": view}
