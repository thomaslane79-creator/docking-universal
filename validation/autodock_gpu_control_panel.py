#!/usr/bin/env python3
"""Sequential, isolated crystal-control assessment of the patched AD4 GPU build.

No production engine changes, input preparation, Vina reruns or automatic retries.
Keep upstream XML's exact ranking order: its printed two-decimal energies can tie.
"""
import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import statistics
import xml.etree.ElementTree as ET

from rdkit import Chem
from rdkit.Chem import Descriptors, rdMolAlign

from autodock_gpu_repro import fingerprint
from autodock_gpu_trial import (
    ROOT, check_idle, digest, execute, grid_description, mapped_molecule,
    parse_xml, pdbqt_atoms, pose_from_template, save,
)
from redock_prepared_ab import verify_coordinate_frame

RUN_ROOT = ROOT / "validation/runs/autodock-gpu-mac-20261016"
SEEDS = [41001, 41002, 41003, 41001]
ARMS = ["heuristic_autostop", "fixed_12m_no_autostop"]
ALLOWED_TYPES = {"A", "C", "HD", "N", "NA", "OA", "S", "SA", "F", "Cl", "Br", "I", "P"}


def canonical(mol):
    return Chem.MolToSmiles(Chem.RemoveHs(mol), isomericSmiles=True)


def validate_types(types):
    unsupported = sorted(set(types) - ALLOWED_TYPES)
    if unsupported:
        raise ValueError("Unsupported AD4 ligand types in this assessment: " + ", ".join(unsupported))


def xml_ranking(path, nrun):
    energies = parse_xml(path, nrun)
    rows = []
    for run in ET.parse(path).getroot().findall("./runs/run"):
        row = {"run": int(run.attrib["id"]), "binding_energy_kcal_mol": energies[int(run.attrib["id"])],
               "intermolecular_kcal_mol": float(run.findtext("final_intermol_NRG")),
               "internal_kcal_mol": float(run.findtext("internal_ligand_NRG")),
               "torsional_kcal_mol": float(run.findtext("torsonial_free_NRG"))}
        if not all(math.isfinite(v) for v in row.values()):
            raise ValueError("Non-finite XML energy components")
        # Dry, freely roaming ligand: upstream unbound_same_as_bound cancels
        # intramolecular energy from estimated binding energy, not from search.
        if abs(row["binding_energy_kcal_mol"] - row["intermolecular_kcal_mol"] - row["torsional_kcal_mol"]) > .0151:
            raise ValueError("Unexpected upstream binding-energy formula")
        rows.append(row)
    if any(a["binding_energy_kcal_mol"] > b["binding_energy_kcal_mol"] + .0001
           for a, b in zip(rows, rows[1:])):
        raise ValueError("Unexpected upstream XML ranking")
    return rows


def winner_search_energies(folder, nrun):
    result = {}
    for number in range(1, nrun + 1):
        table = (folder / f"final_population_run{number}.txt").read_text()
        entries = [line for line in table.splitlines() if re.match(r"^\s*1\s*\|", line)]
        if len(entries) != 1:
            raise ValueError("Missing/duplicate population winner")
        cpu, gpu, difference = map(float, entries[0].split("|")[-3].split("/"))
        if not all(math.isfinite(v) for v in (cpu, gpu, difference)):
            raise ValueError("Invalid population winner energy")
        result[number] = {"cpu_total_report_kcal_mol": cpu, "gpu_total_search_kcal_mol": gpu,
                          "gpu_minus_cpu_total_kcal_mol": difference}
    return result


def command(engine, maps, arm, seed):
    cmd = [str(engine), "--ffile", str(maps), "--lfile", "ligand.pdbqt", "--resnam", "result",
           "--seed", str(seed), "--devnum", "1", "--nrun", "20", "--psize", "150", "--ngen", "42000",
           "--lsmet", "ad", "--lsrat", "100", "--lsit", "300", "--npdb", "1", "--gbest", "0",
           "--gfpop", "1", "--rmstol", "1.5", "--output-cluster-poses", "0"]
    if arm == "heuristic_autostop":
        return cmd + ["--heuristics", "1", "--heurmax", "12000000", "--autostop", "1"]
    if arm == "fixed_12m_no_autostop":
        return cmd + ["--heuristics", "0", "--nev", "12000000", "--autostop", "0"]
    raise ValueError("Undeclared search arm")


