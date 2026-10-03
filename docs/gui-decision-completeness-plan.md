# Complete interactive GUI workflow plan

Scope changes are governed by the
[GUI idea backlog and implementation gate](gui-idea-backlog.md). New ideas are
recorded without interrupting this plan unless they address a demonstrated
correctness, safety, crash, or acceptance blocker.

## Revised interaction rule (2026-09-23)

The intended experience is one chronological scientific run, not a general
"pause anywhere and resume later" feature. Configuration appears when its
stage needs it; an evidence-dependent scientific choice appears only after the
evidence exists. A required choice blocks downstream computation until answered.
Persisting that pending choice protects the audit trail and handles an accidental
window close; it is not a user-facing checkpoint system or a "Review later"
workflow. Non-blocking irregularities stay visible without stopping the run.

The desktop now exposes an initial exploratory-versus-known-ligand-control path.
The latter invokes the existing noninteractive control runner with an exact
deposited ligand and registers a reusable bundle only after verifying that it
is a control-approved protocol. A GUI journey test covers the path into later
SDF screening with substitute scientific executables. Real control-engine,
guided tier-escalation, chemistry-intervention, and platform acceptance gates
below remain open; the new route does not imply those are complete.

Date: 2026-09-21. Status: active implementation plan, grounded in the current
source. This document defines completion of the rigid-receptor GUI workflow.

Implemented foundation (2026-09-21): decision schema v3 retains structured
payloads, progressive explanation content, and validated continuation metadata.
The GUI has a reusable resizable decision window with Brief, Guided, Background,
and Technical views. It remembers only the explanation level, never an answer or
approval. Mid-stage decisions can persist a queued checkpoint without completing
their scientific stage. Deposited-ligand selection now carries exact chain,
residue number, insertion code, and alternate-location identity through the GUI,
host and Bash preparation engine; repeated ligand names no longer force a merged
centroid. Scientific-engine continuation handlers and the remaining decision
inventory are still required by the slices below.

First preparation intervention implemented (2026-09-24): ambiguous histidine
template failures now produce a versioned JSON intervention, pause the active
preparation job, and appear in the reusable decision dialog as explicit
HIE/HID/HIP choices or Stop. An approved choice archives the failed engine
attempt and resumes the same job with exact Meeko template assignments. For
mmCIF inputs, the retained evidence includes any explicit deposited ring H/D,
alternate-location/occupancy/B-factor records, nearby atoms, site annotations,
reported crystallization pH, experimental method, and resolution. Those fields
support review but never select a tautomer automatically. Unsupported cofactor
and removal failures remain failure-closed until an exact, reviewable proposed
change can be represented.

Scientific-completeness correction (2026-09-24): the bounded histidine dialog
is an orchestration implementation, not yet a sufficient assignment method.
Meeko's tie means its atom/template matching cannot distinguish the states. The
GUI must not imply that an ordinary user can resolve that tie by preference.
Before recommending a state it needs independent, retained local-environment
evidence (for example deposited H/D, metal coordination, hydrogen-bond/steric
analysis, or a validated protonation calculation) and must explain the basis and
limitations. If independent evidence remains equivocal, the supported outcomes
are Stop/correct the receptor or an explicitly designed sensitivity workflow;
an arbitrary HIE/HID/HIP selection is not scientific completion. The historical
5NBX guided choice demonstrates the software path only, not biological validation.

Histidine-state sensitivity option: when independent evidence cannot distinguish
the two neutral states, the application may create retained HIE and HID receptor
variants rather than force a guess. This becomes a real sensitivity analysis only
when every selected docking box whose interaction region contains or approaches
the ambiguous residue is docked against both variants using identical ligands,
conformers, seeds, and engine settings. Unaffected boxes are not duplicated. The
GUI must show the additional work before execution, run variants sequentially
under the one-active-job rule, and keep results grouped by receptor-state hash.
Reports compare pose/cluster placement, interaction fingerprints, and ranking
stability and label conclusions as robust or sensitive to histidine state; they
must not interpret a small score difference as proof of the biologically correct
tautomer. Multiple ambiguous residues require a declared variant cap or a
one-residue-at-a-time design rather than uncontrolled 2^n expansion. HIP is not
included without separate evidence for the charged state. Initially this analysis
informs selection of one receptor for the single-receptor protocol; a reusable
multi-receptor ensemble protocol remains a later feature.

