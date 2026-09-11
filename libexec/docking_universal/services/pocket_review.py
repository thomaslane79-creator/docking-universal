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


def build_labeled_candidate_mappings(
    target: str,
    boxes: list[Path],
    pocket_evidence: dict[str, Any] | None,
    cavity: Path | str,
) -> list[dict[str, Any]]:
    """Create the same selectable P#, consolidated P#/P#, and L# boxes."""
    cavity = Path(cavity)
    candidates: list[dict[str, Any]] = []
    ligand_groups = (pocket_evidence or {}).get("ligand_site_groups") or []
    groups_by_pocket: dict[str, list[dict[str, Any]]] = {}
    for group in ligand_groups:
        pocket = (group.get("fpocket_recovery") or {}).get("best_matching_pocket")
        if pocket:
            groups_by_pocket.setdefault(str(pocket), []).append(group)
    available = {path.resolve() for path in boxes}
    for fallback_index, path in enumerate(ordered_pocket_boxes(cavity), 1):
        if available and path.resolve() not in available:
            continue
        match = re.search(r"_pocket(\d+)\.conf$", path.name)
        number = int(match.group(1)) if match else fallback_index
        supporting = groups_by_pocket.get(str(number), [])
        description = "individual fpocket cavity box"
        if supporting:
            description += "; direct deposited-ligand correspondence recorded"
        candidates.append({
            "label": f"P{number}",
            "path": path,
            "description": description,
            "evidence": {
                "kind": "fpocket",
                "direct_ligand_site_groups": len(supporting),
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
                "description": "consolidated box spanning the named overlapping fpocket cavities",
                "evidence": {"kind": "consolidated_fpocket", "automation_eligible": True},
            })

    for group in ligand_groups:
        identity = group.get("site_identity") or {}
        matching_pocket = (group.get("fpocket_recovery") or {}).get("best_matching_pocket")
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
            "description": "ligand-defined box without a corresponding fpocket cavity",
            "requires_homolog_approval": requires_homolog_approval,
            "evidence": {
                "kind": "ligand_defined",
                "evidence_class_counts": classes,
                "automation_eligible": not requires_homolog_approval,
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
            candidate_evidence.update({
                "geometry": config_geometry(path),
                "requires_homolog_approval": item.get("requires_homolog_approval", False),
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
            "related_structure_evidence": bool(evidence),
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
                        "pymol_scene": "Interactive pocket-review scene",
                    }[kind],
                ))
        return records
