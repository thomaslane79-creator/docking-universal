"""Noninteractive service boundary for the existing bash preparation engine."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from ..application import StudyController
from ..jobs import JobService
from ..models import ArtifactRecord
from ..processes import ProcessRequest, ProcessResult
from ..stage_feedback import preparation_feedback
from .structure_input import NormalizedStructureInput, normalize_structure_input
from .preparation_interventions import decision_from_intervention


@dataclass(frozen=True)
class ReceptorPreparationOptions:
    input_pdb: Path
    working_directory: Path
    site_mode: str
    ligand_resname: str | None = None
    ligand_chain_id: str | None = None
    ligand_residue_number: str | None = None
    ligand_insertion_code: str = ""
    ligand_altloc: str = ""
    feedback_level: str = "guided"
    cavity_mode: int = 1
    max_pockets: int = 3
    center_mode: str = "deepest"
    centroid_mode: int = 1
    pdbfixer: str = "auto"
    preparation_backend: str = "auto"
    pocket_engine: str = "auto"
    meeko_templates: str = ""
    meeko_template_file: Path | None = None
    protonation: str = "auto"
    receptor_ph: float = 7.4
    reduce2: str = "auto"
    geostd_library: Path | None = None

    def validate(self) -> None:
        if (
            not self.input_pdb.is_file()
            or self.input_pdb.suffix.lower() not in {".pdb", ".cif", ".mmcif"}
        ):
            raise FileNotFoundError(
                f"Receptor input is not an existing PDB or mmCIF file: {self.input_pdb}"
            )
        if self.site_mode not in {"ligand", "pockets"}:
            raise ValueError("GUI preparation requires an explicit ligand or pockets site mode")
        if self.site_mode == "ligand" and not self.ligand_resname:
            raise ValueError("Ligand mode requires an explicitly selected bound-ligand residue name")
        if bool(self.ligand_chain_id) != bool(self.ligand_residue_number):
            raise ValueError("Exact ligand selection requires both chain and residue number")
        if self.feedback_level not in {"concise", "guided", "verbose"}:
            raise ValueError("Feedback level must be concise, guided, or verbose")
        if self.cavity_mode not in {1, 2, 3} or self.max_pockets < 1:
            raise ValueError("Cavity mode must be 1-3 and max pockets must be positive")
        if self.center_mode not in {"deepest", "centroid"} or self.centroid_mode not in {1, 2}:
            raise ValueError("Invalid cavity center policy")
        if self.pdbfixer not in {"auto", "required", "off"}:
            raise ValueError("PDBFixer policy must be auto, required, or off")
        if self.preparation_backend not in {"auto", "meeko", "adfr"}:
            raise ValueError("Preparation backend must be auto, meeko, or adfr")
        if self.pocket_engine not in {"auto", "p2rank", "fpocket"}:
            raise ValueError("Pocket engine must be auto, p2rank, or fpocket")
        if self.protonation not in {"auto", "required", "off"}:
            raise ValueError("Protonation policy must be auto, required, or off")
        if not 0.0 <= self.receptor_ph <= 14.0:
            raise ValueError("Receptor pH must be between 0 and 14")
        if self.reduce2 not in {"auto", "required", "off"}:
            raise ValueError("Reduce2 policy must be auto, required, or off")
        if self.geostd_library is not None and not self.geostd_library.is_dir():
            raise FileNotFoundError(f"GeoStd component library is unavailable: {self.geostd_library}")
        if self.meeko_template_file is not None and not self.meeko_template_file.is_file():
            raise FileNotFoundError(
                f"Reviewed Meeko template file is unavailable: {self.meeko_template_file}"
            )


@dataclass(frozen=True)
class ReceptorPreparationPlan:
    request: ProcessRequest
    output_root: Path
    receptor_pdb: Path
    receptor_pdbqt: Path
    run_log: Path
    structure_input: NormalizedStructureInput

    @property
    def intervention_record(self) -> Path:
        return self.output_root / "receptor" / "preparation_intervention.json"

    @property
    def required_outputs(self) -> tuple[Path, ...]:
        return self.receptor_pdb, self.receptor_pdbqt, self.run_log


def _canonical_name(path: Path) -> str:
    raw = path.stem
    base = re.sub(r"\([^)]*\)", "", raw)
    base = re.sub(r"[^A-Za-z0-9]", "_", base)
    base = re.sub(r"_+", "_", base)
    match = re.search(r"\(([A-Za-z0-9]{4})\)", raw)
    return base + (f"_{match.group(1)}" if match else "")


def build_receptor_preparation_plan(
    executable: Path | str,
    options: ReceptorPreparationOptions,
    *,
    base_environment: Mapping[str, str] | None = None,
) -> ReceptorPreparationPlan:
    options.validate()
    source = options.input_pdb.expanduser().resolve()
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"Preparation engine does not exist: {executable}")
    working = options.working_directory.resolve()
    canonical = _canonical_name(source)
    output_root = working / f"{canonical}_receptor_prep"
    structure_input = normalize_structure_input(source, working / ".docking-universal-inputs")
    environment = dict(base_environment or os.environ)
    environment.update({
        "FEEDBACK_LEVEL": options.feedback_level,
        "DOCKING_UNIVERSAL_SITE_MODE": options.site_mode,
        "DOCKING_UNIVERSAL_CAVITY_MODE": str(options.cavity_mode),
        "DOCKING_UNIVERSAL_MAX_POCKETS": str(options.max_pockets),
        "DOCKING_UNIVERSAL_CENTER_MODE": options.center_mode,
        "DOCKING_UNIVERSAL_CENTROID_MODE": str(options.centroid_mode),
        "DOCKING_UNIVERSAL_PDBFIXER": options.pdbfixer,
        "DOCKING_UNIVERSAL_PREP_BACKEND": options.preparation_backend,
        "DOCKING_UNIVERSAL_POCKET_ENGINE": options.pocket_engine,
        "DOCKING_UNIVERSAL_PROTONATION": options.protonation,
        "DOCKING_UNIVERSAL_RECEPTOR_PH": str(options.receptor_ph),
        "DOCKING_UNIVERSAL_REDUCE2": options.reduce2,
        "DOCKING_UNIVERSAL_REMOVAL_PROMPT": "0",
        "DOCKING_UNIVERSAL_LOG_MODE": environment.get("DOCKING_UNIVERSAL_LOG_MODE", "tee"),
        "MEEKO_ALLOW_BAD_RES": "0",
        "MEEKO_SET_TEMPLATE": options.meeko_templates,
        "MEEKO_ADD_TEMPLATES": (
            str(options.meeko_template_file.resolve()) if options.meeko_template_file else ""
        ),
    })
    if options.geostd_library is not None:
        environment["DOCKING_UNIVERSAL_GEOSTD"] = str(options.geostd_library.resolve())
    if options.ligand_resname:
        environment["DOCKING_UNIVERSAL_LIGAND_RESNAME"] = options.ligand_resname
    else:
        environment.pop("DOCKING_UNIVERSAL_LIGAND_RESNAME", None)
    identity_environment = {
        "DOCKING_UNIVERSAL_LIGAND_CHAIN": options.ligand_chain_id or "",
        "DOCKING_UNIVERSAL_LIGAND_RESSEQ": options.ligand_residue_number or "",
        "DOCKING_UNIVERSAL_LIGAND_ICODE": options.ligand_insertion_code,
        "DOCKING_UNIVERSAL_LIGAND_ALTLOC": options.ligand_altloc,
    }
    environment.update(identity_environment)
    if structure_input.derived_for_legacy_engine:
        environment["DOCKING_UNIVERSAL_SOURCE_MMCIF"] = str(structure_input.source_path)
        environment["DOCKING_UNIVERSAL_STRUCTURE_METADATA"] = str(structure_input.metadata_path)
    else:
        environment.pop("DOCKING_UNIVERSAL_SOURCE_MMCIF", None)
        environment.pop("DOCKING_UNIVERSAL_STRUCTURE_METADATA", None)
    request = ProcessRequest(
        command=(str(executable), str(structure_input.engine_pdb_path)),
        cwd=working,
        environment=environment,
        log_directory=working / ".docking-universal-application-logs",
        log_name=f"{canonical}-receptor-preparation",
        check=False,
    )
    return ReceptorPreparationPlan(
        request, output_root,
        output_root / "receptor" / f"{canonical}.pdb",
        output_root / "receptor" / f"{canonical}.pdbqt",
        output_root / "run.log", structure_input,
    )


class ReceptorPreparationService:
    def __init__(self, controller: StudyController, jobs: JobService | None = None):
        self.controller = controller
        self.jobs = jobs or JobService(controller)

    def run(self, study_id: str, plan: ReceptorPreparationPlan, **run_options) -> ProcessResult:
        Path(plan.request.cwd).mkdir(parents=True, exist_ok=True)
        resume_job_id = run_options.pop("resume_job_id", None)
        stage = run_options.pop("stage", "preparation_and_pocket_detection")
        if resume_job_id is not None and stage != "preparation_and_pocket_detection":
            raise ValueError("A resumed preparation keeps its original scientific stage")

        def intervention_probe():
            if not plan.intervention_record.is_file():
                return None
            decision = decision_from_intervention(
                plan.intervention_record, self.controller._id("decision"),
            )
            if decision is None:
                return None
            artifact = ArtifactRecord(
                "preparation-intervention", "preparation_intervention",
                str(plan.intervention_record.resolve()), _sha256(plan.intervention_record),
                "Structured receptor-preparation decision evidence",
            )

            def retain(latest) -> None:
                latest.workflow_data["preparation_intervention"] = str(
                    plan.intervention_record.resolve()
                )
                if not any(item.id == artifact.id for item in latest.artifacts):
                    latest.artifacts.append(artifact)

            self.controller.store.update(study_id, retain)
            return decision

        job_method = self.jobs.resume if resume_job_id else self.jobs.run
        job_arguments = (
            (study_id, resume_job_id, plan.request)
            if resume_job_id else
            (study_id, stage, plan.request)
        )
        result = job_method(
            *job_arguments,
            required_outputs=plan.required_outputs,
            progress_probe=lambda: preparation_feedback(
                plan.output_root, plan.receptor_pdb, plan.receptor_pdbqt,
            ),
            intervention_probe=intervention_probe,
            **run_options,
        )
        if result.status.value == "completed":
            discovered = [
                ("source-receptor-structure", "source_receptor_structure", plan.structure_input.source_path),
                ("normalized-receptor-input", "normalized_receptor_input", plan.structure_input.engine_pdb_path),
                ("structure-input-metadata", "structure_input_metadata", plan.structure_input.metadata_path),
                ("prepared-receptor-pdb", "prepared_receptor_structure", plan.receptor_pdb),
                ("prepared-receptor-pdbqt", "prepared_receptor", plan.receptor_pdbqt),
                ("receptor-preparation-run-log", "preparation_log", plan.run_log),
            ]
            receptor_dir = plan.output_root / "receptor"
            for name, kind in (("pdb2pqr_audit.json", "protonation_audit"),
                               ("pdb2pqr.log", "protonation_log"),
                               ("reduce2_audit.json", "reduce2_audit"),
                               ("reduce2.log", "reduce2_log"),
                               (f"{plan.receptor_pdb.stem}_reduce2H.pdb", "reduce2_receptor"),
                               (f"{plan.receptor_pdb.stem}_protonated.pdb", "protonated_receptor"),
                               (f"{plan.receptor_pdb.stem}.pqr", "protonated_receptor_pqr"),
                               ("meeko_additional_templates.json", "meeko_template"),
                               ("meeko_ptm_template_audit.json", "meeko_template_audit"),
                               ("meeko_ptm_template_approval.json", "meeko_template_approval")):
                candidate = receptor_dir / name
                if candidate.is_file():
                    discovered.append((f"protonation-{name}", kind, candidate))
            discovered.extend(
                (_report_artifact_id(plan.output_root, path), "preliminary_report", path)
                for path in sorted(plan.output_root.rglob("*.pdf"))
            )
            discovered.extend(
                (_report_artifact_id(plan.output_root, path), "scientific_image", path)
                for suffix in ("*.png", "*.jpg", "*.jpeg")
                for path in sorted(plan.output_root.rglob(suffix))
            )
            discovered.extend(
                (_report_artifact_id(plan.output_root, path), "report_view_session", path)
                for path in sorted(plan.output_root.rglob("*.pse"))
            )

            def register(latest) -> None:
                latest.workflow_data["preparation_root"] = str(plan.output_root.resolve())
                known = {artifact.id for artifact in latest.artifacts}
                for artifact_id, kind, path in discovered:
                    if artifact_id in known:
                        continue
                    latest.artifacts.append(ArtifactRecord(
                        artifact_id, kind, str(path.resolve()), _sha256(path),
                        (
                            "Existing preliminary scientific report; registered without modification"
                            if kind == "preliminary_report"
                            else "Retained static scientific visualization; registered without modification"
                            if kind == "scientific_image"
                            else "Interactive PyMOL session matching a retained report view"
                            if kind == "report_view_session"
                            else "Retained noninteractive receptor-preparation output"
                        ),
                    ))
                    known.add(artifact_id)

            self.controller.store.update(study_id, register)
        return result


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _report_artifact_id(output_root: Path, path: Path) -> str:
    relative = str(path.resolve().relative_to(output_root.resolve()))
    identity = hashlib.sha256(relative.encode("utf-8")).hexdigest()[:16]
    return f"preliminary-report-{identity}"
