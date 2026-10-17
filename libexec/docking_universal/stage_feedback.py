"""Observable, GUI-ready milestones for supervised scientific stages.

These probes inspect produced artifacts, never infer scientific success from log text.
The job's terminal status remains authoritative.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional
from .screening_progress import read_screening_progress


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
    # These are advisory worker milestones, never a successful terminal status.
    record = read_screening_progress(output)
    completed = sum(1 for pattern in ('compounds/*/seed_*/docking/*_vina.pdbqt',
                                     'compounds/*/site_*/seed_*/docking/*_vina.pdbqt')
                    for path in output.glob(pattern) if _ready(path)) if output.is_dir() else 0
    if record:
        phase = record['phase']
        message = record['message'][:600]
        if phase == 'compound':
            identifier = record.get('compound_id')
            # Never follow an arbitrary worker-supplied path outside this run.
            if (isinstance(identifier, str) and identifier not in ('', '.', '..')
                    and Path(identifier).name == identifier
                    and (output / 'compounds' / identifier).resolve().parent == (output / 'compounds').resolve()):
                child = read_screening_progress(output / 'compounds' / identifier)
                phase = child.get('phase', 'ligands')
                message = child.get('message', message)[:600]
            name = ' '.join(str(record.get('compound_name', identifier or 'compound')).split())[:120]
            message = (f"Compound {record.get('compound_index', '?')}/{record.get('compound_total', '?')}: "
                       f"{name} — {message}")
        failures = record.get('failed_compounds', 0)
        if isinstance(failures, int) and failures > 0:
            message += f' {failures} earlier compound(s) failed; retained successes continue.'
        if completed or phase == 'docking':
            message += f' Docking output files written: {completed} (initial plan: {total_docking_jobs}).'
        # State enumeration can change the actual job count. Do not turn the
        # initial estimate or a finished per-compound phase into 100% completion.
        if phase == 'docking' and 0 <= completed < total_docking_jobs:
            return phase, message, completed, total_docking_jobs
        return phase, message, None, None
    reports = output / "report"
    if any(_ready(path) for path in reports.glob("*.pdf")):
        return "report", "Screening report written; registering results…", None, None
    if total_docking_jobs > 0 and completed >= total_docking_jobs:
        return "analysis", "Docking outputs reached the initial plan; additional states or analysis/reporting may still be running…", None, None
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
