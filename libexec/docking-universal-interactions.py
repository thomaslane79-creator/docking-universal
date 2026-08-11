#!/usr/bin/env python
"""
plip_local.py

Run PLIP on a local PDB file, create a timestamped output folder, and generate
a self-contained all-in-one PyMOL PML scene from the PLIP XML.

Usage:
    plip_local input_complex.pdb

Optional:
    plip_local input_complex.pdb --out-parent /path/to/results
    plip_local input_complex.pdb --plip-command plip
    plip_local input_complex.pdb --skip-native-visuals
"""

import argparse
import json
import shutil
import subprocess
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path


# -----------------------------
# Small XML helpers
# -----------------------------

def get_text(node, path, default=""):
    found = node.find(path)
    if found is None or found.text is None:
        return default
    return found.text.strip()


def get_float(node, path):
    text = get_text(node, path)
    if text == "":
        return None
    return float(text)


def get_coord(node, tag):
    coord_node = node.find(tag)
    if coord_node is None:
        return None

    x = get_float(coord_node, "x")
    y = get_float(coord_node, "y")
    z = get_float(coord_node, "z")

    if x is None or y is None or z is None:
        return None

    return (x, y, z)


def pml_coord(coord):
    x, y, z = coord
    return f"[{x:.3f}, {y:.3f}, {z:.3f}]"


def safe_name(text):
    return (
        str(text)
        .replace(" ", "_")
        .replace("-", "_")
        .replace(".", "_")
        .replace(":", "_")
        .replace("/", "_")
        .replace("+", "plus")
        .replace("'", "")
        .replace('"', "")
    )


def parse_bs_residue(text):
    """
    PLIP binding-site residue text often looks like '714A':
        residue number = 714
        chain = A
    """
    text = (text or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    letters = "".join(ch for ch in text if ch.isalpha())

    if not digits or not letters:
        return None, None

    return digits, letters


# -----------------------------
# Shell command helper
# -----------------------------

def run_command(command, log_path, required=True):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
    )

    log_text = (
        f"COMMAND:\n{' '.join(command)}\n\n"
        f"RETURN CODE:\n{result.returncode}\n\n"
        f"STDOUT:\n{result.stdout}\n\n"
        f"STDERR:\n{result.stderr}\n"
    )

    log_path.write_text(log_text)

    if required and result.returncode != 0:
        raise RuntimeError(f"Required command failed. See log: {log_path}")

    return result


# -----------------------------
# Output discovery
# -----------------------------

def find_report_xml(output_dir):
    xml_files = sorted(output_dir.rglob("*.xml"))

    if not xml_files:
        raise FileNotFoundError(f"No XML files found in: {output_dir}")

    # Prefer a PLIP report.xml if present.
    for xml_file in xml_files:
        if xml_file.name.lower() == "report.xml":
            return xml_file

    return xml_files[0]


def find_pdb_for_pml(output_dir, input_pdb, xml_path):
    """
    Prefer the PLIP-fixed PDB referenced inside the XML. Fall back to any
    plipfixed*.pdb in the output folder. Fall back to a copied input PDB.
    """
    try:
        root = ET.parse(xml_path).getroot()
        pdbfile_text = get_text(root, "pdbfile")
        if pdbfile_text:
            xml_pdb_path = Path(pdbfile_text).expanduser()
            if xml_pdb_path.exists():
                return xml_pdb_path
    except Exception:
        pass

    candidates = sorted(output_dir.rglob("plipfixed*.pdb"))
    if candidates:
        return candidates[0]

    # If PLIP did not leave a fixed PDB in the output folder, copy the input
    # PDB into the output folder and use that.
    copied_pdb = output_dir / input_pdb.name
    if not copied_pdb.exists():
        shutil.copy2(input_pdb, copied_pdb)
    return copied_pdb


# -----------------------------
# PML generation
# -----------------------------

def add_pseudo_distance(lines, prefix, count, coord1, coord2, color, comment, group_name):
    obj1 = f"{prefix}_{count}_a"
    obj2 = f"{prefix}_{count}_b"
    dist_obj = f"{prefix}_{count}"

    lines.append(f"# {comment}")
    lines.append(f"pseudoatom {obj1}, pos={pml_coord(coord1)}, vdw=0.18")
    lines.append(f"pseudoatom {obj2}, pos={pml_coord(coord2)}, vdw=0.18")
    lines.append(f"show spheres, {obj1} or {obj2}")
    lines.append(f"color {color}, {obj1} or {obj2}")
    lines.append(f"distance {dist_obj}, {obj1}, {obj2}")
    lines.append(f"color {color}, {dist_obj}")
    lines.append(f"hide labels, {dist_obj}")
    lines.append(f"group {group_name}, {obj1} {obj2} {dist_obj}")
    lines.append("")