def load_cases():
    base = ROOT / "validation/runs/conformer-ab"
    specs = [("indinavir_protease", base / "indinavir_2r5p_redocking_20261004_framechecked", None)]
    more = base / "four_more_20261005_ready"
    for name in ["tipranavir_2o4p", "kni577_1mrw", "imatinib_1iep", "geldanamycin_1yet"]:
        specs.append((name, more / name / "benchmark", more / name / "control"))
    result = []
    for name, prior, control in specs:
        summary = prior / "summary.json"
        if json.loads(summary.read_text())["status"] != "completed":
            raise ValueError("Retained source did not complete: " + name)
        cmdfile = prior / "vacuum_pruned/dock_conf_01/seed_41001/vina.command.json"
        cmd = json.loads(cmdfile.read_text())
        opts = dict(zip(cmd[1::2], cmd[2::2]))
        ligand, receptor, box = map(Path, [opts["--ligand"], opts["--receptor"], opts["--config"]])
        crystal = (control or prior) / "typed_crystal.sdf"
        text = ligand.read_text()
        mol = mapped_molecule(text)
        geom = {}
        for line in box.read_text().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                if k.strip().startswith(("center_", "size_")):
                    geom[k.strip()] = float(v.split("#")[0])
        if set(geom) != {f"{p}_{a}" for p in ("center", "size") for a in "xyz"}:
            raise ValueError("Incomplete box geometry")
        case = {"id": name, "prior": str(prior), "ligand": str(ligand), "receptor": str(receptor),
                "crystal_sdf": str(crystal), "geometry": geom,
                "heavy_atoms": mol.GetNumHeavyAtoms(), "rdkit_rotatable_bonds": Descriptors.NumRotatableBonds(mol),
                "molecular_weight": Descriptors.MolWt(mol), "chemical_identity": canonical(mol),
                "ligand_types": sorted({a[3] for a in pdbqt_atoms(text)}), "runs": [], "arms": {},
                "status": "pending", "input_hashes": {str(p): digest(p) for p in [summary, cmdfile, ligand, receptor, box, crystal]}}
        try:
            validate_types(case["ligand_types"])
        except ValueError as error:
            # Pseudoatom-containing Meeko molecules are outside this mapping
            # audit too; do not misreport their unsupported graph as a failed
            # ordinary-ligand stereochemistry check.
            case.update(status="unsupported_not_launched", reason=str(error))
            result.append(case)
            continue
        reference = next(iter(Chem.SDMolSupplier(str(crystal), removeHs=True)))
        if reference is None or canonical(reference) != canonical(mol):
            raise ValueError("Crystal/input chemistry differs: " + name)
        geom_reference = Chem.Mol(reference)
        Chem.AssignStereochemistryFrom3D(geom_reference, replaceExistingTags=True)
        Chem.AssignStereochemistry(geom_reference, cleanIt=True, force=True)
        if canonical(geom_reference) != canonical(mol):
            raise ValueError("Crystal coordinate stereochemistry differs: " + name)
        # Recheck the already prepared receptor against its retained pre-prep frame.
        receptor_pdb = receptor.with_suffix(".pdb")
        raw = receptor.parent / "receptor_raw.pdb"
        frame_source = raw if raw.exists() else receptor_pdb
        case["coordinate_frame"] = verify_coordinate_frame(frame_source, receptor)
        case["input_hashes"][str(frame_source)] = digest(frame_source)
        case["input_geometry_chemistry_checks_passed"] = True
        result.append(case)
    return result


