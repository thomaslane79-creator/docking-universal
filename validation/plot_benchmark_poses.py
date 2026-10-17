#!/usr/bin/env python
"""Plot every returned benchmark pose, without cluster or score filtering."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--poses", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--title", required=True)
    args = parser.parse_args()
    with args.poses.open() as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("No retained pose data.")
    for row in rows:
        row["rmsd"] = float(row["crystal_rmsd_angstrom"])
        row["energy"] = float(row["affinity_kcal_per_mol"])
        if not math.isfinite(row["rmsd"]) or row["rmsd"] < 0 or not math.isfinite(row["energy"]):
            raise ValueError("Unevaluable record; do not silently omit or fabricate a plotted value.")
    top = min(rows, key=lambda row: row["energy"])
    closest = min(rows, key=lambda row: row["rmsd"])
    fig, ax = plt.subplots(figsize=(10, 6.5))
    ax.scatter([row["rmsd"] for row in rows], [row["energy"] for row in rows],
               s=38, color="#8996a3", alpha=.7, linewidths=0, label=f"All returned poses ({len(rows)})")
    ax.scatter(top["rmsd"], top["energy"], s=150, marker="D", color="#ce332f", edgecolors="black",
               linewidths=.8, zorder=4, label="Lowest energy")
    ax.scatter(closest["rmsd"], closest["energy"], s=240, marker="*", color="#2468b4", edgecolors="black",
               linewidths=.8, zorder=5, label="Closest experimental pose")
    ax.set_title(args.title, fontsize=17, pad=16)
    ax.set_xlabel("Experimental-pose heavy-atom RMSD (Å; no fitting)", fontsize=13, labelpad=10)
    ax.set_ylabel("Vina binding energy (kcal/mol)", fontsize=13, labelpad=10)
    rmsds, energies = [row["rmsd"] for row in rows], [row["energy"] for row in rows]
    xpad = max(.15, max(rmsds) * .04)
    ypad = max(.15, (max(energies) - min(energies)) * .07)
    ax.set_xlim(0, max(rmsds) + xpad)
    ax.set_ylim(min(energies) - ypad, max(energies) + ypad)
    ax.grid(alpha=.18)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=12)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="upper left", bbox_to_anchor=(0, -.18), ncol=3, frameon=False, fontsize=11)
    fig.subplots_adjust(left=.12, right=.97, top=.89, bottom=.25)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(args.out, dpi=180)
    plt.close(fig)
    audit = {"source": str(args.poses.resolve()), "source_sha256": hashlib.sha256(args.poses.read_bytes()).hexdigest(),
             "source_count": len(rows), "plotted_count": len(rows), "excluded": [],
             "score_cutoff": None, "rmsd_cutoff": None, "cluster_limit": None,
             "seeds": sorted({row["seed"] for row in rows}), "lowest_energy_pose": top,
             "closest_experimental_pose": closest}
    args.out.with_suffix(".json").write_text(json.dumps(audit, indent=2) + "\n")
    print(json.dumps({"count": len(rows), "lowest_energy": top, "closest": closest}, indent=2))


if __name__ == "__main__":
    main()