def generate_all_in_one_pml(
    xml_path,
    pdb_path,
    output_dir,
    pml_path,
    ligand_resname=None,
    ligand_chain=None,
    ligand_position=None,
    typed_ligand_sdf=None,
):
    """
    Generate one self-contained PML in the PLIP output folder.

    The PML changes PyMOL's working directory to output_dir, loads pdb_path
    by relative filename when possible, styles protein/ligands, and overlays
    interaction markers from PLIP XML coordinates.
    """
    tree = ET.parse(xml_path)
    root = tree.getroot()

    binding_sites = []
    for bs in root.findall("bindingsite"):
        hetid = get_text(bs, "./identifiers/hetid")
        chain = get_text(bs, "./identifiers/chain")
        position = get_text(bs, "./identifiers/position")
        if ligand_resname and hetid.upper() != ligand_resname.upper():
            continue
        if ligand_chain and chain != ligand_chain:
            continue
        if ligand_position and position != str(ligand_position):
            continue
        binding_sites.append(bs)

    if (ligand_resname or ligand_chain or ligand_position) and not binding_sites:
        requested = ":".join(
            part for part in (ligand_resname, ligand_chain, str(ligand_position or "")) if part
        )
        raise ValueError(f"PLIP report has no binding site matching {requested}")

    output_dir = output_dir.resolve()
    pdb_path = pdb_path.resolve()

    try:
        pdb_load_path = pdb_path.relative_to(output_dir)
    except ValueError:
        pdb_load_path = pdb_path

    lines = [
        "# All-in-one PLIP local PyMOL scene",
        "# Generated from PLIP XML coordinates.",
        "# This file should be portable as long as the output folder stays together.",
        "",
        "reinitialize",
        # PyMOL's command parser accepts spaces in the remainder of `cd` and
        # before the comma in `load`. Quoting these paths causes PyMOL 3.0 on
        # macOS arm64 to skip the molecular load without a fatal exit status.
        f"cd {output_dir}",
        f"load {pdb_load_path}, complex",
        "",
        "# Base molecular display",
        "hide everything",
        "show cartoon, complex and polymer.protein",
        "color slate, complex and polymer.protein",
        "set cartoon_transparency, 0.35",
        "",
        "# Selected ligand / heteroatom display",
        "show spheres, complex and inorganic",
        "color orange, complex and inorganic",
        "",
    ]
    if typed_ligand_sdf:
        typed_ligand_sdf = Path(typed_ligand_sdf).resolve()
        try:
            typed_load_path = typed_ligand_sdf.relative_to(output_dir)
        except ValueError:
            typed_load_path = typed_ligand_sdf
        lines.extend([
            "# Authoritative ligand chemistry loaded from SDF; PDB ligand is hidden.",
            f"load {typed_load_path}, typed_ligand",
            f"hide everything, complex and resn {ligand_resname} and chain {ligand_chain} and resi {ligand_position}",
            "show sticks, typed_ligand",
            "color gray70, typed_ligand and elem C",
            "util.cnc typed_ligand",
            "",
        ])

    # Per-binding-site ligand selections
    ligand_selections = []
    selected_sites = []
    for bs in binding_sites:
        lig_name = get_text(bs, "./identifiers/longname")
        hetid = get_text(bs, "./identifiers/hetid")
        lig_chain = get_text(bs, "./identifiers/chain")
        lig_position = get_text(bs, "./identifiers/position")
        lig_type = get_text(bs, "./identifiers/ligtype")
        bs_id = bs.get("id", "unknown")

        if hetid and lig_chain and lig_position:
            sel = f"plip_ligand_bs_{safe_name(bs_id)}_{safe_name(hetid)}_{safe_name(lig_chain)}_{safe_name(lig_position)}"
            ligand_selections.append(sel)
            selected_sites.append({
                "binding_site_id": bs_id,
                "resname": hetid,
                "chain": lig_chain,
                "position": lig_position,
                "type": lig_type,
            })
            if typed_ligand_sdf:
                lines.append(f"select {sel}, typed_ligand")
            else:
                lines.append(
                    f"select {sel}, complex and resn {hetid} and chain {lig_chain} and resi {lig_position}"
                )
            if lig_type == "ION":
                lines.append(f"show spheres, {sel}")
                lines.append(f"color orange, {sel}")
            else:
                lines.append(f"show sticks, {sel}")
                lines.append(f"color gray70, {sel}")
                lines.append(f"util.cnc {sel}")
            lines.append(f"# Binding site {bs_id}: {lig_name} {lig_chain}:{lig_position} type={lig_type}")
            lines.append("")

    # Binding-site residue display
    residues_by_chain = {}
    contact_residues_by_chain = {}

    for bs in binding_sites:
        for residue in bs.findall("./bs_residues/bs_residue"):
            resi, chain = parse_bs_residue(residue.text)
            if resi and chain:
                residues_by_chain.setdefault(chain, set()).add(resi)
                if residue.get("contact") == "True":
                    contact_residues_by_chain.setdefault(chain, set()).add(resi)

    for chain, residues in sorted(residues_by_chain.items()):
        resi_string = "+".join(sorted(residues, key=lambda x: int(x)))
        sel = f"plip_binding_site_chain_{safe_name(chain)}"
        lines.append(
            f"select {sel}, complex and polymer.protein and chain {chain} and resi {resi_string}"
        )
        lines.append(f"show sticks, {sel}")
        lines.append(f"color marine, {sel}")
        lines.append("")

    for chain, residues in sorted(contact_residues_by_chain.items()):
        resi_string = "+".join(sorted(residues, key=lambda x: int(x)))
        sel = f"plip_contact_residues_chain_{safe_name(chain)}"
        lines.append(
            f"select {sel}, complex and polymer.protein and chain {chain} and resi {resi_string}"
        )
        lines.append(f"show sticks, {sel}")
        lines.append(f"color tv_blue, {sel}")
        lines.append("")

    # Interaction groups
    lines.extend([
        "# Interaction groups",
        "group PLIP_interactions",
        "group PLIP_hydrophobic",
        "group PLIP_hbonds",
        "group PLIP_pistacking",
        "group PLIP_metal",
        "",
    ])

    counts = {
        "hydrophobic": 0,
        "hbond": 0,
        "pistack": 0,
        "metal": 0,
    }

    for bs in binding_sites:
        bs_id = bs.get("id", "unknown")
        lig_name = get_text(bs, "./identifiers/longname")
        lig_chain = get_text(bs, "./identifiers/chain")
        lig_position = get_text(bs, "./identifiers/position")
        lig_type = get_text(bs, "./identifiers/ligtype")

        lines.append(f"# Binding site {bs_id}: {lig_name} chain {lig_chain} position {lig_position} type {lig_type}")
        lines.append("")

        for interaction in bs.findall("./interactions/hydrophobic_interactions/hydrophobic_interaction"):
            ligcoo = get_coord(interaction, "ligcoo")
            protcoo = get_coord(interaction, "protcoo")
            if ligcoo is None or protcoo is None:
                continue

            counts["hydrophobic"] += 1
            resnr = get_text(interaction, "resnr")
            restype = get_text(interaction, "restype")
            chain = get_text(interaction, "reschain")
            dist = get_text(interaction, "dist")
            comment = f"hydrophobic {counts['hydrophobic']}: {restype}{resnr}{chain}, distance {dist} A"

            add_pseudo_distance(
                lines,
                "plip_hydrophobic",
                counts["hydrophobic"],
                ligcoo,
                protcoo,
                "gray50",
                comment,
                "PLIP_hydrophobic",
            )

        for interaction in bs.findall("./interactions/hydrogen_bonds/hydrogen_bond"):
            ligcoo = get_coord(interaction, "ligcoo")
            protcoo = get_coord(interaction, "protcoo")
            if ligcoo is None or protcoo is None:
                continue

            counts["hbond"] += 1
            resnr = get_text(interaction, "resnr")
            restype = get_text(interaction, "restype")
            chain = get_text(interaction, "reschain")
            dist_da = get_text(interaction, "dist_d-a")
            angle = get_text(interaction, "don_angle")
            protisdon = get_text(interaction, "protisdon")
            comment = (
                f"hbond {counts['hbond']}: {restype}{resnr}{chain}, "
                f"D-A {dist_da} A, angle {angle}, protisdon={protisdon}"
            )

            add_pseudo_distance(
                lines,
                "plip_hbond",
                counts["hbond"],
                ligcoo,
                protcoo,
                "yellow",
                comment,
                "PLIP_hbonds",
            )

        for interaction in bs.findall("./interactions/pi_stacks/pi_stack"):
            ligcoo = get_coord(interaction, "ligcoo")
            protcoo = get_coord(interaction, "protcoo")
            if ligcoo is None or protcoo is None:
                continue

            counts["pistack"] += 1
            resnr = get_text(interaction, "resnr")
            restype = get_text(interaction, "restype")
            chain = get_text(interaction, "reschain")
            centdist = get_text(interaction, "centdist")
            angle = get_text(interaction, "angle")
            stack_type = get_text(interaction, "type")
            comment = (
                f"pi-stack {counts['pistack']}: {restype}{resnr}{chain}, "
                f"centroid {centdist} A, angle {angle}, type {stack_type}"
            )

            add_pseudo_distance(
                lines,
                "plip_pistack",
                counts["pistack"],
                ligcoo,
                protcoo,
                "green",
                comment,
                "PLIP_pistacking",
            )

        for interaction in bs.findall("./interactions/metal_complexes/metal_complex"):
            metalcoo = get_coord(interaction, "metalcoo")
            targetcoo = get_coord(interaction, "targetcoo")
            if metalcoo is None or targetcoo is None:
                continue

            counts["metal"] += 1
            resnr = get_text(interaction, "resnr")
            restype = get_text(interaction, "restype")
            chain = get_text(interaction, "reschain")
            metal_type = get_text(interaction, "metal_type")
            dist = get_text(interaction, "dist")
            geometry = get_text(interaction, "geometry")
            comment = (
                f"metal {counts['metal']}: {metal_type} to {restype}{resnr}{chain}, "
                f"distance {dist} A, geometry {geometry}"
            )

            add_pseudo_distance(
                lines,
                "plip_metal",
                counts["metal"],
                metalcoo,
                targetcoo,
                "magenta",
                comment,
                "PLIP_metal",
            )

    lines.extend([
        "# Put interaction subgroups under one top-level group",
        "group PLIP_interactions, PLIP_hydrophobic PLIP_hbonds PLIP_pistacking PLIP_metal",
        "",
        "# Display settings",
        "set dash_width, 2.0",
        "set dash_gap, 0.25",
        "set sphere_scale, 0.20",
        "set stick_radius, 0.16",
        "hide labels, all",
        "bg_color white",
        "",
        "# Zoom to selected PLIP ligand objects",
        f"zoom {' or '.join(ligand_selections) if ligand_selections else 'complex and (organic or inorganic)'}, 10",
        "",
        f"# Counts: hydrophobic={counts['hydrophobic']}, hbonds={counts['hbond']}, pistacks={counts['pistack']}, metal={counts['metal']}",
        "",
    ])

    pml_path.write_text("\n".join(lines) + "\n")
    return counts, selected_sites


