# Site-first ligand evidence and optional prediction

Scope: user-authorized correction, 2026-10-17. Fresh desktop preparation with
or without a ligand must permit related-PDB evidence lookup. Known-ligand
controls must pause for site review before redocking. The user additionally
requests optional P2Rank prediction even when a ligand is present.

Status: implemented, installed with backups, and final installed acceptance
passed. Restart the desktop app to use the update in a new study; previously
locked studies keep their original scientific records.

## User-facing behavior

The scientific pathway and the site-discovery option are separate. A
ligand-bound study remains ligand-bound when optional prediction is enabled.
Use the selected ligand site with other related-PDB evidence, or additionally
run P2Rank to review alternative pockets. Merely running P2Rank neither changes
the pathway/control status nor selects any extra region for docking.

- **Selected bound ligand** retains the observed ligand site without requiring
  P2Rank. The older ligand-centered preparation uses fpocket only as local
  cavity context; this is not a P2Rank prediction.
- **Also run P2Rank to look for other pockets?** is unchecked by default and runs the chosen
  detector, P2Rank by default, on the prepared ligand-removed receptor. It
  preserves the exact input-ligand region for review alongside predictions.
  fpocket remains an explicitly selectable fallback, not a hidden substitute
  when P2Rank was requested.
- **Search related public PDB structures** is independent of prediction and
  remains available for ligand-bound and control pathways. Offline choice,
  lookup failures and incomplete coverage are explicit; failed lookup does
  not discard otherwise successful preparation.
- Qualified related-structure ligand sites remain directly selectable L#
  boxes without P2Rank, either alone or with the input site. They do not need
  a detector score. A dedicated GUI journey checks selecting L1 alone with
  prediction off, explicit site approval, no control search, and reopening.
- The input ligand defines a site, not new independent evidence. It does not
  add an experimental observation or a green evidence ring. A known input
  PDB entry from HEADER is excluded from related-entry evidence; its identity
  is not inferred from a filename when absent. Reference coordinates remain
  retained separately. Distinct other PDB entries remain eligible for the
  existing sequence/alignment/contact checks.
- Predicted P# boxes retain detector scores. Input-bound B1 and other
  ligand-defined regions have no invented score. B1 uses the exact selected
  ligand instance and a centroid-centered 26 Å minimum box, expanding axes if
  necessary to enclose a large ligand plus 4 Å. This is a box policy, not
  measured cavity geometry. Effectively identical boxes (all six geometry
  values within 0.5 Å) retain both provenance sources as one choice.
- Review and explicitly approve one or more regions before control. Only the
  tested region/receptor/engine/settings can receive control authority.
  Other sites and untested receptor states remain exploratory and require
  explicit exploratory protocol finalization. No control authorizes a larger
  multi-site protocol simply because one site passes.
- Reopening is read-only with respect to science. Existing studies/protocols
  are not migrated, reapproved or modified; imported protocols remain locked.

## Validation records

Source GUI/host fresh RCSB 2R5P download, exact MK1 B:902 selection, real
Reduce2/Meeko preparation and fresh related-entry lookup:
`validation/runs/site-first-control-20261017_b/summary.json`.
This first acceptance inspected 20 entries/18 observations before the later
explicit self-entry exclusion. It stops at durable site review, with zero
scientific approvals and zero docking searches. Those counts are historical,
not the final self-excluded lookup counts.

Real source P2Rank plus bound-ligand preparation with online evidence disabled:
`validation/runs/bound-ligand-p2rank-20261017/review_validation.json`.
Three P2Rank candidates plus exact input B1 were retained. The first harness
incorrectly required an online-evidence record in offline mode and stopped
after successful preparation. Its failed `summary.json` is preserved. A
read-only postflight verified the results and GUI reopening without repeating
preparation, approving sites or docking. The subsequent input-evidence-count
correction is tested separately and in final installed acceptance.

Regression logs under `validation/runs/site-first-control-20261017_b/` cover
online/offline/error paths, approvals and hash changes, single-site versus
multi-site authority, receptor-state scope, GUI reopening, native control
handoff, finalization, reports and saved-protocol screening. The native handoff
uses synthetic chemistry and a calibration spy: it verifies reuse of the
exact prepared receptor/box and refuses unexpected preparation/search calls;
it does not establish scientific control performance.

