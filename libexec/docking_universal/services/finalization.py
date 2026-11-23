"""Finalize an approved site-guided protocol from retained preparation artifacts."""

from __future__ import annotations

import json
import copy
import hashlib
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
    sha256,
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


def attach_report_reference_figures(protocol, report_root, state):
    """Retain portable figures, pairing the control images by exact pose identity."""
    from docking_universal.pose_visuals import approved_interaction_diagram, read_pose_view
    from .screening import read_protocol_record
    import shutil
    import subprocess
    import sys

    refs = {}
    report_root = Path(report_root)
    for key, name in [('docking_box_overview', 'cavity_panel_B_structure.png'),
                      ('selected_docking_boxes', 'cavity_selected_box.png'),
                      ('candidate_site_overview', 'cavity_panels_AB.png'),
                      ('candidate_site_overview_metadata', 'cavity_panels_AB.metadata.json')]:
        source = report_root / 'report' / name
        if source.is_file():
            refs[key] = {'path': str(source.resolve()), 'sha256': sha256(source)}
    scope = protocol.get('related_site_control') or {}
    expected_bundle = (scope.get('result_summary') or {}).get('source_bundle_sha256')
    if expected_bundle:
        for artifact in state.artifacts:
            source = Path(artifact.path)
            if artifact.kind not in {'control_protocol_bundle', 'protocol_bundle'} or not source.is_file() or sha256(source) != expected_bundle:
                continue
            control = read_protocol_record(source)
            top = control.get('global_top_ranked_pose') or {}
            comparison = Path(str(top.get('summary') or '')).parent
            visuals = comparison.parent.parent.parent / 'selected_visuals'
            control_root = source.parent / 'control'
            diagram = control_root / 'report' / 'control_top_ranked_plip2d.png'
            image3d = visuals / 'top_ranked_interactions.png'
            view = read_pose_view(diagram) if approved_interaction_diagram(diagram) else None
            if (view and image3d.is_file() and view['ligand'] == (comparison / 'top_score_pose.sdf').resolve()
                    and view['interactions'] == (visuals / 'top_ranked_interactions' / 'report.xml').resolve()):
                destination = report_root / 'reference_figures_source'
                destination.mkdir(parents=True, exist_ok=True)
                for key, image in [('control_top_2d', diagram),
                                   ('control_top_2d_metadata', diagram.with_suffix('.manifest.json')),
                                   ('control_top_3d', image3d)]:
                    copied = destination / (key + image.suffix)
                    shutil.copy2(image, copied)
                    if key == 'control_top_3d':
                        # Regenerate from the exact verified control interaction
                        # scene so newly bundled references use current labels.
                        scenes = sorted(view['interactions'].parent.glob('*_plip_all_in_one.pml'))
                        renderer = Path(__file__).resolve().parents[2] / 'docking-universal-render3d.py'
                        pymol = shutil.which('pymol') or str(Path(sys.executable).parent / 'pymol')
                        if len(scenes) == 1 and renderer.is_file() and Path(pymol).is_file():
                            updated = destination / 'control_top_3d_refreshed.png'
                            try:
                                result = subprocess.run([sys.executable, str(renderer), str(scenes[0]),
                                    '--out', str(updated), '--contact-residue-labels', '--pymol', pymol],
                                    capture_output=True, text=True)
                            except OSError:
                                result = None
                            if result is not None and result.returncode == 0 and updated.is_file():
                                shutil.copy2(updated, copied)
                    refs[key] = {'path': str(copied.resolve()), 'sha256': sha256(copied)}
            break
    if refs:
        protocol['report_reference_figures'] = refs


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
    from .receptor_model_history import recorded_backend_summary
    recorded = recorded_backend_summary(root / "receptor/ccd_modification_audit.json")
    if recorded:
        return recorded
    log = root / "run.log"
    text = log.read_text(errors="replace") if log.is_file() else ""
    if next(iter(sorted(root.glob("receptor/user_approved_component_removal.txt"))), None):
        return (
            "User explicitly approved removal of unmatched receptor components after safe "
            "preparation fallbacks failed; retained records identify the altered model"
        )
    if next(iter(sorted(root.glob("receptor/meeko_ptm_template_approval.json"))), None):
        return (
            "Strict Meeko used an explicitly reviewed local PTM template derived from retained "
            "CCD and GeoStd definitions; the template, approval, and validation audit are retained"
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
    candidate_groups = {}
    for candidate in state.workflow_data.get("pocket_candidates", []):
        artifact = artifacts.get(candidate.get("box_artifact_id"))
        if artifact is None or not Path(artifact.path).is_file():
            continue
        paths.append(Path(artifact.path))
        group = (candidate.get('evidence') or {}).get('site_group')
        if group:
            candidate_groups[str(Path(artifact.path).resolve())] = group
        labels.append({"label": candidate.get("label") or candidate.get("id"), "path": artifact.path,
                       "site_source": (candidate.get("evidence") or {}).get("source")})
    records = selected_region_records(paths, labels) if paths else []
    for record in records:
        group = candidate_groups.get(str(Path(record['box']).resolve()))
        if group:
            # Candidate evidence is retained for report display; this does not
            # approve it or change any selected docking geometry.
            record['site_group'] = copy.deepcopy(group)
    return records


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
    from .molecule_inspection import split_ligand_site_groups
    ligand_groups, supporting_groups = split_ligand_site_groups(evidence.get('ligand_site_groups', []))
    evidence_record = {
        "mode": "related-structures" if evidence_artifact else "off",
        "status": evidence_status or ("unavailable" if evidence_artifact else "not_requested"),
        "record": str(evidence_path.resolve()) if evidence_path and evidence_path.is_file() else None,
        "criteria": evidence.get("query", {}),
        "ligand_site_groups": ligand_groups,
        "supporting_component_site_groups": supporting_groups,
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
    meeko_template = next(iter(sorted(preparation.glob("receptor/meeko_additional_templates.json"))), None)
    meeko_template_audit = next(iter(sorted(preparation.glob("receptor/meeko_ptm_template_audit.json"))), None)
    meeko_template_approval = next(iter(sorted(preparation.glob("receptor/meeko_ptm_template_approval.json"))), None)
    removal_log = next(iter(sorted(preparation.glob("receptor/receptor_user_approved_removal.log"))), None)
    removal_record = next(iter(sorted(preparation.glob("receptor/user_approved_component_removal.txt"))), None)
    removal_manifest = next(iter(sorted(preparation.glob("receptor/user_approved_component_removal.tsv"))), None)
    removed = _read_removal_manifest(removal_manifest)
    receptor_preparation = {
        "pdbfixer_audit": str(audit) if audit else None,
        "ccd_modification_audit": str(ccd_audit) if ccd_audit else None,
        "meeko_additional_templates": str(meeko_template) if meeko_template else None,
        "meeko_ptm_template_audit": str(meeko_template_audit) if meeko_template_audit else None,
        "meeko_ptm_template_approval": str(meeko_template_approval) if meeko_template_approval else None,
        "user_approved_component_removal": bool(removal_record),
        "user_approved_component_removal_log": str(removal_log) if removal_log else None,
        "user_approved_component_removal_record": str(removal_record) if removal_record else None,
        "user_approved_component_removal_manifest": str(removal_manifest) if removal_manifest else None,
        "user_approved_removed_components": removed,
        "receptor_modification_warning": build_receptor_modification_warning(
            removed, bool(removal_record),
        ),
    }
    from .receptor_model_history import attach_retained_history
    receptor_preparation = attach_retained_history(receptor_preparation, preparation, request.receptor_pdbqt)
    from .site_reference_review import attach
    receptor_preparation = attach(receptor_preparation, state,
                                 hashlib.sha256(request.receptor_pdbqt.read_bytes()).hexdigest(), request.regions)
    version = _package_version(libexec)
    detection_path = preparation / "cavity" / "pocket_detection_provenance.json"
    pocket_detection = json.loads(detection_path.read_text()) if detection_path.is_file() else {
        "engine": "fpocket", "provenance": "legacy retained preparation",
    }
    setup = state.workflow_data.get("study_setup") or {}
    reference_only = setup.get("site_mode") == "ligand" and not setup.get("predict_pockets_with_ligand")
    if reference_only:
        # Preserve a historical unwanted detector run as history, not as the
        # origin or supporting evidence of the approved ligand-defined site.
        historical = pocket_detection if pocket_detection.get("engine") != "none" else None
        pocket_detection = {"engine": "none", "site_definition": "input_bound_ligand",
                            "prediction_requested": False, "used_for_site_definition": False}
        if historical:
            pocket_detection["retained_legacy_detection"] = historical
        else:
            pocket_detection["prediction_executed"] = False
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
    if receptor_preparation.get('backend_identity'):
        software['adfrsuite'] = receptor_preparation['backend_identity']['version']
    scene = next((item.path for item in state.artifacts if item.kind == "pymol_scene"), None)
    if reference_only:
        scene = None
        software.pop("none", None)
    labels = [region["box_label"] for region in request.regions]
    record = build_protocol_record(ProtocolRecordInputs(
        protocol_type="site-guided-exploratory",
        target=request.target,
        site_anchor=Path(str(request.regions[0]["box"])).stem,
        evidence_basis=(
            "User-selected labeled docking boxes: " + ", ".join(labels)
            + (". Pocket prediction was not requested. Input-ligand and independent related-structure sites remain separately auditable."
               if reference_only else f". {detector} pocket predictions and related-structure ligand positions remain separately auditable.")
        ),
        created_utc=created_utc or datetime.now(timezone.utc).isoformat(),
        engine=request.settings.engine,
        software=software,
        region_definition="ligand_defined" if reference_only else ("predicted_pocket" if detector != "fpocket" else "fpocket"),
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
    scope = state.workflow_data.get("control_site_review")
    if scope:
        record["related_site_control"] = dict(scope)
        # Retain the measured control result with the protocol, so future
        # reports do not depend on a path to this machine's study folder.
        from .screening import read_protocol_record
        for artifact in state.artifacts:
            if artifact.kind not in {'control_protocol_bundle', 'protocol_bundle'}:
                continue
            source = Path(artifact.path)
            if not source.is_file() or (artifact.sha256 and sha256(source) != artifact.sha256):
                continue
            try:
                control = read_protocol_record(source)
            except ValueError:
                continue
            locked = control.get('locked_inputs') or {}
            tested = next((r for r in request.regions if r.get('box_label') == scope.get('tested_box_label')), None)
            if (not tested or control.get('control_status') != 'approved'
                    or locked.get('box_sha256') != tested.get('box_sha256')
                    or locked.get('receptor_sha256') != sha256(request.receptor_pdbqt)):
                continue
            top = control.get('global_top_ranked_pose') or {}
            closest = control.get('global_best_sampled_pose') or {}
            record['related_site_control']['result_summary'] = {
                'ligand': (control.get('control_evidence') or {}).get('compound'),
                'engine': control.get('engine'),
                'lowest_energy_kcal_per_mol': top.get('top_score_affinity_kcal_per_mol'),
                'lowest_energy_pose_rmsd_angstrom': top.get('top_score_rmsd_angstrom'),
                'lowest_rmsd_angstrom': closest.get('best_rmsd_angstrom'),
                'acceptance': control.get('acceptance') or {},
                'parameters': control.get('parameters') or {},
                'seed_results': [{'seed': item.get('seed'), 'sampling_pass': item.get('sampling_pass'),
                    'ranking_pass': item.get('ranking_pass'),
                    'top_energy_kcal_per_mol': (item.get('global_top_ranked_pose') or {}).get('top_score_affinity_kcal_per_mol'),
                    'top_pose_rmsd_angstrom': (item.get('global_top_ranked_pose') or {}).get('top_score_rmsd_angstrom'),
                    'best_rmsd_angstrom': (item.get('global_best_sampled_pose') or {}).get('best_rmsd_angstrom')}
                    for item in control.get('seed_results') or []],
                'source_bundle_sha256': sha256(source),
                'receptor_sha256': locked.get('receptor_sha256'),
                'box_sha256': locked.get('box_sha256'),
            }
            import csv
            cluster_csv = source.parent / 'control' / 'report' / 'control_panel_A_cluster.csv'
            if cluster_csv.is_file():
                with cluster_csv.open(newline='') as handle:
                    record['related_site_control']['result_summary']['clusters'] = list(csv.DictReader(handle))
            break
        record["evidence_basis"] += (
            " A separate pose-recovery control concerns only " + str(scope["tested_box_label"])
            + "; this selected-site protocol remains explicitly exploratory."
        )
    if any(region.get("site_source") == "input_bound_ligand" for region in request.regions):
        record["evidence_basis"] += (
            " B1 is defined by the exact input bound ligand, not a predicted pocket or new independent evidence."
        )
    return record


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
    from .protein_identity import read_protein_identity
    protocol["target_identity"] = read_protein_identity(request.source_structure)
    source_dir = request.preparation_root / "source"
    if (source_dir / "structure.cif").is_file():
        protocol["coordinate_source"] = {
            "format": "mmcif",
            "structure": str(source_dir / "structure.cif"),
            "metadata": str(source_dir / "structure-input.json"),
            "evidence": json.loads((source_dir / "structure-input.json").read_text()),
        }
        protocol["target_identity"] = read_protein_identity(source_dir / "structure.cif")
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
    attach_report_reference_figures(protocol, paths.root, state)
    write_protocol_record(paths.protocol, protocol)
    execute([
        sys.executable, str(libexec / "docking-universal-pdf-report.py"),
        str(paths.root), "--out", str(paths.report), "--reuse-figures",
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
