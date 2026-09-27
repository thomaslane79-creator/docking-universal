"""Build a durable pocket-selection decision from retained real artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docking_universal_box_candidates import config_geometry, grouped_fpocket_boxes
from docking_universal_region import write_box_files

from ..application import StudyController
from ..automation import AutomationPolicy
from ..decisions import DecisionRequired
from ..models import ArtifactRecord, PocketCandidate


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ordered_pocket_boxes(cavity: Path | str) -> list[Path]:
    numbered = []
    for path in Path(cavity).glob("*.conf"):
        match = re.search(r"_pocket(\d+)\.conf$", path.name)
        if match:
            numbered.append((int(match.group(1)), path))
    return [path for _, path in sorted(numbered, key=lambda item: (item[0], item[1].name))]


def _safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "site"


def _pocket_coordinate_paths(cavity: Path, label: str) -> list[Path]:
    numbers = [int(value) for value in re.findall(r"P(\d+)", label)]
    paths = []
    for number in numbers:
        matches = sorted(cavity.rglob(f"pocket{number}_atm.pdb"))
        if matches:
            paths.append(matches[0].resolve())
    return paths


def _conformational_site_evidence(
    groups: list[dict[str, Any]], conformational: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return box-review evidence tied to the groups' deposited ligands."""
    source_ids = {
        member.get("source_ligand_id")
        for group in groups for member in group.get("members", [])
        if member.get("source_ligand_id")
    }
    observations = []
    for observation in (conformational or {}).get("observations", []):
        matched = [
            item for item in observation.get("known_ligand_accessibility", [])
            if item.get("source_ligand_id") in source_ids
        ]
        if matched:
            observations.append({
                "residue": observation.get("residue"),
                "entry": observation.get("entry"),
                "alignment_id": observation.get("alignment_id"),
                "maximum_chi_difference_degrees": observation.get("maximum_chi_difference_degrees"),
                "side_chain_rmsd_angstrom": observation.get("side_chain_rmsd_angstrom"),
                "backbone_rmsd_angstrom": observation.get("backbone_rmsd_angstrom"),
                "ligands": matched,
            })
    occluding = [
        item for observation in observations for item in observation["ligands"]
        if item.get("consistent_with_side_chain_occlusion")
    ]
    residues = []
    for observation in observations:
        if any(item.get("consistent_with_side_chain_occlusion") for item in observation["ligands"]):
            residue = observation.get("residue")
            if residue and residue not in residues:
                residues.append(residue)
    return {
        "status": (
            "conformationally_incompatible" if occluding
            else "reviewed_no_geometric_incompatibility" if observations
            else "not_evaluated"
        ),
        "box_decision_warning": (
            "A deposited ligand placement conflicts with the current receptor conformation. "
            "An alternate side-chain conformation may restrict site accessibility or help explain "
            "a missing/reduced predicted cavity; this is supporting evidence, not proof of flexibility. "
            "Rigid docking in this box may not be a legitimate test."
            if occluding else None
        ),
        "occluding_residues": residues,
        "observation_count": len(observations),
        "observations": observations,
        "decision_role": "evidence_for_box_review_only",
    }


def _experimental_site_evidence(
    groups: list[dict[str, Any]], pocket_evidence: dict[str, Any] | None, evidence_root: Path,
) -> dict[str, Any]:
    """Compact, auditable deposited-ligand observations for one candidate."""
    source_ids = {
        member.get("source_ligand_id")
        for group in groups for member in group.get("members", [])
        if member.get("source_ligand_id")
    }
    records = []
    for item in (pocket_evidence or {}).get("evidence", []):
        if item.get("source_ligand_id") not in source_ids:
            continue
        aligned = evidence_root / str(item.get("aligned_ligand_pdb", ""))
        records.append({
            "source_ligand_id": item.get("source_ligand_id"),
            "entry": item.get("entry"), "ligand": item.get("ligand"),
            "evidence_class": item.get("evidence_class"),
            "sequence_identity": item.get("sequence_identity"),
            "query_coverage": item.get("query_coverage"),
            "ca_rmsd_angstrom": item.get("ca_rmsd_angstrom"),
            "aligned_ligand_pdb": str(aligned.resolve()) if aligned.is_file() else None,
        })
    classes: dict[str, int] = {}
    for item in records:
        key = str(item.get("evidence_class") or "unclassified")
        classes[key] = classes.get(key, 0) + 1
    rmsds = [item["ca_rmsd_angstrom"] for item in records if isinstance(item.get("ca_rmsd_angstrom"), (int, float))]
    return {
        "observation_count": len(records),
        "pdb_entry_count": len({item["entry"] for item in records if item.get("entry")}),
        "ligand_count": len({item["ligand"] for item in records if item.get("ligand")}),
        "evidence_class_counts": classes,
        "minimum_ca_rmsd_angstrom": min(rmsds) if rmsds else None,
        "maximum_ca_rmsd_angstrom": max(rmsds) if rmsds else None,
        "observations": records,
        "decision_role": "evidence_for_box_review_only",
    }


