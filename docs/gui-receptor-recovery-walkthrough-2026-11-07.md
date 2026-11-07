# Receptor recovery: actual GUI walkthrough, 2026-11-07

**Status: partial interactive acceptance; native pocket-table interaction is
blocked by a Qt accessibility crash.** Backend/service tests are not substituted
for this result. The reviewed omission, preview, cancellation and GUI approval
were exercised interactively; the box warning was subsequently verified in
saved-state projection and a reopened offscreen GUI render.

## Isolation and runtime

- Public native 1N6O mmCIF copied from the preceding real-structure campaign.
- Dedicated state/output/preferences under `validation/runs/gui-removal-20261107`.
  A temporary `.app` wrapper gives the existing installed GUI a native identity
  for computer-use testing; it is not a new application distribution.
- Installed preparation code from `74fa5dd`; installed GUI updated with the
  failed-progress-page recovery action described below.
- Initial native GUI: Python 3.12, PyQt6 6.11.0, Qt 6.11.2, embedded PyMOL.
  Scientific host: existing Python 3.9 environment and real installed tools.
- Original Cox-2 study and original 5IKR source hashes pinned in `baseline.json`;
  unchanged throughout. Neither COH cofactor was removed from the actual study.
- No production GUI/scientific dependency version changed. The runtime trial
  used a separate venv under the validation directory.

## Interactive steps actually performed

1. Open the installed GUI with the isolated study and preferences.
2. Enter the copied 1N6O source and a new output directory through visible fields.
3. Apply GNP A:200 through **Use as bound reference ligand**, enable the quick
   pose-recovery pathway and additional P2Rank prediction, and disable related-
   PDB lookup for this local-only test.
4. Start preparation from the GUI. Real Reduce2/Meeko/PDBFixer/ADFR stages run.
   The initial attempt fails on the reported Mg charge parameter.
5. Observe that the failed progress page offers logs/files but no recovery action.
   The existing action is on setup. Add that same action to the progress page,
   with identical host capability, active-job, pending-decision and accepted-
   output eligibility gates. Reopen the installed GUI and click the new action.
6. Confirm the recovery dialog has no default component exclusion, discloses
   the previously attempted alternative method and missing charge assignments,
   and says box warnings will be retained when boxes become available.
7. Enter `MG A 201` and preview. Visible result: exactly one atom record excluded,
   no modeled atoms, retained coordinates unchanged, alternative preparation,
   and persistent warnings promised. The preparation button remains disabled.
8. Cancel. Saved revision stays 8, job count stays one, and no reviewed model
   or scientific attempt is created.
9. Reopen the dialog, repeat the exact preview, enter an explicit validation-only
   rationale and acknowledge the warning. Only then does approval become enabled.
10. Click **Use reviewed model and prepare**. A new isolated, strict ADFR attempt
    completes. State revision 19 retains both attempts, the reviewed-model
    approval/history, and a pending pocket decision. No control/docking starts.
11. The GUI closes during transition to selected pocket-table review. Native
    crash evidence is described below. Do not count native review/reopening,
    finalization or export as passed interactive steps.

## Retained warning checks and render

Both generated proposals, P1 and B1, retain the approved Mg omission as:

```text
User-approved receptor changes: Excluded only these reviewed residues/components:
MG A:201. Reviewed receptor changes affect residues inside this box: MG A:201.
```

For both, the recorded minimum distance to the entire box is 0 Å, `inside_box`
is true, severity is high, and `persistent_warning_required` is true. The
projection reads the pinned original coordinates; deleting the atom from the
derivative does not erase its location. `distance_is_permission_to_ignore`
remains false.

Reopening the same saved study through the ordinary desktop screenshot entry
point with an offscreen platform renders that warning in the actual evidence
panel. Local image: `validation/runs/gui-removal-20261107/retained-review.png`.
This verifies retained-state presentation, not native mouse/keyboard stability.
Outside-box warning behavior remains covered by the existing automated tests;
both actual generated boxes in this fixture contain the omitted atom.

## Native accessibility blocker

