#!/usr/bin/env python
"""Dock one unknown compound with an approved protocol or explicit exploration.

The protocol is accepted only if its schema, approval flag, receptor hash, box
hash, and engine-specific macrocycle treatment match. This prevents a control
performed on one target or input revision from silently authorizing another.

Exploratory mode is deliberately marked uncalibrated and never creates an
approval. A successful retrospective control also does not prove that an
unknown pose, score, or biological hypothesis is correct.
"""

import argparse
import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run([str(value) for value in command], check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    authority = parser.add_mutually_exclusive_group(required=True)
    authority.add_argument("--protocol", type=Path, help="approved target-locked protocol")
    authority.add_argument("--exploratory", action="store_true", help="explicitly run without an approved pose-recovery control")
    parser.add_argument("--ligand", required=True, type=Path, help="one compound SDF with authoritative chemistry")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--receptor", type=Path, help="override stored receptor path; hash must still match")
    parser.add_argument("--receptor-pdb", type=Path, help="coordinate receptor used for clustering, PLIP, and PyMOL")
    parser.add_argument("--box", type=Path, help="override stored box path; hash must still match")
    parser.add_argument("--engine-command")
    parser.add_argument("--engine-env")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--check-only", action="store_true", help="validate protocol, ligand, receptor, and box without docking")
    parser.add_argument("--analysis", choices=("none", "summary", "representatives"), default="representatives", help="none: docking only; summary: cluster tables; representatives: tables plus selected PLIP/PyMOL output (default)")
    parser.add_argument("--representatives", type=int, default=3, help="number of lowest-energy distinct pose clusters analyzed (default: 3)")
    parser.add_argument("--cluster-rmsd", type=float, default=2.0, help="cross-run symmetry-aware no-fit heavy-atom RMSD cutoff in A")
    parser.add_argument("--mk-export", default="mk_export.py")
    parser.add_argument("--pymol", default="pymol")
    parser.add_argument("--plip-command", default="plip")
    parser.add_argument("--engine", choices=("vina", "smina"), default="vina", help="exploratory engine")
    parser.add_argument("--seeds", type=int, default=5, help="exploratory independent seeds")
    parser.add_argument("--conformers", type=int, default=3, help="exploratory conformers per chemical state")
    parser.add_argument("--exhaustiveness", type=int, default=16, help="exploratory search effort")
    parser.add_argument("--num-modes", type=int, default=20, help="exploratory poses retained per job")
    parser.add_argument("--energy-range", type=float, default=8.0, help="exploratory kcal/mol output window")
    parser.add_argument("--ph", type=float, default=7.4, help="exploratory ligand-state pH")
    parser.add_argument("--base-seed", type=int, default=20260808, help="exploratory deterministic base seed")
    parser.add_argument("--forcefield", choices=("mmff94", "mmff94s", "uff"), default="mmff94")
    parser.add_argument("--rmsd-prune", type=float, default=0.75)
    parser.add_argument("--skip-tautomers", action="store_true")
    parser.add_argument("--charge-model", default="gasteiger")
    args = parser.parse_args()

    ligand = args.ligand.expanduser().resolve()
    if not ligand.is_file():
        parser.error("ligand file does not exist")

    # The current protocol-transfer interface is intentionally one compound per
    # SDF. Failing explicitly avoids silently screening only the first library
    # record; low-level commands remain available for uncalibrated batch work.
    from rdkit import Chem
    molecule_count = sum(1 for molecule in Chem.SDMolSupplier(str(ligand), removeHs=False) if molecule)
    if molecule_count != 1:
        raise SystemExit(f"--ligand must contain exactly one readable molecule; found {molecule_count}")

    if args.protocol:
        protocol_path = args.protocol.expanduser().resolve()
        if not protocol_path.is_file():
            parser.error("protocol file does not exist")
        protocol = json.loads(protocol_path.read_text())
        if protocol.get("schema_name") != "docking-universal-protocol" or protocol.get("schema_version") != 1:
            raise SystemExit("Protocol is missing the supported docking-universal-protocol v1 schema")
        if not protocol.get("unknown_docking_allowed") or protocol.get("control_status") != "approved":
            raise SystemExit("Protocol is not approved; unknown docking is blocked")
        acceptance = protocol.get("acceptance", {})
        stored_seeds = protocol.get("parameters", {}).get("seeds", [])
        minimum_seeds = int(acceptance.get("minimum_independent_seeds", 0))
        internally_consistent = (
            acceptance.get("sampling_pass") is True and acceptance.get("ranking_pass") is True
            and acceptance.get("seed_requirement_pass") is True
            and len(set(stored_seeds)) >= minimum_seeds >= 1
            and int(acceptance.get("independent_seed_count", 0)) == len(set(stored_seeds))
        )
        if not internally_consistent:
            raise SystemExit("Protocol approval fields are incomplete or internally inconsistent")
        engine = protocol["engine"]
        expected_macrocycle = "flexible_meeko" if engine == "vina" else "rigid_conformer_ensemble"
        if protocol["parameters"].get("macrocycle_treatment") != expected_macrocycle:
            raise SystemExit("Protocol macrocycle treatment does not match the recorded engine")
        receptor = (args.receptor or Path(protocol["locked_inputs"]["receptor"])).expanduser().resolve()
        box = (args.box or Path(protocol["locked_inputs"]["box"])).expanduser().resolve()
        for path, key, label in ((receptor, "receptor_sha256", "receptor"), (box, "box_sha256", "box")):
            if not path.is_file():
                raise SystemExit(f"Locked {label} not found: {path}")
            if sha256(path) != protocol["locked_inputs"][key]:
                raise SystemExit(f"Locked {label} hash mismatch; rerun the control for the changed input")
        parameters = protocol["parameters"]
        workflow_status = "CONTROL_APPROVED"
    else:
        if not args.receptor or not args.box:
            parser.error("--exploratory requires --receptor and --box")
        if min(args.seeds, args.conformers, args.exhaustiveness, args.num_modes) < 1:
            parser.error("exploratory seeds, conformers, exhaustiveness, and num-modes must be positive")
        if args.base_seed < 0 or args.rmsd_prune < 0:
            parser.error("exploratory base seed and RMSD pruning threshold must be non-negative")
        receptor = args.receptor.expanduser().resolve()
        box = args.box.expanduser().resolve()
        if not receptor.is_file() or not box.is_file():
            parser.error("exploratory receptor and box must exist")
        engine = args.engine
        parameters = {
            "ph": args.ph, "conformers_per_state": args.conformers,
            "ensemble_seed": args.base_seed, "forcefield": args.forcefield,
            "rmsd_prune_angstrom": args.rmsd_prune,
            "tautomers_enumerated": not args.skip_tautomers,
            "charge_model": args.charge_model,
            "macrocycle_treatment": "flexible_meeko" if engine == "vina" else "rigid_conformer_ensemble",
            "exhaustiveness": args.exhaustiveness, "num_modes": args.num_modes,
            "energy_range_kcal_per_mol": args.energy_range,
            "seeds": [args.base_seed + index for index in range(args.seeds)],
        }
        protocol_path = None
        workflow_status = "EXPLORATORY_NO_CONTROL"

    if args.check_only:
        print("Input check: PASS")
        print(f"Engine: {engine}")
        print(f"Independent seeds: {len(parameters['seeds'])}")
        print("Protocol status: approved and hashes unchanged" if protocol_path else "Protocol status: exploratory, no control approval")
        return

    out = args.out.expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    project = Path(__file__).resolve().parent.parent
    # A 2D depiction documents the submitted chemical graph independently of
    # any docking pose. Its filename follows the authoritative input SDF.
    run([
        project / "bin/docking-universal", "depict2d", ligand,
        "--out-dir", out / "depiction", "--format", "png",
    ])
    conformers = int(parameters["conformers_per_state"])
    seeds = [int(seed) for seed in parameters["seeds"]]
    job_count = conformers * len(seeds)
    print(f"Approved protocol: {protocol_path}" if protocol_path else "Exploratory workflow: no approved target-specific control")
    print(f"Planned docking jobs: {conformers} conformers × {len(seeds)} seeds = {job_count} jobs")
    if not args.non_interactive and sys.stdin.isatty():
        answer = input("Run docking with these recorded settings? [y/N]: ").strip().lower()
        if answer not in {"y", "yes"}:
            raise SystemExit("Cancelled")

    ensemble = out / "independent_ensemble.sdf"
    ensemble_command = [
        sys.executable, project / "libexec/docking-universal-ensemble.py", ligand,
        "--out", ensemble, "--ph", parameters["ph"], "--conformers", conformers,
        "--seed", parameters.get("ensemble_seed", seeds[0]),
        "--forcefield", parameters.get("forcefield", "mmff94"),
        "--rmsd-prune", parameters.get("rmsd_prune_angstrom", 0.75),
    ]
    if parameters.get("tautomers_enumerated", True) is False:
        ensemble_command.append("--skip-tautomers")
    run(ensemble_command)
    prep = out / "ligand_preparation"
    run([
        project / "bin/docking-universal", "ligands", ensemble, "--out", prep,
        "--target-engines", engine, "--geometry-mode", "preserve",
        "--charge-model", parameters["charge_model"],
    ])
    score_files = []
    for seed in seeds:
        docking = out / f"seed_{seed}" / "docking"
        command = [
            project / "bin/docking-universal", "dock", "--engine", engine,
            "--receptor", receptor, "--ligands", prep / "pdbqt_ligands",
            "--config", box, "--out", docking,
            "--exhaustiveness", parameters["exhaustiveness"],
            "--num-modes", parameters["num_modes"],
            "--energy-range", parameters["energy_range_kcal_per_mol"], "--seed", seed, "--skip-existing",
        ]
        if args.engine_command:
            command += ["--engine-command", args.engine_command]
        if args.engine_env:
            command += ["--engine-env", args.engine_env]
        run(command)
        scores = docking.parent / "scores.csv"
        run([project / "bin/docking-universal", "collect", docking, "--out", scores])
        score_files.append(scores)

    combined = out / "all_scores.csv"
    rows = []
    fields = []
    for seed, path in zip(seeds, score_files):
        with path.open(newline="") as handle:
            reader = csv.DictReader(handle)
            fields = reader.fieldnames or fields
            for row in reader:
                rows.append({"seed": seed, **row})
    with combined.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["seed", *fields])
        writer.writeheader()
        writer.writerows(rows)
    manifest = {
        "workflow": "target_locked_unknown_docking" if protocol_path else "exploratory_unknown_docking",
        "completion_status": workflow_status,
        "protocol": str(protocol_path) if protocol_path else None,
        "protocol_sha256": sha256(protocol_path) if protocol_path else None,
        "ligand": str(ligand),
        "ligand_sha256": sha256(ligand),
        "receptor": str(receptor),
        "box": str(box),
        "engine": engine,
        "seeds": seeds,
        "ensemble_parameters": {
            "ph": parameters["ph"],
            "conformers_per_state": conformers,
            "ensemble_seed": parameters.get("ensemble_seed", seeds[0]),
            "forcefield": parameters.get("forcefield", "mmff94"),
            "rmsd_prune_angstrom": parameters.get("rmsd_prune_angstrom", 0.75),
            "tautomers_enumerated": parameters.get("tautomers_enumerated", True),
            "charge_model": parameters["charge_model"],
        },
        "docking_job_count": job_count,
        "scientific_warning": "Scores and poses require independent scientific interpretation." if protocol_path else "EXPLORATORY: no approved target-specific pose-recovery control was available.",
    }
    (out / "screen_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    if args.analysis != "none":
        analysis = out / "pose_analysis"
        run([
            project / "bin/docking-universal", "cluster-poses", "--docking-root", out,
            "--ligand-work", prep / "ligand_work", "--engine", engine,
            "--receptor", args.receptor_pdb.expanduser().resolve() if args.receptor_pdb else (receptor.with_suffix(".pdb") if receptor.with_suffix(".pdb").is_file() else receptor),
            "--out", analysis, "--cluster-rmsd", args.cluster_rmsd,
            "--representatives", args.representatives, "--mk-export", args.mk_export,
        ])
        if args.analysis == "representatives":
            run([
                project / "bin/docking-universal", "render3d", analysis / "representative_browser.pml",
                "--out", analysis / "representative_browser.png",
                "--session-out", analysis / "representative_browser.pse", "--pymol", args.pymol,
            ])
            for cluster_dir in sorted(analysis.glob("cluster_*")):
                if not cluster_dir.is_dir():
                    continue
                run([
                    project / "bin/docking-universal", "render3d", cluster_dir / "representative.pml",
                    "--out", cluster_dir / "representative.png",
                    "--session-out", cluster_dir / "representative.pse", "--pymol", args.pymol,
                ])
                run([
                    project / "bin/docking-universal", "interactions", cluster_dir / "complex.pdb",
                    "--out-dir", cluster_dir / "interactions", "--plip-command", args.plip_command,
                    "--skip-native-visuals", "--typed-ligand-sdf", cluster_dir / "representative.sdf",
                    "--ligand-resname", "UNL", "--ligand-chain", "Z", "--ligand-position", "1",
                ])
                interaction_scene = cluster_dir / "interactions" / "complex_plip_all_in_one.pml"
                if interaction_scene.is_file():
                    run([
                        project / "bin/docking-universal", "render3d", interaction_scene,
                        "--out", cluster_dir / "interactions" / "complex_plip_all_in_one.png",
                        "--session-out", cluster_dir / "interactions" / "complex_plip_all_in_one.pse",
                        "--pymol", args.pymol,
                    ])
    print(f"Unknown docking complete: {out}")
    print(f"Combined scores: {combined}")


if __name__ == "__main__":
    main()