# -----------------------------
# Main workflow
# -----------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Run PLIP locally and create a timestamped all-in-one PyMOL PML scene."
    )

    parser.add_argument(
        "pdb_file",
        help="Input protein-ligand complex PDB file",
    )

    parser.add_argument(
        "--out-parent",
        default=None,
        help="Parent folder for timestamped PLIP results. Default: input PDB folder.",
    )

    parser.add_argument(
        "--out-dir",
        default=None,
        help="Exact output folder. Mutually exclusive with --out-parent.",
    )

    parser.add_argument(
        "--ligand-resname",
        default=None,
        help="Limit the generated PML and counts to this PLIP ligand residue name.",
    )

    parser.add_argument(
        "--ligand-chain",
        default=None,
        help="Optional ligand chain filter used with --ligand-resname.",
    )

    parser.add_argument(
        "--ligand-position",
        default=None,
        help="Optional ligand residue-number filter used with --ligand-resname.",
    )
    parser.add_argument(
        "--typed-ligand-sdf",
        default=None,
        help="Authoritative ligand SDF used for PyMOL bond orders instead of PDB distance perception.",
    )

    parser.add_argument(
        "--plip-command",
        default="plip",
        help="PLIP executable or command name. Default: plip",
    )

    parser.add_argument(
        "--skip-native-visuals",
        action="store_true",
        help="Skip PLIP's native PSE/ray image attempt.",
    )

    args = parser.parse_args()

    input_pdb = Path(args.pdb_file).expanduser().resolve()

    if not input_pdb.exists():
        raise FileNotFoundError(f"Input PDB not found: {input_pdb}")
    typed_ligand_sdf = Path(args.typed_ligand_sdf).expanduser().resolve() if args.typed_ligand_sdf else None
    if typed_ligand_sdf and not typed_ligand_sdf.is_file():
        raise FileNotFoundError(f"Typed ligand SDF not found: {typed_ligand_sdf}")
    if typed_ligand_sdf and not (args.ligand_resname and args.ligand_chain and args.ligand_position):
        parser.error("--typed-ligand-sdf requires exact ligand residue, chain, and position filters")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    if args.out_dir and args.out_parent:
        parser.error("--out-dir and --out-parent are mutually exclusive")

    if args.out_dir:
        output_dir = Path(args.out_dir).expanduser().resolve()
    elif args.out_parent is None:
        out_parent = input_pdb.parent
        output_dir = out_parent / f"{input_pdb.stem}_plip_local_{timestamp}"
    else:
        out_parent = Path(args.out_parent).expanduser().resolve()
        output_dir = out_parent / f"{input_pdb.stem}_plip_local_{timestamp}"
    logs_dir = output_dir / "logs"
    native_visuals_dir = output_dir / "native_visuals"

    output_dir.mkdir(parents=True, exist_ok=False)
    logs_dir.mkdir(parents=True, exist_ok=True)
    native_visuals_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "input_pdb": str(input_pdb),
        "output_dir": str(output_dir),
        "timestamp": timestamp,
        "steps": {},
        "ligand_filter": {
            "resname": args.ligand_resname,
            "chain": args.ligand_chain,
            "position": args.ligand_position,
        },
        "typed_ligand_sdf": str(typed_ligand_sdf) if typed_ligand_sdf else None,
    }

    try:
        # Stable PLIP analytical outputs
        analysis_command = [
            args.plip_command,
            "-f", str(input_pdb),
            "-x",
            "-t",
            "-o", str(output_dir),
        ]

        run_command(
            analysis_command,
            logs_dir / "plip_xml_text.log",
            required=True,
        )
        manifest["steps"]["plip_xml_text"] = "succeeded"

        # Optional native PLIP visuals. This is nonfatal because it is the brittle part.
        if args.skip_native_visuals:
            manifest["steps"]["plip_native_visuals"] = "skipped"
        else:
            native_command = [
                args.plip_command,
                "-f", str(input_pdb),
                "-y",
                "-p",
                "-o", str(native_visuals_dir),
            ]

            native_result = run_command(
                native_command,
                logs_dir / "plip_native_visuals.log",
                required=False,
            )

            if native_result.returncode == 0:
                manifest["steps"]["plip_native_visuals"] = "succeeded"
            else:
                manifest["steps"]["plip_native_visuals"] = "failed_nonfatal"

        # Find outputs and generate all-in-one PML
        report_xml = find_report_xml(output_dir)
        manifest["steps"]["report_xml"] = str(report_xml)

        pdb_for_pml = find_pdb_for_pml(output_dir, input_pdb, report_xml)
        manifest["steps"]["pdb_for_pml"] = str(pdb_for_pml)

        pml_path = output_dir / f"{input_pdb.stem}_plip_all_in_one.pml"
        counts, selected_sites = generate_all_in_one_pml(
            xml_path=report_xml,
            pdb_path=pdb_for_pml,
            output_dir=output_dir,
            pml_path=pml_path,
            ligand_resname=args.ligand_resname,
            ligand_chain=args.ligand_chain,
            ligand_position=args.ligand_position,
            typed_ligand_sdf=typed_ligand_sdf,
        )

        manifest["steps"]["all_in_one_pml"] = str(pml_path)
        manifest["interaction_counts"] = counts
        manifest["selected_binding_sites"] = selected_sites

        manifest["status"] = "succeeded"

    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error"] = str(exc)
        raise

    finally:
        manifest_path = output_dir / "run_manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2))

    print("")
    print("Done.")
    print(f"Output folder: {output_dir}")
    print(f"All-in-one PML: {pml_path}")
    print(f"Manifest: {manifest_path}")
    print("")
    print("Open in PyMOL with:")
    print(f'  pymol "{pml_path}"')
    print("")
    print("Or from inside PyMOL:")
    print(f'  @{pml_path}')


if __name__ == "__main__":
    main()
