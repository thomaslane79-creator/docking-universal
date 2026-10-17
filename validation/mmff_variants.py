#!/usr/bin/env python
"""Matched MMFF94/MMFF94s controls, reusing only verified MMFF94 baselines.

Prepare all cases first; --dock subsequently runs sequential MMFF94s redocking.
No downloads, receptor preparation, crystal-seeded conformers or default changes.
"""
import argparse
import csv
import json
import math
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from rdkit import Chem, rdBase

import conformer_ab as ab


def load(path):
    return json.loads(path.read_text())


def read_sdf(path):
    molecules = list(Chem.SDMolSupplier(str(path), removeHs=False))
    if not molecules or any(molecule is None for molecule in molecules):
        raise ValueError(f"Unreadable ensemble: {path}")
    return molecules


def retained_ids(arm):
    return [row["input_id"] for row in sorted(arm["records"],
            key=lambda row: (row["energy_kcal_mol"], row["input_id"]))
            if row["disposition"] == "retained"]


def verify_baseline(records, selected, prior, molecules):
    """Require the regenerated baseline to match before reusing docking."""
    previous = {row["input_id"]: row for row in prior["records"]}
    if set(previous) != {row["input_id"] for row in records}:
        raise ValueError("MMFF94 convergence inventory changed; cannot reuse baseline.")
    if [row["input_id"] for row in selected] != retained_ids(prior):
        raise ValueError("MMFF94 retained IDs changed; cannot reuse baseline.")
    if len(selected) != len(molecules):
        raise ValueError("MMFF94 retained SDF count changed.")
    energy_error = max(abs(row["energy_kcal_mol"] - previous[row["input_id"]]["energy_kcal_mol"])
                       for row in records)
    coordinate_error = max(float(abs(row["molecule"].GetConformer().GetPositions() -
                                     old.GetConformer().GetPositions()).max())
                           for row, old in zip(selected, molecules))
    if energy_error > 1e-6 or coordinate_error > 0.00011:
        raise ValueError(f"MMFF94 baseline changed: energy {energy_error}, coordinates {coordinate_error}.")
    return {"maximum_energy_error_kcal_mol": energy_error,
            "maximum_coordinate_error_angstrom": coordinate_error,
            "coordinate_tolerance_reason": "archived SDF has four-decimal coordinates",
            "passed": True}


