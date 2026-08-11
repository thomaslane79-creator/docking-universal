#!/usr/bin/env python
"""Guide a complete Docking Universal study from input choice to final report.

This orchestration layer does not replace the composable scientific commands.
It selects and records one of three honest workflow states:

* bound-control: retrospective pose-recovery calibration;
* approved-screen: unknown docking with a target-locked approved protocol;
* exploratory: ligand-free or otherwise uncalibrated docking, explicitly marked
  as exploratory and never promoted to approved by this command.

The command accepts one SDF, a multi-record SDF, or a directory of SDF files.
Every compound receives a stable folder, independent ensemble, replicated
docking, clustering, representative analysis, and report entry.
"""

import argparse
import csv
import hashlib
import html
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


STATUSES = {
    "control": "CONTROL_WORKFLOW",
    "screen": "CONTROL_APPROVED",
    "exploratory": "EXPLORATORY_NO_CONTROL",
}

COMMON_ADDITIVES = {"HOH", "WAT", "EDO", "GOL", "PEG", "MPD", "DMS", "IPA", "EOH", "ACT", "ACE", "SO4", "PO4"}
COMMON_IONS = {"ZN", "MG", "MN", "CA", "FE", "CU", "NA", "K", "CL"}


def run(command, cwd=None):
    print("+ " + " ".join(map(str, command)), flush=True)
    subprocess.run([str(value) for value in command], cwd=cwd, check=True)


def safe_id(value, fallback="compound"):
    identifier = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-")
    return identifier or fallback


def read_key_value_tsv(path):
    """Read the two-column run manifests written by shell workflow stages."""
    values = {}
    try:
        with Path(path).open(newline="") as handle:
            for row in csv.reader(handle, delimiter="\t"):
                if len(row) >= 2:
                    values[row[0]] = row[1]
    except OSError:
        pass
    return values


def finalized_control_name(complex_path, ligand_id, timestamp):
    """Build a readable, sortable default control-study folder name."""
    protein = safe_id(Path(complex_path).stem, "protein")
    ligand = safe_id(str(ligand_id).split(":", 1)[0], "ligand")
    return f"control_{protein}_{ligand}_{timestamp}"


def relocate_study(study, destination):
    """Rename a completed study and repair retained absolute text paths."""
    study_input = Path(study).absolute()
    destination_input = Path(destination).absolute()
    study = study_input.resolve()
    destination = destination_input.resolve()
    if destination.exists():
        raise SystemExit(f"Final control-study folder already exists: {destination}")
    study.rename(destination)
    path_replacements = {
        str(study_input): str(destination_input),
        str(study): str(destination),
    }
    text_suffixes = {
        ".json", ".tsv", ".csv", ".md", ".html", ".txt", ".log",
        ".pml", ".conf", ".yaml", ".yml",
    }
    for path in destination.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        try:
            content = path.read_text()
        except (OSError, UnicodeDecodeError):
            continue
        updated = content
        for old_text, new_text in path_replacements.items():
            updated = updated.replace(old_text, new_text)
        if updated != content:
            path.write_text(updated)
    return destination


def choose_mode():
    print("Choose a study pathway:")
    print("  1) Bound-ligand control — calibrate against an experimental pose")
    print("  2) Approved-protocol screen — dock unknown compounds reproducibly")
    print("  3) Exploratory ligand-free docking — no pose-recovery control available")
    choice = input("Select [1]: ").strip() or "1"
    return {"1": "control", "2": "screen", "3": "exploratory"}.get(choice)


def explain_workflow(mode):
    explanations = {
        "control": (
            "BOUND-LIGAND CONTROL", "Find a relevant experimental ligand, use it to define the site, "
            "then test whether independently generated conformers recover the withheld pose."
        ),
        "screen": (
            "APPROVED-PROTOCOL BATCH", "Verify the target-locked control protocol, prepare every supplied "
            "compound independently, dock across recorded seeds, cluster poses, and summarize results."
        ),
        "exploratory": (
            "LIGAND-FREE EXPLORATION", "Prepare the rigid receptor, discover and review protein cavities, "
            "then dock compounds without claiming target-specific pose-recovery approval."
        ),
    }
    title, purpose = explanations[mode]
    print(f"\n=== {title} ===")
    print(f"Purpose: {purpose}")
    print("Scientific model: rigid receptor; ligand torsions/conformers may be sampled.")
    print("Progress messages summarize decisions; detailed external-tool output is retained in logs.\n")


def choose_ensemble_settings(args, mode):
    """Expose ligand-state/conformer settings without low-level commands."""
    if mode == "screen":
        print("Ligand ensemble settings will be read from the approved protocol and cannot be changed for this screen.\n")
        return
    print("Ligand ensemble configuration:")
    print("  1) Recommended defaults - tier/default conformer count, pH 7.4, base seed 20260808,")
    print("     MMFF94 with UFF fallback, 0.75 A pruning, tautomer enumeration, Gasteiger charges")
    print("  2) Custom - review and set every ligand-ensemble option")
    choice = input("Select [1]: ").strip() or "1"
    if choice == "1":
        return
    if choice != "2":
        raise SystemExit("Choose ligand ensemble configuration 1 or 2")

    def number(prompt, current, cast, minimum=None):
        raw = input(f"{prompt} [{current}]: ").strip()
        try:
            value = current if not raw else cast(raw)
        except ValueError:
            raise SystemExit(f"{prompt} must be numeric") from None
        if minimum is not None and value < minimum:
            raise SystemExit(f"{prompt} must be at least {minimum}")
        return value

    args.ph = number("Ligand-state pH", args.ph, float, 0.0)
    args.conformers = number("Conformers retained per chemical state", args.conformers, int, 1)
    if mode == "control":
        args.conformers_override = args.conformers
        print("This overrides the conformer count in the calibration tier; seeds and search depth remain tier-controlled.")
    args.base_seed = number("Deterministic base seed", args.base_seed, int, 0)
    print("Force field: 1) MMFF94 (recommended)  2) MMFF94s  3) UFF")
    args.forcefield = {"1": "mmff94", "2": "mmff94s", "3": "uff"}.get(input("Select [1]: ").strip() or "1")
    if not args.forcefield:
        raise SystemExit("Choose force field 1, 2, or 3")
    args.rmsd_prune = number("Conformer RMSD pruning threshold in Angstroms", args.rmsd_prune, float, 0.0)
    args.skip_tautomers = input("Enumerate plausible tautomers? [Y/n]: ").strip().lower() in {"n", "no"}
    args.charge_model = input(f"Ligand charge model [{args.charge_model}]: ").strip() or args.charge_model
    if mode == "exploratory":
        args.seeds = number("Independent docking seeds", args.seeds, int, 1)
    print(
        f"Selected ensemble: pH {args.ph}; {args.conformers} conformers/state; {args.forcefield}; "
        f"RMSD prune {args.rmsd_prune} A; tautomers {'off' if args.skip_tautomers else 'on'}; "
        f"base seed {args.base_seed}; charge model {args.charge_model}.\n"
    )


