# GUI implementation roadmap

### Scope-control rule (2026-09-24)

New interface ideas go first to the
[GUI idea backlog and implementation gate](gui-idea-backlog.md). Recording an
idea does not add it to the active milestone. Unless a proposal fixes scientific
correctness, safety, data loss, a reproducible crash, or a demonstrated failure
of the current rigid-receptor acceptance path, preserve it for later and finish
the chronological vertical workflow first.

### Decision-completeness plan (2026-09-21)

The [complete interactive GUI workflow plan](gui-decision-completeness-plan.md)
defines the next implementation sequence and acceptance gates for every supported
user-input point. It extends the current exploratory route to preparation
interventions, exact ligand identities, detector-specific retries, evidence
authorization, all region modes, control/calibration, and protocol reuse.
The current chronological navigation and fixture-backed journey tests do not
establish complete interactive or real-engine coverage. Use that plan for this
work; flexible docking remains after the complete rigid-receptor GUI release.

Status: active implementation roadmap, updated 2026-09-20. The desktop client
targets Python 3.12/PyQt6. The existing PyMOL companion remains the production
fallback; an isolated source-built embedded viewer is now the integration direction
under validation. This document refines the existing architecture plan and takes precedence
for toolkit selection, process ownership, viewer integration, and sequencing.

### Current addendum: embedded viewer and visual identity (2026-09-20)

The isolated [embedded PyMOL proof of concept](../../embedded-pymol-poc/README.md)
uses an actual upstream `pmg_qt.pymol_gl_widget.PyMOLGLWidget` in a PyQt6 window,
with source pinned to `5e8bfca5a7f5dc4d5e7f84fa1d15af707cc86e69` (3.2.0a0).
On this macOS arm64 machine, two complete runs passed 30 GUI/OpenGL checks each:
receptor, surface, CGO boxes, table selection, mouse navigation, real atom picking
back into Qt, repeated resizing/reloading, and shutdown. Process monitoring found
no child viewer processes or survivors. This is local feasibility evidence, not
production integration or cross-platform acceptance. Production code and the
existing companion environment were not changed by the prototype.

The first production integration slice is now implemented behind the existing
viewer coordinator. The desktop launcher accepts `auto`, `embedded`, `companion`,
and `none` backends; `auto` uses the embedded backend only when compatible PyMOL
and widget imports exist in the GUI runtime. A genuine **Interactive structure**
tab hosts the widget, while the companion remains available without an empty
pseudo-viewport. A real production-window smoke check loaded the retained report
scene, rendered a nonempty 2160×956 framebuffer, and stopped the engine and timer
on close. This does not yet satisfy packaging or cross-platform release gates.

Next: integrate behind the viewer abstraction while retaining report-view reset,
selection identities, explicit approvals, the separate scientific host, and the
companion backend. Gate release on lifecycle/scene regression tests, long sessions,
multiple displays/DPI, and supported-platform packaging. Detachment/reattachment
and full expert PyMOL controls are separate unverified work. Do not restore the
failed native-window activation/wrapper approach. Earlier companion-only task
descriptions below describe the existing baseline, not a prohibition on embedding.
Flexible docking remains after the first complete GUI version; evidence gathering
and review remain in scope now.

The **Compare Business Plus** decisions and supplied PNG references are retained
in the [GUI and report visual identity plan](gui-report-visual-identity-plan.md).
Schedule its bounded asset, GUI-theme, report-footer, and figure-attribution slices
after the viewer contract is stable. Use restrained navy/teal GUI accents and flat
existing artwork; preserve scientific report layouts and scientific color meanings.
Only small logo/version/page attribution is planned for reports. No styling has
been implemented by this planning update.

Implementation status (2026-09-12): task 01 is implemented by the read-only
`docking-universal runtime-inventory` command and recorded in the
[2026-09-12 macOS arm64 audit](runtime-inventory-audit-2026-09-12.md). Task 02
has a working restricted bridge for controller-driven selection, structured
residue picking, box, camera, real fpocket layers, GUI-thread dispatch and
relaunch replay. Its [spike record](pymol-interaction-spike.md) retains the
remaining literal human mouse-click acceptance check.

