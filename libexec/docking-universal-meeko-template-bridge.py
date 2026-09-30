#!/usr/bin/env python3
"""Inspect or generate reviewed Meeko templates from local public definitions."""

from __future__ import annotations

import argparse
import json

from docking_universal.services.meeko_template_bridge import (
    generate_reviewed_polymer_templates,
    installed_meeko_missing_components,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("components", nargs="+")
    parser.add_argument("--list-missing", action="store_true")
    parser.add_argument("--geostd-library")
    parser.add_argument("--ccd-cache")
    parser.add_argument("--output-json")
    parser.add_argument("--audit-json")
    args = parser.parse_args(argv)
    if args.list_missing:
        print(json.dumps({
            "missing_components": list(installed_meeko_missing_components(args.components)),
        }, sort_keys=True))
        return 0
    required = {
        "--geostd-library": args.geostd_library,
        "--ccd-cache": args.ccd_cache,
        "--output-json": args.output_json,
        "--audit-json": args.audit_json,
    }
    absent = [name for name, value in required.items() if not value]
    if absent:
        parser.error("generation requires " + ", ".join(absent))
    record = generate_reviewed_polymer_templates(
        args.components,
        geostd_library=args.geostd_library,
        ccd_cache=args.ccd_cache,
        output_json=args.output_json,
        audit_json=args.audit_json,
    )
    print(json.dumps(record, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