def csv_file(path, rows):
    if not rows:
        return
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def prepare_case(source, folder):
    baseline = load(source / "summary.json")
    preparation = Path(baseline.get("preparation", source))
    prior = load(preparation / "summary.json")
    if baseline["status"] != "completed" or prior["status"] != "completed":
        raise ValueError("Baseline preparation and docking must both be completed.")
    if prior["arguments"]["vacuum_backend"] != "mmff94" or prior["rdkit_version"] != rdBase.rdkitVersion:
        raise ValueError("Require MMFF94 baseline and identical RDKit version.")
    parameters = prior["arguments"]
    folder.mkdir()
    result = {"status": "preparing", "baseline": str(source), "preparation": str(preparation),
              "baseline_summary_sha256": ab.digest(source / "summary.json"),
              "rdkit_version": rdBase.rdkitVersion, "arms": {}}
    ab.dump(folder / "summary.json", result)
    try:
        smiles, pool = ab.independent_pool(Path(parameters["ligand"]), parameters["attempts"], parameters["seed"])
        ab.sdf(folder / "shared_initial_pool.sdf", pool)
        if ab.digest(folder / "shared_initial_pool.sdf") != prior["shared_pool_sha256"]:
            raise ValueError("Regenerated independent pool differs from baseline; refusing unmatched comparison.")
        result.update(smiles=smiles, embedded_count=len(pool), heavy_atoms=pool[0].GetNumHeavyAtoms(),
                      shared_pool_sha256=prior["shared_pool_sha256"], rmsd_prune_angstrom=parameters["rmsd"])
        selected_by_arm, all_by_arm = {}, {}
        for name, variant in (("mmff94", "MMFF94"), ("mmff94s", "MMFF94s")):
            arm_folder = folder / name
            arm_folder.mkdir()
            started = time.monotonic()
            records, failures = [], []
            for index, molecule in enumerate(pool, 1):
                try:
                    optimized, energy = ab.minimize_mmff(molecule, variant)
                    if not math.isfinite(energy):
                        raise ValueError("Non-finite minimized energy.")
                    check = Chem.Mol(optimized)
                    Chem.AssignStereochemistryFrom3D(check, replaceExistingTags=True)
                    Chem.AssignStereochemistry(check, cleanIt=True, force=True)
                    if any(atom.HasProp("_CIPCode") and (not other.HasProp("_CIPCode") or
                           atom.GetProp("_CIPCode") != other.GetProp("_CIPCode"))
                           for atom, other in zip(optimized.GetAtoms(), check.GetAtoms())):
                        raise ValueError("Minimization inverted a specified stereocenter.")
                    records.append({"input_id": index, "molecule": optimized, "energy_kcal_mol": energy})
                except ValueError as error:
                    failures.append({"input_id": index, "reason": str(error)})
            selected = ab.prune(records, parameters["rmsd"], parameters["keep"])
            if len(selected) != baseline.get("docked_conformers_per_arm", parameters["keep"]):
                raise ValueError("Insufficient distinct conformers for the existing matched docking budget.")
            ab.sdf(arm_folder / "minimized.sdf", [row["molecule"] for row in records])
            ab.sdf(arm_folder / "retained.sdf", [row["molecule"] for row in selected])
            result["arms"][name] = {"minimization_and_pruning_seconds": time.monotonic() - started,
                "converged_count": len(records), "failures": failures,
                "retained_sdf_sha256": ab.digest(arm_folder / "retained.sdf"),
                "selected_input_ids": [row["input_id"] for row in selected],
                "records": [{key: value for key, value in row.items() if key != "molecule"} for row in records]}
            selected_by_arm[name], all_by_arm[name] = selected, records
        result["baseline_reproduction"] = verify_baseline(all_by_arm["mmff94"], selected_by_arm["mmff94"],
            prior["arms"]["vacuum_pruned"], read_sdf(source / "vacuum_pruned/retained.sdf"))
        used_ids = baseline["arms"]["vacuum_pruned"].get("docked_input_ids",
                   baseline["arms"]["vacuum_pruned"].get("selected_input_ids"))
        if used_ids != result["arms"]["mmff94"]["selected_input_ids"]:
            raise ValueError("Baseline docked IDs differ from reproduced preparation.")
        cross = [[ab.aligned_rmsd(first["molecule"], second["molecule"]) for second in selected_by_arm["mmff94s"]]
                 for first in selected_by_arm["mmff94"]]
        a = {row["input_id"]: row for row in all_by_arm["mmff94"]}
        b = {row["input_id"]: row for row in all_by_arm["mmff94s"]}
        comparison = {"method": "aligned symmetry-aware heavy atoms; fitting only copies",
            "mmff94_rows_mmff94s_columns_rmsd_angstrom": cross,
            "same_input_rmsd_angstrom": {str(index): ab.aligned_rmsd(a[index]["molecule"], b[index]["molecule"])
                                         for index in a.keys() & b.keys()},
            "selected_input_ids": {name: [row["input_id"] for row in rows] for name, rows in selected_by_arm.items()}}
        ab.dump(folder / "conformation_comparison.json", comparison)
        # Only machine-identical coordinates may skip redocking; small geometric
        # differences can change a stochastic search, so do not call them equivalent.
        identical = (comparison["selected_input_ids"]["mmff94"] == comparison["selected_input_ids"]["mmff94s"]
                     and all(float(abs(first["molecule"].GetConformer().GetPositions() -
                                       second["molecule"].GetConformer().GetPositions()).max()) < 1e-8
                             for first, second in zip(selected_by_arm["mmff94"], selected_by_arm["mmff94s"])))
        result["identical_retained_coordinates"] = identical
        tools = baseline.get("executables", baseline.get("tools"))
        result["tools"] = {name: ab.executable(tools[name]) for name in ("vina", "meeko", "exporter")}
        result["seeds"] = baseline.get("seeds", parameters["dock_seeds"])
        result.update(exhaustiveness=baseline.get("exhaustiveness", parameters["exhaustiveness"]),
                      num_modes=baseline.get("num_modes", parameters["num_modes"]), timeout=parameters["timeout"])
        source_paths = {name: source / name for name in ("receptor.pdb", "receptor.pdbqt", "box.conf", "crystal_ligand.pdb")}
        if "arguments" in baseline:
            source_paths = {name: Path(baseline["arguments"][key]) for name, key in (
                ("receptor.pdb", "receptor_pdb"), ("receptor.pdbqt", "receptor_pdbqt"),
                ("box.conf", "box"), ("crystal_ligand.pdb", "crystal_ligand"))}
        result["input_sha256"] = {}
        for name, path in source_paths.items():
            key = name if "arguments" not in baseline else {
                "receptor.pdb": "receptor_pdb", "receptor.pdbqt": "receptor_pdbqt",
                "box.conf": "box", "crystal_ligand.pdb": "crystal_ligand"}[name]
            if ab.digest(path) != baseline["input_sha256"][key]:
                raise ValueError(f"Baseline control input changed: {path}")
            shutil.copy2(path, folder / name)
            result["input_sha256"][name] = ab.digest(path)
        result["arms"]["mmff94"]["redocking"] = baseline["arms"]["vacuum_pruned"]["redocking"]
        result["arms"]["mmff94"]["docking_reused_from"] = str(source / "vacuum_pruned")
        shutil.copy2(source / "vacuum_pruned/poses.csv", folder / "mmff94/poses.csv")
        result["status"] = "ready"
    except BaseException as error:
        result.update(status="failed", error=str(error))
        raise
    finally:
        ab.dump(folder / "summary.json", result)
    return result


