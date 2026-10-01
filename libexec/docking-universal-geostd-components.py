#!/usr/bin/env python3
"""Plan or perform explicitly approved GeoStd component retrieval."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from docking_universal.services.geostd_components import (
    bundled_minimal_library,
    download_components,
    missing_components,
    network_disclosure,
    reduce2_required_component_ids,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-pdb", type=Path, help="filtered receptor PDB to inspect")
    parser.add_argument("--component", action="append", default=[], help="explicit component ID")
    parser.add_argument("--library", type=Path, help="writable minimal-library/cache destination")
    parser.add_argument("--download", action="store_true", help="perform the disclosed requests")
    parser.add_argument(
        "--approve-network-disclosure", action="store_true",
        help="confirm that the displayed component IDs and connection metadata may be shared",
    )
    parser.add_argument("--output-json", type=Path)
    args = parser.parse_args(argv)
    components = list(args.component)
    if args.input_pdb:
        components.extend(reduce2_required_component_ids(args.input_pdb))
    reference = args.library if args.library and args.library.is_dir() else bundled_minimal_library()
    requested = missing_components(reference, components)
    if args.download:
        if args.library is None:
            parser.error("--library is required with --download")
        record = download_components(
            requested, args.library, approved=args.approve_network_disclosure,
        )
    else:
        record = network_disclosure(requested)
    text = json.dumps(record, indent=2) + "\n"
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(text)
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
