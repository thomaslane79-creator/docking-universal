#!/usr/bin/env python
"""Redock the exact retained A/B ensembles without repeating minimization.

Creates a separate local control using an explicitly selected deposited dimer
and ligand instance. No production studies or preparation results are edited.
"""
import argparse
import csv
import json
import math
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

from rdkit import Chem
from rdkit.Chem import AllChem

import conformer_ab as ab


def verify_coordinate_frame(original, prepared):
    """Require polymer C-alpha anchors to stay in the crystal/box frame.

    Reduce2 can legitimately flip side chains, but without CRYST1 it also
    boxes/translates the entire model. Atom inventory alone cannot detect that.
    """
    def anchors(path):
        return {(line[21:27], line[17:20]): tuple(float(line[i:i+8]) for i in (30, 38, 46))
                for line in path.read_text().splitlines()
                if line.startswith("ATOM  ") and line[12:16].strip() == "CA"}
    before, after = anchors(original), anchors(prepared)
    if not before or before.keys() != after.keys():
        raise ValueError(f"Missing or changed receptor coordinate anchors: {prepared.name}")
    maximum = max(math.sqrt(sum((a-b)**2 for a, b in zip(position, after[key])))
                  for key, position in before.items())
    if maximum > 0.01:
        raise ValueError(f"Receptor moved out of crystal/box coordinate frame: {maximum:.3f} A ({prepared.name})")
    return {"anchor_count": len(before), "maximum_displacement_angstrom": maximum,
            "tolerance_angstrom": 0.01}


