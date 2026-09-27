#!/usr/bin/env python3
"""Run the serialized Docking Universal application host over JSON lines."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from docking_universal.application import StudyController
from docking_universal.host import ApplicationHostLease, CommandDispatcher, HostAlreadyRunning, reconcile_interrupted_jobs, serve_json_lines
from docking_universal.state import JsonStudyStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--session-id")
    args = parser.parse_args()
    store = JsonStudyStore(args.state_root)
    dispatcher = CommandDispatcher(
        StudyController(store), args.session_id,
        preparation_executable=Path(__file__).with_name("docking-universal-prepare"),
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
                    "conda_environment": os.environ.get("CONDA_DEFAULT_ENV"),
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
