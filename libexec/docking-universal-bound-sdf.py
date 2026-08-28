#!/usr/bin/env python
"""Create a typed experimental-coordinate SDF from a confirmed PDB ligand.

PDB coordinates do not authoritatively encode bond orders or protonation. The
default path uses coordinate-free isomeric SMILES from RCSB CCD metadata; an
optional user SDF can override that identity. An explicit, audited PDB-based
bond-perception fallback is available for unpublished structures, but is
provisional and must be reviewed before docking. Only the selected PDB residue
supplies experimental coordinates.
"""

import argparse
import collections
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def fetch_bytes(url):
    request = urllib.request.Request(url, headers={"User-Agent": "Docking-Universal/0.2"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def element_counts(molecule):
    return dict(sorted(collections.Counter(
        atom.GetSymbol() for atom in molecule.GetAtoms() if atom.GetAtomicNum() > 1
    ).items()))


def read_first_sdf(path):
    from rdkit import Chem

    return next((mol for mol in Chem.SDMolSupplier(str(path), removeHs=False) if mol), None)


def main():
    """Extract one exact PDB ligand residue and write a typed reference SDF."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ligand-pdb", required=True, type=Path)
    parser.add_argument("--ligand-id", required=True, help="Exact RESNAME:CHAIN:RESNUM identifier")
    parser.add_argument("--out", required=True, type=Path, help="Experimental-coordinate SDF output")
    parser.add_argument("--template-sdf", type=Path, help="Optional user-supplied chemistry template")
    parser.add_argument("--infer-from-pdb", action="store_true", help="provisionally infer bonds from PDB geometry; requires --force")
    parser.add_argument("--force", action="store_true", help="Allow unverified/inferred chemistry")
    parser.add_argument("--override-reason", default="", help="Required explanation when --force is used")
    parser.add_argument("--obabel", default="obabel")
    args = parser.parse_args()

    if args.force and not args.override_reason.strip():
        parser.error("--override-reason is required with --force")
    if args.infer_from_pdb and not args.force:
        parser.error("--infer-from-pdb requires --force and --override-reason")
    if args.infer_from_pdb and args.template_sdf:
        parser.error("--infer-from-pdb cannot be combined with --template-sdf")
    ligand_pdb = args.ligand_pdb.expanduser().resolve()
    if not ligand_pdb.is_file():
        parser.error(f"ligand PDB does not exist: {ligand_pdb}")

    parts = args.ligand_id.split(":")
    if len(parts) != 3 or not all(parts):
        parser.error("--ligand-id must be RESNAME:CHAIN:RESNUM")
    resname, _chain, _residue_number = parts
    resname = resname.upper()

    output = args.out.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    manifest_path = output.with_suffix(".manifest.json")
    template_copy = output.parent / f"{resname}_user_chemistry.sdf"
    metadata_path = output.parent / f"{resname}_ccd_metadata.json"

    manifest = {
        "ligand_id": args.ligand_id,
        "source_coordinates": str(ligand_pdb),
        "output_sdf": str(output),
        "forced_override": args.force,
        "provisional_pdb_inference": args.infer_from_pdb,
        "override_reason": args.override_reason or None,
        "checks": {},
    }

    template_source = None
    if args.template_sdf:
        supplied = args.template_sdf.expanduser().resolve()
        if not supplied.is_file():
            parser.error(f"template SDF does not exist: {supplied}")
        shutil.copy2(supplied, template_copy)
        template_source = f"user:{supplied}"

    metadata = None
    ccd_smiles = None
    metadata_url = f"https://data.rcsb.org/rest/v1/core/chemcomp/{resname}"
    try:
        metadata = json.loads(fetch_bytes(metadata_url).decode("utf-8"))
        metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
        chem_comp = metadata.get("chem_comp", {})
        descriptors = metadata.get("rcsb_chem_comp_descriptor", {})
        ccd_smiles = descriptors.get("SMILES_stereo") or descriptors.get("SMILES")
        component_type = str(chem_comp.get("type", "unknown"))
        manifest["ccd"] = {
            "id": chem_comp.get("id", resname),
            "name": chem_comp.get("name"),
            "formula": chem_comp.get("formula"),
            "type": component_type,
            "metadata_url": metadata_url,
            "isomeric_smiles": ccd_smiles,
            "inchikey": descriptors.get("InChIKey"),
        }
        manifest["coordinate_policy"] = "CCD coordinates not requested; chemical identity only"
        manifest["checks"]["ccd_smiles_available"] = bool(ccd_smiles)
        nonpolymer = "NON-POLYMER" in component_type.upper()
        manifest["checks"]["ccd_nonpolymer"] = nonpolymer
        if not nonpolymer and not args.force:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            raise SystemExit(
                f"CCD classifies {resname} as '{component_type}', not a non-polymer; use --force with a reason to override"
            )
    except urllib.error.HTTPError as exc:
        manifest["checks"]["ccd_metadata"] = f"unavailable: HTTP {exc.code}"
    except urllib.error.URLError as exc:
        manifest["checks"]["ccd_metadata"] = f"unavailable: {exc.reason}"

    from rdkit import Chem
    from rdkit.Chem import AllChem

    crystal_raw = Chem.MolFromPDBFile(str(ligand_pdb), removeHs=True, sanitize=False)
    if crystal_raw is None:
        raise SystemExit("RDKit could not read the bound-ligand PDB coordinates")
    crystal_elements = element_counts(crystal_raw)
    manifest["checks"]["experimental_heavy_atoms"] = crystal_raw.GetNumHeavyAtoms()
    manifest["checks"]["experimental_elements"] = crystal_elements

    typed_crystal = None
    template = None
    if template_source and template_copy.is_file():
        template_full = read_first_sdf(template_copy)
        if template_full is not None:
            template = Chem.RemoveHs(template_full)
    elif ccd_smiles and not args.infer_from_pdb:
        template = Chem.MolFromSmiles(ccd_smiles)
        template_source = metadata_url

    if template is not None:
        template_elements = element_counts(template)
        element_match = template_elements == crystal_elements
        manifest["chemistry_source"] = template_source
        manifest["checks"]["chemistry_heavy_atoms"] = template.GetNumHeavyAtoms()
        manifest["checks"]["chemistry_elements"] = template_elements
        manifest["checks"]["element_inventory_match"] = element_match
        if not element_match and not args.force:
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
            raise SystemExit(
                "bound coordinates and chemistry identity have different heavy-atom element inventories; "
                f"see {manifest_path}"
            )
        if element_match:
            try:
                typed_crystal = AllChem.AssignBondOrdersFromTemplate(template, crystal_raw)
                Chem.SanitizeMol(typed_crystal)
                manifest["checks"]["bond_order_mapping"] = "passed"
            except Exception as exc:
                manifest["checks"]["bond_order_mapping"] = f"failed: {exc}"

    if typed_crystal is not None:
        typed_crystal.SetProp("_Name", f"{resname}_experimental")
        typed_crystal.SetProp("DockingUniversal_LigandID", args.ligand_id)
        typed_crystal.SetProp("DockingUniversal_ChemistrySource", template_source)
        writer = Chem.SDWriter(str(output))
        writer.write(typed_crystal)
        writer.close()
        manifest["chemistry_status"] = "verified_coordinate_free_identity_mapping"
    elif args.infer_from_pdb or args.force:
        obabel = shutil.which(args.obabel) if Path(args.obabel).name == args.obabel else args.obabel
        if not obabel or not Path(obabel).is_file():
            raise SystemExit("forced chemistry inference requires Open Babel")
        result = subprocess.run([str(obabel), str(ligand_pdb), "-O", str(output)], capture_output=True, text=True)
        manifest["openbabel"] = {"returncode": result.returncode, "stderr": result.stderr.strip()}
        if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
            raise SystemExit("Open Babel could not create the forced/inferred SDF")
        manifest["chemistry_status"] = (
            "provisional_openbabel_pdb_inference" if args.infer_from_pdb
            else "forced_openbabel_inference"
        )
        manifest["review_requirement"] = (
            "2D depiction must be reviewed and explicitly confirmed before docking"
            if args.infer_from_pdb else "manual override recorded"
        )
    else:
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
        raise SystemExit(
            "verified chemistry mapping failed; provide a user chemistry SDF or use --force with --override-reason"
        )

    manifest["status"] = "succeeded"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Created {output}")
    print(f"Chemistry status: {manifest['chemistry_status']}")
    print("Coordinate policy: chemistry graph only; CCD coordinates were not requested or used")
    print("Experimental PDB coordinates are retained only in the RMSD reference SDF")
    print(f"Manifest: {manifest_path}")


if __name__ == "__main__":
    main()
