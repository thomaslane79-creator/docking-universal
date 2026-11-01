# Mac GUI and documentation synchronization — 2026-10-22

Subsequent fresh three-engine validation found and corrected a canonical
energy-column reader mismatch. The installed GUI now reads real collector
outputs as well as legacy aliases. All three bounded GUI docking/review/reopen
paths pass; a report-image callout-clipping issue remains separately recorded.
See [the follow-up validation](mac-all-engine-gui-validation.md). The no-redocking
scope and counts below describe the earlier synchronization task only.

## Bounded corrections

The user authorized fixing the Mac GUI/documentation review findings. The
working Mac application now includes the tested no-prediction report handling
and retained P2Rank-operation version handoff, alongside the source fixes.
Missing software provenance still fails; no version is queried or guessed to
replace the version that actually produced a scientific result.

The results overview now shows **Best energy (kcal/mol)** followed immediately
by **Scoring function**. The latter uses the compound's retained screening
engine: Vina and QuickVina-W map to Vina; AutoDock-GPU maps to AD4. A missing
or unfamiliar historical identity says **Not recorded**, irrespective of the
current GUI settings. Expanded pose review says **Energy** and keeps its
per-cell kcal/mol units. No energies or scientific records are rewritten.

The guide, README and ligand-free tutorial now distinguish P2Rank primary
prediction from the fpocket fallback, and identify Vina as the default docking
engine. Advanced terminal-only region definitions are not advertised as GUI
dropdown choices. Static report figures are viewed in reports, not a removed
GUI figure browser. Historical toolkit notes are marked historical, with links
to current embedded-PyMOL packaging. The main guide now links and explains the
existing top-20 cluster/control-global-RMSD rules, colors and coordinate basis;
the plotting/selection rules themselves are unchanged.

The protocol-layout validator now checks all three engine forms, including
which controls should be visible. Intentionally hidden fields are not assigned
meaningless geometry checks. Help remains modeless and cannot approve a study.

## Additional control-only report defect found during verification

Rendering a copied completed control exposed another report-dispatch error:
the absence of prospective compound clusters was treated as absence of all
docking. An inherited ligand-defined cavity record then triggered an early
preparation-only return, omitted the control section and incorrectly said no
docking or interaction analysis was performed.

The report now distinguishes retained prospective results from an actual
retained control landscape. A nonempty control-cluster table permits its
control section and docking-method provenance without inventing a new-compound
results page. A claimed approval or intended input alone is not enough.
Dedicated helper and whole-report-flow regressions cover this distinction.

## Local verification and limits

- The final complete suite passes 737 Python cases and 21 shell checks.
- 163 GUI/result regressions pass, including Vina, QuickVina-W, AD4 and unknown
  scoring identities; 73 focused report/cavity/artifact cases pass.
- All 231 protocol-layout checks pass at 960/1280/1440 widths for the three
  engine forms; all 77 screening-layout checks pass.
- Ten checks against the actual installed application pass in the registered
  Qt6 desktop Python. The detached results table fits both energy columns;
  no synthetic review action changes study authority.
- The installed public command's version and installation checks pass.
- A report-only integration check reuses completed public biotin-control
  results and accepted retained figures in an isolated copied study. The
  installed generator produces a four-page portrait PDF with the control
  results, no false no-docking statement and no invented prospective section.
  All four pages were rendered and visually inspected. All 1,021 original
  fixture files remain hash-identical. No preparation, search, PLIP analysis
  or scientific approval was repeated.
- Only four installed application files changed: the PDF generator, result
  model, result panel and the desktop's result-row projection. The Mac desktop
  receives only that one-line row-projection patch rather than unrelated
  Windows capability changes. All other 693 entries in the pre-update
  protection snapshot are unchanged, including the pre-existing missing stale
  ReportLab metadata entry. Dependencies, launchers/runtime registrations,
  settings, GPU descriptors, saved studies and existing PDFs are untouched.

Exact file hashes and check counts are recorded in the local verification summary.
This is a Mac presentation/reporting update, not a new scientific benchmark,
Windows rerun or GPU certification. New labels appear after restarting the
desktop. Existing completed PDFs are not silently regenerated.

Local-only evidence, omitted from Git:
`validation/runs/mac-gui-doc-sync-20261022/`. It contains the pre-update hashes,
recoverable application-file backups, installed-check summary/screenshot and
the report-only copy. Early validation attempts remain preserved: an incorrect
test-driver method name and an overly strict subprocess allowlist were fixed;
the first completed PDF exposed the control-only classification defect above.
The final installed checks and corrected report are separate successful records.
Scientific structures, diagrams, reports and their numerical evidence remain
local and are not uploaded.