def choose_file_with_finder():
    """Open the native macOS file chooser and return its POSIX path."""
    if platform.system() != "Darwin" or not shutil.which("osascript"):
        raise SystemExit("Finder selection is available only in a local macOS session; use the manual-path option instead")
    script = (
        'POSIX path of (choose file with prompt "Choose the experimental-complex PDB file" '
        'of type {"org.wwpdb.pdb", "public.data"})'
    )
    result = subprocess.run(
        ["osascript", "-e", script], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        if "User canceled" in result.stderr or "-128" in result.stderr:
            raise SystemExit("Finder selection cancelled")
        raise SystemExit(f"Finder could not select a file: {result.stderr.strip()}")
    selected = Path(result.stdout.strip()).expanduser().resolve()
    if not selected.is_file():
        raise SystemExit(f"Finder selection is not a readable file: {selected}")
    return selected


def choose_sdf_with_finder():
    """Open the native macOS file chooser for one SDF ligand file."""
    if platform.system() != "Darwin" or not shutil.which("osascript"):
        raise SystemExit(
            "Finder selection is available only in a local macOS session."
        )

    script = (
        'POSIX path of (choose file '
        'with prompt "Choose the compound SDF file")'
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        text=True,
        capture_output=True,
        check=False,
    )

    if result.returncode != 0:
        if "User canceled" in result.stderr or "-128" in result.stderr:
            raise SystemExit("Finder selection cancelled")
        raise SystemExit(
            f"Finder could not select an SDF file: {result.stderr.strip()}"
        )

    selected = Path(result.stdout.strip()).expanduser().resolve()
    if not selected.is_file():
        raise SystemExit(f"Finder selection is not a readable file: {selected}")
    if selected.suffix.lower() != ".sdf":
        raise SystemExit(f"Selected ligand file must end in .sdf: {selected}")

    print(f"Selected compound SDF: {selected}")
    return selected


def choose_ligand_source():
    """Choose one SDF in Finder or enter a portable file/directory path."""
    finder_available = platform.system() == "Darwin" and bool(shutil.which("osascript"))
    print("Choose the compound input:")
    if finder_available:
        print("  1) Choose an SDF file with Finder")
        print("  2) Enter an exact SDF file path")
        print("  3) Enter an SDF directory path for batch docking")
    else:
        print("  1) Enter an exact SDF file path")
        print("  2) Enter an SDF directory path for batch docking")
    choice = input("Select [1]: ").strip() or "1"
    if finder_available and choice == "1":
        return choose_sdf_with_finder()
    file_choice = "2" if finder_available else "1"
    directory_choice = "3" if finder_available else "2"
    if choice == file_choice:
        value = input("Exact compound SDF path: ").strip()
        if not value:
            raise SystemExit("No compound SDF path entered")
        selected = Path(value).expanduser().resolve()
        if not selected.is_file() or selected.suffix.lower() != ".sdf":
            raise SystemExit(f"Selected ligand input is not a readable SDF file: {selected}")
        return selected
    if choice == directory_choice:
        value = input("Directory containing SDF files: ").strip()
        if not value:
            raise SystemExit("No SDF directory path entered")
        selected = Path(value).expanduser().resolve()
        if not selected.is_dir() or not any(selected.glob("*.sdf")):
            raise SystemExit(f"No readable .sdf files found in directory: {selected}")
        return selected
    valid = "1, 2, or 3" if finder_available else "1 or 2"
    raise SystemExit(f"Invalid compound input selection; choose {valid}")


def choose_path_with_finder(prompt, folder=False):
    """Open a macOS file or folder chooser and return the selected POSIX path."""
    if platform.system() != "Darwin" or not shutil.which("osascript"):
        raise SystemExit("Finder selection is available only in a local macOS session")
    chooser = "choose folder" if folder else "choose file"
    script = f'POSIX path of ({chooser} with prompt "{prompt}")'
    result = subprocess.run(
        ["osascript", "-e", script], text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        if "User canceled" in result.stderr or "-128" in result.stderr:
            raise SystemExit("Finder selection cancelled")
        raise SystemExit(f"Finder could not select the requested input: {result.stderr.strip()}")
    return Path(result.stdout.strip()).expanduser().resolve()


def approved_protocols_under(path):
    """Return approved protocol records beneath a selected control or study folder."""
    path = path.expanduser().resolve()
    candidates = [path] if path.is_file() else sorted(path.glob("**/protocol.json")) if path.is_dir() else []
    return [candidate for candidate in candidates if protocol_allows_screening(candidate)]


def choose_approved_protocol_from(path):
    """Validate or disambiguate approved protocols found at a file/folder selection."""
    protocols = approved_protocols_under(path)
    if not protocols:
        raise SystemExit(
            f"No approved Docking Universal protocol.json was found at: {path}\n"
            "An approved protocol must retain passing sampling, ranking, and independent-seed criteria."
        )
    if len(protocols) == 1:
        selected = protocols[0]
    else:
        print("Approved protocols found:")
        for index, protocol_path in enumerate(protocols, start=1):
            record = read_json(protocol_path) or {}
            parameters = record.get("parameters", {})
            print(
                f"  {index}) {record.get('engine', 'unknown')} / {record.get('calibration_tier', 'unknown')} - "
                f"{len(parameters.get('seeds', []))} seeds, exhaustiveness {parameters.get('exhaustiveness', 'NA')}\n"
                f"     {protocol_path}"
            )
        choice = input("Select approved protocol [1]: ").strip() or "1"
        try:
            selected = protocols[int(choice) - 1]
        except (ValueError, IndexError):
            raise SystemExit(f"Choose an approved protocol from 1 to {len(protocols)}") from None
    print(f"Selected approved protocol: {selected}")
    return selected.resolve()


def choose_approved_protocol():
    """Resume screening from a previously approved target-specific protocol."""
    finder_available = platform.system() == "Darwin" and bool(shutil.which("osascript"))
    print("Resume from an existing approved protocol:")
    if finder_available:
        print("  1) Choose protocol.json with Finder")
        print("  2) Choose its control/study folder with Finder")
        print("  3) Enter an exact protocol.json path")
        print("  4) Enter a control/study folder path and discover approved protocols")
    else:
        print("  1) Enter an exact protocol.json path")
        print("  2) Enter a control/study folder path and discover approved protocols")
    choice = input("Select [1]: ").strip() or "1"
    if finder_available and choice == "1":
        return choose_approved_protocol_from(
            choose_path_with_finder("Choose the approved Docking Universal protocol.json")
        )
    if finder_available and choice == "2":
        return choose_approved_protocol_from(
            choose_path_with_finder("Choose the completed control or study folder", folder=True)
        )
    file_choice = "3" if finder_available else "1"
    folder_choice = "4" if finder_available else "2"
    if choice == file_choice:
        value = input("Exact approved protocol.json path: ").strip()
        if not value:
            raise SystemExit("No protocol path entered")
        return choose_approved_protocol_from(Path(value))
    if choice == folder_choice:
        value = input("Control or study folder path: ").strip()
        if not value:
            raise SystemExit("No control/study folder path entered")
        return choose_approved_protocol_from(Path(value))
    valid = "1, 2, 3, or 4" if finder_available else "1 or 2"
    raise SystemExit(f"Invalid approved-protocol selection; choose {valid}")


def choose_complex_source():
    """Ask explicitly whether the experimental complex is remote or local."""
    print("Choose the experimental-complex source:")
    print("  1) Download a canonical structure from RCSB using its PDB ID")
    if platform.system() == "Darwin":
        print("  2) Choose a local PDB file with Finder")
    else:
        print("  2) Choose a local PDB file (macOS Finder unavailable)")
    print("  3) Enter an exact local PDB path")
    choice = input("Select [1]: ").strip() or "1"
    if choice == "1":
        pdb_id = input("Four-character PDB ID (example: 1HVR): ").strip()
        if not re.fullmatch(r"(?i)[0-9][A-Za-z0-9]{3}", pdb_id):
            raise SystemExit("A PDB ID must contain four characters and begin with a number")
        return Path(pdb_id.upper())
    if choice == "2":
        return choose_file_with_finder()
    if choice == "3":
        local_path = input("Exact local experimental-complex PDB path: ").strip()
        if not local_path:
            raise SystemExit("No local PDB path entered")
        return Path(local_path)
    raise SystemExit("Invalid experimental-complex source selection; choose 1, 2, or 3")


def download_pdb_entry(pdb_id, destination):
    """Download one legacy-format coordinate entry and record its provenance."""
    pdb_id = pdb_id.upper()
    url = f"https://files.rcsb.org/download/{pdb_id}.pdb"
    destination.mkdir(parents=True, exist_ok=True)
    output = destination / f"{pdb_id}.pdb"
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "Docking-Universal/0.4.0"})
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SystemExit(f"Could not download {pdb_id} from RCSB PDB: {exc}") from None
    if not payload or (b"ATOM  " not in payload and b"HETATM" not in payload):
        raise SystemExit(
            f"RCSB did not return a usable legacy PDB coordinate file for {pdb_id}. "
            "Download and convert the PDBx/mmCIF entry manually."
        )
    output.write_bytes(payload)
    provenance = {
        "pdb_id": pdb_id,
        "source": "RCSB Protein Data Bank",
        "url": url,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "file": str(output),
    }
    (destination / f"{pdb_id}_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(f"Downloaded {pdb_id} from RCSB PDB: {output}")
    return output


def validate_complex_pdb(path):
    """Reject a mislabeled or coordinate-free local selection early."""
    if path.suffix.lower() != ".pdb":
        raise SystemExit(f"Selected structure must be a .pdb file: {path}")
    with path.open("rb") as handle:
        sample = handle.read(2 * 1024 * 1024)
    if b"ATOM  " not in sample and b"HETATM" not in sample:
        raise SystemExit(f"Selected PDB contains no ATOM or HETATM coordinate records: {path}")
    return path


def import_local_pdb(path, destination):
    """Copy a selected local input into the study and record its provenance."""
    destination.mkdir(parents=True, exist_ok=True)
    source = path.resolve()
    target = destination / source.name
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    if target.exists() and target.resolve() != source:
        target_hash = hashlib.sha256(target.read_bytes()).hexdigest()
        if target_hash != source_hash:
            suffix = 2
            while (destination / f"{source.stem}_local_{suffix}{source.suffix}").exists():
                suffix += 1
            target = destination / f"{source.stem}_local_{suffix}{source.suffix}"
    if target.resolve() != source:
        shutil.copy2(source, target)
    provenance = {
        "source_type": "local_file",
        "original_path": str(source),
        "imported_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": source_hash,
        "file": str(target.resolve()),
    }
    (destination / f"{target.stem}_provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    print(f"Imported local PDB into study: {target}")
    return target.resolve()


def inspect_pdb_compounds(path, output=None):
    """Inventory every exact HETATM group and explain candidate classification."""
    modified = set()
    groups = {}
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("MODRES"):
            name = line[12:15].strip()
            if name:
                modified.add(name)
        elif line.startswith("HETATM"):
            name = line[17:20].strip() or "UNK"
            chain = line[21:22].strip() or "_"
            residue = line[22:26].strip() or "?"
            key = (name, chain, residue)
            groups[key] = groups.get(key, 0) + 1
    inventory = []
    for (name, chain, residue), count in sorted(groups.items()):
        if name in modified:
            classification, reason = "polymer_modification", "MODRES-declared part of the receptor"
        elif name in COMMON_ADDITIVES:
            classification, reason = "solvent_or_additive", "common solvent/crystallization additive"
        elif name in COMMON_IONS:
            classification, reason = "ion_or_metal", "common ion/metal; not an organic control ligand"
        elif count < 10:
            classification, reason = "small_hetero_group", "fewer than 10 atoms; excluded from automatic ligand candidates"
        else:
            classification, reason = "ligand_candidate", "eligible for user identity and chemistry review"
        inventory.append({
            "id": f"{name}:{chain}:{residue}", "resname": name, "chain": chain,
            "residue_number": residue, "atom_count": count,
            "classification": classification, "reason": reason,
        })
    print("\nPDB compound inventory")
    print("  HETATM records are possible non-protein components; they are not automatically assumed to be ligands.")
    if not inventory:
        print("  No HETATM groups found. A ligand-free cavity search is required.")
    else:
        candidates_list = [item for item in inventory if item["classification"] == "ligand_candidate"]
        print("  Eligible ligand candidates (exact instances):")
        if candidates_list:
            for item in candidates_list:
                print(f"    - {item['id']:<16} {item['atom_count']:>3} atoms  {item['reason']}")
        else:
            print("    - none")
        excluded = {}
        for item in inventory:
            if item["classification"] == "ligand_candidate":
                continue
            key = (item["resname"], item["classification"], item["reason"])
            summary = excluded.setdefault(key, {"instances": 0, "atoms": 0})
            summary["instances"] += 1
            summary["atoms"] += item["atom_count"]
        if excluded:
            print("  Excluded hetero groups (summarized):")
            for (name, classification, reason), summary in sorted(excluded.items()):
                print(
                    f"    - {name:<4} {summary['instances']:>3} instance(s), {summary['atoms']:>4} atoms  "
                    f"{classification}: {reason}"
                )
    candidates = sum(item["classification"] == "ligand_candidate" for item in inventory)
    print(f"  Summary: {len(inventory)} exact hetero groups; {candidates} ligand candidate(s).")
    print("  Candidate status is a screening heuristic. Confirm biological relevance before ligand-centered docking.\n")
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps({"source_pdb": str(path), "groups": inventory}, indent=2) + "\n")
        print(f"  Inventory saved: {output}\n")
    return inventory


def require_complex_path(value, project, destination, non_interactive=False, allow_download=False):
    """Resolve an exact local path or a canonical four-character PDB ID.

    A bare ID never searches generated project files: prepared receptors and
    copied coordinates can share the accession filename but are not equivalent
    to the archived experimental entry required by a control.
    """
    requested_name = value.name
    bare_id_match = re.fullmatch(r"(?i)([0-9][A-Za-z0-9]{3})", requested_name)
    if bare_id_match:
        pdb_id = bare_id_match.group(1).upper()
        cached = destination / f"{pdb_id}.pdb"
        if cached.is_file():
            print(f"Using study-cached RCSB entry: {cached}")
            return cached
        if non_interactive:
            if allow_download:
                return download_pdb_entry(pdb_id, destination)
            raise SystemExit(
                f"PDB ID {pdb_id} is not cached in this study. Add --download-pdb "
                "to authorize an RCSB download, or provide an exact local file path."
            )
        answer = input(f"Download canonical {pdb_id}.pdb from RCSB PDB? [Y/n]: ").strip().lower()
        if answer in {"", "y", "yes"}:
            return download_pdb_entry(pdb_id, destination)
        replacement = input("Exact local experimental-complex PDB path: ").strip()
        if not replacement:
            raise SystemExit("No complex PDB selected")
        replacement_path = Path(replacement).expanduser().resolve()
        if not replacement_path.is_file():
            raise SystemExit(f"Complex PDB not found: {replacement_path}")
        return replacement_path

    candidate = value.expanduser().resolve()
    if candidate.is_file():
        return candidate
    message = [
        f"Complex PDB not found: {candidate}",
        "The local-file option requires an exact path and will not guess among generated PDB copies.",
    ]
    if non_interactive:
        raise SystemExit("\n".join(message))
    print("\n".join(message), file=sys.stderr)
    replacement = input("Enter the exact local experimental-complex PDB path again: ").strip()
    if not replacement:
        raise SystemExit("No complex PDB selected")
    replacement_path = Path(replacement).expanduser().resolve()
    if not replacement_path.is_file():
        raise SystemExit(f"Complex PDB not found: {replacement_path}")
    return replacement_path


def split_compounds(source, destination):
    """Write exactly one typed SDF per compound with collision-safe stable IDs."""
    from rdkit import Chem
    from rdkit.Chem import rdMolDescriptors

    source = source.expanduser().resolve()
    paths = sorted(source.glob("*.sdf")) if source.is_dir() else [source]
    if not paths or any(not path.is_file() for path in paths):
        raise SystemExit(f"No readable SDF input found at {source}")
    destination.mkdir(parents=True, exist_ok=True)
    compounds = []
    used = set()
    for path in paths:
        molecules = [molecule for molecule in Chem.SDMolSupplier(str(path), removeHs=False) if molecule]
        if not molecules:
            raise SystemExit(f"No readable molecules in {path}")
        for index, molecule in enumerate(molecules, start=1):
            raw_name = molecule.GetProp("_Name").strip() if molecule.HasProp("_Name") else ""
            property_name = molecule.GetProp("Name").strip() if molecule.HasProp("Name") else ""
            compound_name = raw_name or property_name
            base = safe_id(
                compound_name
                or (path.stem if len(molecules) == 1 else f"{path.stem}_{index}")
            )
            identifier = base
            suffix = 2
            while identifier.lower() in used:
                identifier = f"{base}_{suffix}"
                suffix += 1
            used.add(identifier.lower())
            output = destination / f"{identifier}.sdf"
            molecule.SetProp("_Name", compound_name or identifier)
            molecule.SetProp("DockingUniversal_CompoundName", compound_name or identifier)
            molecule.SetProp("DockingUniversal_CompoundID", identifier)
            writer = Chem.SDWriter(str(output))
            writer.write(molecule)
            writer.close()
            compounds.append({
                "compound_id": identifier,
                "compound_name": compound_name or identifier,
                "input": str(output),
                "source": str(path),
                "formula": rdMolDescriptors.CalcMolFormula(molecule),
                "formal_charge": Chem.GetFormalCharge(molecule),
                "heavy_atoms": molecule.GetNumHeavyAtoms(),
                "isomeric_smiles": Chem.MolToSmiles(Chem.RemoveHs(molecule), isomericSmiles=True),
            })
    return compounds


def report_compound_library(compounds, output):
    """Show and retain every compound accepted from the supplied SDF input."""
    print("\nCompound library inventory")
    print("  Each readable SDF record is treated as one compound and receives an isolated result folder.")
    for index, compound in enumerate(compounds, start=1):
        smiles = compound["isomeric_smiles"]
        display_smiles = smiles if len(smiles) <= 72 else smiles[:69] + "..."
        print(
            f"  {index}) {compound['compound_name']} [{compound['compound_id']}]\n"
            f"     formula={compound['formula']}  charge={compound['formal_charge']:+d}  "
            f"heavy_atoms={compound['heavy_atoms']}\n"
            f"     SMILES={display_smiles}"
        )
    print(f"  Total compounds accepted: {len(compounds)}\n")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({"compound_count": len(compounds), "compounds": compounds}, indent=2) + "\n")
    print(f"  Inventory saved: {output}\n")


