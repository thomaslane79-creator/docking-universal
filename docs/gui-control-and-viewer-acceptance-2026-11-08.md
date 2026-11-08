# Control and interaction-viewer acceptance, November 8

The installed native Mac GUI completed a bounded public-1N6O walkthrough using
an isolated copy of the retained prepared study. The original Cox-2 study and
5IKR input were unchanged. This is not a claim that every raw-input preparation
path has passed native acceptance.

## Scientific workflow

The user-reviewed B1 region retained its exact geometry and the high-severity
warning for omitted Mg A201. The known-ligand control completed 36 sequential
Vina jobs (18 starting variants, two seeds). Its best sampled RMSD was 0.7006 Å
and global top-pose RMSD 1.3433 Å. It correctly remained **not approved** because
two seeds do not meet the required five. No validated protocol was created.

The native GUI then required explicit exploratory authorization, finalized an
exploratory protocol and screened the retained two-compound example. This
acceptance run deliberately used minimal settings, not a recommended screening
protocol. Both compounds completed. The retained paired 2D/3D review opened,
including detach/reattach and selection of Rilpivirine cluster 002.

One report gap remains: the screening PDF correctly refused incomplete software
provenance, naming ADFRsuite. The protocol PDF and screening figures exist, but
the screening PDF does not. Repair preparation-time version recording and test
a fresh run; do not infer a historical backend version from today's installation.

The current local renderer is unavailable because Chrome is absent. Retained
diagrams open without it. The retained diagram has no verified residue hit map,
so 2D residue picking remains explicitly disabled for that asset. Do not count
renderer regeneration or 2D residue picking as accepted.

## Corrections and checks

- Control progress recognizes real batch outputs instead of showing a premature
  completed assessment. Reopened old results also say that a failed/not-approved
  control did not create a validated protocol.
- Native PLIP interaction types now have labeled checkboxes. Individual type
  switching, master off/on with preserved choices, visibility on both detached
  tabs, and retained pose selection passed the native UI check.
- The actual native Retina PyMOL object list and mouse guide are readable after
  restart. The saved headless scene disables shaders; the legacy bitmap font
  ignores Retina scaling. For the full native Mac interface at >1× scale, use
  PyMOL's shader path and display scale, restoring original settings on return.
  Embedded, Windows and Linux renderer settings are unchanged.
- Background refresh no longer rebuilds unchanged selectors or resets the
  selected cluster while a user opens its menu.
- A second plain click on a selected evidence row now hides that ligand. A
  GUI event regression verifies multi-selection, synchronized main/detached
  panels, the viewer's empty-selection call, and unchanged scientific state.
- The detached pose browser exposes the existing “Open 2D/3D review” action,
  enabled only when its selected cluster has a retained diagram.

The focused offscreen Qt suite passes **155 tests** across contact controls,
linked review, embedded adapters, desktop workspace, evidence plots and stage
feedback. These event/adapter checks supplement, and do not replace, the native
observations above. The last two additions (second-click hiding and detached
paired-review access) still need a native confirmation after restart.

Installed modules retain original backups and before/after hashes under
`local-fix-backups/plip-detached-controls-20261108/manifest.json` and
`local-fix-backups/control-gui-feedback-20261108/manifest.json` (local only).
Native study assets are retained under
`validation/runs/qt-cocoa-acceptance-20261108/` (local only).

Duplicate P1/B1 consolidation and ADFR preparation-time provenance remain open
at this checkpoint. The template and charge-surface work stays behind these
repairs.