The related-PDB stage now also retains the prepared receptor as its atom-level
baseline and writes a central conformational-evidence artifact. It separates
chi/side-chain changes from backbone displacement, preserves ligand context,
counts repeated observations, and can flag a current side chain geometrically
consistent with occluding an aligned deposited ligand. These records are GUI
review suggestions only and never automatic flexible-residue selections.
The resulting primary warning now addresses site validity directly: the known
site may be inaccessible in the prepared conformation, making rigid docking an
invalid test even when the location is experimentally supported.

The pocket-engine boundary now discovers fpocket and P2Rank by executable
capability, requires a Java runtime for P2Rank, and normalizes P2Rank prediction
tables into engine-labeled, non-automatically-selectable candidate records.
Execution wiring and the comparative pocket-review controls remain the next
P2Rank slice; engine scores will remain independent rather than being collapsed
into a synthetic rank.
The adapter now also writes P2Rank's explicit fpocket-rescoring dataset contract
and normalizes rescored output while retaining both the original fpocket rank
and the P2Rank rank. The remaining work is launching that plan through the job
service and attaching its retained output to the pocket-review candidates.
The intended product ordering is now P2Rank primary, fpocket fallback, and
fpocket-plus-P2Rank-rescoring as an advanced comparison. The live default will
change only after P2Rank output-to-box construction and retained report/bundle
provenance are implemented and tested end to end; existing fpocket protocols
will not be reinterpreted.

Task 03 initially selected Qt 5/PyQt5. The source now imports PyQt6 through a
single binding module, and the GUI and PyMOL runtimes have separate Python 3.12
environment contracts. The launcher also gives the sole serialized application
host the established scientific environment's interpreter, keeping GUI, PyMOL,
and scientific dependencies in three explicit process boundaries while they
continue to operate on one study and one active run. The rationale and remaining platform packaging checks are in the
[toolkit decision](gui-toolkit-decision.md). Tasks 04-08 now have an implemented
foundation: revisioned/locked state, a sole serialized JSON-lines host,
idempotent approvals, crash reconciliation, one application-wide scientific
job slot, explicit stage transitions, viewer-neutral identity/selection/message
contracts, a supervised PyMOL adapter, and a dockable desktop connected to the
host for explicit pocket approval. The desktop also treats a terminated
application-host process as unavailable,
disables scientific mutations, displays a persistent retained-study warning,
and can restart the host against the same durable study. PyMOL failures use the
existing reconnect path and replay the retained report session and current pose
selection. The workspace poll also detects an exited PyMOL process before the
next viewer action, marks the shared viewer state failed, and exposes the
reconnect control. Preparation and pocket-review services now
register the receptor and pocket coordinate artifacts needed for required
PyMOL review; choosing a table row can update the viewer box without approving
the scientific decision. The retained PyMOL session used to create the report
figure is now the primary live view; reopening or resetting the visual panel
reloads that hash-verified session instead of displaying the static image.
Decision review exposes both a compact, selection-aware synopsis and the
complete preliminary pocket-review report containing all candidate positions.
A graphical study launcher now removes the command-line prerequisite from
desktop startup. It lists valid persisted studies newest-first, reopens their
exact identities, and creates uniquely identified studies only through the
application host. Closing the launcher starts no run, and reopening an existing
entry never creates a duplicate job.
A noninteractive service boundary invokes the existing bash receptor-preparation
engine with explicit settings and disables model-changing removal. Task 09 is
now wired for the initial site-guided workflow: the desktop can create a study,
launch receptor preparation and pocket detection asynchronously, cancel the
running stage, discover existing preliminary reports without changing them,
pause at the durable visual pocket decision, and finalize the approved retained
preparation into the existing report and `.duprotocol` formats without rerunning
preparation. The finalization panel exposes the protocol settings currently
available in the protocol CLI, requires separate explicit exploratory-use
authorization, retains process logs, supports cancellation/retry, and registers
hashes for the final protocol, PDF, and bundle. The portable bundle also searches
the separate retained preparation root so related-PDB and structural-ensemble
evidence are not lost during the GUI transition. Application exit during work
offers cancellation or return to the run; silent background continuation is not
allowed. The first task-10 screening slice is also implemented: the host verifies
the registered bundle hash, reads all docking parameters exclusively from that
locked protocol, previews compounds × conformers × seeds × sites, and launches
the existing noninteractive screening workflow as one cancellable serialized
stage. Compound failures retain partial outputs. A docked results table exposes
completion status, site/job counts, best retained ranking score, cluster count,
the complete screening report, and retained pose sessions while keeping the
scientific-limit warning visible. Full in-application pose/interaction control
now includes a cluster-synopsis versus expanded-review selector and an exact
retained-pose table with cluster, score, representative status, seed, conformer,
and model provenance. Pose selection clears the prior diagram before checking
the pose-keyed local cache. Cache misses now pass through the application host's
single serialized scientific-job slot, run local PLIP, require the approved
renderer policy and provenance manifest, register the exact-pose artifact, and
refresh only the still-selected pose. The installable approved renderer now
packages its local browser assets, enforces the zero-collision and provenance
audits, and writes 3× content-cropped output. No legacy or network renderer is
used as a fallback. Flexible-residue docking remains future integration work.

