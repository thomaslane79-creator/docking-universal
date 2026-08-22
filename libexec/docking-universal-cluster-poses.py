#!/usr/bin/env python
"""Cluster poses across seeds/conformers and select energy-ranked representatives.

Scientific method
-----------------
Poses are compared by symmetry-aware heavy-atom RMSD without coordinate fitting,
because every pose already shares the receptor coordinate frame. Chemical states
are clustered separately. RDKit Butina clustering uses a configurable RMSD cutoff
(2.0 A by default). The representative is the lowest-energy member of a cluster;
the default selected outputs are the three lowest-energy distinct clusters.

This is consensus organization, not validation. Cluster population and seed
support are reported but do not prove a pose is correct.
"""

import argparse
import csv
import json
import re
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path


def parse_scores(path):
    scores = {}
    model = 0
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("MODEL"):
            fields = line.split()
            model = int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else model + 1
        elif line.startswith("REMARK VINA RESULT:"):
            scores[model or 1] = float(line.split()[3])
        elif line.startswith("REMARK minimizedAffinity"):
            scores[model or 1] = float(line.split()[2])
    return scores


def seed_from_path(path):
    for parent in path.parents:
        match = re.fullmatch(r"seed_(-?\d+)", parent.name)
        if match:
            return int(match.group(1))
    return None


def write_complex(receptor, ligand_pdb, output):
    receptor_lines = [
        line for line in receptor.read_text(errors="replace").splitlines()
        if line.startswith(("ATOM  ", "HETATM", "TER"))
    ]
    max_serial = max(
        (int(line[6:11]) for line in receptor_lines if line.startswith(("ATOM  ", "HETATM")) and line[6:11].strip().isdigit()),
        default=0,
    )
    ligand_source = ligand_pdb.read_text(errors="replace").splitlines()
    serial_map = {}
    for line in ligand_source:
        if line.startswith(("ATOM  ", "HETATM")) and line[6:11].strip().isdigit():
            serial_map[int(line[6:11])] = max_serial + len(serial_map) + 1
    ligand_lines = []
    for line in ligand_source:
        if line.startswith(("ATOM  ", "HETATM")):
            old = int(line[6:11])
            ligand_lines.append("HETATM" + f"{serial_map[old]:5d}" + line[11:])
        elif line.startswith("CONECT"):
            values = [int(line[index:index + 5]) for index in range(6, len(line), 5) if line[index:index + 5].strip().isdigit()]
            mapped = [serial_map[value] for value in values if value in serial_map]
            if len(mapped) >= 2:
                ligand_lines.append("CONECT" + "".join(f"{value:5d}" for value in mapped))
    output.write_text("\n".join(receptor_lines + ligand_lines + ["END"]) + "\n")


def safe_name(value):
    return str(value).replace("-", "m").replace(".", "p").replace("+", "p")


def set_ligand_pdb_info(molecule, resname="UNL", chain="Z", residue_number=1):
    """Give representative atoms unique conventional PDB residue metadata."""
    from rdkit import Chem

    counters = defaultdict(int)
    for atom in molecule.GetAtoms():
        symbol = atom.GetSymbol().upper()
        counters[symbol] += 1
        info = Chem.AtomPDBResidueInfo()
        info.SetName(f"{symbol}{counters[symbol]}"[:4].rjust(4))
        info.SetResidueName(resname[:3].rjust(3))
        info.SetResidueNumber(residue_number)
        info.SetChainId(chain[:1])
        info.SetIsHeteroAtom(True)
        atom.SetMonomerInfo(info)


