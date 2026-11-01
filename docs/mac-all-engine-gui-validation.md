# Installed Mac three-engine functional validation

Follow-up: the report callout-clipping issue recorded below is now corrected
and installed. Original PyMOL renders were intact; the shared panel compositor
was cropping their edges. See [the correction and verification](report-snapshot-framing.md).
The original validation PDFs are preserved; corrected copies do not rerun docking.

2026-10-22: all three supported engine choices passed fresh installed GUI/host
docking, native result review and completed-study reopening on this Mac. PDF
visual review retains a separate callout-clipping issue. This is bounded
functional coverage, not universal chemistry acceptance or accuracy comparison.

## Coverage and scope

The registered Qt6/PyMOL desktop Python loaded the installed application and
scientific host. Each engine ran in a separate native application process with
isolated study directories and window settings. The previously reviewed 2R8N
receptor/P1 decision was reused; download, preparation, P2Rank and experimental
control calibration were not repeated.

Each engine finalized a fresh exploratory protocol and screened nevirapine and
rilpivirine with one retained starting shape per chemical state and one seed.
CPU search effort was 16, with 15 requested modes and an 8 kcal/mol window.
AD4 used its separate 20-genetic-run/12-million-evaluation-cap settings. These
are not matched scientific budgets. No production default was changed.

| Installed GUI engine | Two-compound screening | Native representative review | Reopening |
| --- | --- | --- | --- |
| AutoDock Vina | Passed | Six exact poses with PLIP contacts | Passed |
| QuickVina-W | Passed | Six exact poses with PLIP contacts | Passed |
| AutoDock-GPU, AD4 experimental | Passed | Five exact poses with PLIP contacts | Passed |

Checks covered all three GUI engine choices, finalized bundle identity,
compound selection/workload preview, completed energies/scoring identities,
retained diagrams, matching native 3D poses/contacts, paired review for each
compound and fresh-host reopening without scientific-state changes. Scientific
services, docking and native viewing were not mocked. Notification dialogs were
recorded; unexpected scientific decisions stopped the test rather than receiving
an automatic answer.

AD4 remains exploratory dry rigid-receptor Apple-Silicon docking, not production
experimental-ligand control calibration. AD4/Vina energies are not interchangeable.
This does not extend acceptance to Windows/Linux GPUs, unsupported chemistries,
all GUI settings or new receptor-preparation paths.

## Reader correction and regression checks

The first completed Vina case exposed real GUI `NA` energies: the collector
writes `affinity_kcal_per_mol`, whereas the overview only read older `affinity`
and `score` aliases. The GUI now reads the canonical column first, preserving
legacy aliases. Synthetic tests cover the real collector schema for all three
engine identities and canonical-column precedence.

Only that tested reader file was updated in the installed application, with
the previous file backed up. Completed Vina searches/reports were retained;
only their GUI review was repeated. Energies, poses, settings and dependencies
were not changed. The complete suite passes 737 Python cases/21 shell checks;
the focused Qt/result suite passes 92 cases.

The 697-entry protection audit matches the earlier accepted application update
plus this one reader correction, with no unexpected changes. Original user
studies, launch registrations, settings, descriptors and dependencies remain
unchanged. The same stale ReportLab metadata entry remains absent; this is not
a claim of 697 matching physical files.

## Report visual review and retained attempts

All six fresh protocol/screening PDFs were generated. Automated checks confirm
portrait format and model/units. All 33 rendered pages were inspected as contact
sheets, supplemented by larger settings/results/figure pages and native review
screenshots. Some saved 3D residue callouts extend beyond the image edge and are
partially cut off, including an AD4 rilpivirine panel. This engine-neutral report
image issue was left open in this initial audit, which was not an unqualified
visual pass. The follow-up linked above resolves it in corrected copies.
Interactive PyMOL and retained scientific outputs are unaffected. The
recurring macOS texture warning also appeared, while native views displayed
their matching molecules and contacts successfully.

Preserved failed attempts include sandboxed desktop initialization before any
case, a test-launcher PATH omission before docking, the completed-Vina reader
failure, and PyMOL singleton recreation before QuickVina docking. Separate native
processes fixed that test-driver limitation without repeating completed searches.
An initial regression invocation used Python without RDKit; the full rerun used
the configured scientific Python and passed.

Drivers: `validation/mac_all_engine_gui_acceptance.py` (one explicit engine per
native process) and `validation/mac_engine_pdf_audit.py` (read-only report and
protection audit). Final local evidence:
`validation/runs/mac-all-engine-gui-20261022-native-b/`, including `summary.json`,
preserved failures, screenshots, reader backup and `pdf-audit/summary.json`.
Scientific files/images/reports/numerical results remain local and excluded
from Git.