The runtime inventory and Screening Results panel now expose a composite local
interaction-renderer readiness check with separate Node.js, Playwright,
Chrome/Chromium, and bundled-asset observations. Missing components prevent only
new cache-miss generation and produce an actionable message; retained cached
scientific evidence remains reviewable.

The interaction review surface retains the full-resolution rendered image in a
scroll area and provides Fit, 50%, 100%, and 200% inspection levels. Expanded
review keeps the exact pose, cluster, and score visible above the diagram, and
the loading transition clears both the displayed pixmap and its full-resolution
source before another pose is requested.

Expanded pose review now synchronizes its exact materialized SDF with the
already-open live PyMOL companion through the restricted `show_review_pose`
operation. The bridge replaces only `du_review_pose`, preserving the receptor
and report session; visual synchronization never implies approval. A visible
button permits explicit resynchronization, and automatic synchronization occurs
when a pose is selected while PyMOL is connected. The all-pose table supports
cluster filtering and preserves compound/pose selection across periodic study
refreshes without relaunching scientific work.

The approved PoseEdit-style renderer is also the preferred backend for the
existing PDF report's selected cluster and control interaction figures. This is
a renderer substitution only: report structure, captions, ordering, requested
panel dimensions, and pagination remain governed by the existing report code.
Per-image manifests and logs distinguish approved output from the explicit
native SDF compatibility path.

Architectural consolidation has started with a shared `ActiveStudySession`.
Every desktop window for the same store/study pair now observes one in-process
session containing the latest authoritative `StudyState`, typed artifact
queries, active-operation status, viewer status, and recoverable
compound/site/cluster/pose presentation selection. The session never writes
scientific state: approvals and workflow mutations remain exclusive host
operations. The screening-results surface is the first migrated consumer;
compound, cluster, and exact-pose selections can be mirrored between windows
without changing the retained scientific record.

The first multi-window consistency gate is also implemented. Cluster and exact
pose changes propagate through `ActiveStudySession`, secondary windows switch
to the matching synopsis/expanded mode, and cached diagrams may be displayed
there without resubmitting scientific analysis. A mirrored cache miss waits for
the originating operation's retained artifact instead of launching a duplicate
PLIP job. PyMOL connection, report-view availability, and synchronization
status are likewise session events visible to every window; only a window with
the configured viewer coordinator may issue viewer commands.

The Results Review surface now exposes this architecture directly. It is a
named application-owned dock with explicit **Detach review** and **Return to
workspace** controls. The same widgets and `ActiveStudySession` remain active
while it floats, and its header shows the shared compound/site/cluster/pose as
recoverable presentation state. Detaching, redocking, or closing the surface
does not clone a workflow, submit analysis, approve evidence, cancel a job, or
write the scientific record.

