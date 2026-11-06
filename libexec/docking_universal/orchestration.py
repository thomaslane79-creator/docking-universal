"""Asynchronous host-owned orchestration for the first GUI protocol workflow."""

from __future__ import annotations

import threading
import time
import sys
import json
import shutil
import os
from dataclasses import replace
from pathlib import Path
from typing import Any
from uuid import uuid4

from .application import ActiveStageError, StudyController
from .events import EventType
from .models import ArtifactRecord, CompletionStatus, ScientificAuthority, utc_now
from .processes import ProcessRequest
from .stage_feedback import control_feedback, finalization_feedback, screening_feedback
from .protocol_finalization import FinalizationSettings, request_from_study, sha256
from .services.finalization import finalization_paths
from .services.screening import build_screening_plan, discover_screening_artifacts
from .services.screening import read_protocol_record
from docking_universal_bundle import CONTROL_VALIDATED, protocol_type
from .services.pose_interactions import build_pose_interaction_plan, validate_pose_interaction_outputs
from .services.pocket_review import PocketReviewInputs, PocketReviewService, ordered_pocket_boxes
from .services.preparation import (
    ReceptorPreparationOptions,
    ReceptorPreparationService,
    build_receptor_preparation_plan,
)
from .services.preparation_interventions import (
    neutral_sensitivity_assignments,
    read_intervention_record,
    template_assignments,
)
from .services.structure_input import normalize_structure_input
from .services.bound_ligands import detect_bound_ligands
from .services.geostd_components import available_library, reduce2_required_component_ids


