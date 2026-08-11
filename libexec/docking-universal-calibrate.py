#!/usr/bin/env python
"""Run a reproducible ensemble redocking calibration and write a protocol record.

Scientific role
---------------
This command asks whether a docking search can repeatedly sample and rank the
withheld crystallographic ligand pose.  It is a retrospective search diagnostic,
not evidence that affinities or prospective poses are biologically correct.

The crystallographic coordinates are used only by the RMSD comparison. Starting
conformers are generated independently from bond-order/stereochemical chemistry.
Vina receives Meeko flexible-macrocycle PDBQT files; smina receives rigid
macrocycle conformers because the supported smina build cannot parse CG0/G0.
"""

import argparse
import importlib.metadata
import json
import platform
import subprocess
import sys
import time
from pathlib import Path


TIERS = {
    "quick": dict(conformers=3, seeds=2, exhaustiveness=16, modes=15, energy_range=8.0),
    "repeatability": dict(conformers=3, seeds=5, exhaustiveness=16, modes=15, energy_range=8.0),
    "broader": dict(conformers=3, seeds=5, exhaustiveness=32, modes=20, energy_range=8.0),
    "conformers": dict(conformers=5, seeds=3, exhaustiveness=32, modes=20, energy_range=8.0),
    "robust": dict(conformers=5, seeds=5, exhaustiveness=32, modes=20, energy_range=8.0),
}


def tier_settings(args, tier_name):
    settings = dict(TIERS[tier_name])
    if args.conformers_override is not None:
        settings["conformers"] = args.conformers_override
    return settings


def run(command):
    """Run one auditable stage and stop immediately if it fails."""
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run([str(item) for item in command], check=True)


def distribution_version(name):
    """Return an installed distribution version without making it a hard dependency."""
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return "not_detected"


def read_tsv_manifest(path):
    """Read the two-column engine manifest written by the low-level runner."""
    values = {}
    for line in path.read_text(errors="replace").splitlines():
        key, separator, value = line.partition("\t")
        if separator:
            values[key] = value
    return values


def choose_manual_tier(result):
    """Let an experienced user select one tier without implying minimality."""
    acceptance = result["acceptance"]
    print()
    print("Manual tier selection tests only the chosen settings.")
    print("A passing result will not establish that any less expensive tier would also pass.")
    print("  1) Repeatability — five seeds at the current search depth")
    print("     Tests stochastic reproducibility without changing chemistry or search depth.")
    print("  2) Broader search — five seeds and greater exhaustiveness")
    print("     Tests whether search depth limited recovery; the scientific model is unchanged.")
    print("  3) More conformers — expand independent starting geometries")
    print("     Tests sensitivity to the ligand's initial 3D geometry.")
    print("  4) Robust retry — combine five conformers, five seeds, and greater exhaustiveness")
    print("     Broadens both starting geometry and stochastic search, but cannot identify which change enabled a pass.")
    print("  5) Inspect inputs — stop and review chemistry, receptor, and docking box")
    print("     Reconsiders scientific assumptions before adding computation; appropriate when preparation or site definition is doubtful.")
    if not acceptance["sampling_pass"] and not acceptance["ranking_pass"]:
        recommendation = "4"
    elif not acceptance["sampling_pass"]:
        recommendation = "3"
    elif not acceptance["ranking_pass"]:
        recommendation = "2"
    else:
        recommendation = "1"
    answer = input(f"Select an option [{recommendation}]: ").strip() or recommendation
    return {"1": "repeatability", "2": "broader", "3": "conformers", "4": "robust"}.get(answer)


def guided_next_tier(current_tier, result):
    """Choose the next informative tier in a lowest-cost-first progression."""
    acceptance = result["acceptance"]
    if current_tier == "quick":
        if acceptance["sampling_pass"] and acceptance["ranking_pass"]:
            return "repeatability", "poses passed; extend the same search depth to the five-seed requirement"
        return "broader", "pose sampling or ranking failed; increasing seed count alone is unlikely to be sufficient"
    if current_tier == "repeatability":
        return "broader", "five seeds at the lower search depth did not pass; increase search depth"
    if current_tier == "broader":
        return "conformers", "broader search did not pass; test whether independent starting-geometry coverage is limiting"
    if current_tier == "conformers":
        return "robust", "expanded conformers need the full five-seed repeatability test"
    return None, "the robust tier did not pass; further automatic escalation would encourage overfitting"


