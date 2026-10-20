#!/usr/bin/env python3
"""Run the strict installed native preparation path as a supervised desktop job."""
from pathlib import Path
import os
import sys

from docking_universal.windows_desktop import installed_host, installed_capabilities, preparation_options
from docking_universal.native_preparation import prepare_native_candidate


def main():
    if os.name != "nt" or len(sys.argv) != 2:
        raise ValueError("This internal service requires native Windows and one structure argument")
    app = Path(__file__).resolve().parent
    print("Native preparation service: verifying runtime", flush=True)
    runtime = installed_host(app)
    if runtime is None:
        raise ValueError("The native desktop scientific workflow is not configured")
    _script, environment, receipt = runtime
    allow_ligand = 'ligand' in installed_capabilities(app, os.environ)['supported_site_modes']
    options = preparation_options(sys.argv[1], Path.cwd(), os.environ, allow_ligand=allow_ligand)
    os.environ.update(environment)
    print("Native preparation service: starting preparation", flush=True)
    prepare_native_candidate(options, p2rank=Path(receipt["p2rank"]), java=Path(receipt["java"]), libexec=app,
                             allow_ligand=allow_ligand)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Native preparation stopped: {exc}", file=sys.stderr)
        raise SystemExit(1)
