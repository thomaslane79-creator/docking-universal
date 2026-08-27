#!/usr/bin/env python
"""Evaluate ensemble redocking as sampling and ranking controls.

Sampling asks whether any pose recovers the reference; ranking asks whether the
lowest-energy pose does. Approval requires both across the required seeds and
locks receptor/box hashes. It does not establish prospective accuracy.
"""

import argparse
import hashlib
from importlib import metadata
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def package_version():
    root = Path(__file__).resolve().parent
    for path in (root / "VERSION", root.parent / "VERSION"):
        if path.is_file():
            return path.read_text().strip()
    return "not detected"


def distribution_version(*names):
    for name in names:
        try:
            return metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return "not detected"


def engine_version(engine):
    executable = shutil.which(engine)
    command = [executable, "--version"] if executable else []
    source = executable or "not detected"
    if not command:
        conda = shutil.which("conda")
        environment_defaults = {
            "vina": ("DOCKING_UNIVERSAL_VINA_ENV", "docking-universal-vina"),
            "qvinaw": ("DOCKING_UNIVERSAL_QVINAW_ENV", "docking-universal-qvinaw"),
        }
        environment_variable, default_environment = environment_defaults.get(engine, ("", ""))
        engine_env = os.environ.get(environment_variable, default_environment) if environment_variable else ""
        if conda and engine_env:
            command = [conda, "run", "-n", engine_env, engine, "--version"]
            source = f"conda environment {engine_env}"
    if not command:
        return "not detected", source
    try:
        result = subprocess.run(
            command, capture_output=True, text=True,
            check=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return "not detected", source
    lines = (result.stdout or result.stderr).strip().splitlines()
    return (lines[-1].strip() if lines else "not detected"), source


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison_root", type=Path, nargs="+")
    parser.add_argument("--engine", required=True, choices=("vina", "qvinaw"))
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--receptor", required=True, type=Path)
    parser.add_argument("--box", required=True, type=Path)
    parser.add_argument("--threshold", type=float, default=2.0)
    parser.add_argument("--exhaustiveness", type=int, required=True)
    parser.add_argument("--num-modes", type=int, required=True)
    parser.add_argument("--energy-range", type=float, required=True)
    parser.add_argument("--seed", type=int, action="append", required=True)
    parser.add_argument("--min-seeds", type=int, default=3)
    parser.add_argument("--ph", type=float, default=7.4)
    parser.add_argument("--conformers", type=int, required=True)
    parser.add_argument("--charge-model", default="gasteiger")
    parser.add_argument("--macrocycle-treatment", required=True)
    parser.add_argument(
        "--no-prompt",
        action="store_true",
        help="do not ask about follow-up calibration options after a failed control",
    )
    args = parser.parse_args()

    if len(args.comparison_root) != len(args.seed):
        parser.error("provide one --seed for each comparison root")
    seed_results = []
    variants = []
    for root_arg, seed in zip(args.comparison_root, args.seed):
        root = root_arg.expanduser().resolve()
        summaries = sorted(root.rglob("comparison_summary.json"))
        if not summaries:
            parser.error(f"no comparison summaries found under {root}")
        seed_variants = []
        for path in summaries:
            data = json.loads(path.read_text())
            row = {
                "seed": seed,
                "variant": path.parent.name.removesuffix("_comparison"),
                "summary": str(path),
                "pose_count": data["pose_count"],
                "top_score_affinity_kcal_per_mol": float(data["top_score_affinity_kcal_per_mol"]),
                "top_score_rmsd_angstrom": float(data["top_score_rmsd_angstrom"]),
                "best_rmsd_angstrom": float(data["best_rmsd_angstrom"]),
            }
            seed_variants.append(row)
            variants.append(row)
        seed_top = min(seed_variants, key=lambda row: row["top_score_affinity_kcal_per_mol"])
        seed_best = min(seed_variants, key=lambda row: row["best_rmsd_angstrom"])
        seed_results.append({
            "seed": seed,
            "sampling_pass": seed_best["best_rmsd_angstrom"] <= args.threshold,
            "ranking_pass": seed_top["top_score_rmsd_angstrom"] <= args.threshold,
            "global_top_ranked_pose": seed_top,
            "global_best_sampled_pose": seed_best,
        })
    global_top = min(variants, key=lambda row: row["top_score_affinity_kcal_per_mol"])
    global_best = min(variants, key=lambda row: row["best_rmsd_angstrom"])
    sampling_pass = all(row["sampling_pass"] for row in seed_results)
    ranking_pass = all(row["ranking_pass"] for row in seed_results)
    seed_requirement_pass = len(set(args.seed)) >= args.min_seeds
    approved = sampling_pass and ranking_pass and seed_requirement_pass

    receptor = args.receptor.expanduser().resolve()
    box = args.box.expanduser().resolve()
    detected_engine_version, detected_engine_source = engine_version(args.engine)
    result = {
        "schema_name": "docking-universal-protocol",
        "schema_version": 1,
        "schema_status": "stable_v1",
        "control_status": "approved" if approved else "failed",
        "engine": args.engine,
        "acceptance": {
            "threshold_angstrom": args.threshold,
            "sampling_pass": sampling_pass,
            "ranking_pass": ranking_pass,
            "minimum_independent_seeds": args.min_seeds,
            "independent_seed_count": len(set(args.seed)),
            "seed_requirement_pass": seed_requirement_pass,
            "requires_both": True,
        },
        "global_top_ranked_pose": global_top,
        "global_best_sampled_pose": global_best,
        "parameters": {
            "ph": args.ph,
            "conformers_per_state": args.conformers,
            "charge_model": args.charge_model,
            "macrocycle_treatment": args.macrocycle_treatment,
            "exhaustiveness": args.exhaustiveness,
            "num_modes": args.num_modes,
            "energy_range_kcal_per_mol": args.energy_range,
            "seeds": args.seed,
        },
        "locked_inputs": {
            "receptor": str(receptor),
            "receptor_sha256": sha256(receptor),
            "box": str(box),
            "box_sha256": sha256(box),
        },
        "variant_count": len(variants),
        "seed_results": seed_results,
        "variants": variants,
        "unknown_docking_allowed": approved,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "software": {
            "docking_universal": package_version(),
            "python": platform.python_version(),
            "rdkit": distribution_version("rdkit", "rdkit-pypi"),
            "molscrub": distribution_version("molscrub"),
            "meeko": distribution_version("meeko"),
            "pdbfixer": distribution_version("pdbfixer"),
            "engine": args.engine,
            "engine_version": detected_engine_version,
            "engine_source": detected_engine_source,
        },
    }
    if approved:
        result.update({
            "protocol_type": "control-validated",
            "evidence_basis": "Passing bound-ligand pose-recovery control",
            "screening_authority": "control-approved",
        })
    output = args.out.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(f"Engine: {args.engine}")
    print(f"Sampling control: {'PASS' if sampling_pass else 'FAIL'} (best {global_best['best_rmsd_angstrom']:.3f} A)")
    print(f"Ranking control: {'PASS' if ranking_pass else 'FAIL'} (global top {global_top['top_score_rmsd_angstrom']:.3f} A)")
    print(f"Seed requirement: {'PASS' if seed_requirement_pass else 'INCOMPLETE'} ({len(set(args.seed))}/{args.min_seeds})")
    print(f"Unknown docking: {'ALLOWED' if approved else 'BLOCKED'}")
    print(f"Protocol record: {output}")

    if not approved:
        print()
        print(
            "This control has a high RMSD or insufficient repeatability, so the current "
            "protocol may not be appropriate for this target."
        )
        if not sampling_pass and not ranking_pass:
            recommendation = "increase both search effort and the independent conformer ensemble"
        elif not sampling_pass:
            recommendation = "increase exhaustiveness, seeds, and/or independent starting conformers"
        elif not ranking_pass:
            recommendation = "sample additional seeds and conformers, then reassess pose ranking"
        else:
            recommendation = f"run at least {args.min_seeds} independent seeds"
        print(f"Recommended next step: {recommendation}.")

        if not args.no_prompt and sys.stdin.isatty():
            answer = input(
                "This control has a high RMSD. Would you like to test broader sampling "
                "to determine whether the result can be recovered reproducibly? [y/N]: "
            ).strip().lower()
            if answer in {"y", "yes"}:
                print("Suggested calibration options:")
                print("  1. Quick retry: add independent seeds.")
                print("  2. Broader search: increase exhaustiveness and output poses.")
                print("  3. Flexible-ligand retry: generate more independent conformers.")
                print("  4. Robust retry: combine all three options.")
                print("No retry was started automatically; select the new protocol in the pipeline menu.")
            else:
                print("Keeping the current result as a failed control; unknown docking remains blocked.")


if __name__ == "__main__":
    main()