def choose_retry_strategy(current_tier, result):
    """Make incremental calibration versus manual complexity an explicit choice."""
    print()
    print("The current control is not approved.")
    print("How would you like to continue calibration?")
    print("  1) Guided incremental calibration (recommended)")
    print("     Test the next least-complex informative tier and stop at the first reproducible pass.")
    print("  2) Choose a tier manually")
    print("     Test only the selected complexity; no claim is made about cheaper settings.")
    print("  3) Inspect inputs and stop")
    print("     Review chemistry, receptor preparation, and site definition instead of treating every failure as under-sampling.")
    answer = input("Select an approach [1]: ").strip() or "1"
    if answer == "1":
        next_tier, reason = guided_next_tier(current_tier, result)
        print(f"Guided assessment: {reason}.")
        if next_tier:
            settings = TIERS[next_tier]
            print(
                f"Recommended next tier: {next_tier} — {settings['conformers']} conformers × "
                f"{settings['seeds']} seeds, exhaustiveness {settings['exhaustiveness']}."
            )
        return "guided_incremental", next_tier
    if answer == "2":
        return "manual", choose_manual_tier(result)
    if answer == "3":
        return "inspect_inputs", None
    raise SystemExit("Choose 1, 2, or 3")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-sdf", required=True, type=Path, help="withheld experimental-coordinate SDF")
    parser.add_argument("--crystal-ligand", required=True, type=Path, help="selected ligand coordinates from the complex")
    parser.add_argument("--receptor-pdb", required=True, type=Path, help="prepared receptor used for pose complexes")
    parser.add_argument("--receptor-pdbqt", required=True, type=Path, help="prepared docking receptor")
    parser.add_argument("--box", required=True, type=Path, help="Vina-format box configuration")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--engine", choices=("vina", "smina"), default="vina")
    parser.add_argument("--tier", choices=tuple(TIERS), default="quick")
    parser.add_argument(
        "--guided-from", type=Path,
        help=(
            "completed earlier protocol.json to continue as a guided incremental "
            "calibration; the next tier is chosen from its recorded result"
        ),
    )
    parser.add_argument("--base-seed", type=int, default=20260808)
    parser.add_argument("--rmsd-threshold", type=float, default=2.0)
    parser.add_argument("--approval-min-seeds", type=int, default=5)
    parser.add_argument("--ph", type=float, default=7.4)
    parser.add_argument("--conformers-override", type=int)
    parser.add_argument("--forcefield", choices=("mmff94", "mmff94s", "uff"), default="mmff94")
    parser.add_argument("--rmsd-prune", type=float, default=0.75)
    parser.add_argument("--skip-tautomers", action="store_true")
    parser.add_argument("--charge-model", default="gasteiger")
    parser.add_argument(
        "--provisional-chemistry", action="store_true",
        help="record PDB-inferred ligand chemistry and block protocol authorization",
    )
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--engine-command")
    parser.add_argument("--engine-env")
    parser.add_argument("--mk-export", default="mk_export.py")
    parser.add_argument("--render-visuals", action="store_true", help="render selected control PSE/PNG and PLIP scene")
    parser.add_argument("--pymol", default="pymol")
    parser.add_argument("--plip-command", default="plip")
    return parser.parse_args()


