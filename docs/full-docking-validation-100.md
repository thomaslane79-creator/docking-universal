# 100 actual docking workflows: curated coverage

This is a separate cohort from the earlier 100 mixed GUI/pipeline checks. Those
checks do **not** count as 100 docking workflows. A new completed case must
perform new molecular docking and retain clustering, PLIP/2D, reports, native
linked 3D review and a fresh-host reopen. Visual acceptance is recorded
separately. Failed, blocked, excluded, input-only and component checks are not
completed docks. Report the actual number of engine searches separately from
the workflow count.

## Deliberate selection, not random sampling

The first 20 cases use the already reviewed 2R8N site with ten new public ligand
graphs and Vina/QuickVina-W. They exercise protocol import, five ligand input
formats, explicit table-column approval, subset selection and pagination.
They are not twenty raw receptor preparations or native-target recovery tests.

The remaining 80 cases start from raw structures. Their primary matrix is ten
protein/chemistry groups crossed with eight predefined workflow configurations.
This intentionally replaces the earlier unbound, protease-heavy draft slots.

| Group | Public reference | Distinct coverage |
| --- | --- | --- |
| ABL kinase | 1IEP / STI | Large flexible inhibitor; repeated ligand instances |
| HSP90 | 1YET / GDM; 1UY6 / PU3 | Macrocyclic CPU route versus a separately deposited nonmacrocyclic GPU-compatible inhibitor |
| Streptavidin | 1STP / BTN | Small stereochemical ligand; assembly interpretation |
| Trypsin | 3PTB / BEN | Small basic ligand and retained structural calcium |
| Estrogen receptor alpha | 3ERT / OHT | Hydrophobic ligand, alkene stereochemistry and protein alternate conformations |
| Acetylcholinesterase | 4EY7 / E20 | Large binding gorge, repeated chains and linked glycan compatibility |
| PPAR gamma / RXR | 1FM6 / BRL | Heteromeric complex and different deposited ligand types |
| Gyrase B domain | 1KZN / CBN | Large, stereochemically complex antibiotic |
| BRD4 | 3MXF / JQ1 | Small recognition domain and stereospecific inhibitor |
| Influenza B neuraminidase | 1A4G / ZMR | Highly polar/ionizable ligand, repeated instances, glycan and calcium boundaries |

All are public experimental structures, not a claim of ten independent accuracy
benchmarks. Protein families, ligand flexibility/size, source formats, chemical
features and workflow branches are the selection criteria. These examples do
not establish universal accuracy, platform support or statistical coverage of
all chemical space.

## Paired structure formats

The remaining matrix contains **40 PDB and 40 mmCIF** workflow cases. Each group
has paired same-engine PDB/mmCIF scenarios before the additional discovery/lookup
scenarios. Before launching, compare deposited atom identities and coordinates
without fitting. Later compare prepared receptor inventories, coordinate frame,
reference-box geometry, protocol settings and warnings. Matching deposited
coordinates do not imply byte-identical prepared receptors or identical poses.

Ten cases use the ordinary GUI's fresh public download path. Twenty request
P2Rank and independent related-structure evidence while retaining the exact
input-ligand reference site. The remaining cases exercise local raw PDB/mmCIF
and explicitly disabled optional lookup/prediction. Across the cohort, ligand
inputs include SDF, MOL, CSV, TSV and XLSX. Table headers are suggestions only;
the configured columns and record subset must be approved through the GUI.

Repeated ligand instances are selected by exact component, author chain,
residue and insertion code. No merged centroid, post hoc best-RMSD instance,
automatic assembly construction or silent alternate-conformation choice is
allowed. This panel does not yet claim multi-site screening, restart recovery
or strict control-calibration coverage merely from repeated-instance cases.

## Engines and scientific boundaries

The staged remainder uses 32 Vina, 32 QuickVina-W and 16 experimental Apple AD4
cases. Metal-containing targets remain CPU cases because the accepted AD4
profile excludes those retained atom types. Metals are not removed to obtain a
pass. Native GDM is not forced into AD4; its HSP90 AD4 pair uses the independent
1UY6/PU3 structure and its own exact reference site.