def write_browser(output, receptor, selected, cutoff):
    """Write one PyMOL scene per selected cluster representative."""
    shutil.copy2(receptor, output / "receptor.pdb")
    lines = [
        "# Energy-ranked representatives of distinct cross-run pose clusters",
        f"# Each scene shows one representative and receptor residues within {cutoff:g} A.",
        "reinitialize",
        f"cd {output}",
        "load receptor.pdb, receptor",
        "hide everything, all",
        "remove (receptor and polymer.protein and hydro and neighbor elem C)",
        "show cartoon, receptor and polymer.protein",
        "color slate, receptor and polymer.protein",
        "set cartoon_transparency, 0.72, receptor",
        "bg_color white",
        "set label_color, black",
        "set label_outline_color, white",
    ]
    objects = []
    sites = []
    labels = []
    for rank, cluster in enumerate(selected, start=1):
        pose = cluster["representative"]
        obj = f"cluster_{cluster['cluster_id']:03d}_E_{safe_name(pose['energy'])}"
        site = f"site_{cluster['cluster_id']:03d}_within_{safe_name(cutoff)}A"
        label = f"cluster_{cluster['cluster_id']:03d}_information"
        objects.append(obj)
        sites.append(site)
        labels.append(label)
        display = (
            f"Rank {rank} | Cluster {cluster['cluster_id']} | Energy {pose['energy']:.3f} kcal/mol | "
            f"Seeds {cluster['seed_support']} | Poses {cluster['pose_count']}"
        )
        lines.extend([
            f"load cluster_{cluster['cluster_id']:03d}/representative.sdf, {obj}",
            f"create {site}, byres (receptor within {cutoff:.3f} of {obj})",
            f"hide everything, {site}",
            f"show sticks, {site}",
            f"color skyblue, {site} and elem C",
            f"util.cnc {site}",
            f"hide sticks, ({site} and hydro and neighbor elem C)",
            f"label {site} and name CA, \"%s%s/%s\" % (resn,resi,chain)",
            f"show sticks, {obj}",
            f"color gray70, {obj} and elem C",
            f"util.cnc {obj}",
            f"pseudoatom {label}, selection={obj}, label=\"{display}\"",
            f"hide nonbonded, {label}",
            f"show labels, {label}",
            f"set label_size, 16, {label}",
        ])
    switchable = objects + sites + labels
    lines.append(f"group representative_browser, {' '.join(switchable)}")
    lines.extend(f"disable {name}" for name in switchable)
    for index, cluster in enumerate(selected):
        lines.extend([
            f"enable {objects[index]}", f"enable {sites[index]}", f"enable {labels[index]}",
            f"zoom {objects[index]} or {sites[index]}, 7", f"orient {objects[index]}",
            f"scene cluster_{cluster['cluster_id']:03d}, store",
            f"disable {objects[index]}", f"disable {sites[index]}", f"disable {labels[index]}",
        ])
    if selected:
        lines.extend([
            f"scene cluster_{selected[0]['cluster_id']:03d}, recall",
            "python", "from pymol import cmd",
            "cmd.set_key('RIGHT', lambda: cmd.scene('', 'next'))",
            "cmd.set_key('LEFT', lambda: cmd.scene('', 'previous'))", "python end",
        ])
    pml = output / "representative_browser.pml"
    pml.write_text("\n".join(lines) + "\n")
    return pml


def write_representative_pml(cluster_dir, cluster, cutoff):
    """Write a standalone scene for one cluster representative."""
    pose = cluster["representative"]
    lines = [
        "# One energy-ranked cross-run cluster representative",
        "reinitialize",
        f"cd {cluster_dir}",
        "load ../receptor.pdb, receptor",
        "load representative.sdf, representative",
        f"create site, byres (receptor within {cutoff:.3f} of representative)",
        "hide everything, all", "remove (receptor and polymer.protein and hydro and neighbor elem C)", "show cartoon, receptor and polymer.protein",
        "color slate, receptor", "set cartoon_transparency, 0.72, receptor",
        "show sticks, site", "color skyblue, site and elem C", "util.cnc site",
        "hide sticks, (site and hydro and neighbor elem C)",
        "label site and name CA, \"%s%s/%s\" % (resn,resi,chain)",
        "show sticks, representative", "color gray70, representative and elem C",
        "util.cnc representative", "set stick_radius, 0.18",
        "bg_color white", "set label_color, black", "set label_outline_color, white",
        f"pseudoatom information, selection=representative, label=\"Cluster {cluster['cluster_id']} | Energy {pose['energy']:.3f} kcal/mol | Seeds {cluster['seed_support']} | Poses {cluster['pose_count']}\"",
        "hide nonbonded, information", "show labels, information", "set label_size, 16, information",
        "zoom representative or site, 7", "orient representative",
    ]
    pml = cluster_dir / "representative.pml"
    pml.write_text("\n".join(lines) + "\n")
    return pml


