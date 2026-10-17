"""Sequential, isolated real preparation checks; no docking or network lookup.

Reuses only the immutable raw inputs and retained aligned experimental ligands,
not prepared receptors, cavities, or an old scientific approval.
"""
from collections import Counter
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

import gemmi
import numpy as np

from docking_universal_pocket_evidence import (
    classify_cavity_match, ligand_box_relationship, pdb_atom_coordinates, read_box_geometry,
)


ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / "validation/runs/full-scratch-two-paths-20261017"
RUN = ROOT / "validation/runs/reduce2-frame-fix-20261017"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def protein_backbone(path):
    structure = gemmi.read_structure(str(path))
    return {(chain.name, residue.seqid.num, residue.seqid.icode, atom.name, atom.altloc):
            (atom.pos.x, atom.pos.y, atom.pos.z)
            for chain in structure[0] for residue in chain for atom in residue
            if atom.name in {"N", "CA", "C", "O"} and residue.het_flag == "A"}


def evidence_check(cavity):
    evidence_root = OLD / "fresh-download/preparation/2R8N_receptor_prep/cavity/pdb_site_evidence"
    evidence = json.loads((evidence_root / "pdb_ligand_site_evidence.json").read_text())["evidence"]
    boxes = sorted(cavity.glob("2R8N_pocket*.conf"), key=lambda p: int(p.stem.split("pocket")[-1]))
    pocket_atoms = {index: pdb_atom_coordinates(cavity / f"frozen_pockets/pocket{index}_atm.pdb")
                    for index in range(1, len(boxes) + 1)}
    counts = Counter()
    rows = []
    for observation in evidence:
        atoms = pdb_atom_coordinates(evidence_root / observation["aligned_ligand_pdb"])
        _, match, reason = classify_cavity_match(atoms, pocket_atoms)
        relationships = {index: ligand_box_relationship(atoms, *read_box_geometry(box))
                         for index, box in enumerate(boxes, 1)}
        if match is not None and not relationships[match]["all_heavy_atoms_inside"]:
            match = None
        if observation.get("chain_assignment_ambiguous"):
            match = None
        counts[str(match)] += 1
        rows.append({"ligand": observation["source_ligand_id"], "matched_cavity": match,
                     "original_matched_cavity": observation["matched_cavity"], "reason": reason,
                     "p1_distance_angstrom": relationships[1]["minimum_distance_to_box_angstrom"]})
    return {"mode": "local reassociation of 18 retained, original-frame aligned ligands; no new PDB lookup",
            "matched_cavity_counts": dict(counts), "observations": rows,
            "all_match_original_associations": all(row["matched_cavity"] == row["original_matched_cavity"] for row in rows)}


def compare_formats(summary):
    def rows(case):
        path = Path(case["preparation"]) / "receptor/2R8N.pdbqt"
        return {line[12:27]: {"xyz": [float(line[start:start + 8]) for start in (30, 38, 46)],
                              "charge": float(line[70:76]), "type": line[77:].strip()}
                for line in path.read_text().splitlines() if line.startswith(("ATOM  ", "HETATM"))}
    first, second = summary["cases"]
    left, right = rows(first), rows(second)
    assert left.keys() == right.keys()
    differences = [dict(atom=key.strip(), distance_angstrom=float(np.linalg.norm(np.array(left[key]["xyz"]) - right[key]["xyz"])))
                   for key in left if left[key]["xyz"] != right[key]["xyz"]]
    summary["format_comparison"] = {
        "matched_atom_count": len(left),
        "identical_heavy_atom_coordinates": all(left[key]["xyz"] == right[key]["xyz"] for key in left if left[key]["type"] not in {"H", "HD"}),
        "identical_partial_charges_and_types": all((left[key]["charge"], left[key]["type"]) == (right[key]["charge"], right[key]["type"]) for key in left),
        "coordinate_differences": differences,
        "maximum_coordinate_difference_angstrom": max((row["distance_angstrom"] for row in differences), default=0),
    }
    summary["pdbqt_byte_identical_between_formats"] = first["receptor_pdbqt_sha256"] == second["receptor_pdbqt_sha256"]
    summary["p1_geometry_identical_between_formats"] = first["p1_geometry"] == second["p1_geometry"]
    assert summary["format_comparison"]["identical_heavy_atom_coordinates"]
    assert summary["format_comparison"]["identical_partial_charges_and_types"]
    # Native CIF retains higher coordinate precision than PDB. Two added H
    # coordinates can round differently by the final PDBQT's 0.001 A unit.
    assert summary["format_comparison"]["maximum_coordinate_difference_angstrom"] <= .0011
    assert summary["p1_geometry_identical_between_formats"]