The staged protocols use one retained starting shape and one seed per case for
bounded functional testing, with the explicitly recorded search settings. This
is not production control sampling, an engine-equivalence study or a speed
benchmark. Workflow and actual engine-search counts can differ if preparation
generates more chemical states; retain and explain that difference.

The user explicitly approved deposited-ligand reference sites for exploratory
validation. This does not grant control-validated production authority. Stop an
affected case for ambiguous chemistry, missing templates, unexpected approvals,
unsupported components or an unexplained reference-box discrepancy. Do not
delete glycans/cofactors, invent charge/stereochemistry, relax thresholds or
silently fall back to another engine. Retain the failure and inspect it before
any bounded correction or replacement case.

The alternate-ligand 4J3I example, AD4 macrocycle rejection and AD4 retained-metal
rejection are additional boundary evidence, not successful full docks. They
must not be used to inflate the requested count.

## Execution and local checkpoint

Only one scientific worker runs at a time. Preparing public inputs, parser
preflight and case definitions may proceed while the first batch runs; its
suite, worker code, installation, settings and original studies remain unchanged.
The new adapter is staged under the ignored local cohort directory, outside the
active source fingerprint. A full raw-input vertical case must pass before the
remaining queue can be called runtime-ready.

Local records are under `validation/local/full-docks-100-20261022/`:

- `phase-a-20-reviewed.json`: unchanged launched first phase.
- `curated-inventory.json`: downloaded public input identities and inventories.
- `curated80/format-pairs.json`: read-only deposited PDB/mmCIF comparisons.
- `curated80/suite.json`: the actual revised 80 case definitions.
- `curated80/coverage.json`: allocation and explicitly excluded boundaries.
- `curated80/preflight.json`: installed-parser checks, **not docking results**.
- `cohort-ledger.json`: links first-phase and remainder case IDs without counting
  the old mixed-check suite or the superseded unbound draft.

First-phase execution is `validation/runs/full-docks-100-phase-a-20261023`.
The remaining 80 have not been launched at this checkpoint. All 80 passed
read-only checks of pinned inputs, exact installed-parser ligand identities,
explicit library selection and selected graph/stereochemistry. Five new adapter
authority/geometry guards passed. No raw preparation or docking is implied by
those preflight results. Native raw-adapter execution, downstream outputs,
cleanup and visual review remain required.

All downloaded coordinate files, selected graphs, poses, numerical structural
evidence, PLIP outputs, figures, reports and detailed logs remain local and are
ignored by Git. No result is submitted to an external renderer or service.

## Execution finding, 2026-10-23

The first 20 workflows completed their new docking, clustering, PLIP/2D, PDF,
native linked review and reopening without a calculation failure. All retained
case inventories and protected original study files were verified. The audit
checked 20 portrait reports, inspected all 20 native screenshots and six full
rendered reports. The other 14 complete-report visual gates remain pending;
functional completion is not full visual acceptance. Local evidence is
`validation/runs/full-docks-100-phase-a-20261023-review/`.

The first raw-input case exposed two distinct issues, neither an engine-search
failure. Its receptor preparation completed once; no docking was launched.

1. The new validation adapter incorrectly waited for `active_job` to disappear
   before site review, although the application's review job is intentionally
   `waiting_for_decision`. The adapter now accepts the exact site-review
   decision with no queued/running computation. Seven authority/geometry/wait
   guards and all 80 read-only case preflights pass. The failed driver record
   is retained, and continuation reused the exact saved preparation without
   repeating it.
2. The installed Mac ligand-only path, with optional P2Rank unchecked, still
   invokes the legacy ligand-local fpocket route. Its box matches the intended
   deposited ligand's geometry, but site review labels it as fpocket and omits
   the explicit input-bound-ligand identity/provenance. The corrected adapter
   therefore refused approval before finalization or docking. Do not weaken
   that check, pretend the reference site was verified, or change the requested
   workflow to hide the missing provenance.