The main window now has the first concrete Study Workspace shell: a persistent
six-stage Scientific Workflow navigator, an honest central Structural Review
surface for the external PyMOL companion, shared-selection context, stage-local
left controls, right-side evidence/detail docks, and bottom logs and retained
artifacts. Only the selected stage's setup/finalization/screening controls are
shown, while evidence and mandatory decision warnings remain independently
available. Normal desktop launch opens maximized; explicit full-screen mode and
saved dock geometry remain supported. Refresh polling is owned by the visible
workspace lifecycle so a closed window cannot continue reading or acting on a
study.

The navigator is state-aware rather than a static menu. It marks completed and
current stages and presents one persistent **Next required action** explanation.
Pending pocket review always takes precedence over job activity so a waiting
scientific decision cannot be mislabeled as background computation. The guide
does not auto-approve, skip, or hide decisions; it only derives presentation
state from the same persisted study record used by the CLI and application
host. Flexible docking remains a post-GUI feature, although its future evidence
artifacts and residue identities remain compatible with this workflow shell.

A full widget-driven journey test now crosses the production application-host
boundary and its separate scientific Python environment. It creates and
reopens one study through preparation, P2Rank/fpocket selection, explicit region
approval, report and `.duprotocol` finalization, sequential screening, and
results recovery. External scientific executables are deterministic fixtures,
but GUI signals, JSON host commands, asynchronous jobs, persistence, report
publication, bundle reuse, and restart behavior are production paths. This test
also established that `pocket_engine` is part of the versioned preparation
command contract; the host now accepts and validates the GUI's explicit engine
selection.

Per-study draft forms now survive a normal GUI restart through presentation-only
Qt settings. Receptor and output paths, detector choice, protocol parameters,
and screening options are restored; explicit exploratory-use approvals and a
previous workload preview are deliberately cleared and must be renewed. The
workflow navigator also reports the active stage, uses indeterminate progress
when an external engine cannot provide an honest percentage, distinguishes a
decision wait from computation, and provides direct access to complete logs.

The PyMOL companion lifecycle is now explicit and shared. `ActiveStudySession`
publishes disconnected, connecting, connected, and failed states with retained
failure detail; all windows render the same state. Opening preserves report-view
hash validation, reset reloads that exact retained session, and a failed viewer
offers reconnection through the existing supervised adapter. Reconnection
replays registered structures, pockets, selections, box/view state, the report
session, and any exact retained review pose without launching docking or PLIP.
If an exact pose was selected before connection, the workspace synchronizes it
after connection only when its materialized local SDF already exists. Viewer
command failures transition to failed state rather than implying that PyMOL is
still connected.

Results Review presentation is now extracted into a reusable
`ResultsReviewPanel`. The component owns its scientific warning, compound and
pose tables, cluster/expanded controls, local-renderer readiness, interaction
canvas, zoom, and visible actions, but deliberately has no study store, host
client, viewer coordinator, or workflow mutation authority. `StudyWindow`
currently acts as its controller through compatibility aliases and narrow Qt
signal connections; subsequent slices can move retained-results projection and
pose-loading coordination behind dedicated models without rebuilding the UI.

The retained-results projection has now moved behind a Qt-independent
`ResultsReviewModel`. It parses compound manifests, scores, cluster summaries,
interaction-diagram metadata, pose inventories, and pose-keyed cache precedence
into immutable presentation records without holding the study store or invoking
the host or viewer. The desktop controller is consequently limited to rendering
those records and coordinating explicit user actions. Pose-loading requests and
stale-completion state remain in the controller for the next extraction slice.

Exact-pose loading coordination is now separated into
`ResultsReviewController`. It owns only transient pose keys and analysis
identity, chooses among cached display, mirrored-window waiting, missing-host,
missing-renderer, and new-request outcomes, locates matching retained completion
artifacts, and rejects stale completions. It neither renders Qt widgets nor
executes scientific tools; `StudyWindow` translates its decisions into visible
states and sends the explicitly required request through the application host.

The preparation, protocol-finalization, and locked-screening forms are now
passive `StudySetupPanel`, `ProtocolFinalizationPanel`, and
`ScreeningSetupPanel` components. They own controls and typed/presentation form
state and emit user-intention signals, but have no store, host, viewer, or study
authority. A separate `WorkflowNavigationController` now owns only the
visibility policy for those stage docks. `StudyWindow` retains host routing and
workflow validation while compatibility aliases preserve the established GUI
and test contracts during incremental migration.

