# GUI implementation roadmap

Status: active implementation roadmap, 2026-09-12. PyQt5/Qt 5 is selected for
the initial desktop client. This document refines the existing architecture plan and takes precedence
for toolkit selection, process ownership, viewer integration, and sequencing.

Implementation status (2026-09-12): task 01 is implemented by the read-only
`docking-universal runtime-inventory` command and recorded in the
[2026-09-12 macOS arm64 audit](runtime-inventory-audit-2026-09-12.md). Task 02
has a working restricted bridge for controller-driven selection, structured
residue picking, box, camera, real fpocket layers, GUI-thread dispatch and
relaunch replay. Its [spike record](pymol-interaction-spike.md) retains the
remaining literal human mouse-click acceptance check.

Task 03 selected the already-installed Qt 5/PyQt5 stack for the initial client;
the rationale and remaining platform packaging checks are in the
[toolkit decision](gui-toolkit-decision.md). Tasks 04-08 now have an implemented
foundation: revisioned/locked state, a sole serialized JSON-lines host,
idempotent approvals, crash reconciliation, one application-wide scientific
job slot, explicit stage transitions, viewer-neutral identity/selection/message
contracts, a supervised PyMOL adapter, and a dockable desktop connected to the
host for explicit pocket approval. Preparation and pocket-review services now
register the receptor and pocket coordinate artifacts needed for required
PyMOL review; choosing a table row can update the viewer box without approving
the scientific decision. A noninteractive service boundary invokes the
existing bash receptor-preparation engine with explicit settings and disables
model-changing removal. The first task-09 slice is also wired: the desktop can
create a study, launch receptor preparation and pocket detection asynchronously,
cancel the running stage, discover existing preliminary reports without changing
them, and pause at the durable visual pocket decision. Application exit during
that work offers cancellation or return to the run; silent background continuation
is not allowed. Final protocol/report/bundle generation, screening, and flexible
residue docking remain future integration work, so this is not yet a complete
end-to-end GUI workflow.

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
| 10 Screening and enhanced Vina | Locked-protocol screen, parameter explanations, CPU/cost display, cancellation, pose/cluster/interaction review | Locked parameters enforced by host; partial successes retained; completion and scientific authority stay distinct. |
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
