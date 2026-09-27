"""Plan and discover outputs for locked-protocol screening."""

from __future__ import annotations

import hashlib
import json
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from docking_universal_bundle import CONTROL_VALIDATED, protocol_can_screen, protocol_type

from ..models import ArtifactRecord


@dataclass(frozen=True)
class ScreeningPlan:
    protocol_type: str
    target: str
    engine: str
    compound_count: int
    conformers_per_compound: int
    independent_seed_count: int
    docking_site_count: int
    receptor_state_variant_count: int
    affected_docking_site_count: int
    jobs_per_compound: int
    baseline_docking_jobs: int
    additional_sensitivity_jobs: int
    total_docking_jobs: int
    exploratory_authorization_required: bool
    receptor_region_tasks: tuple[dict[str, Any], ...]
    parameters: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_protocol_record(path: Path | str) -> dict[str, Any]:
    source = Path(path).resolve()
    if source.suffix.lower() == ".duprotocol":
        try:
            with zipfile.ZipFile(source) as archive:
                manifest = json.loads(archive.read("bundle_manifest.json"))
                value = json.loads(archive.read(manifest["protocol"]))
        except (KeyError, OSError, zipfile.BadZipFile, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid Docking Universal protocol bundle: {exc}") from None
    else:
        try:
            value = json.loads(source.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid Docking Universal protocol: {exc}") from None
    if not isinstance(value, dict) or value.get("schema_name") != "docking-universal-protocol":
        raise ValueError("Protocol is missing the supported docking-universal-protocol schema")
    if not protocol_can_screen(value):
        raise ValueError("Protocol is not authorized for screening")
    return value


def count_ligands(source: Path | str) -> int:
    path = Path(source).resolve()
    if path.is_dir():
        files = sorted(item for item in path.glob("*.sdf") if item.is_file())
    elif path.is_file() and path.suffix.lower() == ".sdf":
        files = [path]
    else:
        raise FileNotFoundError(f"Ligand source must be an SDF file or directory: {path}")
    count = 0
    for item in files:
        text = item.read_text(errors="replace")
        count += sum(1 for line in text.splitlines() if line.strip() == "$$$$")
        if "$$$$" not in text and text.strip():
            count += 1
    if count < 1:
        raise ValueError("Ligand source contains no apparent SDF records")
    return count


def build_receptor_region_matrix(protocol: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    """Expand approved regions only where retained receptor-state comparison is required."""

    locked = protocol.get("locked_inputs") or {}
    regions = locked.get("boxes") or [locked.get("box")]
    regions = [region for region in regions if region]
    sensitivity = protocol.get("receptor_state_sensitivity") or {}
    affected = set(map(str, sensitivity.get("affected_boxes") or ()))
    variants = sensitivity.get("variants") or {}
    primary_state = str(sensitivity.get("primary_review_state") or "primary")
    tasks = []
    for index, raw_region in enumerate(regions, 1):
        region = raw_region if isinstance(raw_region, dict) else {"box": raw_region}
        label = str(region.get("box_label") or f"site-{index}")
        if label in affected:
            if len(variants) < 2:
                raise ValueError(
                    f"Docking region {label} requires receptor-state comparison but lacks both variants"
                )
            order = sorted(variants, key=lambda value: (value != primary_state, value))
            for state_name in order:
                variant = variants[state_name]
                receptor = variant.get("receptor_pdbqt") if isinstance(variant, dict) else None
                if not receptor:
                    raise ValueError(f"Receptor-state variant {state_name} lacks a prepared PDBQT")
                tasks.append({
                    "box_label": label,
                    "box": region.get("box"),
                    "receptor_state": state_name,
                    "receptor": receptor,
                    "receptor_sha256": variant.get("receptor_pdbqt_sha256"),
                    "sensitivity_comparison": True,
                })
        else:
            tasks.append({
                "box_label": label,
                "box": region.get("box"),
                "receptor_state": primary_state,
                "receptor": locked.get("receptor"),
                "receptor_sha256": locked.get("receptor_sha256"),
                "sensitivity_comparison": False,
            })
    return tuple(tasks)


def build_screening_plan(
    protocol_path: Path | str,
    ligand_source: Path | str,
    *,
    expected_protocol_sha256: str | None = None,
) -> ScreeningPlan:
    path = Path(protocol_path).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Reusable protocol does not exist: {path}")
    if expected_protocol_sha256 and _sha256(path) != expected_protocol_sha256:
        raise ValueError("Registered reusable protocol changed after finalization")
    protocol = read_protocol_record(path)
    parameters = dict(protocol.get("parameters") or {})
    conformers = int(parameters.get("conformers_per_state", 0))
    seeds = parameters.get("seeds") or []
    regions = protocol.get("locked_inputs", {}).get("boxes") or [
        protocol.get("locked_inputs", {}).get("box")
    ]
    if conformers < 1 or not seeds or not regions:
        raise ValueError("Protocol lacks complete conformer, seed, or docking-site settings")
    compounds = count_ligands(ligand_source)
    sensitivity = protocol.get("receptor_state_sensitivity") or {}
    variants = sensitivity.get("variants") or {}
    affected_labels = set(map(str, sensitivity.get("affected_boxes") or ()))
    affected_regions = sum(
        1 for region in regions
        if str((region or {}).get("box_label") or "") in affected_labels
    )
    variant_count = len(variants) if affected_regions else 1
    receptor_region_tasks = build_receptor_region_matrix(protocol)
    baseline_per_compound = conformers * len(seeds) * len(regions)
    additional_per_compound = (
        conformers * len(seeds) * affected_regions * (variant_count - 1)
    )
    jobs_per_compound = baseline_per_compound + additional_per_compound
    kind = protocol_type(protocol)
    return ScreeningPlan(
        protocol_type=str(kind), target=str(protocol.get("target") or "not recorded"),
        engine=str(protocol.get("engine") or "not recorded"), compound_count=compounds,
        conformers_per_compound=conformers, independent_seed_count=len(seeds),
        docking_site_count=len(regions), receptor_state_variant_count=variant_count,
        affected_docking_site_count=affected_regions,
        jobs_per_compound=jobs_per_compound,
        baseline_docking_jobs=compounds * baseline_per_compound,
        additional_sensitivity_jobs=compounds * additional_per_compound,
        total_docking_jobs=compounds * jobs_per_compound,
        exploratory_authorization_required=kind != CONTROL_VALIDATED,
        receptor_region_tasks=receptor_region_tasks,
        parameters=parameters,
    )


def discover_screening_artifacts(output_root: Path | str) -> list[ArtifactRecord]:
    root = Path(output_root).resolve()
    patterns = (
        ("screening_study_manifest", "study_manifest.json"),
        ("screening_report", "report/*.pdf"),
        ("screening_report_figure", "report/*.png"),
        ("screening_summary", "report/study_summary.json"),
        ("screening_compound_manifest", "compounds/*/screen_manifest.json"),
        ("screening_scores", "compounds/*/all_scores.csv"),
        ("screening_pose_clusters", "compounds/*/pose_analysis/cluster_summary.csv"),
        ("screening_pose_session", "compounds/*/pose_analysis/*.pse"),
        ("screening_pose_session", "compounds/*/site_*/pose_analysis/*.pse"),
        ("screening_interaction_diagram", "compounds/*/pose_analysis/cluster_*/interactions/representative_plip2d.png"),
        ("screening_interaction_diagram", "compounds/*/site_*/pose_analysis/cluster_*/interactions/representative_plip2d.png"),
        ("screening_interaction_record", "compounds/*/pose_analysis/cluster_*/interactions/report.xml"),
        ("screening_interaction_record", "compounds/*/pose_analysis/cluster_*/interactions/report.txt"),
        ("screening_interaction_record", "compounds/*/site_*/pose_analysis/cluster_*/interactions/report.xml"),
        ("screening_interaction_record", "compounds/*/site_*/pose_analysis/cluster_*/interactions/report.txt"),
    )
    records = []
    seen = set()
    for kind, pattern in patterns:
        for path in sorted(root.glob(pattern)):
            resolved = path.resolve()
            if not path.is_file() or resolved in seen:
                continue
            seen.add(resolved)
            relative = str(resolved.relative_to(root))
            identity = hashlib.sha256(relative.encode()).hexdigest()[:16]
            description = (
                "Chemically typed PLIP 2D interactions for the lowest-energy member "
                "of one selected pose cluster"
                if kind == "screening_interaction_diagram"
                else "Retained machine-readable PLIP interaction evidence"
                if kind == "screening_interaction_record"
                else "Retained locked-protocol screening output"
            )
            records.append(ArtifactRecord(
                id=f"{kind}-{identity}", kind=kind, path=str(resolved),
                sha256=_sha256(resolved), description=description,
            ))
    return records