def discover_preparation(root, interactive=True, defer_box_selection=False):
    prep_roots = sorted(root.glob("*_receptor_prep"))
    if len(prep_roots) != 1:
        raise SystemExit(f"Expected one receptor-preparation folder under {root}; found {len(prep_roots)}")
    prep = prep_roots[0]
    receptor_pdbqt = next(iter(sorted((prep / "receptor").glob("*.pdbqt"))), None)
    receptor_pdb = next(iter(sorted((prep / "receptor").glob("*.pdb"))), None)
    boxes = sorted((prep / "cavity").glob("*.conf"))
    if not receptor_pdbqt or not receptor_pdb or not boxes:
        raise SystemExit("Preparation did not produce receptor PDB/PDBQT and a docking box")
    if defer_box_selection:
        return receptor_pdb, receptor_pdbqt, boxes
    if len(boxes) > 1:
        print("Prepared docking boxes:")
        for index, box in enumerate(boxes, start=1):
            print(f"  {index}) {box.name}")
        choice = input("Select box [1]: ").strip() or "1" if interactive else "1"
        box = boxes[int(choice) - 1]
    else:
        box = boxes[0]
    return receptor_pdb, receptor_pdbqt, box


def choose_prepared_box(boxes, interactive=True):
    if len(boxes) == 1:
        return boxes[0]
    print("Prepared docking boxes available after pocket review:")
    for index, box in enumerate(boxes, start=1):
        print(f"  {index}) {box.name}")
    choice = input("Select reviewed pocket/box [1]: ").strip() or "1" if interactive else "1"
    if not choice.isdigit() or not (1 <= int(choice) <= len(boxes)):
        raise SystemExit("Invalid docking-box selection")
    return boxes[int(choice) - 1]