def load_from_comparisons(root):
    """Load already typed pose SDFs and energies from redocking comparison folders."""
    from rdkit import Chem

    records = []
    for table in sorted(root.rglob("pose_comparison.csv")):
        comparison = table.parent
        seed = seed_from_path(table)
        conformer = comparison.name.removesuffix("_comparison")
        with table.open(newline="") as handle:
            for row in csv.DictReader(handle):
                model = int(row["model"])
                pose_path = comparison / f"pose_{model:03d}.sdf"
                molecule = next((m for m in Chem.SDMolSupplier(str(pose_path), removeHs=True) if m), None)
                if molecule is None or not row.get("affinity_kcal_per_mol"):
                    continue
                records.append({
                    "molecule": molecule, "pose_path": pose_path, "source": table,
                    "seed": seed, "conformer": conformer, "model": model,
                    "energy": float(row["affinity_kcal_per_mol"]),
                })
    return records


def load_from_docking(root, ligand_work, exporter, engine, export_root):
    """Export raw PDBQT results with Meeko and recover typed pose molecules."""
    from rdkit import Chem

    records = []
    for pdbqt in sorted(root.rglob(f"*_{engine}.pdbqt")):
        if "ligand_preparation" in pdbqt.parts:
            continue
        ligand_id = pdbqt.name.removesuffix(f"_{engine}.pdbqt")
        source_sdf = ligand_work / f"{ligand_id}_opt.sdf"
        if not source_sdf.is_file():
            raise SystemExit(f"No typed source SDF for {pdbqt.name}: {source_sdf}")
        destination = export_root / f"{seed_from_path(pdbqt)}_{ligand_id}.sdf"
        result = subprocess.run([str(exporter), str(pdbqt), "-s", str(destination)], capture_output=True, text=True)
        if result.returncode or not destination.is_file():
            raise SystemExit(f"Meeko export failed for {pdbqt}: {result.stderr or result.stdout}")
        scores = parse_scores(pdbqt)
        source = next((m for m in Chem.SDMolSupplier(str(source_sdf), removeHs=False) if m), None)
        state = source.GetIntProp("DockingUniversal_State") if source and source.HasProp("DockingUniversal_State") else 1
        for model, molecule in enumerate(Chem.SDMolSupplier(str(destination), removeHs=True), start=1):
            if molecule is None or model not in scores:
                continue
            records.append({
                "molecule": molecule, "pose_path": destination, "source": pdbqt,
                "seed": seed_from_path(pdbqt), "conformer": ligand_id, "model": model,
                "energy": scores[model], "state": state,
            })
    return records


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Scientific interpretation:
  A cluster represents poses with similar ligand geometry and placement in the
  fixed receptor frame. Fewer clusters indicate greater convergence, but neither
  cluster size nor docking energy proves that a binding mode is correct.

Typical cutoff choices:
  1.0 A  strict; separates modest pose differences
  1.5 A  moderately strict
  2.0 A  default binding-mode grouping
  2.5-3.0 A broad; may merge meaningfully different poses

