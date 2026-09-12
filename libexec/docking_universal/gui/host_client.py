"""Supervised JSON-lines client for the sole application-host process."""

from __future__ import annotations

import json
import os
import selectors
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..viewer.messages import Command


class ApplicationHostError(RuntimeError):
    pass


class ApplicationHostClient:
    def __init__(self, state_root: Path | str, host_script: Path | str, *, timeout_seconds: float = 5.0):
        self.state_root = Path(state_root).resolve()
        self.host_script = Path(host_script).resolve()
        self.timeout_seconds = timeout_seconds
        self.process: subprocess.Popen | None = None
        self.session_id: str | None = None
        self._lock = threading.Lock()
        self._log = None

    def start(self) -> str:
        if self.process and self.process.poll() is None:
            raise ApplicationHostError("Application host is already connected")
        if not self.host_script.is_file():
            raise FileNotFoundError(f"Application host script is missing: {self.host_script}")
        self.state_root.mkdir(parents=True, exist_ok=True)
        self._log = (self.state_root / "application-host.stderr.log").open("a")
        self.process = subprocess.Popen(
            [sys.executable, str(self.host_script), "--state-root", str(self.state_root)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log, text=True, bufsize=1,
            env=self._environment(), start_new_session=os.name != "nt",
        )
        ready = self._read_message()
        if ready.get("type") != "ready" or not ready.get("session_id"):
            self.close()
            raise ApplicationHostError(f"Application host did not become ready: {ready}")
        self.session_id = str(ready["session_id"])
        return self.session_id

    def request(
        self,
        study_id: str,
        operation: str,
        payload: dict[str, Any] | None = None,
        *,
        expected_revision: int | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if not self.process or self.process.poll() is not None or not self.session_id:
                raise ApplicationHostError("Application host is not connected")
            command = Command(
                study_id, self.session_id, request_id or f"request-{uuid4().hex}",
                operation, payload or {}, expected_revision,
            )
            self.process.stdin.write(json.dumps(command.to_dict(), sort_keys=True) + "\n")
            self.process.stdin.flush()
            response = self._read_message()
            if response.get("request_id") != command.request_id:
                raise ApplicationHostError("Application host returned a mismatched request ID")
            if response.get("status") not in {"applied", "replayed"}:
                raise ApplicationHostError(str(response.get("error") or "Application host rejected the request"))
            return response

    def close(self) -> None:
        process = self.process
        self.process = None
        self.session_id = None
        if process:
            if process.stdin and not process.stdin.closed:
                process.stdin.close()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if process.stdout:
                process.stdout.close()
        if self._log and not self._log.closed:
            self._log.close()

    def _read_message(self) -> dict[str, Any]:
        if not self.process or not self.process.stdout:
            raise ApplicationHostError("Application host output is unavailable")
        selector = selectors.DefaultSelector()
        try:
            selector.register(self.process.stdout, selectors.EVENT_READ)
            if not selector.select(self.timeout_seconds):
                raise ApplicationHostError("Timed out waiting for the application host")
            line = self.process.stdout.readline()
        finally:
            selector.close()
        if not line:
            code = self.process.poll()
            raise ApplicationHostError(f"Application host closed its response stream (status {code})")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ApplicationHostError("Application host emitted an invalid response frame") from exc
        if not isinstance(value, dict):
            raise ApplicationHostError("Application host response must be an object")
        return value

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        package_root = str(self.host_script.parent)
        current = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = package_root + (os.pathsep + current if current else "")
        return environment

    def __enter__(self) -> "ApplicationHostClient":
        self.start()
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()