def historical_vina(case):
    prior = Path(case["prior"])
    rows = []
    for seed in SEEDS[:3]:
        folder = prior / f"vacuum_pruned/dock_conf_01/seed_{seed}"
        cmd = json.loads((folder / "vina.command.json").read_text())
        opts = dict(zip(cmd[1::2], cmd[2::2]))
        output = Path(opts["--out"])
        text = output.read_text()
        energies = [float(e) for e in re.findall(r"REMARK VINA RESULT:\s+([-\d.]+)", text)]
        mol = mapped_molecule(text)
        if mol.GetNumConformers() != len(energies) or not energies:
            raise ValueError("Historical Vina pose/energy inventory mismatch")
        ref = next(iter(Chem.SDMolSupplier(case["crystal_sdf"], removeHs=True)))
        rmsds = [rdMolAlign.CalcRMS(mol, ref, prbId=i) for i in range(len(energies))]
        winner = min(range(len(energies)), key=energies.__getitem__)
        rows.append({"seed": seed, "binding_energy_kcal_mol": energies[winner],
                     "lowest_energy_crystal_rmsd_angstrom": rmsds[winner],
                     "best_of_poses_rmsd_secondary": min(rmsds), "pose_count": len(energies),
                     "output": str(output), "sha256": digest(output),
                     "cpu": opts.get("--cpu"), "exhaustiveness": opts.get("--exhaustiveness"),
                     "num_modes": opts.get("--num_modes"), "command_file": str(folder / "vina.command.json")})
    return {"rows": rows, "meaning": "Retained single-conformer Vina crystal controls; different scoring/search/settings, not equivalent-work speedups or interchangeable energy scales. No new Vina jobs."}


def assess_run(case, target, process, seed, repeat, arm):
    log = (target / "adgpu.stdout.log").read_text()
    if not gpu_log_valid(log):
        raise ValueError("Expected Apple GPU execution/completion not confirmed")
    ranking = xml_ranking(target / "result.xml", 20)
    search = winner_search_energies(target, 20)
    fp = fingerprint(target, 20)
    crystal = next(iter(Chem.SDMolSupplier(case["crystal_sdf"], removeHs=True)))
    text = Path(case["ligand"]).read_text()
    for row in ranking:
        path = target / f"ligand_docked_run{row['run']}_entity1.pdbqt"
        mol = pose_from_template(text, path.read_text())
        row.update(crystal_rmsd_angstrom=rdMolAlign.CalcRMS(mol, crystal), pdbqt=str(path), sha256=digest(path),
                   **search[row["run"]])
    # Upstream orders full-precision inter energies; don't re-sort rounded ties
    # by run ID (or by crystal RMSD) and accidentally choose a different winner.
    primary = ranking[0]
    dlg = (target / "result.dlg").read_text()
    # Paths differ across repeats; use actual pose hashes, ordered energies and
    # complete printed populations for scientific reproducibility instead.
    score_fingerprint = hashlib.sha256(json.dumps([{k: v for k, v in row.items() if k not in ("pdbqt", "sha256")}
                                                  for row in ranking], sort_keys=True).encode()).hexdigest()
    return {"seed": seed, "repeat": repeat, "arm": arm, "directory": str(target), "poses": ranking,
            "primary": primary, "lowest_energy_recovered_2A": primary["crystal_rmsd_angstrom"] <= 2.,
            "best_of_runs_rmsd_secondary": min(r["crystal_rmsd_angstrom"] for r in ranking),
            "chemistry_checks_passed": True, "pose_count": len(ranking),
            "pose_sha256": fp["pose_sha256"], "population_sha256": fp["population_sha256"],
            "scores_sha256": score_fingerprint, "population_rows": fp["population_rows"],
            "wall_seconds": process["wall_seconds"],
            "engine_job_seconds": float(re.search(r"Job #1 took ([\d.]+) sec", log)[1]),
            "evaluations_per_run_reported": int(re.search(r"Number of energy evaluations performed:\s+(\d+)", dlg)[1]),
            "generations_reported": int(re.search(r"Number of generations used:\s+(\d+)", dlg)[1])}


def gpu_log_valid(log):
    return bool(re.search(r"(?m)^OpenCL device:\s+Apple M2 Max\s*$", log)) and "All jobs ran without errors." in log