def review_pocket_scene(root, pymol_command, interactive=False, requested=False):
    """Optionally open the prepared cavity scene before exploratory docking."""
    prep_roots = sorted(root.glob("*_receptor_prep"))
    scenes = sorted(prep_roots[0].glob("cavity/*.pml")) if len(prep_roots) == 1 else []
    if not scenes:
        print("Pocket review: no generated PyMOL cavity scene was found.")
        return None
    print("Pocket review scenes:")
    for scene in scenes:
        print(f"  {scene}")
    should_open = requested
    if interactive and not requested:
        answer = input("Open the prepared cavity scene in PyMOL before docking? [y/N]: ").strip().lower()
        should_open = answer in {"y", "yes"}
    if not should_open:
        return None
    executable = shutil.which(pymol_command) or (pymol_command if Path(pymol_command).is_file() else None)
    if not executable:
        message = f"PyMOL was requested for pocket review but was not found: {pymol_command}"
        if requested:
            raise SystemExit(message)
        print(message)
        return None
    scene = scenes[0]
    subprocess.Popen([str(executable), str(scene)], cwd=str(scene.parent))
    print(f"Opened cavity review in PyMOL: {scene}")
    return str(scene)


def read_cluster_rows(compound_dir):
    table = compound_dir / "pose_analysis" / "cluster_summary.csv"
    if not table.is_file():
        return []
    with table.open(newline="") as handle:
        return list(csv.DictReader(handle))

def protocol_allows_screening(protocol_path):
    """Return True only when the protocol explicitly authorizes screening."""
    protocol = read_json(protocol_path)
    if not isinstance(protocol, dict):
        return False

    acceptance = protocol.get("acceptance", {})
    return (
        protocol.get("schema_name") == "docking-universal-protocol"
        and protocol.get("schema_version") == 1
        and protocol.get("control_status") == "approved"
        and protocol.get("unknown_docking_allowed") is True
        and acceptance.get("sampling_pass") is True
        and acceptance.get("ranking_pass") is True
        and acceptance.get("seed_requirement_pass") is True
    )
