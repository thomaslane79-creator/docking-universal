# Fresh-study saved-protocol reuse acceptance

Completed locally on macOS, 2026-10-17. This is a workflow/integrity test, not a
pose-recovery control or a comparison of docking accuracy.

## Implemented route

Create a fresh study and select **Study setup → Scientific pathway → Use a saved
protocol**. The application host verifies the bundle inventory and locked input
hashes. The user reviews the target, scientific status and selectable settings,
then explicitly imports. A study-owned copy is registered with a content hash;
source-file changes between review and import are rejected. Import into an
existing prepared/imported study is rejected rather than replacing its work.

Screening uses the existing engine-locked runner, not a new docking path. It
requires separate exploratory approval where applicable. Inherited preparation,
regions and settings are labeled as inherited/locked, not represented as newly
performed stages or fabricated approval decisions. Imported settings can be
reviewed again, including after reopening. Engine/settings overrides are not
accepted by the import command.

The snapshot writer closes its temporary-file handle before copying/publishing,
so the import implementation does not rely on Unix-only open-file behavior.
Windows/Linux native acceptance remains separate; this test does not certify
their engines, GUI runtimes or installers.

## Real vertical acceptance

Record: `validation/runs/protocol-reuse-20261017_b/summary.json`.

- Imported the retained 2R8N exploratory Vina bundle into a genuinely new study
  through the GUI/application host; no receptor preparation was rerun.
- Verified all 188 inventoried bundle files. Moved the isolated source bundle
  after import, then screened and reopened using only the study-owned snapshot.
- Read a three-record SDF through the embedded reader; checked two records and
  left the duplicate unchecked. Only Nevirapine and Rilpivirine were screened.
- Preserved pH 7.4, up to three starting shapes, five seeds, exhaustiveness 16,
  15 requested poses and an 8 kcal/mol energy window. Analysis used the existing
  three representatives and 1.5 Å clustering default.
- The workload preview was an upper estimate of 30 searches. Preparation
  retained two shapes for Nevirapine and three for Rilpivirine, producing 25
  actual docking outputs across five seeds. No search settings were reduced.
- One sequential screening job completed without compound failures. Supervised
  screening time, including ligand preparation, searches, analysis and reports,
  was 317.86 seconds. This is not a performance comparison.
- A fresh application host reopened both result rows, retained interaction
  choices and elapsed time without changing the completed scientific state.
- The original user study and source protocol bundle remained byte-identical.

The nine-page portrait report was rendered and visually reviewed. It includes
protein/source-species identity, actual selected pocket metadata, locked settings,
both completed compounds, Vina identification beside scores, top-20 cluster
tables and the 1.5 Å clustering statement. This run has no experimental ligand
control; its plotted RMSD is relative to the lowest-energy cluster representative,
not experimental crystal RMSD.

## Regressions and native viewer checks

- 127 GUI/host/screening tests pass: `gui-regressions.log`.
- 53 protocol/report/import tests pass in the scientific runtime:
  `report-regressions.log`. These include changed/damaged bundles, locked hashes,
  unlisted/traversal entries, stale revisions, repeated requests, attempted
  replacement, authority preservation and active-stage rejection.
- 24 real import/selection/screen/reopen assertions pass.
- 61 native retained-pose checks pass against source, and another 61 pass against
  the installed application: `native-review/verification.json` and
  `installed-native-review/verification.json`. They exercise six representatives,
  exact ligand coordinates, PLIP contacts, residue/type toggles, paired review,
  detached PyMOL and restoration without docking or scientific-state changes.

The constrained screening harness did not expose Node on its search path, so
its report retained the existing SDF/PLIP fallback diagrams. This is recorded,
not evidence that the approved browser-based layout was exercised. The installed
native viewer check explicitly configured the available local Node runtime.
The existing macOS `GLD_TEXTURE_INDEX_2D` warning appeared during native startup;
the actual viewer checks passed despite it. This work does not claim to remove
that graphics-driver warning.

## Problems found and resolved

The first isolated attempt, `validation/runs/protocol-reuse-20261017/`, failed
before any Vina searches: its restricted path omitted Conda. The corrected run
uses the existing engine environment; the failed outputs/logs remain retained.
That attempt also exposed a real reuse-report problem: P2Rank's version was read
from the new ligand-screening runtime even though pocket detection was not
rerun. Reports now use the detector version recorded in the locked protocol,
while retaining current-run ligand/docking versions. A regression covers this.

Running real PDF integration tests in the GUI-only Python failed their missing-
PyMOL provenance guard. Rerunning them in the scientific runtime passed; the
guard was not weakened. The first installation smoke harness also passed a
Python Path where its JSON command expected a string. That harness was corrected;
the failed installation automatically restored the previous files, without
docking. The subsequent installed import, locked preview and result reopen pass.

## Local installation

`validation/runs/protocol-reuse-20261017_b/installation-2.json` records the seven
installed files, their hashes and previous hashes. Recoverable backups are in
`installation-backup-2/`. The installed-host smoke test imports a new disposable
study and previews its selection without docking; it also reopens the completed
real screen. The installed native check passes with retained inputs only.

Restart the desktop app to load the update. No production defaults, scientific
search methods, original studies or original reports were changed. AD4 bundle
inspection was checked, but this fresh-study real screen used Vina; it does not
constitute another AD4 calibration or platform validation.
