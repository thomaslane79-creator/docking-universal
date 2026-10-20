# Native Windows reviewed-control port — candidate, not enabled

The exploratory Vina/QuickVina-W GUI, private renderer and interactive software
viewer passed at `50a8ef2`; see [the completed gate](windows-viewer-engine-validation.md).
That success does not validate the separate known-ligand control path.

The next bounded port removes Bash orchestration only. It reuses the existing
strict coordinate-free CCD chemistry helper, independent conformer generator,
Meeko preparation/export, Vina-family adapters, calibration tiers, no-fit
crystal RMSD evaluation, approval rules and ordinary reports. The experimental
coordinates remain withheld from docking starting shapes. No legacy
single-conformer, inferred-chemistry, deletion-permitting or silent engine
fallback is added. Both engines retain their identities and original settings.

Native ligand-only preparation skips Java/P2Rank when the user does not request
prediction. It records no detector score/cavity. The host verifies the retained
source and constructs its exact unscored input-ligand site before explicit
approval. Optional P2Rank still predicts on the ligand-removed receptor. The
input ligand defines a site; it is not independent experimental corroboration.
Related-structure evidence remains a separate choice and additional untested
sites remain exploratory.

Windows control comparison now uses the same literal executable discovery and
byte-preserving Meeko filename transport as clustering, in the owned ASCII
staging folder. Missing new SDF output cannot be mistaken for a previous result.
Unix keeps its existing executable/file arguments; no exported molecular data
or energy is transformed by the transport.

`native_control_supported` stays **false** in normal installations. The native
acceptance driver enables it only in its fresh disposable installation and
restores that configuration after closing/reaping the host. It exercises actual
Qt buttons and the owned scientific host with public 1STP/biotin BTN A:300:

- Vina, exact ligand site without P2Rank;
- QuickVina-W, exact ligand site plus optional P2Rank;
- explicit site review before any redocking, reused sealed receptor/box;
- unchanged default quick calibration (three conformers, two seeds,
  exhaustiveness 16, 15 poses, 8 kcal/mol window);
- the five-seed approval requirement must keep these quick runs unapproved,
  even if they recover a pose; no approved bundle may be published;
- separate repeatability-tier fixtures with both engines must pass the actual
  unchanged five-seed sampling/ranking rules, publish approved bundles, and
  verify their portable receptor/site hashes. They are fresh disposable studies,
  not a silent escalation/retry of the quick studies;
- normal report generation, unchanged reviewed inputs and complete host cleanup.

These are compatibility/workflow fixtures, not target-accuracy or engine-
superiority benchmarks. Only status/check names/counts, exception types and code
locations are retained outside the runner. Structures, poses, diagrams, reports,
scientific logs and numerical structural evidence remain runner-local. No
completed user study or working Mac installation is changed.

Local evidence so far: 723 Python cases/21 shell checks pass, including the
report-synchronization regressions now in the normal test target;
targeted control/transport/authority tests and 110 separate Qt
cases pass. Real isolated Mac preparations of public 2R5P and 1STP mmCIF inputs
complete Reduce2, strict Meeko and the component audit without running P2Rank.
The new stage also completes the unchanged quick biotin control locally,
including independent conformers, two seeds, comparisons and reference/pose
visuals. It correctly withholds approval under the five-seed rule. This is not
native Windows or full outer GUI/report acceptance. Native candidate results
remain pending.

The local report-only rehearsal exposed a genuine report bug: explicit detector
`none` was indexed as a software version. Reports now distinguish the exact
input-ligand site/prediction-not-requested case from P2Rank/fpocket, and preserve
the historical default only for genuinely missing legacy records. Regression
checks also cover an unfamiliar detector without substituting fpocket. Reusing
the already completed scientific control produces its normal PDF; no redocking
was needed. The earlier failed local report record is preserved. The pending
native run at `dba4a7b` predates this correction and the separate positive gate;
it cannot validate the corrected build. Failure metadata remains restricted to
exception types and code locations, never scientific log text.
