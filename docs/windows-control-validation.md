# Native Windows reviewed-control port — enabled-default acceptance passed

Final enabled-default build: `73054b9`, pushed only to the existing `github`
feature branch. Native run
[39512043939](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39512043939)
and general run
[39512043826](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39512043826)
both passed: two native jobs and all eight general jobs. This build includes
the report-origin and detector-version fixes. Final activation is verified
without the candidate's fixture-only override. The installed job took about
27 minutes including installation and all workflow/control checks; this is not
an installation-only timing or a performance promise for other machines.

The final status verifies `installed_control_workflow=passed_enabled_defaults`,
`production_control_enabled=true`, `candidate_configuration_only=false`,
`capability_override_used=false` and `installation_configuration_unchanged=true`.
All four controls pass, with zero failure dialogs and released host lease.
Both quick cases withhold approval; both five-seed cases produce ordinary PDFs
and verified portable approved bundles. Every case preserves reviewed inputs
and explicit site review. The 16 outer checks, 20 viewer checks, five installed
CLI stages and both 11-step exploratory GUI workflows pass as well.

Only the named status metadata artifact was retrieved, under
`validation/runs/windows-support-20261020/73054b9/installed/`; scientific outputs
and logs remain on the original runner. This accepts the bounded native
Server 2022/x64 CPU/control profile for fresh installations, not a full Windows
release or prospective accuracy/GPU claim. The user's Windows 11 Home/Intel
machine is the next real consumer-machine check; it is not yet validated.

The exploratory Vina/QuickVina-W GUI, private renderer and interactive software
viewer passed at `50a8ef2`; see [the completed gate](windows-viewer-engine-validation.md).
That success does not validate the separate known-ligand control path.

Accepted candidate: `ba85d2f`, with the retained-detector-version correction and
the report-origin changes included. Native run
[39479026877](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39479026877)
and general run
[39479026589](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39479026589)
both passed. All eight general jobs pass. All four native cases pass, with no
failure dialogs, released host lease and the fixture configuration restored.
The installed science/viewer and both exploratory engine GUI paths pass too.
Both earlier failed native runs below remain failed records.

Fresh full installers now enable only this accepted strict reviewed-control
capability. The final enabled-default rerun passed: its driver refuses
a disabled installation, never overrides or writes the installation
configuration, and requires it to remain byte-identical through cleanup.
The baseline host probe now checks an actually unsupported GPU-engine request,
not the previously unaccepted control method; the Qt gate checks that the control
option agrees with the installation's advertised capability. Both retain
fail-before-state-mutation checks, including incomplete control requests.
Chemistry interventions and GPU support remain separately gated. Historical
candidate notes below describe the earlier disabled/fixture-override stage.

The completed bounded port removes Bash orchestration only. It reuses the existing
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

During candidate acceptance, `native_control_supported` stayed **false** in
normal installations; the disposable fixture enabled and restored it only for
its independent gate. The final driver instead requires normally enabled
defaults, with no override. Both exercise actual
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

At the detector-version candidate checkpoint, 732 Python cases/21 shell checks passed, including the
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
remain intact. These semantics have dedicated regressions. At the historical
`f8ef36a` checkpoint, the corrected native four-case gate had not passed and
normal installations still disabled controls. That build's native run
[39473514519](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39473514519)
and companion general run
[39473514518](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39473514518)
record the next attempt, not the earlier failed run. The companion general run
completed successfully with all eight jobs passing. The native dependency/source
job passed, but the installed gate failed: Vina's ligand-only quick control now
passes including its PDF; QuickVina-W's quick control with P2Rank reaches the
ordinary-PDF check but has no PDF. Neither five-seed case was reached. The normal
disabled capability was restored. This is partial progress, not acceptance.
Its status-only files are retained under
`validation/runs/windows-support-20261020/f8ef36a/installed/`.

The no-prediction wording also follows the actual selected region(s): another
structure's aligned ligand and mixed input/evidence selections are not labeled
as though every box came from the exact input ligand. The original preparation
mode alone is insufficient to make that claim. These additional report-only
regressions pass locally; they do not change docking inputs or acceptance rules.

## P2Rank version handoff correction

The failed native metadata identifies missing PDF retention, not its underlying
generator message. The matching control metadata condition is reproducible
locally: P2Rank 2.5.1 is correctly retained as
`pocket_detection.engine_version`, but the report used only the separate control
software inventory. That inventory does not rerun/list the earlier detector.
The report consequently labeled the used P2Rank version `not recorded` and
correctly refused incomplete provenance. Do not weaken that guard.

The report now takes the version from the actual retained detector operation,
then falls back to retained software inventories only when needed. It never
queries today's installed detector or substitutes a guessed version. A genuine
missing version still fails. Dedicated regressions cover the control handoff,
the operation-versus-inventory priority, and the missing-version rejection.

A local report-only check additionally ran actual P2Rank prediction on the
unchanged public biotin fixture receptor and reused the completed five-seed
Vina control. With the fix, its PDF includes the retained 2.5.1 version. This
post hoc predictor run is explicitly marked as a report-compatibility fixture,
not evidence that prediction was used to select the original control site. No
control search or preparation was repeated, and no user result was changed.

Future native failures can also retain a fixed provenance-error code and an
allowlisted missing-software name from that specific error. No scientific log
message, target identifier or structural value is exported. This makes a later
native failure diagnosable without retrieving private scientific logs. The
corrected build required its own complete four-case native gate; controls
remained disabled in normal installations until the candidate pass below.

The corrected detector-version build passes the complete local 732-case/21-shell
suite and all 64 focused report/control checks. The 697-file protection audit
still matches 696 files with only the previously recorded stale ReportLab conda
metadata exception. No working installation or completed user study changed.

## Candidate acceptance result — ba85d2f

The native four-case status is `passed`: Vina quick (no P2Rank), QuickVina-W
quick (P2Rank requested), Vina repeatability and QuickVina-W repeatability all
finish normally. Both quick cases correctly retain no approved bundle; both
five-seed cases pass the real sampling/ranking/seed rules, publish an approved
bundle and verify its portable receptor/PDB/site hashes. Every case retains its
ordinary PDF and unchanged reviewed assets. There are zero failure dialogs,
the host lease is released, and the fixture-only configuration is restored.

The native run passes both jobs; the companion general run passes all eight.
Only status metadata was retrieved into
`validation/runs/windows-support-20261020/ba85d2f/installed/`. Scientific results
and logs remain runner-local. This is native Server 2022/x64 workflow evidence,
not prospective docking accuracy, a consumer Windows VM or GPU acceptance.
The bounded fresh-install capability activation followed this independent pass;
its separate normal-default acceptance subsequently passed at `73054b9`, above.

## Enabled-default build checks

The bounded activation and no-override acceptance changes pass 735 Python cases,
21 shell checks and 110 targeted Qt cases locally; all 29 focused native
control/desktop/bootstrap/scientific cases pass too. Validators compile and
the diff has no whitespace errors. The protection audit still matches 696 of
697 entries, with only the previously recorded stale ReportLab conda metadata
exception. No user study or working Mac installation is changed.
