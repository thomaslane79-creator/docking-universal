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

from .application import ActiveStageError, StudyController
from .events import EventType
from .models import ArtifactRecord, CompletionStatus, utc_now
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
from .services.geostd_components import available_library, retained_component_ids


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
        if state.jobs or state.workflow_data.get("study_setup"):
            raise ActiveStageError("A known-ligand control requires a new study")
        allowed = {"input_structure", "output_directory", "ligand_resname", "ligand_chain_id",
                   "ligand_residue_number", "ligand_insertion_code", "engine", "control_tier",
                   "geostd_library"}
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown control options: {', '.join(sorted(unknown))}")
        source = Path(str(payload.get("input_structure") or "")).resolve()
        output = Path(str(payload.get("output_directory") or "")).resolve()
        if not payload.get("output_directory"):
            raise ValueError("A control output directory is required")
        if not source.is_file() or source.suffix.lower() not in {".pdb", ".cif", ".mmcif"}:
            raise FileNotFoundError("A deposited PDB or mmCIF complex is required for control redocking")
        if output.exists():
            raise ValueError("Control output directory must not already exist")
        if payload.get("geostd_library"):
            geostd_library = Path(str(payload["geostd_library"])).resolve()
        else:
            geostd_library = available_library(retained_component_ids(source))
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
        # Legacy control scripts require PDB coordinates. Retain the original
        # mmCIF and conversion metadata rather than changing the source silently.
        normalized = normalize_structure_input(source, output.parent / f".{output.name}.inputs")
        setup = {
            "pathway": "control", "input_structure": str(source),
            "input_pdb": str(normalized.engine_pdb_path),
            "input_structure_format": normalized.source_format,
            "structure_input_metadata": str(normalized.metadata_path),
            "biological_assemblies": list(normalized.assemblies),
            "working_directory": str(output), "site_mode": "ligand",
            "ligand_resname": payload["ligand_resname"],
            "ligand_chain_id": payload["ligand_chain_id"],
            "ligand_residue_number": payload["ligand_residue_number"],
            "engine": engine, "control_tier": tier,
            "geostd_library": str(geostd_library),
        }
        retained, _ = self.controller.store.update(
            study_id, lambda current: current.workflow_data.setdefault("study_setup", setup),
            expected_revision=expected_revision,
        )
        process = ProcessRequest(
            command=(sys.executable, str(script), "control", "--complex",
                     str(normalized.engine_pdb_path), "--control-ligand-id", ligand_id,
                     "--out", str(output), "--engine", engine, "--control-tier", tier,
                     "--non-interactive"),
            cwd=output.parent,
            environment={**os.environ, "DOCKING_UNIVERSAL_GEOSTD": str(geostd_library)},
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
                self._record_orchestration_failure(study_id, str(exc))
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
        if status == "completed":
            for candidate in sorted(output.glob("*.duprotocol")):
                try:
                    record = read_protocol_record(candidate)
                except ValueError:
                    continue
                if protocol_type(record) == CONTROL_VALIDATED:
                    bundles.append(candidate)
        reports = sorted((output / "report").glob("*.pdf"))
        manifest = output / "study_manifest.json"

        def mutation(state) -> None:
            known = {artifact.id for artifact in state.artifacts}
            for kind, paths in (("protocol_bundle", bundles), ("final_report", reports),
                                ("control_manifest", [manifest] if manifest.is_file() else [])):
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
        self._assert_no_active_stage()
        allowed = {
            "input_pdb", "working_directory", "site_mode", "ligand_resname",
            "ligand_chain_id", "ligand_residue_number", "ligand_insertion_code",
            "ligand_altloc",
            "feedback_level", "cavity_mode", "max_pockets", "center_mode",
            "centroid_mode", "pdbfixer", "preparation_backend", "pocket_engine",
            "meeko_templates",
            "geostd_library",
            "pdb_pocket_evidence",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown preparation options: {', '.join(sorted(unknown))}")
        values = dict(payload)
        for name in ("input_pdb", "working_directory"):
            if name not in values:
                raise ValueError(f"Preparation option is required: {name}")
            values[name] = Path(values[name])
        if values.get("geostd_library"):
            values["geostd_library"] = Path(values["geostd_library"])
        evidence_mode = values.pop("pdb_pocket_evidence", "related-structures")
        if evidence_mode not in {"related-structures", "off"}:
            raise ValueError("PDB pocket evidence must be related-structures or off")
        options = ReceptorPreparationOptions(**values)
        plan = build_receptor_preparation_plan(self.preparation_executable, options)
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
            "meeko_templates": options.meeko_templates,
            "geostd_library": str(options.geostd_library.resolve()) if options.geostd_library else None,
            "pdb_pocket_evidence": evidence_mode,
            "accepted_at_revision": state.revision,
        }

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

        retained_state, _unused = self.controller.store.update(
            study_id, retain_setup, expected_revision=expected_revision,
        )
        preparation_revision = retained_state.revision
        cancellation = threading.Event()

        def work() -> None:
            try:
                result = ReceptorPreparationService(self.controller).run(
                    study_id, plan, cancel_event=cancellation,
                    request_id=request_id, expected_revision=preparation_revision,
                )
                if result.status.value == "completed":
                    if options.site_mode == "pockets" and evidence_mode == "related-structures":
                        self._collect_pdb_pocket_evidence(study_id, plan)
                    self._start_review(study_id, plan.output_root)
            except Exception as exc:
                self._record_orchestration_failure(study_id, str(exc))
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
                return {"job_id": job.id, "stage": job.stage, "output_root": str(plan.output_root)}
            if not thread.is_alive():
                break
            time.sleep(0.01)
        raise RuntimeError("Preparation worker did not persist its job start")

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
            meeko_templates=assignments,
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
                    if options.site_mode == "pockets" and evidence_mode == "related-structures":
                        self._collect_pdb_pocket_evidence(study_id, plan)
                    self._start_review(study_id, plan.output_root)
            except Exception as exc:
                self._record_orchestration_failure(study_id, str(exc))
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
                meeko_templates=assignment,
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
                if setup.get("site_mode") == "pockets" and evidence_mode == "related-structures":
                    self._collect_pdb_pocket_evidence(study_id, plans["HIE"])
                self._start_review(study_id, plans["HIE"].output_root)
                final_status = "completed"
            except Exception as exc:
                self._record_orchestration_failure(study_id, str(exc))
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

        cavity = plan.output_root / "cavity"
        evidence_root = cavity / "pdb_site_evidence"
        record = evidence_root / "pdb_ligand_site_evidence.json"
        status = "available"
        detail = None
        if record.is_file():
            try:
                retained = json.loads(record.read_text())
                status = retained.get("status", status)
                detail = retained.get("error")
            except (OSError, ValueError):
                status = "unavailable"
                detail = "Retained PDB evidence record could not be read"
        else:
            try:
                collected = collect_pocket_evidence(
                    Path(plan.request.command[1]), tuple(ordered_pocket_boxes(cavity)), evidence_root,
                )
                status = collected.get("status", "completed")
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
            "exploratory_use_approved",
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown finalization options: {', '.join(sorted(unknown))}")
        if payload.get("exploratory_use_approved") is not True:
            raise ValueError("Finalization requires explicit exploratory-use approval")
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
                self._record_orchestration_failure(study_id, str(exc))
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

    def screening_plan(self, study_id: str, ligand_source: Path | str) -> dict[str, Any]:
        state = self.controller.get_study(study_id)
        protocol = next((
            artifact for artifact in state.artifacts if artifact.kind == "protocol_bundle"
        ), None)
        if protocol is None:
            raise ValueError("Screening requires a completed reusable protocol bundle")
        return build_screening_plan(
            protocol.path, ligand_source, expected_protocol_sha256=protocol.sha256,
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
        }
        unknown = set(payload) - allowed
        if unknown:
            raise ValueError(f"Unknown screening options: {', '.join(sorted(unknown))}")
        if not payload.get("ligand_source") or not payload.get("output_directory"):
            raise ValueError("Screening requires ligand and output paths")
        plan = self.screening_plan(study_id, Path(str(payload["ligand_source"])))
        if plan["exploratory_authorization_required"] and payload.get("exploratory_use_approved") is not True:
            raise ValueError("Exploratory protocol screening requires explicit approval")
        analysis = str(payload.get("analysis", "representatives"))
        if analysis not in {"none", "summary", "representatives"}:
            raise ValueError("Screening analysis must be none, summary, or representatives")
        representatives = int(payload.get("representatives", 3))
        cluster_rmsd = float(payload.get("cluster_rmsd", 2.0))
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
        process = ProcessRequest(
            command=tuple(command), cwd=output.parent,
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
                self._record_orchestration_failure(study_id, str(exc))
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
                self._record_orchestration_failure(study_id, str(exc))
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
        for path in self.controller.store.root.glob("*/application_state.json"):
            state = self.controller.store.load(path.parent.name)
            if state.active_job:
                raise ActiveStageError(
                    f"Study {state.study_id} already has an active stage: {state.active_job.stage}"
                )

    def _start_review(self, study_id: str, output_root: Path) -> None:
        cavity = output_root / "cavity"
        boxes = tuple(ordered_pocket_boxes(cavity))
        if not boxes:
            raise FileNotFoundError(f"Preparation produced no retained docking boxes in {cavity}")
        evidence = cavity / "pdb_site_evidence" / "pdb_ligand_site_evidence.json"
        scenes = sorted(cavity.glob("*_all_retained_pockets_review.pml"))
        PocketReviewService(self.controller).start(study_id, PocketReviewInputs(
            target=output_root.name.removesuffix("_receptor_prep"),
            cavity_directory=cavity,
            boxes=boxes,
            pocket_evidence_record=evidence if evidence.is_file() else None,
            review_scene=scenes[0] if scenes else None,
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

    def _record_orchestration_failure(self, study_id: str, error: str) -> None:
        state = self.controller.get_study(study_id)
        # JobService already recorded process failures. This path records only
        # orchestration failures after a successful external stage.
        if state.completion_status in {CompletionStatus.FAILED, CompletionStatus.CANCELLED}:
            return
        state.completion_status = CompletionStatus.FAILED
        state.current_stage = None
        StudyController._event(
            state, EventType.STAGE_FAILED, "GUI protocol orchestration failed",
            explanation=error, technical={"component": "ProtocolWorkflowRunner"}, mandatory=True,
        )
        self.controller.store.save(state)