The original raw attempt and no-repreparation continuation remain separate:
`validation/runs/full-docks-100-curated80-20261023/` and
`validation/runs/full-docks-100-curated80-20261023-v2/`. The current corrected
adapter suite is `curated80/suite-v2.json`; the old `suite.json` pins the earlier
adapter and must not be relaunched. The saved raw study is still awaiting its
site decision; no preparation, docking or user-study data was discarded.

The raw queue initially stopped pending direction about a bounded application
fix. The user subsequently authorized **an isolated test-build correction**;
the installed Mac application and production source remain unchanged. Historical
failed runs are retained. This is a real workflow/provenance defect found by
the broader panel, not evidence that 100 full docks passed.

## Authorized isolated correction and vertical pilot

The private installed-code copy is
`validation/local/full-docks-100-20261022/isolated-reference-site-v1/`.
Six private application files were corrected: ligand-only preparation skips
unrequested pocket detectors; site review retains the exact input-ligand
identity as B1 rather than attributing it to fpocket; finalization carries that
same meaning into the protocol/report. Optional predicted pockets and independent
related-structure sites remain separate. A legacy unwanted fpocket run remains
recorded as history, not as independent support or the source of the B1 box.

An audited local refresh superseded only the **unapproved** old review and
created a new pending decision. No approval was inherited. Every old preparation
file remained unchanged, and neither download nor receptor preparation was
repeated. The box check uses the existing writer's three-decimal Angstrom
serialization of the predefined ligand centroid; no box policy, chemistry,
sampling or approval threshold was changed.

Thirty-five focused synthetic/regression cases pass (not counted as docks),
and all 392 non-cache installed application files match the pre-copy inventory.
Evidence is `isolated-reference-site-v1/validation.json` and
`curated80/isolated-review-refresh.json`. Read-only preflight passes for the
one-case pilot and 79 remaining cases, not runtime acceptance of those cases.

The one-case sequential vertical pilot is
`validation/runs/full-docks-100-curated80-20261023-v3-pilot/`, pinned by
`curated80/suite-v3-pilot.json`. It **completed one new workflow and one engine
search**, including exact B1 verification, GUI protocol/report finalization,
screening, clustering, PLIP/2D, native linked 3D review and fresh-host reopening.
Retained output hashes, cleanup and original protected files passed checks.
The total is now **21 functional workflows and 21 engine searches**, not 100.

All two protocol-report and five docking-report pages and the native screenshot
were inspected locally. The ligand-site/provenance correction passes; an existing
Asp381A sidechain-label overlap with the ligand ring in 2D panel C is recorded
as a separate **failed presentation gate**, not silently signed off. This does
not invalidate the completed calculation, but the pilot is not fully visually
accepted. No renderer modification or repeat docking was performed to hide it.
Evidence is `validation/runs/full-docks-100-curated80-20261023-v3-pilot-review/`.

After that functional pilot and output inspection, the remaining 79 were
launched once in the sequential supervisor at
`validation/runs/full-docks-100-curated79-20261023-v3/`, using
`curated80/suite-v3-remainder79.json`. They remain unaccepted until their actual
workflows finish and their presentation gates are reviewed. The first new case
also exercises a fresh mmCIF preparation with prediction unchecked, rather than
reusing the legacy preparation. Do not launch the old suite, repeat the pilot,
change active code/pins or count these queued cases as completed.

## Receptor-preparation boundary, 1UY6 (2026-10-23)

The private remainder run stopped at `full-033-1uy6-pdb-adgpu-5` before site
approval, protocol finalization or any AD4 search. Its retained raw preparation
receipt is failed; the sequential supervisor records interrupted/attention
required rather than a successful workflow. The original installed app and
scientific settings were not changed. All processes exited, the raw study has
no active job or pending decision, and the conservative unresolved-worker lock
was reconciled only after process inspection.