This sensitivity path adds a conditional workflow stage, **Receptor-state
comparison**, after the affected comparison docks and before final protocol
approval. The application, rather than the user, first determines which selected
boxes are geometrically affected, expands only those docking tasks, and tracks
both receptor variants as one comparison set. When the runs finish it presents a
side-by-side synopsis of pose/cluster agreement, interaction changes, and ranking
stability. If the result is materially unchanged, the stage records that the
docking conclusion is robust to the tested neutral histidine state and asks which
single prepared receptor to retain for the current protocol. If the result changes
materially, the stage issues a blocking scientific warning and requires the user
to choose a justified receptor state, revise the box/receptor, or stop; it must not
silently select the variant with the better Vina score. The report retains both
tested states, the affected boxes, the comparison outcome, and the final rationale.
This conditional stage is absent when no ambiguous residue can influence a
selected docking region.

An expert override remains available at the initial ambiguity checkpoint and at
the receptor-state comparison checkpoint. The user may explicitly choose HIE or
HID (and HIP only when separately justified), provide or select the supporting
rationale, and continue with that single receptor without running the recommended
sensitivity branch. The GUI must clearly state which comparison work will be
skipped, require acknowledgement when the choice is not supported by retained
evidence, and record the selected state, residue identifier, user rationale,
available evidence, skipped variants, affected boxes, and timestamp in the audit
trail and final report. An override is a documented scientific decision, not an
automation result, and must never be applied silently to other ambiguous residues.

Deposited-chemistry preservation policy (2026-09-24): when an mmCIF explicitly
identifies a modified polymer component and its chemical-component/parent mapping,
coordinates, connectivity, or local structural evidence are compatible with that
identity, the GUI warns that the docking model contains deposited modified
chemistry and recommends **Keep deposited chemistry**. When the preparation
backend accepts that representation and creates a valid receptor, this is a
non-blocking retained notice rather than a required decision. It does not treat
the warning itself as a reason to normalize the residue. Replacing it with the
parent standard residue is a separate, explicit molecular-model change requiring
approval and stated consequences. Missing or contradictory identity evidence,
incomplete required atoms, an ambiguous template tie, or lack of a supported
preparation template remains a stop rather than an automatic acceptance.
Force-field histidine labels such as HIE/HID/HIP are not interpreted as depositor
CCD component codes.

Study setup is now persisted before preparation starts and rendered read-only
thereafter. Reopening a current study restores its receptor, output location,
site mode, exact ligand identity, detector and public-PDB evidence policy from
the authoritative study record rather than window preferences. Older completed
studies reconstruct the available setup fields from retained source/preparation
artifacts and identify that provenance in the GUI. The Study menu now provides
New study and Open study actions; switching replaces the active workspace and
viewer while retaining the single scientific application host.

## Outcome and scope

A scientist must be able to start an empty study, make every supported scientific
choice when it becomes relevant, review its evidence, and finish the appropriate
protocol and screening reports without answering a terminal prompt. A required
decision stops the active run; saved pending state provides recovery after an
interruption but is not presented as a planned pause-and-resume feature. A
completed-study viewer is insufficient acceptance evidence.

Cover three routes: exploratory protocol creation (pocket-, ligand-, residue-,
or whole-protein-defined), experimental bound-ligand control and calibration,
and screening with an existing reusable protocol. Continue directly from a new
protocol into screening when requested. All routes use one active scientific
job and one authoritative study shared by every window.

Flexible docking remains after this release. Retain and expose experimental
rotamer, backbone, occupancy, and B-factor evidence now. This evidence informs
rigid-site suitability; it does not automatically select flexible residues,
delete chains, or establish that a conformation is flexible.

