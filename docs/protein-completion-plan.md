# Plan for more than 90% protein workflow completion

Goal agreed 2026-10-24: at least 90% of a representative, predeclared protein
panel should complete the application workflow. Pose correctness and affinity
accuracy are separate measurements. This target is not yet achieved.

Latest execution direction (2026-10-26): the user reiterated that the goal is
100 docks. Resume the remaining authorized frozen cohort now; the broader
planning hold is lifted for unaffected unstarted cases. Collect safely stopped
failures and continue unaffected cases without waiting for report cosmetics or
repairing every individual input first. Exact molecular approvals and process
safety remain required. The queue contains 88 unstarted outcomes: 82 executable
full-workflow cases and six explicit reference holds, alongside ten completed
distinct targets and two retained unsupported pilot inputs. Blocked or failed
cases are outcomes, never completed docks; preserve the denominator and actual
completion/search counts. No single-candidate >90% claim follows from this
development continuation.

Clarified 2026-10-25: use **strictly more than 90%**, requiring at least 91/100
primaries. The [new prospective panel](protein-panel-100-20261025.md) is frozen;
its ten-case baseline pilot completed three full workflows and stopped seven
before docking. Metadata/read-only eligibility checks are not completed docks.

## First remove common preparation blockers

The original 100 scenarios exposed a small number of repeated upstream
boundaries, rather than 40 independently measured engine failures. The early
panel is useful for repair work but too small and repeated to estimate protein
coverage. Keep its historical outcomes unchanged.

| Work | Existing evidence | Next acceptance gate |
| --- | --- | --- |
| Input, site and interaction handoffs | The nine-atom BEN handoff and exact PLIP component selection were corrected; two separate BEN retests completed | Keep those regressions passing in the candidate build; exercise the full source site-first path |
| Alternate conformations | Native 4EY7 review with six approved deposited locations and seven sugar exclusions completed strict preparation and a new Vina workflow | Keep exact previews, original inputs and permanent warnings; do not generalize these choices to another receptor |
| Incomplete amino acids | 1UY6's old fallback constructed LYS A224 backbone; 3ERT has a partly absent PRO around the padding failure | Diagnose missing backbone versus side-chain atoms before modeling. Permit only the separately reviewed supported change; retain 1UY6 on hold and stop unsupported backbone construction |
| Linked sugars and other retained components | Exact reviewed exclusions completed full native 1A4G and 4EY7 workflows in the private development build | Component-preserving parameterization remains separate work requiring verified templates/linkages; preserve original structures and explicit exclusion warnings |
| Extensive incomplete models | 1FM6's attempted 193-atom reconstruction failed geometry/valence checks | Keep it failed under the user's latest direction. A manually edited input is a new, permanently flagged retest; no automatic gap filling or mass deletion |
| Outputs and reopening | Some original searches completed while interaction views/report presentation remained incomplete | Verify retained products, warnings and fresh-host reopening; keep functional, presentation and accuracy gates separate |

The immediate product increment is **site review followed by a complete, explicit
preparation decision and retained model history**. Its primitives are already in
development source. Native exact exclusion/alternate-location adoption and three
new CPU vertical workflows passed; external manual-input declaration and general
repair-builder acceptance remain unfinished. See the [current review evidence](preparation-review-20261025.md).
No preparation alternative counts merely because
Meeko exits successfully. The same derivative must complete docking and output
generation with its warnings intact. These steps do not authorize new chemistry
choices on the retained failed cases.

The exact beta2 side-chain candidate now passes real GUI review/adoption,
strict preparation and the full downstream native workflow, retaining all four
approved exclusions and three modeled atoms. Its generation was an isolated
external local trial: the bounded candidate-import handoff is accepted, while
an integrated user-facing repair builder remains unfinished. Eight pilot targets
have completed functionally across development builds, with thirteen actual
searches; this is not a single-candidate application-supported rate. Presentation
still fails independently. See the [latest prospective checkpoint](protein-panel-100-20261025.md).

The approved DOT1L continuation completed one new full native Vina workflow.
It retains all 108 modeled-atom flags (104 retained, four regenerated) and
exactly six explicitly reviewed connectivity overrides. Strict parameterization
passed with every atom/coordinate retained by the connectivity adapter; the
close contacts remain and geometry is unvalidated. All saved coordinate-stage
files, protected outputs and the 395-file installed application matched their
hashes after cleanup. Its presentation gate failed independently for small
report labels and inconsistent 2D styles. Two pilot inputs and eight reference
holds remain unsupported/unresolved, so the unchanged panel's optimistic ceiling
is 90/100; the larger run remains held pending review.