The initial strict Meeko attempt rejected GLU A75 and incomplete LYS A224 and
reported alternate coordinates at A26/A158/A185/A203. The existing enabled
PDBFixer attempt still failed template matching at A75. Read-only examination
of the deposited input confirms that A75 CD/OE1/OE2 have zero occupancy. This
is a receptor/coordinate-model compatibility boundary, **not an AD4 docking
failure**. The existing PDBFixer fallback had already selected alternate
locations and added eight missing heavy atoms; no additional intervention,
residue deletion, relaxed template matching or repeated preparation was applied
after the failure. The read-only audit is
`curated80/1uy6-receptor-readonly-review.json`.

At this stop, **32 workflows and 32 engine searches** are verified complete:
20 first-phase + one raw pilot + 11 private-remainder cases. Five prepared
PDB/mmCIF pairs were audited separately; visual gates remain separate. The
next 67 cases are not run, including the paired 1UY6/mmCIF case. They are not
passes, and the failed preparation does not count toward 100. Evidence is the
unchanged private remainder run, `curated80/completed-progress-audit.json` and
`cohort-ledger.json`.

The user initially held the queue for review, then explicitly directed:
"for now just skip it and we will look at all the error to address at the end".
The failed 1UY6/PDB case remains failed/interrupted in its historical run; its
unattempted mmCIF pair is deferred/blocked at the cohort level. Neither counts
toward 100. No chemistry repair, silent replacement or repeat of 1UY6 is allowed.

The unaffected 66 unstarted cases35-100 are pinned separately in
`curated80/suite-v4-remaining66.json`, with the same private runtime, driver,
inputs and scientific settings. Continue sequentially in the new run
`validation/runs/full-docks-100-remaining66-20261023-v4/`, preserving all32
completed workflows. `curated80/deferred-errors.json` records the failed/blocked
pair for end-of-run review. Additional safely stopped case failures should be
preserved for that review rather than repaired or blindly retried; before
continuing another versioned subset, verify worker/host cleanup and absence of
running scientific children. An unresolved cleanup, input/provenance corruption
or new authority boundary still requires a safety stop. Even if every remaining
case passes, the original cohort would have98 completed workflows, not100;
replacements or repair require a separately reviewed continuation.

## Deferred small-ligand handoff failure (3PTB/BEN)

The v4 subset completed ten new workflows (cases35-44), bringing the verified
total to42 workflows/42 searches. Case45 then stopped **after receptor PDBQT
preparation succeeded**, at the ligand-site handoff: the GUI detects the exact
BEN A1 instance, but the legacy shell resolver requires at least ten HETATM
records per component; this deposited BEN has nine. This is an application
eligibility mismatch, not a Vina search failure or failed Meeko preparation.
Reduce2 was not accepted in this case, and the retained pipeline used its
existing original-filtered-receptor fallback; no additional repair was applied.

Following the user's instruction to collect errors for end review, preserve
case45 as failed/interrupted and defer unattempted cases46-50, which use the
same exact BEN and failing ligand-only route. Do **not** defer cases51-52 on
this evidence: their requested P2Rank path uses pocket mode and may avoid that
particular resolver rejection. Neither a threshold change nor enabling P2Rank
on the failed cases was used to obtain a pass.

All failed worker/host/scientific processes exited, raw cleanup is idle and the
unresolved-worker marker was reconciled only after inspection. The remaining50
unstarted cases are pinned at `curated80/suite-v5-remaining50.json` and launched
once at `validation/runs/full-docks-100-remaining50-20261023-v5/`. No passed or
failed preparation/search was repeated. Eight cohort cases are now deferred
(two1UY6, six3PTB ligand-only); even if all remaining50 pass, that is92 completed
workflows, not100. Error receipts and blocked coverage are retained in
`curated80/deferred-errors.json`; no molecular or application fixes are applied
during this error-collection continuation.

## Deferred 3ERT receptor-template failure