def conformations(preparation, output):
    inventory, matrices = {}, {}
    for arm in ("vacuum_pruned", "water_pruned"):
        molecules = list(Chem.SDMolSupplier(str(preparation / arm / "retained.sdf"), removeHs=False))
        if not molecules or any(m is None for m in molecules):
            raise ValueError(f"Unreadable retained ensemble: {arm}")
        inventory[arm] = molecules
        matrices[arm] = [[ab.aligned_rmsd(first, second) for second in molecules] for first in molecules]
    cross = [[ab.aligned_rmsd(first, second) for second in inventory["water_pruned"]]
             for first in inventory["vacuum_pruned"]]
    result = {"method": "aligned symmetry-aware heavy-atom RMSD; coordinates copied, never fitted for docking",
              "within_arm_rmsd_angstrom": matrices, "vacuum_rows_water_columns_rmsd_angstrom": cross}
    ab.dump(output / "conformation_comparison.json", result)
    with (output / "conformation_comparison.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["vacuum_conformer", *[f"water_conformer_{i+1}" for i in range(len(cross[0]))]])
        for index, row in enumerate(cross, 1):
            writer.writerow([index, *row])
    return inventory, result


def prepare_control(args, output, template):
    source = args.complex.read_text().splitlines()
    residue, chain, number = args.ligand_id.split(":")
    protein = [line for line in source if line.startswith("ATOM  ") and line[21:22] in args.chains]
    ligand = [line for line in source if line.startswith("HETATM") and line[17:20].strip() == residue
              and line[21:22] == chain and line[22:26].strip() == number]
    if not protein or not ligand:
        raise ValueError("Explicit chains/ligand instance not present in deposited source.")
    if any(line[16:17] != " " for line in protein + ligand):
        raise ValueError("Alternate conformations require explicit review; no silent alternate choice.")
    if any(line.startswith("MODRES") for line in source):
        raise ValueError("Modified polymer components require the main preparation workflow.")
    # This isolated dry control deliberately strips solvent/ions and other
    # ligand instances; exact identities/counts are recorded below.
    # Retain deposited crystallographic context: without it Reduce2 shifts and
    # boxes a noncrystallographic model, invalidating the unchanged ligand box.
    context = [line for line in source if line.startswith(("CRYST1", "SCALE1", "SCALE2", "SCALE3"))]
    (output / "receptor_raw.pdb").write_text("\n".join(context + protein + ["END"]) + "\n")
    crystal = output / "crystal_ligand.pdb"
    crystal.write_text("\n".join(ligand + ["END"]) + "\n")
    raw = Chem.MolFromPDBFile(str(crystal), removeHs=True, sanitize=False)
    if raw is None:
        raise ValueError("Deposited ligand cannot be read.")
    typed = AllChem.AssignBondOrdersFromTemplate(Chem.RemoveHs(template), raw)
    Chem.SanitizeMol(typed)
    if typed.GetNumHeavyAtoms() != template.GetNumHeavyAtoms():
        raise ValueError("Deposited ligand heavy-atom count does not match ensemble chemistry.")
    check = Chem.Mol(typed)
    Chem.AssignStereochemistryFrom3D(check, replaceExistingTags=True)
    Chem.AssignStereochemistry(check, cleanIt=True, force=True)
    # Require the crystal's graph and stereochemistry to match the supplied
    # ensemble, independent of atom ordering.
    expected = Chem.MolToSmiles(Chem.RemoveHs(template), isomericSmiles=True)
    actual = Chem.MolToSmiles(Chem.RemoveHs(check), isomericSmiles=True)
    if expected != actual:
        raise ValueError(f"Crystal/ensemble chemistry or stereochemistry mismatch: {actual} != {expected}")
    ab.sdf(output / "typed_crystal.sdf", [typed])
    coordinates = typed.GetConformer().GetPositions()
    center = coordinates.mean(axis=0)
    sizes = [max(26.0, float(coordinates[:, axis].max() - coordinates[:, axis].min()) + 10.0)
             for axis in range(3)]
    (output / "box.conf").write_text("".join(
        f"{prefix}_{axis} = {value:.6f}\n" for prefix, values in (("center", center), ("size", sizes))
        for axis, value in zip("xyz", values)))
    remarks = [line for line in source if line.startswith("REMARK 350")]
    audit = {"source_path": str(args.complex), "source_sha256": ab.digest(args.complex),
             "chains": args.chains, "ligand_id": args.ligand_id,
             "biological_assembly_remarks": remarks,
             "protein_atom_count": len(protein), "crystal_heavy_atom_count": typed.GetNumHeavyAtoms(),
             "chemistry_and_stereochemistry_match": True, "canonical_smiles": expected,
             "receptor_policy": "explicit protein chains; dry receptor; no other ligands or ions; no coordinate fitting",
             "box_policy": "crystal heavy-atom centroid; at least 26 A per axis and 5 A padding on each side"}
    ab.dump(output / "control_inputs.json", audit)
    # Use the existing chemistry-preserving Reduce2 wrapper, then strict Meeko.
    # No allow_bad_res, deleted-residue fallback or automatic tautomer override.
    env_root = Path(sys.executable).parent
    ab.run([sys.executable, str(ab.ROOT / "libexec/docking-universal-reduce2-receptor.py"),
            str(output / "receptor_raw.pdb"), str(output / "receptor.pdb"),
            str(output / "reduce2_audit.json"), str(output / "reduce2_internal.log")],
           output, "reduce2", args.timeout)
    audit["reduce2_coordinate_frame"] = verify_coordinate_frame(output / "receptor_raw.pdb", output / "receptor.pdb")
    ab.run([sys.executable, str(env_root / "mk_prepare_receptor.py"),
            "--read_pdb", str(output / "receptor.pdb"), "-o", str(output / "meeko_receptor"),
            "-p", str(output / "receptor.pdbqt")], output, "meeko_receptor", args.timeout)
    audit["meeko_coordinate_frame"] = verify_coordinate_frame(output / "receptor_raw.pdb", output / "receptor.pdbqt")
    ab.dump(output / "control_inputs.json", audit)
    return audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--preparation", required=True, type=Path)
    parser.add_argument("--complex", required=True, type=Path)
    parser.add_argument("--chains", required=True, nargs="+")
    parser.add_argument("--ligand-id", required=True, help="Exact RESNAME:CHAIN:NUMBER")
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--vina", required=True)
    parser.add_argument("--dock-seeds", nargs="+", type=int, default=[41001, 41002, 41003])
    parser.add_argument("--exhaustiveness", type=int, default=8)
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    args.preparation = args.preparation.expanduser().resolve()
    args.complex = args.complex.expanduser().resolve()
    output = args.out.expanduser().resolve()
    if output.exists():
        parser.error("Use a new output directory; neither old preparation nor docking runs are overwritten.")
    if args.exhaustiveness < 1 or args.timeout < 1 or any(not 1 <= seed < 2147483647 for seed in args.dock_seeds):
        parser.error("Positive effort/timeout and reproducible nonzero Vina seeds required.")
    manifest = json.loads((args.preparation / "summary.json").read_text())
    if manifest["status"] != "completed":
        parser.error("Preparation must have completed successfully.")
    tools = {"vina": ab.executable(args.vina),
             "meeko": ab.executable(str(Path(sys.executable).parent / "mk_prepare_ligand.py")),
             "exporter": ab.executable(str(Path(sys.executable).parent / "mk_export.py"))}
    output.mkdir(parents=True)
    result = {"status": "running", "preparation": str(args.preparation),
              "preparation_summary_sha256": ab.digest(args.preparation / "summary.json"),
              "coordinate_policy": "reuse exact retained minimized coordinates; crystal only for box/reference",
              "exhaustiveness": args.exhaustiveness, "cpu_per_job": 1, "num_modes": 9,
              "energy_range_kcal_mol": 3, "tools": tools, "arms": {}}
    try:
        inventory, comparisons = conformations(args.preparation, output)
        result["conformations"] = comparisons
        result["control"] = prepare_control(args, output, inventory["vacuum_pruned"][0])
        result["input_sha256"] = {name: ab.digest(output / name) for name in
                                 ("receptor.pdb", "receptor.pdbqt", "box.conf", "crystal_ligand.pdb")}
        common = SimpleNamespace(receptor_pdbqt=output / "receptor.pdbqt", receptor_pdb=output / "receptor.pdb",
                                 crystal_ligand=output / "crystal_ligand.pdb", timeout=args.timeout,
                                 exhaustiveness=args.exhaustiveness, num_modes=9)
        seeds = list(dict.fromkeys(args.dock_seeds))
        budget = min(len(molecules) for molecules in inventory.values())
        result.update(docked_conformers_per_arm=budget, seeds=seeds)
        ab.dump(output / "summary.json", result)
        for arm, molecules in inventory.items():
            folder = output / arm
            folder.mkdir()
            shutil.copy2(args.preparation / arm / "retained.sdf", folder / "retained.sdf")
            selected_ids = [row["input_id"] for row in sorted(manifest["arms"][arm]["records"],
                            key=lambda row: (row["energy_kcal_mol"], row["input_id"])) if row["disposition"] == "retained"]
            if len(selected_ids) != len(molecules):
                raise ValueError("Retained SDF count differs from preparation audit.")
            result["arms"][arm] = {"retained_sdf_sha256": ab.digest(folder / "retained.sdf"),
                                   "selected_input_ids": selected_ids[:budget]}
            chosen = [{"input_id": identifier, "molecule": molecule}
                      for identifier, molecule in zip(selected_ids[:budget], molecules[:budget])]
            start = time.monotonic()
            result["arms"][arm]["redocking"] = ab.dock_arm(common, folder, chosen, seeds, tools)
            result["arms"][arm]["docking_seconds"] = time.monotonic() - start
            ab.dump(output / "summary.json", result)
        rows = [dict(arm=arm, **record) for arm, value in result["arms"].items() for record in value["redocking"]]
        with (output / "comparison.csv").open("w", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
        result["status"] = "completed"
        ab.dump(output / "summary.json", result)
        print(f"Docking comparison: {output / 'comparison.csv'}")
    except BaseException as error:
        result.update(status="failed", error=str(error))
        ab.dump(output / "summary.json", result)
        raise


if __name__ == "__main__":
    main()
