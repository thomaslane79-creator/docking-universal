#!/usr/bin/env python3
"""Write a structured receptor-preparation intervention record."""

from __future__ import annotations

import argparse
from pathlib import Path

from docking_universal.services.preparation_interventions import write_intervention_record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--diagnosis", type=Path, required=True)
    parser.add_argument("--filtered-receptor", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--ambiguous-histidine", default="")
    parser.add_argument("--diagnostic-log", type=Path, action="append", default=[])
    parser.add_argument("--source-mmcif", type=Path)
    args = parser.parse_args()
    write_intervention_record(
        args.diagnosis, args.filtered_receptor, args.output,
        ambiguous_histidine=args.ambiguous_histidine,
        diagnostic_logs=args.diagnostic_log,
        source_mmcif=args.source_mmcif,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