The v5 subset completed cases51-52 through their originally requested P2Rank
route, including new docking and downstream review/reopening. This brings the
verified total to44 workflows/44 searches. Case53 (3ERT/PDB/Vina) then failed
strict receptor preparation: initial Meeko rejected multiple residue templates;
the existing PDBFixer retry ended in a Meeko padding RuntimeError involving
A550/A552. No site approval, finalization or docking occurred for case53.
Preserve the exact original diagnostics for end review rather than applying
model changes or a permissive template override.

Cases54-60 are unattempted/deferred because they use the same deposited receptor
and strict preparation route, before engine selection or optional prediction
could matter. They are blocked coverage, **not seven measured failures**. The
failed worker/host/scientific children exited and the raw cleanup was idle;
the conservative runner lock was reconciled after process inspection.

The remaining40 cases61-100 are pinned in `curated80/suite-v6-remaining40.json`
and launched once at `validation/runs/full-docks-100-remaining40-20261023-v6/`.
The private app/driver/settings remain unchanged; no passed or failed searches
were repeated. Current original-cohort accounting is44 completed,3 attempted
failures and13 unattempted blocked/deferred cases, with40 pending. Even if all40
pass, the cohort would have84 completed workflows rather than100. Review
`curated80/deferred-errors.json` for the distinct causes and exact receipts.

## Deferred 4EY7 linked-glycan preparation failure

Case61 stopped during whole-receptor preparation, before site approval or any
docking. Meeko rejected covalently linked NAG/FUC fragments; existing PDBFixer
and disulfide-template attempts did not resolve the problem. The existing
legacy ADFRsuite fallback additionally failed to start with `Bad CPU type in
executable`. Both causes are preserved; no glycan deletion, template invention,
new software installation or chemistry intervention was used to obtain a pass.

Cases62-68 are unattempted/deferred against this same whole-receptor boundary.
The alternative E20 B605 instance in cases63-64 changes the intended site, not
the glycosylated receptor preparation that fails first. These are blocked
coverage, not seven additional measured failures. Cleanup/process inspection
confirmed no live worker/host/scientific child; the conservative lock was then
reconciled. The v6 run remains failed/interrupted with39 unrun cases.

The unaffected32 cases69-100 were pinned in `curated80/suite-v7-remaining32.json`
and launched once at `validation/runs/full-docks-100-remaining32-20261023-v7/`.
Current original-cohort accounting is44 completed workflows/searches,4 attempted
failures,20 unattempted blocked/deferred cases and32 pending. At most76 original
cases could now complete without a separately reviewed repair/replacement
phase. All installed/private scientific code and sampling settings remain
unchanged; errors await the user's requested final roundup.

## Deferred 1FM6 multichain template/valence failure

Case69 failed whole-receptor preparation. Initial Meeko rejected templates
across several chains; the existing PDBFixer retry then raised an RDKit
AtomValenceException (carbon valence5). No site approval or engine search
occurred. Preserve both the initial residue inventory and retry traceback;
no chain removal, new templates or permissive chemistry override was applied.
Cases70-76 share that whole-receptor preparation boundary and remain
unattempted/deferred rather than being counted as measured engine failures.

After confirming idle cleanup and no scientific children, reconcile the
conservative worker marker and continue only cases77-100 in the new pinned
`curated80/suite-v8-remaining24.json` at
`validation/runs/full-docks-100-remaining24-20261023-v8/`. The v7 failed run is
preserved with31 not-run cases. Original-cohort accounting before v8 is44
completed workflows/searches,5 attempted failures,27 unattempted blocked cases
and24 pending. Even if all24 pass, that is68 completed workflows, not100.

## Terminal original-cohort roundup, 2026-10-23

The original 100-case queue is now terminal, **not 100 successful full docks**.
Sixty workflows completed new docking/searches and downstream output generation
(26 Vina, 26 QuickVina-W, eight experimental Apple AD4). Six attempted cases
stopped before docking; 34 related cases were deliberately left unattempted
against the proven upstream boundaries. There are no unaffected cases left to
launch. No failed science was retried, no replacements were added and no
glycans, chains or cofactors were removed to force a pass.