Scientific Workflow Detail is now a dedicated presentation-only
`ScientificDetailPanel`. It owns Concise, Guided, Teaching, and Technical event
projections plus an explicit **Show full details** action. Its selected level is
shared across sibling windows through `ActiveStudySession` but is never written
to the scientific record. Mandatory decision consequences and automation
warnings remain outside the component in the workspace shell, so closing the
dock or choosing Concise cannot conceal them.

Top-level presentation lifecycle is now owned by a narrow
`WorkspaceWindowController`. It restores and saves geometry/dock layout, starts
polling only while the workspace is shown, stops polling when hidden or closed,
and delegates each refresh to the window. It has no study store, host operation,
approval, or scientific-state mutation path. Active-job exit decisions remain
in `StudyWindow` until host-command routing is extracted as a separate boundary.

## Product contract

Docking Universal is scientific decision support. Structural review is a
required part of its interactive design. PyMOL Open Source is the baseline
viewer; its existing scientific functions should be preserved.

One application owns one active run. Multiple windows show that same run.
Scientific Workflow Detail defaults to Guided (CLI-level explanation), with
Concise, Teaching, and Technical presentations. Evidence and full logs remain
available in every mode. Hiding a panel does not approve a decision. Automation
requires an explicit scoped policy and an obvious persistent indicator.

The initial workflow is rigid, site-guided protocol creation. Flexible Vina,
experimental residue evidence, and enhanced engine controls are required future
features whose identities and contracts must be accommodated now. Existing
report layout, scientific content, and protocol compatibility are acceptance
constraints, not targets for redesign.

The visual panel opens live PyMOL at the retained report camera and scene. The
user may explore freely and can restore that exact scene with **Reset to report
view**. The static figure remains a report artifact but is not substituted for
the interactive viewer. During a decision, **Decision synopsis** summarizes the
current proposal while **Full synopsis report** opens the original complete
preliminary report so every candidate position remains rapidly reviewable.

## Verified starting point and corrections

The repository already contains StudyController, JsonStudyStore, JobService,
ProcessRunner, typed decisions/events, PocketReviewService, and retained
structural-ensemble evidence. Extend these; do not create a competing workflow
core. The current application is a foundation, not a complete GUI backend.

The main environment declares Python 3.9.23, PyMOL Open Source 3.0.0, RDKit
2023.09.6, PLIP 2.3.1, fpocket 4.2.2, Open Babel 3.1.1, molscrub 0.2.2,
PDBFixer 1.11, pycairo 1.27.0, Gemmi, Meeko 0.7.1, and ReportLab 4.2.5.
Its macOS lock includes Qt 5.15.8, PyQt 5.15.10, and Boost 1.82. Vina declares
Python 3.10 and Vina 1.2.7; its lock includes Boost 1.86. QuickVina-W has a third
environment with no explicitly requested Python. Thus two declared Python
versions do not mean only two environments, or a universal PyMOL restriction.

The installed PyMOL Qt wrapper examined on this Mac selects Qt 5/older bindings,
not PySide6. This supports isolating the existing runtime; it does not prove
that PyMOL's Python API is broken. The previous launch failure occurred without
an available display and cannot establish a normal desktop failure.

The pip snapshot's distribution name `pymol` and Conda's `pymol-open-source`
are not by themselves a conflict. Installation sources and solved package
metadata must be compared before claiming incompatibility.

Generated PML is useful for reproducible scenes, but does not alone provide
live two-way interaction. Returning a picked residue, camera state, or edited
box requires a bridge running in PyMOL's compatible Python environment.

An external PyMOL window is a companion window. It is not automatically an
embeddable/dockable panel. Application-owned panels can dock and detach; true
PyMOL embedding remains a separate feasibility question.

## Runtime design

```text
Desktop client (toolkit pending)
           | versioned local commands / events
Application host (main scientific Python; sole study-state writer)
           |                         |
Serialized scientific jobs       PyMOL adapter
           |                         | local structured messages
Existing preparation, Vina,      PyMOL process + small bridge
QuickVina-W, analysis, reports   (existing compatible Python/Qt)
```

