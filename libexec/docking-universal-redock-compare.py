#!/usr/bin/env python
"""Compare docked poses with a crystallographic ligand without realigning them.

Symmetry-aware heavy-atom RMSD is measured in the receptor coordinate frame;
the docked ligand is never fitted onto the reference before measurement.
"""

import argparse
import csv
import json
import shutil
import subprocess
from pathlib import Path


def first_sdf_molecule(path, remove_hs=False):
    from rdkit import Chem

    return next((mol for mol in Chem.SDMolSupplier(str(path), removeHs=remove_hs) if mol), None)


def parse_scores(path):
    scores = {}
    model = 0
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("MODEL"):
            fields = line.split()
            model = int(fields[1]) if len(fields) > 1 and fields[1].isdigit() else model + 1
        elif line.startswith("REMARK VINA RESULT:"):
            fields = line.split()
            if len(fields) >= 4:
                scores[model or 1] = float(fields[3])
        elif line.startswith("REMARK minimizedAffinity"):
            fields = line.split()
            if len(fields) >= 3:
                scores[model or 1] = float(fields[2])
    return scores


def set_ligand_pdb_info(molecule, resname="UNL", chain="Z", residue_number=1):
    from rdkit import Chem

    counters = {}
    for atom in molecule.GetAtoms():
        symbol = atom.GetSymbol().upper()
        counters[symbol] = counters.get(symbol, 0) + 1
        info = Chem.AtomPDBResidueInfo()
        info.SetName(f"{symbol}{counters[symbol]}"[:4].rjust(4))
        info.SetResidueName(resname[:3].rjust(3))
        info.SetResidueNumber(residue_number)
        info.SetChainId(chain[:1])
        info.SetIsHeteroAtom(True)
        atom.SetMonomerInfo(info)


def write_complex(receptor_path, ligand_path, output_path):
    receptor_lines = []
    for line in receptor_path.read_text(errors="replace").splitlines():
        if line.startswith(("ATOM  ", "HETATM", "TER")):
            receptor_lines.append(line)

    max_serial = max(
        (int(line[6:11]) for line in receptor_lines if line.startswith(("ATOM  ", "HETATM")) and line[6:11].strip().isdigit()),
        default=0,
    )
    ligand_source = ligand_path.read_text(errors="replace").splitlines()
    serial_map = {}
    for line in ligand_path.read_text(errors="replace").splitlines():
        if line.startswith(("ATOM  ", "HETATM")):
            old_serial = int(line[6:11])
            serial_map[old_serial] = max_serial + len(serial_map) + 1

    ligand_lines = []
    for line in ligand_source:
        if line.startswith(("ATOM  ", "HETATM")):
            old_serial = int(line[6:11])
            rewritten = "HETATM" + f"{serial_map[old_serial]:5d}" + line[11:]
            ligand_lines.append(rewritten)
        elif line.startswith("CONECT"):
            numbers = [int(line[i:i + 5]) for i in range(6, len(line), 5) if line[i:i + 5].strip().isdigit()]
            mapped = [serial_map[number] for number in numbers if number in serial_map]
            if len(mapped) >= 2:
                ligand_lines.append("CONECT" + "".join(f"{number:5d}" for number in mapped))

    output_path.write_text("\n".join(receptor_lines + ligand_lines + ["END"]) + "\n")


def write_overlay_pml(output_dir, rmsd):
    pml_path = output_dir / "crystal_vs_top_pose.pml"
    lines = [
        "# Crystallographic ligand versus top-scoring redocked pose",
        "# Green carbon: crystal pose; gray carbon: docked pose",
        f"# Symmetry-aware in-place heavy-atom RMSD: {rmsd:.3f} A",
        "reinitialize",
        f"cd {output_dir}",
        "load receptor.pdb, receptor",
        "load crystal_ligand.sdf, crystal_ligand",
        "load top_score_pose.sdf, docked_ligand",
        "hide everything, all",
        "select nearby_residues, byres (receptor within 5 of (crystal_ligand or docked_ligand))",
        "show sticks, nearby_residues",
        "color gray60, nearby_residues",
        "show sticks, crystal_ligand",
        "color green, crystal_ligand and elem C",
        "util.cnc crystal_ligand",
        "show sticks, docked_ligand",
        "color gray70, docked_ligand and elem C",
        "util.cnc docked_ligand",
        "set stick_radius, 0.18",
        "bg_color white",
        "zoom crystal_ligand or docked_ligand, 8",
        "orient crystal_ligand or docked_ligand",
    ]
    pml_path.write_text("\n".join(lines) + "\n")
    return pml_path


