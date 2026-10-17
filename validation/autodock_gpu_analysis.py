#!/usr/bin/env python3
"""Postprocess retained AD4 pilot; no docking or input mutation."""
import argparse
import json
import math
from pathlib import Path
import re
import statistics

import numpy as np
from rdkit import Chem
from rdkit.Chem import rdMolAlign

from autodock_gpu_trial import ROOT, digest, mapped_molecule, save


def energy_residuals(folder):
    all_values, winners, scaled, bounded = [], [], [], []
    files = list(folder.glob("final_population_run*.txt"))
    for path in files:
        count = 0
        for line in path.read_text().splitlines():
            if not re.match(r"^\s*\d+\s*\|", line):
                continue
            entity = int(line.split("|")[0])
            cpu, gpu, difference = map(float, line.split("|")[-3].split("/"))
            if not all(math.isfinite(v) for v in (cpu, gpu, difference)):
                raise ValueError("Non-finite CPU/GPU energy comparison")
            if abs(abs(gpu - cpu) - abs(difference)) > 0.0021:
                raise ValueError("Inconsistent energy-comparison columns")
            all_values.append(abs(difference))
            scaled.append(abs(gpu-cpu) / max(1, abs(cpu), abs(gpu)))
            if max(abs(cpu), abs(gpu)) <= 1000:
                bounded.append(abs(difference))
            if entity == 1:
                winners.append(abs(difference))
            count += 1
        if count != 150:
            raise ValueError(f"Expected 150 population rows, found {count}: {path}")
    if len(files) != 20 or len(winners) != 20:
        raise ValueError("Missing population energy-check files")
    return {"population_rows": len(all_values), "all_max_abs_kcal_mol": max(all_values),
            "all_p95_abs_kcal_mol": float(np.percentile(all_values, 95)),
            "winner_max_abs_kcal_mol": max(winners),
            "winner_median_abs_kcal_mol": statistics.median(winners),
            "max_scaled_error_all_populations": max(scaled),
            "population_rows_with_cpu_and_gpu_absolute_energy_le_1000": len(bounded),
            "max_abs_error_for_absolute_energy_le_1000": max(bounded) if bounded else None,
            "meaning": "engine CPU recomputation minus GPU total search energy, not binding-affinity validation"}


def protease_swap_reference(receptor, crystal):
    anchors = {}
    for line in receptor.read_text().splitlines():
        if line.startswith("ATOM  ") and line[12:16].strip() == "CA" and line[21] in "AB":
            anchors[(line[21], line[22:27])] = [float(line[i:i+8]) for i in (30, 38, 46)]
    keys = sorted(anchors)
    if len(keys) < 100 or any(("B" if chain == "A" else "A", number) not in anchors for chain, number in keys):
        raise ValueError("Cannot construct explicit A/B receptor symmetry audit")
    first = np.array([anchors[key] for key in keys])
    second = np.array([anchors[("B" if chain == "A" else "A", number)] for chain, number in keys])
    p, q = first.mean(axis=0), second.mean(axis=0)
    u, _, vt = np.linalg.svd((first-p).T @ (second-q))
    correction = np.eye(3)
    correction[2, 2] = np.linalg.det(u @ vt)
    rotation = u @ correction @ vt
    residual = float(np.sqrt(np.mean(np.sum(((first-p) @ rotation + q - second)**2, axis=1))))
    swapped = Chem.Mol(crystal)
    for i, xyz in enumerate((crystal.GetConformer().GetPositions()-p) @ rotation + q):
        swapped.GetConformer().SetAtomPosition(i, xyz)
    return swapped, {"protein_ca_swap_rmsd_angstrom": residual, "anchor_count": len(keys),
                     "method": "fit only receptor C-alpha A↔B correspondence; no ligand fitting",
                     "interpretation": "secondary approximate homodimer-symmetry diagnostic; primary deposited-frame RMSD remains unchanged"}