Subsequent exact user review allowed two incomplete deposited ligand references
to define exploratory sites without filling atoms or changing the frozen
screening molecules/boxes. Both GSTP1/6Y1E and lipase/1LPA completed new full native
workflows, with permanent reference warnings and verified cleanup/hashes. Current
development totals are **ten distinct cohort targets and fifteen searches across
builds** (eight pilot, two nonpilot). These do not establish one candidate's
application-supported rate. Six reference holds and two unsupported pilot inputs
remain, giving an optimistic 92/100 ceiling if all other cases complete; that is
not achieved coverage. All retained visual pages were reviewed and both new
presentation gates failed independently. The remaining panel is held while the
common-blocker and consistent-candidate execution plan is reviewed. See the
[terminal reference checkpoint](protein-panel-100-20261025.md#reference-holds-read-only-review-after-dot1l).

## Then freeze a representative protein panel

Use the existing small cohort to develop fixes. Before making a broad completion
claim, curate a new acceptance panel of **at least 100 distinct protein targets**,
with one predeclared primary raw-input workflow per protein and supplemental
cases for other structures, engines, sites and formats. Assign biological target
identities explicitly; different PDB entries for one target do not become
independent proteins by changing their names.

Choose across protein families, structure size, oligomeric state, PDB/mmCIF,
bound versus ligand-free starts, alternate conformations, incomplete residues,
modified residues, glycans, metals/cofactors and ligand sizes/flexibility.
Include challenging inputs deliberately and retain their outcomes. Record
overlapping characteristics rather than inventing balanced percentages after
seeing results. Selection should reflect intended users and include a reserved
subset not used to tune preparation fixes. The known difficult cases remain
regression challenges even when they are outside a new independent panel.

Pin the selected source files, exact reference instance or reviewed boxes,
candidate runtime, engine and settings before execution. Run sequentially and
retain every attempt. Freeze a baseline CPU profile first; report QuickVina-W,
AD4/GPU and other operating systems separately. A completion on one engine must
not imply every engine can process that target.

At the preparation screen, users should be able to inspect site proposals even
when parameterization is unresolved. Changes are explicit, original files stay
intact, and a passing derivative retains its warning through protocol, screening
and reports. Unsupported or ambiguous chemistry remains a recorded outcome.
If too many intended-use inputs remain unsupported, revise the stated scope or
the target transparently, preserving both the old panel and old score. Do not
drop difficult cases to manufacture 90%.

## Measure actual completion without inflating it

The read-only `protein-coverage` command checks local supervisor inventories,
raw-preparation/docking receipts and retained poses, clusters, interaction XML,
2D diagrams and PDF products. It never launches a calculation or adopts a model.
Exactly one primary case counts for each declared protein; supplemental success
is reported without replacing a failed primary. Unrun and blocked primary cases
stay in the denominator. The runtime/platform fingerprint must match for a
prospective completion claim.

Report four preparation classes: routine, explicit reviewed changes, external
manual edits, and unclassified. The application-supported rate includes only
the first two, with an explicit classification review bound to the prepared
receptor hash. An unknown historical route is never silently classified as an
unchanged deposition. Manual rescues are disclosed separately. Visual review
and pose-recovery metrics are also separate; a functional target does not imply
publication-ready figures or an accurate pose.

Example local command, after curating a panel (this example launches no docking):

```bash
python validation/validate.py protein-coverage \
  --panel validation/local/my-protein-panel.json \
  --out validation/runs/my-protein-panel-coverage.json
```

Panel schema is `docking-universal-protein-coverage-v1`. `selection` is
`predeclared` or `retrospective`, accompanied by a `selection_note`. Each
`targets` entry has `id`, `label`, `family` and `cases`; each case has `case_id`,
`structure`, `engine`, `primary` and an optional absolute local `run` directory.
An omitted run remains unrun. `completion_route` defaults to `unclassified`.
For `routine` or `reviewed_changes`, `route_review` must identify `actor`,
`rationale` and the exact `prepared_receptor_sha256`. These are explicit operator
annotations, not automatically inferred model-change approvals. Missing raw
receipts cannot be replaced by a protocol-reuse screen.

Exit 0 means the narrowly defined completion target is established; exit 3 means
it is not established, including a small or retrospective panel. Exit 2 rejects
invalid or changed evidence. Results are local and existing files are never
overwritten. No accuracy claim, preparation permission, installation or release
approval follows from this command.

Current status: the [100-target prospective panel](protein-panel-100-20261025.md)
is frozen and its first ten native CPU workflows are terminal (three functional
passes, seven preparation failures). The other ninety remain held while common
blockers are assessed. Confirmed mmCIF format defects and incomplete box-warning
diagnostics were corrected in development source after pilot cleanup. Targeted
PDE5A/HDAC1 retests run separately in a new isolated version; original failures
and single-candidate accounting remain intact. The corrected full regression
passed 862 Python case executions and 21 shell checks, with separate native-reader
and Qt checks. These are not additional protein completions.
Ninety-two reference inputs passed read-only eligibility; eight unresolved
reference cases remain blocked and in the denominator. No staging/preflight
result counts as a completed dock. Source-only site-first/model-history work
remains uninstalled. The working Mac installation and historical studies stay
unchanged. Current evidence is tracked in the
[four-area checkpoint](four-area-completion-20261023.md).
