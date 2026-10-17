#!/usr/bin/env python3
"""Independent matched-coordinate intramolecular references, no docking."""
import argparse
import json
from pathlib import Path

import numpy as np
from autodock_gpu_trial import digest, save


def intramolecular(coords, meta, mode, cutoff_distances=None):
    """Dry rigid ligand, ordinary AD4 pairs: no flexres/reactive/ring glue."""
    pairs = np.array(meta["pairs"], dtype=int).reshape(-1, 2)
    if cutoff_distances is not None:
        cutoff_distances = np.asarray(cutoff_distances, dtype=float)
        if cutoff_distances.shape != (len(coords), len(pairs)) or not np.isfinite(cutoff_distances).all() or np.any(cutoff_distances < 0):
            raise ValueError("Native cutoff-distance inventory must match every entity/pair and be finite/nonnegative")
    a, b = pairs.T
    types = np.array(meta["atom_types"], dtype=int)
    idx = types[a] * meta["types"] + types[b]
    ac, bd, opt = [np.array(meta[k])[idx] for k in ["AC", "BD", "opt_distance"]]
    exponent = np.array(meta["exponents"], dtype=int)[idx]
    m, n = exponent >> 8, exponent & 255
    charge = np.array(meta["charges"])
    solpar, volume = [np.array(meta[k])[types] for k in ["solpar", "volume"]]
    desolv_coefficient = ((solpar[a] + meta["qasp"] * np.abs(charge[a])) * volume[b] +
                         (solpar[b] + meta["qasp"] * np.abs(charge[b])) * volume[a])
    rows = []
    # Bounded batches keep memory small, retaining every entity.
    for start in range(0, len(coords), 100):
        xyz = coords[start:start+100] * meta["spacing"]
        distance = np.linalg.norm(xyz[:, a] - xyz[:, b], axis=2)
        cutoff = (distance if cutoff_distances is None else cutoff_distances[start:start+len(xyz)])
        smooth = np.where(np.abs(opt-distance) >= meta["smooth"]/2,
                          distance + np.copysign(meta["smooth"]/2, opt-distance), opt)
        electro = np.maximum(distance, meta["elec_min"])
        if mode == "table":
            # Engine narrows distances to float before selecting table entries.
            sm = np.maximum(0, np.floor(np.float32(100)*np.float32(smooth)+np.float32(.5)).astype(int)-1)
            el = np.maximum(0, np.floor(np.float32(100)*np.float32(electro)+np.float32(.5)).astype(int)-1)
            sm = np.minimum(sm, 2047)
            el = np.minimum(el, 2047)
            table = {6: np.array(meta["r6"]), 10: np.array(meta["r10"]), 12: np.array(meta["r12"])}
            if not set(m).issubset(table) or not set(n).issubset(table):
                raise ValueError("Unsupported modified pair exponent")
            vdw = np.zeros_like(smooth)
            for power in [6, 10, 12]:
                vdw += np.where(m==power, ac, 0) * table[power][sm]
                vdw -= np.where(n==power, bd, 0) * table[power][sm]
            coulomb = charge[a]*charge[b]*np.array(meta["eps"])[el]
            desolv = desolv_coefficient*np.array(meta["desolv"])[el]
        else:
            vdw = (ac - bd*smooth**(m-n)) * smooth**(-m)
            if mode == "gpu_continuous":
                dielectric_inverse = 1.10859/(electro+1.26366)**2 + .010358
                d2 = electro*electro
                desolv = desolv_coefficient*meta["coeff_desolv"]*(12.96-.1063*d2*(1-.001947*d2))/(12.96+d2*(.4137+d2*(.00357+.000112*d2)))
            elif mode == "exact_continuous":
                dielectric_inverse = 1/(-8.5525 + 86.9525/(1+7.7839*np.exp(-86.9525*.003627*electro)))
                desolv = desolv_coefficient*meta["coeff_desolv"]*np.exp(-electro**2/25.92)
            else:
                raise ValueError(mode)
            coulomb = meta["coeff_elec"]*charge[a]*charge[b]*dielectric_inverse/electro
        vdw = np.where(cutoff < 8, vdw, 0).sum(axis=1)
        electro_cutoff = 20.48 if cutoff_distances is None else float(np.float32(20.48))
        coulomb = np.where(cutoff < electro_cutoff, coulomb, 0).sum(axis=1)
        desolv = np.where(cutoff < electro_cutoff, desolv, 0).sum(axis=1)
        rows.extend(np.stack([vdw, coulomb, desolv], axis=1))
    return np.array(rows)


def stats(x, mask):
    v = np.abs(x[mask])
    return {"n": len(v), "max": float(np.max(v)), "p95": float(np.percentile(v, 95)),
            "median": float(np.median(v))} if len(v) else {"n": 0}


