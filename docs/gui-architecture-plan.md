# Docking Universal GUI architecture plan

## Purpose

Docking Universal should gain a graphical interface without replacing its
scientific workflow, audit trail, command-line interface, reports, or portable
protocols. Dockey demonstrates useful desktop patterns—an embedded PyMOL view,
dockable data panels, background jobs, and interactive docking-box controls—but
Docking Universal should use those patterns as inspiration rather than inherit
Dockey's workflow or data model.

The architectural goal is one tested Python workflow core with two clients:

- the existing command-line interface; and
- a new PySide6 desktop interface.

Both clients must create the same protocols, invoke the same scientific tools,
apply the same validation rules, retain the same audit evidence, and generate
the same reports.

### Product definition

Docking Universal is a **scientific decision-support system for structural
docking**, not merely a graphical engine launcher. It gathers and organizes
evidence, explains consequential choices, supports structural review, and
preserves the reasoning and provenance behind each decision. Docking engines
perform the search; Docking Universal helps the user decide what should be
searched, whether the workflow is defensible, and what the results can
legitimately support.

The interface and application core therefore follow these principles:

- evidence before action;
- explanation before approval;
- user judgment at scientific boundaries;
- explicit uncertainty and interpretation limits;
- reproducible decisions, not only reproducible commands;
- automation of technical repetition without silent scientific assumptions;
- visibility may be reduced by the user, but the underlying detail is always
  retained and recoverable.

## Does everything need to become Python?

No. A complete rewrite would add risk without improving the science.

### Move into reusable Python modules

Logic that represents scientific state or makes a workflow decision must be
callable directly by both the CLI and GUI:

- receptor and ligand input validation;
- protocol creation, loading, locking, and provenance;
- workflow state and stage transitions;
- docking-region definition and review state;
- pocket candidate records and selections;
- engine selection and engine-specific recommendations;
- explicit approvals and model-changing decisions;
- job definitions, status, cancellation, and restart;
- output-directory and artifact manifests;
- structured progress, warning, and error events;
- report inputs and report-generation requests.

### Keep as external executables

Docking Universal should continue to invoke established scientific tools rather
than reimplement them:

- AutoDock Vina and QuickVina-W;
- fpocket;
- Meeko and ADFRsuite tools;
- PDBFixer/OpenMM;
- PLIP;
- Open Babel;
- PyMOL rendering and visualization functions.

Python adapters should construct commands, record exact versions and
parameters, capture output, and convert results into structured records.

### Shell that can remain

- a small installed `docking-universal` launcher;
- installation/bootstrap scripts;
- narrowly scoped compatibility helpers where shell is clearly simpler.

Large shell workflows should be migrated gradually because GUI code cannot
reliably call them as reusable functions or receive structured progress and
decision requests from them.

## Proposed layers

```text
PySide6 GUI                     Command-line interface
     |                                  |
     +---------- Application API -------+
                         |
              Workflow/state services
                         |
        Scientific adapters and job execution
                         |
      Vina · QuickVina-W · fpocket · Meeko ·
      PDBFixer · PLIP · Open Babel · PyMOL
                         |
             Artifacts, logs, reports,
             protocol and audit records
```

### 1. Domain models

Typed, serializable records should define:

- `Study`
- `Target`
- `LigandSet`
- `PreparedReceptor`
- `PreparedLigand`
- `PocketCandidate`
- `DockingRegion`
- `Protocol`
- `ApprovalRecord`
- `Job`
- `PoseCluster`
- `InteractionResult`
- `ArtifactRecord`
- `SoftwareRecord`

These records become the single source of truth for the CLI, GUI, protocol
bundle, audit manifests, and report generator. Existing JSON formats should be
read through compatibility adapters rather than silently changed.

### 2. Scientific tool adapters

Each external tool should have a narrow adapter with a consistent contract:

- availability and version check;
- validated inputs;
- explicit command construction;
- cancellable execution;
- captured standard output and error;
- parsed structured result;
- retained raw log;
- clear failure classification.

Adapters must not contain GUI widgets or terminal prompts.

### 3. Workflow services

Services coordinate stages without knowing whether the caller is graphical or
terminal-based:

- `RunStudyService`
- `CreateProtocolService`
- `ScreenService`
- `PrepareReceptorService`
- `PrepareLigandService`
- `PocketReviewService`
- `ReportService`

A service emits structured events such as `StageStarted`, `ProgressUpdated`,
`WarningRaised`, `DecisionRequired`, `ArtifactCreated`, `StageFailed`, and
`StageCompleted`. The CLI renders these as text; the GUI renders them as status,
dialogs, tables, and progress indicators.

"UI-independent" does not mean interaction-free. A service may pause with a
durable `DecisionRequired` record and resume only after a CLI or GUI client
returns a validated response. Terminal prompts and widget callbacks are
presenters for this shared interaction model, not owners of scientific logic.

### 4. Decision and approval boundary

Scientific ambiguity must not be hidden inside a modal GUI callback. A
`DecisionRequired` record should contain:

