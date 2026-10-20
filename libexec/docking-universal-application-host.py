#!/usr/bin/env python3
"""Run the serialized Docking Universal application host over JSON lines."""

from __future__ import annotations

import argparse
import json
import os
import sys
from functools import partial
from pathlib import Path

from docking_universal.application import StudyController
from docking_universal.host import ApplicationHostLease, CommandDispatcher, HostAlreadyRunning, reconcile_interrupted_jobs, serve_json_lines
from docking_universal.state import JsonStudyStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--session-id")
    args = parser.parse_args()
    preparation = None if os.name == "nt" else Path(__file__).with_name("docking-universal-prepare")
    guard = None
    capabilities = {"scientific_stages_supported": os.name != "nt"}
    if os.name == "nt":
        from docking_universal.windows_desktop import installed_host, workflow_guard, installed_capabilities
        try:
            native = installed_host(Path(__file__).resolve().parent)
            if native is not None:
                preparation, environment, _receipt = native
                os.environ.update(environment)
                capabilities = installed_capabilities(Path(__file__).resolve().parent, environment)
                guard = partial(workflow_guard, supported_engines=tuple(capabilities['supported_engines']))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            print(json.dumps({"type": "fatal", "error": str(exc)}), file=sys.stderr)
            return 2
    store = JsonStudyStore(args.state_root)
    dispatcher = CommandDispatcher(
        StudyController(store), args.session_id,
        preparation_executable=preparation, workflow_guard=guard,
    )
    try:
        with ApplicationHostLease(args.state_root):
            interrupted = reconcile_interrupted_jobs(store)
            print(json.dumps({
                "type": "ready", "version": 1, "session_id": dispatcher.session_id,
                "interrupted_jobs": interrupted,
                "runtime": {
                    "python_executable": str(Path(sys.executable).resolve()),
                    "python_version": ".".join(str(value) for value in sys.version_info[:3]),
                    # A directly launched interpreter can inherit the terminal's
                    # Conda label. Report the environment actually serving jobs.
                    "conda_environment": (
                        Path(sys.prefix).name
                        if (Path(sys.prefix) / "conda-meta").is_dir() else None
                    ),
                    "python_prefix": sys.prefix,
                    **capabilities,
                },
            }), flush=True)
            serve_json_lines(dispatcher, sys.stdin, sys.stdout)
    except HostAlreadyRunning as exc:
        print(json.dumps({"type": "fatal", "error": str(exc)}), file=sys.stderr)
        return 2
    finally:
        dispatcher.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
