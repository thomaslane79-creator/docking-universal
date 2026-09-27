"""Isolated native-mmCIF preparation evaluation; never changes production policy."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class NativeMmcifCapabilities:
    pdbfixer: bool
    meeko: bool
    prody: bool
    direct_meeko_mmcif: bool
    notes: tuple[str, ...]


def detect_native_mmcif_capabilities(python: Path | str, meeko: Path | str) -> NativeMmcifCapabilities:
    python = str(Path(python).expanduser())
    meeko_path = Path(meeko).expanduser()
    checks = {}
    for module in ("pdbfixer", "meeko", "prody"):
        result = subprocess.run(
            [python, "-c", f"import {module}"], capture_output=True, text=True, check=False
        )
        checks[module] = result.returncode == 0
    executable = meeko_path.is_file() or shutil.which(str(meeko_path)) is not None
    direct = executable and checks["meeko"] and checks["prody"]
    notes = []
    if not checks["pdbfixer"]:
        notes.append("PDBFixer is unavailable; native repair cannot be evaluated")
    if not checks["prody"]:
        notes.append("ProDy is unavailable; Meeko --read_with_prody cannot read mmCIF")
    if not executable:
        notes.append("mk_prepare_receptor.py is unavailable")
    return NativeMmcifCapabilities(
        checks["pdbfixer"], checks["meeko"], checks["prody"], direct, tuple(notes)
    )


def pdbfixer_native_command(
    python: Path | str,
    helper: Path | str,
    source_cif: Path | str,
    output_pdb: Path | str,
    audit_json: Path | str,
) -> tuple[str, ...]:
    return tuple(map(str, (python, helper, source_cif, output_pdb, audit_json)))


def meeko_native_mmcif_command(
    executable: Path | str,
    source_cif: Path | str,
    output_prefix: Path | str,
    output_pdbqt: Path | str,
) -> tuple[str, ...]:
    return (
        str(executable), "--read_with_prody", str(source_cif),
        "-o", str(output_prefix), "-p", str(output_pdbqt),
    )


def compare_structure_paths(paths: dict[str, Path | str]) -> dict[str, Any]:
    """Compare outputs without declaring one scientifically correct."""
    import gemmi

    summaries = {}
    identities = {}
    for label, raw_path in paths.items():
        path = Path(raw_path).resolve()
        structure = gemmi.read_structure(str(path))
        atoms = []
        residues = set()
        hetero = set()
        chains = set()
        for model_index, model in enumerate(structure):
            for chain in model:
                chains.add(chain.name)
                for residue in chain:
                    residue_id = (
                        model_index, chain.name, str(residue.seqid.num),
                        str(residue.seqid.icode).strip("\x00 ?.") or "", residue.name,
                    )
                    residues.add(residue_id)
                    if residue.het_flag == "H":
                        hetero.add(residue_id)
                    for atom in residue:
                        atoms.append((*residue_id, atom.name, str(atom.altloc).strip("\x00 ")))
        identity = set(atoms)
        identities[label] = identity
        summaries[label] = {
            "path": str(path),
            "models": len(structure),
            "chains": sorted(chains),
            "residue_count": len(residues),
            "hetero_residue_count": len(hetero),
            "atom_count": len(atoms),
        }
    labels = list(paths)
    pairwise = []
    for index, left in enumerate(labels):
        for right in labels[index + 1:]:
            common = identities[left] & identities[right]
            union = identities[left] | identities[right]
            pairwise.append({
                "left": left,
                "right": right,
                "common_atom_identities": len(common),
                "left_only_atom_identities": len(identities[left] - identities[right]),
                "right_only_atom_identities": len(identities[right] - identities[left]),
                "identity_jaccard": (len(common) / len(union)) if union else 1.0,
            })
    return {
        "schema_name": "docking-universal-mmcif-preparation-comparison",
        "schema_version": 1,
        "interpretation": (
            "Differences require scientific review; this comparison does not automatically "
            "select or promote a preparation route."
        ),
        "structures": summaries,
        "pairwise": pairwise,
    }


def run_command(command: Sequence[str], log_path: Path | str) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(list(command), capture_output=True, text=True, check=False)
    Path(log_path).write_text(
        "$ " + " ".join(map(str, command)) + "\n\nSTDOUT\n" + result.stdout
        + "\nSTDERR\n" + result.stderr
    )
    return result


def write_capabilities(path: Path | str, capabilities: NativeMmcifCapabilities) -> None:
    Path(path).write_text(json.dumps(asdict(capabilities), indent=2) + "\n")
