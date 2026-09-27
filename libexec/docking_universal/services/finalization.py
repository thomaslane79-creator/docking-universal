"""Finalize an approved site-guided protocol from retained preparation artifacts."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path
from typing import Callable

from docking_universal_bundle import build_receptor_modification_warning, create_bundle

from ..protocol_finalization import (
    FinalizationOutputs,
    ProtocolFinalizationRequest,
    ProtocolRecordInputs,
    build_protocol_record,
    build_site_guided_report_manifest,
    publish_final_outputs,
    selected_region_records,
    write_protocol_record,
)
from ..state import StudyState


@dataclass(frozen=True)
class ProtocolFinalizationPaths:
    root: Path
    protocol: Path
    report: Path
    bundle: Path
    summary: Path


def _safe_id(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("._-") or "target"


def finalization_paths(request: ProtocolFinalizationRequest) -> ProtocolFinalizationPaths:
    root = request.output_directory.resolve()
    base = f"{_safe_id(request.target)}_site-guided-exploratory_{request.settings.engine}"
    return ProtocolFinalizationPaths(
        root=root,
        protocol=root / f"{base}_protocol.json",
        report=root / "report" / f"{base}_protocol_report.pdf",
        bundle=root / f"{base}.duprotocol",
        summary=root / "report" / "study_summary.json",
    )


def _version(name: str) -> str:
    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return "not detected"


def _package_version(libexec: Path) -> str:
    for path in (libexec / "VERSION", libexec.parent / "VERSION"):
        if path.is_file():
            return path.read_text().strip()
    return "unknown"


def _read_json(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _read_removal_manifest(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.is_file():
        return []
    lines = path.read_text(errors="replace").splitlines()
    if not lines:
        return []
    headings = lines[0].split("\t")
    return [dict(zip(headings, line.split("\t"))) for line in lines[1:] if line.strip()]


def _preparation_summary(root: Path) -> str:
    log = root / "run.log"
    text = log.read_text(errors="replace") if log.is_file() else ""
    if next(iter(sorted(root.glob("receptor/user_approved_component_removal.txt"))), None):
        return (
            "User explicitly approved removal of unmatched receptor components after safe "
            "preparation fallbacks failed; retained records identify the altered model"
        )
    if "Initial receptor preparation succeeded; PDBFixer was not needed" in text:
        return "Strict Meeko succeeded; PDBFixer was not needed"
    if "PDBFixer" in text and "succeeded" in text:
        return "Strict Meeko required conditional PDBFixer repair; retained audits record the changes"
    return "Receptor preparation completed; the retained preparation log records the applied path"


def _all_candidate_regions(state: StudyState) -> list[dict]:
    artifacts = {item.id: item for item in state.artifacts}
    paths = []
    labels = []
    for candidate in state.workflow_data.get("pocket_candidates", []):
        artifact = artifacts.get(candidate.get("box_artifact_id"))
        if artifact is None or not Path(artifact.path).is_file():
            continue
        paths.append(Path(artifact.path))
        labels.append({"label": candidate.get("label") or candidate.get("id"), "path": artifact.path})
    return selected_region_records(paths, labels) if paths else []


def build_site_guided_protocol(
    state: StudyState,
    request: ProtocolFinalizationRequest,
    *,
    libexec: Path,
    created_utc: str | None = None,
) -> dict:
    """Build the final record from the persisted approval, never client-supplied regions."""
    request.validate()
    paths = finalization_paths(request)
    all_regions = _all_candidate_regions(state)
    evidence_artifact = next((item for item in state.artifacts if item.kind == "pocket_evidence"), None)
    evidence_path = Path(evidence_artifact.path) if evidence_artifact else None
    evidence = _read_json(evidence_path)
    evidence_status = evidence.get("status") if evidence else None
    evidence_record = {
        "mode": "related-structures" if evidence_artifact else "off",
        "status": evidence_status or ("unavailable" if evidence_artifact else "not_requested"),
        "record": str(evidence_path.resolve()) if evidence_path and evidence_path.is_file() else None,
        "criteria": evidence.get("query", {}),
        "ligand_site_groups": evidence.get("ligand_site_groups", []),
        "site_grouping_audit": evidence.get("site_grouping_audit", {}),
        "structural_ensemble": evidence.get("structural_ensemble", {}),
        "user_evidence_decision": {
            "choice": "labeled-box-selection",
            "selected_box_labels": [region["box_label"] for region in request.regions],
        },
        "selection_policy": "evidence_only_user_decides",
    }
    preparation = request.preparation_root
    audit = next(iter(sorted(preparation.glob("receptor/pdbfixer_audit.json"))), None)
    ccd_audit = next(iter(sorted(preparation.glob("receptor/ccd_modification_audit.json"))), None)
    removal_log = next(iter(sorted(preparation.glob("receptor/receptor_user_approved_removal.log"))), None)
    removal_record = next(iter(sorted(preparation.glob("receptor/user_approved_component_removal.txt"))), None)
    removal_manifest = next(iter(sorted(preparation.glob("receptor/user_approved_component_removal.tsv"))), None)
    removed = _read_removal_manifest(removal_manifest)
    receptor_preparation = {
        "pdbfixer_audit": str(audit) if audit else None,
        "ccd_modification_audit": str(ccd_audit) if ccd_audit else None,
        "user_approved_component_removal": bool(removal_record),
        "user_approved_component_removal_log": str(removal_log) if removal_log else None,
        "user_approved_component_removal_record": str(removal_record) if removal_record else None,
        "user_approved_component_removal_manifest": str(removal_manifest) if removal_manifest else None,
        "user_approved_removed_components": removed,
        "receptor_modification_warning": build_receptor_modification_warning(
            removed, bool(removal_record),
        ),
    }
    version = _package_version(libexec)
    detection_path = preparation / "cavity" / "pocket_detection_provenance.json"
    pocket_detection = json.loads(detection_path.read_text()) if detection_path.is_file() else {
        "engine": "fpocket", "provenance": "legacy retained preparation",
    }
    detector = pocket_detection.get("engine", "fpocket")
    software = {
        "docking_universal": version,
        "python": sys.version.split()[0],
        "rdkit": _version("rdkit"),
        "molscrub": _version("molscrub"),
        "meeko": _version("meeko"),
        "pdbfixer": _version("pdbfixer"),
        detector: str(pocket_detection.get("engine_version") or "not recorded"),
        "openbabel": _version("openbabel"),
        "plip": _version("plip"),
        "engine_version": "recorded when screening runs",
    }
    scene = next((item.path for item in state.artifacts if item.kind == "pymol_scene"), None)
    labels = [region["box_label"] for region in request.regions]
    return build_protocol_record(ProtocolRecordInputs(
        protocol_type="site-guided-exploratory",
        target=request.target,
        site_anchor=Path(str(request.regions[0]["box"])).stem,
        evidence_basis=(
            "User-selected labeled docking boxes: " + ", ".join(labels)
            + f". {detector} pocket predictions and related-structure ligand positions remain separately auditable."
        ),
        created_utc=created_utc or datetime.now(timezone.utc).isoformat(),
        engine=request.settings.engine,
        software=software,
        region_definition="predicted_pocket" if detector != "fpocket" else "fpocket",
        fpocket_selection="reviewed" if detector == "fpocket" else None,
        pocket_evidence=evidence_record,
        selected_residues=[],
        engine_selection={"selected_engine": request.settings.engine, "reason": "user selected in GUI"},
        parameters=request.settings.protocol_parameters(),
        receptor_pdbqt=request.receptor_pdbqt,
        receptor_pdb=request.receptor_pdb,
        regions=request.regions,
        selectable_boxes=all_regions or list(request.regions),
        docking_box=dict(request.regions[0]["geometry"]),
        receptor_preparation=receptor_preparation,
        receptor_preparation_summary=_preparation_summary(preparation),
        cavity_score_threshold_used=state.workflow_data.get("cavity_score_threshold_used"),
        pocket_review_scene=scene,
        bundle_file_name=paths.bundle.name,
        pocket_detection=pocket_detection,
        receptor_state_sensitivity=state.workflow_data.get("receptor_state_sensitivity"),
    ))


def finalize_site_guided_protocol(
    state: StudyState,
    request: ProtocolFinalizationRequest,
    *,
    libexec: Path | str,
    command_runner: Callable[[list[str]], None] | None = None,
    bundle_writer=create_bundle,
) -> FinalizationOutputs:
    """Render and publish final artifacts without repeating receptor preparation."""
    libexec = Path(libexec).resolve()
    paths = finalization_paths(request)
    paths.report.parent.mkdir(parents=True, exist_ok=True)
    protocol = build_site_guided_protocol(state, request, libexec=libexec)
    source_dir = request.preparation_root / "source"
    if (source_dir / "structure.cif").is_file():
        protocol["coordinate_source"] = {
            "format": "mmcif",
            "structure": str(source_dir / "structure.cif"),
            "metadata": str(source_dir / "structure-input.json"),
            "evidence": json.loads((source_dir / "structure-input.json").read_text()),
        }
    manifest = build_site_guided_report_manifest(
        protocol, request.source_structure, _package_version(libexec), protocol["software"],
    )
    paths.summary.write_text(json.dumps(manifest, indent=2) + "\n")
    # The report reads this record for retained coordinate and assembly evidence.
    # It must exist before PDF generation, not only when the bundle is published.
    write_protocol_record(paths.protocol, protocol)

    def run(command: list[str]) -> None:
        subprocess.run(command, check=True)

    execute = command_runner or run
    execute([sys.executable, str(libexec / "docking-universal-report-figures.py"), str(paths.root)])
    execute([
        sys.executable, str(libexec / "docking-universal-pdf-report.py"),
        str(paths.root), "--out", str(paths.report),
    ])
    publisher = bundle_writer
    if bundle_writer is create_bundle:
        def publisher(protocol_path, bundle_root, bundle_path):
            return create_bundle(
                protocol_path, bundle_root, bundle_path,
                additional_roots=(request.preparation_root,),
            )
    return publish_final_outputs(
        paths.protocol, protocol, paths.report, paths.bundle, paths.root, publisher,
    )
