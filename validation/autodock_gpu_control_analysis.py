#!/usr/bin/env python3
"""Read-only assessment of retained panel outputs; no engine calls or reruns."""
import argparse
import json
from pathlib import Path
import statistics

from rdkit import Chem
from rdkit.Chem import rdMolAlign
from autodock_gpu_trial import ROOT, digest, mapped_molecule, save


def eight_thread_vina_context(case):
    """Reuse the later retained CPU pilot, only with verified matching inputs."""
    name = {"indinavir_protease": "indinavir_protease", "imatinib_1iep": "imatinib_abl"}.get(case["id"])
    if name is None:
        return None
    base = ROOT / "validation/runs/vina-three-target-threads-20261015"
    config_path = base / (name + ".json")
    config = json.loads(config_path.read_text())
    if digest(config["receptor"]) != digest(case["receptor"]) or digest(config["compounds"][0]["prepared"][0]) != digest(case["ligand"]) or config["geometry"] != case["geometry"]:
        raise ValueError("Eight-thread Vina context is not matched to retained input")
    crystal = next(iter(Chem.SDMolSupplier(case["crystal_sdf"], removeHs=True)))
    rows = []
    records = {}
    for repeat in (1, 2):
        path = base / f"{name}_r{repeat}_cpu8/execution.json"
        data = json.loads(path.read_text())
        if data["status"] != "completed" or data["cpu_setting"] != 8:
            raise ValueError("Eight-thread Vina context did not complete")
        records[str(path)] = digest(path)
        for job in data["jobs"]:
            text = Path(job["output"]).read_text()
            mol = mapped_molecule(text)
            rows.append({"seed": job["seed"], "repeat": repeat, "dock_seconds": job["dock_seconds"],
                         "lowest_energy_crystal_rmsd_angstrom": rdMolAlign.CalcRMS(mol, crystal, prbId=0),
                         "output": job["output"], "output_sha256": digest(job["output"])})
    return {"rows": rows, "parameters": config["parameters"], "execution_hashes": records,
            "config_sha256": digest(config_path), "median_search_only_seconds": statistics.median(r["dock_seconds"] for r in rows),
            "meaning": "Historical eight-thread Vina search-only timing on exact inputs/box; two seeds and two repeats, different engine/search/effort. Not equivalent-work GPU speedup; neither preparation nor full-library/report time."}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise ValueError("Analysis output exists; refusing to overwrite evidence")
    source = a.panel / "summary.json"
    state = json.loads(source.read_text())
    if state["status"] != "completed_assessment_pending_review":
        raise ValueError("Panel has not completed successfully: " + state["status"])
    result = {"status": "completed_analysis_not_production_integration", "panel": str(source.resolve()),
              "panel_sha256": digest(source), "harness_sha256": digest(__file__), "cases": [],
              "engine_sha256": state["engine_sha256"], "production_changed": False,
              "energy_meaning": state["energy_meaning"], "limitations": state["limitations"]}
    counts = {"supported_controls": 0, "unsupported_controls": 0, "search_invocations_in_evidence": 0,
              "new_search_invocations_in_checked_coordinator": 0, "reused_completed_invocations": 0,
              "poses_checked": 0, "same_seed_repeat_comparisons": 0}
    for case in state["cases"]:
        item = {"id": case["id"], "status": case["status"], "arms": {}, "heavy_atoms": case["heavy_atoms"],
                "rdkit_rotatable_bonds": case["rdkit_rotatable_bonds"]}
        if case["status"] == "unsupported_not_launched":
            counts["unsupported_controls"] += 1
            item["reason"] = case["reason"]
            result["cases"].append(item)
            continue
        if case["status"] != "completed" or not case.get("inputs_and_maps_unchanged"):
            raise ValueError("Incomplete case: " + case["id"])
        counts["supported_controls"] += 1
        item.update(map_wall_seconds=case["map_wall_seconds"], input_hashes=case["input_hashes"],
                    historical_vina=case["historical_vina"])
        item["eight_thread_vina_context"] = eight_thread_vina_context(case)
        for file, expected in {**case["input_hashes"], **case["map_hashes"]}.items():
            if digest(file) != expected:
                raise ValueError("Retained source changed: " + file)
        map_folder = Path(next(iter(case["map_hashes"]))).parent
        if digest(map_folder / "receptor.pdbqt") != digest(case["receptor"]):
            raise ValueError("Map-generation receptor differs from retained input")
        item["historical_vina_primary_recovery_2A"] = sum(
            r["lowest_energy_crystal_rmsd_angstrom"] <= 2 for r in case["historical_vina"]["rows"])
        for row in case["historical_vina"]["rows"]:
            if digest(row["output"]) != row["sha256"]:
                raise ValueError("Historical Vina output changed")
        for arm in state["search_arms"]:
            runs = [r for r in case["runs"] if r["arm"] == arm]
            independent = [r for r in runs if r["repeat"] < 3]
            repeats = [r for r in runs if r["repeat"] == 3]
            if len(runs) != 4 or len(independent) != 3 or len(repeats) != 1:
                raise ValueError("Missing declared invocation")
            if not all(repeats[0].get("repeat_matches", {}).values()) or len(repeats[0].get("repeat_matches", {})) != 3:
                raise ValueError("Same-seed repeat did not pass")
            counts["same_seed_repeat_comparisons"] += 1
            for r in runs:
                if not r["chemistry_checks_passed"] or r["pose_count"] != 20 or r["population_rows"] != 3000:
                    raise ValueError("Incomplete pose/population/chemistry check")
                if digest(Path(r["directory"]) / "ligand.pdbqt") != digest(case["ligand"]):
                    raise ValueError("Search ligand copy differs from retained input")
                counts["search_invocations_in_evidence"] += 1
                counts["poses_checked"] += r["pose_count"]
                if "reused_completed_calculation" in r:
                    counts["reused_completed_invocations"] += 1
                    for file, expected in r["reused_completed_calculation"]["file_hashes"].items():
                        if digest(file) != expected:
                            raise ValueError("Reused native output changed: " + file)
                else:
                    counts["new_search_invocations_in_checked_coordinator"] += 1
                for pose in r["poses"]:
                    if digest(pose["pdbqt"]) != pose["sha256"]:
                        raise ValueError("Retained pose changed")
            rows = [{"seed": r["seed"], "binding_energy_kcal_mol": r["primary"]["binding_energy_kcal_mol"],
                     "primary_run": r["primary"]["run"],
                     "lowest_energy_crystal_rmsd_angstrom": r["primary"]["crystal_rmsd_angstrom"],
                     "recovered_within_2A": r["lowest_energy_recovered_2A"],
                     "best_of_runs_rmsd_secondary": r["best_of_runs_rmsd_secondary"],
                     "wall_seconds": r["wall_seconds"], "engine_job_seconds": r["engine_job_seconds"],
                     "evaluations_per_run_reported": r["evaluations_per_run_reported"],
                     "gpu_total_search_kcal_mol_of_primary": r["primary"]["gpu_total_search_kcal_mol"],
                     "cpu_total_diagnostic_kcal_mol_of_primary": r["primary"]["cpu_total_report_kcal_mol"]}
                    for r in independent]
            item["arms"][arm] = {"rows": rows, "primary_recovery_within_2A": sum(r["recovered_within_2A"] for r in rows),
                "any_winner_recovery_within_2A_secondary": sum(r["best_of_runs_rmsd_secondary"] <= 2 for r in rows),
                "median_process_wall_seconds": statistics.median(r["wall_seconds"] for r in rows),
                "median_engine_job_seconds": statistics.median(r["engine_job_seconds"] for r in rows),
                "map_plus_three_searches_seconds": case["map_wall_seconds"] + sum(r["wall_seconds"] for r in rows),
                "same_seed_repeat_passed": True,
                "max_winner_cpu_gpu_total_difference_kcal_mol": max(abs(p["gpu_minus_cpu_total_kcal_mol"]) for r in runs for p in r["poses"])}
        result["cases"].append(item)
    if digest(state["engine"]) != state["engine_sha256"]:
        raise ValueError("Engine changed")
    result["counts"] = counts
    save(a.out, result)
    print(json.dumps({"status": result["status"], "counts": counts}, indent=2))


if __name__ == "__main__":
    main()
