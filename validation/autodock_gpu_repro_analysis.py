#!/usr/bin/env python3
"""Summarize every declared diagnostic, with exact-stage evidence and provenance."""
import argparse
import json
from pathlib import Path
import re
import subprocess

import numpy as np
from autodock_gpu_trial import digest, save
from autodock_gpu_analysis import energy_residuals


def trace_comparison(folder, stem, repeats):
    groups = [folder / f"{stem}_r{n}" for n in range(repeats)]
    result = []
    for path in sorted(groups[0].glob("trace-*.bin")):
        files = [g / path.name for g in groups]
        if not all(p.is_file() for p in files):
            raise ValueError("Missing raw checkpoint: " + path.name)
        hashes = [digest(p) for p in files]
        is_prng = "prng" in path.name
        arrays = [np.fromfile(p, dtype="uint32" if is_prng else "float32") for p in files]
        if not all(np.isfinite(a).all() for a in arrays):
            raise ValueError("Nonfinite checkpoint: " + path.name)
        reference = arrays[0]
        result.append({"checkpoint": path.name, "unique_sha256": len(set(hashes)), "hashes": hashes,
            "elements": len(reference), "changed_elements_vs_first": [int(np.count_nonzero(a != reference)) for a in arrays],
            "max_abs_difference_vs_first": [float(np.max(np.abs(a.astype(float)-reference.astype(float)))) for a in arrays]})
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise ValueError("Fresh analysis output required")
    series = json.loads((a.root / "repro-series.json").read_text())
    if series["status"] != "completed_diagnostic_not_production_acceptance":
        raise ValueError("Matrix is not complete")
    probes = json.loads((a.root / "repro-force-series.json").read_text())
    if probes["status"] != "completed_diagnostic_not_production_acceptance":
        raise ValueError("Force probes are not complete")
    state = {"status": "completed_diagnostic_not_production_acceptance", "arms": {}, "trace_evidence": {},
             "provenance": {}, "production_changed": False, "analysis_sha256": digest(__file__)}
    names = ["repro-official-short", "repro-traced", "repro-translation-barrier", "repro-inter-barrier"]
    names += [r["name"] for r in series["arms"]]
    names += ["repro-force-probe", "repro-force-probe-barrier", "repro-one-workitem-barrier"]
    for name in names:
        folder = a.root / name
        summary = json.loads((folder / "summary.json").read_text())
        if summary["status"] != "completed_diagnostic_not_production_acceptance":
            raise ValueError("Arm incomplete: " + name)
        arm = {"summary": str((folder / "summary.json").resolve()), "sha256": digest(folder / "summary.json"),
               "invocations": len(summary["runs"]), "repeat_comparisons": summary["comparisons"],
               "engine_sha256": summary["engine_sha256"], "runs": []}
        for r in summary["runs"]:
            row = {k: v for k, v in r.items() if k not in ["coordinates", "energies", "crystal_rmsds_angstrom"]}
            dlg = (folder / r["id"] / "result.dlg").read_text()
            row["evaluations_performed_from_dlg"] = int(re.search(r"Number of energy evaluations performed:\s+(\d+)", dlg)[1])
            if summary["phase"] in ("full", "default"):
                row["cpu_gpu_residuals"] = energy_residuals(folder / r["id"])
            arm["runs"].append(row)
        state["arms"][name] = arm
    stem = "indinavir_protease_ad_ls100_runs20_gen1_seed41001"
    for name in ["repro-traced", "repro-translation-barrier", "repro-inter-barrier", "repro-strict",
                 "repro-one-workitem", "repro-force-probe", "repro-force-probe-barrier"]:
        count = 5 if "force-probe" in name else 3
        state["trace_evidence"][name] = trace_comparison(a.root / name, stem, count)
    for source in sorted(a.root.glob("source*")):
        if not source.is_dir():
            continue
        files = [p for sub in ["common", "device", "host", "wrapcl"] for p in (source / sub).rglob("*") if p.is_file()]
        state["provenance"][source.name] = {"files": {str(p.relative_to(source)): digest(p) for p in files},
            "git_head": subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip(),
            "source_diff": subprocess.check_output(["git", "-C", str(source), "diff", "--", "host/src/performdocking.cpp", "device/calcMergedEneGra.cl", "device/kernel_ad.cl"], text=True)}
    candidate_changes = subprocess.check_output(["git", "-C", str(a.root / "source-candidate"), "diff", "--name-only"], text=True).splitlines()
    if set(candidate_changes) != {"device/calcMergedEneGra.cl", "host/inc/stringify.h"}:
        raise ValueError("Candidate has unexpected changes: " + repr(candidate_changes))
    state["candidate_changed_paths"] = candidate_changes
    alias = state["arms"]["repro-official-short"]
    original = json.loads((a.root / "repro-official-short/summary.json").read_text())["runs"]
    lookup = {r["id"]: r for r in original}
    base = lookup["indinavir_protease_ad_ls0_runs20_gen1_seed41001_r0"]
    alias["seed_controls"] = {"explicit_zero_suffix_matches": base["population_sha256"] == lookup["indinavir_protease_ad_ls0_runs20_gen1_seed41001-0-0_r0"]["population_sha256"],
        "different_seed_changes_population": base["population_sha256"] != lookup["indinavir_protease_ad_ls0_runs20_gen1_seed41002_r0"]["population_sha256"]}
    save(a.out, state)
    print(json.dumps({"invocations": sum(r["invocations"] for r in state["arms"].values()),
        "arms": {name: {"invocations": arm["invocations"], "repeat_comparisons": len(arm["repeat_comparisons"]),
            "identical_populations": sum(c["populations_identical"] for c in arm["repeat_comparisons"])} for name, arm in state["arms"].items()}}, indent=2))


if __name__ == "__main__":
    main()