class ProtocolWorkflowRunner:
    """Start fixed scientific stages without blocking the host command loop."""

    def __init__(self, controller: StudyController, preparation_executable: Path | str):
        self.controller = controller
        self.preparation_executable = Path(preparation_executable).resolve()
        self._guard = threading.Lock()
        self._cancellations: dict[str, threading.Event] = {}
        self._threads: dict[str, threading.Thread] = {}

    def start_control_validation(
        self, study_id: str, payload: dict[str, Any], *, request_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Run the existing noninteractive known-ligand control through the host."""
        state = self.controller.get_study(study_id)
        prior = next((job for job in state.jobs if job.request_id == request_id), None)
        if prior:
            return {"job_id": prior.id, "stage": prior.stage, "replayed": True}
        if state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError(
                f"Study {study_id} changed from revision {expected_revision} to {state.revision}"
            )
        self._assert_no_active_stage()
        if (state.workflow_data.get("study_setup") or {}).get("site_review_first"):
            return self._start_reviewed_control(study_id, state, payload, request_id=request_id)
        if state.jobs or state.workflow_data.get("study_setup"):
            raise ActiveStageError("A known-ligand control requires a new study")
        allowed = {"input_structure", "output_directory", "ligand_resname", "ligand_chain_id",
                   "ligand_residue_number", "ligand_insertion_code", "engine", "control_tier",
                   "geostd_library", "pdb_pocket_evidence", "pocket_engine", "predict_pockets_with_ligand"}
        allowed.add("meeko_template_file")
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown control options: {', '.join(sorted(unknown))}")
        source = Path(str(payload.get("input_structure") or "")).resolve()
        output = Path(str(payload.get("output_directory") or "")).resolve()
        if not payload.get("output_directory"):
            raise ValueError("A control output directory is required")
        if not source.is_file() or source.suffix.lower() not in {".pdb", ".cif", ".mmcif"}:
            raise FileNotFoundError("A deposited PDB or mmCIF complex is required for control redocking")
        if output.exists() and not output.is_dir():
            raise ValueError("Control study output must be a directory")
        if (output / "preparation").exists() or (output / "control").exists():
            raise ValueError("Control study already contains preparation/control outputs; choose a new study folder")
        if payload.get("geostd_library"):
            geostd_library = Path(str(payload["geostd_library"])).resolve()
        else:
            geostd_library = available_library(reduce2_required_component_ids(source))
        if geostd_library is None or not geostd_library.is_dir():
            raise FileNotFoundError(
                "Required GeoStd components are unavailable locally; approve the exact "
                "component request in the GUI or install the offline library"
            )
        if payload.get("ligand_insertion_code"):
            raise ValueError("The control runner cannot identify insertion-coded ligands exactly")
        ligand_id = ":".join(str(payload.get(key) or "").strip() for key in (
            "ligand_resname", "ligand_chain_id", "ligand_residue_number",
        ))
        if not all(ligand_id.split(":")):
            raise ValueError("Choose an exact deposited ligand instance for the control")
        instances = [instance for candidate in detect_bound_ligands(source)
                     for instance in candidate.instances]
        if not any(
            (item.resname, item.chain_id, item.residue_number) == tuple(ligand_id.split(":"))
            for item in instances
        ):
            raise ValueError(f"Selected control ligand is not present in the supplied structure: {ligand_id}")
        engine = str(payload.get("engine") or "vina")
        tier = str(payload.get("control_tier") or "quick")
        if engine not in {"vina", "qvinaw"} or tier not in {
            "quick", "repeatability", "broader", "conformers", "robust",
        }:
            raise ValueError("Unsupported control engine or calibration tier")
        script = self.preparation_executable.with_name("docking-universal-run.py")
        if not script.is_file():
            raise FileNotFoundError(f"Control workflow is missing: {script}")
        return self.start_preparation(
            study_id, {
                "input_pdb": str(source), "working_directory": str(output / "preparation"),
                "site_mode": "ligand", "ligand_resname": payload["ligand_resname"],
                "ligand_chain_id": payload["ligand_chain_id"],
                "ligand_residue_number": payload["ligand_residue_number"],
                "feedback_level": "concise", "cavity_mode": 1, "max_pockets": 0,
                "center_mode": "centroid", "centroid_mode": 1,
                "pocket_engine": payload.get("pocket_engine", "p2rank"),
                "predict_pockets_with_ligand": payload.get("predict_pockets_with_ligand", False),
                "geostd_library": str(geostd_library),
                "meeko_template_file": payload.get("meeko_template_file"),
                "pdb_pocket_evidence": payload.get("pdb_pocket_evidence", "related-structures"),
            }, request_id=request_id, expected_revision=expected_revision,
            control_setup={"pathway": "control", "site_review_first": True,
                           "engine": engine, "control_tier": tier,
                           "control_output_directory": str(output / "control")},
        )

    def _start_reviewed_control(self, study_id, state, payload, *, request_id):
        """Continue only after an explicit region decision; never reprepare."""
        from .services.control_review import reviewed_control_inputs
        if payload:
            raise ValueError("Reviewed control uses the retained setup; no replacement inputs/settings are accepted")
        if state.workflow_data.get("latest_control_status"):
            raise ActiveStageError("This control already has a retained result; review it before starting another study")
        reviewed = reviewed_control_inputs(state)
        setup = state.workflow_data["study_setup"]
        output = Path(setup["control_output_directory"])
        if output.exists():
            raise ValueError("Control output already exists; completed/partial work is not overwritten")
        script = self.preparation_executable.with_name("docking-universal-run.py")
        record_path = output.parent / "reviewed_control_inputs.json"
        record_path.write_text(json.dumps(reviewed, indent=2) + "\n")
        def register(current):
            current.workflow_data["control_site_review"] = {
                "tested_box_label": reviewed["tested_box_label"],
                "untested_box_labels": reviewed["untested_box_labels"],
                "untested_receptor_states": reviewed["untested_receptor_states"],
                "record": str(record_path), "record_sha256": sha256(record_path),
                "status": "ready_for_control", "approval_id": reviewed["approval_id"],
            }
        retained, _ = self.controller.store.update(study_id, register, expected_revision=state.revision)
        process = ProcessRequest(
            command=(sys.executable, str(script), "control", "--complex",
                     reviewed["assets"]["source_pdb"]["path"], "--control-ligand-id", reviewed["ligand_id"],
                     "--out", str(output), "--engine", setup["engine"], "--control-tier", setup["control_tier"],
                     "--reviewed-control-inputs", str(record_path),
                     "--reviewed-control-inputs-sha256", sha256(record_path),
                     "--non-interactive"),
            cwd=output.parent,
            environment={
                **os.environ,
                "DOCKING_UNIVERSAL_GEOSTD": setup["geostd_library"],
                "DOCKING_UNIVERSAL_LOG_MODE": "file",
                "MEEKO_ADD_TEMPLATES": (
                    str(Path(setup["meeko_template_file"]).resolve())
                    if setup.get("meeko_template_file") else ""
                ),
            },
            log_directory=output.parent / f".{output.name}.docking-universal-application-logs",
            log_name="known-ligand-control", check=False,
        )
        cancellation = threading.Event()

        def work() -> None:
            try:
                result = ReceptorPreparationService(self.controller).jobs.run(
                    study_id, "control_validation", process, cancel_event=cancellation,
                    progress_probe=lambda: control_feedback(output),
                    request_id=request_id, expected_revision=retained.revision,
                )
                self._register_control_outputs(study_id, output, result.status.value)
            except Exception as exc:
                self._record_orchestration_failure(study_id, exc)
            finally:
                with self._guard:
                    self._cancellations.pop(study_id, None)
                    self._threads.pop(study_id, None)

        thread = threading.Thread(target=work, name=f"du-control-{study_id}", daemon=True)
        with self._guard:
            if self._threads:
                raise ActiveStageError("Another scientific workflow is already running")
            self._cancellations[study_id] = cancellation
            self._threads[study_id] = thread
            thread.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            latest = self.controller.get_study(study_id)
            job = next((item for item in latest.jobs if item.request_id == request_id), None)
            if job:
                return {"job_id": job.id, "stage": job.stage, "output": str(output)}
            if not thread.is_alive():
                break
            time.sleep(0.01)
        raise RuntimeError("Control worker did not persist its job start")

    def _register_control_outputs(self, study_id: str, output: Path, status: str) -> None:
        bundles = []
        state = self.controller.get_study(study_id)
        reviewed_scope = state.workflow_data.get("control_site_review")
        reviewed = None
        if reviewed_scope:
            from .services.control_review import read_reviewed_control_inputs
            reviewed = read_reviewed_control_inputs(reviewed_scope["record"],
                                                    expected_sha256=reviewed_scope["record_sha256"])
        if status == "completed":
            for candidate in sorted(output.glob("*.duprotocol")):
                try:
                    record = read_protocol_record(candidate)
                except ValueError:
                    continue
                if protocol_type(record) == CONTROL_VALIDATED:
                    if reviewed:
                        locked = record.get("locked_inputs") or {}
                        if (locked.get("receptor_sha256") != reviewed["assets"]["receptor_pdbqt"]["sha256"]
                                or locked.get("box_sha256") != reviewed["assets"]["box"]["sha256"]
                                or record.get("engine") != reviewed["engine"]):
                            raise ValueError("Control output does not match the reviewed receptor, box and engine")
                    bundles.append(candidate)
        reports = sorted((output / "report").glob("*.pdf"))
        manifest = output / "study_manifest.json"

        def mutation(state) -> None:
            scope = state.workflow_data.get("control_site_review")
            extra_sites = bool(scope and (scope.get("untested_box_labels") or scope.get("untested_receptor_states")))
            known = {artifact.id for artifact in state.artifacts}
            for kind, paths in (("control_protocol_bundle" if extra_sites else "protocol_bundle", bundles),
                                ("control_report" if extra_sites else "final_report", reports),
                                ("control_manifest", [manifest] if manifest.is_file() else []),
                                ("control_log", sorted(output.glob("control/run.log")))):
                for path in paths:
                    digest = sha256(path)
                    identity = f"control-{kind}-{digest[:16]}"
                    if identity not in known:
                        state.artifacts.append(ArtifactRecord(
                            identity, kind, str(path.resolve()), digest,
                            "Known-ligand control output" if kind != "protocol_bundle"
                            else "Pose-recovery-approved reusable protocol",
                        ))
                        known.add(identity)
            state.workflow_data["latest_control_output"] = str(output)
            state.workflow_data["latest_control_status"] = (
                "approved" if status == "completed" and bundles else
                "not_approved" if status == "completed" else status
            )
            if reviewed is not None:
                state.scientific_authority = (
                    ScientificAuthority.CONTROL_APPROVED if bundles and not extra_sites
                    else ScientificAuthority.EXPLORATORY_NO_CONTROL
                )
            if scope is not None:
                scope["status"] = state.workflow_data["latest_control_status"]
                scope["all_selected_sites_validated"] = bool(bundles and not extra_sites)
                scope["scope_warning"] = (
                    "A passing control covers only " + str(scope["tested_box_label"])
                    + "; untested sites/receptor states remain exploratory: "
                    + ", ".join(scope["untested_box_labels"] + scope.get("untested_receptor_states", []))
                    if extra_sites else "Control authority covers only its tested receptor, site, engine and settings."
                )
            StudyController._event(
                state, EventType.ARTIFACT_CREATED,
                "Known-ligand control result retained",
                explanation=("A completed calculation is not a validated protocol unless a "
                             "pose-recovery-approved bundle was produced."),
                technical={"output": str(output), "status": status,
                           "approved_bundle_count": len(bundles)},
                mandatory=status != "completed" or not bundles,
            )
        self.controller.store.update(study_id, mutation)

    def start_preparation(
        self,
        study_id: str,
        payload: dict[str, Any],
        *,
        request_id: str,
        expected_revision: int,
        control_setup: dict | None = None,
    ) -> dict[str, Any]:
        state = self.controller.get_study(study_id)
        prior = next((job for job in state.jobs if job.request_id == request_id), None)
        if prior:
            return {"job_id": prior.id, "stage": prior.stage, "replayed": True}
        if state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError(
                f"Study {study_id} changed from revision {expected_revision} to {state.revision}"
            )
        if any(
            job.stage == "preparation_and_pocket_detection" and job.status.value == "completed"
            for job in state.jobs
        ):
            raise ActiveStageError(
                "Receptor preparation is already complete for this study; resume its current workflow stage"
            )
        if any(job.stage == 'site_exploration' and job.status.value == 'completed' for job in state.jobs):
            raise ActiveStageError('Site exploration is already complete; prepare the reviewed receptor instead')
        self._assert_no_active_stage()
        allowed = {
            "input_pdb", "working_directory", "site_mode", "ligand_resname",
            "ligand_chain_id", "ligand_residue_number", "ligand_insertion_code",
            "ligand_altloc",
            "feedback_level", "cavity_mode", "max_pockets", "center_mode",
            "centroid_mode", "pdbfixer", "preparation_backend", "pocket_engine",
            "meeko_templates",
            "meeko_template_file",
            "geostd_library",
            "pdb_pocket_evidence",
            "predict_pockets_with_ligand",
            "explore_sites_first",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown preparation options: {', '.join(sorted(unknown))}")
        values = dict(payload)
        explore_first = values.pop('explore_sites_first', False)
        if not isinstance(explore_first, bool):
            raise ValueError('Explore sites first must be a boolean')
        if explore_first and control_setup:
            raise ValueError('Coordinate-first control validation has not been accepted yet')
        for name in ("input_pdb", "working_directory"):
            if name not in values:
                raise ValueError(f"Preparation option is required: {name}")
            values[name] = Path(values[name])
        if values.get("geostd_library"):
            values["geostd_library"] = Path(values["geostd_library"])
        if values.get("meeko_template_file"):
            values["meeko_template_file"] = Path(values["meeko_template_file"])
        evidence_mode = values.pop("pdb_pocket_evidence", "related-structures")
        if evidence_mode not in {"related-structures", "off"}:
            raise ValueError("PDB pocket evidence must be related-structures or off")
        options = ReceptorPreparationOptions(**values)
        plan = build_receptor_preparation_plan(self.preparation_executable, options)
        if explore_first:
            from .services.site_exploration import exploration_request, exploration_root
            exploration_request(plan, options)  # Validate worker/engine before locking setup.
            if exploration_root(plan).exists():
                raise ValueError('Site-review output already exists and will not be overwritten')
        setup_record = {
            "input_pdb": str(plan.structure_input.engine_pdb_path),
            "input_structure": str(plan.structure_input.source_path),
            "input_structure_format": plan.structure_input.source_format,
            "input_structure_sha256": plan.structure_input.source_sha256,
            "structure_input_metadata": str(plan.structure_input.metadata_path),
            "biological_assemblies": list(plan.structure_input.assemblies),
            "legacy_pdb_derived": plan.structure_input.derived_for_legacy_engine,
            "working_directory": str(options.working_directory.resolve()),
            "site_mode": options.site_mode,
            "ligand_resname": options.ligand_resname,
            "ligand_chain_id": options.ligand_chain_id,
            "ligand_residue_number": options.ligand_residue_number,
            "ligand_insertion_code": options.ligand_insertion_code,
            "ligand_altloc": options.ligand_altloc,
            "feedback_level": options.feedback_level,
            "cavity_mode": options.cavity_mode,
            "max_pockets": options.max_pockets,
            "center_mode": options.center_mode,
            "centroid_mode": options.centroid_mode,
            "pdbfixer": options.pdbfixer,
            "preparation_backend": options.preparation_backend,
            "pocket_engine": options.pocket_engine,
            "predict_pockets_with_ligand": options.predict_pockets_with_ligand,
            "meeko_templates": options.meeko_templates,
            "meeko_template_file": (
                str(options.meeko_template_file.resolve()) if options.meeko_template_file else None
            ),
            "geostd_library": str(options.geostd_library.resolve()) if options.geostd_library else None,
            "pdb_pocket_evidence": evidence_mode,
            "accepted_at_revision": state.revision,
        }
        if explore_first:
            setup_record['explore_sites_first'] = True
        if control_setup:
            setup_record.update(control_setup)

        def retain_setup(latest) -> None:
            existing = latest.workflow_data.get("study_setup")
            comparable_existing = dict(existing or {})
            comparable_new = dict(setup_record)
            comparable_existing.pop("accepted_at_revision", None)
            comparable_new.pop("accepted_at_revision", None)
            if existing and comparable_existing != comparable_new:
                raise ValueError(
                    "Study setup is already locked; create a new study to use different inputs"
                )
            if not existing:
                latest.workflow_data["study_setup"] = setup_record
                if evidence_mode == "off":
                    latest.workflow_data["pdb_pocket_evidence"] = {
                        "mode": "off", "status": "disabled_by_user",
                        "detail": "Public-PDB evidence lookup was disabled; local site review remains available.",
                    }

        retained_state, _unused = self.controller.store.update(
            study_id, retain_setup, expected_revision=expected_revision,
        )
        preparation_revision = retained_state.revision
        cancellation = threading.Event()

        def work() -> None:
            try:
                if explore_first:
                    from .services.site_exploration import SiteExplorationService, exploration_root
                    result = SiteExplorationService(self.controller).run(
                        study_id, plan, options, cancel_event=cancellation,
                        request_id=request_id, expected_revision=preparation_revision)
                    review_root = exploration_root(plan)
                else:
                    result = ReceptorPreparationService(self.controller).run(
                        study_id, plan, cancel_event=cancellation,
                        request_id=request_id, expected_revision=preparation_revision,
                    )
                    review_root = plan.output_root
                if result.status.value == "completed":
                    if evidence_mode == "related-structures":
                        self._collect_pdb_pocket_evidence(study_id, replace(plan, output_root=review_root))
                    self._start_review(study_id, review_root)
            except Exception as exc:
                self._record_orchestration_failure(study_id, exc)
            finally:
                with self._guard:
                    self._cancellations.pop(study_id, None)
                    self._threads.pop(study_id, None)

        thread = threading.Thread(target=work, name=f"du-workflow-{study_id}", daemon=True)
        with self._guard:
            if self._threads:
                raise ActiveStageError("Another scientific workflow is already running")
            self._cancellations[study_id] = cancellation
            self._threads[study_id] = thread
            thread.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            latest = self.controller.get_study(study_id)
            job = next((item for item in latest.jobs if item.request_id == request_id), None)
            if job:
                return {"job_id": job.id, "stage": job.stage,
                        "output_root": str(exploration_root(plan) if explore_first else plan.output_root)}
            if not thread.is_alive():
                break
            time.sleep(0.01)
        raise RuntimeError("Preparation worker did not persist its job start")

    def preview_receptor_changes(self, study_id, choices, *, expected_revision):
        """Inspect exact proposed changes without starting work or approving science."""
        from .services.receptor_model_review import preview_changes, inspect_source, digest as sha256_bytes
        from .protocol_finalization import approved_regions_from_study
        state = self.controller.get_study(study_id)
        if state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError('Study changed before receptor-model review')
        self._assert_no_active_stage()
        setup = state.workflow_data.get('study_setup') or {}
        if setup.get('explore_sites_first'):
            if (state.pending_decisions or state.workflow_data.get('receptor_parameterization_status')
                    not in {'not_started', 'failed'}):
                raise ValueError('Review sites first; model changes require an unprepared or safely failed receptor')
            regions, _ = approved_regions_from_study(state)
            from .services.site_exploration import read_exploration
            read_exploration(Path(state.workflow_data['site_exploration_root']))
            sources = {a.kind: a for a in state.artifacts if a.kind in {
                'source_receptor_structure', 'normalized_receptor_input'}}
            if len(sources) != 2 or any(not a.sha256 or sha256(Path(a.path)) != a.sha256 for a in sources.values()):
                raise ValueError('Original receptor input changed before model review')
            original_hash = sources['source_receptor_structure'].sha256
            source_path = sources['normalized_receptor_input'].path
            review_stage = 'reviewed_sites'
            failed_job_id = None
        else:
            from .services.failed_preparation_recovery import failed_preparation_job, recovery_input
            failed_job_id = failed_preparation_job(state).id
            normalized = recovery_input(state)
            original_hash = normalized.source_sha256
            source_path = str(normalized.engine_pdb_path)
            regions = []
            review_stage = 'failed_preparation'
        backend = choices.get('preparation_backend') if isinstance(choices, dict) else None
        backend = backend or (setup.get('preparation_backend') if setup.get('preparation_backend') in {'meeko', 'adfr'} else 'meeko')
        context = {'study_id': study_id, 'revision': state.revision,
                   'original_input_sha256': original_hash, 'review_stage': review_stage,
                   'failed_preparation_job_id': failed_job_id, 'preparation_backend': backend,
                   'locked_setup_sha256': sha256_bytes(json.dumps(setup, sort_keys=True, separators=(',', ':')).encode()),
                   'selected_regions': [{'label': r['box_label'], 'sha256': r['box_sha256']} for r in regions]}
        if setup.get('site_mode') == 'ligand':
            context['bound_reference'] = dict(resname=str(setup.get('ligand_resname') or ''),
                chain=str(setup.get('ligand_chain_id') or ''), number=str(setup.get('ligand_residue_number') or ''),
                insertion_code=str(setup.get('ligand_insertion_code') or ''))
        preview, derivative = preview_changes(source_path, choices, context=context)
        preview.update(source_path=str(source_path), preparation_backend=backend,
                       review_stage=review_stage, box_review_pending=not bool(regions))
        # Coordinates and distances are local review evidence, not an exclusion recommendation.
        from .services.preparation_site_issues import for_box
        _, _, atoms, _ = inspect_source(source_path)
        selected_rows = list(choices.get('exclusions', [])) + list(choices.get('alternate_locations', []))
        selected_rows.extend(row for change in preview['changes'] for row in change.get('generated_atoms', []))
        selected_rows.extend(row for change in preview['changes'] for row in change.get('rejected_inferred_edges', []))
        selected_rows.extend(endpoint for change in preview['changes']
                             for edge in change.get('rejected_inferred_interresidue_edges', [])
                             for endpoint in (edge['first'], edge['second']))
        selected = {tuple(row.get(k, '') for k in ('resname', 'chain', 'number', 'insertion_code'))
                    for row in selected_rows}
        residues = [{'residue': key[0], 'chain': key[1], 'number': key[2] + key[3],
                     'coordinates': [tuple(float(line[i:i+8]) for i in (30, 38, 46)) for line in lines]}
                    for key, lines in atoms.items() if key in selected]
        generated = {(tuple(row.get(k, '') for k in ('resname', 'chain', 'number', 'insertion_code')), row['atom_name'])
                     for change in preview['changes'] for row in change.get('generated_atoms', [])}
        for line in derivative.decode('utf-8').splitlines():
            if not line.startswith(('ATOM  ', 'HETATM')):
                continue
            key = (line[17:20].strip(), line[21:22].strip(), line[22:26].strip(), line[26:27].strip())
            if (key, line[12:16].strip()) in generated:
                row = next(r for r in residues if (r['residue'], r['chain'], r['number']) ==
                           (key[0], key[1], key[2] + key[3]))
                row['coordinates'].append(tuple(float(line[i:i+8]) for i in (30, 38, 46)))
        if preview.get('connectivity_execution'):
            from .services.reviewed_connectivity import validate_review
            from .services.receptor_model_review import inspect_source_data, digest
            execution = preview['connectivity_execution']
            review, graph_change = validate_review(execution['path'], preview['model_input_sha256'])
            if graph_change['review_sha256'] != execution['sha256']:
                raise ValueError('Connectivity review changed during box preview')
            retained = review['retained_stage_files'][review['backend_input']]
            data = Path(retained['path']).read_bytes()
            if digest(data) != retained['sha256']:
                raise ValueError('Saved coordinate stage changed during box preview')
            _, _, backend_atoms, _ = inspect_source_data(data)
            graph_keys = {tuple(row[k] for k in ('resname', 'chain', 'number', 'insertion_code')) for row in review['edges']}
            endpoint_names = {}
            for edge in review.get('inter_residue_edges', []):
                for endpoint in (edge['first'], edge['second']):
                    key = tuple(endpoint[k] for k in ('resname', 'chain', 'number', 'insertion_code'))
                    graph_keys.add(key); endpoint_names.setdefault(key, set()).add(endpoint['atom_name'])
            for key in graph_keys:
                row = next(r for r in residues if (r['residue'], r['chain'], r['number']) ==
                           (key[0], key[1], key[2] + key[3]))
                row['coordinates'] = [tuple(float(line[i:i+8]) for i in (30, 38, 46))
                                      for line in backend_atoms[key] if line[76:78].strip().upper() not in {'H', 'D'}
                                      or line[12:16].strip() in endpoint_names.get(key, set())]
            preview['connectivity_coordinate_source_sha256'] = retained['sha256']
        preview['selected_box_review'] = [{**for_box({'residues': residues}, r['geometry']), 'label': r['box_label'],
            'warning': 'Distances describe the proposed changes relative to each reviewed box; they do not grant permission to ignore them.'}
            for r in regions]
        return preview

    def prepare_reviewed_receptor(self, study_id, *, request_id, expected_revision, model_changes=None):
        """Explicit second stage: selected sites survive a preparation failure."""
        from dataclasses import fields
        from .services.site_exploration import read_exploration, parameterization_plan
        state = self.controller.get_study(study_id)
        prior = next((j for j in state.jobs if j.request_id == request_id), None)
        if prior:
            return {'job_id': prior.id, 'stage': prior.stage, 'replayed': True}
        if state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError('Study changed before preparing the reviewed receptor')
        setup = state.workflow_data.get('study_setup') or {}
        if model_changes is not None and not setup.get('explore_sites_first'):
            self._assert_no_active_stage()
            from .services.failed_preparation_recovery import prepare_failed_receptor_changes
            return prepare_failed_receptor_changes(self, state, model_changes,
                request_id=request_id, expected_revision=expected_revision)
        if not setup.get('explore_sites_first') or not state.selected_pocket_ids or state.pending_decisions:
            raise ValueError('Review and approve docking regions before receptor preparation')
        self._assert_no_active_stage()
        preparation_status = state.workflow_data.get('receptor_parameterization_status')
        if preparation_status != 'not_started' and not (model_changes and preparation_status == 'failed'):
            raise ValueError('Preparation was already attempted; review its retained evidence before any new attempt')
        root = Path(state.workflow_data['site_exploration_root'])
        from .protocol_finalization import approved_regions_from_study
        approved_regions_from_study(state)
        for artifact in state.artifacts:
            if artifact.kind in {'source_receptor_structure', 'normalized_receptor_input',
                                  'site_review_receptor_structure', 'site_exploration_record'}:
                if not artifact.sha256 or sha256(Path(artifact.path)) != artifact.sha256:
                    raise ValueError('Registered site-review input changed before preparation')
        read_exploration(root)
        keys = {f.name for f in fields(ReceptorPreparationOptions)}
        values = {key: value for key, value in setup.items() if key in keys}
        # Keep the original mmCIF handoff/identity, rather than treating its
        # normalized legacy PDB as a newly chosen deposited input.
        values['input_pdb'] = setup.get('input_structure', values['input_pdb'])
        for key in ('input_pdb', 'working_directory', 'geostd_library', 'meeko_template_file'):
            if values.get(key):
                values[key] = Path(values[key])
        plan = parameterization_plan(build_receptor_preparation_plan(
            self.preparation_executable, ReceptorPreparationOptions(**values)))
        model_record = model_root = model_record_sha256 = None
        if model_changes is not None:
            from .services.receptor_model_review import preview_changes, write_model, retain_reviewed_receptor_input
            if (not isinstance(model_changes, dict) or set(model_changes) != {
                    'choices', 'preview_sha256', 'actor', 'rationale'}
                    or any(not isinstance(model_changes[k], str) or not model_changes[k].strip()
                           for k in ('preview_sha256', 'actor', 'rationale'))):
                raise ValueError('Exact preview, actor and rationale are required for receptor changes')
            preview = self.preview_receptor_changes(study_id, model_changes['choices'], expected_revision=expected_revision)
            if preview['preview_sha256'] != model_changes['preview_sha256']:
                raise ValueError('Receptor changes differ from the reviewed preview')
            if not preview['changes']:
                raise ValueError('No model changes were selected; use the ordinary preparation action')
            _, derivative = preview_changes(preview['source_path'], model_changes['choices'], context=preview['context'])
            model_root = Path(setup['working_directory']) / '.docking-universal-reviewed-models' / uuid4().hex
            model, model_record = write_model(model_root, plan.receptor_pdb.name, preview, derivative,
                actor=model_changes['actor'], rationale=model_changes['rationale'])
            model_record['reviewed_receptor_input'] = retain_reviewed_receptor_input(model_root, preview, derivative)
            model_record['execution_policy'] = dict(preparation_backend=preview['preparation_backend'],
                pdbfixer='off', reduce2='off', protonation='off', reviewed_model_only=True,
                parameterization_only=True)
            (model_root / 'reviewed_model.json').write_text(json.dumps(model_record, indent=2) + '\n')
            model_record_sha256 = sha256(model_root / 'reviewed_model.json')
            original_structure_input = plan.structure_input
            values.update(input_pdb=model, working_directory=model_root / 'preparation',
                          pdbfixer='off', reduce2='off', protonation='off',
                          preparation_backend=preview['preparation_backend'])
            plan = parameterization_plan(build_receptor_preparation_plan(
                self.preparation_executable, ReceptorPreparationOptions(**values)))
            environment = dict(plan.request.environment)
            environment.update(DOCKING_UNIVERSAL_REVIEWED_MODEL_ONLY='1', MEEKO_DEFAULT_ALTLOC='',
                DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT=model_record['reviewed_receptor_input']['path'],
                DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT_SHA256=model_record['reviewed_receptor_input']['sha256'])
            plan = replace(plan, structure_input=original_structure_input,
                           request=replace(plan.request, environment=environment))
            if model_record.get('connectivity_execution'):
                if preview['preparation_backend'] != 'meeko':
                    raise ValueError('Reviewed connectivity-stage execution requires Meeko')
                helper = Path(self.preparation_executable).with_name('docking-universal-reviewed-connectivity.py')
                if not helper.is_file():
                    raise ValueError('Reviewed-connectivity preparation adapter is unavailable')
                plan = replace(plan, request=replace(plan.request, command=(sys.executable, str(helper),
                    '--record', str(model_root / 'reviewed_model.json'), '--record-sha256', model_record_sha256,
                    '--out', str(plan.output_root))))
        if plan.output_root.exists():
            raise ValueError('Preparation output already exists; it will not be overwritten or retried automatically')
        pins = {}
        for path in root.rglob('*'):
            if path.is_symlink():
                raise ValueError('Site-review evidence may not contain symbolic links')
            if path.is_file():
                pins[str(path.relative_to(root))] = sha256(path)
        def mark(latest):
            latest.workflow_data['receptor_parameterization_status'] = 'running'
            if model_record:
                latest.workflow_data.setdefault('reviewed_receptor_models', []).append({
                    'request_id': request_id, 'record': str(model_root / 'reviewed_model.json'),
                    'preview_sha256': model_record['preview_sha256'], 'status': 'preparing',
                    'actor': model_record['actor'], 'rationale': model_record['rationale']})
                for suffix, kind, path in (
                    ('record', 'reviewed_receptor_model', model_root / 'reviewed_model.json'),
                    ('input', 'reviewed_receptor_input', Path(model_record['model_path'])),
                    ('filtered', 'reviewed_receptor_filtered_input', Path(model_record['reviewed_receptor_input']['path']))):
                    latest.artifacts.append(ArtifactRecord('reviewed-model-' + model_root.name + '-' + suffix,
                        kind, str(path), sha256(path), 'Explicit exploratory receptor change; not a validated control'))
        retained, _ = self.controller.store.update(study_id, mark, expected_revision=expected_revision)
        cancellation = threading.Event()
        def work():
            try:
                result = ReceptorPreparationService(self.controller).run(
                    study_id, plan, cancel_event=cancellation, request_id=request_id,
                    expected_revision=retained.revision, allow_template_decision=False,
                    stage='receptor_parameterization')
                if result.status.value == 'completed':
                    read_exploration(root)
                    if any(not (root / name).is_file() or sha256(root / name) != digest
                           for name, digest in pins.items()):
                        raise ValueError('Reviewed site evidence changed during preparation')
                    shutil.copytree(root / 'cavity', plan.output_root / 'cavity', dirs_exist_ok=True)
                    if model_record:
                        from .services.receptor_model_history import SCHEMA, normalize_preparation
                        if sha256(Path(model_record['model_path'])) != model_record['model_input_sha256']:
                            raise ValueError('Reviewed receptor model changed during parameterization')
                        if sha256(model_root / 'reviewed_model.json') != model_record_sha256:
                            raise ValueError('Receptor change approval record changed during parameterization')
                        filtered = model_record['reviewed_receptor_input']
                        if sha256(Path(filtered['path'])) != filtered['sha256'] or sha256(Path(filtered['baseline_path'])) != filtered['baseline_sha256']:
                            raise ValueError('Reviewed receptor inventory changed during parameterization')
                        history = {'schema_name': SCHEMA, 'schema_version': 1,
                            'original_input_sha256': model_record['context']['original_input_sha256'],
                            'model_input_sha256': model_record['model_input_sha256'],
                            'prepared_receptor_sha256': sha256(plan.receptor_pdbqt),
                            'review_record_sha256': model_record_sha256,
                            'preparation_backend': preview['preparation_backend'],
                            'execution_policy': model_record['execution_policy'],
                            'reviewed_receptor_input_sha256': filtered['sha256'],
                            'baseline_receptor_input_sha256': filtered['baseline_sha256'],
                            'changes': [dict(change, actor=model_record['actor'], rationale=model_record['rationale'])
                                        for change in model_record['changes']]}
                        normalize_preparation({'model_change_history': history}, sha256(plan.receptor_pdbqt))
                        (plan.output_root / 'receptor/receptor_model_history.json').write_text(json.dumps(history, indent=2) + '\n')
                def finish(latest):
                    latest.workflow_data['receptor_parameterization_status'] = result.status.value
                    latest.workflow_data['site_review_source_hashes'] = pins
                    latest.workflow_data['receptor_parameterization_attempt_root'] = str(plan.output_root)
                    latest.workflow_data.setdefault('receptor_preparation_attempts', []).append({
                        'request_id': request_id, 'root': str(plan.output_root), 'status': result.status.value,
                        'reviewed_model': str(model_root) if model_record else None})
                    if model_record:
                        for review in latest.workflow_data['reviewed_receptor_models']:
                            if review['request_id'] == request_id:
                                review['status'] = result.status.value
                        if result.status.value == 'completed':
                            history_path = plan.output_root / 'receptor/receptor_model_history.json'
                            latest.artifacts.append(ArtifactRecord('receptor-model-history', 'receptor_model_history',
                                str(history_path), sha256(history_path), 'Portable record of explicitly reviewed receptor changes'))
                    if result.status.value == 'failed':
                        from .services.preparation_site_issues import collect_site_issues, for_box
                        issues = collect_site_issues(plan.output_root, plan.structure_input.engine_pdb_path)
                        latest.workflow_data['preparation_site_issues'] = issues
                        known = {a.id for a in latest.artifacts}
                        evidence_paths = [Path(p) for p in issues['diagnostic_logs']]
                        evidence_paths.extend(plan.output_root / 'receptor' / name for name in (
                            'preparation_intervention.json', 'receptor_failure_diagnosis.txt', 'pdbfixer_audit.json'))
                        for path in evidence_paths:
                            identity = 'parameterization-evidence-' + path.name
                            if path.is_file() and identity not in known:
                                latest.artifacts.append(ArtifactRecord(identity, 'preparation_diagnostic',
                                    str(path.resolve()), sha256(path),
                                    'Retained failed preparation evidence; not an approved model change'))
                                known.add(identity)
                        for candidate in latest.workflow_data.get('pocket_candidates', []):
                            geometry = candidate.get('evidence', {}).get('geometry')
                            if geometry:
                                candidate['evidence']['receptor_preparation_review'] = for_box(issues, geometry)
                self.controller.store.update(study_id, finish)
            except Exception as exc:
                self.controller.store.update(study_id, lambda latest:
                    latest.workflow_data.update(receptor_parameterization_status='failed'))
                self._record_orchestration_failure(study_id, exc)
            finally:
                with self._guard:
                    self._cancellations.pop(study_id, None)
                    self._threads.pop(study_id, None)
        thread = threading.Thread(target=work, name=f'du-parameterize-{study_id}', daemon=True)
        with self._guard:
            if self._threads:
                raise ActiveStageError('Another scientific workflow is already running')
            self._threads[study_id] = thread
            self._cancellations[study_id] = cancellation
            thread.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            latest = self.controller.get_study(study_id)
            job = next((j for j in latest.jobs if j.request_id == request_id), None)
            if job:
                return {'job_id': job.id, 'stage': job.stage, 'output_root': str(plan.output_root)}
            if not thread.is_alive():
                break
            time.sleep(.01)
        raise RuntimeError('Parameterization worker did not persist its job start')

    def resume_after_decision(self, study_id: str, decision, approval) -> dict[str, Any] | None:
        """Resume a supported preparation checkpoint using the recorded response."""

        if decision.continuation.get("checkpoint") != "rerun_preparation_with_histidine_template":
            return None
        if "STOP" in approval.selections:
            return None
        state = self.controller.get_study(study_id)
        job = state.active_job
        if job is None or job.status.value != "queued":
            raise ActiveStageError("The preparation continuation is no longer queued")
        setup = dict(state.workflow_data.get("study_setup") or {})
        intervention_path = Path(str(state.workflow_data.get("preparation_intervention") or ""))
        if not intervention_path.is_file():
            raise FileNotFoundError("The retained preparation intervention record is unavailable")
        record = read_intervention_record(intervention_path)
        if approval.selections[0] == "TEST_NEUTRAL_CURRENT":
            return self._resume_neutral_histidine_sensitivity(
                study_id, decision, approval, state, job, setup,
                intervention_path, record,
            )
        assignments = template_assignments(record, approval.selections[0])
        source = Path(str(setup.get("input_structure") or setup.get("input_pdb") or ""))
        working = Path(str(setup.get("working_directory") or ""))
        options = ReceptorPreparationOptions(
            input_pdb=source,
            working_directory=working,
            site_mode=str(setup.get("site_mode") or "pockets"),
            ligand_resname=setup.get("ligand_resname"),
            ligand_chain_id=setup.get("ligand_chain_id"),
            ligand_residue_number=setup.get("ligand_residue_number"),
            ligand_insertion_code=str(setup.get("ligand_insertion_code") or ""),
            ligand_altloc=str(setup.get("ligand_altloc") or ""),
            feedback_level=str(setup.get("feedback_level") or "guided"),
            cavity_mode=int(setup.get("cavity_mode", 1)),
            max_pockets=int(setup.get("max_pockets", 3)),
            center_mode=str(setup.get("center_mode") or "deepest"),
            centroid_mode=int(setup.get("centroid_mode", 1)),
            pdbfixer=str(setup.get("pdbfixer") or "auto"),
            preparation_backend=str(setup.get("preparation_backend") or "auto"),
            pocket_engine=str(setup.get("pocket_engine") or "auto"),
            predict_pockets_with_ligand=setup.get("predict_pockets_with_ligand", False),
            meeko_templates=assignments,
            meeko_template_file=(Path(setup["meeko_template_file"])
                                 if setup.get("meeko_template_file") else None),
            geostd_library=(Path(setup["geostd_library"])
                            if setup.get("geostd_library") else None),
        )
        plan = build_receptor_preparation_plan(self.preparation_executable, options)
        attempts_root = working / ".docking-universal-preparation-attempts" / plan.output_root.name
        attempts_root.mkdir(parents=True, exist_ok=True)
        attempt_number = len(list(attempts_root.glob("attempt-*"))) + 1
        archived = attempts_root / f"attempt-{attempt_number}"
        if plan.output_root.exists():
            shutil.move(str(plan.output_root), str(archived))
        archived_intervention = archived / "receptor" / intervention_path.name
        resumed_request = replace(
            plan.request,
            log_name=f"{plan.request.log_name}-resume-{attempt_number}",
        )
        plan = replace(plan, request=resumed_request)

        def retain_attempt(latest) -> None:
            attempts = latest.workflow_data.setdefault("preparation_attempts", [])
            attempts.append({
                "attempt": attempt_number,
                "archive": str(archived.resolve()),
                "decision_id": decision.id,
                "approval_id": approval.id,
                "selection": approval.selections[0],
                "meeko_template_assignments": assignments,
                "intervention_record": str(archived_intervention.resolve()),
            })
            latest.workflow_data["preparation_intervention"] = str(
                archived_intervention.resolve()
            )
            for continuation in reversed(latest.workflow_data.get("continuation_queue", [])):
                if continuation.get("decision_id") == decision.id:
                    continuation["status"] = "running"
                    continuation["attempt"] = attempt_number
                    break
            for index, artifact in enumerate(latest.artifacts):
                if artifact.id == "preparation-intervention":
                    latest.artifacts[index] = replace(
                        artifact, path=str(archived_intervention.resolve()),
                    )
                    break

        self.controller.store.update(study_id, retain_attempt)
        cancellation = threading.Event()
        evidence_mode = str(setup.get("pdb_pocket_evidence") or "related-structures")

        def work() -> None:
            try:
                result = ReceptorPreparationService(self.controller).run(
                    study_id, plan, resume_job_id=job.id, cancel_event=cancellation,
                )
                if result.status.value == "completed":
                    if evidence_mode == "related-structures":
                        self._collect_pdb_pocket_evidence(study_id, plan)
                    self._start_review(study_id, plan.output_root)
            except Exception as exc:
                self._record_orchestration_failure(study_id, exc)
            finally:
                try:
                    latest = self.controller.get_study(study_id)
                    resumed_job = next(item for item in latest.jobs if item.id == job.id)

                    def finish_continuation(current) -> None:
                        for continuation in reversed(
                            current.workflow_data.get("continuation_queue", [])
                        ):
                            if continuation.get("decision_id") == decision.id:
                                continuation["status"] = resumed_job.status.value
                                continuation["finished_at"] = utc_now()
                                break

                    self.controller.store.update(study_id, finish_continuation)
                except Exception:
                    pass
                with self._guard:
                    self._cancellations.pop(study_id, None)
                    self._threads.pop(study_id, None)

        thread = threading.Thread(
            target=work, name=f"du-preparation-resume-{study_id}", daemon=True,
        )
        with self._guard:
            if self._threads:
                raise ActiveStageError("Another scientific workflow is already running")
            self._cancellations[study_id] = cancellation
            self._threads[study_id] = thread
            thread.start()
        return {
            "job_id": job.id,
            "stage": job.stage,
            "resumed": True,
            "meeko_template_assignments": assignments,
        }

    def _resume_neutral_histidine_sensitivity(
        self, study_id: str, decision, approval, state, job, setup: dict[str, Any],
        intervention_path: Path, record: dict[str, Any],
    ) -> dict[str, Any]:
        """Prepare the two neutral receptor states before docking-box review."""

        assignments = neutral_sensitivity_assignments(record, approval.selections[0])
        source = Path(str(setup.get("input_structure") or setup.get("input_pdb") or ""))
        working = Path(str(setup.get("working_directory") or ""))

        def options_for(destination: Path, assignment: str) -> ReceptorPreparationOptions:
            return ReceptorPreparationOptions(
                input_pdb=source,
                working_directory=destination,
                site_mode=str(setup.get("site_mode") or "pockets"),
                ligand_resname=setup.get("ligand_resname"),
                ligand_chain_id=setup.get("ligand_chain_id"),
                ligand_residue_number=setup.get("ligand_residue_number"),
                ligand_insertion_code=str(setup.get("ligand_insertion_code") or ""),
                ligand_altloc=str(setup.get("ligand_altloc") or ""),
                feedback_level=str(setup.get("feedback_level") or "guided"),
                cavity_mode=int(setup.get("cavity_mode", 1)),
                max_pockets=int(setup.get("max_pockets", 3)),
                center_mode=str(setup.get("center_mode") or "deepest"),
                centroid_mode=int(setup.get("centroid_mode", 1)),
                pdbfixer=str(setup.get("pdbfixer") or "auto"),
                preparation_backend=str(setup.get("preparation_backend") or "auto"),
                pocket_engine=str(setup.get("pocket_engine") or "auto"),
                predict_pockets_with_ligand=setup.get("predict_pockets_with_ligand", False),
                meeko_templates=assignment,
                meeko_template_file=(Path(setup["meeko_template_file"])
                                     if setup.get("meeko_template_file") else None),
                geostd_library=(Path(setup["geostd_library"])
                                if setup.get("geostd_library") else None),
            )

        original = build_receptor_preparation_plan(
            self.preparation_executable, options_for(working, assignments["HIE"]),
        )
        attempts_root = working / ".docking-universal-preparation-attempts" / original.output_root.name
        attempts_root.mkdir(parents=True, exist_ok=True)
        attempt_number = len(list(attempts_root.glob("attempt-*"))) + 1
        archived = attempts_root / f"attempt-{attempt_number}"
        if original.output_root.exists():
            shutil.move(str(original.output_root), str(archived))
        archived_intervention = archived / "receptor" / intervention_path.name

        variant_root = working / ".docking-universal-receptor-states" / decision.id
        plans = {
            template: build_receptor_preparation_plan(
                self.preparation_executable,
                options_for(variant_root / template.lower(), assignment),
            )
            for template, assignment in assignments.items()
        }

        def retain_request(latest) -> None:
            latest.workflow_data.setdefault("preparation_attempts", []).append({
                "attempt": attempt_number,
                "archive": str(archived.resolve()),
                "decision_id": decision.id,
                "approval_id": approval.id,
                "selection": approval.selections[0],
                "meeko_template_assignments": dict(assignments),
                "intervention_record": str(archived_intervention.resolve()),
            })
            latest.workflow_data["preparation_intervention"] = str(
                archived_intervention.resolve()
            )
            latest.workflow_data["receptor_state_sensitivity"] = {
                "schema_name": "docking-universal-receptor-state-sensitivity",
                "schema_version": 1,
                "status": "preparing_variants",
                "decision_id": decision.id,
                "approval_id": approval.id,
                "residues": [str(record.get("residue"))],
                "states": list(assignments),
                "assignments": dict(assignments),
                "affected_boxes": [],
                "comparison_stage": "pending_box_selection",
            }
            for continuation in reversed(latest.workflow_data.get("continuation_queue", [])):
                if continuation.get("decision_id") == decision.id:
                    continuation["status"] = "running"
                    continuation["attempt"] = attempt_number
                    break
            for index, artifact in enumerate(latest.artifacts):
                if artifact.id == "preparation-intervention":
                    latest.artifacts[index] = replace(
                        artifact, path=str(archived_intervention.resolve()),
                    )
                    break

        self.controller.store.update(study_id, retain_request)
        cancellation = threading.Event()
        evidence_mode = str(setup.get("pdb_pocket_evidence") or "related-structures")

        def work() -> None:
            final_status = "failed"
            try:
                service = ReceptorPreparationService(self.controller)
                hie_result = service.run(
                    study_id, plans["HIE"], resume_job_id=job.id,
                    cancel_event=cancellation,
                )
                if hie_result.status.value != "completed":
                    raise RuntimeError("HIE receptor-state preparation did not complete")
                hid_result = service.run(
                    study_id, plans["HID"], stage="receptor_state_variant_preparation",
                    cancel_event=cancellation,
                )
                if hid_result.status.value != "completed":
                    raise RuntimeError("HID receptor-state preparation did not complete")
                if plans["HIE"].output_root != plans["HID"].output_root:
                    variant_records = {
                        template: {
                            "assignment": assignments[template],
                            "preparation_root": str(plan.output_root.resolve()),
                            "receptor_pdb": str(plan.receptor_pdb.resolve()),
                            "receptor_pdbqt": str(plan.receptor_pdbqt.resolve()),
                            "receptor_pdb_sha256": sha256(plan.receptor_pdb),
                            "receptor_pdbqt_sha256": sha256(plan.receptor_pdbqt),
                        }
                        for template, plan in plans.items()
                    }

                    def retain_variants(latest) -> None:
                        sensitivity = latest.workflow_data["receptor_state_sensitivity"]
                        sensitivity["status"] = "prepared_for_box_review"
                        sensitivity["variants"] = variant_records
                        sensitivity["primary_review_state"] = "HIE"
                        latest.workflow_data["preparation_root"] = str(
                            plans["HIE"].output_root.resolve()
                        )
                        known = {artifact.id for artifact in latest.artifacts}
                        for template, plan in plans.items():
                            for suffix, kind, path in (
                                ("pdb", "prepared_receptor_state_structure", plan.receptor_pdb),
                                ("pdbqt", "prepared_receptor_state", plan.receptor_pdbqt),
                            ):
                                artifact_id = f"histidine-state-{template.lower()}-{suffix}"
                                if artifact_id not in known:
                                    latest.artifacts.append(ArtifactRecord(
                                        artifact_id, kind, str(path.resolve()), sha256(path),
                                        f"Retained {template} receptor-state sensitivity variant",
                                    ))
                                    known.add(artifact_id)

                    self.controller.store.update(study_id, retain_variants)
                if evidence_mode == "related-structures":
                    self._collect_pdb_pocket_evidence(study_id, plans["HIE"])
                self._start_review(study_id, plans["HIE"].output_root)
                final_status = "completed"
            except Exception as exc:
                self._record_orchestration_failure(study_id, exc)
            finally:
                def finish(latest) -> None:
                    sensitivity = latest.workflow_data.get("receptor_state_sensitivity")
                    if isinstance(sensitivity, dict) and final_status != "completed":
                        sensitivity["status"] = final_status
                    for continuation in reversed(latest.workflow_data.get("continuation_queue", [])):
                        if continuation.get("decision_id") == decision.id:
                            continuation["status"] = final_status
                            continuation["finished_at"] = utc_now()
                            break

                try:
                    self.controller.store.update(study_id, finish)
                except Exception:
                    pass
                with self._guard:
                    self._cancellations.pop(study_id, None)
                    self._threads.pop(study_id, None)

        thread = threading.Thread(
            target=work, name=f"du-histidine-sensitivity-{study_id}", daemon=True,
        )
        with self._guard:
            if self._threads:
                raise ActiveStageError("Another scientific workflow is already running")
            self._cancellations[study_id] = cancellation
            self._threads[study_id] = thread
            thread.start()
        return {
            "job_id": job.id,
            "stage": job.stage,
            "resumed": True,
            "sensitivity_states": list(assignments),
            "comparison_stage": "pending_box_selection",
        }

    def _collect_pdb_pocket_evidence(self, study_id: str, plan) -> None:
        """Run the public-PDB evidence stage omitted by the low-level bash preparer."""
        from docking_universal_pocket_evidence import collect_pocket_evidence
        from .services.pdb_lookup_status import lookup_coverage

        cavity = plan.output_root / "cavity"
        evidence_root = cavity / "pdb_site_evidence"
        record = evidence_root / "pdb_ligand_site_evidence.json"
        status = "available"
        detail = None
        coverage = {}
        if record.is_file():
            try:
                retained = json.loads(record.read_text())
                status = retained.get("status", status)
                detail = retained.get("error")
                coverage = lookup_coverage(retained)
            except (OSError, ValueError):
                status = "unavailable"
                detail = "Retained PDB evidence record could not be read"
        else:
            try:
                collected = collect_pocket_evidence(
                    Path(plan.request.command[1]), tuple(ordered_pocket_boxes(cavity)), evidence_root,
                )
                status = collected.get("status", "completed")
                coverage = lookup_coverage(collected)
            except Exception as exc:  # Evidence informs review; it must not erase valid preparation.
                status = "unavailable"
                detail = str(exc)
                evidence_root.mkdir(parents=True, exist_ok=True)
                record.write_text(json.dumps({
                    "schema_name": "docking-universal-pdb-ligand-site-evidence",
                    "schema_version": 1,
                    "status": status,
                    "error": detail,
                    "selection_policy": "evidence_only_user_decides",
                }, indent=2) + "\n")

        def register(state) -> None:
            state.workflow_data["pdb_pocket_evidence"] = {
                "mode": "related-structures", "status": status,
                "record": str(record.resolve()), "detail": detail,
                "coverage": coverage,
            }
            if record.is_file() and not any(item.id == "pdb-pocket-evidence" for item in state.artifacts):
                state.artifacts.append(ArtifactRecord(
                    "pdb-pocket-evidence", "pocket_evidence", str(record.resolve()), sha256(record),
                    "Related public-PDB ligand locations and structural alignment evidence",
                ))

        self.controller.store.update(study_id, register)

    def start_finalization(
        self,
        study_id: str,
        payload: dict[str, Any],
        *,
        request_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Start report and bundle generation from the already-approved preparation."""
        state = self.controller.get_study(study_id)
        prior = next((job for job in state.jobs if job.request_id == request_id), None)
        if prior:
            return {"job_id": prior.id, "stage": prior.stage, "replayed": True}
        if state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError(
                f"Study {study_id} changed from revision {expected_revision} to {state.revision}"
            )
        completed_bundle = next((
            artifact for artifact in state.artifacts
            if artifact.kind == "protocol_bundle" and Path(artifact.path).is_file()
        ), None)
        if completed_bundle is not None:
            raise ActiveStageError(
                f"Protocol finalization is already complete for this study: {completed_bundle.path}"
            )
        self._assert_no_active_stage()
        allowed = {
            "output_directory", "engine", "ph", "conformers", "seed_count",
            "base_seed", "exhaustiveness", "num_modes", "energy_range",
            "ad4_runs", "ad4_heuristic_cap",
            "exploratory_use_approved",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown finalization options: {', '.join(sorted(unknown))}")
        if payload.get("exploratory_use_approved") is not True:
            raise ValueError("Finalization requires explicit exploratory-use approval")
        setup = state.workflow_data.get("study_setup") or {}
        if setup.get("site_review_first") and not state.workflow_data.get("latest_control_status"):
            from .services.control_review import reviewed_control_inputs, NoControlSiteSelected
            try:
                reviewed_control_inputs(state)
            except NoControlSiteSelected:
                pass  # Explicit exploratory approval is required above.
            else:
                raise ValueError("Run the reviewed known-ligand control before finalizing its protocol")
        if not payload.get("output_directory"):
            raise ValueError("Final protocol output directory is required")
        settings = FinalizationSettings(
            engine=str(payload.get("engine", "vina")),
            ph=float(payload.get("ph", 7.4)),
            conformers=int(payload.get("conformers", 3)),
            seed_count=int(payload.get("seed_count", 5)),
            base_seed=int(payload.get("base_seed", 20260808)),
            exhaustiveness=int(payload.get("exhaustiveness", 16)),
            num_modes=int(payload.get("num_modes", 15)),
            energy_range=float(payload.get("energy_range", 8.0)),
            ad4_runs=int(payload.get('ad4_runs',20)),
            ad4_heuristic_cap=int(payload.get('ad4_heuristic_cap',12_000_000)),
        )
        request = request_from_study(
            state, settings, Path(str(payload["output_directory"])),
            exploratory_use_approved=True,
        )
        paths = finalization_paths(request)
        script = self.preparation_executable.with_name("docking-universal-finalize-protocol.py")
        if not script.is_file():
            raise FileNotFoundError(f"Protocol finalization service is missing: {script}")
        command = (
            sys.executable, str(script), "--state-root", str(self.controller.store.root.resolve()),
            "--study-id", study_id, "--output", str(paths.root),
            "--engine", settings.engine, "--ph", str(settings.ph),
            "--conformers", str(settings.conformers), "--seeds", str(settings.seed_count),
            "--base-seed", str(settings.base_seed), "--exhaustiveness", str(settings.exhaustiveness),
            "--num-modes", str(settings.num_modes), "--energy-range", str(settings.energy_range),
        )
        if settings.engine == 'adgpu':
            command += ('--ad4-runs',str(settings.ad4_runs),'--ad4-heuristic-cap',str(settings.ad4_heuristic_cap))
        process = ProcessRequest(
            command=command, cwd=paths.root.parent,
            log_directory=paths.root / ".docking-universal-application-logs",
            log_name="protocol-finalization", check=False,
        )
        cancellation = threading.Event()

        def work() -> None:
            try:
                result = ReceptorPreparationService(self.controller).jobs.run(
                    study_id, "final_report", process, cancel_event=cancellation,
                    required_outputs=(paths.protocol, paths.report, paths.bundle),
                    progress_probe=lambda: finalization_feedback(
                        paths.protocol, paths.report, paths.bundle,
                    ),
                    request_id=request_id, expected_revision=expected_revision,
                )
                if result.status.value == "completed":
                    self._register_final_outputs(study_id, paths)
            except Exception as exc:
                self._record_orchestration_failure(study_id, exc)
            finally:
                with self._guard:
                    self._cancellations.pop(study_id, None)
                    self._threads.pop(study_id, None)

        paths.root.parent.mkdir(parents=True, exist_ok=True)
        thread = threading.Thread(target=work, name=f"du-finalize-{study_id}", daemon=True)
        with self._guard:
            if self._threads:
                raise ActiveStageError("Another scientific workflow is already running")
            self._cancellations[study_id] = cancellation
            self._threads[study_id] = thread
            thread.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            latest = self.controller.get_study(study_id)
            job = next((item for item in latest.jobs if item.request_id == request_id), None)
            if job:
                return {
                    "job_id": job.id, "stage": job.stage,
                    "protocol": str(paths.protocol), "report": str(paths.report),
                    "bundle": str(paths.bundle),
                }
            if not thread.is_alive():
                break
            time.sleep(0.01)
        raise RuntimeError("Finalization worker did not persist its job start")

    def screening_plan(self, study_id: str, ligand_source: Path | str, *, ligand_selection=None) -> dict[str, Any]:
        state = self.controller.get_study(study_id)
        protocol = next((
            artifact for artifact in state.artifacts if artifact.kind == "protocol_bundle"
        ), None)
        if protocol is None:
            raise ValueError("Screening requires a completed reusable protocol bundle")
        return build_screening_plan(
            protocol.path, ligand_source, expected_protocol_sha256=protocol.sha256,
            ligand_selection=ligand_selection,
        ).to_dict()

    def start_screening(
        self,
        study_id: str,
        payload: dict[str, Any],
        *,
        request_id: str,
        expected_revision: int,
    ) -> dict[str, Any]:
        """Run the existing locked-protocol screening workflow as one GUI stage."""
        state = self.controller.get_study(study_id)
        prior = next((job for job in state.jobs if job.request_id == request_id), None)
        if prior:
            return {"job_id": prior.id, "stage": prior.stage, "replayed": True}
        if state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError(
                f"Study {study_id} changed from revision {expected_revision} to {state.revision}"
            )
        self._assert_no_active_stage()
        allowed = {
            "ligand_source", "output_directory", "analysis", "representatives",
            "cluster_rmsd", "exploratory_use_approved", "stop_on_error",
            "ligand_selection", "cpu",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown screening options: {', '.join(sorted(unknown))}")
        cpu = payload.get('cpu')
        if cpu is not None and (type(cpu) is not int or not 0 <= cpu <= 1024):
            raise ValueError('CPU threads must be an integer from 0 to 1024 (0 means engine automatic)')
        if not payload.get("ligand_source") or not payload.get("output_directory"):
            raise ValueError("Screening requires ligand and output paths")
        plan = self.screening_plan(study_id, Path(str(payload["ligand_source"])),
                                   ligand_selection=payload.get("ligand_selection"))
        if plan['engine'] == 'adgpu' and cpu is not None:
            raise ValueError('CPU thread overrides do not apply to the experimental AD4 GPU engine')
        if plan["exploratory_authorization_required"] and payload.get("exploratory_use_approved") is not True:
            raise ValueError("Exploratory protocol screening requires explicit approval")
        analysis = str(payload.get("analysis", "representatives"))
        if analysis not in {"none", "summary", "representatives"}:
            raise ValueError("Screening analysis must be none, summary, or representatives")
        representatives = int(payload.get("representatives", 3))
        cluster_rmsd = float(payload.get("cluster_rmsd", 1.5))
        if representatives < 1 or cluster_rmsd <= 0:
            raise ValueError("Representatives and clustering RMSD must be positive")
        protocol = next(item for item in state.artifacts if item.kind == "protocol_bundle")
        output = Path(str(payload["output_directory"])).resolve()
        script = self.preparation_executable.with_name("docking-universal-run.py")
        if not script.is_file():
            raise FileNotFoundError(f"Screening workflow is missing: {script}")
        command = [
            sys.executable, str(script), "screen", "--protocol", protocol.path,
            "--ligands", str(Path(str(payload["ligand_source"])).resolve()),
            "--out", str(output), "--name", f"{study_id}_screen",
            "--analysis", analysis, "--representatives", str(representatives),
            "--cluster-rmsd", str(cluster_rmsd), "--non-interactive",
        ]
        if plan["exploratory_authorization_required"]:
            command.append("--accept-exploratory-protocol")
        if payload.get("stop_on_error") is True:
            command.append("--stop-on-error")
        if payload.get("ligand_selection") is not None:
            selection_root = output.parent / f".{output.name}.docking-universal-application-logs"
            selection_root.mkdir(parents=True, exist_ok=True)
            selection_path = selection_root / f"ligand-selection-{uuid4().hex}.json"
            selection_path.write_text(json.dumps(payload["ligand_selection"], indent=2) + "\n")
            command += ["--ligand-selection", str(selection_path)]
        process = ProcessRequest(
            command=tuple(command), cwd=output.parent,
            # Isolated execution override: all nested docking children inherit
            # it and record the resolved count/source in their run manifests.
            # Never mutate the host environment or the reusable protocol.
            environment={**os.environ, 'DOCKING_UNIVERSAL_CPU': str(cpu)} if cpu is not None else None,
            # The legacy screen runner requires a nonexistent output root for
            # a new study. Keep host-owned launch logs beside it so JobService
            # does not accidentally create the study directory first.
            log_directory=output.parent / f".{output.name}.docking-universal-application-logs",
            log_name="locked-protocol-screening", check=False,
        )
        cancellation = threading.Event()

        def work() -> None:
            try:
                result = ReceptorPreparationService(self.controller).jobs.run(
                    study_id, "screening", process, cancel_event=cancellation,
                    progress_probe=lambda: screening_feedback(
                        output, int(plan["total_docking_jobs"]),
                    ),
                    request_id=request_id, expected_revision=expected_revision,
                )
                self._register_screening_outputs(study_id, output, result.status.value)
            except Exception as exc:
                self._record_orchestration_failure(study_id, exc)
            finally:
                with self._guard:
                    self._cancellations.pop(study_id, None)
                    self._threads.pop(study_id, None)

        output.parent.mkdir(parents=True, exist_ok=True)
        thread = threading.Thread(target=work, name=f"du-screen-{study_id}", daemon=True)
        with self._guard:
            if self._threads:
                raise ActiveStageError("Another scientific workflow is already running")
            self._cancellations[study_id] = cancellation
            self._threads[study_id] = thread
            thread.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            latest = self.controller.get_study(study_id)
            job = next((item for item in latest.jobs if item.request_id == request_id), None)
            if job:
                return {"job_id": job.id, "stage": job.stage, "plan": plan, "output": str(output)}
            if not thread.is_alive():
                break
            time.sleep(0.01)
        raise RuntimeError("Screening worker did not persist its job start")

    def start_pose_interaction(
        self, study_id: str, payload: dict[str, Any], *, request_id: str, expected_revision: int,
    ) -> dict[str, Any]:
        """Generate one exact-pose interaction diagram through the serialized job slot."""
        state = self.controller.get_study(study_id)
        if state.revision != expected_revision:
            from .state import RevisionConflictError
            raise RevisionConflictError(
                f"Study {study_id} changed from revision {expected_revision} to {state.revision}"
            )
        if set(payload) - {"analysis_root", "pose_id"}:
            raise ValueError("Unknown pose-interaction options")
        analysis = Path(str(payload.get("analysis_root", ""))).resolve()
        if not analysis.is_dir():
            raise FileNotFoundError(f"Retained pose analysis is unavailable: {analysis}")
        worker = self.preparation_executable.with_name("docking-universal-pose-interactions.py")
        if not worker.is_file():
            raise FileNotFoundError(f"Approved pose-interaction worker is missing: {worker}")
        plan = build_pose_interaction_plan(
            analysis, int(payload.get("pose_id", 0)), worker_command=(sys.executable, worker),
        )
        if plan.cached:
            validate_pose_interaction_outputs(plan)
            self._register_pose_interaction(study_id, plan)
            return {"cached": True, "diagram": str(plan.diagram), "pose_id": plan.record.pose_id}
        self._assert_no_active_stage()
        cancellation = threading.Event()

        def work() -> None:
            try:
                result = ReceptorPreparationService(self.controller).jobs.run(
                    study_id, "pose_interaction", ProcessRequest(
                        command=plan.command, cwd=plan.cache,
                        log_directory=plan.cache / "logs", log_name="pose-interaction", check=False,
                    ), cancel_event=cancellation,
                    required_outputs=(plan.diagram, plan.evidence, plan.manifest),
                    request_id=request_id, expected_revision=expected_revision,
                )
                if result.status.value == "completed":
                    validate_pose_interaction_outputs(plan)
                    self._register_pose_interaction(study_id, plan)
            except Exception as exc:
                self._record_orchestration_failure(study_id, exc)
            finally:
                with self._guard:
                    self._cancellations.pop(study_id, None)
                    self._threads.pop(study_id, None)

        thread = threading.Thread(target=work, name=f"du-pose-{study_id}-{plan.record.pose_id}", daemon=True)
        with self._guard:
            if self._threads:
                raise ActiveStageError("Another scientific workflow is already running")
            self._cancellations[study_id] = cancellation
            self._threads[study_id] = thread
            thread.start()
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            latest = self.controller.get_study(study_id)
            job = next((item for item in latest.jobs if item.request_id == request_id), None)
            if job:
                return {"cached": False, "job_id": job.id, "pose_id": plan.record.pose_id}
            if not thread.is_alive():
                break
            time.sleep(0.01)
        raise RuntimeError("Pose-interaction worker did not persist its job start")

    def has_live_worker(self, study_id: str) -> bool:
        with self._guard:
            worker = self._threads.get(study_id)
            return bool(worker and worker.is_alive())

    def cancel(self, study_id: str) -> bool:
        with self._guard:
            cancellation = self._cancellations.get(study_id)
            if not cancellation:
                return False
            cancellation.set()
            return True

    def shutdown(self, timeout_seconds: float = 4.0) -> None:
        """Cancel and reap the one worker before the application host exits."""
        with self._guard:
            workers = list(self._threads.values())
            for cancellation in self._cancellations.values():
                cancellation.set()
        deadline = time.monotonic() + timeout_seconds
        for worker in workers:
            worker.join(max(0.0, deadline - time.monotonic()))

    def _assert_no_active_stage(self) -> None:
        for state in self.controller.store.list_studies():
            if state.active_job:
                raise ActiveStageError(
                    f"Study {state.study_id} already has an active stage: {state.active_job.stage}"
                )
        # A terminal job/result can become visible just before its coordinator
        # releases the serialized slot. Finish that short cleanup before a new
        # request, never overlap scientific workers or join under their lock.
        with self._guard:
            finishing=list(self._threads.values())
        for thread in finishing:
            if thread is not threading.current_thread() and thread.is_alive():
                thread.join(timeout=.5)
                if thread.is_alive():
                    raise ActiveStageError('The previous workflow is finishing its retained-output registration')

    def _start_review(self, study_id: str, output_root: Path) -> None:
        cavity = output_root / "cavity"
        boxes = tuple(ordered_pocket_boxes(cavity))
        state = self.controller.get_study(study_id)
        setup = state.workflow_data.get("study_setup") or {}
        bound_review = setup.get("site_mode") == "ligand"
        reference_only = bound_review and not setup.get("predict_pockets_with_ligand")
        # Legacy pocket context is not requested prediction evidence for a
        # reference-only input-ligand box.
        if reference_only:
            boxes = ()
        if not boxes and not bound_review:
            raise FileNotFoundError(f"Preparation produced no retained docking boxes in {cavity}")
        evidence = cavity / "pdb_site_evidence" / "pdb_ligand_site_evidence.json"
        scenes = sorted(cavity.glob("*_all_retained_pockets_review.pml"))
        if bound_review:
            source = next((row for row in state.artifacts if row.kind == "normalized_receptor_input"), None)
            if not source or sha256(Path(source.path)) != source.sha256 or Path(source.path) != Path(setup["input_pdb"]):
                raise ValueError("Input structure changed before bound-ligand site review")
        PocketReviewService(self.controller).start(study_id, PocketReviewInputs(
            target=output_root.name.removesuffix('-site-review').removesuffix("_receptor_prep"),
            cavity_directory=cavity,
            boxes=boxes,
            pocket_evidence_record=evidence if evidence.is_file() else None,
            review_scene=scenes[0] if scenes and not reference_only else None,
            bound_ligand_setup=setup if bound_review else None,
        ))

    def _register_final_outputs(self, study_id: str, paths) -> None:
        report_sessions = sorted(paths.report.parent.glob("*.pse"))
        report_figures = sorted(paths.report.parent.glob("*.png"))

        def mutation(state) -> None:
            known = {artifact.id for artifact in state.artifacts}
            for artifact_id, kind, path, description in (
                ("final-protocol", "final_protocol", paths.protocol, "Locked reusable protocol record"),
                ("final-protocol-report", "final_report", paths.report, "Complete reusable protocol report"),
                ("final-protocol-bundle", "protocol_bundle", paths.bundle, "Portable reusable protocol bundle"),
            ):
                if artifact_id not in known:
                    state.artifacts.append(ArtifactRecord(
                        artifact_id, kind, str(path.resolve()), sha256(path), description,
                    ))
                    known.add(artifact_id)
            for session in report_sessions:
                digest = sha256(session)
                artifact_id = f"final-report-view-{digest[:16]}"
                if artifact_id in known:
                    continue
                state.artifacts.append(ArtifactRecord(
                    artifact_id, "report_view_session", str(session.resolve()), digest,
                    "Interactive PyMOL session matching a retained final-report view",
                ))
                known.add(artifact_id)
            for figure in report_figures:
                digest = sha256(figure)
                artifact_id = f"final-report-figure-{digest[:16]}"
                if artifact_id in known:
                    continue
                state.artifacts.append(ArtifactRecord(
                    artifact_id, "final_report_figure", str(figure.resolve()), digest,
                    "Retained decision-support figure from the final protocol report",
                ))
                known.add(artifact_id)
            completed = state.workflow_data.setdefault("completed_stages", [])
            if "region_approval" not in completed:
                completed.append("region_approval")
            from .workflow import record_stage_completion
            record_stage_completion(state, "bundle")
            StudyController._event(
                state, EventType.ARTIFACT_CREATED,
                "Reusable protocol report and bundle created",
                explanation=(
                    "The approved retained preparation and docking regions were finalized without "
                    "rerunning receptor preparation or ligand docking."
                ),
                technical={
                    "protocol": str(paths.protocol), "report": str(paths.report),
                    "bundle": str(paths.bundle),
                },
            )
        self.controller.store.update(study_id, mutation)

    def _register_screening_outputs(self, study_id: str, output: Path, status: str) -> None:
        artifacts = discover_screening_artifacts(output)

        def mutation(state) -> None:
            known = {artifact.id for artifact in state.artifacts}
            state.artifacts.extend(artifact for artifact in artifacts if artifact.id not in known)
            state.workflow_data["latest_screening_output"] = str(output)
            state.workflow_data["latest_screening_status"] = status
            StudyController._event(
                state, EventType.ARTIFACT_CREATED,
                "Locked-protocol screening outputs retained",
                explanation=(
                    "Completed and partial compound outputs remain available for scientific review; "
                    "process completion does not establish biological activity."
                ),
                technical={"output": str(output), "status": status, "artifacts": len(artifacts)},
                mandatory=status != "completed",
            )
        self.controller.store.update(study_id, mutation)

    def _register_pose_interaction(self, study_id: str, plan) -> None:
        def mutation(state) -> None:
            key = f"{sha256(plan.diagram)[:16]}-pose-{plan.record.pose_id}"
            if not any(artifact.id == key for artifact in state.artifacts):
                state.artifacts.append(ArtifactRecord(
                    key, "pose_interaction_diagram", str(plan.diagram.resolve()), sha256(plan.diagram),
                    f"Exact retained pose {plan.record.pose_id} PLIP interaction diagram",
                    metadata={
                        "analysis_root": str(plan.cache.parent.parent),
                        "pose_id": plan.record.pose_id, "cluster_id": plan.record.cluster_id,
                        "score": plan.record.energy_kcal_per_mol,
                        "renderer_policy": "approved-poseedit-local-v1",
                    },
                ))
        self.controller.store.update(study_id, mutation)

    def _record_orchestration_failure(self, study_id: str, error: Exception | str) -> None:
        import traceback
        state = self.controller.get_study(study_id)
        # JobService already recorded process failures. This path records only
        # orchestration failures after a successful external stage.
        if state.completion_status in {CompletionStatus.FAILED, CompletionStatus.CANCELLED}:
            return
        state.completion_status = CompletionStatus.FAILED
        state.current_stage = None
        StudyController._event(
            state, EventType.STAGE_FAILED, "GUI protocol orchestration failed",
            explanation=str(error), technical={"component": "ProtocolWorkflowRunner",
                "error_type": type(error).__name__ if isinstance(error, Exception) else "unclassified",
                "error_locations": [{"file": Path(frame.filename).name, "function": frame.name, "line": frame.lineno}
                    for frame in traceback.extract_tb(error.__traceback__)[-4:]] if isinstance(error, Exception) else []}, mandatory=True,
        )
        self.controller.store.save(state)