def safe_value(value):
    """Make a compact score/RMSD value safe for use in a PyMOL object name."""
    return str(value).replace("-", "m").replace(".", "p").replace("+", "p")


def write_all_poses_pml(output_dir, rows, top_index, best_rmsd_index):
    pml_path = output_dir / "crystal_vs_all_poses.pml"
    carbon_colors = [
        "gray70", "cyan", "orange", "violet", "salmon",
        "teal", "yelloworange", "marine", "wheat", "purple",
    ]
    lines = [
        "# Crystallographic ligand versus every redocked pose",
        "# Green carbon: crystal pose; gray carbon: top-score pose; magenta carbon: best-RMSD pose",
        "# Every pose is an individually toggleable object in the docked_poses group.",
        "reinitialize",
        f"cd {output_dir}",
        "load receptor.pdb, receptor",
        "load crystal_ligand.pdb, crystal_ligand",
    ]

    object_names = []
    for index, row in enumerate(rows):
        model = int(row["model"])
        tags = []
        if index == top_index:
            tags.append("top_score")
        if index == best_rmsd_index:
            tags.append("best_rmsd")
        tag = "_" + "_".join(tags) if tags else ""
        score = safe_value(row["affinity_kcal_per_mol"] or "NA")
        rmsd = safe_value(row["crystal_rmsd_angstrom"])
        object_name = f"pose_{model:03d}{tag}_E_{score}_RMSD_{rmsd}"
        object_names.append(object_name)
        lines.append(f"load pose_{model:03d}.sdf, {object_name}")

    lines.extend([
        "hide everything, all",
        "show cartoon, receptor and polymer.protein",
        "color slate, receptor and polymer.protein",
        "set cartoon_transparency, 0.65, receptor",
        "show sticks, crystal_ligand",
        "color green, crystal_ligand and elem C",
        "util.cnc crystal_ligand",
    ])

    for index, object_name in enumerate(object_names):
        if index == top_index:
            color = "gray70"
        elif index == best_rmsd_index:
            color = "magenta"
        else:
            color = carbon_colors[index % len(carbon_colors)]
        lines.extend([
            f"show sticks, {object_name}",
            f"color {color}, {object_name} and elem C",
            f"util.cnc {object_name}",
            f"set stick_transparency, {0.0 if index in (top_index, best_rmsd_index) else 0.25}, {object_name}",
        ])

    lines.extend([
        f"group docked_poses, {' '.join(object_names)}",
        "set stick_radius, 0.16",
        "bg_color white",
        "zoom crystal_ligand or docked_poses, 8",
        "orient crystal_ligand or docked_poses",
    ])
    pml_path.write_text("\n".join(lines) + "\n")
    return pml_path


