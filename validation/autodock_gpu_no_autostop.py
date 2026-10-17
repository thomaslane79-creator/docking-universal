#!/usr/bin/env python3
"""Controlled indinavir follow-up: disable early stopping, reuse exact maps.

Not a restart: a new declared search arm after the completed default pilot.
No default changes; no new preparation; no production installation.
"""
import argparse
import json
from pathlib import Path
import re
import shutil

from rdkit import Chem
from rdkit.Chem import rdMolAlign
from autodock_gpu_trial import digest, execute, parse_xml, pose_from_template, save
from autodock_gpu_analysis import energy_residuals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pilot", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    pilot = json.loads((args.pilot / "summary.json").read_text())
    if pilot["status"] != "completed_pilot_not_production_acceptance":
        raise ValueError("Original pilot must have completed")
    case = pilot["cases"][0]
    if case["id"] != "indinavir_protease":
        raise ValueError("This declared follow-up is indinavir only")
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    old = args.pilot.resolve() / case["id"]
    for path in old.glob("receptor.*"):
        shutil.copy2(path, out / path.name)
    state = {"status": "running", "processes": [], "runs": [], "production_changed": False,
             "source_pilot": str(args.pilot.resolve()), "source_summary_sha256": digest(args.pilot / "summary.json"),
             "engine": pilot["engine"], "engine_sha256": pilot["engine_sha256"],
             "harness_sha256": digest(__file__), "input_hashes": case["hashes"],
             "search_difference": "autostop off; heuristics off; explicit cap 5210753 evaluations per LGA run (same cap selected by original indinavir heuristic)",
             "nrun": 20, "seeds": [41001, 41002], "map_reuse": {p.name: digest(p) for p in out.glob("receptor.*.map")}}
    summary = out / "summary.json"
    save(summary, state)
    try:
        if digest(pilot["engine"]) != pilot["engine_sha256"]:
            raise ValueError("Engine changed")
        crystal = next(iter(Chem.SDMolSupplier(case["crystal_sdf"], removeHs=True)))
        ligand = Path(case["ligand"]).read_text()
        for seed in state["seeds"]:
            target = out / f"seed_{seed}"
            target.mkdir()
            (target / "ligand.pdbqt").write_text(ligand)
            command = [pilot["engine"], "--ffile", out / "receptor.maps.fld", "--lfile", "ligand.pdbqt",
                       "--resnam", "result", "--seed", str(seed), "--devnum", "1", "--nrun", "20",
                       "--heuristics", "0", "--nev", "5210753", "--autostop", "0",
                       "--psize", "150", "--ngen", "42000", "--lsmet", "ad", "--lsit", "300",
                       "--npdb", "1", "--gbest", "0", "--gfpop", "1", "--rmstol", "1.5",
                       "--output-cluster-poses", "0"]
            record = execute(command, target, "adgpu", state, summary, 900)
            log = (target / "adgpu.stdout.log").read_text()
            if "Apple M2 Max" not in log or "All jobs ran without errors." not in log:
                raise ValueError("GPU/completion not confirmed")
            rows = []
            for number, energy in sorted(parse_xml(target / "result.xml", 20).items()):
                path = target / f"ligand_docked_run{number}_entity1.pdbqt"
                molecule = pose_from_template(ligand, path.read_text())
                rows.append({"run": number, "ad4_binding_energy_kcal_mol": energy,
                             "crystal_rmsd_angstrom": rdMolAlign.CalcRMS(molecule, crystal),
                             "pdbqt": str(path), "sha256": digest(path)})
            top = min(rows, key=lambda row: (row["ad4_binding_energy_kcal_mol"], row["run"]))
            state["runs"].append({"seed": seed, "wall_seconds": record["wall_seconds"],
                "engine_reported_job_seconds": float(re.search(r"Job #1 took ([\d.]+) sec", log)[1]),
                "lowest_energy_pose": top, "lowest_energy_recovered_2A": top["crystal_rmsd_angstrom"] <= 2,
                "best_of_runs_rmsd_secondary": min(r["crystal_rmsd_angstrom"] for r in rows),
                "poses": rows, "cpu_gpu_energy_check": energy_residuals(target)})
            save(summary, state)
        for key, value in case["hashes"].items():
            if digest(case[key]) != value:
                raise ValueError("Original retained input changed")
        state["status"] = "completed_diagnostic_not_production_acceptance"
    except BaseException as error:
        state.update(status="failed", error=str(error))
        raise
    finally:
        save(summary, state)


if __name__ == "__main__":
    main()
