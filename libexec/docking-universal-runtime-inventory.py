#!/usr/bin/env python3
"""Print a read-only inventory for GUI and installation planning."""

from __future__ import annotations

import argparse
import json

from docking_universal.runtime_inventory import collect_runtime_inventory, render_runtime_inventory


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit the versioned machine-readable record")
    parser.add_argument("--main-environment", default="docking-universal")
    parser.add_argument("--vina-environment", default="docking-universal-vina")
    parser.add_argument("--qvinaw-environment", default="docking-universal-qvinaw")
    args = parser.parse_args()
    inventory = collect_runtime_inventory(
        main_environment=args.main_environment,
        vina_environment=args.vina_environment,
        qvinaw_environment=args.qvinaw_environment,
    )
    if args.json:
        print(json.dumps(inventory, indent=2, sort_keys=True))
    else:
        print(render_runtime_inventory(inventory), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
