#!/usr/bin/env python
"""Four additional local A/B controls, sequentially and without LLM loops.

Inputs must already be present locally. No automatic downloads, state changes,
protein repairs, alternate-conformation selection or replacement examples.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from rdkit import Chem
from rdkit.Chem import rdMolDescriptors

import conformer_ab as ab
import redock_prepared_ab as redock


CASES = [
    {"name": "tipranavir_2o4p", "pdb": "2O4P", "component": "TPV", "chains": ["A", "B"],
     "ligand_id": "TPV:A:300", "target": "HIV-1 protease", "ligand": "tipranavir"},
    {"name": "kni577_1mrw", "pdb": "1MRW", "component": "K57", "chains": ["A", "B"],
     "ligand_id": "K57:A:1001", "target": "HIV-1 protease", "ligand": "KNI-577"},
    {"name": "imatinib_1iep", "pdb": "1IEP", "component": "STI", "chains": ["A"],
     "ligand_id": "STI:A:201", "target": "Abl kinase", "ligand": "imatinib"},
    {"name": "geldanamycin_1yet", "pdb": "1YET", "component": "GDM", "chains": ["A"],
     "ligand_id": "GDM:A:275", "target": "HSP90 N-terminal domain", "ligand": "geldanamycin"},
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--xtb", required=True)
    parser.add_argument("--vina", required=True)
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    tools = {"xtb": ab.executable(args.xtb), "vina": ab.executable(args.vina)}
    root.mkdir(parents=True, exist_ok=True)
    summary_path = root / "series.json"
    prior = None
    if summary_path.exists() and not args.preflight_only:
        prior = json.loads(summary_path.read_text())
        if prior["status"] != "preflight_complete":
            parser.error("Existing series cannot be overwritten or started twice.")
    elif summary_path.exists():
        parser.error("Existing preflight cannot be overwritten.")
    summary = {"status": "preflighting", "tools": tools, "cases": [],
               "attempts": 16, "keep": 3, "prune_rmsd_angstrom": 0.75,
               "embedding_seed": 20260808, "dock_seeds": [41001, 41002, 41003],
               "exhaustiveness": 8, "cpu_per_job": 1,
               "chemical_state_policy": "one exact neutral CCD state; no protonation enumeration",
               "limitations": "Dry rigid receptors; two methods change both energy model and solvent; two controls share a target; not a general benchmark or size-based recommendation."}
    ab.dump(summary_path, summary)
    cached = ab.ROOT / "smoke_runs/mmcif_2r8n_run_file/preparation/2R8N_receptor_prep/cavity/pdb_site_evidence"
    prior_cases = prior["cases"] if prior else None
    if prior_cases:
        summary["cases"] = prior_cases
        if [item["name"] for item in prior_cases] != [item["name"] for item in CASES]:
            raise ValueError("Preflight examples differ from the declared series.")
        for item in prior_cases:
            if ab.digest(Path(item["input_sdf"])) != item["input_sha256"]:
                raise ValueError("Input chemistry changed after preflight.")
            for name, expected in item["control_sha256"].items():
                if ab.digest(root / item["name"] / "control" / name) != expected:
                    raise ValueError(f"Shared control changed after preflight: {item['name']}/{name}")
    else:
        for case in CASES:
            item = dict(case, status="preflighting")
            summary["cases"].append(item)
            ab.dump(summary_path, summary)
            folder = root / case["name"]
            control = folder / "control"
            control.mkdir(parents=True)
            pdb = root / "inputs" / f"{case['pdb']}.pdb"
            sdf = root / "inputs" / f"{case['component']}_ideal.sdf"
            if not pdb.is_file():
                pdb = cached / "structural_ensemble/source_structures" / f"{case['pdb']}.pdb"
            if not sdf.is_file():
                sdf = cached / "ccd" / f"{case['component']}_ideal.sdf"
            try:
                template = Chem.SDMolSupplier(str(sdf), removeHs=False)[0]
                if template is None:
                    raise ValueError("Unreadable authoritative CCD chemistry.")
                heavy = Chem.RemoveHs(template)
                if Chem.GetFormalCharge(heavy) != 0:
                    raise ValueError("This declared neutral-state series requires explicit review of a charged input.")
                item.update(input_sdf=str(sdf), input_sha256=ab.digest(sdf),
                            heavy_atoms=heavy.GetNumHeavyAtoms(),
                            rotatable_bonds=rdMolDescriptors.CalcNumRotatableBonds(heavy),
                            largest_ring=max((len(ring) for ring in heavy.GetRingInfo().AtomRings()), default=0))
                config = SimpleNamespace(complex=pdb, chains=case["chains"], ligand_id=case["ligand_id"], timeout=600)
                print(f"Preflight {case['name']}: exact chemistry, assembly chains and coordinate frame", flush=True)
                item["control"] = redock.prepare_control(config, control, template)
                item["control_sha256"] = {name: ab.digest(control / name) for name in
                                          ("receptor.pdb", "receptor.pdbqt", "crystal_ligand.pdb", "box.conf")}
                item["status"] = "ready"
            except Exception as error:
                item.update(status="preflight_failed", error=str(error))
                print(f"Preflight failed for {case['name']}: {error}", flush=True)
            ab.dump(summary_path, summary)
    if any(item["status"] != "ready" for item in summary["cases"]):
        summary["status"] = "preflight_failed"
        ab.dump(summary_path, summary)
        return 1
    summary["status"] = "preflight_complete"
    ab.dump(summary_path, summary)
    if args.preflight_only:
        return 0
    summary["status"] = "running"
    ab.dump(summary_path, summary)
    for item in summary["cases"]:
        folder = root / item["name"]
        control = folder / "control"
        benchmark = folder / "benchmark"
        item["status"] = "running"
        summary["current_case"] = item["name"]
        ab.dump(summary_path, summary)
        start = time.monotonic()
        try:
            command = [sys.executable, str(ab.ROOT / "validation/conformer_ab.py"),
                       "--ligand", item["input_sdf"], "--out", str(benchmark), "--xtb", tools["xtb"],
                       "--attempts", "16", "--keep", "3", "--rmsd", "0.75", "--seed", "20260808",
                       "--receptor-pdbqt", str(control / "receptor.pdbqt"),
                       "--receptor-pdb", str(control / "receptor.pdb"),
                       "--crystal-ligand", str(control / "crystal_ligand.pdb"),
                       "--box", str(control / "box.conf"), "--vina", tools["vina"],
                       "--dock-seeds", "41001", "41002", "41003", "--exhaustiveness", "8"]
            print(f"Running {item['name']}", flush=True)
            # A whole control can take much longer than an individual dock;
            # the child still enforces its 600-second per-command timeout.
            ab.run(command, folder, "benchmark", 6 * 60 * 60)
            completed = json.loads((benchmark / "summary.json").read_text())
            if completed["status"] != "completed":
                raise ValueError("Benchmark did not report completion.")
            _, geometry = redock.conformations(benchmark, benchmark)
            item.update(status="completed", elapsed_seconds=time.monotonic()-start,
                        summary_path=str(benchmark / "summary.json"), geometry_comparison=geometry)
        except Exception as error:
            item.update(status="failed", error=str(error), elapsed_seconds=time.monotonic()-start)
            # Keep independent controls running, but report every failure.
            print(f"Failed {item['name']}: {error}", flush=True)
        ab.dump(summary_path, summary)
    rows = []
    for item in summary["cases"]:
        if item["status"] != "completed":
            continue
        report = json.loads(Path(item["summary_path"]).read_text())
        for arm, details in report["arms"].items():
            for metric in details["redocking"]:
                rows.append(dict(example=item["name"], ligand=item["ligand"], arm=arm, **metric))
    if rows:
        with (root / "docking_comparison.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    summary["status"] = "completed" if all(item["status"] == "completed" for item in summary["cases"]) else "completed_with_failures"
    ab.dump(summary_path, summary)
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