def read_json(path):
    """Return a JSON object when a retained workflow artifact is available."""
    try:
        return json.loads(path.read_text()) if path.is_file() else None
    except (OSError, json.JSONDecodeError):
        return None


def relative_to_study(path, study):
    """Use readable relative locations in a self-contained study report."""
    try:
        return str(Path(path).resolve().relative_to(study.resolve()))
    except (ValueError, OSError):
        return str(path)


def write_run_details(study, manifest, compounds, report_dir):
    """Consolidate retained run decisions into one human-readable Markdown record."""
    lines = [
        f"# Run details: {manifest['study_name']}", "",
        "This document consolidates the run configuration and retained provenance. "
        "Raw tool output remains in the stage-specific logs and manifests.", "",
        "## Study status", "",
        f"- Workflow: `{manifest['workflow']}`",
        f"- Scientific status: `{manifest['study_status']}`",
        f"- Completion status: `{manifest.get('completion_status', 'UNKNOWN')}`",
        f"- Created: `{manifest.get('created_utc', 'unknown')}`", "",
        "## Scientific model", "",
        "- Rigid receptor: receptor coordinates are fixed during docking.",
        "- Ligands: chemical states/conformers are prepared independently; input 3D coordinates are not used to seed the default ensemble.",
        "- Scores: ranking outputs, not measured binding free energies.",
    ]
    if manifest["study_status"] == "EXPLORATORY_NO_CONTROL":
        lines += ["- **Warning:** no approved target-specific pose-recovery control was available; poses are exploratory hypotheses."]
    elif manifest["study_status"] == "CONTROL_APPROVED":
        lines += ["- Protocol transfer: only the locked receptor/box and recorded settings were used for screening."]
    lines += ["", "## Input discovery", ""]
    pdb_inventory = read_json(study / "inputs" / "pdb_compound_inventory.json")
    if pdb_inventory:
        lines += [f"PDB inventory: `{relative_to_study(study / 'inputs' / 'pdb_compound_inventory.json', study)}`", ""]
        lines += ["| PDB group | Atoms | Classification | Reason |", "| --- | ---: | --- | --- |"]
        for item in pdb_inventory.get("groups", []):
            lines.append(f"| {item['id']} | {item['atom_count']} | {item['classification']} | {item['reason']} |")
    else:
        lines += ["No raw-PDB compound inventory was needed because prepared receptor/box inputs were supplied."]
    library_inventory = read_json(study / "inputs" / "compound_library_inventory.json")
    if library_inventory:
        lines += ["", "Compound-library inventory: `inputs/compound_library_inventory.json`", ""]
        lines += ["| Compound | Formula | Charge | Heavy atoms | Isomeric SMILES |", "| --- | --- | ---: | ---: | --- |"]
        for item in library_inventory.get("compounds", []):
            lines.append(
                f"| {item['compound_name']} (`{item['compound_id']}`) | {item['formula']} | "
                f"{item['formal_charge']:+d} | {item['heavy_atoms']} | `{item['isomeric_smiles']}` |"
            )
    lines += ["", "## Run configuration", ""]
    lines += [
        f"- Pose analysis: `{manifest.get('analysis', 'control-specific')}`",
        f"- Representative clusters requested: `{manifest.get('representatives', 'control-specific')}`",
        f"- Clustering cutoff: `{manifest.get('cluster_rmsd_angstrom', 'control-specific')}` Å",
    ]
    for compound in compounds:
        compound_dir = study / "compounds" / compound["compound_id"]
        screen_manifest = read_json(compound_dir / "screen_manifest.json")
        failure = read_json(compound_dir / "failure.json")
        lines += ["", f"### {compound['compound_name']} (`{compound['compound_id']}`)", ""]
        if screen_manifest:
            lines += [
                f"- Workflow: `{screen_manifest.get('workflow')}`",
                f"- Engine: `{screen_manifest.get('engine')}`",
                f"- Independent seeds: `{', '.join(map(str, screen_manifest.get('seeds', [])))}`",
                f"- Planned docking jobs: `{screen_manifest.get('docking_job_count')}`",
                f"- Ligand input: `{relative_to_study(screen_manifest.get('ligand', ''), study)}`",
                f"- Receptor: `{relative_to_study(screen_manifest.get('receptor', ''), study)}`",
                f"- Box: `{relative_to_study(screen_manifest.get('box', ''), study)}`",
            ]
            if screen_manifest.get("protocol"):
                lines.append(f"- Protocol: `{screen_manifest['protocol']}`")
        elif failure:
            lines += [f"- **Failed:** return code `{failure.get('return_code', 'unknown')}`", f"- Detail: {failure.get('message', '')}"]
        else:
            lines += ["- Status: planned or incomplete; no compound execution manifest is available yet."]
    control_manifest = study / "control" / "run_manifest.tsv"
    if control_manifest.is_file():
        lines += ["", "## Bound-ligand control record", "", f"- Control manifest: `{relative_to_study(control_manifest, study)}`"]
        for line in control_manifest.read_text(errors="replace").splitlines():
            key, separator, value = line.partition("\t")
            if separator and key:
                lines.append(f"- {key.replace('_', ' ')}: `{value}`")
        protocols = sorted((study / "control").glob("**/protocol.json"))
        if protocols:
            lines += ["", "### Calibration protocols", ""]
            for protocol_path in protocols:
                protocol = read_json(protocol_path) or {}
                lines.append(
                    f"- `{relative_to_study(protocol_path, study)}` — tier `{protocol.get('calibration_tier', 'unknown')}`, "
                    f"approved `{protocol.get('unknown_docking_allowed', False)}`, "
                    f"strategy `{protocol.get('calibration_strategy', 'not recorded')}`"
                )
    lines += [
        "", "## Output map", "",
        "- `inputs/`: immutable imported/downloaded structures plus inventory records.",
        "- `compounds/`: per-compound preparation, seed runs, scores, clustering, visualizations, and interaction files.",
        "- `report/compound_summary.csv`: compact result table.",
        "- `report/study_summary.json`: machine-readable study summary.",
        "- `report/study_report.md`: readable result summary.",
        "- Stage-specific `run_manifest.tsv`, JSON manifests, and log files retain detailed executable provenance.",
    ]
    output = report_dir / "run_details.md"
    output.write_text("\n".join(lines) + "\n")
    return output