def vina_reference_metrics(case):
    if case["id"] == "indinavir_protease":
        path = ROOT / "validation/runs/vina-three-target-threads-20261015/indinavir_protease_r1_cpu8/execution.json"
        want_ligand = "ligand.pdbqt"
    else:
        path = ROOT / "validation/runs/vina-execution-20261015_095135/shared_grid_cpu8/execution.json"
        want_ligand = "independent_ensemble_1.pdbqt"
    data = json.loads(path.read_text())
    crystal = next(iter(Chem.SDMolSupplier(case["crystal_sdf"], removeHs=True))) if "crystal_sdf" in case else None
    rows = []
    for job in data["jobs"]:
        if job["ligand"] != want_ligand or job["seed"] not in set(case["seeds"]) or (
                case["id"] == "screen_flexible" and job["compound"] != "Siqueiraneto-Sspps-Library_26740Cpds_2"):
            continue
        output = Path(job["output"])
        text = output.read_text()
        energies = [float(e) for e in re.findall(r"REMARK VINA RESULT:\s+([-\d.]+)", text)]
        mol = mapped_molecule(text)
        if not energies or mol.GetNumConformers() != len(energies):
            raise ValueError("Vina output coordinate/score inventory mismatch")
        best = min(range(len(energies)), key=energies.__getitem__)
        row = {"seed": job["seed"], "search_seconds": job["dock_seconds"],
               "vina_energy_kcal_mol": energies[best], "output": str(output), "sha256": digest(output)}
        if crystal is not None:
            row["lowest_energy_crystal_rmsd_angstrom"] = rdMolAlign.CalcRMS(mol, crystal, prbId=best)
            row["best_of_poses_rmsd_secondary"] = min(rdMolAlign.CalcRMS(mol, crystal, prbId=i)
                                                      for i in range(mol.GetNumConformers()))
        rows.append(row)
    return {"execution_record": str(path), "sha256": digest(path), "rows": rows,
            "meaning": "historical eight-thread Vina context, different scoring/search/output budget; not a matched GPU implementation speedup"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        parser.error("Use a new analysis output; never overwrite retained evidence")
    state = json.loads((args.pilot / "summary.json").read_text())
    if state["status"] != "completed_pilot_not_production_acceptance":
        raise ValueError("Pilot did not complete")
    result = {"status": "completed_analysis_not_production_acceptance", "pilot": str(args.pilot.resolve()),
              "pilot_summary_sha256": digest(args.pilot / "summary.json"), "cases": []}
    for case in state["cases"]:
        values = {"id": case["id"], "runs": [], "median_wall_seconds": case["median_wall_seconds"],
                  "repeat_identical_pose_files": case["repeat_identical_pose_files"],
                  "vina_historical_context": vina_reference_metrics(case)}
        swapped = None
        if "crystal_sdf" in case:
            crystal = next(iter(Chem.SDMolSupplier(case["crystal_sdf"], removeHs=True)))
            receptor = Path(case["receptor"]).with_suffix(".pdb")
            swapped, values["dimer_symmetry_audit"] = protease_swap_reference(receptor, crystal)
        for run in case["runs"]:
            folder = Path(run["lowest_energy_pose"]["pdbqt"]).parent
            row = {"seed": run["seed"], "repeat": run["repeat"], "wall_seconds": run["wall_seconds"],
                   "engine_reported_job_seconds": run["engine_reported_job_seconds"],
                   "lowest_energy_pose": run["lowest_energy_pose"],
                   "best_of_runs_rmsd_secondary": run.get("best_of_runs_rmsd_secondary"),
                   "cpu_gpu_energy_check": energy_residuals(folder)}
            dlg = (folder / "result.dlg").read_text()
            row["heuristic_evaluation_limit"] = int(re.search(r"Number of energy evaluations:\s+(\d+)", dlg)[1])
            row["evaluations_per_run_reported"] = int(re.search(r"Number of energy evaluations performed:\s+(\d+)", dlg)[1])
            row["generations_reported"] = int(re.search(r"Number of generations used:\s+(\d+)", dlg)[1])
            if swapped is not None:
                best = mapped_molecule(Path(run["lowest_energy_pose"]["pdbqt"]).read_text())
                row["top_pose_rmsd_to_chain_swapped_crystal_secondary"] = rdMolAlign.CalcRMS(best, swapped)
            values["runs"].append(row)
        result["cases"].append(values)
    save(args.out, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