def run_tier(args, tier_name, project, tier_root):
    started = time.monotonic()
    settings = tier_settings(args, tier_name)
    tier_root.mkdir(parents=True, exist_ok=True)
    ensemble = tier_root / "independent_ensemble.sdf"
    prep = tier_root / "ligand_preparation"
    comparisons = []
    seeds = [args.base_seed + index for index in range(settings["seeds"])]

    ensemble_command = [
        sys.executable, project / "libexec/docking-universal-ensemble.py", args.reference_sdf,
        "--out", ensemble, "--ph", args.ph, "--conformers", settings["conformers"],
        "--seed", args.base_seed, "--forcefield", args.forcefield,
        "--rmsd-prune", args.rmsd_prune,
    ]
    if args.skip_tautomers:
        ensemble_command.append("--skip-tautomers")
    run(ensemble_command)
    run([
        project / "bin/docking-universal", "ligands", ensemble, "--out", prep,
        "--target-engines", args.engine, "--geometry-mode", "preserve",
        "--charge-model", args.charge_model,
    ])

    for seed in seeds:
        seed_root = tier_root / f"seed_{seed}"
        docking = seed_root / "docking"
        command = [
            project / "bin/docking-universal", "dock", "--engine", args.engine,
            "--receptor", args.receptor_pdbqt, "--ligands", prep / "pdbqt_ligands",
            "--config", args.box, "--out", docking,
            "--exhaustiveness", settings["exhaustiveness"], "--num-modes", settings["modes"],
            "--energy-range", settings["energy_range"], "--seed", seed, "--skip-existing",
        ]
        if args.engine_command:
            command += ["--engine-command", args.engine_command]
        if args.engine_env:
            command += ["--engine-env", args.engine_env]
        run(command)

        comparison_root = seed_root / "comparisons"
        for docked in sorted(docking.glob(f"*_{args.engine}.pdbqt")):
            ligand_id = docked.name.removesuffix(f"_{args.engine}.pdbqt")
            chemistry = prep / "ligand_work" / f"{ligand_id}_opt.sdf"
            if not chemistry.is_file():
                raise SystemExit(f"No matching chemistry SDF for {docked.name}: {chemistry}")
            run([
                sys.executable, project / "libexec/docking-universal-redock-compare.py",
                "--reference-sdf", chemistry, "--crystal-ligand", args.crystal_ligand,
                "--docked-pdbqt", docked, "--receptor-pdb", args.receptor_pdb,
                "--out", comparison_root / f"{ligand_id}_comparison",
                "--mk-export", args.mk_export, "--rmsd-threshold", args.rmsd_threshold,
            ])
        comparisons.append(comparison_root)

    protocol = tier_root / "protocol.json"
    evaluate = [
        sys.executable, project / "libexec/docking-universal-calibration-evaluate.py",
        *comparisons, "--engine", args.engine, "--out", protocol,
        "--receptor", args.receptor_pdbqt, "--box", args.box,
        "--threshold", args.rmsd_threshold, "--exhaustiveness", settings["exhaustiveness"],
        "--num-modes", settings["modes"], "--energy-range", settings["energy_range"],
        "--min-seeds", args.approval_min_seeds, "--ph", args.ph,
        "--conformers", settings["conformers"], "--charge-model", args.charge_model,
        "--macrocycle-treatment", "flexible_meeko" if args.engine == "vina" else "rigid_conformer_ensemble",
        "--no-prompt",
    ]
    for seed in seeds:
        evaluate += ["--seed", seed]
    run(evaluate)
    result = json.loads(protocol.read_text())
    result.setdefault("parameters", {}).update({
        "ensemble_seed": args.base_seed,
        "forcefield": args.forcefield,
        "rmsd_prune_angstrom": args.rmsd_prune,
        "tautomers_enumerated": not args.skip_tautomers,
    })
    result["schema_name"] = "docking-universal-protocol"
    result["schema_version"] = 1
    result["calibration_tier"] = tier_name
    result["scientific_scope"] = {
        "purpose": "retrospective pose-recovery search control",
        "does_not_establish": ["binding affinity accuracy", "prospective pose accuracy", "biological activity"],
    }
    if args.provisional_chemistry:
        # A pose search can still be useful for inspection, but inferred bond
        # orders/charges are not an adequate chemical basis for authorizing
        # prospective screening.
        result["unknown_docking_allowed"] = False
        result["provisional_chemistry_limit"] = (
            "PDB-inferred ligand chemistry was used; this control cannot authorize unknown-compound screening."
        )
    engine_manifest = read_tsv_manifest(tier_root / f"seed_{seeds[0]}" / "docking" / "run_manifest.tsv")
    result["software"] = {
        "docking_universal": (project / "VERSION").read_text().strip(),
        "python": platform.python_version(),
        "rdkit": distribution_version("rdkit"),
        "molscrub": distribution_version("molscrub"),
        "meeko": distribution_version("meeko"),
        "engine": engine_manifest.get("engine", args.engine),
        "engine_version": engine_manifest.get("engine_version", "unknown"),
        "engine_source": engine_manifest.get("engine_source", "unknown"),
    }
    protocol.write_text(json.dumps(result, indent=2) + "\n")

    # Render only the globally top-ranked and globally best-sampled comparisons.
    # Every underlying pose remains available in each browser PML, while this
    # avoids opening or rendering all conformer/seed combinations at once.
    if args.render_visuals:
        visuals = tier_root / "selected_visuals"
        visuals.mkdir(exist_ok=True)
        selected = {
            "top_ranked": result["global_top_ranked_pose"],
            "best_sampled": result["global_best_sampled_pose"],
        }
        for label, record in selected.items():
            comparison = Path(record["summary"]).parent
            run([
                project / "bin/docking-universal", "render3d", comparison / "crystal_pose_browser.pml",
                "--out", visuals / f"{label}.png", "--session-out", visuals / f"{label}.pse",
                "--pymol", args.pymol,
            ])
        top_comparison = Path(result["global_top_ranked_pose"]["summary"]).parent
        interactions = visuals / "top_ranked_interactions"
        run([
            project / "bin/docking-universal", "interactions", top_comparison / "top_score_complex.pdb",
            "--out-dir", interactions, "--plip-command", args.plip_command,
            "--skip-native-visuals", "--typed-ligand-sdf", top_comparison / "top_score_pose.sdf",
            "--ligand-resname", "UNL", "--ligand-chain", "Z", "--ligand-position", "1",
        ])
        best_comparison = Path(result["global_best_sampled_pose"]["summary"]).parent
        best_interactions = visuals / "best_sampled_interactions"
        comparison_summary = json.loads((best_comparison / "comparison_summary.json").read_text())
        same_selected_pose = (
            best_comparison.resolve() == top_comparison.resolve()
            and comparison_summary.get("top_score_model") == comparison_summary.get("best_rmsd_model")
        )
        if not same_selected_pose and not best_interactions.exists():
            run([
                project / "bin/docking-universal", "interactions", best_comparison / "best_rmsd_complex.pdb",
                "--out-dir", best_interactions, "--plip-command", args.plip_command,
                "--skip-native-visuals", "--typed-ligand-sdf", best_comparison / "best_rmsd_pose.sdf",
                "--ligand-resname", "UNL", "--ligand-chain", "Z", "--ligand-position", "1",
            ])
        pml = interactions / "top_score_complex_plip_all_in_one.pml"
        run([
            project / "bin/docking-universal", "render3d", pml,
            "--out", visuals / "top_ranked_interactions.png",
            "--session-out", visuals / "top_ranked_interactions.pse", "--pymol", args.pymol,
        ])
    result["wall_time_seconds"] = round(time.monotonic() - started, 1)
    protocol.write_text(json.dumps(result, indent=2) + "\n")
    return protocol, result


