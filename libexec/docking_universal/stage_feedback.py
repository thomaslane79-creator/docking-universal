"""Observable, GUI-ready milestones for supervised scientific stages.

These probes inspect produced artifacts, never infer scientific success from log text.
The job's terminal status remains authoritative.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


Feedback = tuple[str, str, Optional[int], Optional[int]]


def _ready(path: Path) -> bool:
    return path.is_file() and path.stat().st_size > 0


def preparation_feedback(root: Path, receptor_pdb: Path, receptor_pdbqt: Path) -> Feedback:
    if any(_ready(path) for path in (root / "preliminary-pocket-review.pdf", *root.glob("*.pdf"))):
        return "report", "Preliminary pocket report is ready; finishing preparation…", 4, 4
    if any(root.glob("cavity/*pocket*.conf")):
        return "pockets", "Docking regions detected; preparing the evidence report…", 3, 4
    if _ready(receptor_pdbqt):
        return "receptor", "Receptor prepared; detecting docking regions…", 2, 4
    if _ready(receptor_pdb):
        return "coordinates", "Receptor coordinates processed; preparing docking atoms…", 1, 4
    return "input", "Reading and validating the receptor structure…", 0, 4


def finalization_feedback(protocol: Path, report: Path, bundle: Path) -> Feedback:
    if _ready(bundle):
        return "bundle", "Portable protocol bundle written; verifying final outputs…", 3, 3
    if _ready(report):
        return "report", "Final report generated; packaging the protocol bundle…", 2, 3
    if _ready(protocol):
        return "protocol", "Approved protocol recorded; generating report figures…", 1, 3
    return "setup", "Building the protocol from approved preparation and regions…", 0, 3


def screening_feedback(output: Path, total_docking_jobs: int) -> Feedback:
    reports = output / "report"
    if any(_ready(path) for path in reports.glob("*.pdf")):
        return "report", "Screening report written; registering results…", None, None
    completed = sum(
        1 for path in output.glob("compounds/*/seed_*/docking/*_vina.pdbqt") if _ready(path)
    ) if output.is_dir() else 0
    if total_docking_jobs > 0 and completed >= total_docking_jobs:
        return "analysis", "Docking outputs ready; clustering poses and generating the report…", None, None
    if completed:
        return "docking", f"Docking outputs ready: {completed}/{total_docking_jobs}", completed, total_docking_jobs
    return "ligands", "Preparing ligand conformers and starting docking…", 0, total_docking_jobs


def control_feedback(output: Path) -> Feedback:
    if any(_ready(path) for path in output.glob("*.duprotocol")):
        return "bundle", "Control protocol bundle detected; verifying the final result…", 3, 3
    if _ready(output / "study_manifest.json"):
        return "assessment", "Control docking complete; checking pose recovery and report…", 2, 3
    if any(output.glob("control/**/protocol.json")):
        return "redocking", "Known-ligand redocking complete; evaluating pose recovery…", 1, 3
    return "preparation", "Preparing the known complex and starting control redocking…", 0, 3
