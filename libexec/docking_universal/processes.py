"""Cancellable external-process execution with complete retained logs."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping, Sequence

from .models import utc_now


class ProcessStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ProcessOutput:
    stream: str
    text: str


@dataclass(frozen=True)
class ProcessRequest:
    command: Sequence[str | os.PathLike[str]]
    log_directory: Path | str
    log_name: str
    cwd: Path | str | None = None
    environment: Mapping[str, str] | None = None
    timeout_seconds: float | None = None
    termination_grace_seconds: float = 2.0
    captured_tail_characters: int = 100_000
    check: bool = True


@dataclass(frozen=True)
class ProcessResult:
    command: tuple[str, ...]
    status: ProcessStatus
    returncode: int
    stdout_tail: str
    stderr_tail: str
    stdout_log: str
    stderr_log: str
    started_at: str
    finished_at: str
    duration_seconds: float


class ProcessExecutionError(RuntimeError):
    def __init__(self, result: ProcessResult):
        super().__init__(
            f"Command failed with status {result.status.value} and exit code {result.returncode}: "
            + " ".join(result.command)
        )
        self.result = result


class ProcessRunner:
    """Run one command without a shell and retain stdout and stderr in full."""

    def run(
        self,
        request: ProcessRequest,
        *,
        cancel_event: threading.Event | None = None,
        on_output: Callable[[ProcessOutput], None] | None = None,
        on_started: Callable[[int], None] | None = None,
        on_tick: Callable[[], None] | None = None,
    ) -> ProcessResult:
        tree = None
        if os.name == "nt":
            from .windows_job import WindowsProcessTree
            tree = WindowsProcessTree()
        try:
            return self._run(request, cancel_event=cancel_event, on_output=on_output,
                             on_started=on_started, on_tick=on_tick, tree=tree)
        finally:
            if tree:
                tree.close()

    def _run(self, request, *, cancel_event, on_output, on_started, on_tick, tree):
        command = tuple(str(value) for value in request.command)
        if not command:
            raise ValueError("A process request requires a command")
        if os.name == "nt":
            from .tool_commands import script_command
            command = tuple(script_command(command[0], *command[1:]))
        log_directory = Path(request.log_directory)
        log_directory.mkdir(parents=True, exist_ok=True)
        stdout_log = log_directory / f"{request.log_name}.stdout.log"
        stderr_log = log_directory / f"{request.log_name}.stderr.log"
        started_at = utc_now()
        started = time.monotonic()
        output: dict[str, list[str]] = {"stdout": [], "stderr": []}

        try:
            spawn = tree.spawn if tree else subprocess.Popen
            process = spawn(command,
                cwd=Path(request.cwd) if request.cwd is not None else None,
                env=dict(request.environment) if request.environment is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8", errors="replace",
                bufsize=1,
                start_new_session=os.name != "nt",
            )
        except BaseException:
            if tree:
                tree.close()
            raise
        if on_started:
            try:
                on_started(process.pid)
            except Exception:
                # A child without its durable process identity cannot safely be
                # left running. Stop it before returning the tracking failure.
                if tree:
                    tree.close()
                self._terminate(process, request.termination_grace_seconds)
                process.communicate()
                raise

        def consume(stream_name: str, stream, path: Path) -> None:
            with path.open("w", encoding="utf-8") as handle:
                for line in iter(stream.readline, ""):
                    handle.write(line)
                    handle.flush()
                    output[stream_name].append(line)
                    if on_output:
                        on_output(ProcessOutput(stream_name, line))
            stream.close()

        threads = [
            threading.Thread(target=consume, args=("stdout", process.stdout, stdout_log), daemon=True),
            threading.Thread(target=consume, args=("stderr", process.stderr, stderr_log), daemon=True),
        ]
        for thread in threads:
            thread.start()

        status = ProcessStatus.COMPLETED
        next_tick = 0.0
        try:
            while process.poll() is None:
                now = time.monotonic()
                if on_tick is not None and now >= next_tick:
                    on_tick()
                    next_tick = now + 0.5
                if cancel_event and cancel_event.is_set():
                    status = ProcessStatus.CANCELLED
                    if tree:
                        tree.close()
                    self._terminate(process, request.termination_grace_seconds)
                    break
                if request.timeout_seconds is not None and time.monotonic() - started >= request.timeout_seconds:
                    status = ProcessStatus.TIMED_OUT
                    if tree:
                        tree.close()
                    self._terminate(process, request.termination_grace_seconds)
                    break
                time.sleep(0.02)
            if on_tick is not None:
                on_tick()
            returncode = process.wait()
        except BaseException:
            if tree:
                tree.close()
            self._terminate(process, request.termination_grace_seconds)
            process.wait()
            raise
        finally:
            if tree:
                # Kill any grandchild that outlived a completed wrapper before
                # joining readers; inherited pipes must not hang shutdown.
                tree.close()
            for thread in threads:
                thread.join()
        if status is ProcessStatus.COMPLETED and returncode != 0:
            status = ProcessStatus.FAILED
        duration = time.monotonic() - started

        def tail(parts: list[str]) -> str:
            return "".join(parts)[-request.captured_tail_characters:]

        result = ProcessResult(
            command=command,
            status=status,
            returncode=returncode,
            stdout_tail=tail(output["stdout"]),
            stderr_tail=tail(output["stderr"]),
            stdout_log=str(stdout_log),
            stderr_log=str(stderr_log),
            started_at=started_at,
            finished_at=utc_now(),
            duration_seconds=round(duration, 6),
        )
        if request.check and status is not ProcessStatus.COMPLETED:
            raise ProcessExecutionError(result)
        return result

    @staticmethod
    def _terminate(process: subprocess.Popen, grace_seconds: float) -> None:
        if process.poll() is not None:
            return
        try:
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return
        deadline = time.monotonic() + max(0.0, grace_seconds)
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if process.poll() is None:
            try:
                if os.name != "nt":
                    os.killpg(process.pid, signal.SIGKILL)
                else:
                    process.kill()
            except ProcessLookupError:
                pass