Preserve existing scientific report layouts, PoseEdit-style local interaction
diagrams, PLIP implementation, scientific colors, and portable protocols. Add
the records required to explain newly exposed choices using the existing report
sections. Branding follows the separate visual identity plan after functional
acceptance. Docked structures and derived interaction data remain local.

## Verified baseline and corrections to earlier assumptions

- `gui/workflow_panels.py` offers local/RCSB input, residue-name ligand detection,
  pocket/ligand site modes, detector selection, and related-PDB search.
- `services/preparation.py` wraps the Bash engine noninteractively. It explicitly
  disables component-removal prompting and permissive unmatched-residue removal.
  A failure here needs an intervention mechanism, not a checkbox that silently
  enables deletion for an entire run.
- `decisions.py` already defines options, consequences, evidence references, and
  approval records. Extend this foundation.
- `application.py` currently handles `select_pockets` and completes the waiting
  job on resolution. That behavior cannot serve an arbitrary mid-stage decision.
- `workflow.py` defines the site-guided route; control/calibration and the full
  screening lifecycle need explicit transitions. Unknown stage completion must
  not imply completion of a larger workflow.
- `protocol_finalization.py` requires persisted pocket approval and checks box
  hashes. Preserve and generalize those checks.
- `test_gui_full_journey.py` exercises widgets and a real host with substitute
  preparation/screening executables. It is useful integration coverage, but
  does not establish scientific-engine or real OpenGL end-to-end acceptance.
- Additional CLI decisions include histidine template/state and scope, ligand
  chemistry verification, manual override rationale, and provisional chemistry
  review. These belong in the plan alongside the previously identified gaps.
- The documented 0.10-to-0.0 cavity retry belongs to fpocket. It must not become
  a P2Rank threshold or imply that the two detectors' scores are interchangeable.

## Decision coverage inventory

Create a checked-in coverage registry during slice 1. Each entry records source
prompt or equivalent noninteractive gate, trigger, current implementation status,
GUI surface, host handler, saved inputs/evidence, continuation, invalidation
rules, and associated tests. Include Bash prompts and error/override branches,
not only Python `input()` calls. Mark superseded presentation prompts explicitly.

| Point in the run | Required interaction and outcome | Current coverage / planned work |
| --- | --- | --- |
| Starting route | Exploratory creation, bound-ligand control, or existing-protocol screen | Launcher currently offers site-guided exploratory creation; add the other routes |
| Receptor input | Local file or explicit PDB retrieval; inspect source and retained provenance | Basic input exists; persist setup drafts and expose the actual model/chains used |
| Ligand identity | Discover ligands; select exact model/chain/residue/insertion code/altloc instance | Current residue-name selection can group multiple instances; extend throughout preparation/control |
| Repeated chains/sites | Show equivalence evidence and RMSD, let the user choose sites | Preserve assemblies by default; similarity must not delete a chain or site |
| Ligand chemistry | CCD or supplied SDF verification; review ambiguity, override rationale, provisional 2D chemistry approval where supported | Extract control-script decisions and retain chemistry/coordinate separation |
| Preparation policy | Explain backend/repair policy and accepted defaults | Expose existing supported settings in expandable detail; save the exact policy |
| Preparation intervention | Histidine state/template and scope; exact proposed unmatched-component removal; decline or supply corrected input | Histidine state/scope and Stop implemented with durable same-job continuation and archived attempts; exact component-removal inventory remains open and failure-closed |
| Pocket detection | Detector and search/centering policy, candidate count, fallback choice and fpocket retry | Basic detector selection exists; add policy and conditional interventions |
| Experimental evidence | Search status, exact versus homolog observations, evidence basis, explicit homolog-use authorization when required | Review exists; add distinct authorization linked to evidence actually used |
| Region definition | Predicted sites, exact bound ligand, explicit residue/group, whole protein; review numeric box geometry | Pocket/ligand modes exist; remaining definitions require backend-to-GUI coverage |
| Region approval | Select one or several regions; review consequences and rationale; approve exact geometry/evidence | Existing pocket approval is the starting point; generalize to all region sources |
| Ligand ensemble | Defaults or custom pH, conformers, base seed, force field, pruning, tautomers, charge model | Partial settings; expose and validate the full supported set |
| Control calibration | Initial box/settings; sampling/ranking/seed evidence; guided next tier or manual tier; accept/reject continuation | Add service extraction, progress and review screens |
| Protocol finalization | Review exact settings, authority, receptor changes and regions; authorize exploratory use where needed | Exploratory path exists; add control-backed finalization and persist authorization uniformly |
| Existing protocol | Verify bundle/hashes/authority; show preparation warnings and recorded versus current software | Integrate as an independent starting route with locked parameters |
| Screening | Input library, analysis options, preflight/work estimate, run authorization, compound failure policy | Existing controls require parity audit, persistence and multi-site validation |
| Failure/recovery | Cancel, correct input, retry only eligible work, inspect partial outputs, resume interrupted study | Extend common recovery to every branch; never convert failure into approval |
| Results | Exact pose/cluster selection, interactions, report/synopsis, export | Preserve current review; prove identity and stale-render handling across all routes |