def write_reports(study, manifest, compounds):
    """Write machine-readable and human-readable summaries from retained files."""
    rows = []
    for compound in compounds:
        compound_dir = study / "compounds" / compound["compound_id"]
        screen_manifest = compound_dir / "screen_manifest.json"
        clusters = read_cluster_rows(compound_dir)
        selected = [row for row in clusters if row.get("selected") == "yes"]
        failure = compound_dir / "failure.json"
        if compound.get("run_status"):
            status = compound["run_status"]
        elif screen_manifest.is_file():
            status = "COMPLETED"
        elif failure.is_file():
            status = "FAILED"
        else:
            status = "INCOMPLETE"
        warning = "" if manifest["study_status"] == "CONTROL_APPROVED" else "No approved target-specific pose-recovery control"
        rows.append({
            "compound_id": compound["compound_id"], "compound_name": compound["compound_name"],
            "status": status, "cluster_count": len(clusters), "selected_representatives": len(selected),
            "best_cluster_energy_kcal_per_mol": selected[0].get("best_energy_kcal_per_mol", "") if selected else "",
            "best_cluster_seed_support": selected[0].get("seed_support", "") if selected else "",
            "warning": warning,
        })
    report_dir = study / "report"
    report_dir.mkdir(exist_ok=True)
    fields = list(rows[0]) if rows else ["compound_id", "status"]
    with (report_dir / "compound_summary.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    report = {**manifest, "compounds": rows}
    (report_dir / "study_summary.json").write_text(json.dumps(report, indent=2) + "\n")

    lines = [
        f"# Docking Universal study: {manifest['study_name']}", "",
        f"**Scientific status:** `{manifest['study_status']}`", "",
        f"**Completion status:** `{manifest.get('completion_status', 'UNKNOWN')}`", "",
        f"**Workflow:** {manifest['workflow']}", "",
        f"**Compounds:** {len(rows)}", "",
    ]
    if manifest["study_status"] == "EXPLORATORY_NO_CONTROL":
        lines += ["> **Exploratory result:** no approved bound-ligand pose-recovery control was available. Generated poses and scores are hypotheses for structural review.", ""]
    lines += ["## Compound results", "", "| Compound | Status | Clusters | Representatives | Best energy | Seed support |", "| --- | --- | ---: | ---: | ---: | ---: |"]
    for row in rows:
        link = f"../compounds/{row['compound_id']}/pose_analysis/representative_browser.pse"
        display = f"[{row['compound_name']}]({link})" if row["status"] == "COMPLETED" else row["compound_name"]
        lines.append(
            f"| {display} | {row['status']} | {row['cluster_count']} | "
            f"{row['selected_representatives']} | {row['best_cluster_energy_kcal_per_mol'] or 'NA'} | "
            f"{row['best_cluster_seed_support'] or 'NA'} |"
        )
    lines += ["", "## Interpretation", "", "Docking scores are ranking outputs, not measured binding free energies. Cluster and seed support describe convergence of the configured search. They do not establish biological activity or prospective pose correctness.", ""]
    markdown = "\n".join(lines)
    (report_dir / "study_report.md").write_text(markdown)
    html_rows = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(row[field]))}</td>" for field in fields) + "</tr>" for row in rows
    )
    warning_html = "<p><strong>Exploratory:</strong> no approved target-specific pose-recovery control was available.</p>" if manifest["study_status"] == "EXPLORATORY_NO_CONTROL" else ""
    document = f"""<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width\"><title>{html.escape(manifest['study_name'])}</title><style>body{{font:16px system-ui;max-width:1100px;margin:3rem auto;padding:0 1rem;color:#18202a}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ccd3da;padding:.55rem;text-align:left}}th{{background:#eef3f6}}code{{background:#eef3f6;padding:.15rem .3rem}}.note{{border-left:4px solid #b87900;padding:.8rem;background:#fff6df}}</style></head><body><h1>{html.escape(manifest['study_name'])}</h1><p>Scientific status: <code>{manifest['study_status']}</code><br>Completion status: <code>{manifest.get('completion_status', 'UNKNOWN')}</code></p><div class=\"note\">{warning_html or 'Target-specific protocol gate passed. This remains computational evidence, not experimental validation.'}</div><h2>Compound summary</h2><table><thead><tr>{''.join(f'<th>{html.escape(field)}</th>' for field in fields)}</tr></thead><tbody>{html_rows}</tbody></table><h2>Scientific limits</h2><p>Scores are ranking outputs. Pose clustering and seed support describe search convergence and require structural and experimental interpretation.</p></body></html>"""
    (report_dir / "index.html").write_text(document)
    write_run_details(study, manifest, compounds, report_dir)
    # PDF is a presentation artifact; keep it optional so core report generation
    # remains usable in minimal/headless installations, but never hide its status.
    pdf_script = Path(__file__).with_name("docking-universal-pdf-report.py")
    pdf_path = report_dir / "study_report.pdf"
    temporary_pdf = report_dir / ".study_report.building.pdf"
    try:
        result = subprocess.run(
            [sys.executable, str(pdf_script), str(study), "--out", str(temporary_pdf)],
            check=True, capture_output=True, text=True,
        )
        if temporary_pdf.is_file():
            temporary_pdf.replace(pdf_path)
            print(f"PDF report: {pdf_path}")
        else:
            print(
                "WARNING: PDF generation returned successfully but study_report.pdf was not found. "
                f"Generator output: {result.stdout.strip()}", file=sys.stderr,
            )
    except subprocess.CalledProcessError as exc:
        temporary_pdf.unlink(missing_ok=True)
        detail = exc.stderr.strip() or exc.stdout.strip() or f"exit status {exc.returncode}"
        print(f"WARNING: PDF report could not be generated: {detail}", file=sys.stderr)
    except FileNotFoundError as exc:
        temporary_pdf.unlink(missing_ok=True)
        print(f"WARNING: PDF report could not be generated: {exc}", file=sys.stderr)
    return report_dir


def parse_args():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--mode", choices=("control", "screen", "exploratory"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--name", help="study name")
    parser.add_argument("--complex", type=Path, help="raw bound complex or protein PDB")
    parser.add_argument("--download-pdb", action="store_true", help="allow non-interactive RCSB download when --complex is a four-character PDB ID")
    parser.add_argument("--protocol", type=Path)
    parser.add_argument("--ligands", type=Path, help="single/multi-record SDF or directory of SDF files")
    parser.add_argument("--receptor-pdb", type=Path)
    parser.add_argument("--receptor-pdbqt", type=Path)
    parser.add_argument("--box", type=Path)
    parser.add_argument("--engine", choices=("vina", "smina"), default="vina")
    parser.add_argument("--control-tier", choices=("quick", "repeatability", "broader", "conformers", "robust"), default="quick")
    parser.add_argument("--seeds", type=int, default=5, help="exploratory independent seeds (default: 5)")
    parser.add_argument("--conformers", type=int, default=3, help="exploratory conformers per state (default: 3)")
    parser.add_argument("--conformers-override", type=int, help="control conformers per state; overrides the selected tier")
    parser.add_argument("--exhaustiveness", type=int, default=16, help="exploratory search effort (default: 16)")
    parser.add_argument("--num-modes", type=int, default=20)
    parser.add_argument("--energy-range", type=float, default=8.0)
    parser.add_argument("--ph", type=float, default=7.4)
    parser.add_argument("--base-seed", type=int, default=20260808)
    parser.add_argument("--forcefield", choices=("mmff94", "mmff94s", "uff"), default="mmff94")
    parser.add_argument("--rmsd-prune", type=float, default=0.75)
    parser.add_argument("--skip-tautomers", action="store_true")
    parser.add_argument("--charge-model", default="gasteiger")
    parser.add_argument("--analysis", choices=("none", "summary", "representatives"), default="representatives")
    parser.add_argument("--representatives", type=int, default=3)
    parser.add_argument("--cluster-rmsd", type=float, default=2.0)
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--no-visuals", action="store_true")
    parser.add_argument("--review-pockets", action="store_true", help="open the prepared exploratory cavity scene in PyMOL before docking")
    parser.add_argument("--pymol", default="pymol", help="PyMOL executable for --review-pockets")
    parser.add_argument("--cavity-mode", choices=("1", "2", "3"), default="2", help="ligand-free fpocket mode: conservative, expanded, or permissive")
    parser.add_argument("--max-pockets", type=int, default=5, help="maximum ligand-free pockets to retain")
    parser.add_argument("--center-mode", choices=("deepest", "centroid"), default="centroid", help="ligand-free cavity center strategy")
    parser.add_argument("--plan-only", action="store_true", help="validate/split inputs and write a study plan without docking")
    parser.add_argument("--stop-on-error", action="store_true", help="stop the library at the first failed compound")
    return parser.parse_args()


