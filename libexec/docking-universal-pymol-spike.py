#!/usr/bin/env python3
"""Run the required PyMOL two-way interaction feasibility spike."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path

from docking_universal.pymol_spike import PymolSpikeController, restore_spike, run_spike


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("structure", type=Path)
    parser.add_argument("--pymol", type=Path, required=True)
    parser.add_argument("--bridge", type=Path, default=Path(__file__).with_name("docking-universal-pymol-spike-bridge.py"))
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--chain", default="A")
    parser.add_argument("--residue", action="append", required=True, help="residue number, including insertion code")
    parser.add_argument("--pocket", type=Path, action="append", default=[], help="fpocket coordinate artifact to display")
    parser.add_argument("--center", type=float, nargs=3, default=(0.0, 0.0, 0.0))
    parser.add_argument("--size", type=float, nargs=3, default=(20.0, 20.0, 20.0))
    parser.add_argument("--log-directory", type=Path)
    parser.add_argument("--relaunch", action="store_true", help="close, relaunch, and restore the review state")
    args = parser.parse_args()
    log_directory = args.log_directory or Path(tempfile.mkdtemp(prefix="docking-universal-pymol-spike-"))
    residues = [{"chain": args.chain, "residue_number": value.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"), "insertion_code": value[len(value.rstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz")):]} for value in args.residue]
    snapshot = None
    with PymolSpikeController(args.pymol, args.bridge, log_directory) as controller:
        client = controller.start(headless=args.headless)
        result = run_spike(client, args.structure, residues, args.center, args.size, args.pocket)
        print(json.dumps({"status": "passed", "log_directory": str(log_directory), **result}, indent=2))
        if not args.headless:
            input("PyMOL is ready. Make a selection if desired, then press Return to inspect pk1 and close: ")
            try:
                print(json.dumps(client.request("get_selection", {"name": "pk1"}), indent=2))
            except Exception as exc:
                print(json.dumps({"picked_selection": "unavailable", "detail": str(exc)}, indent=2))
        snapshot = result
    if args.relaunch:
        with PymolSpikeController(args.pymol, args.bridge, log_directory) as controller:
            client = controller.start(headless=args.headless)
            restored = restore_spike(client, snapshot)
            print(json.dumps({"status": "restored_after_relaunch", **restored}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