def write_pose_browser_pml(output_dir, rows, top_index, best_rmsd_index, contact_cutoff):
    """Write a scene-based browser showing one pose and its local residues at a time."""
    pml_path = output_dir / "crystal_pose_browser.pml"
    lines = [
        "# Scene-based crystallographic-ligand/redocked-pose browser",
        f"# Each scene shows one pose and receptor residues within {contact_cutoff:.1f} A.",
        "# Use the PyMOL scene buttons or type: scene next / scene previous",
        "reinitialize",
        f"cd {output_dir}",
        "load receptor.pdb, receptor",
        "load crystal_ligand.sdf, crystal_ligand",
        "hide everything, all",
        "show cartoon, receptor and polymer.protein",
        "color slate, receptor and polymer.protein",
        "set cartoon_transparency, 0.70, receptor",
        "show sticks, crystal_ligand",
        "color green, crystal_ligand and elem C",
        "util.cnc crystal_ligand",
        "set stick_radius, 0.17",
        "bg_color white",
        "set label_color, black",
        "set label_font_id, 7",
        "set label_outline_color, white",
    ]

    pose_objects = []
    site_objects = []
    label_objects = []
    for index, row in enumerate(rows):
        model = int(row["model"])
        tags = []
        if index == top_index:
            tags.append("top_score")
        if index == best_rmsd_index:
            tags.append("best_rmsd")
        tag = "_" + "_".join(tags) if tags else ""
        score_text = row["affinity_kcal_per_mol"] or "NA"
        score = safe_value(score_text)
        rmsd_text = row["crystal_rmsd_angstrom"]
        rmsd = safe_value(rmsd_text)
        pose_object = f"pose_{model:03d}{tag}_E_{score}_RMSD_{rmsd}"
        site_object = f"site_within_{contact_cutoff:g}A_pose_{model:03d}"
        label_object = f"pose_information_{model:03d}"
        pose_objects.append(pose_object)
        site_objects.append(site_object)
        label_objects.append(label_object)

        status = []
        if index == top_index:
            status.append("LOWEST ENERGY")
        if index == best_rmsd_index:
            status.append("LOWEST RMSD")
        status_text = " | ".join(status) if status else "sampled pose"
        display_label = (
            f"Pose {model} | {status_text} | Energy {score_text} kcal/mol | "
            f"RMSD {rmsd_text} A"
        )
        carbon_color = "gray70" if index == top_index else "magenta" if index == best_rmsd_index else "cyan"

        lines.extend([
            f"load pose_{model:03d}.sdf, {pose_object}",
            f"create {site_object}, byres (receptor within {contact_cutoff:.3f} of {pose_object})",
            f"hide everything, {site_object}",
            f"show sticks, {site_object}",
            f"color skyblue, {site_object} and elem C",
            f"util.cnc {site_object}",
            f"set stick_radius, 0.13, {site_object}",
            f"set label_size, 12, {site_object}",
            f"set label_color, gray20, {site_object}",
            f"label {site_object} and name CA, \"%s%s/%s\" % (resn,resi,chain)",
            f"show sticks, {pose_object}",
            f"set stick_radius, 0.18, {pose_object}",
            f"color {carbon_color}, {pose_object} and elem C",
            f"util.cnc {pose_object}",
            f"pseudoatom {label_object}, selection={pose_object}, label=\"{display_label}\"",
            f"hide nonbonded, {label_object}",
            f"show labels, {label_object}",
            f"set label_size, 18, {label_object}",
            f"set label_color, black, {label_object}",
            f"set label_position, [0.0, 8.0, 0.0], {label_object}",
        ])

    all_switchable = pose_objects + site_objects + label_objects
    lines.append(f"group docked_pose_browser, {' '.join(all_switchable)}")
    lines.extend(f"disable {name}" for name in all_switchable)

    for index, row in enumerate(rows):
        model = int(row["model"])
        lines.extend([
            f"enable {pose_objects[index]}",
            f"enable {site_objects[index]}",
            f"enable {label_objects[index]}",
            f"zoom crystal_ligand or {pose_objects[index]} or {site_objects[index]}, 7",
            f"orient crystal_ligand or {pose_objects[index]}",
            f"scene pose_{model:03d}, store",
            f"disable {pose_objects[index]}",
            f"disable {site_objects[index]}",
            f"disable {label_objects[index]}",
        ])

    lines.extend([
        "scene pose_001, recall",
        "python",
        "from pymol import cmd",
        "cmd.set_key('RIGHT', lambda: cmd.scene('', 'next'))",
        "cmd.set_key('LEFT', lambda: cmd.scene('', 'previous'))",
        "python end",
    ])
    pml_path.write_text("\n".join(lines) + "\n")
    return pml_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference-sdf", required=True, type=Path, help="Matching ligand SDF with bond orders")
    parser.add_argument("--crystal-ligand", required=True, type=Path, help="Bound ligand coordinates extracted from the complex PDB")
    parser.add_argument("--docked-pdbqt", required=True, type=Path, help="Multi-model Vina/smina docking output")
    parser.add_argument("--receptor-pdb", required=True, type=Path, help="Prepared receptor PDB without the bound ligand")
    parser.add_argument("--out", required=True, type=Path, help="Output directory")
    parser.add_argument("--mk-export", default="mk_export.py", help="Meeko pose exporter")
    parser.add_argument("--rmsd-threshold", type=float, default=2.0, help="Conventional recovery threshold in angstroms")
    parser.add_argument("--contact-cutoff", type=float, default=5.0, help="Receptor neighborhood shown around each pose")
    args = parser.parse_args()

    inputs = [args.reference_sdf, args.crystal_ligand, args.docked_pdbqt, args.receptor_pdb]
    for path in inputs:
        if not path.expanduser().is_file():
            parser.error(f"input does not exist: {path}")

    exporter = shutil.which(args.mk_export) if Path(args.mk_export).name == args.mk_export else args.mk_export
    if not exporter or not Path(exporter).is_file():
        parser.error(f"Meeko exporter not found: {args.mk_export}")

    output_dir = args.out.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    exported_sdf = output_dir / "docked_poses.sdf"
    export_result = subprocess.run(
        [str(exporter), str(args.docked_pdbqt.expanduser().resolve()), "-s", str(exported_sdf)],
        capture_output=True,
        text=True,
    )
    (output_dir / "mk_export.log").write_text(
        f"RETURN CODE: {export_result.returncode}\n\nSTDOUT:\n{export_result.stdout}\n\nSTDERR:\n{export_result.stderr}\n"
    )
    if export_result.returncode != 0 or not exported_sdf.is_file():
        raise SystemExit(f"Meeko pose export failed; see {output_dir / 'mk_export.log'}")

    from rdkit import Chem
    from rdkit.Chem import AllChem, rdMolAlign

    template_full = first_sdf_molecule(args.reference_sdf.expanduser().resolve(), remove_hs=False)
    if template_full is None:
        raise SystemExit("reference SDF could not be read by RDKit")
    template = Chem.RemoveHs(template_full)

    crystal_raw = Chem.MolFromPDBFile(
        str(args.crystal_ligand.expanduser().resolve()), removeHs=True, sanitize=False
    )
    if crystal_raw is None:
        raise SystemExit("crystallographic ligand PDB could not be read by RDKit")
    try:
        crystal = AllChem.AssignBondOrdersFromTemplate(template, crystal_raw)
        Chem.SanitizeMol(crystal)
    except Exception as exc:
        raise SystemExit(f"could not map SDF chemistry onto crystallographic coordinates: {exc}") from exc

    poses = [Chem.RemoveHs(mol) for mol in Chem.SDMolSupplier(str(exported_sdf), removeHs=False) if mol]
    if not poses:
        raise SystemExit("Meeko exported no readable docked poses")

    scores = parse_scores(args.docked_pdbqt.expanduser().resolve())
    rows = []
    pose_paths = []
    pose_sdf_paths = []
    for index, pose in enumerate(poses, start=1):
        if pose.GetNumHeavyAtoms() != crystal.GetNumHeavyAtoms():
            raise SystemExit(
                f"pose {index} has {pose.GetNumHeavyAtoms()} heavy atoms; crystal ligand has {crystal.GetNumHeavyAtoms()}"
            )
        try:
            rmsd = rdMolAlign.CalcRMS(pose, crystal, maxMatches=100000)
        except Exception as exc:
            raise SystemExit(f"symmetry-aware atom mapping failed for pose {index}: {exc}") from exc

        set_ligand_pdb_info(pose)
        pose_path = output_dir / f"pose_{index:03d}.pdb"
        Chem.MolToPDBFile(pose, str(pose_path))
        pose_paths.append(pose_path)
        pose_sdf_path = output_dir / f"pose_{index:03d}.sdf"
        pose_writer = Chem.SDWriter(str(pose_sdf_path))
        pose_writer.write(pose)
        pose_writer.close()
        pose_sdf_paths.append(pose_sdf_path)
        affinity = scores.get(index)
        rows.append({
            "model": index,
            "affinity_kcal_per_mol": "" if affinity is None else f"{affinity:.7g}",
            "crystal_rmsd_angstrom": f"{rmsd:.4f}",
            "within_threshold": "yes" if rmsd <= args.rmsd_threshold else "no",
        })

    comparison_csv = output_dir / "pose_comparison.csv"
    with comparison_csv.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    scored_indices = [i for i in range(len(rows)) if rows[i]["affinity_kcal_per_mol"] != ""]
    top_index = min(scored_indices, key=lambda i: float(rows[i]["affinity_kcal_per_mol"])) if scored_indices else 0
    best_rmsd_index = min(range(len(rows)), key=lambda i: float(rows[i]["crystal_rmsd_angstrom"]))

    receptor_copy = output_dir / "receptor.pdb"
    crystal_copy = output_dir / "crystal_ligand.pdb"
    crystal_sdf = output_dir / "crystal_ligand.sdf"
    top_pose_copy = output_dir / "top_score_pose.pdb"
    best_rmsd_copy = output_dir / "best_rmsd_pose.pdb"
    shutil.copy2(args.receptor_pdb, receptor_copy)
    shutil.copy2(args.crystal_ligand, crystal_copy)
    crystal.SetProp("_Name", "crystal_ligand")
    crystal_writer = Chem.SDWriter(str(crystal_sdf))
    crystal_writer.write(crystal)
    crystal_writer.close()
    shutil.copy2(pose_paths[top_index], top_pose_copy)
    shutil.copy2(pose_paths[best_rmsd_index], best_rmsd_copy)
    shutil.copy2(pose_sdf_paths[top_index], output_dir / "top_score_pose.sdf")
    shutil.copy2(pose_sdf_paths[best_rmsd_index], output_dir / "best_rmsd_pose.sdf")

    top_complex = output_dir / "top_score_complex.pdb"
    best_rmsd_complex = output_dir / "best_rmsd_complex.pdb"
    write_complex(receptor_copy, top_pose_copy, top_complex)
    write_complex(receptor_copy, best_rmsd_copy, best_rmsd_complex)
    overlay_pml = write_overlay_pml(output_dir, float(rows[top_index]["crystal_rmsd_angstrom"]))
    all_poses_pml = write_all_poses_pml(output_dir, rows, top_index, best_rmsd_index)
    pose_browser_pml = write_pose_browser_pml(
        output_dir, rows, top_index, best_rmsd_index, args.contact_cutoff
    )

    summary = {
        "method": "RDKit CalcRMS; symmetry-aware heavy-atom RMSD in the receptor coordinate frame without pose fitting",
        "threshold_angstrom": args.rmsd_threshold,
        "pose_count": len(rows),
        "top_score_model": top_index + 1,
        "top_score_affinity_kcal_per_mol": rows[top_index]["affinity_kcal_per_mol"],
        "top_score_rmsd_angstrom": float(rows[top_index]["crystal_rmsd_angstrom"]),
        "top_score_within_threshold": rows[top_index]["within_threshold"] == "yes",
        "best_rmsd_model": best_rmsd_index + 1,
        "best_rmsd_angstrom": float(rows[best_rmsd_index]["crystal_rmsd_angstrom"]),
        "outputs": {
            "comparison_csv": comparison_csv.name,
            "top_score_complex": top_complex.name,
            "best_rmsd_complex": best_rmsd_complex.name,
            "typed_crystal_sdf": crystal_sdf.name,
            "typed_pose_sdfs": [path.name for path in pose_sdf_paths],
            "overlay_pml": overlay_pml.name,
            "all_poses_overlay_pml": all_poses_pml.name,
            "pose_browser_pml": pose_browser_pml.name,
        },
    }
    (output_dir / "comparison_summary.json").write_text(json.dumps(summary, indent=2) + "\n")

    print(f"Compared {len(rows)} docked poses")
    print(
        f"Top-score model {top_index + 1}: RMSD {rows[top_index]['crystal_rmsd_angstrom']} A "
        f"(threshold {args.rmsd_threshold:.2f} A: {rows[top_index]['within_threshold']})"
    )
    print(f"Best-RMSD model {best_rmsd_index + 1}: {rows[best_rmsd_index]['crystal_rmsd_angstrom']} A")
    print(f"Comparison table: {comparison_csv}")


if __name__ == "__main__":
    main()