def analyze(folder, cutoff_distances=None):
    meta = json.loads((folder / "audit-metadata.json").read_text())
    shape = (meta["entities"], meta["atoms"])
    gpu = np.fromfile(folder / "audit-gpu-coordinates.bin", dtype="float32").reshape(*shape, 4)[:, :, :3].astype(float)
    cpu = np.fromfile(folder / "audit-cpu-coordinates.bin", dtype="float64").reshape(*shape, 3)
    original = np.fromfile(folder / "audit-search-energy.bin", dtype="float32").astype(float)
    rescore = np.fromfile(folder / "audit-reevaluated-energy.bin", dtype="float32").astype(float)
    rows = [json.loads(line) for line in (folder / "audit-cpu.jsonl").read_text().splitlines()]
    if len(rows) != meta["entities"] or [r["entity"] for r in rows] != list(range(meta["entities"])):
        raise ValueError("CPU/GPU inventory mismatch")
    cpu_inter, cpu_intra, same_inter, same_intra = [np.array([r[k] for r in rows]) for k in ["cpucoords_inter", "cpucoords_intra", "gpucoords_inter", "gpucoords_intra"]]
    gpu_model = intramolecular(gpu, meta, "gpu_continuous", cutoff_distances=cutoff_distances).sum(axis=1)
    exact = intramolecular(gpu, meta, "exact_continuous").sum(axis=1)
    table = intramolecular(gpu, meta, "table").sum(axis=1)
    for array in [gpu, cpu, original, rescore, cpu_inter, cpu_intra, same_inter, same_intra, gpu_model, exact, table]:
        if not np.isfinite(array).all():
            raise ValueError("Nonfinite reference data")
    masks = {"all": np.ones(len(rows),dtype=bool),
             "both_absolute_energies_le_1000": (np.abs(original)<=1000)&(np.abs(cpu_inter+cpu_intra)<=1000)}
    winners = np.zeros(len(rows),dtype=bool)
    for run in range(meta["runs"]):
        lo = run*meta["population"]
        winners[lo+np.argmin(original[lo:lo+meta["population"]])] = True
    masks["run_winners"] = winners
    differences = {"reported_cpu_minus_search_gpu": cpu_inter+cpu_intra-original,
        "same_gpucoords_cpu_table_minus_gpu": same_inter+same_intra-rescore,
        "cpu_table_intra_minus_independent_table": same_intra-table,
        "independent_gpu_formula_minus_gpu": same_inter+gpu_model-rescore,
        "search_minus_energy_only_kernel": original-rescore,
        "coordinate_transform_effect_cpu_total": cpu_inter+cpu_intra-same_inter-same_intra,
        "distance_table_effect_intra": table-exact,
        "gpu_approximation_effect_intra": exact-gpu_model}
    result = {"metadata": meta, "hashes": {p.name: digest(p) for p in folder.glob("audit-*")},
        "coordinate_max_difference_angstrom": float(np.max(np.abs(cpu-gpu))*meta["spacing"]),
        "comparisons": {k: {name: stats(v, mask) for name, mask in masks.items()} for k, v in differences.items()}}
    predicted=same_inter+gpu_model
    scale=np.maximum(1,np.maximum(np.abs(predicted),np.abs(rescore)))
    result["matched_model_scaled_error"]={name:stats((predicted-rescore)/scale,mask) for name,mask in masks.items()}
    largest=int(np.argmax(np.abs(predicted-rescore)))
    result["largest_absolute_matched_model_residual"]={"entity":largest,"gpu_energy":float(rescore[largest]),
        "reference_energy":float(predicted[largest]),"absolute_difference":float(abs(predicted[largest]-rescore[largest])),
        "scaled_difference":float(abs(predicted[largest]-rescore[largest])/scale[largest]),
        "float32_spacing_at_gpu_energy":float(abs(np.spacing(np.float32(rescore[largest]))))}
    bounded = np.flatnonzero(masks["both_absolute_energies_le_1000"])
    worst = sorted(bounded,key=lambda n: abs(differences["reported_cpu_minus_search_gpu"][n]),reverse=True)[:10]
    result["worst_bounded_entities"] = [{"entity": int(i), "search_energy": float(original[i]), "cpu_energy": float(cpu_inter[i]+cpu_intra[i]),
        "decomposition": {k: float(v[i]) for k, v in differences.items()}} for i in worst]
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    a = p.parse_args()
    if a.out.exists():
        raise ValueError("Fresh analysis output required")
    summary = json.loads((a.run / "summary.json").read_text())
    if summary["status"] != "completed_diagnostic_not_production_acceptance":
        raise ValueError("Audit search not complete")
    result = {"status": "completed_matched_coordinate_analysis", "source_summary_sha256": digest(a.run / "summary.json"),
              "harness_sha256": digest(__file__), "cases": {}}
    for r in summary["runs"]:
        result["cases"][r["case"]] = analyze(a.run / r["id"])
    save(a.out, result)
    print(json.dumps({k: v["comparisons"] for k,v in result["cases"].items()},indent=2))


if __name__ == "__main__":
    main()