The application host owns StudyController and JobService. The desktop owns
presentation and sends intentions to the host. All windows share one client
session. PyMOL owns rendering and picking; it cannot approve a protocol or
write authoritative study state.

The first transport is newline-delimited JSON over supervised process pipes.
The application host reserves stdout for framed messages and sends diagnostic
logs elsewhere. PyMOL's noisy stdout is only a log: use a dedicated localhost
connection with a per-launch token for its bridge. Network parsing queues work
for execution on the viewer's GUI thread through its existing Qt binding.
This is a design to prove in the spike, not an already implemented capability.

Messages contain protocol version, study ID, session ID, request ID, operation,
and payload. State-changing requests also carry the expected study revision.
Responses acknowledge applied or rejected work; events have ordered sequence
numbers. Reject unknown versions, stale sessions, invalid identities, and
duplicate mutations. On reconnect send an authoritative snapshot, then events
after its cursor. Coalesce hover/camera updates; preserve decisions and errors.

The transport accepts defined operations, never arbitrary remote Python or
shell execution. Generated PML remains an export/replay artifact. Use explicit
executable paths and construct each child's environment deliberately; avoid
leaking the GUI's QT_API, QT_PLUGIN_PATH, or PYTHONPATH into scientific tools.

Keep the scientific scheduler to one active stage across the application.
The live viewer and host are support processes and may coexist with that
stage. They must not occupy the scientific job slot. Independent ligands,
sites, and seeds run sequentially; an engine may use a bounded CPU allocation.

Closing a panel leaves the run intact. Closing PyMOL leaves a visual decision
pending and offers reconnection. Application exit while work is active must
offer cancel-and-exit or return to the run. Background continuation is outside
the first release. Unexpected host loss triggers child cleanup where possible;
restart reconciles process identity and marks uncertain work interrupted rather
than declaring it complete or automatically launching a duplicate.

## Selection and review contracts

Add a small viewer-neutral package, provisionally `docking_universal/viewer/`:

| Record / module | Responsibility |
| --- | --- |
| `identities.py` | Structure artifact/hash, model/state, chain, residue number as text, insertion code, residue name, atom name, altloc; assembly-copy identity when applicable |
| `selections.py` | Explicit atom/residue sets and typed operations: union, intersection, exclusion, within-distance, whole-residue expansion |
| `messages.py` | Versioned commands, acknowledgements, errors, selection/camera events |
| `pymol_adapter.py` | Launch, handshake, validate identities, map selections, recover viewer |
| `pymol_bridge.py` | Small Python-3.9-compatible implementation loaded in PyMOL only |

Use retained source-to-prepared and ensemble mappings. Atom indexes in PyMOL
are temporary lookup values, not persistent identities. Missing or ambiguous
mappings produce visible errors. A related-structure residue cannot silently
become a different residue in the prepared receptor.

Initial operations: load a registered structure, show a pocket layer, apply or
capture a named selection, focus selection, show box geometry, get/set camera,
export scene/session, and close. SelectionChanged returns explicit identities
and an origin/request ID to prevent table-to-viewer feedback loops.

Separate three states: visual highlight, proposed scientific selection, and
approved selection. Clicking or changing visibility updates the first or
second only. Approval references the exact decision, evidence hashes, region
geometry, and state revision. A later box/residue edit invalidates affected
approval and creates a new proposal; it never modifies a locked protocol.

Start box editing with validated numeric center/size controls and an immediate
3D box update. Add direct manipulation only after round-trip geometry is proven.
Retain coordinate frame and units. Reject nonfinite values and nonpositive
sizes. Camera motion never changes box coordinates.

## Implementation sequence and acceptance gates

Each row is a bounded implementation assignment. Its deliverable, tests, and
remaining limitations should be recorded before the next dependent row starts.