def dock_case(folder):
    result = load(folder / "summary.json")
    if result["status"] != "ready":
        raise ValueError("Dock case must be ready; completed/partial cases cannot be silently rerun.")
    result["status"] = "running"
    ab.dump(folder / "summary.json", result)
    try:
        for name, expected in result["input_sha256"].items():
            if ab.digest(folder / name) != expected:
                raise ValueError(f"Control input changed: {name}")
        for name, arm in result["arms"].items():
            if ab.digest(folder / name / "retained.sdf") != arm["retained_sdf_sha256"]:
                raise ValueError(f"Retained conformers changed: {name}")
        if result["identical_retained_coordinates"]:
            result["arms"]["mmff94s"]["redocking"] = result["arms"]["mmff94"]["redocking"]
            result["arms"]["mmff94s"]["docking_reuse_reason"] = "machine-identical retained coordinates"
        else:
            common = SimpleNamespace(receptor_pdb=folder / "receptor.pdb", receptor_pdbqt=folder / "receptor.pdbqt",
                crystal_ligand=folder / "crystal_ligand.pdb", timeout=result["timeout"],
                exhaustiveness=result["exhaustiveness"], num_modes=result["num_modes"])
            selected = [{"input_id": index, "molecule": molecule} for index, molecule in zip(
                result["arms"]["mmff94s"]["selected_input_ids"], read_sdf(folder / "mmff94s/retained.sdf"))]
            started = time.monotonic()
            result["arms"]["mmff94s"]["redocking"] = ab.dock_arm(common, folder / "mmff94s", selected,
                                                                        result["seeds"], result["tools"])
            result["arms"]["mmff94s"]["docking_seconds"] = time.monotonic() - started
        csv_file(folder / "comparison.csv", [dict(arm=name, **row) for name, arm in result["arms"].items()
                                            for row in arm["redocking"]])
        result["status"] = "completed"
    except BaseException as error:
        result.update(status="failed", error=str(error))
        raise
    finally:
        ab.dump(folder / "summary.json", result)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, nargs="+")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--dock", action="store_true")
    parser.add_argument("--wait-for-ready", action="store_true",
                        help="Wait for the already-running preparation; never start a second preparation")
    args = parser.parse_args(argv)
    root = args.out.resolve()
    if args.dock:
        series = load(root / "series.json")
        while args.wait_for_ready and series["status"] == "preparing":
            time.sleep(15)
            series = load(root / "series.json")
        if series["status"] != "ready":
            parser.error("Only a ready series may start; no duplicate or partial-job restart.")
        series["status"] = "running"
        ab.dump(root / "series.json", series)
        for case in series["cases"]:
            if case["status"] != "ready":
                continue
            case["status"] = "running"
            ab.dump(root / "series.json", series)
            try:
                print(f"Redocking {case['name']}", flush=True)
                dock_case(root / case["name"])
                case["status"] = "completed"
            except Exception as error:
                case.update(status="failed", error=str(error))
            ab.dump(root / "series.json", series)
        rows = [dict(case=case["name"], **row) for case in series["cases"] if case["status"] == "completed"
                for row in csv.DictReader((root / case["name"] / "comparison.csv").open())]
        csv_file(root / "comparison.csv", rows)
        series["status"] = "completed" if all(case["status"] == "completed" for case in series["cases"]) else "completed_with_failures"
        ab.dump(root / "series.json", series)
        return 0 if series["status"] == "completed" else 1
    if not args.source or root.exists():
        parser.error("Preparation requires sources and a new output directory.")
    root.mkdir(parents=True)
    series = {"status": "preparing", "method": "MMFF94 versus MMFF94s; both vacuum; unchanged production defaults",
              "baseline_policy": "reuse only after exact independent-pool and minimization reproduction checks",
              "cases": []}
    for source in args.source:
        source = source.resolve()
        name = source.parent.name if source.name == "benchmark" else "indinavir_2r5p"
        if any(case["name"] == name for case in series["cases"]):
            parser.error(f"Duplicate case name: {name}")
        case = {"name": name, "source": str(source), "status": "preparing"}
        series["cases"].append(case)
        ab.dump(root / "series.json", series)
        try:
            print(f"Preparing {name}", flush=True)
            result = prepare_case(source, root / name)
            case.update(status="ready", identical_retained_coordinates=result["identical_retained_coordinates"])
        except Exception as error:
            case.update(status="failed", error=str(error))
        ab.dump(root / "series.json", series)
    series["status"] = "ready" if any(case["status"] == "ready" for case in series["cases"]) else "failed"
    ab.dump(root / "series.json", series)
    return 0 if all(case["status"] == "ready" for case in series["cases"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