def main():
    args = parse_args()
    if args.conformers_override is not None and args.conformers_override < 1:
        raise SystemExit("--conformers-override must be positive")
    if args.base_seed < 0 or args.rmsd_prune < 0:
        raise SystemExit("--base-seed and --rmsd-prune must be non-negative")
    for path in (args.reference_sdf, args.crystal_ligand, args.receptor_pdb, args.receptor_pdbqt, args.box):
        if not path.expanduser().is_file():
            raise SystemExit(f"Required input not found: {path}")
    project = Path(__file__).resolve().parent.parent
    output = args.out.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    tier = args.tier
    calibration_strategy = "initial_tier"
    escalation_history = []
    if args.guided_from:
        previous_path = args.guided_from.expanduser().resolve()
        if not previous_path.is_file():
            raise SystemExit(f"Guided-resume protocol not found: {previous_path}")
        previous = json.loads(previous_path.read_text())
        previous_tier = previous.get("calibration_tier")
        if previous_tier not in TIERS:
            raise SystemExit("Guided-resume protocol does not record a recognized calibration tier")
        next_tier, reason = guided_next_tier(previous_tier, previous)
        if not next_tier:
            raise SystemExit(f"Guided calibration cannot advance from {previous_tier}: {reason}")
        previous_settings = tier_settings(args, previous_tier)
        escalation_history = [{
            "tier": previous_tier,
            "approved": bool(previous.get("unknown_docking_allowed")),
            "sampling_pass": bool(previous.get("acceptance", {}).get("sampling_pass")),
            "ranking_pass": bool(previous.get("acceptance", {}).get("ranking_pass")),
            "seed_requirement_pass": bool(previous.get("acceptance", {}).get("seed_requirement_pass")),
            "job_count": previous_settings["conformers"] * previous_settings["seeds"],
            "wall_time_seconds": previous.get("wall_time_seconds"),
            "source_protocol": str(previous_path),
        }]
        tier = next_tier
        calibration_strategy = "guided_incremental"
        print(f"Guided resume from {previous_tier}: {reason}.")
        print(f"Starting next informative tier: {tier}.")
    while tier:
        settings = tier_settings(args, tier)
        job_count = settings["conformers"] * settings["seeds"]
        print()
        print(f"Calibration tier: {tier}")
        print(
            f"Planned docking jobs: {settings['conformers']} conformers × "
            f"{settings['seeds']} seeds = {job_count} jobs"
        )
        timed_history = [entry for entry in escalation_history if entry.get("wall_time_seconds")]
        if timed_history:
            completed_jobs = sum(entry["job_count"] for entry in timed_history)
            completed_seconds = sum(entry["wall_time_seconds"] for entry in timed_history)
            estimated_seconds = job_count * completed_seconds / completed_jobs
            print(
                f"Estimated elapsed time on this machine: about {estimated_seconds / 60:.1f} minutes "
                f"({completed_seconds / completed_jobs:.1f} seconds per completed docking job)."
            )
            print("Estimate excludes unusual tool startup, rendering, and system-load variation.")
        if tier != "quick" and not args.non_interactive and sys.stdin.isatty():
            confirmation = input(
                "Run this tier with the displayed settings? [Y/n]: "
            ).strip().lower()
            if confirmation not in {"", "y", "yes"}:
                print("Calibration stopped before the selected tier. Unknown docking remains blocked.")
                break
        protocol, result = run_tier(args, tier, project, output / tier)
        escalation_history.append({
            "tier": tier,
            "approved": bool(result["unknown_docking_allowed"]),
            "sampling_pass": bool(result["acceptance"]["sampling_pass"]),
            "ranking_pass": bool(result["acceptance"]["ranking_pass"]),
            "seed_requirement_pass": bool(result["acceptance"]["seed_requirement_pass"]),
            "job_count": job_count,
            "wall_time_seconds": result.get("wall_time_seconds"),
        })
        result["calibration_strategy"] = calibration_strategy
        result["escalation_history"] = escalation_history
        result["efficiency_claim"] = (
            "first passing tier in the tested guided progression"
            if calibration_strategy == "guided_incremental" and result["unknown_docking_allowed"]
            else "no claim that lower-cost tiers are adequate"
        )
        protocol.write_text(json.dumps(result, indent=2) + "\n")
        print(f"Protocol record: {protocol}")
        if result["unknown_docking_allowed"]:
            print("Control passed reproducibly. This protocol may be used for target-matched unknown docking.")
            break
        if args.provisional_chemistry:
            print("Control completed with provisional PDB-inferred chemistry; protocol authorization is intentionally blocked.")
            break
        if args.non_interactive or not sys.stdin.isatty():
            print("Control did not pass; no retry was started in non-interactive mode.")
            break
        if calibration_strategy == "guided_incremental":
            next_tier, reason = guided_next_tier(tier, result)
            print(f"Guided assessment: {reason}.")
            if next_tier:
                settings = tier_settings(args, next_tier)
                print(
                    f"Next incremental tier: {next_tier} — {settings['conformers']} conformers × "
                    f"{settings['seeds']} seeds, exhaustiveness {settings['exhaustiveness']}."
                )
        else:
            selected_strategy, next_tier = choose_retry_strategy(tier, result)
            if selected_strategy != "inspect_inputs":
                calibration_strategy = selected_strategy
        if not next_tier:
            print("Calibration stopped for input inspection. Unknown docking remains blocked.")
            break
        tier = next_tier


if __name__ == "__main__":
    main()
