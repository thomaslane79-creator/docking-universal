# Prospective 100-protein CPU workflow panel

Status: the user reiterated the 100-dock objective on 2026-10-26; resume the
remaining unaffected frozen cases and collect errors for later review. The
earlier broader planning hold is lifted. There are **eleven completed distinct
targets across development builds**, three retained failed/unsupported inputs and
86 remaining outcomes (80 executable, six explicit reference holds). The frozen
first-candidate baseline remains three completions and seven preparation
failures. This is separate from the historical
100-scenario cohort and the three development workflows completed on October 25.

The user clarified the goal as **more than 90%**: at least **91 of 100** declared
primary protein workflows must complete. The accounting schema now supports
`goal_comparison: greater_than`; its older default remains `at_least` so historical
receipts retain their meaning. A synthetic boundary test rejects 90/100 and
accepts 91/100 without performing any docking.

## Selection and scope

The panel declares 100 distinct UniProt targets across ten deliberate groups:
protein kinases; other transferases; proteases; other hydrolases;
oxidoreductases; other metabolic enzymes; ATPases/chaperones/ligases; nuclear
receptors; membrane receptors/transporters; and chromatin/regulatory proteins.
Different entries, chains, mutations or engines do not create extra proteins.
Target accessions and names are checked against public
[RCSB entity records and UniProt identifiers](https://www.rcsb.org/docs/general-help/identifiers-in-pdb).
Metadata corrections and ortholog choices precede any new preparation outcome.

The intended primary scope is experimental, ligand-bound structures with a
complete, identifiable small-molecule reference. It includes inhibitors and
endogenous ligands. This curated panel measures intended-use coverage; it is
not an unbiased estimate for every deposited protein, apo structures, covalent
docking or every engine/platform. Those require separate evidence.

Reference eligibility checks exact non-polymer entity/atom identity, contact
with the declared protein entity, occupancy, alternate conformations and CCD
chemistry/stereochemistry. Metal ions, buffers and detergents are not used as
reference docking compounds. An incomplete, ambiguous or covalently linked
reference can be replaced by the next metadata-ranked eligible reference for
the **same protein before freeze**. Every such exclusion is retained locally.
At freeze, 92 reference inputs passed these read-only checks. Eight retain
unresolved reference issues and are blocked from scientific execution. They
remain in the 100-target denominator; no different protein replaces them.
This is 92 input-eligible tasks, not 92 completed workflows. Those unresolved
reference cases will need explicit review or will remain blocked outcomes.

These checks do not parameterize, repair or select receptors based on whether
preparation succeeds. Receptor glycans, cofactors, metals, partner chains,
modifications and missing residues are retained for the real workflow test.

All public acquisition uses RCSB metadata, coordinate and CCD GET requests.
No local structure, pose, interaction, image, report or numerical result is
uploaded. Original inputs and previously completed studies remain untouched.

## Execution and counting

Freeze the full target/primary-case ledger, raw input hashes, exact reference
instances/boxes, private runtime and scientific settings before launching the
first ten. Use 50 raw PDB and 50 raw mmCIF cases, five ligand-library formats,
and one baseline Vina CPU profile: eight threads, pH 7.4, one retained shape,
one seed, exhaustiveness 16, 15 requested modes and an 8 kcal/mol window.
Actual generated states/search counts are retained separately from workflow
counts. These are bounded exploratory functional tests, not redocking controls
or affinity/pose-accuracy acceptance.

One predeclared target per group forms the first ten. Twenty other primaries
are reserved from scientific tuning; reference-identity metadata inspection is
not a preparation-performance test. The remaining cases start only after
review of the pilot's actual outcomes and cleanup. All calculations are
sequential through the existing native Qt/host supervisor. Unknown molecular
decisions stop the affected case, rather than being answered automatically.

Each completed primary needs new docking, clusters, PLIP/2D, protocol/screening
PDFs, native linked 3D review and fresh-host reopen. Preparation-only success,
preflight, old retained outputs and a passing boundary guard do not count as a
new dock. Unrun, blocked and failed primaries stay in the denominator. Routine
and explicitly reviewed-change routes are reported separately; external manual
rescues are disclosed separately. Visual quality and accuracy remain distinct.

The local staging root is `validation/local/protein-panel-100-20261025-v1/`.
The [frozen target ledger](../validation/local/protein-panel-100-20261025-v1/frozen-panel.json),
[selection/eligibility ledger](../validation/local/protein-panel-100-20261025-v1/selection-ledger.json)
and [read-only preflight](../validation/local/protein-panel-100-20261025-v1/preflight.json)
precede the [ten-case native pilot](../validation/runs/protein-panel-100-20261025-v1-pilot/summary.json).
The exact launch receipt records supervisor PID 23342. The private candidate
contains 422 pinned application files. No outcome is inferred from staging.
The first EGFR/8A27 case has progressed through site review, strict preparation
and protocol/report generation and **completed one new docking search**, PLIP/2D,
three native representative reviews and fresh-host reopen. It used the recorded
conditional PDBFixer route (zero heavy atoms added; one terminal atom not added).
It is classified as an ordinary application route with retained audits, not an
untouched deposited model. All three protocol and five screening PDF pages and
the native screenshot were inspected. The functional gate passed; very small
figure labels and partial ligand occlusion by the native cartoon keep its full
visual gate failed.

DOT1L/6TE6 stopped before docking. Initial strict template matching failed;
the enabled PDBFixer attempt added 108 side-chain heavy atoms and selected its
normal alternate locations, but added no backbone/sequence. Meeko then raised
an internal connectivity/padding error at A56/A58. This does not itself prove
incorrect deposited chemistry. The original and derivative models, audits and
failure remain retained; no extra molecular override or retry was applied.
Worker/host/scientific-child cleanup was confirmed by exact process inspection
before reconciling the conservative supervisor lock.

The [unstarted eight-case continuation](../validation/runs/protein-panel-100-20261025-v1-pilot-remainder8/summary.json)
was launched once with supervisor PID 28424, using the exact frozen profile,
inputs and settings. It repeats neither EGFR's completed science nor DOT1L's
failed preparation. The [execution ledger](../validation/local/protein-panel-100-20261025-v1/execution-ledger.json)
links phases; frozen-panel.json is unchanged. The existing ten-minute
follow-up is tied to this new run, remaining quiet during healthy work and
reporting meaningful milestones or decisions. It must not revisit/restart the
historical cohort.

The renin/3K1W case subsequently stopped before docking on linking NAG/HSQ
glycan templates. Its existing PDBFixer attempt added zero heavy atoms and did
not resolve the template boundary; a configured-backend compatibility warning
is a separate issue. No glycan was removed to obtain a pass. Its worker/host
and scientific processes were inspected absent before reconciling the lock.
The [seven unstarted pilot cases](../validation/runs/protein-panel-100-20261025-v1-pilot-remainder7/summary.json)
continue once, with supervisor PID 36024 and unchanged frozen profile/inputs.

After renin, eight reference holds and two attempted preparation failures left
the unchanged baseline with a maximum of 90/100. It could not establish the
strict >90% goal. Finish the pilot, review the common software versus scientific
boundaries, and address those blockers before launching the broader ninety
unchanged. Preserve the baseline; do not replace failed proteins or weaken the
threshold. The error and execution ledgers retain exact causes and phases.

PDE5A/1TBF then stopped before docking: Meeko requires specific alternate-location
choices at A634, A667, A670, A691, A805, A816 and A847. The generic diagnosis
incorrectly labeled this unclassified; that classifier gap is recorded for
correction after the active pilot. Reduce2 separately lacked ZN/MG restraints
and the original filtered receptor was retained; PDBFixer produced no accepted
repair and the legacy executable failed its startup compatibility check.
These are distinct boundaries, not a Vina-search failure or proof of bad
experimental coordinates. No extra model choice was answered automatically.

After exact worker/host/scientific-process inspection and lock reconciliation,
the [six never-started pilot cases](../validation/runs/protein-panel-100-20261025-v1-pilot-remainder6/summary.json)
continue once with supervisor PID 37857. At this checkpoint the confirmed
functional count is one, with three attempted preparation failures and eight
separate reference-input holds. The unchanged baseline maximum is now 89/100;
the broader ninety stay gated on the pilot/error review and blocker resolution.
The working Mac installation, scientific defaults and GPU registrations are
unchanged.

## Bounded continuation and failure diagnosis

The ignored local `pilot_coordinator.py` now handles only safely stopped
parameterization jobs. It checks terminal job state, absence of pending decisions
or screening, exact input/runtime hashes, previous completed/protected outputs,
and two actual process snapshots covering recorded PIDs, process groups and
scientific command markers. Only then can it use the normal supervisor's lock
reconciliation and launch a new subset of never-started pilot cases. It never
kills a process, repairs a molecule, retries a failed case or launches the broader
ninety. Twelve synthetic/process safety checks passed; they are not docking
workflows. The [coordinator status](../validation/local/protein-panel-100-20261025-v1/coordinator-status.json)
and execution ledger identify the current phase. Historical interrupted runs
remain unchanged.

Two more baseline preparation failures are retained. DHFR/1KMV has both
alternate-location and template conflicts; its repair audit specifically refuses
missing backbone atoms at ASP A186, creates no repaired output and adds no heavy
atoms. PKM/3GR4's generated repair was rejected for sub-Angstrom heavy-atom
overlaps. Those overlaps describe the attempted derivative, not the deposited
model. No new molecular choice or repeated preparation was applied.

HSPA8/5AQV subsequently completed a new Vina search, clustering, PLIP/2D, PDFs,
three native representative views and fresh-host reopen. Its ordinary conditional
PDBFixer route added 68 side-chain heavy atoms and did not add one detected
terminal atom; this history is retained and must accompany the functional pass.
Its three protocol and six screening PDF pages and native screenshot have been
inspected. Small figure text and native-cartoon occlusion remain presentation
failures, separate from functional completion. At this checkpoint there are two
functional passes and five attempted pre-docking failures; later pilot cases
remain active/unstarted. Derive current counts from actual supervisor rows,
because the coordinator's convenience list of passed IDs may lag new passes.

A read-only reproduction also found a concrete box-review software gap:
`collect_site_issues` locates none of PDE5A's seven backend-named alternate-location
residues and misses DHFR's additional alternate-location list. The failure
classifier also misses an alternate-location-only error. Correct those parsers
in a separately versioned candidate after the frozen pilot ends; do not select
conformers or omit residues as part of a diagnostic correction.

## Terminal pilot and format corrections

All ten original pilot cases reached terminal outcomes. Exact worker/host/job
process inspection found no remaining scientific calculation; all completed
output inventories and protected paths matched. The frozen private runtime's
422 files and the installed application's 395-file baseline matched. The
[terminal audit](../validation/local/protein-panel-100-20261025-v1/pilot-terminal-status-audit.json)
and [coverage accounting](../validation/local/protein-panel-100-20261025-v1/coverage-live-003.json)
retain the evidence: three application-supported primary completions, seven
attempted preparation failures and ninety primaries not executed. Eight of those
ninety have separately recorded reference-input holds. All three completed
reports/native screenshots were reviewed; their presentation gates failed for
small figure text and partial cartoon occlusion, without relabeling completed
searches as failed searches.

| Primary | Baseline outcome |
| --- | --- |
| EGFR / 8A27 | Completed new Vina workflow; conditional repair added zero heavy atoms |
| DOT1L / 6TE6 | Meeko connectivity/padding error after side-chain reconstruction |
| Renin / 3K1W | Unsupported linked NAG/HSQ templates |
| PDE5A / 1TBF | Explicit alternate-location error, followed by the mmCIF geometry-audit bug |
| DHFR / 1KMV | Alternate/template conflict; missing ASP A186 backbone correctly prevented repair |
| PKM / 3GR4 | Generated repair rejected for gross overlaps |
| HSPA8 / 5AQV | Completed new Vina workflow; 68 side-chain atoms added, no backbone built |
| Androgen receptor / 8E1A | Completed new Vina workflow; 12 side-chain atoms added; one sequence segment detected but not built |
| Beta2 receptor / 2RH1 | Unsupported linked GLC/PLM/ACM templates |
| HDAC1 / 9R4I | ProDy mmCIF indexing failure, then the application mmCIF geometry-audit bug |

The original seven failures and eight reference holds leave the unresolved
baseline with an upper bound of 85/100, even if all other cases completed. This
is a diagnostic baseline, not a measured population success rate or a claim that
reviewed changes cannot improve coverage. Do not launch the broader ninety
unchanged or replace failed proteins to manufacture the goal.

After pilot cleanup, bounded development-source corrections addressed four
demonstrated defects:

- The repair-geometry guard now reads native mmCIF with Gemmi, keeping author
  residue identities and the existing overlap threshold. It refuses nonfinite
  or empty coordinates and ambiguous multiple mmCIF models.
- Generated native mmCIF ends with a CIF comment. ProDy's reader otherwise skips
  the last atom when its atom-site loop reaches EOF. The retained 9R4I input
  reproduced the failure; the corrected projection reads all 20,587 atoms with
  exactly unchanged atom identities, coordinates and occupancies.
- Box-review extraction accepts explicit backend lists and component
  dictionaries. The retained PDE5A error now locates seven residues instead of
  zero; renin locates its two linked components, and DHFR locates all 25 named
  template/alternate-location residues.
- Failure categories distinguish alternate-location-only requests, refused
  backbone construction, internal native-reader errors and application format
  errors. Original diagnoses stay retained beside the corrected interpretation.

The corrected geometry guard also reads the saved PDE5A and HDAC1 attempted
derivatives without the previous format exception and finds no introduced gross
overlap under its existing threshold. This is neither complete chemical
validation nor strict-Meeko/docking acceptance. These reproductions change no
original input or retained scientific output and launch no preparation/search.
See the [retained-input reproduction receipt](../validation/local/protein-panel-100-20261025-v1/diagnostic-fix-retained-reproductions/summary.json).
The frozen v1 runtime remains untouched; corrected-build end-to-end retests must
use a new version and retain the earlier failed outcomes separately.

The corrected source passed 862 Python case executions across 31 overlapping
groups (95 expected runtime skips) and 21 shell checks. Six separate native-reader/
evaluation checks and 16 Qt/site-review checks passed. The initial full-suite
invocation stopped on the known Xcode-license system-Make boundary; using GNU
Make throughout the test PATH passed without accepting a license. These checks
are not protein workflows.

The [two-case corrected-build retest](../validation/runs/protein-panel-100-20261025-v2-format-retests/summary.json)
was launched once with supervisor PID 60154. Its isolated 422-file runtime differs
from frozen v1 in only the four documented format/diagnostic files. It uses the
same original local mmCIF inputs, CCD libraries, exact ligand sites and scientific
settings; the earlier fresh GUI downloads remain tested baseline evidence.
Ordinary conditional preparation retains its audit, and any new molecular choice
still stops. These are supplemental development retests, not silently replaced
baseline successes or a mixed-build >90% acceptance claim. All original pilot
run directories are protected during the retest.

## Corrected-build outcomes and exact reviewed follow-ups

Both targeted format retests completed the full native workflow. PDE5A retained
Zn/Mg and passed through the ordinary conditional location-selection route with
zero heavy atoms added; its six generated chemical states produced six actual
Vina search outputs. HDAC1 passed strict Meeko without PDBFixer after the native
reader correction, then produced one search. The
[terminal audit](../validation/local/protein-panel-100-20261025-v2-format-fixes/terminal-audit.json)
verifies both full output inventories, protected paths, runtime hashes and exact
process cleanup. Development evidence now contains **five distinct completed
pilot targets and ten searches across baseline and corrected builds**. Frozen
baseline accounting remains three primaries; these separate-build rescues do
not establish >90% acceptance or silently replace earlier failures.

PDE5A's report exposed two further correctness defects. Unavailable cross-state
RMSDs removed twelve of the top twenty clusters from the graph/table, including
the third energy-ranked representative, and shifted highlight colors. Shared
report code now retains all twenty global ranks, places unavailable distances
in a separate categorical N/A strip, preserves rank colors and exports N/A
rather than a fabricated RMSD. The caption explains the distinction. The repair
note also retains the recorded alternate-location policy instead of claiming
no structural changes when zero atoms were added. Three new real-geometry/plot
checks and 62 shared report regressions passed (65 final source checks).

A [corrected report copy](../validation/runs/protein-panel-100-20261025-v4-report-review/PDE5A_report-correction-full-source.pdf)
was regenerated from saved results, with unchanged scores/PLIP and no new
preparation or docking. The isolated two-file test layout initially lacked the
full renderer assets/version; its earlier intermediate PDF is retained as an
invalid renderer fixture. The final copy used complete source assets and the
pinned Node runtime. Its table retains all twenty rows, the third-rank gold
cluster appears in the N/A strip, and its preparation note records location
selection. All six final PDF pages were inspected. Original result inventories
still match; small report labels/native-cartoon occlusion remain independent
presentation issues. HDAC1's two protocol/five screen pages and native image were
also inspected with the same presentation limitation.

The user then approved exact exploratory component exclusions for renin
(NAG A344, HSQ B345) and beta2 (PLM A415, ACM A411, GLC B1/B2). Actual GUI
previews/adoption were exercised in isolated retests, preserving original inputs
and permanent warnings. Both stopped before docking on additional, unapproved
issues: renin required eleven deposited alternate-location choices, and beta2
ASP A29 lacked CG/OD1/OD2. Neither stop was bypassed. Exact process snapshots and
protected-output checks preceded normal supervisor-lock reconciliation; both
historical reviewed attempts remain failed.

The user has now explicitly approved all eleven listed renin A locations
(each A/B occupancy is 0.5/0.5), and separately authorized an isolated rebuild of
only beta2 ASP A29 CG/OD1/OD2 with every observed atom preserved and no backbone
addition. The exact authority is retained in
[the follow-up record](../validation/local/protein-panel-100-20261025-v5-approved-followup/user-approval.json).
Renin's new [one-case follow-up](../validation/runs/protein-panel-100-20261025-v5-renin-approved-alternates/summary.json)
was launched once with PID 78335, using a frozen 422-file candidate containing
the tested format/diagnostic/report corrections. The beta2 three-atom model has
**not** been generated: its bounded builder/provenance checks must be implemented
and verified before any actual target modeling, sequentially after the active
renin calculation. No other conformers, exclusions or repairs are approved.
The working installation remains unchanged and the broader ninety remain held.

The exact-choice renin follow-up subsequently **completed** strict preparation,
new Vina docking, clustering, PLIP/2D, reports, native 3D and fresh-host reopening.
It retains both approved exclusions and all eleven explicitly chosen A
locations in portable model history. Its
[terminal audit](../validation/local/protein-panel-100-20261025-v5-approved-followup/renin-terminal-audit.json)
verifies one actual search, completed/protected hashes and complete process
cleanup. There are now six distinct pilot targets with completed workflows and
eleven actual searches across the separate baseline/development builds. Renin's
new presentation gate remains pending. Original baseline accounting and failed
reviewed attempts remain unchanged.

The approved beta2 trial then generated only ASP A29 CG/OD1/OD2 in an isolated
CPU model. Five projection safety tests passed. The trial refuses additional
missing atoms, residue conversion, unresolved alternate locations or backbone
construction; only the three authorized generated atom coordinates are projected
onto the original input. Every observed record remains verbatim, and the existing
gross-overlap guard passed. Actual algorithm, seed, source/approval/model hashes
and warnings are retained in the
[local trial audit](../validation/local/protein-panel-100-20261025-v6-beta2-three-atoms/trial/audit.json).
This is **geometry feasibility only**, not strict parameterization, application
GUI adoption, a portable reviewed protocol or another completed workflow. Those
application/provenance steps remain necessary before this route can count toward
the completion goal. No new beta2 docking has been launched.

The development application now has a bounded local side-chain-candidate review
handoff. It verifies the exact declared standard side-chain additions, a resolved
observed backbone, unchanged observed records/metadata, parent/model/receipt
hashes and the existing gross-overlap guard. The GUI requires a fresh preview,
rationale and acknowledgement. Generation provenance and earlier component
exclusions remain portable; the application does not silently generate atoms or
claim chemical accuracy. Eight new synthetic candidate/workflow guards and the
existing focused contracts pass: 81 scientific service/workflow/report checks,
seven Qt review checks and fourteen scientific control contracts.

The [beta2 application retest](../validation/runs/protein-panel-100-20261025-v7-beta2-reviewed-sidechain/summary.json)
launched once with supervisor PID 91910. Its frozen 423-file private runtime
contains only the five bounded handoff/geometry changes above the preserved v5
runtime. It reuses the already generated, approved three-atom candidate rather
than regenerating it, retains all four approved component exclusions, and has
reached real GUI adoption/strict preparation. This is an active test, not a
seventh completed target. The 395-file installed application remains unchanged,
historical attempts remain intact and the broader ninety are still held. See
the [pinned launch and authority](../validation/local/protein-panel-100-20261025-v7-beta2-application-review/beta2-launch.json).

The beta2 retest then **completed the full functional workflow**, with one new
Vina search, three native representatives/fresh-host reopening, clustering,
PLIP/2D and both report types. The exact four component exclusions and three
modeled atoms, generation provenance and original-input hash survived protocol
export/import and screening. The
[terminal audit](../validation/local/protein-panel-100-20261025-v7-beta2-application-review/beta2-terminal-audit.json)
verifies retained/protected output hashes, the 423-file candidate, exact process
cleanup and the unchanged 395-file installation. Development evidence now has
**seven distinct completed pilot targets and twelve actual searches across
builds**; frozen first-candidate accounting remains three primaries.

All three protocol PDF pages, six docking PDF pages and the native linked
screenshot were inspected. Exact modification warnings are visible. The
[presentation review](../validation/runs/protein-panel-100-20261025-v7-beta2-review/summary.json)
failed independently for miniature report labels and opaque native cartoon
occlusion. No docking was repeated for this review. The candidate was generated
outside the application and then verified/adopted through its real GUI: this
accepts the bounded import/review handoff, not an integrated user-facing repair
builder. Preserve that generation distinction in any future application-supported
coverage classification; no >90% or installation acceptance is claimed.

A read-only review of the three still-failed pilot targets and eight frozen
reference holds launched no new science. DOT1L's failing pair contains a newly
modeled GLU A56 oxygen beside an observed TYR A58 ring atom; observed heavy atoms
were not moved. A concrete
[four-atom follow-up proposal](../validation/local/protein-panel-100-20261025-v7-beta2-application-review/dot1l-four-atom-review-proposal.json)
would retest only GLU A56 CG/CD/OE1/OE2, keeping the other 104 previously modeled
atoms and every observed record unchanged. This is a new molecular choice and
is awaiting direct user approval; no new model has been generated. DHFR's
missing-backbone and PKM's generated-overlap failures remain unresolved.
The eight reference holds include four covalent references, four incomplete
reference inventories, one alternate-location issue and one missing intended-
target contact (categories overlap). None was silently approved or replaced.

## Approved DOT1L four-atom follow-up (2026-10-26)

The user explicitly approved one isolated rebuild of GLU A56 CG/CD/OE1/OE2,
preserving every observed atom and the other 104 previously modeled atoms, with
all 108 modeled atoms permanently flagged. The exact
[authority](../validation/local/protein-panel-100-20261026-v8-dot1l-four-atoms/user-approval.json)
is linked to the original proposal and retained input hashes. Five synthetic
projection guards passed before the single CPU trial was started. The trial
removes only those four previously generated records from a copy, disables
backbone/segment construction and residue conversion, and projects only their
new coordinates onto the retained model. A separate exact projection retains
every original normalized input record for application review. This is active
modeling, not a new docking completion; historical failures and the broader
ninety remain unchanged. See the
[current trial receipt](../validation/local/protein-panel-100-20261026-v8-dot1l-four-atoms/runner.json).

The single trial **passed its geometry/projection guards**. All four approved
coordinates changed, the other 104 modeled atom coordinates stayed unchanged,
and every original normalized input record remains verbatim in the application
candidate. No additional conformation was generated. The review importer now
also verifies the earlier reconstruction hash and retained-coordinate inventory,
and carries a concise **108 modeled / 104 retained / 4 regenerated** warning,
with both generation histories. Two new provenance checks and the focused
service/workflow/report groups passed: 83 checks in the final source group.

The [v9 native continuation](../validation/runs/protein-panel-100-20261026-v9-dot1l-reviewed-four-atoms/summary.json)
was launched once with supervisor PID 36867, using a frozen 423-file candidate.
It cloned the exact saved failed-study checkpoint, changed only its output
directory, retained the original site approval/failure, and used the real GUI
to review the new model. The completed pocket analysis and old preparation were
not repeated. The new strict preparation **failed before docking** after the
ordinary Reduce2 stage, with an RDKit carbon-valence error. No prepared receptor,
portable protocol or new docking completion was registered.

Read-only reproduction against the retained backend inputs located the
valence failures in **ARG A73 and ASN B126**; the heavy-atom-only residue parsing
passed, while parsing the retained hydrogenated input failed. Comparing inferred
internal bonds with the existing standard-residue restraint tables identified
ARG CG–NE and ASN CB–ND2 / ND2–OD1 as extra inferred heavy-atom edges. This does
not authorize removing bonds, accepting the modeled geometry or weakening
valence validation. An exact
[standard-connectivity proposal](../validation/local/protein-panel-100-20261026-v9-dot1l-application-review/standard-connectivity-review-proposal.json)
retains all atoms/coordinates and the complete 108-atom warning, and is awaiting
a separate direct user decision. No override has been applied.

The [terminal cleanup audit](../validation/local/protein-panel-100-20261026-v9-dot1l-application-review/dot1l-terminal-cleanup.json)
verifies exact worker/host/scientific PIDs 36867/36876/36900 exited, all original
jobs/site authority and protected hashes stayed intact, the candidate runtime
and 395-file installed application are unchanged, and raw cleanup is idle.
Only then was the conservative runner lock reconciled. The interrupted v9
supervisor record and actual failed-preparation evidence remain retained.
Development totals remain **seven completed pilot targets and twelve actual
searches across builds**; frozen-baseline three primaries and broader-ninety
hold remain unchanged.

The user then explicitly approved the exact three-edge standard-connectivity
test, with all atoms/coordinates and all 108 modeling flags retained. The
[direct authority](../validation/local/protein-panel-100-20261026-v10-dot1l-connectivity/user-approval.json)
binds the earlier proposal. An opt-in adapter changes only those exact existing
distance-inferred side-chain edges inside its isolated Meeko process; unreviewed
residues use the original reader, and strict sanitization/template matching
remain enabled. The installed package and default preparation route are unchanged.
It reuses the checksummed hydrogen stage instead of running Reduce2, pocket
prediction or model generation again. The modeling and connectivity warnings
are separate and portable; per-box review uses the saved backend coordinates
for the two connectivity issues.

The final focused source group passed **93 checks**, and seven Qt review checks
passed. Read-only parsing of the actual saved input passed all 642 residues with
exactly three reviewed edges applied and unchanged input hashes. This is residue-
reader preflight, not full parameterization or docking. Initial supervisor
invocation 50084 rejected five malformed input-role labels before creating a run
or scientific worker. The invalid suite/log/receipt remain retained. A bounded
[prelaunch correction](../validation/local/protein-panel-100-20261026-v10-dot1l-connectivity/prelaunch-adapter-correction.json)
renamed only those labels and passed the typed suite/input checks, without
changing model, coordinates, settings or edges. The corrected
[v10b native continuation](../validation/runs/protein-panel-100-20261026-v10b-dot1l-reviewed-connectivity/summary.json)
launched once with supervisor PID 51633 and the same frozen 425-file private
runtime; no scientific stage was retried by the label correction.

The real backend applied exactly the three approved internal-edge overrides,
then **failed strict global parameterization before docking**. Meeko reported
additional inferred inter-residue links at A56/A58 and A59/A77. Read-only mapping
identified GLU A56 OE2–TYR A58 CE2, GLU A56 OE2–TYR A58 HE2, and VAL A59
HG23–LYS A77 CD. These additional links were not removed. Rejecting distance-
inferred connectivity would leave the close contacts in place, not establish
acceptable model geometry. The exact
[additional-link proposal](../validation/local/protein-panel-100-20261026-v10-dot1l-connectivity/additional-interresidue-review-proposal.json)
is awaiting a new direct user decision, beyond the three internal edges already
approved.

The [v10b terminal audit](../validation/local/protein-panel-100-20261026-v10-dot1l-connectivity/terminal-cleanup-v10b.json)
verifies PIDs 51633/51635/51648 and matching descendants exited; original jobs,
failed records, input/protected hashes and all five saved coordinate-stage files
remain unchanged. The candidate's 425 files and installed application's 395
files still match. No atoms/coordinates changed, no model/Reduce2/pocket stage
was repeated, and no prepared receptor or docking output was registered. The
conservative lock was reconciled only after actual process inspection. All
historical failures remain retained. Totals remain seven distinct completed
pilot targets and twelve actual searches across builds, with baseline three
primaries and the broader-ninety hold unchanged.

The user approved those three additional inter-residue links explicitly. The
[new authority](../validation/local/protein-panel-100-20261026-v11-dot1l-interresidue/user-approval.json)
allows only GLU A56 OE2–TYR A58 CE2/HE2 and VAL A59 HG23–LYS A77 CD, retaining
all atoms/coordinates, the three earlier internal overrides and all 108 modeling
flags. A new opt-in adapter preserves all other inter-residue links, refuses
declared LINK/CONECT/disulfide or unsupported backbone overrides, and checks
the installed reader's source hash. No default/library installation changes
or additional automatic choices are allowed. The final focused source group
passed 96 checks; the real saved-input preflight applied exactly three internal
and three inter-residue overrides without other edge/coordinate changes.

The [v11 native continuation](../validation/runs/protein-panel-100-20261026-v11-dot1l-reviewed-interresidue/summary.json)
launched once with supervisor PID 56740 and worker PID 56744, using a new frozen
425-file private candidate. It has **passed full strict parameterization and
portable protocol finalization** and is now performing the target's first new
docking/results workflow. The saved hydrogen/site stages and original model
were reused; no geometry was regenerated. The portable warning states that
close contacts remain and geometry is unvalidated. No eighth completed target
is counted until docking, downstream outputs, reopening and cleanup are verified.

The v11 continuation is now **functionally complete**: one actual new Vina
search, clustering, PLIP/2D, portable protocol and docking PDFs, three native
representatives and fresh-host reopening passed. The
[terminal audit](../validation/local/protein-panel-100-20261026-v11-dot1l-interresidue/dot1l-terminal-audit.json)
verifies worker/host/scientific processes exited, cleanup is idle, all 222 output
and 2,844 protected files match, all five saved coordinate-stage files are
unchanged, and the private 425-file runtime and installed 395-file application
still match. The prepared receptor hash is
`a894ba307e55782cc0f79ce610988a12127b0bd30ee38deb3be8cff4f588bb73`.
All 108 modeled atoms, the 104-retained/four-regenerated distinction and the six
exact connectivity overrides survived protocol export, reports and reopening.
The adapter removed no atom and changed no coordinate; close contacts remain.
Earlier failed attempts and the frozen primary outcomes remain unchanged.

All two protocol and five docking PDF pages plus the retained native screenshot
were inspected. Exact modification warnings are visible. The
[presentation review](../validation/runs/protein-panel-100-20261026-v11-dot1l-review/summary.json)
**failed** for miniature report labels and mixed 2D styles. The third native
representative is broadly legible with crowded context; the other two were
exercised functionally but were not independently image-judged. No search was
repeated for this review.

Development totals are now **eight distinct completed pilot targets and thirteen
actual searches across builds**. External local model generation followed by
application review is disclosed; an integrated repair builder remains unfinished.
The first frozen candidate still has only three completed primaries. DHFR's
missing-backbone and PKM's generated-overlap cases plus eight reference holds
remain unresolved, limiting unchanged optimistic coverage to 90/100. The broader
ninety are held for review; no single-candidate >90%, accuracy, installation or
other-platform acceptance is claimed.

## Reference holds: read-only review after DOT1L

The [concrete local proposals](../validation/local/protein-panel-100-20261026-v12-reference-review/reference-review-proposals.json)
verify the frozen source/library hashes, exact GUI-detected identities and
unchanged predefined centroids. No preparation, docking, atom reconstruction or
approval occurred. Two conditional proposals use only the existing incomplete
deposited instance as an exploratory site anchor: GSTP1/6Y1E O7Z A303 has five
of 23 CCD heavy atoms; lipase/1LPA BNG B450 has 20 of 21, lacking C1. The already
frozen complete CCD-derived screening molecules, stereochemistry and boxes
would stay unchanged. These coordinates cannot establish the complete ligand's
chemistry/stereochemistry; permanent incomplete-reference and CCD-source warnings
must survive downstream outputs. Neither case would be a pose-recovery control.
The proposals await a separate direct user decision and grant no receptor
repair, component removal or new conformer selection.

A separate [classifier audit](../validation/local/protein-panel-100-20261026-v12-reference-review/reference-classifier-audit.json)
corrects two interpretations without changing historical hold records. 5TDI has
all 36 CCD heavy-atom names: its old inventory comparison also included one
explicit stereo-defining SDF hydrogen, causing a misleading missing-inventory
label. Its covalent-link hold remains. 1MX1 has four complete 15-heavy-atom
alternate locations at the selected instance; counting all 60 records does not
make each conformation incomplete. No conformation is selected, and its original
box averages the alternatives, so that hold remains. All eight reference holds
remain in the denominator; this read-only correction adds no completed target.

The user subsequently approved **both exact incomplete references as flagged
site anchors**. The [direct authority](../validation/local/protein-panel-100-20261026-v12-reference-review/user-approval.json)
allows no coordinate reconstruction, chemistry change, box change, receptor
intervention or pose-recovery claim. A bounded host receipt import now verifies
the source/CCD/library/authority and selected-box hashes before ordinary GUI
box approval. The GUI displays the warning beside the box. Inline reference
history is distinct from receptor-model changes and is normalized during
portable export/import and reporting, with transfer to a control or another
box rejected. The focused groups passed **138 Python checks and nine Qt checks**.

The [two-case native run](../validation/runs/protein-panel-100-20261026-v13-reviewed-reference-anchors/summary.json)
launched once, sequentially, with supervisor PID 72866 and a new 426-file private
candidate. The [launch receipt](../validation/local/protein-panel-100-20261026-v13-reviewed-reference-anchors/launch.json)
pins `suite-v2.json` and its driver. A static prelaunch check caught the driver's
incorrect assumption about nested import-preview state; the original driver and
suite remain retained and the versioned correction preceded all scientific
execution. No scientific stage was repeated. All frozen source files, screening
molecules, settings and boxes are unchanged; the installed 395 files still
matched before launch. These are two previously unstarted **nonpilot** targets,
not repeated pilot searches or replacements for frozen failures.

At this checkpoint, GSTP1/6Y1E has passed actual coordinate-site review, strict
receptor preparation and protocol finalization. Its exact incomplete-reference
warning is visible in GUI box review and portable import preview, and its inline
authority binds the new prepared receptor and unchanged box. Its native ligand
screening/results path is active; lipase/1LPA remains queued. Neither is counted
as a full completion yet. The earlier eight completed pilot targets/thirteen
searches across builds, the three frozen baseline primaries and broader-ninety
hold remain unchanged until new terminal evidence is verified.

Both approved reference-anchor cases are now **functionally complete**, with
one new Vina search each, clustering, PLIP/2D, PDFs, three linked native
representatives per target and fresh-host reopening. Their exact reference
warnings survived protocol export/import, screening and reopening; no reference
atoms or frozen boxes/libraries were changed. The
[terminal audit](../validation/local/protein-panel-100-20261026-v13-reviewed-reference-anchors/terminal-audit.json)
verifies 456 output files, 3,070 protected files, all inputs, the private 426-file
runtime and the unchanged installed 395 files. All supervisor/worker/host/scientific
processes exited and raw cleanup is idle. GSTP1 used the ordinary conditional
PDBFixer route, adding zero heavy atoms and selecting its recorded default
alternate locations; lipase used strict Meeko without PDBFixer. Lipase's Reduce2
attempt failed for missing component definitions; its original filtered model
was retained for the successful strict route. These paths are recorded rather
than described as untouched depositions or successful Reduce2 runs.

All five protocol and twelve docking PDF pages plus two retained native
screenshots were inspected. The exact warnings are visible. Both
[visual gates failed](../validation/runs/protein-panel-100-20261026-v13-reference-review/summary.json)
for miniature figure/residue labels and partial native cartoon occlusion.
GSTP1's protocol warning spans two pages but is complete. Each retained screenshot
shows the third representative; the other two per target were exercised
functionally, not independently image-judged. The report retains an unverified
engine-version placeholder from protocol creation, while actual engine identity
is separately pinned in execution evidence. No docking was repeated for review.

Verified development totals are **ten distinct cohort targets and fifteen actual
searches across builds**, comprising eight pilot targets and these two nonpilot
targets. Neither replaces a frozen failure or upgrades the original three-primary
baseline score. Six original reference holds and two unsupported pilot inputs
remain; the optimistic unchanged ceiling is now 92/100, not measured coverage.
The broader panel remains held for common-blocker review and a consistent
candidate/route acceptance plan; no scientific worker is active. No >90%, pose
accuracy, engine-equivalence, installation or other-OS acceptance is claimed.

## Remaining cohort resumed at the user's direction

The user reiterated, “the goal was to do 100 docks.” This supersedes the broader
planning hold: continue unaffected unstarted cases and collect safely stopped
errors for end review, without delaying docking for cosmetic report repairs.
Exact molecular approvals and process-safety guards remain in force.

The [remaining 88-outcome queue](../validation/runs/protein-panel-100-20261026-v14-unstarted88/summary.json)
launched once with supervisor PID 85175. Its
[execution ledger](../validation/local/protein-panel-100-20261026-v14-unstarted88/execution-ledger.json)
and launch receipt pin the original 88 unstarted case IDs, sources, libraries,
reference sites and settings. Eighty-two are executable full workflows; six
retain explicit reference-review capability holds and cannot count as docks.
Ten completed distinct targets and the two retained unsupported pilot inputs
complete the original 100-target accounting. The tested 426-file v13 application
runtime is reused unchanged; no previous scientific attempt is repeated and the
installed application is untouched. One worker runs at a time.

The first new case, BRAF/8C7X (`protein-002-8c7x-vina`, worker PID 85294), has
passed preparation and protocol finalization and entered native screening/review.
No new full completion is counted until terminal receipts and hashes pass.
An unexpected failure still stops its supervisor for inspection; after exact
cleanup, continue only unaffected unstarted cases in a new versioned subset,
preserving the failure. Do not repair/retry scientific inputs automatically or
skip unrelated coverage. Visual acceptance remains separate from the active
docking queue. The automation follows this active run rather than polling the
closed reference pair.

The v14 phase closed with **one full functional pass (BRAF/8C7X, five actual
chemical-state searches)** and one stopped MAPK14/4EHV preparation. Site review
passed for 4EHV; initial Meeko rejected incomplete LYS A121/GLU A160 and requested
alternate-location review. Its existing PDBFixer fallback added ten side-chain
heavy atoms, built no backbone/segments, then strict Meeko rejected HIS A199
template/connectivity. No 4EHV docking started and no additional repair or
override was applied. Preserve this failure for end review; do not skip other
proteins on its account. The failed worker's final input-check flag was not
reached; an independent SHA audit confirms its inputs are unchanged.

The [v14 cleanup audit](../validation/local/protein-panel-100-20261026-v14-unstarted88/terminal-audit.json)
verifies BRAF output/input/protected hashes, the unchanged 426-file candidate and
395-file installed application, idle raw cleanup and absent exact stopped
supervisor/worker/host/scientific PIDs 85175/86805/86810/86812/86814. Only then was
the conservative lock reconciled. Both historical supervisor outcomes remain
unchanged. Visual review of BRAF is pending and does not block new science.

The [v15 continuation](../validation/runs/protein-panel-100-20261027-v15-unstarted86/summary.json)
launched once with supervisor PID 96644, selecting **only the 86 unstarted
original cases** (80 executable full workflows, six unchanged reference holds).
Its [continuation receipt](../validation/local/protein-panel-100-20261027-v15-unstarted86/continuation-spec.json)
verifies unchanged cases, inputs, runtime, driver and settings. No BRAF search,
4EHV preparation or other earlier science is repeated. Counts verified before
v15 are **eleven distinct completed targets and twenty actual searches across
builds**; those are not a one-candidate >90% result. The queue continues under
the user's skip/collect-errors direction, with exact cleanup required before
each further unstarted subset.