File choosers, opening reports, and selecting explanation detail are presentation
actions. They do not all need approval dialogs. Scientific parameters are saved
configuration; decisions that require review are durable stops. Every CLI prompt
must be accounted for, but its terminal presentation need not be copied literally.

## Shared architecture

### Decisions and continuation

Keep `StudyController`, `JsonStudyStore`, the serialized host, services, and
viewer interfaces. Do not add a second workflow manager inside the GUI.

Extend decision records with a versioned, kind-specific payload and a retained
continuation descriptor: stage, checkpoint, attempt, validated input hashes,
configuration revision, and evidence references. Use typed payload validation for
residue identities, box geometry and parameters instead of encoding arbitrary
data in option strings. Presentation drafts may be saved separately from accepted
configuration so reopening does not lose work or silently accept it.

Resolution validates the response against the exact pending decision and its
dependencies, records it once, then schedules the declared continuation. It must
not automatically finish the entire stage. A queued continuation is persisted
before execution; duplicate requests or reconnects cannot run it twice. A crash
between recording the answer and starting the continuation is reconciled on
restart. An interrupted process needs output validation before reuse.

Represent pending, resolved, declined/cancelled, and superseded decisions, with
explicit migrations for existing JSON. Retain old approvals as history when
their dependencies change; do not delete them or reuse them as current authority.
Changing an upstream receptor, ligand identity, chemistry, region or settings
invalidates dependent results/approvals. Moving the camera, changing visible
evidence, or revisiting a stage does not.

### Scientific engine boundary

Preparation/control scripts produce a versioned structured intervention artifact
and a documented exit outcome when user input is required. The host validates
it and creates a decision; no GUI code parses prose logs or sends canned answers
to stdin. Resume from a checkpoint where safe. If the engine requires a rerun,
record a new attempt in a separate output location, validate its input hashes,
and reuse only verified products. Do not overwrite the previous evidence.

Extract preparation interventions and calibration orchestration into small
services, retaining existing scientific engines and their sequence. CLI and GUI
must call the same validation/policy functions. Use a temporary compatibility
adapter while extracting; keep established noninteractive CLI behavior tested.

### Scientific authority

Execution success, study completion, and scientific authority remain separate.
A control pass is determined by the existing evaluator and retained evidence.
The user can approve an exploratory route, but cannot turn a failed control into
a passing one by clicking Continue. Guided calibration recommendations describe
sampling, ranking and seed evidence and require the existing intended user choice.
Store each tier's settings, results, timing and chosen next action.

Keep viewing homolog ligands distinct from authorizing their use to define the
protocol. Preserve the selected evidence basis and required approval in the
report/bundle. Missing or failed searches are not reported as absence of evidence.
If a user declines homolog use, retain the review evidence and permit only region
choices that do not depend on that authorization.

## GUI behavior through time

