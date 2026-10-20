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

Local evidence so far: 728 Python cases/21 shell checks pass, including the
report-synchronization regressions now in the normal test target;
extended scientific-host discovery also passes 885 cases (111 expected runtime
skips), and separate GUI regressions pass 185 cases. The initial unsplit
discovery attempt lacked Qt and the shell test environment; a second explicit
module invocation also lacked the tests' sibling-import path. Those diagnostics
are preserved locally; the correctly separated runs above do not hide these
environment requirements. No dependency or Xcode license was changed.
Real isolated Mac preparations of public 2R5P and 1STP mmCIF inputs
complete Reduce2, strict Meeko and the component audit without running P2Rank.
The new stage also completes the unchanged quick biotin control locally,
including independent conformers, two seeds, comparisons and reference/pose
visuals. It correctly withholds approval under the five-seed rule. This is not
native Windows or full outer GUI/report acceptance.

The first native candidate at `dba4a7b` (run
[39470496663](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39470496663))
passed the existing installed science/viewer and both exploratory CPU-engine
GUI paths, but failed the first control's ordinary-PDF retention check after
redocking. It restored the disabled production control capability. The native
metadata does not include the PDF traceback; the local matching ligand-only
report independently reproduced the no-detector error below. The companion
[general run 39470496717](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39470496717)
passes all eight jobs. Preserve this partial native run as failed, not accepted.
Status-only records are under
`validation/runs/windows-support-20261020/dba4a7b/installed/`.

The local report-only rehearsal exposed a genuine report bug: explicit detector
`none` was indexed as a software version. Reports now distinguish the exact
input-ligand site/prediction-not-requested case from P2Rank/fpocket, and preserve
the historical default only for genuinely missing legacy records. Regression
checks also cover an unfamiliar detector without substituting fpocket. Reusing
the already completed scientific control produces its normal PDF; no redocking
was needed. The earlier failed local report record is preserved. The failed
native run at `dba4a7b` predates this correction and the separate positive gate;
it cannot validate the corrected build. Failure metadata remains restricted to
exception types and code locations, never scientific log text.

A separate actual local five-seed repeatability control also passes sampling,
ranking and seed requirements, produces the ordinary PDF and an approved
portable bundle, and verifies its receptor/PDB/site hashes after extraction.
The first network-restricted attempt stopped before conformer generation at
the required public CCD identity lookup; its failed output is preserved. The
fresh successful run used the same strict helper with that coordinate-free
lookup permitted, not inferred chemistry or forced approval. Only disposable
public-fixture outputs were created. This remains Mac evidence for the shared
stage, not a substitute for native Windows acceptance.

Report correctness checks now also prevent a ligand-only site from acquiring a
fictitious `none score`/fpocket descriptor or a ligand-free-cavity heading.
Retained passed/unapproved controls are described as performed site-specific
controls, not as though no control was run. Related-site scope restrictions
remain intact. These semantics have dedicated regressions; the corrected native
four-case gate remains pending and normal installations still disable controls.
The corrected feature-branch build is `f8ef36a`; native run
[39473514519](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39473514519)
and companion general run
[39473514518](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39473514518)
are the relevant gates, not the earlier failed run. The companion general run
has completed successfully with all eight jobs passing; the installed native
gate is still active. Its dependency/source-workflow job has already passed.

The no-prediction wording also follows the actual selected region(s): another
structure's aligned ligand and mixed input/evidence selections are not labeled
as though every box came from the exact input ligand. The original preparation
mode alone is insufficient to make that claim. These additional report-only
regressions pass locally; they do not change docking inputs or acceptance rules.
