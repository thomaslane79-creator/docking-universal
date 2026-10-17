#!/usr/bin/env python3
"""Isolated, fail-closed validation of the pinned empirical GNINA Metal fork.

Never prepares molecules, changes production files, resumes, or overwrites runs.
CPU and Metal share the same patched executable and retained PDBQT inputs.
GNINA's search is NOT assumed identical to stock Vina's search.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

from rdkit import Chem
from rdkit.Chem import rdMolAlign
from meeko import PDBQTMolecule, RDKitMolCreate

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n")


def molecule(path):
    if path.suffix == ".sdf":
        mols = list(Chem.SDMolSupplier(str(path), removeHs=False))
        if len(mols) != 1 or mols[0] is None:
            raise ValueError(f"Expected one readable SDF molecule: {path}")
        return Chem.RemoveHs(mols[0])
    text = path.read_text()
    mols = RDKitMolCreate.from_pdbqt_mol(PDBQTMolecule(text, skip_typing=True))
    if len(mols) != 1 or mols[0] is None:
        raise ValueError(f"Expected one Meeko-mapped retained input: {path}")
    return Chem.RemoveHs(mols[0])


def identity(mol):
    return Chem.MolToSmiles(Chem.RemoveHs(mol), isomericSmiles=True)


def guard():
    studies = Path("/Users/crown2/Library/Application Support/Docking Universal/studies")
    for path in studies.glob("*/application_state.json"):
        state = json.loads(path.read_text())
        jobs = state.get("jobs", [])
        if isinstance(jobs, dict):
            jobs = jobs.values()
        for job in jobs:
            if isinstance(job, dict) and job.get("status") in ("queued", "running"):
                raise RuntimeError(f"An application scientific job is active: {path}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--input-format", choices=("pdbqt", "mapped-sdf"), default="pdbqt")
    args = parser.parse_args()
    run = args.run.resolve()
    run.mkdir(exist_ok=False, parents=True)
    args.engine = args.engine.resolve()
    state = {"status": "running", "pid": os.getpid(), "started": time.time(),
             "engine": str(args.engine), "engine_sha256": digest(args.engine),
             "harness_sha256": digest(__file__), "production_changed": False,
             "input_format": args.input_format,
             "records": [], "cases": [], "limitations": [
                 "Experimental patched fork; CNN weights omitted, CNN scoring disabled.",
                 "Same-engine paired test, not algorithm equivalence to stock Vina.",
                 "GNINA has no energy_range option; retain all returned poses, never silently drop them.",
                 "Dry rigid receptors, retained chemical states, no new preparation.",
                 "Only crystal controls have experimental RMSD; current-screen compound does not."]}
    dump(run / "summary.json", state)

    def execute(name, command, timeout=None):
        guard()
        if digest(args.engine) != state["engine_sha256"]:
            raise RuntimeError("Engine changed after validation started")
        record = {"name": name, "command": [str(p) for p in command], "status": "running",
                  "started": time.time(), "stdout": name + ".stdout.log", "stderr": name + ".stderr.log"}
        state["records"].append(record)
        dump(run / "summary.json", state)
        print(name, flush=True)
        start = time.monotonic()
        with (run / record["stdout"]).open("w") as out, (run / record["stderr"]).open("w") as err:
            proc = subprocess.Popen(record["command"], stdout=out, stderr=err,
                                    env=dict(os.environ, GNINA_METAL_TRACE="1"), cwd=run)
            record["pid"] = proc.pid
            dump(run / "summary.json", state)
            try:
                record["returncode"] = proc.wait(timeout=timeout or args.timeout)
            except subprocess.TimeoutExpired:
                proc.terminate()
                try:
                    proc.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                record["status"] = "timeout"
                raise RuntimeError(f"{name}: exceeded {timeout or args.timeout}s validation limit; not a completed timing")
            finally:
                record["elapsed_seconds"] = time.monotonic() - start
                dump(run / "summary.json", state)
        record["status"] = "completed" if proc.returncode == 0 else "failed"
        dump(run / "summary.json", state)
        if proc.returncode:
            tail = (run / record["stderr"]).read_text()[-1800:]
            raise RuntimeError(f"{name}: exit {proc.returncode}: {tail}")
        return record

    def cmd(case, arm, seed, mode):
        command = [args.engine, "--receptor", case["receptor"], "--ligand", case["ligand"],
                   "--cnn_scoring", "none", "--scoring", "vina", "--approximation", "spline",
                   "--factor", "32", "--cpu", "8", "--seed", str(seed),
                   "--pose_sort_order", "Energy", "--num_modes", "15", "--exhaustiveness", "16"]
        for key, value in case["geometry"].items():
            command += ["--" + key, str(value)]
        command += ["--gpu_docking"] if arm == "metal" else ["--no_gpu"]
        if mode != "search":
            command += ["--" + mode]
        return command

    def metrics(case, path):
        mols = list(Chem.SDMolSupplier(str(path), removeHs=True))
        if not mols or any(m is None for m in mols):
            raise ValueError(f"Missing/unreadable poses: {path}")
        reference = molecule(Path(case["ligand"]))
        expected = identity(reference)
        crystal = None
        if case.get("crystal"):
            crystal = next(iter(Chem.SDMolSupplier(case["crystal"], removeHs=True)))
            if crystal is None or identity(crystal) != expected:
                raise ValueError(f"Crystal/input chemistry mismatch: {case['id']}")
        rows = []
        for index, mol in enumerate(mols, 1):
            if identity(mol) != expected:
                raise ValueError(f"Output chemistry/stereochemistry differs: {case['id']}, {path.name}, pose {index}; "
                                 f"{identity(mol)} != {expected}")
            coords = mol.GetConformer().GetPositions()
            if not all(math.isfinite(float(x)) for row in coords for x in row):
                raise ValueError("Non-finite pose coordinates")
            energy = float(mol.GetProp("minimizedAffinity"))
            if not math.isfinite(energy):
                raise ValueError("Non-finite pose energy")
            row = {"pose": index, "energy_kcal_mol": energy}
            if crystal is not None:
                row["crystal_rmsd_angstrom"] = rdMolAlign.CalcRMS(mol, crystal)
            rows.append(row)
        best = min(rows, key=lambda r: r["energy_kcal_mol"])
        result = {"pose_count": len(rows), "lowest_energy_pose": best, "poses": rows,
                  "sha256": digest(path), "chemistry_match": True}
        if crystal is not None:
            result["lowest_energy_recovered_2A"] = best["crystal_rmsd_angstrom"] <= 2
            result["best_of_poses_rmsd_secondary"] = min(r["crystal_rmsd_angstrom"] for r in rows)
        return result

    try:
        # Keep all native numerical failure logs. Only current repaired runs
        # are prerequisites, not the deliberately preserved failed attempts.
        base = args.engine.parents[2]
        state["numerical_gates"] = {}
        for seed in (41001, 41002, 41003):
            log = base / f"numerical-1g-{seed}.log"
            if not log.is_file() or "No errors detected" not in log.read_text():
                raise RuntimeError(f"Native CPU/Metal numerical gate incomplete or failed: {log}")
            state["numerical_gates"][str(seed)] = {"path": str(log), "sha256": digest(log)}
        for label, crystal in (
            ("indinavir_protease", ROOT / "validation/runs/conformer-ab/indinavir_2r5p_redocking_20261004_framechecked/typed_crystal.sdf"),
            ("imatinib_abl", ROOT / "validation/runs/conformer-ab/four_more_20261005_ready/imatinib_1iep/control/typed_crystal.sdf")):
            conf = json.loads((ROOT / f"validation/runs/vina-three-target-threads-20261015/{label}.json").read_text())
            state["cases"].append({"id": label, "receptor": conf["receptor"],
                                    "ligand": conf["compounds"][0]["prepared"][0],
                                    "geometry": conf["geometry"], "crystal": str(crystal)})
        screen = json.loads((ROOT / "validation/runs/vina-execution-20261015_095135/config.json").read_text())
        state["cases"].append({"id": "screen_flexible", "receptor": screen["receptor"],
                                "ligand": screen["compounds"][0]["prepared"][0], "geometry": screen["geometry"]})
        for case in state["cases"]:
            case["input_sha256"] = {key: digest(case[key]) for key in ("receptor", "ligand")}
            if case.get("crystal"):
                case["input_sha256"]["crystal"] = digest(case["crystal"])
            ref = molecule(Path(case["ligand"]))
            case["input_smiles"] = identity(ref)
            case["heavy_atoms"] = ref.GetNumHeavyAtoms()
            if args.input_format == "mapped-sdf":
                original = Path(case["ligand"])
                full = RDKitMolCreate.from_pdbqt_mol(
                    PDBQTMolecule(original.read_text(), skip_typing=True))[0]
                exported = run / (case["id"] + "_mapped_input.sdf")
                writer = Chem.SDWriter(str(exported))
                writer.write(full)
                writer.close()
                reread = next(iter(Chem.SDMolSupplier(str(exported), removeHs=True)))
                deviation = rdMolAlign.CalcRMS(reread, ref)
                if identity(reread) != identity(ref) or deviation > 0.0001:
                    raise ValueError("Mapped export changed chemical identity or retained heavy coordinates")
                case["pdbqt_source"] = str(original)
                case["mapped_export"] = {"path": str(exported), "sha256": digest(exported),
                                         "heavy_atom_no_fit_rmsd_angstrom": deviation,
                                         "method": "Meeko SMILES/atom map reconstruction; no embedding/minimization/state change"}
                case["ligand"] = str(exported)
            # Scoring and local refinement first: do not spend hours timing
            # searches if the exact retained inputs cannot survive conversion.
            case["score_only"] = {}
            for arm in ("cpu", "metal"):
                name = case["id"] + "_score_" + arm
                execute(name, cmd(case, arm, 41001, "score_only"), 120)
                text = (run / (name + ".stdout.log")).read_text()
                found = re.search(r"^Affinity:\s+([-+\d.eE]+)", text, re.M)
                if not found:
                    raise ValueError(f"No fixed-coordinate energy: {name}")
                case["score_only"][arm] = float(found.group(1))
            delta = abs(case["score_only"]["cpu"] - case["score_only"]["metal"])
            case["score_only"]["absolute_difference_kcal_mol"] = delta
            if not math.isfinite(delta) or delta > 0.01:
                raise ValueError(f"Fixed-coordinate energy disagreement exceeds 0.01 kcal/mol: {case['id']}: {delta}")
            case["local"] = {}
            for arm in ("cpu", "metal"):
                name = case["id"] + "_local_" + arm
                output = run / (name + ".sdf")
                execute(name, cmd(case, arm, 41001, "local_only") + ["--out", output], 120)
                case["local"][arm] = metrics(case, output)
            dump(run / "summary.json", state)
        state["preflight_passed"] = True
        dump(run / "summary.json", state)
        # Two matched seeds, then repeat the first seed to check reproducibility.
        # Alternating order avoids always favouring one backend thermally.
        for case in state["cases"]:
            case["search"] = []
            for repeat, seed in enumerate((41001, 41002, 41001)):
                for arm in (("cpu", "metal") if repeat % 2 == 0 else ("metal", "cpu")):
                    name = f"{case['id']}_search_{arm}_{seed}_r{repeat}"
                    output = run / (name + ".sdf")
                    record = execute(name, cmd(case, arm, seed, "search") + ["--out", output])
                    value = dict(arm=arm, seed=seed, repeat=repeat,
                                 elapsed_seconds=record["elapsed_seconds"], **metrics(case, output))
                    trace = (run / record["stderr"]).read_text()
                    value["gpu_trace"] = re.findall(r"METAL_TRACE (\S+) count=(\d+) gpu_seconds=(\S+)", trace)
                    if arm == "metal" and not value["gpu_trace"]:
                        raise ValueError("Metal docking returned without proof of completed GPU dispatches")
                    case["search"].append(value)
                    dump(run / "summary.json", state)
        for case in state["cases"]:
            case["repeatability"] = {}
            for arm in ("cpu", "metal"):
                values = [r for r in case["search"] if r["arm"] == arm and r["seed"] == 41001]
                case["repeatability"][arm] = {"same_complete_sdf_sha256": values[0]["sha256"] == values[1]["sha256"],
                                               "energy_and_crystal_metrics_equal": values[0]["poses"] == values[1]["poses"]}
        state["status"] = "completed_measurements_not_production_approval"
    except BaseException as error:
        state.update(status="failed_validation", error=str(error))
        raise
    finally:
        state["finished"] = time.time()
        dump(run / "summary.json", state)


if __name__ == "__main__":
    main()
