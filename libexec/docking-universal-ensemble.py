#!/usr/bin/env python
"""Generate an independent pH-aware ligand conformer ensemble from SDF chemistry.

Input 3D coordinates are discarded deliberately. MolScrub enumerates chemical
states and RDKit ETKDG plus MMFF/UFF generates deterministic minimized starting
conformers, preventing a crystal pose from seeding its own redocking control.
"""

import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path


def first_molecule(path):
    from rdkit import Chem
    return next((m for m in Chem.SDMolSupplier(str(path), removeHs=False) if m), None)


def main():
    """Generate and record pH-aware ligand states and independent conformers."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template_sdf", type=Path, help="Authoritative bond-order/stereo template")
    parser.add_argument("--out", required=True, type=Path, help="Independent ensemble SDF")
    ph = parser.add_mutually_exclusive_group()
    ph.add_argument("--ph", type=float, default=7.4)
    ph.add_argument("--ph-range", nargs=2, type=float, metavar=("LOW", "HIGH"))
    parser.add_argument("--conformers", type=int, default=10, help="Conformers retained per chemical state")
    parser.add_argument("--seed", type=int, default=20260808)
    parser.add_argument("--forcefield", choices=("mmff94", "mmff94s", "uff"), default="mmff94")
    parser.add_argument("--rmsd-prune", type=float, default=0.75)
    parser.add_argument("--scrub-command", default="scrub.py")
    parser.add_argument("--skip-tautomers", action="store_true")
    args = parser.parse_args()

    if args.conformers < 1:
        parser.error("--conformers must be positive")
    source = args.template_sdf.expanduser().resolve()
    if not source.is_file():
        parser.error(f"template SDF not found: {source}")
    scrub = shutil.which(args.scrub_command) if Path(args.scrub_command).name == args.scrub_command else args.scrub_command
    if not scrub or not Path(scrub).is_file():
        parser.error(f"MolScrub command not found: {args.scrub_command}")

    from rdkit import Chem
    from rdkit.Chem import AllChem

    template = first_molecule(source)
    if template is None:
        raise SystemExit("RDKit could not read the chemistry template")
    parent_name = template.GetProp("_Name").strip() if template.HasProp("_Name") else source.stem
    # Preserve a stable parent-level heavy-atom identity through state and
    # conformer generation.  Atom-map numbers are metadata for RMSD matching;
    # they do not alter the chemical graph or docking input.
    parent_heavy = 0
    for atom in template.GetAtoms():
        if atom.GetAtomicNum() > 1:
            parent_heavy += 1
            atom.SetAtomMapNum(parent_heavy)
    # SMILES deliberately discards all input coordinates. The crystal pose must
    # never seed an unbiased redocking-control ensemble.
    smiles = Chem.MolToSmiles(Chem.RemoveHs(template), isomericSmiles=True)
    output = args.out.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="docking-universal-ensemble-") as tmp:
        states_path = Path(tmp) / "chemical_states.sdf"
        command = [str(scrub), smiles, "-o", str(states_path), "--skip_gen3d", "--cpu", "1"]
        if args.ph_range:
            command += ["--ph_low", str(args.ph_range[0]), "--ph_high", str(args.ph_range[1])]
        else:
            command += ["--ph", str(args.ph)]
        if args.skip_tautomers:
            command.append("--skip_tautomers")
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode != 0 or not states_path.is_file():
            raise SystemExit(f"MolScrub chemical-state enumeration failed: {result.stderr or result.stdout}")
        states = [m for m in Chem.SDMolSupplier(str(states_path), removeHs=False) if m]

    if not states:
        raise SystemExit("MolScrub produced no readable chemical states")

    writer = Chem.SDWriter(str(output))
    records = []
    for state_index, state in enumerate(states, start=1):
        state = Chem.AddHs(Chem.RemoveHs(state))
        # MolScrub generally preserves atom order; restore the parent map by
        # heavy-atom order and fail loudly if the heavy-atom scaffold changed.
        heavy = [atom for atom in state.GetAtoms() if atom.GetAtomicNum() > 1]
        if len(heavy) != parent_heavy:
            raise SystemExit(f"chemical state {state_index} changed heavy-atom count ({len(heavy)} vs {parent_heavy}); cannot establish RMSD mapping")
        for atom, map_num in zip(heavy, range(1, parent_heavy + 1)):
            atom.SetAtomMapNum(map_num)
        params = AllChem.ETKDGv3()
        params.randomSeed = args.seed + state_index - 1
        params.pruneRmsThresh = args.rmsd_prune
        params.useRandomCoords = True
        requested = max(args.conformers * 4, args.conformers)
        conformer_ids = list(AllChem.EmbedMultipleConfs(state, numConfs=requested, params=params))
        if not conformer_ids:
            raise SystemExit(f"ETKDG produced no conformers for chemical state {state_index}")
        if args.forcefield.startswith("mmff") and AllChem.MMFFHasAllMoleculeParams(state):
            variant = "MMFF94s" if args.forcefield == "mmff94s" else "MMFF94"
            optimized = AllChem.MMFFOptimizeMoleculeConfs(state, mmffVariant=variant, maxIters=1000)
        else:
            optimized = AllChem.UFFOptimizeMoleculeConfs(state, maxIters=1000)
        ranked = sorted(zip(conformer_ids, optimized), key=lambda item: (item[1][0], item[1][1]))
        for rank, (conformer_id, (not_converged, energy)) in enumerate(ranked[: args.conformers], start=1):
            molecule = Chem.Mol(state)
            selected = Chem.Conformer(state.GetConformer(conformer_id))
            molecule.RemoveAllConformers()
            molecule.AddConformer(selected, assignId=True)
            name = f"{parent_name}__state{state_index:02d}__conf{rank:02d}"
            molecule.SetProp("_Name", name)
            molecule.SetProp("DockingUniversal_Parent", parent_name)
            molecule.SetIntProp("DockingUniversal_State", state_index)
            molecule.SetIntProp("DockingUniversal_Conformer", rank)
            molecule.SetIntProp("DockingUniversal_FormalCharge", Chem.GetFormalCharge(molecule))
            molecule.SetDoubleProp("DockingUniversal_ConformerEnergy", float(energy))
            molecule.SetProp("DockingUniversal_ForceField", args.forcefield)
            writer.write(molecule)
            records.append({
                "name": name,
                "state": state_index,
                "conformer": rank,
                "formal_charge": Chem.GetFormalCharge(molecule),
                "energy": float(energy),
                "optimization_converged": not bool(not_converged),
                "heavy_atom_map": "parent_order_1_based",
            })
    writer.close()

    manifest = {
        "status": "succeeded",
        "coordinate_policy": "independent_from_template_coordinates",
        "template_sdf": str(source),
        "canonical_isomeric_smiles": smiles,
        "ph": None if args.ph_range else args.ph,
        "ph_range": args.ph_range,
        "tautomers_enumerated": not args.skip_tautomers,
        "conformers_requested_per_state": args.conformers,
        "chemical_state_count": len(states),
        "output_record_count": len(records),
        "seed": args.seed,
        "forcefield": args.forcefield,
        "rmsd_prune_angstrom": args.rmsd_prune,
        "records": records,
    }
    manifest_path = output.with_suffix(".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Generated {len(records)} independent conformers across {len(states)} chemical states")
    print(f"Ensemble: {output}")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
