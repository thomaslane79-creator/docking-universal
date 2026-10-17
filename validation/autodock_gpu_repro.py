#!/usr/bin/env python3
"""Isolated same-seed diagnostics; no preparation or production changes."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

import numpy as np
from rdkit import Chem
from rdkit.Chem import rdMolAlign
from autodock_gpu_trial import digest, execute, parse_xml, pdbqt_atoms, pose_from_template, save


def fingerprint(folder, nrun):
    poses = []
    populations = []
    for n in range(1, nrun + 1):
        atoms = pdbqt_atoms((folder / f"ligand_docked_run{n}_entity1.pdbqt").read_text())
        poses.append([list(a[1]) for a in atoms])
        table = (folder / f"final_population_run{n}.txt").read_text()
        # Compare scientific table only, not headers/times/paths.
        populations.extend(line for line in table.splitlines() if "|" in line and re.match(r"^\s*\d+\s*\|", line))
    if len(populations) != 150 * nrun:
        raise ValueError("Incomplete final-population table")
    return {"pose_sha256": hashlib.sha256(json.dumps(poses).encode()).hexdigest(),
            "population_sha256": hashlib.sha256("\n".join(populations).encode()).hexdigest(),
            "population_rows": len(populations), "coordinates": poses}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pilot", type=Path, required=True)
    p.add_argument("--engine", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--phase", choices=["short", "full", "focused", "ad", "default", "force", "medium", "energy"], default="short")
    a = p.parse_args()
    out = a.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    pilot = json.loads((a.pilot / "summary.json").read_text())
    state = {"status": "running", "engine": str(a.engine.resolve()), "engine_sha256": digest(a.engine),
             "harness_sha256": digest(__file__), "phase": a.phase, "processes": [], "runs": [],
             "production_changed": False, "map_hashes": {}, "comparisons": []}
    summary = out / "summary.json"
    save(summary, state)
    specs = []
    if a.phase == "force":
        specs = [(0, "ad", 100, 20, 1, rep, "41001") for rep in range(5)]
    elif a.phase == "medium":
        specs = [(0, "ad", 100, 20, 5, rep, "41001") for rep in range(3)]
    elif a.phase == "short":
        for method, rate in [("ad", 0), ("ad", 100), ("sw", 100)]:
            for nrun in [1, 20]:
                for ngen in [1, 5, 20]:
                    for rep in range(3):
                        specs.append((0, method, rate, nrun, ngen, rep, "41001"))
        # Positive control: changing the seed must change the generated shapes.
        specs.append((0, "ad", 0, 20, 1, 0, "41002"))
        specs.append((0, "ad", 0, 20, 1, 0, "41001,0,0"))
    elif a.phase in ("focused", "ad"):
        for method, rate in ([("ad", 100)] if a.phase == "ad" else [("ad", 0), ("ad", 100), ("sw", 100)]):
            for ngen in [1, 5, 20]:
                for rep in range(3):
                    specs.append((0, method, rate, 20, ngen, rep, "41001"))
    else:
        for ci, seed in [(0, "41001"), (1, "20260808")]:
            for rep in range(1 if a.phase == "energy" else 3):
                specs.append((ci, "ad", 100, 20, 42000, rep, seed))
    try:
        for ci, method, rate, nrun, ngen, rep, seed in specs:
            case = pilot["cases"][ci]
            source = a.pilot.resolve() / case["id"]
            name = f"{case['id']}_{method}_ls{rate}_runs{nrun}_gen{ngen}_seed{seed.replace(',', '-')}_r{rep}"
            target = out / name
            target.mkdir()
            shutil.copy2(case["ligand"], target / "ligand.pdbqt")
            # Absolute original map paths: no map regeneration or mutable symlink.
            for path in source.glob("receptor.*.map"):
                state["map_hashes"][str(path)] = digest(path)
            cmd = [a.engine.resolve(), "--ffile", source / "receptor.maps.fld", "--lfile", "ligand.pdbqt",
                   "--resnam", "result", "--seed", seed, "--devnum", "1", "--nrun", str(nrun),
                   "--heuristics", "0", "--nev", "5210753" if ci == 0 else "12000000", "--autostop", "1" if a.phase == "default" else "0",
                   "--psize", "150", "--ngen", str(ngen), "--lsmet", method, "--lsrat", str(rate), "--lsit", "300",
                   "--npdb", "1", "--gbest", "0", "--gfpop", "1", "--rmstol", "1.5", "--output-cluster-poses", "0"]
            if a.phase == "default":
                cmd[cmd.index("--heuristics") + 1] = "1"
                cmd[cmd.index("--nev")] = "--heurmax"
                cmd[cmd.index("--heurmax") + 1] = "12000000"
            if a.phase == "force":
                cmd[cmd.index("--lsit") + 1] = "1"
            process = execute(cmd, target, "adgpu", state, summary, 1200)
            log = (target / "adgpu.stdout.log").read_text()
            if "Apple M2 Max" not in log or "All jobs ran without errors." not in log:
                raise ValueError("GPU/completion not confirmed")
            energies = parse_xml(target / "result.xml", nrun)
            fp = fingerprint(target, nrun)
            row = {"id": name, "case": case["id"], "method": method, "lsrate": rate, "nrun": nrun,
                   "ngen": ngen, "seed": seed, "repeat": rep, "energies": energies,
                   "job_seconds": float(re.search(r"Job #1 took ([\d.]+) sec", log)[1]),
                   "wall_seconds": process["wall_seconds"], **fp}
            if a.phase in ("full", "default", "energy"):
                crystal = next(iter(Chem.SDMolSupplier(case["crystal_sdf"], removeHs=True))) if case.get("crystal_sdf") else None
                rmsds = {}
                for n in energies:
                    molecule = pose_from_template(Path(case["ligand"]).read_text(),
                        (target / f"ligand_docked_run{n}_entity1.pdbqt").read_text())
                    if crystal is not None:
                        rmsds[n] = rdMolAlign.CalcRMS(molecule, crystal)
                winner = min(energies, key=lambda n: (energies[n], n))
                row.update(chemistry_checks_passed=True, crystal_rmsds_angstrom=rmsds,
                    lowest_energy_run=winner, lowest_energy_kcal_mol=energies[winner],
                    lowest_energy_crystal_rmsd_angstrom=rmsds.get(winner),
                    best_of_runs_crystal_rmsd_secondary=min(rmsds.values()) if rmsds else None)
            previous = [r for r in state["runs"] if all(r[k] == row[k] for k in ["case", "method", "lsrate", "nrun", "ngen", "seed"])]
            if previous:
                ref = previous[0]
                delta = np.array(row["coordinates"]) - np.array(ref["coordinates"])
                state["comparisons"].append({"id": name, "reference": ref["id"],
                    "poses_identical": row["pose_sha256"] == ref["pose_sha256"],
                    "populations_identical": row["population_sha256"] == ref["population_sha256"],
                    "max_coordinate_difference_angstrom": float(np.max(np.abs(delta))),
                    "max_run_energy_difference": max(abs(energies[n] - ref["energies"][n]) for n in energies)})
            state["runs"].append(row)
            save(summary, state)
        if digest(a.engine) != state["engine_sha256"]:
            raise ValueError("Engine changed during diagnostic")
        for path, expected in state["map_hashes"].items():
            if digest(path) != expected:
                raise ValueError("Map changed during diagnostic")
        for case in pilot["cases"]:
            for key, expected in case["hashes"].items():
                if digest(case[key]) != expected:
                    raise ValueError("Original retained input changed")
        state["status"] = "completed_diagnostic_not_production_acceptance"
    except BaseException as error:
        state.update(status="failed", error=str(error))
        raise
    finally:
        save(summary, state)


if __name__ == "__main__":
    main()
