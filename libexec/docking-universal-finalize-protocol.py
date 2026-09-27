#!/usr/bin/env python3
"""Finalize one GUI-approved site-guided protocol without rerunning preparation."""

from __future__ import annotations

import argparse
from pathlib import Path

from docking_universal.protocol_finalization import FinalizationSettings, request_from_study
from docking_universal.services.finalization import finalize_site_guided_protocol
from docking_universal.state import JsonStudyStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-root", type=Path, required=True)
    parser.add_argument("--study-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--engine", choices=("vina", "qvinaw"), default="vina")
    parser.add_argument("--ph", type=float, default=7.4)
    parser.add_argument("--conformers", type=int, default=3)
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--base-seed", type=int, default=20260808)
    parser.add_argument("--exhaustiveness", type=int, default=16)
    parser.add_argument("--num-modes", type=int, default=15)
    parser.add_argument("--energy-range", type=float, default=8.0)
    args = parser.parse_args()
    state = JsonStudyStore(args.state_root).load(args.study_id)
    settings = FinalizationSettings(
        engine=args.engine, ph=args.ph, conformers=args.conformers,
        seed_count=args.seeds, base_seed=args.base_seed,
        exhaustiveness=args.exhaustiveness, num_modes=args.num_modes,
        energy_range=args.energy_range,
    )
    request = request_from_study(
        state, settings, args.output, exploratory_use_approved=True,
    )
    outputs = finalize_site_guided_protocol(
        state, request, libexec=Path(__file__).resolve().parent,
    )
    print(f"Protocol: {outputs.protocol}")
    print(f"Report: {outputs.report}")
    print(f"Bundle: {outputs.bundle}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
