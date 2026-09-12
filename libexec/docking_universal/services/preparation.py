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


@dataclass(frozen=True)
class ReceptorPreparationOptions:
    input_pdb: Path
    working_directory: Path
    site_mode: str
    ligand_resname: str | None = None
    feedback_level: str = "guided"
    cavity_mode: int = 1
    max_pockets: int = 3
    center_mode: str = "deepest"
    centroid_mode: int = 1
    pdbfixer: str = "auto"
    preparation_backend: str = "auto"
    meeko_templates: str = ""

    def validate(self) -> None:
        if not self.input_pdb.is_file() or self.input_pdb.suffix.lower() != ".pdb":
            raise FileNotFoundError(f"Receptor input is not an existing PDB file: {self.input_pdb}")
        if self.site_mode not in {"ligand", "pockets"}:
            raise ValueError("GUI preparation requires an explicit ligand or pockets site mode")
        if self.site_mode == "ligand" and not self.ligand_resname:
            raise ValueError("Ligand mode requires an explicitly selected bound-ligand residue name")
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


@dataclass(frozen=True)
class ReceptorPreparationPlan:
    request: ProcessRequest
    output_root: Path
    receptor_pdb: Path
    receptor_pdbqt: Path
    run_log: Path

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
    executable = Path(executable).resolve()
    if not executable.is_file():
        raise FileNotFoundError(f"Preparation engine does not exist: {executable}")
    working = options.working_directory.resolve()
    canonical = _canonical_name(options.input_pdb)
    output_root = working / f"{canonical}_receptor_prep"
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
        "DOCKING_UNIVERSAL_REMOVAL_PROMPT": "0",
        "DOCKING_UNIVERSAL_LOG_MODE": "tee",
        "MEEKO_ALLOW_BAD_RES": "0",
        "MEEKO_SET_TEMPLATE": options.meeko_templates,
    })
    if options.ligand_resname:
        environment["DOCKING_UNIVERSAL_LIGAND_RESNAME"] = options.ligand_resname
    else:
        environment.pop("DOCKING_UNIVERSAL_LIGAND_RESNAME", None)
    request = ProcessRequest(
        command=(str(executable), str(options.input_pdb.resolve())),
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
        output_root / "run.log",
    )


class ReceptorPreparationService:
    def __init__(self, controller: StudyController, jobs: JobService | None = None):
        self.controller = controller
        self.jobs = jobs or JobService(controller)

    def run(self, study_id: str, plan: ReceptorPreparationPlan, **run_options) -> ProcessResult:
        Path(plan.request.cwd).mkdir(parents=True, exist_ok=True)
        result = self.jobs.run(
            study_id, "preparation_and_pocket_detection", plan.request,
            required_outputs=plan.required_outputs, **run_options,
        )
        if result.status.value == "completed":
            discovered = [
                ("prepared-receptor-pdb", "prepared_receptor_structure", plan.receptor_pdb),
                ("prepared-receptor-pdbqt", "prepared_receptor", plan.receptor_pdbqt),
                ("receptor-preparation-run-log", "preparation_log", plan.run_log),
            ]
            discovered.extend(
                (_report_artifact_id(plan.output_root, path), "preliminary_report", path)
                for path in sorted(plan.output_root.rglob("*.pdf"))
            )

            def register(latest) -> None:
                known = {artifact.id for artifact in latest.artifacts}
                for artifact_id, kind, path in discovered:
                    if artifact_id in known:
                        continue
                    latest.artifacts.append(ArtifactRecord(
                        artifact_id, kind, str(path.resolve()), _sha256(path),
                        (
                            "Existing preliminary scientific report; registered without modification"
                            if kind == "preliminary_report"
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