def completed_parser_failure(source, cases, engine):
    """Narrow recovery of a successful native run rejected only by our log parser.

    Never restart a failed scientific job. Preserve the original failed record,
    original map files and outputs; verify identity and all contents before reuse.
    """
    path = source.resolve() / "summary.json"
    old = json.loads(path.read_text())
    if old.get("status") != "failed" or old.get("error") != "Expected Apple GPU execution/completion not confirmed":
        raise ValueError("Only the recorded device-log parser failure can be reused")
    if old["engine_sha256"] != digest(engine) or old["search_arms"] != ARMS or old["seeds_with_repeat"] != SEEDS:
        raise ValueError("Reuse engine/search provenance differs")
    if len(old["processes"]) != 2 or any(r.get("status") != "completed" or r.get("returncode") != 0 for r in old["processes"]):
        raise ValueError("Reuse requires completed successful map and GPU processes")
    before, current = old["cases"][0], cases[0]
    if before["id"] != current["id"] or before["input_hashes"] != current["input_hashes"] or before["runs"]:
        raise ValueError("Reuse input/assessment provenance differs")
    for file, expected in {**before["input_hashes"], **before["map_hashes"]}.items():
        if digest(file) != expected:
            raise ValueError("Reuse source input/map changed")
    process = old["processes"][1]
    expected_cmd = command(engine, source.resolve() / current["id"] / "receptor.maps.fld", ARMS[0], SEEDS[0])
    if process["command"] != expected_cmd:
        raise ValueError("Reuse native command differs")
    target = Path(process["cwd"])
    row = assess_run(current, target, process, SEEDS[0], 0, ARMS[0])
    provenance = {"original_failed_summary": str(path), "summary_sha256": digest(path),
                  "reason": "Native job completed successfully; validator rejected whitespace in device log. Revalidated without redocking.",
                  "file_hashes": {str(p): digest(p) for p in target.iterdir() if p.is_file()}}
    row["reused_completed_calculation"] = provenance
    return before, row


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--preflight-only", action="store_true")
    p.add_argument("--reuse-completed-parser-failure", type=Path)
    args = p.parse_args()
    engine = RUN_ROOT / "source-gpu-candidate-guarded/bin/adgpu_guarded_128"
    autogrid = Path("/usr/local/bin/autogrid4")
    out = args.out.resolve()
    if out.exists():
        raise ValueError("Assessment output exists: no duplicate/restart")
    check_idle()
    cases = load_cases()
    reuse = completed_parser_failure(args.reuse_completed_parser_failure, cases, engine) if args.reuse_completed_parser_failure else None
    if args.preflight_only:
        print(json.dumps(cases, indent=2))
        return
    # One coordinator across this validation panel, in addition to GUI guard.
    with (RUN_ROOT / "control-panel.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        out.mkdir(parents=True, exist_ok=False)
        path = out / "summary.json"
        state = {"status": "running", "pid": os.getpid(), "started_utc": datetime.now(timezone.utc).isoformat(),
                 "production_changed": False, "engine": str(engine), "engine_sha256": digest(engine),
                 "autogrid_sha256": digest(autogrid), "harness_sha256": digest(__file__),
                 "processes": [], "cases": cases, "seeds_with_repeat": SEEDS, "search_arms": ARMS,
                 "search": {"nrun": 20, "population": 150, "local_search": "ADADELTA", "lsrate": 100,
                            "local_search_max_iterations": 300, "generation_limit": 42000, "evaluation_cap": 12000000},
                 "energy_meaning": "Primary: upstream XML-order estimated AD4 binding energy (CPU intermolecular + constant torsional term, unbound_same_as_bound). GPU total search and CPU total diagnostic energies retained separately; not Vina-equivalent energies.",
                 "acceptance_policy": {"technical": "Every retained pose must preserve graph/atom inventory/charge/types/3D stereochemistry; same-seed repeats must match poses, complete printed populations and scores. Preserve hashes/frame, native GPU execution and explicit unsupported-input outcomes. Stop on correctness failure; no silent retry.",
                                       "pose_recovery": "Report lowest-binding-energy deposited-frame heavy-atom RMSD and <=2 A recovery for each of three independent seeds. Best-of-run RMSD secondary. No automatic general engine acceptance; review coverage and failures first."},
                 "limitations": ["Four controls, three HIV protease ligands and one Abl kinase; not broad target/ligand-size coverage.",
                                 "One retained neutral chemical state and starting conformer, dry rigid receptor; no protonation ensemble or affinity validation.",
                                 "Geldanamycin macrocycle pseudoatoms are unsupported here; rejected without preparation or search.",
                                 "Engine/AutoGrid setup timings included separately; original chemistry preparation and reports/PLIP excluded.",
                                 "AD4 LGA budgets and scoring differ from Vina; no equality requirement or equivalent-work speedup claim.",
                                 "12M is the engine average-evaluation stopping target across LGA runs, with a generation cap, not a hard cap for every individual run."]}
        save(path, state)
        try:
            for case in cases:
                if case["status"] == "unsupported_not_launched":
                    continue
                folder = out / case["id"]
                folder.mkdir()
                case["status"] = "running"
                case["historical_vina"] = historical_vina(case)
                maps_folder = folder
                if reuse and case["id"] == reuse[0]["id"]:
                    before, row = reuse
                    maps_folder = args.reuse_completed_parser_failure.resolve() / case["id"]
                    case.update(grid=before["grid"], map_wall_seconds=before["map_wall_seconds"],
                                map_hashes=before["map_hashes"], map_reused_from=str(maps_folder))
                    case["runs"].append(row)
                else:
                    shutil.copy2(case["receptor"], folder / "receptor.pdbqt")
                    receptor_types = sorted({a[3] for a in pdbqt_atoms(Path(case["receptor"]).read_text())})
                    gpf, case["grid"] = grid_description(case["geometry"], receptor_types, case["ligand_types"])
                    # Only new AD4 maps are generated; receptor/ligand preparation is reused.
                    (folder / "receptor.gpf").write_text(gpf)
                    map_process = execute([autogrid, "-p", "receptor.gpf", "-l", "receptor.glg"], folder, "autogrid", state, path, 300)
                    if "Successful Completion" not in (folder / "receptor.glg").read_text():
                        raise ValueError("AutoGrid did not confirm successful completion")
                    maps = sorted(folder.glob("receptor.*.map"))
                    if len(maps) != len(case["ligand_types"]) + 2 or not (folder / "receptor.maps.fld").exists():
                        raise ValueError("Incomplete map inventory")
                    case["map_wall_seconds"] = map_process["wall_seconds"]
                    case["map_hashes"] = {str(p): digest(p) for p in maps + [folder / "receptor.maps.fld"]}
                save(path, state)
                for arm in ARMS:
                    for repeat, seed in enumerate(SEEDS):
                        if any(r["arm"] == arm and r["repeat"] == repeat for r in case["runs"]):
                            continue
                        target = folder / f"{arm}_seed{seed}_r{repeat}"
                        target.mkdir()
                        shutil.copy2(case["ligand"], target / "ligand.pdbqt")
                        process = execute(command(engine, maps_folder / "receptor.maps.fld", arm, seed), target,
                                          "adgpu", state, path, 1800)
                        row = assess_run(case, target, process, seed, repeat, arm)
                        previous = [r for r in case["runs"] if r["arm"] == arm and r["seed"] == seed]
                        if previous:
                            row["repeat_matches"] = {k: row[k] == previous[0][k]
                                                     for k in ("pose_sha256", "population_sha256", "scores_sha256")}
                            if not all(row["repeat_matches"].values()):
                                case["runs"].append(row)
                                raise ValueError("Same-seed repeat failed: " + case["id"] + " " + arm)
                        case["runs"].append(row)
                        save(path, state)
                    unique = [r for r in case["runs"] if r["arm"] == arm and r["repeat"] < 3]
                    case["arms"][arm] = {"independent_seeds": 3,
                        "primary_recovery_within_2A": sum(r["lowest_energy_recovered_2A"] for r in unique),
                        "lowest_energy_rmsds_angstrom": [r["primary"]["crystal_rmsd_angstrom"] for r in unique],
                        "median_wall_seconds": statistics.median(r["wall_seconds"] for r in unique),
                        "map_plus_three_searches_wall_seconds": case["map_wall_seconds"] + sum(r["wall_seconds"] for r in unique),
                        "first_seed_repeat_passed": True}
                    save(path, state)
                for file, expected in {**case["input_hashes"], **case["map_hashes"]}.items():
                    if digest(file) != expected:
                        raise ValueError("Retained input/map changed: " + file)
                case.update(status="completed", inputs_and_maps_unchanged=True)
                save(path, state)
            if digest(engine) != state["engine_sha256"]:
                raise ValueError("GPU executable changed during assessment")
            state.update(status="completed_assessment_pending_review", production_integration_approved=False,
                         search_invocations=sum(len(c["runs"]) for c in cases),
                         poses_checked=sum(r["pose_count"] for c in cases for r in c["runs"]))
        except BaseException as error:
            state.update(status="failed", error=str(error))
            raise
        finally:
            state["finished_utc"] = datetime.now(timezone.utc).isoformat()
            save(path, state)


if __name__ == "__main__":
    main()