def build_labeled_candidate_mappings(
    target: str,
    boxes: list[Path],
    pocket_evidence: dict[str, Any] | None,
    cavity: Path | str,
) -> list[dict[str, Any]]:
    """Create the same selectable P#, consolidated P#/P#, and L# boxes."""
    cavity = Path(cavity)
    candidates: list[dict[str, Any]] = []
    provenance_path = cavity / "pocket_detection_provenance.json"
    provenance = json.loads(provenance_path.read_text()) if provenance_path.is_file() else {}
    detector = provenance.get("engine", "fpocket")
    equivalence_by_pocket: dict[int, list[dict[str, Any]]] = {}
    for equivalence in provenance.get("pocket_equivalences", []):
        for number in equivalence.get("pockets", []):
            equivalence_by_pocket.setdefault(int(number), []).append(equivalence)
    ligand_groups = (pocket_evidence or {}).get("ligand_site_groups") or []
    evidence_root = cavity / "pdb_site_evidence"
    conformational = (pocket_evidence or {}).get("_conformational_evidence")
    groups_by_pocket: dict[str, list[dict[str, Any]]] = {}
    for group in ligand_groups:
        pocket = (group.get("pocket_recovery") or group.get("fpocket_recovery") or {}).get("best_matching_pocket")
        if pocket:
            groups_by_pocket.setdefault(str(pocket), []).append(group)
    available = {path.resolve() for path in boxes}
    for fallback_index, path in enumerate(ordered_pocket_boxes(cavity), 1):
        if available and path.resolve() not in available:
            continue
        match = re.search(r"_pocket(\d+)\.conf$", path.name)
        number = int(match.group(1)) if match else fallback_index
        supporting = groups_by_pocket.get(str(number), [])
        description = f"individual {detector} pocket box"
        if supporting:
            description += "; direct deposited-ligand correspondence recorded"
        equivalences = equivalence_by_pocket.get(number, [])
        if equivalences:
            equivalence_phrases = []
            for item in equivalences:
                peers = [int(peer) for peer in item.get("pockets", []) if int(peer) != number]
                rmsd = item.get("fitted_pocket_atom_rmsd_angstrom")
                chain_text = "/".join(str(chain) for chain in item.get("chains", []) if chain)
                for peer in peers:
                    detail = f"fitted pocket RMSD {rmsd:g} Å" if isinstance(rmsd, (int, float)) else "low fitted pocket RMSD"
                    if chain_text:
                        detail += f"; chains {chain_text}"
                    equivalence_phrases.append(
                        f"probable symmetry-related pocket copy of P{peer} ({detail}); "
                        "both sites may be relevant in the physiological assembly"
                    )
            description += "; " + "; ".join(equivalence_phrases)
        candidates.append({
            "label": f"P{number}",
            "path": path,
            "description": description,
            "evidence": {
                "kind": detector,
                "detector": detector,
                "direct_ligand_site_groups": len(supporting),
                "pocket_equivalences": equivalences,
                "symmetry_equivalence_shown_in_box_selection": bool(equivalences),
                "conformational_site_evidence": _conformational_site_evidence(supporting, conformational),
                "experimental_ligand_evidence": _experimental_site_evidence(
                    supporting, pocket_evidence, evidence_root,
                ),
                "automation_eligible": True,
            },
        })

    diagnostics = cavity / "pocket_selection_diagnostics.tsv"
    if diagnostics.is_file():
        with diagnostics.open(newline="") as handle:
            retained = [
                row for row in csv.DictReader(handle, delimiter="\t")
                if row.get("decision") == "selected"
            ]
        retained.sort(key=lambda row: int(row.get("rank_order", 999999)))
        displayed_files = [row.get("pocket_file", "") for row in retained[:3]]
        for group in grouped_fpocket_boxes(diagnostics, retained, displayed_files):
            if len(group["numbers"]) < 2:
                continue
            label = "/".join(f"P{number}" for number in group["numbers"])
            path = write_box_files(
                cavity / f"{target}_consolidated_{label.replace('/', '-')}.conf",
                group["geometry"],
            )
            candidates.append({
                "label": label,
                "path": path,
                "description": f"consolidated box spanning the named overlapping {detector} pockets",
                "evidence": {"kind": f"consolidated_{detector}", "detector": detector, "automation_eligible": True},
            })

    for group in ligand_groups:
        identity = group.get("site_identity") or {}
        matching_pocket = (group.get("pocket_recovery") or group.get("fpocket_recovery") or {}).get("best_matching_pocket")
        if matching_pocket:
            continue
        label = identity.get("canonical_label", f"L{group.get('site_number', '?')}")
        path = write_box_files(
            cavity / f"{target}_evidence_{_safe_label(label)}.conf",
            group["box"],
        )
        classes = group.get("evidence_class_counts") or {}
        requires_homolog_approval = bool(classes.get("close_structural_homolog"))
        candidates.append({
            "label": label,
            "path": path,
            "description": f"ligand-defined box without a corresponding {detector} cavity",
            "requires_homolog_approval": requires_homolog_approval,
            "evidence": {
                "kind": "ligand_defined",
                "evidence_class_counts": classes,
                "automation_eligible": not requires_homolog_approval,
                "conformational_site_evidence": _conformational_site_evidence([group], conformational),
                "experimental_ligand_evidence": _experimental_site_evidence(
                    [group], pocket_evidence, evidence_root,
                ),
            },
        })
    return candidates