Representatives are the lowest-energy members of distinct clusters. Seed and
conformer support are reported separately as measures of search repeatability.
""",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--comparison-root", type=Path, help="existing redocking comparison tree containing typed pose SDFs")
    source.add_argument("--docking-root", type=Path, help="raw cross-seed docking tree to export and cluster")
    parser.add_argument("--ligand-work", type=Path, help="typed per-conformer SDF directory; required with --docking-root")
    parser.add_argument("--engine", choices=("vina",), default="vina", help="score syntax and output suffix to parse (Vina)")
    parser.add_argument("--receptor", required=True, type=Path, help="fixed receptor-frame PDB used for nearby residues and scenes")
    parser.add_argument("--out", required=True, type=Path, help="cluster tables, all-pose SDF, representatives, and PyMOL scripts")
    parser.add_argument("--cluster-rmsd", type=float, default=2.0, help="symmetry-aware no-fit heavy-atom RMSD cutoff in A (default: 2.0)")
    parser.add_argument("--representatives", type=int, default=3, help="number of lowest-energy distinct clusters selected (default: 3)")
    parser.add_argument("--contact-cutoff", type=float, default=5.0, help="receptor neighborhood shown around representatives in A (default: 5.0)")
    parser.add_argument("--mk-export", default="mk_export.py", help="Meeko PDBQT-to-SDF pose exporter")
    args = parser.parse_args()
    if args.cluster_rmsd <= 0 or args.representatives < 1:
        parser.error("cluster RMSD and representative count must be positive")
    if not args.receptor.expanduser().is_file():
        parser.error("receptor PDB not found")
    if args.docking_root and not args.ligand_work:
        parser.error("--ligand-work is required with --docking-root")

    from rdkit import Chem
    from rdkit.Chem import rdMolAlign
    from rdkit.ML.Cluster import Butina

    output = args.out.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="docking-universal-cluster-") as tmp:
        if args.comparison_root:
            records = load_from_comparisons(args.comparison_root.expanduser().resolve())
        else:
            exporter = shutil.which(args.mk_export) if Path(args.mk_export).name == args.mk_export else args.mk_export
            if not exporter or not Path(exporter).is_file():
                parser.error(f"Meeko exporter not found: {args.mk_export}")
            records = load_from_docking(
                args.docking_root.expanduser().resolve(), args.ligand_work.expanduser().resolve(),
                Path(exporter), args.engine, Path(tmp),
            )
    if not records:
        raise SystemExit("No scored poses were found")

    # Separate incompatible chemical states before RMSD clustering.
    groups = defaultdict(list)
    for index, record in enumerate(records):
        molecule = record["molecule"]
        smiles = Chem.MolToSmiles(Chem.RemoveHs(molecule), isomericSmiles=True)
        state = record.get("state", smiles)
        groups[(state, smiles)].append(index)

    clusters = []
    next_cluster_id = 1
    for (state, smiles), indices in groups.items():
        distances = []
        for local_i in range(1, len(indices)):
            for local_j in range(local_i):
                first = records[indices[local_i]]["molecule"]
                second = records[indices[local_j]]["molecule"]
                distances.append(rdMolAlign.CalcRMS(first, second, maxMatches=100000))
        local_clusters = Butina.ClusterData(distances, len(indices), args.cluster_rmsd, isDistData=True)
        for members in local_clusters:
            member_indices = [indices[index] for index in members]
            representative_index = min(member_indices, key=lambda index: records[index]["energy"])
            energies = sorted(records[index]["energy"] for index in member_indices)
            seeds = sorted({records[index]["seed"] for index in member_indices if records[index]["seed"] is not None})
            conformers = sorted({records[index]["conformer"] for index in member_indices})
            clusters.append({
                "cluster_id": next_cluster_id, "state": state, "smiles": smiles,
                "pose_count": len(member_indices), "seed_support": len(seeds), "seeds": seeds,
                "conformer_support": len(conformers), "conformers": conformers,
                "best_energy": energies[0], "median_energy": energies[len(energies) // 2],
                "representative_index": representative_index,
                "representative": records[representative_index], "member_indices": member_indices,
            })
            next_cluster_id += 1
    clusters.sort(key=lambda cluster: (cluster["best_energy"], -cluster["seed_support"], -cluster["pose_count"]))
    selected = clusters[: args.representatives]

    inventory_fields = ["pose_id", "cluster_id", "selected_cluster", "seed", "conformer", "model", "energy_kcal_per_mol", "source"]
    with (output / "pose_inventory.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=inventory_fields)
        writer.writeheader()
        cluster_for_pose = {index: cluster for cluster in clusters for index in cluster["member_indices"]}
        selected_ids = {cluster["cluster_id"] for cluster in selected}
        for index, record in enumerate(records, start=1):
            cluster = cluster_for_pose[index - 1]
            writer.writerow({
                "pose_id": index, "cluster_id": cluster["cluster_id"],
                "selected_cluster": "yes" if cluster["cluster_id"] in selected_ids else "no",
                "seed": record["seed"], "conformer": record["conformer"], "model": record["model"],
                "energy_kcal_per_mol": record["energy"], "source": record["source"],
            })

    summary_fields = ["energy_rank", "cluster_id", "chemical_state", "best_energy_kcal_per_mol", "median_energy_kcal_per_mol", "pose_count", "seed_support", "conformer_support", "selected"]
    with (output / "cluster_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=summary_fields)
        writer.writeheader()
        selected_ids = {cluster["cluster_id"] for cluster in selected}
        for rank, cluster in enumerate(clusters, start=1):
            writer.writerow({
                "energy_rank": rank, "cluster_id": cluster["cluster_id"], "chemical_state": cluster["state"],
                "best_energy_kcal_per_mol": cluster["best_energy"], "median_energy_kcal_per_mol": cluster["median_energy"],
                "pose_count": cluster["pose_count"], "seed_support": cluster["seed_support"],
                "conformer_support": cluster["conformer_support"],
                "selected": "yes" if cluster["cluster_id"] in selected_ids else "no",
            })

    all_writer = Chem.SDWriter(str(output / "all_poses.sdf"))
    for index, record in enumerate(records, start=1):
        molecule = Chem.Mol(record["molecule"])
        molecule.SetProp("_Name", f"pose_{index:04d}")
        molecule.SetIntProp("DockingUniversal_Seed", record["seed"] or 0)
        molecule.SetDoubleProp("DockingUniversal_Energy", record["energy"])
        all_writer.write(molecule)
    all_writer.close()

    for cluster in selected:
        cluster_dir = output / f"cluster_{cluster['cluster_id']:03d}"
        cluster_dir.mkdir(exist_ok=True)
        molecule = Chem.Mol(cluster["representative"]["molecule"])
        molecule.SetProp("_Name", f"cluster_{cluster['cluster_id']:03d}_representative")
        writer = Chem.SDWriter(str(cluster_dir / "representative.sdf"))
        writer.write(molecule)
        writer.close()
        set_ligand_pdb_info(molecule)
        Chem.MolToPDBFile(molecule, str(cluster_dir / "representative.pdb"))
        write_complex(args.receptor.expanduser().resolve(), cluster_dir / "representative.pdb", cluster_dir / "complex.pdb")
        write_representative_pml(cluster_dir, cluster, args.contact_cutoff)
        metadata = {key: value for key, value in cluster.items() if key not in {"representative", "member_indices"}}
        metadata["representative"] = {
            key: str(value) if isinstance(value, Path) else value
            for key, value in cluster["representative"].items() if key != "molecule"
        }
        (cluster_dir / "cluster.json").write_text(json.dumps(metadata, indent=2) + "\n")

    browser = write_browser(output, args.receptor.expanduser().resolve(), selected, args.contact_cutoff)
    report = {
        "method": "RDKit symmetry-aware heavy-atom CalcRMS without fitting; Butina clustering",
        "cluster_rmsd_angstrom": args.cluster_rmsd,
        "pose_count": len(records), "chemical_state_count": len(groups),
        "cluster_count": len(clusters), "selected_representative_count": len(selected),
        "selected_cluster_ids": [cluster["cluster_id"] for cluster in selected],
        "representative_browser": str(browser),
    }
    (output / "clustering_manifest.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Clustered {len(records)} poses into {len(clusters)} distinct clusters at {args.cluster_rmsd:.2f} A")
    for rank, cluster in enumerate(selected, start=1):
        print(
            f"  {rank}) cluster {cluster['cluster_id']}: {cluster['best_energy']:.3f} kcal/mol; "
            f"{cluster['pose_count']} poses; {cluster['seed_support']} seeds"
        )
    print(f"Cluster summary: {output / 'cluster_summary.csv'}")
    print(f"Representative browser: {browser}")


if __name__ == "__main__":
    main()