def main():
    global RUN
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verify-only", action="store_true", help="Recheck existing outputs; never repeat preparation")
    parser.add_argument("--runtime", type=Path, default=ROOT / "libexec")
    parser.add_argument("--out", type=Path, default=RUN)
    args = parser.parse_args()
    RUN = args.out.resolve()
    if args.verify_only:
        summary_file = RUN / "summary.json"
        summary = json.loads(summary_file.read_text())
        summary["verification_history"] = [{"status": summary["status"], "error": summary.pop("error", None),
                                            "explanation": "Initial harness required byte identity; actual difference is two H coordinates rounded by 0.001 A. No preparation repeated."}]
        compare_formats(summary)
        assert all(sha(path) == digest for path, digest in summary["protected_sha256"].items())
        summary["status"] = "passed"
        summary_file.write_text(json.dumps(summary, indent=2) + "\n")
        print(json.dumps(summary["format_comparison"], indent=2))
        return
    RUN.mkdir(exist_ok=False)
    protected = json.loads((OLD / "receptor-investigation/comparison.json").read_text())["file_sha256"]
    protected[str(OLD / "summary.json")] = sha(OLD / "summary.json")
    assert all(sha(path) == digest for path, digest in protected.items())
    summary = {"status": "running", "runtime": str(args.runtime.resolve()),
               "scientific_boundary": "preparation only; no approval, docking, or new network requests",
               "cases": [], "protected_sha256": protected}
    summary_file = RUN / "summary.json"
    def save():
        summary_file.write_text(json.dumps(summary, indent=2) + "\n")
    save()
    env = dict(os.environ,
               PATH="/opt/anaconda3/envs/docking-universal/bin:/opt/anaconda3/bin:/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin",
               CONDA_PREFIX="/opt/anaconda3/envs/docking-universal",
               DOCKING_UNIVERSAL_PYTHON="/opt/anaconda3/envs/docking-universal/bin/python",
               DOCKING_UNIVERSAL_POCKET_ENGINE="p2rank", DOCKING_UNIVERSAL_SITE_MODE="pockets",
               DOCKING_UNIVERSAL_MAX_POCKETS="0", DOCKING_UNIVERSAL_CAVITY_MODE="1",
               DOCKING_UNIVERSAL_CENTER_MODE="centroid", DOCKING_UNIVERSAL_CENTROID_MODE="1",
               DOCKING_UNIVERSAL_GEOSTD=str(args.runtime / "docking_universal/data/geostd"),
               DOCKING_UNIVERSAL_REDUCE2="required", FEEDBACK_LEVEL="concise", DOCKING_UNIVERSAL_LOG_MODE="file")
    try:
        for name, source in (
            ("mmcif", OLD / "fresh-download/preparation/inputs/2R8N.cif"),
            ("pdb", ROOT / "examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb"),
        ):
            case = RUN / name
            case.mkdir()
            copied = case / source.name
            shutil.copyfile(source, copied)
            item = {"format": name, "source": str(source), "source_sha256": sha(source), "status": "running"}
            summary["cases"].append(item)
            save()
            started = time.monotonic()
            with (case / "driver.log").open("w") as log:
                result = subprocess.run([str(args.runtime / "docking-universal-prepare"), str(copied)],
                                        cwd=case, env=env, stdout=log, stderr=subprocess.STDOUT)
            item["returncode"] = result.returncode
            item["elapsed_seconds"] = time.monotonic() - started
            prep = case / "2R8N_receptor_prep"
            item["preparation"] = str(prep)
            if result.returncode:
                raise RuntimeError(f"{name} preparation failed: inspect {case / 'driver.log'} and {prep / 'run.log'}")
            audit = json.loads((prep / "receptor/reduce2_audit.json").read_text())
            assert audit["status"] == "compatible", audit
            assert audit["input_heavy_atom_count"] == audit["output_heavy_atom_count"] == 754
            assert audit["coordinate_frame"]["status"] == "preserved"
            original = protein_backbone(source)
            prepared = protein_backbone(prep / "receptor/2R8N.pdb")
            assert original.keys() == prepared.keys()
            displacement = max(np.linalg.norm(np.array(prepared[key]) - original[key]) for key in original)
            assert displacement <= .001
            item["maximum_original_backbone_displacement_angstrom"] = float(displacement)
            item["reduce2_audit"] = audit
            item["evidence_reassociation"] = evidence_check(prep / "cavity")
            assert item["evidence_reassociation"]["all_match_original_associations"]
            item["p1_geometry"] = [array.tolist() for array in read_box_geometry(prep / "cavity/2R8N_pocket1.conf")]
            item["receptor_pdbqt_sha256"] = sha(prep / "receptor/2R8N.pdbqt")
            item["status"] = "passed"
            save()
        compare_formats(summary)
        summary["status"] = "passed"
    except Exception as error:
        summary.update(status="failed", error=str(error))
        raise
    finally:
        summary["protected_files_unchanged"] = all(sha(path) == digest for path, digest in protected.items())
        save()
    print(json.dumps({key: summary[key] for key in ("status", "pdbqt_byte_identical_between_formats",
                                                  "p1_geometry_identical_between_formats", "protected_files_unchanged")}, indent=2))


if __name__ == "__main__":
    main()