The native crash report resolves the leading frame to
`-[QMacAccessibilityElement accessibilitySelectedChildren]`, followed by macOS
accessibility hierarchy-copy calls. This matches the signature described in
[Qt's selected-table accessibility issue QTBUG-149612](https://qt-project.atlassian.net/browse/QTBUG-149612).
The exact upstream ownership mechanism was not independently patched/A-B tested
in this application, so the matching signature is evidence, not proof of every
detail of that report's root cause.

An isolated official PyPI PyQt6 6.10.2 / Qt runtime 6.10.2 trial also terminated
during accessibility inspection of the saved review. It did not resolve native
acceptance and was not installed into the production environment. At the time
of checking, the queried PyQt6-Qt6 wheels did not include the issue's listed
6.12.1 or 6.8.10 fix versions. No accessibility/security permission was disabled
to hide the failure. The offscreen GUI remains renderable.

## Additional correctness issue caught by this case

The generic linked-component retention policy initially left all 32 GNP reference
atoms in this fixture's scored receptor. Parameterization success therefore
could not authorize a pose-recovery control against that receptor. No control
was run.

Add an exact-reference guard before control launch and again at the sealed
native control boundary. It rejects the selected reference's own identity in
the scored PDBQT even when all file hashes match, while allowing another exact
instance. It preserves the original full input/reference and removes nothing.
The real initially retained 1N6O output is rejected by this guard.

Repair the shared receptor filter to withhold only the exact selected reference
instance, even when it coordinates a retained standalone metal. Preserve the
full original complex/reference for extraction and evidence, other instances,
and the receptor's other retained components. Reject a selected reference linked
to protein or a multi-atom component for explicit covalent-reference review;
this repair does not authorize covalent cleavage. Apply the same rule to POSIX,
native and reviewed-model preparation, and retain its identity/count audit.

A fresh API integration retry reproducing the GUI's exact reviewed Mg omission
now completes: GNP A:200 is absent from the scored receptor, its 32 original
atoms remain in the retained source, BME's four heavy atoms remain, and ADFR's
strict audit accepts all 1,343 receptor heavy atoms at unchanged coordinates.
P2Rank completes and both proposals still carry the Mg warning. The control
reference-absence guard passes. This is a service/API rerun, not a second
interactive GUI approval or a completed redocking control.

Two further real preparation/job-service checks exercise normal exact-reference
selection. 1HVR withholds all 46 XK2 reference atoms and completes through strict
Meeko while preserving both CSO residues. Its 1,514 exported heavy atoms retain
the input positions, but Meeko exchanges terminal O/OXT labels in two residues:
the retained strict identity audit rejects those four label/coordinate matches.
The separate permutation record does not prove chemical equivalence. Unmodified
1N6O withholds GNP but retains Mg and BME, then safely fails on the reported Mg
Gasteiger-parameter gap; no prepared receptor is registered. A neutral inventory
check alone passes that diagnostic file, illustrating why the actual backend
log/charge audit remains mandatory. Neither check modifies the original source.

## Site-evidence/duplicate follow-up requested by the user

- B1 is the exact input-bound GNP A:200 site, not a predicted pocket. Its absent
  P2Rank score is expected. Its input-ligand provenance should be visible.
- P1 contains all 32 heavy atoms of the same experimental input ligand. Both
  proposals contain the whole ligand, despite zero independent related-PDB
  observations in this local-only run.
- The green ring currently reads only the external-observation summary, so it
  misses the input-ligand association. Record this as an evidence/presentation
  defect, without relabeling same-input observations as independent validation.
- The two 26 Å boxes have centers 0.543 Å apart, share 97.12% of each volume,
  and have 94.41% intersection-over-union. Counting them as distinct site options
  is the concrete duplicate case to consolidate, preserving both sources.
- The user moves these fixes and optional experimental-ligand similarity/
  template guidance ahead of charge surfaces, after the pipeline issues. See
  the updated backlog and workflow plan. No deduplication/template calculation
  was implemented as part of this walkthrough.

## Verification and evidence

- 43 targeted GUI tests passed, including approval/cancel behavior through the
  progress-page action and gates for running, pending, completed and unsupported
  hosts.
- 46 control/recovery/box-projection tests passed, including preventing an exact
  reference from being redocked against itself and rechecking the native boundary.
- 68 targeted reference-filter, reviewed-model, recovery, native-preparation,
  control and preparation-service tests passed; the POSIX route suite also passed.
  These test groups overlap and are not a combined unique-test count.
- The eight changed production files are backed up under
  `local-fix-backups/gui-progress-recovery-20261107` and installed-file hashes
  match source. No speculative Qt runtime update was installed.
- Local evidence includes `baseline.json`, the persisted study/approval/history,
  `box-warning-audit.json`, `control-reference-audit.json`,
  `candidate-overlap-and-input-ligand.json`, native GUI logs and the reopened
  offscreen rendering. The corrected retry is recorded in
  `reference-separated-rerun-3/receipt.json`, with the two ordinary service
  checks in `reference-role-panel`. Raw public structures, generated runs and dependencies
  remain ignored by Git.

Remaining acceptance is explicit: native selected-table stability and a
subsequent complete GUI control/
finalization/export walkthrough. The protected original 5IKR glycan charge
problem remains unresolved by this separate fixture.