The workflow rail is a projection of host state. Before execution it shows the
next inputs; while running it shows progress and the current operation; when
paused it shows the actual question and associated evidence; after completion
it shows the retained inputs, transformations, choices and outputs for that stage.
Every selectable stage therefore has useful content in a fresh or completed run.

Use route-appropriate steps: control studies include chemistry and calibration;
existing-protocol screening starts with protocol review. The six existing stages
remain the exploratory route's familiar structure. Revisit completed steps
without re-running them. An explicit revision action explains which downstream
products become stale before changing accepted scientific inputs.

Present one clear current action, a short reason, and consequences beside a large
figure/PyMOL canvas. Put full evidence in an accessible detail window, including
double-click access to truncated table content. Logs are hidden by default.
Scientific Workflow Detail retains Concise/Guided/Teaching/Technical presentations;
necessary decision consequences stay visible. Explicitly enabled automation has
a persistent indicator and a recorded scope; model changes remain explicit.

Decision figures show report panels; Interactive structure selects the associated
3D scene. Preserve rotation and protein-level zoom for the same receptor, recenter
selected boxes without changing scale, and reset only on explicit request or a
new structure requiring initial framing. Use consistent colors and selection-driven
ligand visibility. Detach/fullscreen shares the same viewer and study. Embedded
mouse actions must not open another PyMOL interface. Retain the companion fallback
without reintroducing native activation wrappers or duplicate launches.

Use bounded panel sizes, scrolling and optional detail windows. Verify the complete
workflow at 1280×800 and 1920×1080, high DPI, resizing, stage switching and fullscreen.
Keyboard users must be able to reach choices and open the same evidence details.

## Implementation slices and acceptance gates

Implement in this dependency order. Each slice should be independently reviewable
and include its migrations, focused tests and a short status update in the registry.

| Slice | Main work and likely ownership | Acceptance gate |
| --- | --- | --- |
| 1. Inventory and baseline | Registry from run/create-protocol/control/calibrate/screen and prepare.d; map current host/UI/tests; capture baseline reports/bundles | Every interactive prompt and consequential noninteractive gate has a disposition; new-study reproduction recorded |
| 2. Durable decisions | Extend decisions/models/state/application/workflow/host; add typed handlers and continuation validation | Resolve/decline/restart/stale evidence/duplicate command tests; multiple decisions inside one stage; existing pocket approval still works |
| 3. Chronological presentation | Stage view models and reusable decision panel; saved setup/configuration drafts and historical stage summaries | Start empty, stop for a decision, reopen and continue with no terminal; stage revisits do not mutate science or move windows |
| 4. Receptor and ligand identity | Extend bound_ligands and preparation/control selectors; exact identities and source-to-prepared mapping | Same ligand name in two chains selects only the chosen instance; insertion codes/altlocs/ambiguous mappings tested; input provenance retained |
| 5. Preparation intervention | receptor.sh structured stops, preparation service resume, histidine and component-removal review | Both accept and decline tested against exact component inventories; no blanket permissive removal; changed input invalidates prior response |
| 6. Detection and experimental evidence | Detector-specific retry/fallback, search outcomes, evidence basis and homolog approval | P2Rank failure differs from zero candidates; fpocket relaxation applies only to fpocket; rejected homolog authorization cannot enter finalization |
| 7. Complete region review | All region sources, numeric box preview/edit, multi-site approval and dependent invalidation | Exact approved geometry matches viewer/report/bundle; separate sites stay separate and run sequentially; no automatic chain deletion |
| 8. Exploratory settings and bundle | Full ensemble settings; saved exploratory authorization; finalization from approved preparation | Compare CLI/GUI normalized parameters, receptor/box hashes, evidence and report sections; changed settings cannot reuse stale approval |
| 9. Control chemistry and calibration | New control service and GUI route; CCD/SDF/provisional review; tier-by-tier continuation; passing bundle | Experimental coordinates withheld from generation; ambiguous chemistry pauses; failed tier offers correct choices; restart between tiers; failure never grants screening authority |
| 10. Protocol reuse and screening | Independent import route, locked settings, preflight, explicit start, site/compound queue and failure policy | CLI-created bundles work in GUI and converse; partial failures retained; cancellation/retry causes no duplicate site/compound jobs |
| 11. Full acceptance and release docs | Real runs, platform/lifecycle checks, coverage closure, updated roadmap/guides and visual identity slice | All supported choices reachable, reports consistent, no unexplained prompts, orphan processes or crashes; limitations stated for untested platforms |