| Task | Deliverable | Acceptance / gate |
| --- | --- | --- |
| 01 Runtime inventory | Read-only probe of declared and installed environments, module/CLI versions, architectures, Qt bindings, required/optional tools and paths | Include transitive OpenMM, NumPy/SciPy, Pillow/Matplotlib and graphics libraries; ADFRsuite fallback, OS choosers, installation prerequisites; separate absence from incompatibility. No environment upgrades. |
| 02 PyMOL interaction spike | Minimal controller plus PyMOL bridge on the actual Mac desktop | Load an existing receptor and two candidate pockets; table/controller selection highlights exact residues; mouse selection returns identities; numeric box update agrees; viewer stays responsive; close/relaunch restores view. Check repeated residue numbers, insertion codes, altlocs, and spaced paths. |
| 03 Toolkit decision | Short recorded comparison of a separate PySide6 client and using the existing Qt 5 stack for a client | Verify packaging and Python requirements using actual candidate versions. Demonstrate windows/fullscreen, keyboard focus, DPI and multiple displays. Choose after task 02. If embedded PyMOL is essential, resolve it here before full UI work. |
| 04 Reliable application host | Serialized command dispatcher, exclusive run ownership, revision checks, reconnect, crash reconciliation | Concurrent launch attempts start one job; stale approval rejected; duplicate request creates one approval/job; interrupted process never reported successful. |
| 05 Selection contracts | Identity/mapping records, typed selectors, deterministic PyMOL translation | Round trips preserve identities across original/prepared/ensemble structures; malformed identifiers cannot become commands; proposal/highlight never approves. |
| 06 Production viewer adapter | Supervised bridge, handshake, acknowledgements, state replay, bounded traffic | Viewer crash and missing display remain explicit; stale events after restart ignored; no UI freeze or untracked process. |
| 07 Read-only desktop | Main workspace, candidate/evidence table, required visual review, detail selector, logs, reports, layout persistence | All windows show one study; Guided includes existing explanations; mandatory warnings survive Concise; hiding a window changes no science. |
| 08 Resumable protocol services | Preparation and protocol orchestration expose durable decisions, including model-changing fallbacks | No scripted answers to terminal prompts. Existing preparation order and explicit removal approval preserved; workflow resumes at the correct next stage. |
| 09 First complete GUI workflow | Receptor → preparation → pockets/evidence → preliminary report → visual review → approval → final report/bundle | CLI/GUI produce equivalent region choices, parameters, provenance and reports. GUI bundle usable by CLI. Multiple selected sites remain sequential. Restart during pending review works. |
| 10 Screening and enhanced Vina | Locked-protocol screen, parameter explanations, CPU/cost display, cancellation, two-level pose/cluster/interaction review | Locked parameters enforced by host; partial successes retained; completion and scientific authority stay distinct. Default interaction synopsis uses each distinct cluster's lowest-energy representative, ordered by energy. Expanded review exposes every retained pose and lazily generates a cached PLIP 2D diagram for the exact selected pose, with pose ID, score, cluster, seed, conformer, model, chemistry source, and interaction-source provenance. Pose selection clears the previous 2D image immediately and shows a keyed loading state; late completion for a pose that is no longer selected is cached but never displayed under the new pose. |
| 11 Flexible-residue evidence and docking | Ensemble evidence table/view, explicit residue approval, validated rigid/flexible preparation, Vina execution | Exact mappings, raw evidence and exclusions retained; no confidence-column/B-factor confusion; target-matched controls and separate protocol designation; no inferred QuickVina flexibility support. |

Task 02 is the first implementation expenditure after the small inventory.
If the round trip fails, investigate that concrete failure and revise the viewer
transport/host. Do not replace PyMOL or reduce visual review to static images
as an implicit fallback. Manual PML export is diagnostic support, not acceptance.

## Existing backend gaps to address in task 04/08

JsonStudyStore uses atomic replacement, which prevents partial JSON writes but
does not make load/check/save a transaction. The active-job guard is per study
and can race across controllers. Add exclusive host ownership and serialized
mutations, plus persisted revision validation; separate clients cannot write
the store directly.

JobService and pocket decision resolution currently mark the study completed
when their individual stage ends. Introduce an explicit workflow transition
table: stage completion advances or pauses the study; only final required
artifacts and stages complete the workflow. Validate required output artifacts
in the stage service even if a subprocess exits zero.