def main():
    args = parse_args()
    project = Path(__file__).resolve().parent.parent
    cli = project / "bin/docking-universal"
    mode = args.mode
    if not mode:
        if args.non_interactive:
            raise SystemExit("--mode is required with --non-interactive")
        mode = choose_mode()
        if not mode:
            raise SystemExit("Invalid workflow selection")
    explain_workflow(mode)
    if not args.non_interactive:
        choose_ensemble_settings(args, mode)
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    if mode == "control" and not args.complex and not args.non_interactive:
        args.complex = choose_complex_source()
    if mode == "screen":
        if not args.protocol:
            if args.non_interactive:
                raise SystemExit("--protocol is required with --mode screen --non-interactive")
            args.protocol = choose_approved_protocol()
        else:
            args.protocol = args.protocol.expanduser().resolve()
            if not protocol_allows_screening(args.protocol):
                raise SystemExit(f"Protocol is not approved for screening: {args.protocol}")
            print(f"Selected approved protocol: {args.protocol}")
        locked_parameters = (read_json(args.protocol) or {}).get("parameters", {})
        print("Locked ligand ensemble from approved protocol:")
        print(f"  pH: {locked_parameters.get('ph', 'NA')}")
        print(f"  Conformers per chemical state: {locked_parameters.get('conformers_per_state', 'NA')}")
        print(f"  Ensemble seed: {locked_parameters.get('ensemble_seed', (locked_parameters.get('seeds') or ['NA'])[0])}")
        print(f"  Force field: {locked_parameters.get('forcefield', 'mmff94')}")
        print(f"  RMSD pruning: {locked_parameters.get('rmsd_prune_angstrom', 0.75)} A")
        print(f"  Tautomers enumerated: {locked_parameters.get('tautomers_enumerated', True)}")
        print(f"  Charge model: {locked_parameters.get('charge_model', 'NA')}")
    study_name = args.name or f"docking_universal_{mode}"
    default_control_output = mode == "control" and args.out is None
    if default_control_output:
        protein_hint = safe_id(Path(args.complex).stem if args.complex else "protein", "protein")
        requested_study = Path(f"control_pending_{protein_hint}_{run_timestamp}").resolve()
    else:
        requested_study = (args.out or Path(safe_id(study_name))).expanduser().resolve()
    if mode == "control" and requested_study.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        study = requested_study.with_name(f"{requested_study.name}_{timestamp}")
        print(f"Requested study directory already exists: {requested_study}")
        print(f"Writing this control study to timestamped directory: {study}")
    else:
        study = requested_study
    study.mkdir(parents=True, exist_ok=False)

    if mode == "control":
        complex_path = args.complex
        if not complex_path:
            raise SystemExit("--complex is required for control mode")
        complex_path = require_complex_path(
            complex_path, project, study / "inputs", args.non_interactive, args.download_pdb
        )
        complex_path = validate_complex_pdb(complex_path)
        # RCSB IDs are already downloaded into this destination. Exact local
        # files are copied so the study remains usable if the original moves.
        print("STAGE: inspect PDB compounds → verify ligand → prepare receptor/site → independent redocking → RMSD/protocol decision")
        try:
            complex_path.relative_to((study / "inputs").resolve())
        except ValueError:
            complex_path = import_local_pdb(complex_path, study / "inputs")
        inspect_pdb_compounds(complex_path, study / "inputs" / "pdb_compound_inventory.json")
        control_tier = args.control_tier
        legacy_single_conformer = False
        box_size = os.environ.get("BOX_SIZE", "26.0")
        if not args.non_interactive:
            print("\nChoose the initial calibration strategy:")
            print("  1) Guided iterative - start quick, then offer broader sampling only if needed (recommended)")
            print("  2) Minimal single-conformer control - fastest qualitative check; not a repeatability control")
            print("  3) Repeatability - five independent seeds at the standard search depth")
            print("  4) Broader search - five seeds with greater exhaustiveness")
            print("  5) More conformers - expand independent starting geometries")
            print("  6) Robust - combine five conformers, five seeds, and greater exhaustiveness")
            calibration_choice = input("Select [1]: ").strip() or "1"
            calibration_tiers = {"1": "quick", "2": "quick", "3": "repeatability", "4": "broader", "5": "conformers", "6": "robust"}
            if calibration_choice not in calibration_tiers:
                raise SystemExit("Choose a calibration strategy from 1 to 6")
            control_tier = calibration_tiers[calibration_choice]
            legacy_single_conformer = calibration_choice == "2"
            box_size = input("Docking-box edge length in Angstroms [26.0]: ").strip() or "26.0"
            try:
                if not 10.0 <= float(box_size) <= 50.0:
                    raise ValueError
            except ValueError:
                raise SystemExit("Docking-box edge length must be between 10 and 50 Angstroms")
        command = [
            "env", f"BOX_SIZE={box_size}", cli, "control", "--complex", complex_path,
            "--engine", args.engine, "--control-tier", control_tier, "--out", study / "control",
            "--ph", args.ph, "--base-seed", args.base_seed, "--forcefield", args.forcefield,
            "--rmsd-prune", args.rmsd_prune, "--charge-model", args.charge_model,
        ]
        if args.conformers_override:
            command += ["--conformers-override", args.conformers_override]
        if args.skip_tautomers:
            command.append("--skip-tautomers")
        if legacy_single_conformer:
            command.append("--legacy-single-conformer")
        if args.non_interactive:
            command.append("--non-interactive")
        if args.no_visuals:
            command.append("--no-visuals")
        try:
            run(command)
        except subprocess.CalledProcessError as exc:
            raise SystemExit(f"Control workflow stopped (exit status {exc.returncode}). Review the concise error above; completed files were retained in {study / 'control'}.") from None
        if default_control_output:
            control_manifest = read_key_value_tsv(study / "control" / "run_manifest.tsv")
            ligand_id = control_manifest.get("ligand_id", "ligand")
            final_study = study.with_name(finalized_control_name(complex_path, ligand_id, run_timestamp))
            study = relocate_study(study, final_study)
            complex_path = study / "inputs" / Path(complex_path).name
            print(f"Final control-study folder: {study}")
        completed_protocols = [
            read_json(path) or {}
            for path in (study / "control").glob("**/protocol.json")
        ]
        control_approved = any(protocol.get("unknown_docking_allowed") for protocol in completed_protocols)
        control_study_manifest = {
            "schema_name": "docking-universal-study", "schema_version": 1,
            "study_name": study_name,
            "study_status": "CONTROL_APPROVED" if control_approved else "CONTROL_NOT_APPROVED",
            "workflow": "control",
            "created_utc": datetime.now(timezone.utc).isoformat(), "compound_count": 0,
            "analysis": "control-specific", "representatives": "control-specific",
            "cluster_rmsd_angstrom": "control-specific", "completion_status": "COMPLETED",
            "experimental_complex": str(complex_path),
            "approved_protocol_count": sum(
                bool(protocol.get("unknown_docking_allowed")) for protocol in completed_protocols
            ),
        }
        (study / "study_manifest.json").write_text(json.dumps(control_study_manifest, indent=2) + "\n")
        report_dir = write_reports(study, control_study_manifest, [])
        print(f"Control study complete: {study}")
        print(f"Run details: {report_dir / 'run_details.md'}")
        if control_approved and not args.non_interactive:
            approved_protocol = next(
                (
                    protocol_path
                    for protocol_path in (study / "control").glob("**/protocol.json")
                    if protocol_allows_screening(protocol_path)
                ),
                None,
            )
            if approved_protocol:
                continue_screen = input("Continue directly to unknown-compound screening with this approved protocol? [y/N]: ").strip().lower()
                if continue_screen in {"y", "yes"}:
                    ligand_source = choose_ligand_source()
                    if not ligand_source.exists():
                        raise SystemExit(f"Ligand input not found: {ligand_source}")
                    screen_out = study / "screen"
                    run([
                        sys.executable, __file__, "--mode", "screen",
                        "--protocol", approved_protocol, "--ligands", ligand_source,
                        "--out", screen_out, "--name", f"{study_name}_screen",
                        "--analysis", "representatives", "--representatives", "20",
                    ])
                    pdf_script = Path(__file__).with_name("docking-universal-pdf-report.py")
                    combined_pdf = screen_out / "report" / "study_report.pdf"
                    subprocess.run([
                        sys.executable, str(pdf_script), str(screen_out),
                        "--control", study / "control", "--out", combined_pdf,
                    ], check=False)
        return

    ligands = args.ligands
    if not ligands and not args.non_interactive:
        ligands = choose_ligand_source()
    if not ligands:
        raise SystemExit("--ligands is required")
    compounds = split_compounds(ligands, study / "inputs" / "compounds")
    report_compound_library(compounds, study / "inputs" / "compound_library_inventory.json")

    if mode == "screen":
        print("STAGE: validating the approved protocol and locked receptor/box before any compound is docked")
        run([
            cli, "screen", "--protocol", args.protocol, "--ligand", compounds[0]["input"],
            "--out", study / "protocol_check", "--check-only", "--non-interactive",
        ])

    receptor_pdb = args.receptor_pdb
    receptor_pdbqt = args.receptor_pdbqt
    box = args.box
    pocket_review_scene = None
    if mode == "exploratory" and not (receptor_pdb and receptor_pdbqt and box):
        if not args.complex:
            raise SystemExit("exploratory mode requires prepared receptor/box inputs or --complex for guided preparation")
        if args.non_interactive and not args.plan_only:
            raise SystemExit("raw exploratory preparation requires interaction; provide --receptor-pdb, --receptor-pdbqt, and --box")
        raw_complex = validate_complex_pdb(args.complex.expanduser().resolve())
        try:
            raw_complex.relative_to((study / "inputs").resolve())
        except ValueError:
            raw_complex = import_local_pdb(raw_complex, study / "inputs")
        inspect_pdb_compounds(raw_complex, study / "inputs" / "pdb_compound_inventory.json")
        prep_parent = study / "preparation"
        prep_parent.mkdir(exist_ok=True)
        # Planning and unattended exploratory runs must not stop at the
        # preparation guide's feedback/site prompts.  Cavity mode is the
        # scientifically appropriate default when no bound ligand is selected.
        run([
            "env", "FEEDBACK_LEVEL=concise", "DOCKING_UNIVERSAL_SITE_MODE=pockets",
            f"DOCKING_UNIVERSAL_CAVITY_MODE={args.cavity_mode}", f"DOCKING_UNIVERSAL_MAX_POCKETS={args.max_pockets}",
            f"DOCKING_UNIVERSAL_CENTER_MODE={args.center_mode}", "DOCKING_UNIVERSAL_CENTROID_MODE=1",
            "STRICT_LOCAL_POCKETS=0",
            "DOCKING_UNIVERSAL_LOG_MODE=file", cli, "prepare", raw_complex,
        ], cwd=prep_parent)
        receptor_pdb, receptor_pdbqt, prepared_boxes = discover_preparation(
            prep_parent, interactive=not args.non_interactive, defer_box_selection=True
        )
        pocket_review_scene = review_pocket_scene(
            prep_parent, args.pymol,
            interactive=(not args.non_interactive and not args.plan_only),
            requested=(args.review_pockets and not args.plan_only),
        )
        box = choose_prepared_box(prepared_boxes, interactive=not args.non_interactive)

    manifest = {
        "schema_name": "docking-universal-study", "schema_version": 1,
        "study_name": study_name, "study_status": STATUSES[mode], "workflow": mode,
        "created_utc": datetime.now(timezone.utc).isoformat(), "compound_count": len(compounds),
        "analysis": args.analysis, "representatives": args.representatives, "cluster_rmsd_angstrom": args.cluster_rmsd,
        "completion_status": "PLANNED" if args.plan_only else "RUNNING",
        "pocket_review_scene": pocket_review_scene,
    }
    (study / "study_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

    failures = 0
    if args.plan_only:
        for compound in compounds:
            compound["run_status"] = "PLANNED"
    for index, compound in enumerate(compounds, start=1):
        if args.plan_only:
            continue
        print(f"\nCOMPOUND {index}/{len(compounds)}: {compound['compound_name']} ({compound['compound_id']})")
        print("  Next: independent conformers → ligand PDBQT → replicated rigid-receptor docking → clustering → reports")
        compound_dir = study / "compounds" / compound["compound_id"]
        command = [
            cli, "screen", "--ligand", compound["input"], "--out", compound_dir,
            "--analysis", args.analysis, "--representatives", args.representatives,
            "--cluster-rmsd", args.cluster_rmsd, "--non-interactive",
        ]
        if mode == "screen":
            command += ["--protocol", args.protocol]
        else:
            command += [
                "--exploratory", "--receptor", receptor_pdbqt, "--receptor-pdb", receptor_pdb,
                "--box", box, "--engine", args.engine, "--seeds", args.seeds,
                "--conformers", args.conformers, "--exhaustiveness", args.exhaustiveness,
                "--num-modes", args.num_modes, "--energy-range", args.energy_range, "--ph", args.ph,
                "--base-seed", args.base_seed, "--forcefield", args.forcefield,
                "--rmsd-prune", args.rmsd_prune, "--charge-model", args.charge_model,
            ]
            if args.skip_tautomers:
                command.append("--skip-tautomers")
        try:
            run(command)
            compound["run_status"] = "COMPLETED"
        except subprocess.CalledProcessError as exc:
            failures += 1
            compound["run_status"] = "FAILED"
            compound_dir.mkdir(parents=True, exist_ok=True)
            (compound_dir / "failure.json").write_text(json.dumps({
                "status": "FAILED", "return_code": exc.returncode,
                "command": [str(value) for value in exc.cmd],
                "message": "Compound workflow failed; completed outputs were retained for resume.",
            }, indent=2) + "\n")
            print(f"ERROR: compound {compound['compound_id']} failed; continuing with retained outputs", file=sys.stderr)
            if args.stop_on_error:
                break

    if args.plan_only:
        manifest["completion_status"] = "PLANNED"
    elif failures:
        manifest["completion_status"] = "COMPLETED_WITH_WARNINGS"
    else:
        manifest["completion_status"] = "COMPLETED"
    (study / "study_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    report_dir = write_reports(study, manifest, compounds)
    print(f"\nStudy complete: {study}")
    print(f"Readable report: {report_dir / 'index.html'}")
    print(f"Machine summary: {report_dir / 'study_summary.json'}")
    print(f"Run details: {report_dir / 'run_details.md'}")


if __name__ == "__main__":
    main()