- what was detected;
- why automation stopped;
- the scientifically relevant consequences;
- allowed choices;
- the default or recommended choice, if one is justified;
- artifacts available for inspection;
- whether the decision changes the molecular model.

The returned selection becomes an `ApprovalRecord` stored in the audit trail
and propagated to subsequent protocol and screening reports.

Interaction is the default. Eligible repeatable choices may be automated only
through an explicit, scoped user policy. An automated choice still creates a
visible decision record containing its rule, evidence, consequence, timestamp,
and a way to review why it was selected. The GUI must display a persistent
`AUTOMATED SCIENTIFIC DECISIONS` indicator while such a policy is active.

Decisions that change the receptor model, accept ambiguous chemistry, or grant
scientific screening authority continue to require explicit approval. Hiding a
panel must never imply approval. Pending decisions belong to the persisted study
state, so they survive window closure and application restart.

### 5. Job execution

Long-running work should run outside the GUI event loop. Start with a local job
manager using Qt signals over a Python worker/process layer. The first release
supports one active study run and one active scientific stage/process at a time;
it does not attempt multi-study scheduling or broad concurrent execution. It
should support:

- queued, running, completed, failed, cancelled, and interrupted states;
- per-stage and overall progress;
- live but bounded log display;
- cancellation with subprocess cleanup;
- restart from retained valid artifacts;
- multiple ligands without losing successful results when one fails.

The job manager should consume the same application API used by noninteractive
tests. Qt-specific code belongs only in the GUI-facing bridge.

## Proposed desktop interface

### Home

Present the three report-producing workflows first:

1. **Run a complete study**
2. **Create a reusable Docking Universal protocol**
3. **Screen ligands with an existing protocol**

Standalone receptor and ligand preparation remain available under a clearly
separated **Prepare files for docking** section.

### Study workspace

Use a restrained, task-oriented layout:

- **center:** embedded PyMOL structural view;
- **left:** study contents (target, ligands, protocol, generated artifacts);
- **right:** current guided step and its relevant controls;
- **bottom:** jobs, warnings, decisions, and expandable raw logs;
- **results tabs:** summary, pockets/region, poses/clusters, interactions,
  report, and audit trail.

Panels may be resized or hidden, but the default arrangement should guide the
user through one decision at a time rather than expose every parameter.

The Study Workspace should open maximized or full-screen by default. Its major
views are dockable: a user may focus a view full-screen, detach it into a
floating window or another display, and dock it back later. Home, Study
Workspace, Structural Review, Report/Audit, and Job windows are synchronized
views of one application and one persisted run, not independent copies of the
workflow. Closing a detached view must not cancel, approve, or mutate the run.

### Scientific Workflow Detail

General Options provides a presentation-only **Scientific Workflow Detail**
setting:

- **Concise:** essential progress, results, warnings, and decisions;
- **Guided (default):** the current CLI level of explanation, including
  scientific implications and interpretation boundaries;
- **Teaching:** expanded concepts, examples, and suggested review steps;
- **Technical:** guided detail plus commands, parameters, paths, versions, and
  live external-tool output.

The setting may change during a run and never changes protocol parameters,
scientific state, results, or the retained audit record. Mandatory warnings and
approval consequences remain visible at every level. Every workflow panel
offers `Show full details`, and the complete event timeline, raw logs, evidence,
and artifacts remain available even if the user hides their live presentation.
Teaching content should be attached to the real decision where it matters—for
example, explaining why an fpocket rank is a geometric hypothesis while the
user compares candidate sites—rather than interrupting work with generic
tutorial pop-ups.

### Interactive structural review

The PyMOL view should support:

- selecting a bound ligand;
- showing fpocket candidates with stable numbers and colors;
- clicking a pocket to select it and populate its recorded values;
- showing and adjusting the proposed docking box;
- selecting a residue-centered region;
- comparing experimental and docked poses;
- selecting clusters and synchronizing 2D/3D interaction views;
- inspecting components proposed for removal before approval.

Visual actions must update domain records, not directly rewrite protocol files.

### Audit experience

The GUI should make transparency useful without overwhelming the main flow:

- concise explanation in the active workflow panel;
- a persistent warning/approval history;
- an expandable record of parameters, commands, versions, and raw logs;
- direct links to retained artifacts;
- a final pre-run summary of receptor, ligand set, region, engine, settings,
  scientific status, and prior approvals.

## Migration sequence

### Phase 0 — lock current behavior

- Retain the current CLI and passing integration suite as the reference.
- Add characterization tests before extracting each large shell stage.
- Define equivalence in terms of artifacts, parameters, decisions, and results,
  not incidental console text or timestamps.

### Phase 1 — application contracts

- Create domain models and structured workflow events.
- Wrap the current commands behind Python application services.
- Build a UI-independent, resumable Python API exercised by tests.
- Keep existing scripts as the implementation behind those adapters initially.

This phase enables an early GUI without first rewriting every workflow.

The first contract implementation includes typed decision options and
responses, approval records, automation policies, workflow events, artifact and
job records, separate scientific-authority and completion states, persistent
pause/resume state, and a window-independent application controller. A
simulated pocket-selection workflow must prove the contracts before real
scientific commands are connected.

