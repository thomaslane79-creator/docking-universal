#!/usr/bin/env python3
"""Local, isolated AD4/OpenCL pilot; never prepares or overwrites study inputs.

AD4 search effort/energies are not interchangeable with Vina's settings/scores.
Retain every LGA run's winner; measure crystal RMSD independently without fitting.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import subprocess
import time
import xml.etree.ElementTree as ET

import numpy as np
from rdkit import Chem
from rdkit.Chem import rdMolAlign
from meeko import PDBQTMolecule, RDKitMolCreate
from meeko.gridbox import get_gpf_string

ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = Path("/Users/crown2/Library/Application Support/Docking Universal/studies")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def check_idle():
    states = list(STATE_ROOT.glob("*/application_state.json"))
    if not states:
        raise RuntimeError("No study states found for active-job guard")
    for path in states:
        state = json.loads(path.read_text())
        jobs = state.get("jobs", [])
        if isinstance(jobs, dict):
            jobs = jobs.values()
        if any(j.get("status") in ("queued", "running") for j in jobs):
            raise RuntimeError(f"Another scientific calculation is active: {path.parent.name}")


def pdbqt_atoms(text):
    atoms = []
    for line in text.splitlines():
        if not line.startswith(("ATOM  ", "HETATM")):
            continue
        atoms.append((line[:30], tuple(float(line[i:i+8]) for i in (30, 38, 46)),
                      float(line[70:76]), line[77:].strip()))
    if not atoms or not all(math.isfinite(v) for _, xyz, q, _ in atoms for v in (*xyz, q)):
        raise ValueError("Empty or non-finite PDBQT atom inventory")
    return atoms


def mapped_molecule(text):
    molecules = RDKitMolCreate.from_pdbqt_mol(PDBQTMolecule(text, skip_typing=True))
    if len(molecules) != 1 or molecules[0] is None:
        raise ValueError("Expected exactly one Meeko-mapped ligand")
    return Chem.RemoveHs(molecules[0])


def pose_from_template(template, output):
    before, after = pdbqt_atoms(template), pdbqt_atoms(output)
    if len(before) != len(after):
        raise ValueError("Output PDBQT atom inventory changed")
    for old, new in zip(before, after):
        if old[0] != new[0] or old[2:] != new[2:]:
            raise ValueError("Output atom identity, charge or AD4 type changed")
    molecule = mapped_molecule(output)
    initial = mapped_molecule(template)
    expected = Chem.MolToSmiles(initial, isomericSmiles=True)
    if Chem.MolToSmiles(molecule, isomericSmiles=True) != expected:
        raise ValueError("Meeko-mapped output chemical identity changed")
    # Atom-map reconstruction retains input stereotags. Independently derive
    # tetrahedral tags from the actual output coordinates to detect inversion.
    geometry = Chem.Mol(molecule)
    Chem.AssignStereochemistryFrom3D(geometry, replaceExistingTags=True)
    Chem.AssignStereochemistry(geometry, cleanIt=True, force=True)
    if Chem.MolToSmiles(geometry, isomericSmiles=True) != expected:
        raise ValueError("Output coordinates do not preserve input stereochemistry")
    return molecule


def grid_description(geometry, receptor_types, ligand_types):
    spacing = 0.375
    center = [geometry["center_" + axis] for axis in "xyz"]
    requested = [geometry["size_" + axis] for axis in "xyz"]
    npts = [2 * math.ceil(size / (2 * spacing)) for size in requested]
    actual = [n * spacing for n in npts]
    text, actual_npts = get_gpf_string(center, actual, "receptor.pdbqt",
                                     receptor_types, ligand_types, map_prefix="receptor")
    if list(actual_npts) != npts:
        raise ValueError("Unexpected map dimension rounding")
    # Meeko's default GPF formatter rounds centers to 3 decimals. Keep the
    # retained six-decimal control frame; only map extents expand to grid cells.
    text = re.sub(r"^gridcenter .*", "gridcenter " + " ".join(f"{x:.6f}" for x in center), text, flags=re.M)
    return text, {"spacing_angstrom": spacing, "center": center, "requested_size": requested,
                  "grid_intervals": npts, "actual_size": actual,
                  "policy": "round intervals up to even count; never shrink approved region"}


def parse_xml(path, expected_runs):
    root = ET.parse(path).getroot()
    if int(root.findtext("run_requested")) != expected_runs:
        raise ValueError("Engine run count differs from requested budget")
    result = {}
    for run in root.findall("./runs/run"):
        number = int(run.attrib["id"])
        value = float(run.findtext("free_NRG_binding"))
        if number in result or not math.isfinite(value):
            raise ValueError("Duplicate run or invalid AD4 energy")
        result[number] = value
    if set(result) != set(range(1, expected_runs + 1)):
        raise ValueError("Missing LGA run outputs")
    return result


def execute(command, folder, name, state, summary, timeout):
    check_idle()
    record = {"command": list(map(str, command)), "cwd": str(folder), "name": name,
              "status": "running", "started_utc": datetime.now(timezone.utc).isoformat()}
    state["processes"].append(record)
    save(summary, state)
    print(name, flush=True)
    start = time.monotonic()
    with (folder / (name + ".stdout.log")).open("w") as out, (folder / (name + ".stderr.log")).open("w") as err:
        child = subprocess.Popen(record["command"], cwd=folder, stdout=out, stderr=err)
        record["pid"] = child.pid
        save(summary, state)
        try:
            while child.poll() is None:
                if time.monotonic() - start > timeout:
                    raise TimeoutError(f"{name}: exceeded {timeout}s pilot limit; not a complete timing")
                check_idle()
                time.sleep(1)
            record["returncode"] = child.returncode
            record["status"] = "completed" if child.returncode == 0 else "failed"
        except BaseException:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            record.update(status="interrupted", returncode=child.returncode)
            raise
        finally:
            record["wall_seconds"] = time.monotonic() - start
            save(summary, state)
    if child.returncode:
        raise RuntimeError(f"{name}: exit {child.returncode}; inspect retained stdout/stderr")
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--autogrid", type=Path, default=Path("/usr/local/bin/autogrid4"))
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    engine, autogrid = args.engine.resolve(), args.autogrid.resolve()
    summary = out / "summary.json"
    state = {"status": "running", "pid": os.getpid(), "processes": [], "cases": [],
             "engine": str(engine), "engine_sha256": digest(engine),
             "autogrid": str(autogrid), "autogrid_sha256": digest(autogrid),
             "harness_sha256": digest(__file__), "production_changed": False,
             "scoring": "AutoDock4; never compare its numerical energies directly to Vina",
             "search": {"nrun": 20, "heuristics": True, "heurmax": 12000000,
                        "autostop": True, "population": 150, "local_search": "ADADELTA",
                        "local_search_max_iterations": 300, "generation_limit": 42000,
                        "clustering_angstrom": 1.5, "poses_retained": "one winner per LGA run, all 20"},
             "limitations": ["One conformer and retained chemical state per case; dry rigid receptors.",
                             "AD4 effort is not Vina exhaustiveness; this is a cross-engine pilot, not a matched implementation speedup.",
                             "Flexible screen ligand has no experimental pose; no crystal recovery claim for it.",
                             "Autostop/rotatable-bond heuristics are explicit; actual evaluations and GPU/CPU energy residuals retained.",
                             "Map generation is separate from per-search time; PLIP/report time excluded."]}
    save(summary, state)
    try:
        config = json.loads((ROOT / "validation/runs/vina-three-target-threads-20261015/indinavir_protease.json").read_text())
        case_root = ROOT / "validation/runs/conformer-ab/indinavir_2r5p_redocking_20261004_framechecked"
        state["cases"].append({"id": "indinavir_protease", "receptor": config["receptor"],
                               "ligand": config["compounds"][0]["prepared"][0], "geometry": config["geometry"],
                               "crystal_sdf": str(case_root / "typed_crystal.sdf"), "seeds": [41001, 41002, 41001]})
        screen = json.loads((ROOT / "validation/runs/vina-execution-20261015_095135/config.json").read_text())
        state["cases"].append({"id": "screen_flexible", "receptor": screen["receptor"],
                               "ligand": screen["compounds"][0]["prepared"][0], "geometry": screen["geometry"],
                               "seeds": [20260808, 20260809, 20260808]})
        for case in state["cases"]:
            folder = out / case["id"]
            folder.mkdir()
            case["hashes"] = {key: digest(case[key]) for key in ("ligand", "receptor")}
            if "crystal_sdf" in case:
                case["hashes"]["crystal_sdf"] = digest(case["crystal_sdf"])
            shutil.copy2(case["receptor"], folder / "receptor.pdbqt")
            ligand = Path(case["ligand"]).read_text()
            original = mapped_molecule(ligand)
            case["chemical_identity"] = Chem.MolToSmiles(original, isomericSmiles=True)
            case["heavy_atoms"] = original.GetNumHeavyAtoms()
            case["ligand_types"] = sorted({a[3] for a in pdbqt_atoms(ligand)})
            receptor_types = sorted({a[3] for a in pdbqt_atoms(Path(case["receptor"]).read_text())})
            if any(t.startswith(("CG", "G")) for t in case["ligand_types"]):
                raise ValueError("Meeko flexible-macrocycle pseudoatoms require explicit AD4 parameter review")
            gpf, case["grid"] = grid_description(case["geometry"], receptor_types, case["ligand_types"])
            (folder / "receptor.gpf").write_text(gpf)
            execute([autogrid, "-p", "receptor.gpf", "-l", "receptor.glg"], folder,
                    "autogrid", state, summary, 300)
            if "Successful Completion" not in (folder / "receptor.glg").read_text():
                raise ValueError("AutoGrid did not confirm successful completion")
            case["map_sha256"] = {p.name: digest(p) for p in folder.glob("receptor.*.map")}
            crystal = None
            if "crystal_sdf" in case:
                crystal = next(iter(Chem.SDMolSupplier(case["crystal_sdf"], removeHs=True)))
                if crystal is None or Chem.MolToSmiles(crystal, isomericSmiles=True) != case["chemical_identity"]:
                    raise ValueError("Crystal/reference chemistry differs")
            case["runs"] = []
            for repeat, seed in enumerate(case["seeds"]):
                check_idle()
                target = folder / f"seed_{seed}_r{repeat}"
                target.mkdir()
                (target / "ligand.pdbqt").write_text(ligand)
                command = [engine, "--ffile", folder / "receptor.maps.fld", "--lfile", "ligand.pdbqt",
                           "--resnam", "result", "--seed", str(seed), "--devnum", "1", "--nrun", "20",
                           "--heuristics", "1", "--heurmax", "12000000", "--autostop", "1",
                           "--psize", "150", "--ngen", "42000", "--lsmet", "ad", "--lsit", "300",
                           "--npdb", "1", "--gbest", "0", "--gfpop", "1", "--rmstol", "1.5",
                           "--output-cluster-poses", "0"]
                record = execute(command, target, "adgpu", state, summary, 900)
                log = (target / "adgpu.stdout.log").read_text()
                if "OpenCL device:" not in log or "Apple M2 Max" not in log or "All jobs ran without errors." not in log:
                    raise ValueError("Expected actual Apple GPU and error-free completion were not confirmed")
                energies = parse_xml(target / "result.xml", 20)
                rows, fingerprints = [], []
                for number, energy in sorted(energies.items()):
                    path = target / f"ligand_docked_run{number}_entity1.pdbqt"
                    mol = pose_from_template(ligand, path.read_text())
                    row = {"run": number, "ad4_binding_energy_kcal_mol": energy,
                           "pdbqt": str(path), "sha256": digest(path)}
                    if crystal is not None:
                        row["crystal_rmsd_angstrom"] = rdMolAlign.CalcRMS(mol, crystal)
                    rows.append(row)
                    fingerprints.append(row["sha256"])
                top = min(rows, key=lambda r: (r["ad4_binding_energy_kcal_mol"], r["run"]))
                item = {"seed": seed, "repeat": repeat, "wall_seconds": record["wall_seconds"],
                        "lowest_energy_pose": top, "poses": rows, "pose_count": len(rows),
                        "pose_hashes_by_run": fingerprints,
                        "engine_reported_job_seconds": float(re.search(r"Job #1 took ([\d.]+) sec", log)[1])}
                if crystal is not None:
                    item["lowest_energy_recovered_2A"] = top["crystal_rmsd_angstrom"] <= 2
                    item["best_of_runs_rmsd_secondary"] = min(r["crystal_rmsd_angstrom"] for r in rows)
                case["runs"].append(item)
                save(summary, state)
            case["median_wall_seconds"] = statistics.median(r["wall_seconds"] for r in case["runs"])
            case["repeat_identical_pose_files"] = case["runs"][0]["pose_hashes_by_run"] == case["runs"][2]["pose_hashes_by_run"]
            for key, value in case["hashes"].items():
                if digest(case[key]) != value:
                    raise ValueError(f"Original retained input changed: {case[key]}")
        state["status"] = "completed_pilot_not_production_acceptance"
    except BaseException as error:
        state.update(status="failed", error=str(error))
        raise
    finally:
        state["finished_utc"] = datetime.now(timezone.utc).isoformat()
        save(summary, state)


if __name__ == "__main__":
    main()
