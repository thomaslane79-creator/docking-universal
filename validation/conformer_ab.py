#!/usr/bin/env python
"""Offline paired conformer benchmark; does not change production preparation.

One exact chemical state, one shared independent ETKDG pool, two minimization
arms, identical symmetry-aware heavy-atom RMSD pruning, optional equal-budget
Vina redocking. Run with the scientific Python environment containing RDKit.
"""

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from rdkit import Chem, rdBase
from rdkit.Chem import AllChem, rdMolAlign

HARTREE_TO_KCAL = 627.509474
ROOT = Path(__file__).resolve().parents[1]


def dump(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def executable(value):
    # Commands run in per-conformer directories; relative executable paths must
    # be resolved before changing the subprocess working directory.
    found = str(Path(shutil.which(value) or value).expanduser().resolve())
    if not Path(found).is_file() or not os.access(found, os.X_OK):
        raise ValueError(f"Executable not found: {value}. No automatic installation or vacuum fallback.")
    return found


def run(command, folder, label, timeout):
    dump(folder / f"{label}.command.json", command)
    environment = dict(os.environ, OMP_NUM_THREADS="1", MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1")
    with (folder / f"{label}.log").open("w") as log:
        result = subprocess.run(command, cwd=folder, env=environment, stdout=log,
                                stderr=subprocess.STDOUT, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{label} failed (exit {result.returncode}); see {folder / (label + '.log')}")
    return (folder / f"{label}.log").read_text(errors="replace")


def independent_pool(source, attempts, seed):
    records = list(Chem.SDMolSupplier(str(source), removeHs=False))
    if len(records) != 1 or records[0] is None:
        raise ValueError("Supply exactly one readable SDF record, with the intended protonation/tautomer state.")
    template = records[0]
    # Rebuild from chemistry, never from deposited/input 3D coordinates.
    heavy = Chem.RemoveHs(template)
    for atom in heavy.GetAtoms():
        atom.SetAtomMapNum(0)
    smiles = Chem.MolToSmiles(heavy, isomericSmiles=True)
    molecule = Chem.AddHs(Chem.MolFromSmiles(smiles))
    params = AllChem.ETKDGv3()
    params.randomSeed = seed
    params.useRandomCoords = True
    params.pruneRmsThresh = -1  # Both arms prune ONLY after their own minimization.
    ids = AllChem.EmbedMultipleConfs(molecule, numConfs=attempts, params=params)
    pool = []
    for identifier in ids:
        item = Chem.Mol(molecule)
        conformer = Chem.Conformer(molecule.GetConformer(identifier))
        item.RemoveAllConformers()
        item.AddConformer(conformer, assignId=True)
        pool.append(item)
    if not pool:
        raise ValueError("ETKDG could not embed this chemical state.")
    return smiles, pool


def sdf(path, molecules):
    with Chem.SDWriter(str(path)) as writer:
        for molecule in molecules:
            writer.write(molecule)


def minimize_mmff(molecule, variant="MMFF94"):
    if variant not in ("MMFF94", "MMFF94s"):
        raise ValueError(f"Unsupported MMFF variant: {variant}")
    optimized = Chem.Mol(molecule)
    if not AllChem.MMFFHasAllMoleculeParams(optimized):
        raise ValueError(f"{variant} parameters missing; no silent UFF substitution in this benchmark.")
    properties = AllChem.MMFFGetMoleculeProperties(optimized, mmffVariant=variant)
    force = AllChem.MMFFGetMoleculeForceField(optimized, properties)
    status = force.Minimize(maxIts=1000)
    if status != 0:
        raise ValueError(f"{variant} did not converge within 1000 iterations.")
    return optimized, float(force.CalcEnergy())


def parse_xtb(molecule, xyz_path, log):
    if "geometry optimization converged" not in log.lower():
        raise ValueError("xTB did not report converged geometry optimization.")
    energies = re.findall(r"TOTAL ENERGY\s+([-+0-9.eEdD]+)\s+Eh", log, flags=re.I)
    if not energies:
        raise ValueError("xTB total energy in Hartree was not found.")
    energy = float(energies[-1].replace("D", "E").replace("d", "e")) * HARTREE_TO_KCAL
    lines = xyz_path.read_text().splitlines()
    if int(lines[0]) != molecule.GetNumAtoms() or len(lines[2:]) != molecule.GetNumAtoms():
        raise ValueError("xTB changed atom count or returned an incomplete geometry.")
    optimized = Chem.Mol(molecule)
    conformer = optimized.GetConformer()
    for index, (atom, line) in enumerate(zip(optimized.GetAtoms(), lines[2:])):
        fields = line.split()
        if len(fields) != 4 or fields[0].lower() != atom.GetSymbol().lower():
            raise ValueError("xTB atom order/elements changed; geometry mapping is unsafe.")
        coordinates = tuple(float(value) for value in fields[1:])
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError("xTB returned non-finite coordinates.")
        conformer.SetAtomPosition(index, coordinates)
    if not math.isfinite(energy):
        raise ValueError("xTB returned non-finite energy.")
    # Do not silently retain an inverted specified stereocenter.
    check = Chem.Mol(optimized)
    Chem.AssignStereochemistryFrom3D(check, replaceExistingTags=True)
    Chem.AssignStereochemistry(check, cleanIt=True, force=True)
    for before, after in zip(optimized.GetAtoms(), check.GetAtoms()):
        if before.HasProp("_CIPCode") and (not after.HasProp("_CIPCode") or
                                           before.GetProp("_CIPCode") != after.GetProp("_CIPCode")):
            raise ValueError("xTB geometry inverted a specified stereocenter.")
    return optimized, energy


def minimize_xtb(molecule, folder, xtb, solvent, timeout):
    Chem.MolToXYZFile(molecule, str(folder / "input.xyz"))
    command = [xtb, "input.xyz", "--gfn", "2", "--opt", "tight", "--chrg",
               str(Chem.GetFormalCharge(molecule)), "--uhf",
               str(sum(atom.GetNumRadicalElectrons() for atom in molecule.GetAtoms())), "--parallel", "1"]
    if solvent:
        command += ["--alpb", "water"]
    log = run(command, folder, "xtb", timeout)
    return parse_xtb(molecule, folder / "xtbopt.xyz", log)


def aligned_rmsd(first, second):
    # GetBestRMS mutates the probe: use copies, never move retained dock inputs.
    return float(rdMolAlign.GetBestRMS(Chem.RemoveHs(Chem.Mol(first)),
                                     Chem.RemoveHs(Chem.Mol(second)), maxMatches=100000))


def prune(records, threshold, keep):
    selected = []
    for record in sorted(records, key=lambda item: (item["energy_kcal_mol"], item["input_id"])):
        nearest = min((aligned_rmsd(record["molecule"], old["molecule"]) for old in selected), default=None)
        record["nearest_selected_rmsd_angstrom"] = nearest
        if nearest is not None and nearest < threshold:
            record["disposition"] = "near_duplicate"
        elif len(selected) < keep:
            record["disposition"] = "retained"
            selected.append(record)
        else:
            record["disposition"] = "distinct_over_budget"
    return selected


def dock_arm(args, folder, selected, seeds, tools):
    rows = []
    for index, record in enumerate(selected, 1):
        work = folder / f"dock_conf_{index:02d}"
        work.mkdir()
        sdf(work / "ligand.sdf", [record["molecule"]])
        run([sys.executable, tools["meeko"], "-i", str(work / "ligand.sdf"),
             "-o", str(work / "ligand.pdbqt"), "--charge_model", "gasteiger"], work, "meeko", args.timeout)
        for seed in seeds:
            print(f"  Docking {folder.name}, conformer {index}, seed {seed}", flush=True)
            target = work / f"seed_{seed}"
            target.mkdir()
            run([tools["vina"], "--receptor", str(args.receptor_pdbqt), "--ligand", str(work / "ligand.pdbqt"),
                 "--config", str(folder.parent / "box.conf"), "--out", str(target / "poses.pdbqt"),
                 "--seed", str(seed), "--cpu", "1", "--exhaustiveness", str(args.exhaustiveness),
                 "--num_modes", str(args.num_modes), "--energy_range", "3"], target, "vina", args.timeout)
            run([sys.executable, str(ROOT / "libexec/docking-universal-redock-compare.py"),
                 "--reference-sdf", str(work / "ligand.sdf"), "--crystal-ligand", str(args.crystal_ligand),
                 "--docked-pdbqt", str(target / "poses.pdbqt"), "--receptor-pdb", str(args.receptor_pdb),
                 "--mk-export", tools["exporter"], "--out", str(target / "comparison")], target, "compare", args.timeout)
            with (target / "comparison/pose_comparison.csv").open() as handle:
                for row in csv.DictReader(handle):
                    rows.append(dict(row, arm=folder.name, conformer=index, input_id=record["input_id"], seed=seed))
    metrics = []
    for seed in seeds:
        subset = [row for row in rows if row["seed"] == seed]
        top = min(subset, key=lambda row: float(row["affinity_kcal_per_mol"]))
        best = min(float(row["crystal_rmsd_angstrom"]) for row in subset)
        metrics.append({"seed": seed, "pose_count": len(subset),
                        "top_score_kcal_mol": float(top["affinity_kcal_per_mol"]),
                        "top_score_rmsd_angstrom": float(top["crystal_rmsd_angstrom"]),
                        "top_score_recovered_2A": float(top["crystal_rmsd_angstrom"]) <= 2.0,
                        "best_rmsd_angstrom": best, "any_pose_recovered_2A": best <= 2.0})
    with (folder / "poses.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return metrics


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ligand", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="New/empty benchmark directory")
    parser.add_argument("--attempts", type=int, default=16)
    parser.add_argument("--keep", type=int, default=3)
    parser.add_argument("--rmsd", type=float, default=0.75)
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--vacuum-backend", choices=("mmff94", "gfn2"), default="mmff94")
    parser.add_argument("--xtb", default="xtb")
    parser.add_argument("--timeout", type=int, default=600, help="Seconds per external command")
    parser.add_argument("--receptor-pdbqt", type=Path)
    parser.add_argument("--receptor-pdb", type=Path)
    parser.add_argument("--box", type=Path, help="Vina config containing only center/size entries")
    parser.add_argument("--crystal-ligand", type=Path, help="Exact extracted bound instance, PDB format")
    parser.add_argument("--dock-seeds", type=int, nargs="+", default=[41001])
    parser.add_argument("--exhaustiveness", type=int, default=8)
    parser.add_argument("--num-modes", type=int, default=9)
    parser.add_argument("--vina", default="vina")
    parser.add_argument("--meeko", default=str(Path(sys.executable).parent / "mk_prepare_ligand.py"))
    parser.add_argument("--mk-export", default=str(Path(sys.executable).parent / "mk_export.py"))
    args = parser.parse_args(argv)
    if not (1 <= args.keep <= args.attempts) or not math.isfinite(args.rmsd) or args.rmsd <= 0:
        parser.error("Require attempts >= keep >= 1 and a positive finite RMSD threshold.")
    if min(args.timeout, args.exhaustiveness, args.num_modes) < 1 or not 0 <= args.seed < 2147483647:
        parser.error("Require positive timeout/docking effort and a valid nonnegative 32-bit embedding seed.")
    if any(not 1 <= seed < 2147483647 for seed in args.dock_seeds):
        parser.error("Docking seeds must be positive 32-bit integers; seed 0 is not reproducible in Vina.")
    dock_inputs = [args.receptor_pdbqt, args.receptor_pdb, args.box, args.crystal_ligand]
    docking = any(dock_inputs)
    if docking and not all(dock_inputs):
        parser.error("Redocking requires --receptor-pdbqt, --receptor-pdb, --box and --crystal-ligand together.")
    for key in ("ligand", "receptor_pdbqt", "receptor_pdb", "box", "crystal_ligand"):
        value = getattr(args, key)
        if value:
            value = value.expanduser().resolve()
            if not value.is_file():
                parser.error(f"Missing {key}: {value}")
            setattr(args, key, value)
    root = args.out.expanduser().resolve()
    if root.exists() and (not root.is_dir() or any(root.iterdir())):
        parser.error("--out must be new or empty; existing runs are never overwritten.")
    tools = {"xtb": executable(args.xtb)}
    if docking:
        tools.update(vina=executable(args.vina), meeko=executable(args.meeko), exporter=executable(args.mk_export))
        # Prevent hidden config inputs/budgets from differing or overriding flags.
        box = {}
        for line in args.box.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            key, value = (part.strip() for part in line.split("=", 1))
            if key not in {f"{prefix}_{axis}" for prefix in ("center", "size") for axis in "xyz"} or key in box:
                parser.error("Box config must contain exactly the six unique center_x/y/z and size_x/y/z values.")
            box[key] = float(value)
        if len(box) != 6 or not all(math.isfinite(value) for value in box.values()) or any(box[f"size_{axis}"] <= 0 for axis in "xyz"):
            parser.error("Box config requires six finite values and positive sizes.")
    root.mkdir(parents=True, exist_ok=True)
    summary = {"schema": "conformer-ab-v1", "status": "running", "arguments": {key: str(value) if isinstance(value, Path) else value for key, value in vars(args).items()},
               "rdkit_version": rdBase.rdkitVersion, "executables": tools,
               "input_sha256": {key: digest(getattr(args, key)) for key in ("ligand", "receptor_pdbqt", "receptor_pdb", "box", "crystal_ligand") if getattr(args, key)},
               "chemical_state_policy": "exact supplied SDF state; no protonation/tautomer enumeration",
               "rmsd_method": "aligned symmetry-aware heavy atoms; within-state only",
               "energy_policy": "rank within each arm only; never compare absolute MMFF/xTB energies or chemical states",
               "interpretation": "preparation-method comparison" if args.vacuum_backend == "mmff94" else "matched GFN2-xTB solvent comparison",
               "arms": {}}
    dump(root / "summary.json", summary)
    try:
        summary["xtb_version_output"] = run([tools["xtb"], "--version"], root, "xtb_version", args.timeout).strip()
        smiles, pool = independent_pool(args.ligand, args.attempts, args.seed)
        summary.update(smiles=smiles, heavy_atoms=pool[0].GetNumHeavyAtoms(), embedded_count=len(pool))
        sdf(root / "shared_initial_pool.sdf", pool)
        summary["shared_pool_sha256"] = digest(root / "shared_initial_pool.sdf")
        chosen = {}
        for arm in ("vacuum_pruned", "water_pruned"):
            folder = root / arm
            folder.mkdir()
            start = time.monotonic()
            records, failures = [], []
            for index, molecule in enumerate(pool, 1):
                print(f"{arm}: minimizing {index}/{len(pool)}", flush=True)
                work = folder / f"input_{index:03d}"
                work.mkdir()
                try:
                    if arm == "vacuum_pruned" and args.vacuum_backend == "mmff94":
                        optimized, energy = minimize_mmff(molecule)
                    else:
                        optimized, energy = minimize_xtb(molecule, work, tools["xtb"], arm == "water_pruned", args.timeout)
                    if not math.isfinite(energy):
                        raise ValueError("Non-finite minimized energy.")
                    sdf(work / "minimized.sdf", [optimized])
                    records.append({"input_id": index, "molecule": optimized, "energy_kcal_mol": energy})
                except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
                    failures.append({"input_id": index, "reason": str(error)})
            chosen[arm] = prune(records, args.rmsd, args.keep)
            sdf(folder / "retained.sdf", [record["molecule"] for record in chosen[arm]])
            summary["arms"][arm] = {"minimization_seconds": time.monotonic() - start,
                                    "converged_count": len(records), "retained_count": len(chosen[arm]),
                                    "failures": failures, "records": [{key: value for key, value in record.items() if key != "molecule"} for record in records]}
            dump(root / "summary.json", summary)
            if not chosen[arm]:
                raise RuntimeError(f"No converged conformers survived in {arm}; see summary/logs. No fallback.")
        if docking:
            (root / "box.conf").write_text("".join(f"{key} = {value}\n" for key, value in box.items()))
            budget = min(len(selected) for selected in chosen.values())
            summary["docked_conformers_per_arm"] = budget
            seeds = list(dict.fromkeys(args.dock_seeds))
            for arm, selected in chosen.items():
                start = time.monotonic()
                summary["arms"][arm]["docked_input_ids"] = [record["input_id"] for record in selected[:budget]]
                summary["arms"][arm]["redocking"] = dock_arm(args, root / arm, selected[:budget], seeds, tools)
                summary["arms"][arm]["docking_seconds"] = time.monotonic() - start
                dump(root / "summary.json", summary)
        summary["status"] = "completed"
        dump(root / "summary.json", summary)
        rows = []
        for arm, result in summary["arms"].items():
            base = {"arm": arm, "embedded": len(pool), "converged": result["converged_count"],
                    "retained": result["retained_count"], "failed": len(result["failures"]),
                    "minimization_seconds": round(result["minimization_seconds"], 2)}
            rows.extend(dict(base, **metrics) for metrics in result.get("redocking", [{}]))
        with (root / "comparison.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        print(f"Paired comparison: {root / 'comparison.csv'}\nAudit and exclusions: {root / 'summary.json'}")
    except BaseException as error:
        summary.update(status="failed", error=str(error))
        dump(root / "summary.json", summary)
        raise
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f"Benchmark stopped: {error}") from error
