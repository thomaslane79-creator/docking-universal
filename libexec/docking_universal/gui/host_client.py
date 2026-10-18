"""Supervised JSON-lines client for the sole application-host process."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..viewer.messages import Command
from ..runtime_layout import prefix_for_python, executable_directories


class ApplicationHostError(RuntimeError):
    pass


class ApplicationHostClient:
    def __init__(
        self,
        state_root: Path | str,
        host_script: Path | str,
        *,
        python_executable: Path | str | None = None,
        timeout_seconds: float = 5.0,
    ):
        self.state_root = Path(state_root).resolve()
        self.host_script = Path(host_script).resolve()
        self.python_executable = Path(python_executable or sys.executable).resolve()
        self.timeout_seconds = timeout_seconds
        self.process: subprocess.Popen | None = None
        self.session_id: str | None = None
        self.runtime: dict[str, Any] = {}
        self._lock = threading.Lock()
        self._log = None
        self._messages = None
        self._reader = None
        self._reader_stop = None
        self._process_tree = None

    @property
    def connected(self) -> bool:
        return bool(
            self.process is not None
            and self.process.poll() is None
            and self.session_id
        )

    def restart(self) -> str:
        """Replace a failed host without changing persisted study state."""
        with self._lock:
            self.close()
            return self.start()

    def start(self) -> str:
        if self.process and self.process.poll() is None:
            raise ApplicationHostError("Application host is already connected")
        if self.process:
            self.close()
        if not self.host_script.is_file():
            raise FileNotFoundError(f"Application host script is missing: {self.host_script}")
        if not self.python_executable.is_file():
            raise FileNotFoundError(f"Application host Python is missing: {self.python_executable}")
        self.state_root.mkdir(parents=True, exist_ok=True)
        self._log = (self.state_root / "application-host.stderr.log").open("a", encoding="utf-8")
        try:
            if os.name == "nt":
                from ..windows_job import WindowsProcessTree
                self._process_tree = WindowsProcessTree()
            spawn = self._process_tree.spawn if self._process_tree else subprocess.Popen
            self.process = spawn(
                [str(self.python_executable), str(self.host_script), "--state-root", str(self.state_root)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._log,
                text=True, encoding="utf-8", bufsize=1,
                env=self._environment(), start_new_session=os.name != "nt",
            )
            self._start_reader()
            ready = self._read_message()
        except BaseException:
            self.close()
            raise
        if ready.get("type") != "ready" or not ready.get("session_id"):
            self.close()
            raise ApplicationHostError(f"Application host did not become ready: {ready}")
        runtime = ready.get("runtime")
        if not isinstance(runtime, dict) or not runtime.get("python_executable"):
            self.close()
            raise ApplicationHostError("Application host omitted its runtime identity")
        observed_python = Path(str(runtime["python_executable"])).resolve()
        if observed_python != self.python_executable:
            self.close()
            raise ApplicationHostError(
                f"Application host used unexpected Python: {observed_python}"
            )
        self.runtime = dict(runtime)
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
            try:
                self.process.stdin.write(json.dumps(command.to_dict(), sort_keys=True) + "\n")
                self.process.stdin.flush()
            except OSError as exc:
                self.close()
                raise ApplicationHostError("Application host command stream closed; reconnect before continuing") from exc
            # Indexing a large local library is asynchronous in the GUI and may
            # legitimately exceed the ordinary short command-response timeout.
            response = self._read_message(timeout_seconds=max(120.0, self.timeout_seconds)
                                          if operation in {'inspect_ligand_library', 'inspect_protocol_bundle', 'import_protocol_bundle'} else None)
            if response.get("request_id") != command.request_id:
                self.close()
                raise ApplicationHostError("Application host returned a mismatched request ID")
            if response.get("status") not in {"applied", "replayed"}:
                raise ApplicationHostError(str(response.get("error") or "Application host rejected the request"))
            return response

    def close(self) -> None:
        process = self.process
        self.process = None
        tree, self._process_tree = self._process_tree, None
        self.session_id = None
        self.runtime = {}
        reader, stop, messages = self._reader, self._reader_stop, self._messages
        self._reader = self._reader_stop = self._messages = None
        if stop:
            stop.set()
        if messages is not None:
            try:
                messages.put_nowait(None)
            except queue.Full:
                pass
        if process:
            if process.stdin and not process.stdin.closed:
                try:
                    process.stdin.close()
                except OSError:
                    pass  # A crashed host may already have closed its pipe.
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if tree:
                    tree.close()
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            if tree:
                tree.close()
            if reader:
                reader.join(timeout=2)
            elif process.stdout:
                process.stdout.close()
        if tree:
            tree.close()
        if self._log and not self._log.closed:
            self._log.close()

    def _start_reader(self) -> None:
        # Windows select() only supports sockets, not subprocess pipes. One
        # session-owned reader frames complete lines before waking the client;
        # a partial line must not defeat the request timeout on any platform.
        stream = self.process.stdout
        messages = queue.Queue(maxsize=16)
        stop = threading.Event()
        self._messages, self._reader_stop = messages, stop

        def deliver(value):
            while not stop.is_set():
                try:
                    messages.put(value, timeout=0.1)
                    return
                except queue.Full:
                    pass

        def consume():
            try:
                while not stop.is_set():
                    # Replies can legitimately contain a large compound-library
                    # index. Do not apply the host's 1 MB *command* limit here.
                    line = stream.readline()
                    if not line:
                        deliver(None)
                        return
                    if not line.endswith("\n"):
                        deliver(ApplicationHostError("Application host emitted an incomplete response frame"))
                        return
                    deliver(line)
            except (OSError, UnicodeError) as exc:
                deliver(ApplicationHostError(f"Application host response stream failed: {exc}"))
            finally:
                stream.close()

        self._reader = threading.Thread(target=consume, name="application-host-reader", daemon=True)
        self._reader.start()

    def _read_message(self, timeout_seconds=None) -> dict[str, Any]:
        process, messages = self.process, self._messages
        if not process or messages is None:
            raise ApplicationHostError("Application host output is unavailable")
        def disconnect():
            # An older request interrupted by close must never tear down a new
            # session opened by another UI action.
            if self.process is process:
                self.close()
        try:
            line = messages.get(timeout=self.timeout_seconds if timeout_seconds is None else timeout_seconds)
        except queue.Empty as exc:
            # Never reuse a timed-out session: a delayed reply could otherwise
            # be mistaken for the acknowledgement of the next mutation.
            disconnect()
            raise ApplicationHostError("Timed out waiting for the application host; reconnect before continuing") from exc
        if isinstance(line, Exception):
            disconnect()
            raise line
        if not line:
            code = process.poll()
            disconnect()
            raise ApplicationHostError(f"Application host closed its response stream (status {code})")
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            disconnect()
            raise ApplicationHostError("Application host emitted an invalid response frame") from exc
        if not isinstance(value, dict):
            disconnect()
            raise ApplicationHostError("Application host response must be an object")
        return value

    def _environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        package_root = str(self.host_script.parent)
        current = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = package_root + (os.pathsep + current if current else "")
        # The GUI may itself have been launched with an explicit PyQt Python.
        # Scientific Bash workers must instead inherit the supervised host's
        # exact interpreter so `python3` resolution cannot escape to the OS or
        # back into the GUI environment.
        environment["DOCKING_UNIVERSAL_PYTHON"] = str(self.python_executable)
        environment["PYTHONIOENCODING"] = "utf-8"
        prefix = prefix_for_python(self.python_executable)
        scientific_cli = prefix / ("Scripts/docking-universal.cmd" if os.name == "nt" else "bin/docking-universal")
        if scientific_cli.is_file() and not environment.get('DOCKING_UNIVERSAL_CLI'):
            environment["DOCKING_UNIVERSAL_CLI"] = str(scientific_cli)
        runtime_paths = executable_directories(prefix)
        environment["PATH"] = os.pathsep.join(
            [str(path) for path in runtime_paths if path.is_dir()]
            + [environment.get("PATH", "")]
        )
        p2rank = prefix / "share" / "docking-universal" / "p2rank-2.5.1" / (
            "prank.bat" if os.name == "nt" else "prank"
        )
        if p2rank.is_file():
            environment["DOCKING_UNIVERSAL_P2RANK"] = str(p2rank)
        return environment

    def __enter__(self) -> "ApplicationHostClient":
        self.start()
        return self

    def __exit__(self, *_error: object) -> None:
        self.close()