### Phase 2 — GUI shell and read-only workspace

- Add PySide6 application packaging.
- Implement Home and Study workspace layouts.
- Embed open-source PyMOL using a small isolated viewer component.
- Load existing protocols, manifests, results, and reports read-only.

This validates the desktop architecture before it can alter scientific state.

### Phase 3 — protocol creation GUI

- Implement target and output selection.
- Add bound-ligand, predicted-pocket, and user-defined region paths.
- Add pocket/box visualization and selection.
- Route ambiguity through recorded decision requests.
- Generate the same protocol bundle and report as the CLI.

Protocol creation is the best first write-capable workflow because it exercises
the important visual decisions without requiring the entire batch-results UI.

### Phase 4 — screening and results

- Load and summarize a selected `.duprotocol`.
- Prepare one or many ligands.
- Run and monitor engine jobs.
- Present scores, clusters, 3D poses, 2D interactions, partial failures, and the
  generated PDF report.

### Phase 5 — complete guided run

- Join preparation, control validation or exploratory site definition,
  protocol creation, screening, analysis, and reporting.
- Verify that CLI and GUI executions with the same recorded inputs are
  equivalent.

### Phase 6 — migrate remaining large shell workflows

Move shell implementations into Python one stage at a time only when doing so
improves structured progress, cancellation, portability, testing, or
maintainability. For each migration:

1. add or identify a behavior-locking test;
2. replace one stage;
3. run its focused tests;
4. run restart/equivalence tests;
5. run the relevant real-tool integration test;
6. commit the isolated change.

## Initial extraction priorities

The current code already has substantial Python orchestration, but the largest
GUI obstacles are the shell-based receptor preparation and stage commands.
Recommended order:

1. stabilize common path selection, process execution, and event reporting;
2. split `docking-universal-run.py` into application services and CLI prompts;
3. expose create-protocol and screen as noninteractive service calls;
4. migrate receptor preparation from its large shell script behind an
   equivalence-tested Python service;
5. migrate ligand preparation and direct docking stages;
6. leave reporting Python code in place, replacing only its invocation API.

## Agreed first vertical slice

The first write-capable GUI workflow is site-guided protocol creation because
it exercises Docking Universal's defining interaction without requiring the
complete screening-results interface:

1. select or explicitly download a receptor;
2. run the established receptor-preparation sequence through an adapter;
3. present preparation routes, warnings, and retained artifacts;
4. run fpocket and assemble candidate-region evidence;
5. generate the preliminary pocket-review report;
6. show every candidate in the embedded or detached PyMOL review;
7. synchronize structural selection with the candidate table;
8. pause for selection of one or multiple docking regions;
9. present the scientific implications and record explicit approval;
10. generate the final report and portable `.duprotocol` bundle.

Existing tested commands may remain behind adapters during this slice. Their
large internals are migrated only after the interaction contract works, using
the characterization and equivalence sequence above. In particular, receptor
preparation preserves strict Meeko first, conservative PDBFixer followed by
strict Meeko, diagnosed disulfide or histidine handling, the narrow linked-
component ADFRsuite fallback, and an explicit decision before component
removal. The missing target-adaptive fallback fixture in the receptor refactor
matrix must be added before translating that later stage.

## What to borrow from Dockey

Use as architectural reference:

- PySide6 desktop framework;
- isolated embedded PyMOL OpenGL component;
- dockable/resizable panels;
- model/view tables for molecules, jobs, poses, and interactions;
- background jobs communicating through signals;
- synchronized structural view and table selection;
- visible numeric docking-box controls.

Do not inherit by default:

- Dockey's database schema or project format;
- its scientific preparation and fallback rules;
- its whole-receptor default search behavior;
- direct UI-to-database coupling;
- its dense default layout;
- destructive behavior such as replacing prior engine results;
- broad exception handling or implementation shortcuts that weaken auditing.

Any copied or substantially adapted MIT-licensed code must retain Dockey's
copyright and permission notice in the appropriate third-party notices and
source files. Conceptual inspiration alone does not require code attribution,
although acknowledging Dockey as interface inspiration may still be useful.

## Acceptance criteria for the GUI foundation

- CLI behavior remains supported.
- GUI and CLI use the same workflow services and scientific rules.
- No scientific decision exists only in widget code.
- Every model-changing choice requires explicit recorded approval.
- Scientific explanations and evidence remain recoverable when their live
  panels are hidden or the run uses eligible automation.
- Automated decisions are visibly identified and fully auditable.
- Pending decisions and approvals survive window closure and application
  restart.
- Detached windows remain synchronized views of the same run.
- The initial job manager never starts more than one scientific stage at once.
- Closing the GUI cannot leave untracked child processes running.
- A failed ligand does not discard successful ligands.
- Existing `.duprotocol` bundles remain readable.
- GUI-created bundles are usable by the CLI and vice versa.
- Reports are identical in scientific content for equivalent runs.
- Ubuntu and macOS integration tests cover both the core and GUI-launch smoke
  path before a GUI release.