| Attempted case | Failure retained for review | Related unattempted cases |
| --- | --- | --- |
| 033 / 1UY6 | Strict GLU A75 template failure despite the existing PDBFixer attempt | 034 |
| 045 / 3PTB | GUI accepts nine-atom BEN; shell ligand-only resolver requires ten, after successful receptor PDBQT | 046-050 |
| 053 / 3ERT | Meeko/PDBFixer padding error involving A550/A552 | 054-060 |
| 061 / 4EY7 | Linked NAG/FUC templates; legacy ADFRsuite fallback cannot execute on this Mac | 062-068 |
| 069 / 1FM6 | Multichain template rejection, then carbon-valence exception | 070-076 |
| 093 / 1A4G | Linked NAG templates persist after existing PDBFixer/disulfide retries; legacy ADFRsuite also reports Bad CPU type | 094-100 |

The final seven cases share the whole glycosylated 1A4G receptor preparation
boundary. Selecting ZMR B466 instead of A466 would not change that failed
upstream preparation. They are blocked coverage, not seven measured failures.
The final worker, host and scientific children exited; idle cleanup and absence
of active processes were checked before reconciling the safety marker. The v8
run remains historical: 16 passed, one interrupted and seven not run.

The retained 60 searches are **not blanket full-workflow acceptance**. Final
snapshot review found that completed cases 051/052 have a 2D diagram but their
GUI explicitly reports unavailable 3D PLIP contacts and no verified residue
links. Both presentation gates were rejected without changing or repeating
their completed calculations. Together with the existing ABL label-overlap
failure, the presentation ledger is six passed, three failed and 51 pending.
All 60 retained native screenshots have been inspected; that does not replace
complete report or every-view inspection. Additional sampled PDF pages also
show a nearly empty final reference page needing pagination review. No new
full-report passes were granted from that sample.

Fourteen prepared PDB/mmCIF pairs were audited; deposited equality was not
treated as prepared/pose equivalence. Output hashes and original protected
studies passed the final audit. All 392 installed application files and the
private runtime remain unchanged. Multi-site behavior, post-run reclustering,
pose accuracy and platform certification are not established by this cohort.

Local terminal receipts: `validation/runs/full-docks-100-final-review-20261023/summary.json`,
`validation/local/full-docks-100-20261022/curated80/deferred-errors.json` and
`cohort-ledger.json`. Historical failures and all scientific evidence remain
local. The follow-up is paused for the requested error review; repairs or new
cases require a separately scoped continuation.

The user subsequently authorized fixing software defects first. The
[isolated repair checkpoint](software-defect-repairs-20261023.md) records tested
code corrections and retained-output checks. It does not overwrite the failed
cohort records, install the candidate or turn unresolved receptor preparation
into a pass. No additional docking was performed for those software checks.

The subsequent user-requested corrected-build retest added two separately
recorded actual workflows (trypsin/BEN, PDB and fresh-download mmCIF, Vina), both
functionally passing. They do not rewrite the original 100-case cohort or its
60 completed searches. All representatives in these runs plus one retained
QuickVina-W run passed strengthened native contact checks. Report review found
an additional protocol preparation-history wording error; isolated v3 corrected
only regenerated report copies, with no redocking. See the repair checkpoint
for the 113 Python/four shell-group results, separate original/corrected visual
gates and unchanged installation/protected-output audits. The candidate remains
uninstalled and the original cohort automation remains paused.

Later on 2026-10-23 the user authorized deployment and the qualitative RMSD
controls. The tested fixes and Tight/Default/Loose/Custom choices are now in
the source and installed Mac app. Twenty backed-up application files changed;
231 installed-runtime contracts, four shell groups and six native retained
representatives passed. This deployment launched no science, rewrote no reports
and does not change any original cohort outcome. The five remaining preparation
boundaries, full visual review and multi-site/reclustering coverage are still
open. See the repair checkpoint's deployment section and
`validation/runs/software-fixes-install-20261023-v4/summary.json`.