Slices 2–3 are the foundation. Implement the first concrete intervention through
slice 5 before propagating the pattern widely. Complete the exploratory route
through slice 8 as the first usable milestone, then control and protocol reuse.
Do not call the full GUI complete at the exploratory milestone.

Avoid putting new policy branches in the already large `gui/desktop.py`. Keep it
responsible for routing intentions and composing panels. Proposed modules, added
only when their slice needs them, are `decision_handlers.py`,
`gui/decision_panel.py`, `gui/workflow_view_model.py`,
`services/preparation_interventions.py`, `services/control.py`, and
`services/calibration.py`. Extend existing service modules where responsibility
already fits. These are internal components, not a new collection of competing
standalone pipeline scripts.

## Verification matrix

Use deterministic small fixtures for branch coverage and a separate opt-in suite
for real engines and OpenGL. Keep private structures local and out of committed
test fixtures. Obtain public fixtures using retained provenance when needed.
The concrete public examples, chronological paths and acceptance artifacts are
defined in [Real GUI workflow validation](gui-real-workflow-validation.md).

Required journeys:

1. Empty study → PDB retrieval → multiple ligand instances → selected site →
   review → exploratory bundle → screening → final report.
2. Local ligand-free receptor → P2Rank candidates → approve several sites →
   sequential screening; equivalent chains remain intact.
3. No predicted pocket at an experimental ligand location → ligand-defined site,
   with conformational/rotamer evidence and explicit homolog-use decision.
4. P2Rank unavailable/fails versus succeeds with no usable candidates; fpocket
   fallback and threshold retry accepted and declined separately.
5. Histidine intervention and unmatched-component removal accepted/declined,
   changed-source rejection, corrected-input recovery, report provenance.
6. Experimental control with verified chemistry → calibration pass → bundle →
   screening; a failing control follows guided/manual retry and stop paths.
7. CCD unavailable or chemistry ambiguous → supplied SDF/provisional review as
   supported; declined review cannot proceed to docking.
8. Existing control/exploratory bundle import, damaged hash rejection, locked
   settings, partial compound failures and stop-on-error behavior.

For every durable decision test closing/reopening while pending, double-submit,
stale revision or evidence, decline, and a crash after response persistence but
before continuation. Test cancellation during execution independently of declining
a decision. Explicitly test changed upstream input after prior approval.

Compare scientific equivalence rather than byte-identical PDF output: normalized
settings, identities, hashes, authority, decision history, site labels, figure
source manifests and report sections. Inspect rendered reports for layout and
the real GUI for viewer behavior; offscreen widget tests cannot prove either.

Real acceptance records must identify OS, runtime, engine versions, fixture,
choices made, outputs and result. macOS embedding evidence is not Windows/Linux
acceptance. On unsupported/unavailable runners, record the gap and constrain the
release claim instead of declaring success from mocks.

## Completion and handoff

The release gate is a coverage registry with no unexplained supported decision
gaps, real chronological acceptance for all three routes, restartable decisions,
CLI/GUI scientific equivalence, and usable reports/viewer layouts. A failed
scientific case may pass the software test when it stops correctly and explains
the available next actions.

Each implementation handoff specifies registry rows, owned files, existing
contracts, fixtures, test commands and remaining limitations. Update the status
of completed slices without rewriting historical test claims. Estimate work per
slice after its baseline is measured; do not promise a completion date from the
number of widgets involved.

References: [Design philosophy](design-philosophy.md),
[guided workflow](guided-workflow.md), [architecture](gui-architecture-plan.md),
[implementation roadmap](gui-implementation-roadmap.md),
[visual identity](gui-report-visual-identity-plan.md), and
[data privacy](data-privacy.md).