Final checks: 254 scientific/workflow/report checks
(`scientific-regressions-install-ready.log`), 106 GUI checks
(`gui-regressions-final.log`) and 28 retained-engine/preparation checks
(`retained-engine-regressions.log`) pass; native control shell syntax passes.
Earlier failed logs remain retained: the first broad suite used a PATH that
selected macOS's Xcode-gated Python for a test fixture; another caught a
misplaced test assertion during test authoring. Both were corrected and the
complete scientific suite rerun. No scientific calculation was restarted.

The retained two-page `multisite-fixture` report was rendered and visually
checked. It is explicitly synthetic (fictional remote evidence, simulated
control), not a scientific result. It correctly identifies a separate P1-only
control and preserves the selected P1/L1 protocol as exploratory.

Initial source GUI acceptance also caught an existing-folder guard that
rejected the input folder created by the GUI's own download action. The guard
now permits input-only folders but rejects existing preparation/control stage
outputs. The failed first attempt remains under
`validation/runs/site-first-control-20261017/`; it performed no preparation or
docking.

Installation status and exact hashes are recorded in
`validation/runs/site-first-control-20261017_b/installation.json`; final
installed fresh-download/P2Rank/lookup acceptance is recorded in
`validation/runs/site-first-control-installed-20261017/summary.json`.
Installation uses targeted files, recoverable backups, protected-study hashes
and rollback if acceptance fails. No full-install/reinstallation or docking
reruns are part of this update.

Final installed acceptance: fresh downloaded 2R5P, exact MK1 B:902, real
Reduce2/Meeko/P2Rank and fresh related-entry lookup, approximately 32.4 seconds
for preparation/lookup. It retains three P2Rank candidates P1/P2/P3,
independent ligand-evidence site L1, and input-defined B1. The search inspected
20 other PDB entries and retained 20 ligand observations; 2R5P was explicitly
excluded as the input reference. B1 contributes no independent observation or
invented P2Rank score. Reopening preserved study state and the optional-prediction
choice; no sites were approved and no docking/control search was launched.
All 14 installed-file hashes match source; protected prior studies/results
remain unchanged. These entry/observation counts are results for this query,
not a promise of fixed coverage for future RCSB responses.

## Boundaries

Site-guidance wording follow-up: **Site definition** is now **Starting point
for site review**, with inline explanation that the final choice can include
one or more regions here or elsewhere. This wording is installed; 23 source
and 23 installed panel/journey checks pass. Existing study-state hashes remain
unchanged. Backup, logs and installed hash:
`validation/runs/site-guidance-wording-20261017/`. No geometry, science settings,
approvals or docking results were changed.

Checkbox-layout follow-up installed: redocking, related-PDB lookup and optional
additional prediction are independent recommended checkboxes. New structure
versus saved protocol is a separate source choice. Turning redocking off
preserves the selected ligand site and requires exploratory approval later.
All 108 GUI/workflow checks pass against the installed runtime. The installed
module matches source; all pre-installation study-state hashes remain unchanged.
Recoverable backup, exact hashes and logs are under
`validation/runs/site-options-checkboxes-20261017/`. This follow-up launches no
preparation, public lookup or docking and does not alter existing approvals.

Follow-up clarification: the optional checkbox now explicitly asks **Also run
P2Rank to look for other pockets?** and stays unchecked by default. A GUI
regression selects and approves a related-structure L1 box alone with prediction
disabled, then reopens the study without launching control/docking. Together
with the panel suite, 14 source checks pass; all 13 panel checks also pass
against the installed wording. Only `workflow_panels.py` was updated in this
follow-up, with its previous installed copy retained in
`validation/runs/p2rank-optional-prompt-20261017/`. The follow-up installed hash
is recorded there; the earlier 14-file installation record remains historical.

Automated GUI checks exercise actual widgets and the scientific host without
the native PyMOL widget; this is not fresh native-OpenGL acceptance. Real
preflight stops before any new scientific approval or control docking.
Low-level CLI primitives retain their explicit noninteractive behavior; this
change does not claim that every CLI command has acquired a GUI review pause.

The earlier three-engine raw-input coverage series remains paused. Its
corrected prepared receptor no longer meets the user's earlier byte-identical
approval-reuse condition; this UI update does not authorize continuation.
