#!/usr/bin/env python3
"""Extend matched-coordinate references to added ordinary-ligand atom types.

Two instrumented repeats have a distinct purpose: capture raw GPU arrays and
independent numerical references, not add more independent recovery seeds.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

from autodock_gpu_control_panel import ARMS, RUN_ROOT, assess_run, command
from autodock_gpu_energy_reference import analyze
from autodock_gpu_trial import check_idle, digest, execute, save


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--panel", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    source = a.panel.resolve() / "summary.json"
    panel = json.loads(source.read_text())
    if panel["status"] != "completed_assessment_pending_review":
        raise ValueError("Main panel must finish before starting this separate audit")
    out = a.out.resolve()
    if out.exists():
        raise ValueError("Audit output exists; no duplicate/restart")
    check_idle()
    engine = RUN_ROOT / "source-energy-audit/bin/adgpu_energy_audit_128"
    out.mkdir(parents=True, exist_ok=False)
    path = out / "summary.json"
    state = {"status": "running", "pid": os.getpid(), "processes": [], "cases": [],
             "started_utc": datetime.now(timezone.utc).isoformat(),
             "panel_sha256": digest(source), "harness_sha256": digest(__file__),
             "engine_sha256": digest(engine), "production_changed": False,
             "purpose": "Two instrumented repeats to capture raw arrays, not independent recovery samples or timing improvements.",
             "declared_gates": {"bounded_max_absolute_kcal_mol": .001, "run_winner_max_absolute_kcal_mol": .0001,
                                "all_population_max_scaled_error": .00001,
                                "interpretation": "Matched GPU formulas on identical GPU coordinates, CPU grid reference; retain all entities and absolute extremes. These are new explicit audit gates, not a change to earlier evidence/tolerances."}}
    save(path, state)
    try:
        for case in panel["cases"]:
            if case["id"] not in ("tipranavir_2o4p", "kni577_1mrw"):
                continue
            if case["status"] != "completed":
                raise ValueError("Expected completed ordinary-ligand control")
            reference = next(r for r in case["runs"] if r["arm"] == ARMS[0] and r["repeat"] == 0)
            maps = Path(next(iter(case["map_hashes"]))).parent / "receptor.maps.fld"
            for file, expected in {**case["input_hashes"], **case["map_hashes"]}.items():
                if digest(file) != expected:
                    raise ValueError("Retained source changed")
            target = out / case["id"]
            target.mkdir()
            shutil.copy2(case["ligand"], target / "ligand.pdbqt")
            process = execute(command(engine, maps, ARMS[0], 41001), target, "adgpu", state, path, 900)
            run = assess_run(case, target, process, 41001, 0, ARMS[0])
            matches = {k: run[k] == reference[k] for k in ("pose_sha256", "population_sha256", "scores_sha256")}
            numerical = analyze(target)
            comparisons = numerical["comparisons"]["independent_gpu_formula_minus_gpu"]
            bounded = comparisons["both_absolute_energies_le_1000"]["max"]
            winners = comparisons["run_winners"]["max"]
            scaled = numerical["matched_model_scaled_error"]["all"]["max"]
            gates = state["declared_gates"]
            passed = all(matches.values()) and bounded <= gates["bounded_max_absolute_kcal_mol"] and winners <= gates["run_winner_max_absolute_kcal_mol"] and scaled <= gates["all_population_max_scaled_error"]
            row = {"id": case["id"], "search_chemistry_checks_passed": run["chemistry_checks_passed"],
                   "same_seed_uninstrumented_matches": matches, "pose_count": run["pose_count"],
                   "numerical_reference": numerical, "declared_gates_passed": passed}
            state["cases"].append(row)
            save(path, state)
            if not passed:
                raise ValueError("Numerical/instrumentation comparison failed: " + case["id"])
            for file, expected in {**case["input_hashes"], **case["map_hashes"]}.items():
                if digest(file) != expected:
                    raise ValueError("Retained source changed during audit")
        if len(state["cases"]) != 2 or digest(engine) != state["engine_sha256"]:
            raise ValueError("Incomplete audit or changed executable")
        state["status"] = "completed_scoped_numerical_checks"
    except BaseException as error:
        state.update(status="failed", error=str(error))
        raise
    finally:
        state["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save(path, state)


if __name__ == "__main__":
    main()
