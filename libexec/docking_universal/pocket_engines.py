"""Capability-driven pocket-engine discovery and normalized pocket records."""

from __future__ import annotations

import csv
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable


@dataclass(frozen=True)
class PocketEngineCapability:
    engine: str
    status: str
    executable: str | None
    runtime: str | None
    detail: str | None = None


@dataclass(frozen=True)
class P2RankRescorePlan:
    command: tuple[str, ...]
    dataset: Path
    output_directory: Path
    expected_rescored_csv: Path


def discover_pocket_engines(
    *, which: Callable[[str], str | None] = shutil.which,
    environment: dict[str, str] | None = None,
) -> dict[str, PocketEngineCapability]:
    """Discover engines by capability, without platform assumptions or installs."""
    values = dict(os.environ if environment is None else environment)
    fpocket = values.get("DOCKING_UNIVERSAL_FPOCKET") or which("fpocket")
    p2rank = (values.get("DOCKING_UNIVERSAL_P2RANK") or which("prank")
              or which("prank.bat") or which("prank.cmd") or which("p2rank"))
    java = values.get("DOCKING_UNIVERSAL_JAVA") or which("java")
    if not java and p2rank:
        prefix_java = Path(p2rank).resolve().parent.parent / "lib" / "jvm" / "bin" / "java"
        java = str(prefix_java) if prefix_java.is_file() else None
    return {
        "fpocket": PocketEngineCapability(
            "fpocket", "available" if fpocket else "unavailable", fpocket, None,
            None if fpocket else "fpocket executable not found",
        ),
        "p2rank": PocketEngineCapability(
            "p2rank", "available" if p2rank and java else "unavailable", p2rank, java,
            None if p2rank and java else (
                "P2Rank launcher not found" if not p2rank else "Java runtime not found"
            ),
        ),
    }


def available_pocket_modes(capabilities: dict[str, PocketEngineCapability]) -> list[dict]:
    """Expose scientifically distinct modes strictly from observed capabilities."""
    fpocket = capabilities["fpocket"].status == "available"
    p2rank = capabilities["p2rank"].status == "available"
    return [
        {
            "id": "p2rank", "label": "P2Rank",
            "available": p2rank,
            "description": "P2Rank-only machine-learning pocket prediction",
            "policy_role": "primary",
            "unavailable_reason": capabilities["p2rank"].detail if not p2rank else None,
        },
        {
            "id": "fpocket", "label": "fpocket",
            "available": fpocket,
            "description": "fpocket geometric cavity prediction",
            "policy_role": "fallback",
            "unavailable_reason": capabilities["fpocket"].detail if not fpocket else None,
        },
        {
            "id": "fpocket_p2rank_rescore", "label": "fpocket + P2Rank rescoring",
            "available": fpocket and p2rank,
            "description": "fpocket geometry re-ranked by P2Rank with both scores retained",
            "policy_role": "advanced_comparison",
            "unavailable_reason": None if fpocket and p2rank else "requires both fpocket and P2Rank",
        },
    ]


def build_p2rank_prediction_command(
    launcher: Path | str, receptor: Path | str, output_directory: Path | str,
    *, profile: str = "default",
) -> tuple[str, ...]:
    """Build the native P2Rank-only prediction command used on every platform."""
    launcher, receptor = Path(launcher).resolve(), Path(receptor).resolve()
    if not launcher.is_file():
        raise FileNotFoundError(f"P2Rank launcher does not exist: {launcher}")
    if not receptor.is_file():
        raise FileNotFoundError(f"Receptor does not exist: {receptor}")
    output_directory = Path(output_directory).resolve()
    return (str(launcher), "predict", "-f", str(receptor), "-c", profile,
            "-visualizations", "0", "-o", str(output_directory))


def parse_p2rank_predictions(path: Path | str) -> list[dict]:
    """Normalize a P2Rank predictions CSV without assigning biological validity."""
    path = Path(path)
    records = []
    with path.open(newline="") as handle:
        for rank, raw in enumerate(csv.DictReader(handle), 1):
            row = {str(key).strip(): value.strip() for key, value in raw.items() if key is not None}
            def number(*names):
                value = next((row[name] for name in names if row.get(name) not in (None, "")), None)
                return float(value) if value is not None else None
            center = [number("center_x", "center x"), number("center_y", "center y"), number("center_z", "center z")]
            records.append({
                "schema_name": "docking-universal-pocket-candidate",
                "schema_version": 1,
                "candidate_id": f"p2rank:{row.get('name') or rank}",
                "engine": "p2rank", "engine_rank": rank,
                "engine_score": number("score"), "probability": number("probability"),
                "center_angstrom": center,
                "lining_residues": row.get("residue_ids") or row.get("residue ids") or "",
                "source_artifact": str(path.resolve()),
                "interpretation": "machine-learning pocket hypothesis; user decision required",
                "automation_eligible": False,
            })
    return records


def build_p2rank_fpocket_rescore_plan(
    launcher: Path | str, receptor: Path | str, fpocket_output: Path | str,
    output_directory: Path | str,
) -> P2RankRescorePlan:
    """Write the explicit upstream dataset contract for rescoring retained fpocket output."""
    launcher, receptor, fpocket_output = map(lambda value: Path(value).resolve(),
                                             (launcher, receptor, fpocket_output))
    for label, path in (("P2Rank launcher", launcher), ("receptor", receptor),
                        ("fpocket output", fpocket_output)):
        if not path.is_file():
            raise FileNotFoundError(f"{label} does not exist: {path}")
        if any(character.isspace() for character in str(path)):
            raise ValueError(f"{label} path contains whitespace unsupported by the P2Rank dataset format: {path}")
    output_directory = Path(output_directory).resolve()
    output_directory.mkdir(parents=True, exist_ok=True)
    dataset = output_directory / "fpocket_rescore.ds"
    dataset.write_text(
        "PARAM.PREDICTION_METHOD=fpocket\n\n"
        "HEADER: prediction protein\n"
        f"{fpocket_output} {receptor}\n"
    )
    expected = output_directory / f"{receptor.name}_rescored.csv"
    return P2RankRescorePlan(
        command=(str(launcher), "rescore", str(dataset), "-o", str(output_directory)),
        dataset=dataset, output_directory=output_directory,
        expected_rescored_csv=expected,
    )


def parse_p2rank_rescoring(path: Path | str) -> list[dict]:
    """Normalize PRANK re-ranking while preserving fpocket's original rank."""
    path = Path(path)
    records = []
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            cleaned = {str(key).strip(): value.strip() for key, value in row.items() if key}
            old_rank = int(cleaned["old_rank"])
            records.append({
                "schema_name": "docking-universal-pocket-rescoring",
                "schema_version": 1,
                "candidate_id": f"fpocket:P{old_rank}",
                "source_engine": "fpocket", "original_fpocket_rank": old_rank,
                "rescoring_engine": "p2rank", "p2rank_rank": int(cleaned["rank"]),
                "p2rank_score": float(cleaned["score"]),
                "rank_change": int(cleaned.get("change") or old_rank - int(cleaned["rank"])),
                "source_artifact": str(path.resolve()),
                "interpretation": "P2Rank re-ranking of an fpocket-generated cavity; both ranks remain evidence",
                "automation_eligible": False,
            })
    return records


def merge_pocket_evidence(*candidate_sets: Iterable[dict]) -> list[dict]:
    """Retain independent engine evidence without collapsing unlike scores."""
    return [dict(candidate) for candidates in candidate_sets for candidate in candidates]