Decision resolution must validate any claimed automation policy against the
persisted enabled policy, allowed options and evidence revision on the host.
Do not trust a client-supplied policy ID. Molecular-model changes remain explicit
user decisions for the initial implementation, including flexible-residue sets.

Keep schema migration fixtures for existing state/bundles. Separate recoverable
UI/viewer preferences from scientific records so camera movement and window
layout do not rewrite scientific history.

## Future flexibility and performance

Reuse the central structural ensemble already retained by the pocket-evidence
pipeline. Future calculations consume its source structures, transforms, atom
records, and accepted mappings. They retain per-source B-factor normalization,
occupancy/altloc/missingness, rotamer/chi observations, ligand context and
eligibility separately. Missing evidence is unknown, not evidence of rigidity.

ReceptorConfiguration already anticipates rigid and flexible components.
Extend selection identities and output layers consistently. Flexible docking
requires its own validated preparation/output fixtures and control evidence;
it is not a hidden toggle in the initial rigid implementation. Future report
additions for flexibility require a separate approved report change.

Initial speed work: parse each hashed artifact once, lazily populate large
tables, coalesce viewer events, bound displayed logs, and reuse stages only
when all scientific inputs, versions and parameters match. Preserve complete
raw logs and evidence. Do not reduce seeds, search effort, or evidence collection
as an interface optimization.

## Future GitHub Wiki

Publish a version-aware GitHub Wiki after the first stable GUI workflow is usable. The Wiki is the
approachable teaching and operations layer; the repository's `docs/` directory remains the versioned
technical authority. Initial pages should cover installation and runtime checks, the guided scientific
workflow, dockable/fullscreen GUI behavior, Scientific Workflow Detail levels, PyMOL report-view reset,
synopsis versus full reports, explicit approval points, SDF-aware PLIP 2D diagrams, lazy per-pose PLIP
generation, cache/provenance behavior, scoring and clustering limits, B-factor/rotamer evidence,
flexible-docking status, dependency troubleshooting, interrupted runs, and portable `.duprotocol`
bundles. Every page should identify its compatible repository release and link to the relevant source
documentation. The Wiki explains the workflow; retained study artifacts and reports remain authoritative.

The GUI and all renderers must also enforce the local-only structural-data boundary in
[`data-privacy.md`](data-privacy.md): docked structures and derived interaction evidence are never
sent to web services or third-party APIs.

The approved visual and behavioral contract for locally rendered PLIP diagrams
is recorded in [`interaction-diagram-reference-design.md`](interaction-diagram-reference-design.md).
Treat that document and its public 4EY7 image as the GUI implementation reference;
do not substitute a web rendering backend or commit private docked-pose fixtures.

## Model-cost handoff

Use the stronger model for this design, reviewing the task-02 feasibility
result, the toolkit decision, concurrency/decision contracts, and the final
scientific equivalence review. Use a less expensive implementation model for
one numbered task or a small portion of it at a time.

Every assignment includes: this document and the relevant existing code; exact
owned files; approved interfaces; input/output fixtures; acceptance criteria;
and the focused test command. Require a concise change summary, test results,
and unresolved findings. Escalate when a contract must change, the Mac bridge
fails, or scientific semantics are unclear. Do not repeatedly re-audit the
whole repository for routine widget implementation.

Implementation follows this plan incrementally. No dependency installation,
runtime migration, report modification, complete workflow, or flexible-docking
support is implied beyond the status explicitly recorded above.

## References

- [Design philosophy](design-philosophy.md), [existing architecture](gui-architecture-plan.md),
  [scientific environments](environment.md), [guided workflow](guided-workflow.md).
- Installed PyMOL inspected at `pymol/Qt/__init__.py` in the main Python 3.9
  environment; repository environment declarations and locks are the recorded
  compatibility evidence, not a fresh solve or full installed-package audit.
- [Qt dock-widget documentation](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QDockWidget.html)
  describes application panel docking/floating; it does not establish external
  PyMOL window embedding.
- [PyMOL upstream GUI implementation](https://github.com/schrodinger/pymol-open-source/blob/master/modules/pmg_qt/pymol_qt_gui.py)
  is a reference for feasibility work; test against the installed version.