@dataclass(frozen=True)
class PocketReviewInputs:
    target: str
    cavity_directory: Path
    boxes: tuple[Path, ...]
    pocket_evidence_record: Path | None = None
    review_scene: Path | None = None


class PocketReviewService:
    """Translate retained cavity evidence into a UI-independent decision."""

    def __init__(self, controller: StudyController):
        self.controller = controller

    def start(
        self,
        study_id: str,
        inputs: PocketReviewInputs,
        *,
        automation: AutomationPolicy | None = None,
    ) -> DecisionRequired:
        cavity = Path(inputs.cavity_directory)
        if not cavity.is_dir():
            raise FileNotFoundError(f"Cavity directory does not exist: {cavity}")
        missing = [str(path) for path in inputs.boxes if not Path(path).is_file()]
        if missing:
            raise FileNotFoundError("Missing retained docking box(es): " + ", ".join(missing))
        evidence: dict[str, Any] = {}
        if inputs.pocket_evidence_record:
            evidence_path = Path(inputs.pocket_evidence_record)
            if not evidence_path.is_file():
                raise FileNotFoundError(f"Pocket evidence record does not exist: {evidence_path}")
            evidence = json.loads(evidence_path.read_text())
            conformational_value = (
                evidence.get("structural_ensemble") or {}
            ).get("conformational_evidence")
            if conformational_value:
                conformational_path = evidence_path.parent / conformational_value
                if conformational_path.is_file():
                    evidence["_conformational_evidence"] = json.loads(conformational_path.read_text())

        mappings = build_labeled_candidate_mappings(
            inputs.target,
            [Path(path) for path in inputs.boxes],
            evidence,
            cavity,
        )
        if not mappings:
            raise ValueError("No selectable pocket candidates could be built from the retained artifacts")

        artifacts: list[ArtifactRecord] = []
        candidates: list[PocketCandidate] = []
        for rank, item in enumerate(mappings, 1):
            path = Path(item["path"]).resolve()
            artifact_id = f"pocket-box-{_safe_label(item['label'])}"
            artifacts.append(ArtifactRecord(
                id=artifact_id,
                kind="docking_box",
                path=str(path),
                sha256=_sha256(path),
                description=item["description"],
                metadata={"label": item["label"], "geometry": config_geometry(path)},
            ))
            candidate_evidence = dict(item.get("evidence") or {})
            viewer_artifact_ids = []
            for pocket_path in _pocket_coordinate_paths(cavity, item["label"]):
                pocket_id = f"pocket-coordinates-{pocket_path.stem}"
                if pocket_id not in {artifact.id for artifact in artifacts}:
                    artifacts.append(ArtifactRecord(
                        id=pocket_id,
                        kind="pocket_coordinates",
                        path=str(pocket_path),
                        sha256=_sha256(pocket_path),
                        description=f"PyMOL coordinates for {item['label']}",
                        metadata={"candidate_label": item["label"]},
                    ))
                viewer_artifact_ids.append(pocket_id)
            candidate_evidence.update({
                "geometry": config_geometry(path),
                "requires_homolog_approval": item.get("requires_homolog_approval", False),
                "viewer_artifact_ids": viewer_artifact_ids,
            })
            candidates.append(PocketCandidate(
                id=item["label"],
                label=item["label"],
                rank=rank,
                box_artifact_id=artifact_id,
                summary=item["description"],
                evidence=candidate_evidence,
            ))

        review_ids = [artifact.id for artifact in artifacts]
        for artifact in self._supporting_artifacts(inputs, evidence):
            artifacts.append(artifact)
            review_ids.append(artifact.id)
        source = {
            "cavity_directory": str(cavity.resolve()),
            "pocket_evidence_record": (
                str(Path(inputs.pocket_evidence_record).resolve())
                if inputs.pocket_evidence_record else None
            ),
            "candidate_count": len(candidates),
            "related_structure_evidence": (
                evidence.get("status") in {"completed", "available"}
                and bool(evidence.get("evidence") or evidence.get("ligand_site_groups"))
            ),
        }
        return self.controller.start_pocket_review(
            study_id,
            candidates,
            artifacts=tuple(artifacts),
            review_artifact_ids=tuple(review_ids),
            source=source,
            automation=automation,
        )

    @staticmethod
    def _supporting_artifacts(
        inputs: PocketReviewInputs,
        evidence: dict[str, Any],
    ) -> list[ArtifactRecord]:
        records = []
        paths: list[tuple[str, str, Path]] = []
        if inputs.pocket_evidence_record:
            paths.append(("pocket-evidence", "pocket_evidence", Path(inputs.pocket_evidence_record)))
            ensemble_value = (evidence.get("structural_ensemble") or {}).get("manifest")
            if ensemble_value:
                paths.append((
                    "structural-ensemble",
                    "structural_ensemble",
                    Path(inputs.pocket_evidence_record).parent / ensemble_value,
                ))
            conformational_value = (evidence.get("structural_ensemble") or {}).get("conformational_evidence")
            if conformational_value:
                paths.append((
                    "conformational-evidence", "conformational_evidence",
                    Path(inputs.pocket_evidence_record).parent / conformational_value,
                ))
        if inputs.review_scene:
            paths.append(("pocket-review-scene", "pymol_scene", Path(inputs.review_scene)))
        for artifact_id, kind, path in paths:
            if path.is_file():
                records.append(ArtifactRecord(
                    id=artifact_id,
                    kind=kind,
                    path=str(path.resolve()),
                    sha256=_sha256(path),
                    description={
                        "pocket_evidence": "Related-PDB ligand and pocket evidence",
                        "structural_ensemble": "Shared related-structure ensemble evidence",
                        "conformational_evidence": "Rotamer and site-accessibility evidence for docking-box review",
                        "pymol_scene": "Interactive pocket-review scene",
                    }[kind],
                ))
        return records
