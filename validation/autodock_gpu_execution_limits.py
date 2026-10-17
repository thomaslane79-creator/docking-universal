#!/usr/bin/env python3
"""Declared isolated execution-size controls; expected failures are retained."""
import argparse
import json
from pathlib import Path
import shutil

import numpy as np
from autodock_gpu_trial import check_idle, digest, execute, parse_xml, save
from autodock_gpu_repro import fingerprint


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    a = parser.parse_args()
    root = Path(__file__).resolve().parent / "runs/autodock-gpu-mac-20261016"
    pilot = json.loads((root / "pilot/summary.json").read_text())
    case = pilot["cases"][0]
    a.out.mkdir(parents=True, exist_ok=False)
    summary = a.out / "summary.json"
    state = {"status": "running", "engine_sha256": digest(a.engine), "harness_sha256": digest(__file__),
             "runs": [], "processes": [], "production_changed": False}
    save(summary, state)
    try:
        specs = [(0, 20, 5, n) for n in range(2)] + [(200, 20, g, n) for g in [5, 20] for n in range(3)]
        specs += [(0, 1, 20, n) for n in range(2)]
        for chunk, nrun, ngen, rep in specs:
            check_idle()
            folder = a.out / f"chunk{chunk}_runs{nrun}_gen{ngen}_r{rep}"
            folder.mkdir()
            shutil.copy2(case["ligand"], folder / "ligand.pdbqt")
            cmd = ["/usr/bin/env", f"ADGPU_AUDIT_CHUNK={chunk or 3000}", a.engine.resolve(),
                   "--ffile", root / "pilot/indinavir_protease/receptor.maps.fld", "--lfile", "ligand.pdbqt",
                   "--resnam", "result", "--seed", "41001", "--devnum", "1", "--nrun", str(nrun),
                   "--heuristics", "0", "--nev", "5210753", "--autostop", "0", "--psize", "150",
                   "--ngen", str(ngen), "--lsmet", "ad", "--lsrat", "100", "--lsit", "300",
                   "--npdb", "1", "--gbest", "0", "--gfpop", "1", "--rmstol", "1.5", "--output-cluster-poses", "0"]
            row = {"id": folder.name, "chunk_work_items": chunk or 3000, "nrun": nrun, "ngen": ngen, "repeat": rep}
            try:
                process = execute(cmd, folder, "adgpu", state, summary, 900)
                row["wall_seconds"] = process["wall_seconds"]
                row["energies"] = parse_xml(folder / "result.xml", nrun)
                row.update(fingerprint(folder, nrun))
                row.pop("coordinates")
                invalid = []
                for path in folder.glob("trace-*-population.bin"):
                    x = np.fromfile(path, dtype="float32")
                    if not np.isfinite(x).all() or not np.any(x):
                        invalid.append(path.name)
                row.update(status="invalid_output" if invalid else "completed", invalid_checkpoints=invalid)
            except RuntimeError as error:
                row.update(status="execution_failure", error=str(error))
            log = folder / "execution-audit.jsonl"
            if log.exists():
                events = [json.loads(line) for line in log.read_text().splitlines()]
                row["events"] = events
                row["max_kernel_seconds"] = max(e["seconds"] for e in events)
            state["runs"].append(row)
            save(summary, state)
        if digest(a.engine) != state["engine_sha256"]:
            raise ValueError("Executable changed")
        state["status"] = "completed_diagnostic_with_explicit_outcomes"
    except BaseException as error:
        state.update(status="failed", error=str(error))
        raise
    finally:
        save(summary, state)


if __name__ == "__main__":
    main()
