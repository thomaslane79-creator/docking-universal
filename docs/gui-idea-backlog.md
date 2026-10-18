# GUI idea backlog and implementation gate

Status: active scope-control record, established 2026-09-24.

### Older-macOS and cross-platform compatibility (authorized 2026-10-18)

- User authorizes rebuilding the same patched GPU source for an older macOS
  deployment target, and requires Windows/Linux compatibility as well.
- Keep the accepted runtime and production installation unchanged while testing
  a separate macOS 15 candidate. A lower build target is not older-OS/driver
  acceptance. Preserve scientific settings, explicit engine choice and hashes.
- Audit actual installer/dependency/platform gaps, add native CI where feasible,
  and document CPU/viewer fallback paths. Never present simulated platform tests
  as native GPU acceptance or transfer Apple GPU approval to CUDA/OpenCL builds.
- User explicitly requires **native Windows**, not WSL2. The current pipeline
  uses POSIX shell programs; audit native dependencies, add native Windows safety
  and CI foundations, and record the remaining port milestones. Do not silently
  substitute WSL or describe an unfinished installer as native support.
- First milestone passed: native Windows/Ubuntu/macOS 15 locking/state/browser
  contracts; a macOS 15 candidate build/loading check; native Windows Vina 1.2.7
  prepared-input CPU adapter with exact same-seed repeats and paths with spaces;
  and Ubuntu/macOS full CLI plus real-tool integration CI. Native Windows full
  installer/preparation/desktop/report acceptance remains unfinished; the older
  Mac GPU candidate is not activated without older-OS GPU acceptance. See
  `docs/cross-platform-compatibility.md` and CI runs 39131637146 / 39132054556.
- Next bounded slice (user: keep going): native PowerShell/bootstrap entry
  points, isolated preview runtimes, and the real desktop-to-host pipe transport.
  Validate on native Windows, including Unicode/spaced paths and fail-before-
  mutation for unported scientific stages. This is installer/transport work,
  not a new GUI feature or authority to claim the complete scientific port.

### Bounded Mac runtime packaging (authorized 2026-10-17)

- Clean, isolated installation of checkpoint `24700aa` passes CLI/smoke/window
  startup but lacks the embedded PyMOL runtime and optional accepted GPU setup.
  User explicitly authorizes fixing these two installation gaps, without new
  GUI features or scientific engine/settings changes.
- Package the pinned embedded runtime relocatably and the exact accepted Apple
  GPU executable plus AutoGrid, with hashes, source/license provenance and
  prefix-local discovery. Keep Vina the default and GPU explicitly experimental.
- Test in fresh environments without using the working custom PyMOL/GPU paths.
  Do not change working environments, studies, scientific approval rules,
  accepted GPU hash or unsupported-platform guards. No wholesale benchmark rerun.
- Completed 2026-10-18: five fresh environments, public installer/CLI/smoke,
  real embedded/full PyMOL detach/return and ray export, same-seed synthetic AD4
  checks, and exact AutoGrid map-payload parity passed. All 697 protected working
  files remain unchanged. No new GUI/scientific feature or method default.
  See `docs/mac-runtime-packaging.md` for limits, source/licenses and retained
  results, including the rejected initial synthetic test fixtures.

### Approved tabular compound import (2026-10-17)

- User explicitly prioritizes CSV, TSV and XLSX SMILES import now. Reuse the
  existing paginated compound review, selection and screening path.
- Suggest a SMILES column and optional name/ID column, but list every header
  in dropdowns. Suggestions are not approval: **Use these columns** is required
  before parsing/selecting compounds. Editing either mapping clears selection
  and requires approval again. Worksheet choice is explicit for Excel files.
- Preserve exact source hashes, original row numbers, approved column mapping,
  invalid-row diagnostics and selected-subset provenance. Do not evaluate Excel
  formulas, change supplied chemistry to the protocol pH, or start docking.
- Keep SDF/MOL behavior and existing studies unchanged. Tabular files are opened
  individually; folders remain SDF/MOL libraries.
- Implemented: literal CSV/TSV/XLSX reading without new production dependencies,
  explicit mapping approval, worksheet choice, paginated valid-subset selection,
  exact mapping/source-row provenance and source/mapping change guards. Source
  validation passes 87 scientific/workflow and 121 GUI/host checks plus 22 real
  GUI/host/materialization checks. Installation and its repeat acceptance are
  recorded in `docs/tabular-ligand-import-validation.md`; no docking or scientific
  approvals are performed by this validation.

### Optional prediction alongside a bound ligand (authorized 2026-10-17)

- User flags that **Site definition** implies a final, single docking location.
  Rename the initial source choice **Starting point for site review**, with
  inline guidance that one or more regions can be chosen later, here or
  elsewhere. This is wording only: do not change site geometry, selected
  regions, control authority, lookup settings or approved studies.

- User clarification: this remains the ligand-bound workflow. Site discovery
  is a separate choice: use the selected ligand site while still gathering
  related-PDB evidence, or additionally run P2Rank to review other pockets.
  Enabling prediction must not switch the scientific pathway to ligand-free
  docking, change a control into exploratory use, or select alternative sites
  automatically. Control authority remains limited to what was actually tested.
- The explicit unchecked option reads **Also run P2Rank to look for other
  pockets?** Related-structure ligand sites remain directly selectable without
  prediction, alone or together with the input-ligand site; they are not merely
  passive annotations of predicted pockets. If the user explicitly chooses the
  fallback detector, the question names that actual detector instead.
- User accepts clear **recommended** labels instead of forcing every option
  on. Mark experimental-ligand redocking (when suitable), related-public-PDB
  lookup (internet required), and P2Rank for additional-site review. Preserve
  all existing selections/defaults, offline mode, exploratory approval and
  separate explicit box selection. This is guidance, not automatic authority.
- User prefers independent checkboxes over named combinations. Present a
  redocking checkbox alongside existing PDB-lookup and optional-prediction
  checkboxes. Keep new-structure versus saved-protocol reuse as the separate
  starting choice. Preserve the existing serialized pathway and all host
  authority checks; unchecking redocking must keep the selected ligand site
  rather than silently switching the study to predicted pockets.
- Checkbox layout installed after the user's explicit installation request.
  All 108 installed GUI/workflow checks pass; source/installed module hashes
  agree and existing study-state hashes are unchanged. Backup and logs:
  `validation/runs/site-options-checkboxes-20261017/`. No preparation or docking
  was run during this installation.

- User explicitly requests P2Rank as an option even with a bound ligand.
  Add an optional prediction checkbox to ligand-guided/control preparation;
  retain the exact bound-ligand site, predict on the ligand-removed prepared
  receptor, and review both sources before any docking. This closes the same
  site-discovery acceptance gap as universal related-ligand lookup.
- Keep offline prediction independent of online evidence lookup. Do not invent
  a P2Rank score for a ligand-defined site, silently substitute a detector,
  reapprove old studies, or extend a control to untested regions.
- Implemented and installed with recoverable backups. Fresh installed 2R5P/MK1
  preparation runs P2Rank and related-entry lookup, retains P1/P2/P3, a separate
  evidence-defined L1 and input-defined B1, and stops before approval/docking.
  The input ligand adds no supporting-evidence observation; the recorded input
  PDB entry is excluded from related-entry counts. 254 scientific/workflow,
  106 GUI and 28 retained-engine checks pass. Details:
  `docs/site-first-ligand-evidence-validation.md`.

### Related-ligand lookup independent of input ligand/pathway (authorized 2026-10-17)

- User requires public ligand-site evidence lookup whether the input is apo or
  ligand-bound and across preparation pathways, because users may choose more
  than one site. This corrects a workflow gap: the known-ligand control route
  currently hides the lookup option and bypasses the evidence review.
- Keep online lookup optional with explicit local-only/unavailable/partial
  statuses. Preserve non-P2Rank ligand-defined alternatives and multi-region
  selection. A control of one exact ligand/site does not validate other sites,
  overwrite an approved protocol, or authorize docking automatically.
- User chooses site review before redocking. Implemented and installed:
  prepare/lookup, explicit multi-site review, then exact-input control. Only
  the tested scope can acquire control authority; a separate multi-site
  exploratory protocol still requires explicit approval. Final native GUI/host
  acceptance searched 20 other entries and retained 20 ligand observations,
  excluding the reference 2R5P entry; no docking or scientific approvals were
  performed. Existing studies/results are hash-unchanged. Acceptance and limits:
  `docs/site-first-ligand-evidence-validation.md`.
- Acceptance: lookup is not suppressed merely because a ligand is present;
  independent ligand-defined sites remain visible/selectable; offline/failure
  paths retain preparation and do not claim no evidence; control authority
  stays attached to the tested receptor, region, ligand, engine and settings.

### Raw-input end-to-end coverage (authorized 2026-10-17; paused for preparation defects)

- User chooses three sequential full workflows rather than nine combinations:
  fresh 2R8N download/Vina; local 2R8N PDB/QuickVina-W; ligand-present
  2R5P/MK1/experimental AD4. Preparation is new for each case. Separate explicit
  site/authority approvals are retained; exploratory AD4 is not control-validated.
  Records: `validation/runs/full-scratch-two-paths-20261017/`.
- First fresh preparation reproduces the approved receptor SHA256 and all six
  P1 geometry values exactly; fresh public-PDB lookup records 18 observations
  across 20 examined candidate entries. Approval persisted, but the GUI received
  an invalid host response frame. The existing lookup worker prints progress to
  stdout (`docking_universal_pocket_evidence.py`), shared with host JSON replies.
  Reopening the host reads the saved approval correctly; continuation did not
  repeat preparation or scientific decisions. Record this transport finding;
  do not silently interpret an acknowledgement error as a failed mutation or
  rerun science. No production fix has been installed for this finding.
- User requests investigation of the stopped local-PDB mismatch. Retained-input
  comparison shows identical original/filtered heavy-atom coordinates. Native
  mmCIF Reduce2 succeeds, but the wrapper searches only for PDB output and falls
  back. The PDB filter loses crystal context; Reduce2 shifts/boxes the receptor,
  while public-PDB evidence remains in the input frame. P1's physical site is
  unchanged under the translation, but its 17 evidence matches become zero and
  an extra ligand-defined candidate appears. Two PRO1 hydrogens/terminal-charge
  changes and optimization flips additionally distinguish the preparation
  routes. No new calculation or production fix was made during diagnosis.
  Findings: `validation/runs/full-scratch-two-paths-20261017/receptor-investigation/findings.md`.
  Correct native-format auditing and frame preservation, then validate both
  input routes before further engine runs; do not approve the mismatched
  evidence merely to finish the series.
- User authorizes the fixes. Native mmCIF output auditing/conversion and PDB
  crystal-context preservation are now implemented and installed with backups,
  together with fixed-backbone coordinate checks and stderr-only evidence
  progress. Both installed raw-input routes pass real Reduce2/Meeko/P2Rank
  preparation using the bundled minimal GeoStd core. All 754 heavy atoms and
  396 backbone anchors are preserved; both routes recover 17 P1 evidence
  associations locally from retained observations. Charges/types and heavy
  coordinates agree; two added H coordinates differ by 0.001 Å rounding.
  No docking or old-state writes occurred. P1 geometry matches the old box,
  but the corrected receptor differs from the previous fallback receptor;
  renewed preparation approval is required before the remaining engine runs.
  Details: `docs/reduce2-frame-validation-2026-10-17.md`.

### Fresh-study protocol reuse (authorized 2026-10-17)

- User selects remaining item 2: import a saved protocol into a fresh study,
  select compounds, screen, and reopen results. Inspection found no independent
  GUI import entry point. Add that focused route with read-only integrity and
  settings review, explicit import, a host-owned immutable bundle snapshot and
  unchanged scientific authority. Reuse locked preparation/settings; do not
  rerun receptor preparation or silently approve exploratory screening.
- Verify damaged/changed bundles, stale revisions, duplicate imports and
  existing-study rejection. Run a small real sequential screen in an isolated
  study, then reopen results and compare retained protocol/input identities.
- Implemented and installed with recoverable backups: 127 GUI/host checks,
  53 protocol/report/import checks, 24 real workflow assertions and 61 native
  viewer checks against each of source and installed files pass. Selected two
  of three SDF records; 25 actual Vina searches completed using unchanged locked
  settings, with no receptor preparation. Fresh-host reopening passes and the
  original study/bundle are unchanged. Fixed inherited detector-version
  provenance in reuse reports. Details/limitations:
  `docs/protocol-reuse-validation.md`; records:
  `validation/runs/protocol-reuse-20261017_b/`.

### Report-only static figures; keep interactive review (authorized 2026-10-17)

- User explicitly confirms removal of direct static-figure viewing: leave
  interactive views. Remove the Decision figures browser, its zoom/full-screen
  controls and static-figure export entry. Keep interactive candidate plots,
  pocket selection, linked 2D/3D inspection, pose/cluster browsing and retained
  PyMOL scenes. Static report panels stay in reports and on disk; Open report
  actions remain. Separate scene discovery from static image decoding, and
  verify approval gates, detached views and exports without scientific reruns.
- Implemented: 384 GUI/report/workflow checks and 92 native PyMOL checks pass.
  The three changed GUI modules are installed with recoverable backups; the
  original study remains unchanged. Native checks use retained poses only.
  All 61 retained-cluster checks also pass against the installed GUI files.
  Records: `validation/runs/gui-interactive-only-20261017/`.

### Synchronize production report generators (2026-10-17)

- User additionally requests standalone protocol-only acceptance for Vina and
  experimental AD4. Verify engine-specific selectable settings, the planned
  energy explanation, actual AD4 grid geometry and absence of fabricated docking
  results. Correct no-run-manifest pocket selection to follow the approved box,
  not the first generated candidate. Reuse retained inputs/figures in isolated
  report copies; no docking or original-study changes.
- User authorizes synchronizing the recent report/label changes across report
  generation paths. Share compact protocol and result tables across PDF,
  HTML and Markdown; preserve machine-readable diagnostics. Carry numeric
  pocket scores/probabilities into portable protocols and remove the inherited
  report placeholder. Retain original studies and scientific outputs; no new
  preparation, docking or clustering. Details: `docs/reporting-consistency.md`.

### Engine-specific energy table labels (2026-10-17)

- User clarifies the location: beside the best docking score in the results,
  not in configured-protocol options. Add a Scoring function column immediately
  after Best docking score in the multi-ligand overview, and a row immediately
  after Best retained docking score in individual summaries. Values are AD4
  or Vina (including QuickVina-W); existing energy headings/units are unchanged.
  Identify the engine from the retained protocol/manifest, not the current
  runtime. Unknown historical engines show Not recorded; no invented
  scoring identity or changed values/rankings.

### Reader-facing results summary (2026-10-17)

- User identifies excess diagnostic detail in the main compound summary.
  Remove seed support, conformer support and selected-representative counts
  from that table across report routes. Retain the diagnostic fields in the
  result records and scientific artifacts; keep energies, top-cluster
  population and distinct pose-cluster count visible. Presentation-only.

### Saved 3D residue-label legibility (2026-10-17)

- User requests more prominent report callout typography. Switch the shared
  saved-figure font from Sans to Sans Bold, keeping size 40 and the compact
  callout placement unchanged. Six retained examples are ray-rendered in an
  isolated copy; the two changed PDF pages are visually checked, with the
  other six pages pixel-identical to the prior reviewed report. All 61 focused
  tests pass. No docking, coordinates, clustering or camera changes.

### Configured-protocol report cleanup (2026-10-16)

- User explicitly requests only selectable options in this report section.
  Use one allowlisted table across report routes; exclude fixed defaults,
  derived results, implementation limits and approval/file metadata. Retain
  technical provenance in the existing protocol/study records. Actual AD4
  search-grid dimensions stay with pocket geometry. Presentation-only work;
  no docking, preparation, scoring or clustering changes.

### Isolated AutoDock-GPU Apple-Silicon trial (2026-10-16)

- Current completion: numerical reference/KNI follow-up, native adapter, two-
  compound GUI/protocol/screen/report/reopen, 59 native PyMOL checks and native
  failure/skip/tamper/cancellation checks pass. 374 regression tests pass.
  The optional engine uses the shared reporting pipeline and its own AD4
  parameters. Vina stays the default. The GUI and README now include detailed
  teaching copy. Local backed-up installation and all 59 installed native viewer
  checks also pass; Vina remains the initial GUI choice. Windows/Linux remain an architectural goal, not acceptance
  inherited from the Mac. See `docs/ad4-gpu-integration.md` and its separately
  recorded local installation status. Historical trial restrictions below are
  point-in-time records, superseded only within this accepted scope.
- User now authorizes completing the remaining numerical investigation,
  finishing the KNI-577 audit, then optional-engine integration and complete
  GUI/protocol/report/failure/cancellation/reopen acceptance. This supersedes
  the earlier validation-only restriction, conditional on correctness gates.
  Preserve Vina defaults and studies; use one common report/visualization
  pipeline for all engines, with explicit engine-specific energy and method
  labels. Do not enable an engine or relax a gate to complete the checklist.
- Current numerical work first checks the retained tipranavir state at the
  8 Å intramolecular cutoff. No new docking is needed to isolate its arithmetic.
  Further native searches are sequential and scoped to a declared validation
  purpose, not duplicate timing or preparation runs.
- Full retained-workload benchmark completed: all 30 searches / 600 checked
  poses, six representative PLIP/2D/ray-rendered 3D sets and visually reviewed
  seven-page AD4 PDF. GPU docking phase 356.98 s versus historical CPU8 499.31 s.
  Stage-summed active processing 427.83 s versus 581.60 s, not an uninterrupted
  total: initial report elapsed 648.91 s including manual recovery. Isolated
  launcher import-path failure and a rejected 15-unit diagram layout are retained;
  explicit continuation uses supported 20-unit spacing and unchanged gates,
  reusing completed work without redocking. Report-only pagination/rank-order
  corrections and QA are separate. No preparation, original study/default change,
  production engine installation or numerical-acceptance claim. Final record:
  `validation/runs/autodock-gpu-mac-20261016/full-screen-20261016/completion.json`;
  detailed timing/recovery boundaries in `docs/docking-performance.md`.
- User authorized running the full original two-compound workload on the corrected
  GPU engine: all three retained conformers and five original seeds, sequentially,
  no new preparation or production integration. Use explicit AD4 scoring labels,
  exact native output/chemistry provenance and shared clustering/PLIP/2D/3D stages
  where engine-neutral; create a labeled benchmark PDF rather than a misleading
  Vina production report. Keep the separate numerical gate unresolved and retain
  original protocol/study unchanged. Time setup, searches and downstream work
  separately; a historical cross-engine comparison is not equal-effort hardware
  acceleration or experimental hit validation.
- Broader assessment completed: 32 searches / 640 chemistry-checked poses, all
  eight same-seed pose/population/score repeats match across four supported
  controls and two stopping settings. Primary recovery within 2 Å is 2/3 seeds
  for indinavir and 3/3 for tipranavir, KNI-577 and imatinib in both arms. A
  separate added-atom-type numerical audit stops on tipranavir: all winners
  agree within 3.63e-6 kcal/mol, but one non-winning state differs by 0.00093215
  kcal/mol near zero and fails the predeclared 1e-5 scaled gate. Do not relax
  the gate or claim expanded numerical acceptance; isolate the retained-array
  residual first. KNI-577's extra audit was not launched; geldanamycin macrocycle
  types remain unsupported here. No active workers or production changes.
  Results/limits: `docs/autodock-gpu-control-assessment.md`; README now records
  upstream fixes and links the exact source patch outside run directories.
- User authorized continued scientific assessment before offering an optional
  engine, explicitly accepting documented Vina/AD4 differences, not same-engine
  nondeterminism. Test four retained crystal controls with three seeds plus a
  first-seed repeat, heuristic/autostop and declared fixed-budget arms, no
  preparation reruns or Vina reruns. Keep unsupported macrocycle types explicit,
  original inputs intact and production integration pending review. Document
  upstream source corrections and safety guards in the main README.
- User authorized the next isolated investigation of the remaining one-work-item
  failure and wider population energy discrepancies. Test GPU event completion /
  launch-size controls and matched-coordinate/component scoring references; no
  production installation, preparation changes or relaxed acceptance tolerances.
- Completed that follow-up: 48 additional searches, one expected native rejection
  without a GPU launch, ten unit tests passing. One-work-item still fails with
  profiling/chunking/explicit completion; its precise defect remains unresolved.
  An isolated guard now rejects it, while 32/64/guarded-128 repeat controls pass.
  Matched-coordinate/formula references explain the large energy tails: CPU
  0.01 Å distance tables and different dielectric/desolvation formulas were being
  compared with GPU continuous evaluation. Independent GPU-formula bounded-
  population residual maxima are 0.000307 / 0.000264 kcal/mol, with every one
  of 6,000 population entities retained. No score rewriting or production install.
  Full extremes/small cached-energy differences and limits remain explicit:
  `docs/autodock-gpu-numerical-validation.md`. All diagnostic workers exited.
- User subsequently authorized comprehensive same-seed diagnostics. Isolate
  fixed-generation/early-stop-disabled repeats, genetic search versus local
  refinement, host initialization and GPU kernel behavior; instrument/build
  pinned-source diagnostic variants as needed. Preserve original results and
  production settings; no preparation repeats, remote jobs or integration.
- Completed 213 diagnostic invocations: seed/host initialization and initial GPU
  scoring match; divergence first appears in ADADELTA forces. Identical-coordinate
  gradient probes expose a non-atomic/atomic shared-force race between inter-
  and intramolecular loops. A single barrier makes the standard 128-work-item
  candidate match in traced/untraced short searches, full-budget repeats on both
  ligands and original-autostop repeats. No production install/default changes.
  One-work-item repeats still fail even with that barrier, and population energy
  residuals remain a separate numerical gate; not blanket production acceptance.
  Seven native unit tests pass, all diagnostic workers exited. Evidence and
  complete unsuccessful controls: `docs/autodock-gpu-reproducibility.md`.
- User authorized testing option 1 after the experimental GNINA Metal search
  failed: official AutoDock-GPU on the local Apple GPU, not production integration.
- Pin the official release/source and verify native GPU execution. Reuse exact
  retained receptor/ligand PDBQT inputs and generate AutoDock4-specific maps in a
  new validation directory; no preparation/default/study changes or remote jobs.
- Start with indinavir crystal recovery and the slow flexible current-screen
  ligand. Report AutoDock4 scores separately from Vina, actual search budgets,
  map/setup/search times and chemistry/frame checks. Different engines are not
  equivalent searches, and a launch/smoke pass is not scientific validation.
- No system/Homebrew upgrades, disabled security controls, duplicate jobs or
  automatic failed-job restarts. Stop at unsupported-input or correctness gates.
- Completed the official unmodified v1.6 OpenCL pilot on Apple M2 Max: two cases,
  two seeds plus first-seed repeat, 20 LGA winners each (120 poses). Chemistry/
  charge/type and 3D stereochemistry checks pass; same seeds are not bit-identical.
  Fast autostop defaults rank indinavir at 4.15/3.71 Å, repeated seed at 1.77 Å.
- A separate declared no-autostop diagnostic reused maps with the original
  heuristic's explicit 5,210,753 evaluation ceiling: both indinavir seeds rank
  ~1.64 Å poses first in ~32 s process wall. Forty additional poses pass the
  chemistry checks. Historical eight-thread Vina searches are ~45–46 s with
  1.22/1.26 Å top-pose RMSDs; different search/scoring/timing boundaries prohibit
  claiming equivalent-workload GPU speedup. No analogous no-autostop screen run.
- Low-energy run-winner CPU/GPU total-energy residuals are small, but larger
  discrepancies exist elsewhere in the populations and remain unaudited. Not
  production acceptance. No installation, default change or active worker remains.
  Full evidence/limits: `docs/autodock-gpu-mac-trial.md`.

### Experimental Apple-GPU docking feasibility (2026-10-15)

- User explicitly authorized investigating native Apple-GPU acceleration after
  declining further CPU job-splitting tests. Evaluation is isolated; no change
  to production Vina, receptor/ligand preparation, studies, settings or GUI.
- Audit actual search kernels and build requirements before compiling third-
  party code. Distinguish search acceleration from CNN rescoring, verify Metal
  availability, and use a pinned source checkout. No system/Homebrew upgrades,
  new remote jobs or structure uploads. Do not revive cancelled CPU tests.
- Prioritize the experimental GNINA Metal contribution for a same-engine CPU /
  GPU comparison with CNN scoring disabled; assess Vina scoring/input parity
  separately from stock Vina. At initial inspection Druse required macOS 26
  while this Mac ran 15.7.9; no OS upgrade was performed by the agent.
- Gate any docking benchmark on a successful isolated build, visible actual GPU
  work, stable chemistry/atom mapping, fixed inputs and an honest matched search
  budget. Failed builds, unsupported preparation and differing algorithms must
  be reported explicitly, not silently worked around or called equivalent.
- User independently upgraded to macOS 27.0.1. Scientific Python/RDKit/gemmi/
  Meeko and Vina load correctly; 91 GUI/workspace regressions pass. A pinned
  GNINA shader probe ran on the Apple M2 Max: scalar multiply, pair energy/
  forces, curl/bounds correction and energy reduction pass synthetic reference
  checks (maximum observed absolute error 1.53e-5, tolerance 1e-4). All six
  shaders compile at runtime; tree kernels have not been numerically tested.
- User explicitly approved the optional Apple Metal compiler installation and
  full isolated validation. Component 17C7003j is installed; explicit toolchain
  selection works although unqualified `xcrun metal` does not locate it.
  Full engine is not built and no docking speedup has been measured.
  Other dependencies must stay in an isolated
  build prefix. Evidence: `docs/apple-gpu-feasibility.md` and the post-update
  `metal-probe.json` in the isolated validation run.
- Full isolated validation subsequently **failed acceptance**: loader and spline
  pointer repairs allowed all 11 libmolgrid native tests and five GNINA numerical
  checks across three seeds to pass. Direct retained-PDBQT round-trip chemistry
  verification failed; explicit Meeko-mapped SDF retained chemistry/coordinates.
  The first full Metal indinavir search then crashed in the atom/tree mapping
  path; remaining searches/repeats were not run after that gate. No speedup or
  production readiness is established. All workers exited; no automatic restart.
  Details, patches and retained failure summaries: `docs/apple-gpu-feasibility.md`.

### Full five-seed concurrency follow-up (2026-10-15)

- User requested testing the full roughly twelve-minute example after the
  two-seed pilot and noted compound size as a likely bottleneck.
- Run all five retained seeds × three conformers × two compounds: thirty
  searches / ten compound-seed batches for each 1×8, 2×4 and 4×2 layout. One
  pass per layout (ninety searches), explicitly not repeated medians. Preserve
  chemistry, search effort and per-pose output settings; no production changes.
- Reuse preparation and omit PLIP/reports to isolate docking throughput. The
  historical 729.08 s full worker time is context, not a contemporaneous equal-
  scope timing baseline. Report per-compound search time separately from total
  concurrent wall time; sums of overlapping search times are not elapsed time.
- Retained inputs: 37 heavy atoms / 15 RDKit rotatable bonds versus 27 / 3.
  The larger, more flexible compound consumed 422.65 of 489.64 s of prior
  eight-thread search time (86.3%). This comparison does not isolate size from
  flexibility/chemistry. Do not reduce sampling or promise concurrency gains.
- Keep active-GUI guard, cancellation, input/implementation hashes and complete
  output checks. Preserve the original two-seed harness snapshot in its run.
- Cancelled at the user's request during the first 1×8 arm: the user decided
  further splitting tests were not worth pursuing. The coordinator and recorded
  dispatcher/API workers exited; no full arm completed. Retain the interrupted
  outputs/logs, but do not use them as full-workload timing results or restart.
  Results: `validation/runs/vina-concurrency-full5-20261015/summary.json`.

### Isolated Mac CPU-concurrency pilot (2026-10-15)

- User explicitly authorized testing option 1: one 8-thread worker versus two
  4-thread workers versus four 2-thread workers. This is an isolated benchmark,
  not authorization for a production scheduler or concurrent user studies.
- Reuse the two-compound 2R8N screen's three prepared conformers and first two
  matched seeds: four compound/seed batches, twelve searches per arm. Repeat
  each layout twice in reversed order (72 searches). Use the installed API
  batch path, with identical effort 16, 15 requested poses, 8 kcal/mol window,
  refinement, maps and chemistry. No preparation, PLIP or report regeneration.
- Limit simultaneous docking-search threads to eight, record total arm wall
  time, check every complete output against its retained seed/conformer result,
  and verify original input/reference/implementation hashes. Abort the pilot
  if another GUI calculation starts; never stop the user's calculation.
- Keep all results in a fresh validation directory. No production changes,
  silent restarts, remote/GPU jobs or new scientific-validation claims.
- Started in `validation/runs/vina-concurrency-20261015/`; 23 combined batch and
  benchmark tests pass. No competing GUI calculation was running at launch.
- Completed all six arms: median twelve-search wall time 205.07 s (1×8),
  221.85 s (2×4, 8.2% longer), 344.06 s (4×2, 67.8% longer). All 72 complete
  outputs match the corresponding retained references; post-run verification
  reconfirmed source/reference/implementation hashes. Keep sequential eight-thread
  execution for this workload. No production scheduler/default change or
  automatic installation. Larger/differently balanced libraries remain untested.

### Explain and expose screening CPU choices (2026-10-15)

- User explicitly requested keeping eight threads as the practical default and
  explaining the available choices in the GUI after the three-target pilot.
- Keep the existing bounded eight-thread Apple-Silicon Vina policy and existing
  overrides. Add application-default, engine-automatic and custom-count choices
  to Screen ligands, with visible teaching copy. Higher counts are permitted,
  not promised faster. This is execution, not search effort or parallel jobs.
- Apply a custom/automatic choice only to the newly launched screening process;
  inherit existing environment/config policy when application default is chosen.
  Preserve the reusable protocol and actual per-docking CPU/source manifests.
- Acceptance: GUI default/automatic/custom values and launch payload, host
  validation and isolated child environment, no changed scientific settings,
  existing CPU-priority tests, and readable narrow-screen layout. No redocking.
- Completed: 103 targeted GUI/host/docking-runner tests pass; 77 native layout
  and control checks pass at 960/1100/1440 widths, including custom counts.
  Three installed GUI/workflow files match tested source; installed controls
  and the unchanged eight-thread default on this Mac were verified. Relaunch
  the desktop to load the new controls. Existing protocols/runs are unchanged.

### Broader CPU validation and persistent Vina batches (2026-10-15)

- User explicitly authorized a broader timing comparison followed by integration
  of the validated persistent-worker/shared-grid path. Supported screening is
  too slow; the current CLI starts a new engine for every conformer.
- Compare 4/8/12 threads twice in varied order on retained indinavir/protease,
  imatinib/Abl and geldanamycin/HSP90 inputs: one fixed starting conformer and
  two matched seeds per case, exhaustiveness 16, 15 poses, 8 kcal/mol window.
  No preparation, PLIP or report reruns; these are timing/implementation checks,
  not new conformer-method claims or a small-ligand/general-hardware survey.
- Integrate one persistent Vina API worker per prepared-ligand batch/seed, with
  all atom-type maps generated before loading ligands and reused in memory.
  Preserve exact search settings, rigid-receptor refinement, output names,
  skip/failure behavior, run provenance and single active scientific job.
- Auto-selection must check supported Vina version/runtime and config options
  before any search; unsupported paths retain the existing CLI with an explicit
  reason. Never silently rerun failed API searches through a different backend.
  Retain a CLI override for comparison/troubleshooting. No concurrent docking
  jobs, GPU implementation, altered chemistry or reduced search budget.
- Acceptance: unit tests for batch map reuse, per-ligand failure isolation,
  skip-existing, settings/version gates and cancellation; real output comparison
  against the CLI on multiple retained targets and the current screen. Record
  runtime and pose equivalence separately. Other engines/GPU remain evaluation
  work after the supported CPU path is measured and verified.
- Implementation is complete in source. Twenty-two targeted execution tests,
  the CLI shell suite, 107 host/GUI regressions and the broader workflow/process
  tests pass. Managed Conda direct-executable discovery was checked without
  docking. Native acceptance passed all 22 checks: nine complete outputs match
  CLI references, skips preserve bytes without maps, and bad-ligand isolation
  passes. The three execution files were installed only after acceptance;
  independent SHA-256 verification confirms the installed tested versions.
- Completed thread pilot: median two-seed worker seconds at 4/8/12 threads are
  indinavir 166.08/94.87/89.20, imatinib 48.71/28.08/28.80, and geldanamycin
  226.34/121.02/121.25. All 36 complete outputs match corresponding case/seed
  references across counts/repeats. Eight is not universally optimal; no default
  or scientific setting changed. Preparation and analysis were not timed.
- The fresh current-screen three-conformer API batch took 14.57 s versus
  13.87 s for same-thread direct CLI: slightly slower, not a demonstrated
  whole-screen speedup. Installed persistence is per compound/seed batch, not
  across the whole study, and is not a GPU backend. Original data are unchanged.
- CPU pilot: `validation/runs/vina-three-target-threads-20261015/`; gated native
  acceptance/installation: `validation/runs/vina-batch-acceptance-20261015_b/`.
  The earlier acceptance directory records cancellation of its waiting-only
  coordinator before any docking; it is not the active acceptance run.
- The quiet completion monitor confirmed final success and was paused after
  completion; it did not restart or duplicate any work.
  GPU feasibility findings and backend guarantees: `docs/docking-performance.md`.

### Cluster PLIP display and CPU-thread execution correction (2026-10-15)

- User explicitly requested automatic PLIP contacts while browsing retained
  docking clusters, and implementation of the faster CPU setting, then asked
  about counts above eight. This corrects the supported Results review step:
  previously ordinary cluster browsing loaded ligand coordinates alone while
  the paired review loaded the contacts from the same retained XML.
- Smallest correction: load exact representative/receptor/report together,
  show contact residues and the existing thick, colored contact geometry, offer
  a compact 3D-only clickable type key, contact/cartoon/label toggles, and borrow
  those same controls in full detached PyMOL. No PLIP rerun or report rewrite.
- Clear old geometry and residue sticks on pose changes; missing/mismatched
  reports fail closed with an explicit message. Same-receptor camera is retained;
  paired review restores the previous cluster's contact state and type choices.
- CPU override: `dock --cpu N` or `DOCKING_UNIVERSAL_CPU=N`, including automatic
  `0`. Explicit CLI/environment/config choices take precedence over a bounded
  eight-thread Apple-Silicon Vina default; other platforms/QuickVina-W retain
  automatic behavior. Record count and source in each docking run manifest.
  This thread policy is not the benchmark's shared-grid API execution backend;
  no claim that changing threads alone reproduces its full elapsed-time gain.
- Additional timing pilot: sequential 12/8/10-thread arms, both compounds and
  three conformers, two matched seeds, unchanged per-search sampling. It reuses
  preparation and omits analysis/report generation. All timings and full-output
  equality are retained in `validation/runs/vina-threads-20261015_12_8_10/`.
- Acceptance: unit regressions plus native six-representative checks for exact
  PLIP contacts, independent toggles, camera preservation, paired/full-window
  restoration, missing-report clearing and unchanged source data. No unrelated
  GUI feature, new scientific method or parallel scientific jobs are added.
- Completed pilot: 8 threads 197.45 s, 10 threads 207.04 s, 12 threads
  223.13 s; all 36 complete outputs match their retained baseline outputs.
  Keep the eight-thread default; expose higher counts as explicit overrides,
  without a universal performance claim. Targeted unit coverage: 131 tests plus
  eight PyMOL bridge tests. Native real-compound/cluster navigation, paired and
  full-window checks passed using a disposable copy of the completed study;
  the real study and original diagrams/reports remained unchanged.

### Screening duration retention and isolated execution benchmark (2026-10-15)

- User requested a full same-protocol example against the retained two-compound
  2R8N screen and preservation of elapsed time in Screen ligands.
- Retain total wall time from existing job start/finish timestamps, including
  preparation, docking, analysis and reporting; update it while running and keep
  it after completion/reopening. Unknown/missing timestamps stay explicitly
  unavailable. No authoritative-state edits or new timing source are needed.
- Isolated, sequential shared-grid Vina API benchmark: automatic CPU versus
  eight threads, exact retained prepared inputs, five seeds × three conformers ×
  two compounds, same box/receptor/refinement/search settings, same retained
  2 Å clustering override and top-three analysis/report pipeline. No production
  default change, GPU port, parallel jobs, new chemistry or duplicate baseline.
- This protocol is exploratory-authorized, not experimentally pose-recovery
  validated. Compare to historical docking poses, not to invented crystal poses.
  Instrument setup/grid/search/analysis separately; historical worker timing is
  729.08 seconds, distinct from the user's roughly 16-minute observation.
- Retained baseline/protocol remain hash-verified unchanged. Preparation reuse
  must be disclosed; eight threads does not mean affinity to performance cores.
- Run: `validation/runs/vina-execution-20261015_095135/`.
- Completed: automatic shared-grid execution plus analysis/reporting 10:31;
  eight threads 9:42, versus historical supervised 12:09. Exact preparation was
  reused, so this is not a matched full-preparation timing comparison.
- All 30 PDBQT outputs (450 poses), two cluster tables and six PLIP interaction
  subtrees per arm match the baseline. Both complete reports were generated.
  A wrapper runtime error was explicitly recovered in analysis only, without
  rerunning completed docking. Source protocol/baseline hashes are unchanged.
- Installed duration display passed 105 targeted regressions and seven native
  read-only/reopen checks. Production search/thread settings remain unchanged.

### Selected-compound screening: visible worker phases (2026-10-14)

- Accepted current screening-step correction: the user cannot tell which
  compound or operation is running; a generic count obscures preparation and
  slow PLIP/rendering phases. Add immediate submission feedback and atomic,
  advisory parent/compound worker milestones consumed by the existing host poll.
- Show compound index/name, protocol pH during state/conformer preparation,
  ligand atom preparation, site/repeat/seed during docking, clustering, 3D/PLIP
  generation and the final library report. Preserve terminal process authority;
  a phase record/output file never establishes scientific success.
- Count both single/multiple-site outputs; label the initial job count as planned
  because state enumeration may change it. Do not infer full completion from
  reaching that estimate. Failed earlier compounds remain explicitly disclosed.
- Label library depictions as input chemistry/charge, not pH-adjusted prepared
  states. No preview chemistry, molecule spacing, locked parameters or docking
  defaults change. Existing running jobs are not stopped/restarted for this.
- Acceptance: advisory I/O failures do not stop work, bad/missing records fall
  back safely, phases reach the GUI, custom pH retained, launch is visibly pending
  before the host call, no duplicate or real docking jobs during validation.
- Verified: 60 scientific/worker tests and 100 GUI/host regressions pass, plus
  12 native phase-polling/failure checks and 19 real-host library/viewport checks.
  Results: `validation/runs/screening-feedback-20261014.JNvSHZ/`. The active user
  screen was read only and left running; no scientific commands were duplicated.
- Broader journey suite: five of six pass; the known-ligand control fixture
  fails before creating any job with "Control output directory must not already
  exist" after component preflight. Reproduced with the prior installed desktop
  module too, so this is a pre-existing separate control-startup acceptance bug,
  not evidence that this screen failed. Retain for the next end-to-end correction.

### Screening settings: brief visible explanations (2026-10-14)

- Accepted teaching/usability correction: representative count and clustering
  distance were unexplained in the supported screening step. Add concise inline
  help for output, analysis, representative count, RMSD cutoff, failure handling
  and exploratory authorization; no new settings or workflow branches.
- Distinguish pose groups from compounds/total poses, and receptor-frame
  clustering from RMSD to an experimental reference. Preserve the 1.5 Å default
  and explicit saved overrides, all payloads and locked-protocol chemistry.
- The user confirmed molecule whitespace is acceptable: leave the renderer,
  preview sizing, margins and navigation unchanged.
- Acceptance: readable wrapping help at small/large widths, unchanged values and
  launch signals, no docking or modification of an existing study/protocol.
- Verified: 100 GUI/host regressions and 41 isolated native checks at
  960/1100/1440 widths; help wraps without horizontal scrolling or clipped text.
  Results: `validation/runs/screening-guidance-20261014.JcOFRo/`. Molecule
  rendering and preview geometry were not changed.

### Paginated ligand-library review (2026-10-14)

- Accepted usability/performance correction requested by the user: large SDFs
  currently instantiate every GUI row and reparse the full library per preview.
- Render 50 rows per page by default, adjustable page size and explicit previous/
  next/jump navigation. Selections are library-wide, survive page changes and
  still drive the exact workload/run subset. Page navigation is not selection.
- Select-all/clear explicitly cover all pages; invalid rows remain visible and
  cannot be selected. Pagination does not drop or limit source records.
- Cache reviewed molecule snapshots and a bounded number of 2D previews in the
  scientific host. Use file-change guards for preview reuse and full source-hash
  checks before workload/launch; no weakened scientific source validation.
- Validate 1,000/10,000-record libraries and cross-page selection. This remains
  initial full-library indexing, not unlimited-memory streaming or CSV/XLSX work.
- Compound-cycle jump correction: use the same visible-cell navigation table as
  pocket review, and a paint-only preview widget whose layout hints do not change
  for loading/errors/images. Do not recenter visible text or resize the preview
  when focus/current compound changes.
- Verified: 57 scientific/import/screening regressions and 99 GUI/host regressions
  pass. Native checks with small and 10,000-record sources preserve layout and
  table/outer scroll positions for clipped-cell clicks, including focus entering
  from another field. Cross-page selections drive the exact host workload.
- Synthetic size test repeats retained 28-heavy-atom rilpivirine records: 1,000
  indexed in ~0.24 s, 10,000 (~65 MB) in ~2.39 s; cached preview ~0.0003 s and
  full-hash subset validation ~0.087 s at 10,000 on this machine. This is an input/
  UI-size test, not diverse-library chemistry or docking-performance validation.
- Results: `validation/runs/ligand-pagination-20261014.J1773e/`. No docking jobs
  ran, source coordinates/protocol were unchanged. Host caches at most two binary
  library snapshots and 32 images per snapshot; fresh full hashes gate launch.

### MOL ligand input (2026-10-14)

- Accepted bounded input correction: the chemistry reader supports MOL, but GUI
  selection and folder/workload discovery only offered SDF.
- Single V2000/V3000 MOL, case-insensitive SDF/MOL folder discovery, readable
  picker labels and CLI parity. MOL imports must contain exactly one valid
  molecule; normalized internal SDF retains original source provenance, bond
  orders, charges, stereo, hydrogens and input coordinates. Normal protocol
  preparation still runs later; importing does not dock or approve anything.
- Verified with V2000/V3000, mixed/upper-case folders, typed stereo/charge/H and
  coordinate preservation, invalid and multi-record MOL rejection, and GUI picker
  regressions. Installed together with the accepted compound-selection slice.

### Selectable ligand-library review and tabular SMILES import (2026-10-14)

- User explicitly changed priority: implement SDF/MOL compound selection next,
  after completing MOL input support. This is accepted under the scope gate.
- Smallest vertical path: SDF/MOL record table, 2D preview, explicit selected
  subset, workload/run parity, source-record identifiers and hashes in the run
  record. No silent filtering, deduplication or default chemistry changes.
- Tabular extension remains a separate follow-on: explicit SMILES/name column
  mapping, sheet choice for XLSX, per-row parse errors and exact original row
  provenance; never guess a column, evaluate formulas, or discard invalid rows.
- Follow-on explicitly authorized and implemented 2026-10-17 (see the current
  approved-tabular entry). Header detection suggests only; user approval is
  required. The earlier deferral below describes the original SDF/MOL milestone.
- Cost: adds a review/import state and new provenance/host payload contracts,
  plus table dependencies and failure handling. Finish/test the SDF/MOL selection
  path before adding CSV/XLSX. Existing all-compound CLI screening stays available.
- SDF/MOL selection implemented: asynchronous read-only host inspection/2D
  depiction, no automatic row selection, checkbox-driven hash-bound subset,
  read/preview/error gating and retained full record ledger. Changing selection
  invalidates workload; changed files fail before worker launch and again before
  CLI materialization. Only selected records enter docking outputs/reports.
- Verified: 54 scientific import/selection/screening/chooser regressions, 95 GUI/
  host-client regressions, and 15 native real-host checks at 1440/1100 widths.
  Native acceptance never launched docking and left the protocol byte-identical.
  Results: `validation/runs/ligand-library-final-20261014.5QK3j6/`.

### Report target identity and source species (2026-10-14)

- Accepted report-completeness correction: the heading only identified the input
  filename (for example Target: 2R8N), not the protein and source organism.
- Replace that heading with deposited protein/entity name and fragment, preserve
  structure accession, and put source species directly below it. Multiple proteins
  retain entity/chain-specific species; expression host is not source species.
- Local mmCIF or PDB annotations only; no new lookup, docking, approval or network
  dependency. Preserve the metadata snapshot in new protocols for portable reuse.
  Older metadata can be supplemented from its exact retained coordinates; absent
  annotations are explicitly described as not recorded, never guessed from a name.
- Existing completed reports/bundles are not overwritten or silently regenerated.
  Validate the header with the retained 2R8N input in a separate report preview.
- Verified: 95 identity, structure-input, coordinate-evidence, protocol and report
  regressions passed, including real PDF text and portable-bundle round trip.
  Thirteen additional asynchronous workflow tests passed after the change.
  The three-page 2R8N preview was visually reviewed; the original study files
  remained byte-identical and no figure/docking/PLIP calculation was repeated.
  Preview: `validation/runs/report-target-identity-20261014.iUnTOs/`.

### Completed finalization remains visibly running (2026-10-14)

- Demonstrated current acceptance failure: the user's finalization completed in
  about 15 seconds with report and bundle saved, but the GUI stayed at revision 14
  with a moving bar and elapsed 0:00 while authority was already revision 20.
- Cause: duplicate StudyWindow.showEvent definitions; the later initial-view
  handler overrode the handler that starts persisted-state polling.
- Smallest correction: merge the handlers, start/restart polling on show, and
  refresh immediately. Poll elapsed time and service health on unchanged revisions
  without rebuilding tables/pose views; redraw when authoritative state changes.
- No job retry, state edit, source change or protocol regeneration. Real retained
  phase messages and completed outputs drive the UI; an animated bar is not proof
  that calculation is progressing.
- Acceptance: visible window automatically observes running → phase update →
  completed/failed, hides the bar and enables saved-output actions, elapsed advances
  without revisions, hide/show restarts polling, and unchanged ticks do not reload
  poses or write scientific state.
- Verified: 134 GUI regression tests, 13 native automatic-polling checks, and
  126 paired PyMOL checks with polling enabled. A read-only opening of the user's
  completed revision-20 study cleared the activity bar without changing its bytes.
  Native results are in `validation/runs/workspace-polling-20261014.9FnyPD/`.
  Polling avoids native PyMOL's lock during ray export, preserving responsive
  render feedback/cancellation; initial preparation feedback remains visible
  until the application host acknowledges submission.

### Finalize protocol: visible teaching guidance (2026-10-14)

- User identified unexplained settings and unused space in the current supported
  finalization step. Explicit authorization is not meaningful without understanding
  the recipe, workload and absence of an experimental pose-recovery control.
- Bounded current acceptance correction: always-visible plain-language explanations
  beside every option, clearer labels, accessible descriptions, live shapes × repeats
  workload hint, and modeless per-option/full teaching guide. Guidance is local and
  distinguishes chemical state, conformer, search, pose and later cluster.
- Explain pH versus solvent, MMFF94 vacuum minimization, within-run energy-window
  filtering, repeatability versus correctness, and approval versus validation.
  Detail links are optional; no lookup occurs simply by reading help.
- Existing controls, defaults, typed payloads and authority remain unchanged.
  No new scientific settings, automatic approval or docking job. At narrower widths
  text wraps and the existing stage scroll area keeps actions reachable.
- Acceptance: all settings explained visibly; current-value guide; default/payload
  parity, no authority signals on help, no text collision at 960/1280/1440 widths.
- Verified: 82 GUI regressions, 19 finalization/workflow tests in the scientific
  runtime, and 66 native layout/guide checks. Native screenshots are retained in
  `validation/runs/protocol-guidance-20261014.jrdfV4/verified/`. Scientific report
  tests are run in the scientific runtime, not treated as GUI dependency tests.

### Optional ray-traced visual exports (2026-10-14)

- User explicitly approved an optional ray PNG after reviewing the slower-render
  tradeoff. This extends the current export acceptance slice, not scientific
  analysis or a second viewer; existing fast OpenGL export remains available.
- Same engine and current camera/visibility, native output dimensions, CPU ray
  rendering off the GUI thread. An application-modal busy indicator prevents
  conflicting user scene changes; Cancel interrupts only PyMOL's visual render.
  No destination is published on cancellation or failure.
- Available for 3D images and clean paired panels, including full PyMOL. Retained
  2D images stay unchanged; metadata distinguishes ray versus OpenGL rendering.
- Acceptance: real CPU ray PNG, main/paired/full action parity, responsive cancel,
  no stale image buffer, unchanged camera/contacts/coordinates/scientific state,
  and no duplicate engine or job. Arbitrary output sizes remain separate.
- Verified: 113 regression tests, 126 native paired checks including experimental
  and docked ray exports, and 96 native full-PyMOL checks. Results are retained in
  `validation/runs/paired-interactions/ray-option-20261014.pjrF9B/`.
  Cancellation/failure preserve existing destinations. Native ray images may
  occlude labels that OpenGL floats in front; this is disclosed in the guide.

### Current review image exports (2026-10-14)

- User-requested completion of supported results review/export: customized live
  PyMOL views and particular retained 2D figures had no clear save path in the
  paired/main workspace. Screenshots include controls or lose source resolution.
- Bounded current-milestone implementation: one compact Save image menu for
  current native PyMOL PNG, original-resolution 2D diagram, and clean paired
  panels. Main workspace also saves selected retained report figures and the
  pocket-ranking plot; full PyMOL exposes the same current-view PNG action.
- The initial slice used existing retained data and the one live engine; no ray-tracing controls,
  new pane, network operation, docking or PLIP rerun. Native-resolution PNG is
  the first supported format; arbitrary output sizes/vector export are separate.
- Exports are presentation derivatives, not approved reports or pipeline input.
  PNG metadata records context; retained source files cannot be overwritten;
  atomic saving preserves existing destinations on encoding failures.
- Acceptance: customized visibility/camera retained, original 2D pixel size,
  color-matched paired key, experimental/docked basis, cancellation/error safety,
  absent-source action gating, and unchanged scientific state/source files.
- Native checks passed for both experimental and docked paired exports (123
  checks), and the full PyMOL menu action/lifecycle (94 checks). Native export
  must run inside the upstream widget's valid OpenGL context; a plain PNG call
  outside that context did not produce a file and is not used as a fallback.
- Installed after 109 image-export, linked-review, adapter and desktop regression
  tests passed. Native-image dimensions are preserved; PNG captures active native
  selections if they are shown, so users may deselect those before saving.

### Paired review: discoverable optional 3D labels (2026-10-14)

- Accepted bounded correction to existing residue inspection: labels were only
  discoverable through 3D picking, with no visible way to show or clear them.
- Smallest correction: a compact Residue labels checkbox on the existing cartoon/
  contact control row. On labels visible, exactly mapped contact residues; off
  clears only review-added labels. Individual picks still toggle one label and
  synchronize the checkbox without invoking bulk labeling. Hiding a residue
  removes its label; labels start off in each paired review.
- Shared by experimental and docked-pose review. No new pane, engine, chemistry,
  docking option or scientific decision; label styling remains unchanged.
- Acceptance: real label representation on/off, independent chain identities,
  unchanged camera/contacts/2D, no atom-selection markers, and original scene
  restored on close. This finishes current review usability, not scope expansion.
- Verified: 102 linked-review, adapter and desktop regression tests pass; native
  experimental and docked checks pass in
  `validation/runs/paired-interactions/label-switch-20261014.g5qeFL/verified/`.
  Clearing text alone left the native label representation enabled; explicit
  show/hide now keeps actual PyMOL representation and checkbox state consistent.

### Paired review: residue-fragment scale and experimental provenance (2026-10-06)

- Accepted current review-step correction: schematic residue bonds stayed at
  15 drawing units while expanded ligand bonds reached 37.5, making residue
  fragments disproportionately small; experimental-control views were described
  as docking poses because the basis text depended on a title substring.
- Smallest change: residue fragment bonds at 70% of the ligand's median 2D bond
  length, before collision-aware packing; explicit experimental/docked source-kind
  metadata and safe compatibility for established experimental artifacts.
- The user also requested larger atom symbols and slightly heavier bonds:
  diagram text size 10 (up from 8; originally 6.5), bond width 0.9 (up from 0.8;
  originally 0.65); packing
  measures the same text size. No 3D representation or scientific data changes.
- Larger symbols exposed a null-intersection error in unused circle-representation
  label placement. Static rendering now permits only the actual molecular
  representation and fails closed if any structure, contact or annotation is lost.
- GUI label enlargement was withdrawn after the user clarified that the
  sidechain drawings, not their names, needed changing. Labels retain the
  established renderer styling and exact clickable outlines.
- Retained old report images remain unchanged on opening. Legacy diagrams without verified
  click regions do not promise clickable residue names. Updating a report image
  requires rendering from its exact retained ligand/receptor/XML, not redocking.
- Existing experimental caches refresh their display derivative on Render 2D,
  reusing exact typed coordinates and PLIP XML. The old PNG and result metadata
  are preserved; no docking or PLIP rerun is needed. Report regeneration checks
  the layout revision before reusing a previously rendered detailed diagram.
- Acceptance: source coordinates/contact calls stay unchanged; fragment bonds
  have the declared relative scale; packing remains collision-free and clicks
  map to the same exact residue; experimental PLIP contacts are explicitly
  calculated from experimental coordinates, not a docked prediction.

### Retained control/report visual consistency (2026-10-05)

- Accepted correctness correction: control PLIP diagrams were not recognized by
  the linked GUI resolver; standalone cluster scenes used different colors, and
  calibration snapshots could recall pose 1 for the best-RMSD role.
- Smallest change: exact hash-verified diagram/ligand/receptor/XML sidecars,
  cluster-rank color propagation, explicit scene recall, and control figure labels.
  No new pane, docking, chemistry, dependency, or implicit approval.
- Acceptance: changed files invalidate the link; top-three colors survive a
  closest-pose role; outside-top-three closest ligands are green; experiment is
  magenta. Local per-run diagnostics disclose that global ranks are not known.
- Following the retained-pose Indinavir comparison, the user approved 1.5 Å
  as the software default. Explicit saved cutoffs and the separate 2 Å recovery
  threshold remain unchanged; this example does not establish a universal cutoff.

### Paired review: visible residue links and compact controls (2026-10-04)

- Accepted bounded usability correction to the existing linked-review step:
  outline every verified clickable residue name over the detailed 2D image;
  move cartoon/contact master switches below the contact legend and compact
  the residue checkbox row. No new rendering, chemistry, or workflow option.
- Acceptance: boxes and clicks share exact fit/zoom/gutter geometry; retained
  image bytes remain unchanged; the native paired view still centers the exact
  source residue without changing 2D zoom. Legend precedes master switches.
- The older rendering mentioned by the user appeared only in the chat preview,
  not the app; do not migrate or regenerate existing report images for this.
- Verified and installed: eight linked-review unit tests, 15 adapter tests,
  70 desktop tests, and 98 isolated native PyMOL checks pass. Native preview:
  `validation/runs/paired-interactions/residue-outline-controls/paired.png`.

## Purpose

Docking Universal benefits from ideas discovered while testing the interface,
but repeatedly implementing them before the core workflow is complete makes the
GUI harder to finish and validate. This document preserves those ideas without
silently turning each one into current work.

The active objective is one reliable, chronological, rigid-receptor workflow:

> structure input → preparation → scientific interventions → pocket and
> experimental-evidence review → region approval → protocol finalization →
> screening → linked 2D/3D results review → final reports.

An idea can be valuable and still be deferred. Recording it is not approval to
implement it.

## Implementation gate

Before adding an unplanned GUI option, panel, workflow branch, or dependency,
answer these questions:

1. Does it correct scientific validity, data loss, privacy, or a reproducible
   crash in the supported workflow?
2. Is it necessary to complete an already-supported step in the chronological
   rigid-receptor workflow?
3. Does a current acceptance test or real end-to-end run fail without it?
4. Does it replace existing complexity with a demonstrably simpler interaction
   rather than adding another way to do the same thing?
5. Can it be implemented and tested without delaying the current vertical
   milestone?

Implement immediately only when questions 1, 2, or 3 have a concrete yes and
the change is the smallest defensible correction. Question 4 can justify a
replacement after its migration and regression risk are understood. Otherwise,
record the idea here and continue the active milestone.

The implementation case must name the observed problem, evidence, affected
workflow stage, smallest proposed change, acceptance test, and what current work
would be displaced. “Useful,” “nice,” or “might help” is not enough by itself.

## Expected pushback

When a new request does not pass the gate, the development response should:

- acknowledge the scientific or usability value;
- explain why it is not required for the current milestone;
- identify the additional state, dependency, testing, or interface complexity;
- record it below with a clear revisit condition; and
- recommend continuing the current blocking task.

Pushback should be specific and evidence-based, not dismissive. The user can
explicitly change the active milestone, but the cost and displaced work should
be stated before implementation begins.

## Idea record template

Copy this block for each new idea:

```text
### Idea title

- Date recorded:
- Status: inbox | deferred | accepted for current milestone | rejected | implemented
- User/scientific problem:
- Proposed behavior:
- Evidence or example:
- Dependencies and risks:
- Smallest acceptance test:
- Revisit condition:
- Related roadmap section:
```

## Deferred ideas

### Cryo-EM map evidence linked to atomic PDB models

- Date recorded: 2026-10-04; future-update inquiry, not implementation approval.
- Proposed behavior: expose experimental method and linked EMDB map/validation
  metadata for an existing atomic model; later offer local, opt-in map overlays.
- Boundary: cryo-EM atomic models are already deposited in PDB. EMDB archives
  reconstructed volumes; EMPIAR archives raw images, not ready-to-dock receptors.
  A map alone cannot be silently converted into a docking receptor.
- Dependencies/risks: large map downloads, origin/grid/frame agreement,
  resolution and local ligand support, explicit provenance, no automatic claim
  that an EM density feature verifies ligand chemistry or pose.
- Acceptance/revisit: after rigid GUI acceptance, validate one PDB/EMDB linked
  model with exact-frame map overlay and clear model-versus-map evidence labels.
- Primary sources: https://www.ebi.ac.uk/emdb/ and
  https://www.ebi.ac.uk/empiar/about/.

### Benchmark OpenFF Sage 2.3.0/AshGC for ligand minimization

- Date recorded: 2026-10-04; evaluation requested, not production replacement.
- Current pipeline: MolScrub states → RDKit ETKDGv3 embedding → MMFF94 (UFF
  fallback) minimization/ranking → Meeko with Gasteiger charges. Screening
  defaults to three retained conformers per state, not three generated total;
  embedding attempts four times the retention budget and counts are configurable.
- Observed limitation to benchmark: RMSD pruning precedes minimization; there
  is no second diversity filter after relaxation, so retained conformers can
  converge to similar geometries. Address coverage before claiming a force-field
  swap compensates for a small retained ensemble.
- Hypothesis: unconstrained Sage 2.3.0 with its fitted AshGC charge model may
  improve ligand geometries and starting ring conformations. Sage is not itself
  the conformer sampler. Neither force-field recency nor three-conformer budget
  establishes improved Vina pose recovery.
- Boundary: native Vina scoring ignores supplied partial charges; charges still
  affect Sage minimization. AD4 scoring is a separate case. External Meeko
  charges require explicit read mode and verified atom mapping, not default
  Gasteiger reassignment. Do not mix Sage 2.3.0 with AM1-BCC as if identical.
- Smallest future test: same enumerated states/seeds/initial conformers and
  docking effort, compare MMFF versus Sage geometry/strain, unique ring diversity,
  convergence and coverage, runtime and known-pose recovery. Include rigid,
  flexible, saturated-ring, ionized and supported unusual-chemistry ligands;
  avoid selecting only the lowest-energy vacuum conformers after collapse.
- Risks: OpenFF/NAGL/OpenMM dependencies, model-file pin/cache/disclosure,
  stereochemistry/atom identities, supported chemistry, reproducibility and
  cross-platform packaging. No new backend installed in the live environment.
- Revisit: isolated benchmark authorization after current GUI corrections;
  promote only with measured benefit, retained provenance and explicit fallback.
- Primary sources: https://github.com/openforcefield/openff-forcefields,
  https://docs.openforcefield.org/en/latest/examples/openforcefield/openff-interchange/conformer_energies/conformer_energies.html,
  https://autodock-vina.readthedocs.io/en/latest/faq.html.

### Isolated solvent-aware conformer A/B validation

- Date accepted: 2026-10-04; user explicitly requested a lightweight local test.
- Scope: `validation/conformer_ab.py` and `docs/conformer-ab-benchmark.md`;
  no GUI options, production defaults, dependency installation, or network work.
- Shared independent ETKDG pool, post-minimization symmetry-aware heavy-atom
  RMSD pruning in both arms, default MMFF94 vacuum versus GFN2-xTB/ALPB water.
  Optional matched GFN2 vacuum baseline isolates solvent from energy-model choice.
- Start with a larger flexible ligand (indinavir), then several matched bound
  ligands. Optional fixed-receptor/box equal-budget Vina redocking records
  top-score recovery separately from best experimental RMSD among all poses.
- Acceptance boundary: real solvent/redocking runs require a local xTB binary;
  mocked backend tests are not scientific validation. Promotion remains deferred
  until controls show reproducible benefit, acceptable failures and runtime.
- 2026-10-05: user authorized four additional matched controls. The completed
  indinavir control recovered the crystal pose within 2 Å for both methods on
  all three seeds; lowest-score pose RMSDs were 1.22–1.32 Å for MMFF94 and
  0.72–0.74 Å for water GFN2-xTB. Water preparation took about five minutes,
  versus about two seconds for MMFF. Keep this experiment separate from GUI
  defaults and retain the equal docking budgets for the four-control extension.

### Optional slower conformer preparation with evidence-based guidance

- Date recorded: 2026-10-05; status: deferred pending matched-control results.
- User proposal: make solvent-aware preparation optional, potentially recommend
  it for larger ligands, while acknowledging the substantial runtime cost.
- Boundary: a 0.96 Å versus 0.72 Å best-of-all-poses result is not by itself a
  useful reason to change defaults; lowest-score pose recovery is the primary
  endpoint. Both methods succeeded on the initial control. Atom count alone
  is not yet a validated decision rule; flexible bonds, ring topology and
  charged groups may also matter. Do not invent a size threshold from one case.
- Revisit: review four more controls, failures and runtime; then decide whether
  an opt-in backend earns its dependency, testing and packaging costs. Do not
  add another GUI setting or automatically run extra docks at this stage.

### Flexible docking and flexible-residue selection

- Date recorded: 2026-09-24 (consolidating earlier design discussions).
- Status: deferred until the complete rigid-receptor GUI passes acceptance.
- User/scientific problem: related structures, B-factors, occupancy, backbone
  movement, and rotamer changes may show that a rigid receptor makes an
  experimentally supported site inaccessible.
- Proposed behavior: review consolidated evidence, synchronize candidate
  residues with PyMOL, explicitly select flexible residues, and run a validated
  AutoDock Vina flexible-receptor workflow.
- Dependencies and risks: separate receptor preparation, atom/residue mapping,
  control evidence, protocol designation, report semantics, and engine-specific
  validation. Evidence must never be presented as proof of flexibility.
- Smallest acceptance test: a target-matched control demonstrates a valid
  rigid/flexible preparation and reproducible pose-recovery path with retained
  mappings and exclusions.
- Revisit condition: the rigid-receptor GUI completes its real-engine acceptance
  matrix.

### Parallel studies or simultaneous docking jobs

- Date recorded: 2026-09-24.
- Status: deferred.
- User/scientific problem: experienced users may eventually want throughput
  across studies.
- Proposed behavior: manage several independent jobs concurrently.
- Dependencies and risks: resource scheduling, process ownership, progress and
  cancellation semantics, GPU/CPU contention, and substantially broader failure
  recovery. The current design deliberately has one authoritative run.
- Smallest acceptance test: isolated outputs and deterministic cancellation for
  two concurrent studies without oversubscription or state crossover.
- Revisit condition: single-run lifecycle, recovery, and shutdown are proven on
  supported platforms.

### Direct manipulation of docking boxes in 3D

- Date recorded: 2026-09-24.
- Status: deferred.
- User/scientific problem: dragging a box may feel more immediate than editing
  numeric center and size fields.
- Proposed behavior: manipulate box faces or handles in embedded PyMOL.
- Dependencies and risks: coordinate-frame fidelity, picking conflicts, unit
  conversion, accidental scientific changes, undo, and approval invalidation.
- Smallest acceptance test: round-trip geometry exactly matches the retained
  numeric configuration and invalidates stale approval.
- Revisit condition: numeric box editing and immediate 3D updates are complete
  and validated.

### Full dark theme

- Date recorded: 2026-09-24.
- Status: deferred.
- User/scientific problem: a dark workspace may be preferable in some viewing
  environments.
- Proposed behavior: theme the full desktop using the approved inverted assets.
- Dependencies and risks: scientific colors, warning contrast, figures, PyMOL,
  platform styling, and accessibility must remain consistent.
- Smallest acceptance test: contrast and semantic-color review across all
  workflow states at standard and high DPI.
- Revisit condition: the restrained light-theme token system and functional GUI
  acceptance are complete.

### Versioned GitHub Wiki

- Date recorded: 2026-09-24.
- Status: deferred.
- User/scientific problem: users will need an approachable teaching and
  troubleshooting layer in addition to versioned technical documentation.
- Proposed behavior: publish version-aware workflow, installation, evidence,
  viewer, and troubleshooting pages.
- Dependencies and risks: publishing before the workflow stabilizes creates
  duplicated and quickly outdated instructions.
- Smallest acceptance test: every page identifies a compatible release and
  links to the repository documentation that remains authoritative.
- Revisit condition: the first stable GUI workflow is usable.

## Accepted current work

### Stable pocket-navigation camera and compact full-PyMOL console

- Date accepted: 2026-10-04; user reports moved protein positioning on region
  switches and excessive command-area height on detachment.
- Smallest correction: no automatic recenter or rotation-pivot change on box
  navigation; preserve user rotation, pan and zoom in embedded/companion views.
  Only widen clipping if required. Start the upstream command dock at its
  minimum usable height, retaining menus, console and resizing. The native
  shortcut-button block starts collapsed behind a compact Controls toggle;
  automatically reveal it during native calculations so Abort remains usable.
- Acceptance: rotate and translate the live protein, click P1/P2/plot and
  detached selections repeatedly, compare all camera/pivot components;
  compact initial console remains expandable and executable after re-detach.
- Boundary: explicit paired-review ligand/residue centering stays available;
  no scientific coordinates, cached reports, decisions or new options change.
- Verified: 104 targeted unit tests, 19 real pocket-surface GUI checks, and
  91 full-PyMOL checks pass. Rotated/panned camera remains fixed across P1/P2/P4;
  console starts at 84 logical pixels in the tested native environment, can
  expand manually, and reveals Abort for simulated native calculation progress.
  Evidence: `validation/runs/pocket-space-gui/stable-user-camera/` and
  `validation/runs/full-pymol/stable-camera-compact-console-final/`.

### Explicit online versus local-only PDB evidence review

- Date accepted: 2026-10-04; users may lack connectivity or deliberately
  avoid online evidence queries. A failed search must not look like a scientific
  finding that no deposited ligand supports the site.
- Smallest correction: clarify the existing search checkbox and disclose its
  sequence query; show a persistent evidence-panel notice for disabled,
  unavailable and incomplete lookup. Keep successful no-match searches distinct.
- Scope: PDB evidence acquisition only, not a global network/offline mode.
  Structure downloads and consent-gated chemical definitions remain separate.
  Local preparation, docking, visualization and retained evidence stay usable.
- Acceptance: disabled mode never calls the collector; simulated connection
  failure preserves prepared artifacts and displays an unavailable warning;
  main/full evidence views agree; partial retrieval does not claim no evidence.
  No connectivity ping, automatic retry, silent mode change or new dependency.
- Verified: 93 targeted unit tests and 76 isolated native full-PyMOL checks
  pass, including warning wrapping and persistence through candidate navigation.
  Offline failures are simulated; validation does not upload receptor sequences.
  Native evidence: `validation/runs/full-pymol/pdb-lookup-status/verification.json`.

### Unclipped starting scenes and restrained selected-box edges

- Date accepted: 2026-10-04; user prefers complete scene geometry and reports
  selected docking-box edges distract from the pocket.
- Smallest correction: expand starting near/far planes for all enabled scene
  coordinates (including the live CGO box) with a rotation-safe margin; do not
  zoom, pan, alter coordinates or continuously override manual clipping.
  Reduce the selected box cylinder radius from 0.35 to 0.22 Å, retaining color.
- Scope: managed embedded, paired, restored-report and full-PyMOL opening views;
  no report-image rewriting, additional settings UI or scientific changes.
- Acceptance: deliberately narrow slabs become complete at scene initialization
  and full detach; rotation/zoom remain fixed; paired/docked controls and return
  restoration pass. CGO box bounds must be included explicitly because PyMOL's
  atom extent query omits them. This replaces existing styling only.
- Verified and installed: 16 adapter, eight linked-review and 70 desktop unit
  checks; 103 paired/retained-scene checks and 73 full-PyMOL checks pass.
  Native evidence: `validation/runs/paired-interactions/unclipped-scenes-final/`
  and `validation/runs/full-pymol/unclipped-scenes-box/`. Full-shell region
  navigation restores framing but retains expanded clipping for its new box.

### Compact linked-review key and discoverable centering/labels

- Date accepted: 2026-10-04; user reports an oversized clickable legend,
  unclear 2D ligand target and unreadably small/occluded 3D residue labels.
- Status: implemented; unit and native deposited/docked-pose checks pass.
- Smallest change: replace the button grid with inline clickable legend text;
  box the existing 2D heading as an explicit named ligand-centering target;
  larger outlined foreground residue labels. No extra panel or render dependency.
- Scope: shared paired viewer for deposited ligands and retained docked poses.
  Residue-label links remain exact/hash-verified; side-chain drawing is not
  guessed to be a clickable residue. Scientific coordinates and decisions stay fixed.
- Acceptance: compact key toggles each type without changing other types;
  named ligand target centers without zoom/diagram changes; native labels are
  larger and foreground, and scene/settings restore on close. Exercise a
  retained docking-pose path as well as deposited evidence.
- Displaced work: replaces current controls/settings only, not a new
  docking workflow or broad docking acceptance campaign.
- Native evidence: `validation/runs/paired-interactions/compact-foreground-final/`
  verifies real Qt legend clicks, two-line maximum key on the tested pane,
  boxed MK1 ligand centering, outlined foreground labels, original
  foreground setting restoration, and retained cluster_031 docking review.
- Older docking diagrams retain their existing colors and may lack verified
  label hit regions; this test does not migrate them or certify all results
  workflows. Broad exact-pose/renderer acceptance remains part of the roadmap.
- Follow-up: 22-point outlined labels replace the overwhelming 32-point bold
  preview. Native reproduction found `load_cgo` defaults to appending states;
  type toggles must explicitly replace state 1. Add actual state/payload
  validation, not just checkbox or adapter visibility flags.
- Regression evidence: all 93 native checks pass in
  `validation/runs/paired-interactions/displayed-state-fix/`; each hidden type
  is absent from the native state's cylinder colors, remaining types persist,
  restoration replaces the same state, and no stale states accumulate.

### Smooth pocket-space surfaces without accidental slab clipping

- Date accepted: 2026-10-04; user reports dimples and clipping in the new surface.
- Status: implemented; native previews and slab tests pass on 2R8N and 3QBF.
- Smallest correction: use an object-local smoothing probe on the grid display,
  without changing sampled points, their display radii, predictions or boxes.
  Expand only near/far planes when the selected surface exceeds the current
  slab; preserve rotation, pan and zoom, and never shrink the user's slab.
- Acceptance: before/after native previews on 2R8N and two-chain 3QBF;
  deliberately clipped surface becomes complete without camera recenter/zoom;
  repeated cached navigation keeps settings and scientific hashes unchanged.
- Boundary: smoothing is a visualization envelope, not a measured cavity or
  permission to fill/recalculate P2Rank's grid. No new GUI option is introduced.
- Display: object-local 1.4 Å rolling probe, solid surface, quality 2; sampled
  point positions and 1.02 Å display radii remain unchanged. Cached objects are
  restyled once; only near/far planes expand if needed.

### Legible contact geometry and clickable type key in paired review

- Date accepted: 2026-10-04; user reports barely visible PLIP lines and useless
  Shift group selections in the paired 2D/3D view.
- Status: implemented; unit and native two-chain paired-review checks pass.
- Smallest correction: render colored solid/dashed contact cylinders instead
  of device-dependent hairlines; turn the existing 3D key into per-type toggles.
  Keep the master contact and residue toggles independent. Suppress modified
  selection gestures only while the paired review owns the viewport; full
  PyMOL remains unrestricted. No new scientific interaction calculation.
- User-confirmed scope: the clickable type key controls 3D only. The retained
  2D diagram remains unchanged. Contacts use 0.12 Å-radius cylinders with the
  same PLIP endpoints/colors and dashed/solid distinction.
- Acceptance: each type hides/restores independently with unchanged camera,
  report coordinates/colors, diagram scale and other toggles; native modified
  drag creates no selection; previous scene/input behavior returns on close.
- Validation: `validation/paired_interaction_review.py` verifies all four
  present types independently, master-gate persistence, all-off restoration,
  Shift/Ctrl drags, diagram links, resize and unchanged study state. Evidence:
  `validation/runs/paired-interactions/thick-type-toggles-linked/verification.json`.

### Alpha pocket-space surfaces and linked-review interaction correction

- Date accepted: 2026-10-04; explicit user authorization to integrate the alpha
  visual following the isolated comparison, plus observed cached-opening and
  atom-picking problems in the paired review.
- Status: implemented; native 2R8N/four-pocket and two-chain 3QBF checks pass.
- Smallest correction: retain stable 2.5.1 scientific predictions/boxes; run
  pinned 2.6-alpha locally as an asynchronous visual-only worker, using unfilled
  grids and exact retained-prediction parity before attaching surfaces. Cache
  by receptor/prediction hashes; fail closed on mismatches. No receptor upload,
  new scientific decision or alpha prediction replaces an approved region.
- Paired review: restore cartoon with a visibility control; labels on exact
  residue clicks instead of persistent atom/bond picks; show contact geometry
  from the same PLIP XML with the established 2D blue/green/cyan color key.
- Acceptance: real alpha surface in native embedded/full PyMOL, per-rank
  switching with unchanged camera/palette/boxes; unchanged scientific state;
  cached/fresh timings and restoration; exact chain picking and contact geometry.
- Displaced work: replaces misleading residue-surface visualization rather
  than adding a docking engine choice. Alpha remains a visual-only prerelease
  dependency; report migration is separately recorded, not silently rewritten.
- Validation: `validation/pocket_space_integration.py` verifies the real
  worker and native surfaces on both examples. `validation/paired_interaction_review.py`
  verifies PLIP geometry, toggles, exact chain mapping, residue picking and scene
  restoration. Cached pair first-frame latency was about 0.08 seconds on the
  small fixture; the user's longer delay has not been reproduced or declared
  resolved by that measurement. Larger-target acceptance remains outstanding.
  `validation/pocket_space_gui.py` exercises the installed asynchronous worker,
  original rank IDs after filtering, exact box/surface palette, stable panel
  geometry and cached navigation without altering scientific state.

### Label the ligand evidence section and match its graph key

- Date accepted: 2026-10-04; screenshot-backed evidence-review clarification.
- Status: implemented in the shared main/full-PyMOL evidence panel.
- Observed problem: observation counts and a ligand table lack a section
  heading connecting them to the graph's green ring.
- Smallest correction: bold "Ligand evidence" header with the matching green
  ring, plus an explanatory tooltip distinguishing deposited observations from
  newly docked poses. Keep a compact fixed header and preserve the existing
  count area; geometry remains constant across candidate changes.
- Acceptance: same symbol and explanation, main/full panel parity, readable
  header, fixed layout when changing candidates, unchanged selection behavior.
- User-requested visual parity: a subtle green summary box shares the graph
  ring's outline color; the warning box uses the same amber outline and pale
  yellow fill as the `!` badge. Shared color constants prevent drift. Pocket
  identity colors and scientific representations remain unchanged.
- Follow-up correction: the green header/count box sits immediately above
  its ligand table, below the obstruction review and highlight controls.
  The main warning uses a fixed four-line viewport instead of six, a concise
  explanation, and complete text in the tooltip/optional Guide. Longer residue
  lists scroll without resizing the surrounding panels. Explicitly distinguish
  protein side-chain obstruction from all rotamer changes or ligand rotamers;
  the geometric test and separate conformational record are unchanged.

### Make the obstruction symbol's key visible

- Date accepted: 2026-10-04; screenshot-backed evidence-review correction.
- Status: implemented; regression validation recorded with this change.
- Observed problem: the small amber `!` and understated legend do not clearly
  connect the graph to the scientific caution below it.
- Smallest correction: a larger amber exclamation badge beside the candidate,
  the matching badge in the graph key, and a bold `! Possible ligand obstruction`
  heading in both main and full-PyMOL warning boxes. Clicking the badge inspects
  its candidate; it never approves it. Fixed panel sizes remain unchanged.
- Acceptance: matching symbol/meaning, selectable warning text, prominent
  heading, badge click dispatch, and no P1/P2 layout movement.
- Paired-review design requirement (implemented 2026-10-04): default balanced
  panes in a resizable, non-modal window with an adjustable divider. Diagram
  contacts and 3D residues must use the same source receptor/ligand pose;
  independent all-contact residue toggles remain part of linked-review work.

### Matched-source paired interaction review and obstruction details

- Date accepted: 2026-10-04; explicitly requested after paired-window mockups.
- Status: implemented and native-tested with the retained 2R5P/MK1/B/902 data.
- Interaction correction accepted 2026-10-04: diagram clicks center the exact
  residue/ligand in 3D without changing zoom, orientation, visibility or the 2D
  image. Only the existing checkboxes show/hide residue sticks. This replaces
  click-to-toggle behavior rather than adding another control; acceptance tests
  must prove the two actions remain independent, including hidden residues.
- Render 2D interactions opens a maximized, resizable, modeless 2D/3D window
  with an adjustable divider, borrowing the existing PyMOL viewport and engine.
  Experimental diagrams use the original deposited receptor and exact ligand
  coordinates, not an aligned ligand overlaid on the study receptor.
- All recorded PLIP contact residues have independent sticks toggles. Fresh
  primary/fallback renders include crop-normalized residue-label hit regions,
  bound to the exact image and PLIP XML hashes. No inference from label text
  alone is allowed. Older diagrams without verified links retain residue buttons.
- Checkbox toggles preserve camera, 2D zoom and colors, with no atom-selection
  markers. Closing restores the study scene, camera and user selections.
  Full PyMOL remains a separate mutually exclusive detached mode.
- The optional Details… popup explains the <2.0 Å and ≥0.5 Å clearance rule,
  displays available per-ligand measurements, and distinguishes obstruction
  evidence from all recorded conformational differences. No automatic popup
  or scientific approval is introduced.
- Acceptance: `validation/paired_interaction_review.py`; native checks and
  screenshot in `validation/runs/paired-interactions/native/`; fresh collision-
  free primary render plus source/hash and fallback-render regression tests.

### Keep decision evidence usable and clarify the P2Rank surface

- Date recorded: 2026-10-04, following the paired-review implementation.
- Status: next iterative correction; not implemented in the paired-review slice.
- Observed problem: Focus canvas hides the scientific-evidence dock alongside
  workflow/setup docks, making region selection harder. Evidence must remain
  accessible during decision review instead of trading it for empty canvas.
- Verified display meaning: the P2Rank adapter writes the listed protein
  residues into pocket atom files. PyMOL renders their molecular surface.
  This is a predicted-site residue surface, not a separately calculated cavity
  void or cavity-volume measurement. Existing "predicted pocket surface" help
  text needs to make this distinction explicit; the wireframe is the generated
  docking search box, and detector score is not docking affinity.
- Acceptance: useful evidence remains visible with focus enabled; labeling
  distinguishes site residues, detector score, and search box without changing
  the scientific artifacts or inventing cavity geometry.

### Pocket-local paired review and visible rendering progress

- Date accepted: 2026-10-04; correction to the existing linked-review acceptance.
- Status: implemented and native-tested on a deposited two-chain contact site.
- Observed problem: first generation appears inactive and whole-receptor framing
  makes multichain interactions too small to examine.
- Smallest change: non-modal indeterminate progress with elapsed time, then
  frame the exact ligand plus chain-specific contact sticks once. No protein
  surface or whole-protein cartoon in this paired view. Preserve the entire
  previous scene on return and keep subsequent clicks zoom-neutral.
- Acceptance: native paired-review exercise checks ligand-centered origin,
  no receptor cartoon/surface, visible progress and same-engine restoration;
  unit regression checks both exact chain mapping and one-time local framing.
- Displaced work: no workflow branch or dependency replacement; pocket-volume
  evaluation below remains separate from this usability correction.

### Evaluate an actual pocket-volume display, separate from protein surfaces

- Date accepted for isolated evaluation: 2026-10-04; the user explicitly
  prioritizes pocket geometry and is open to the alpha if needed.
- Status: initial evaluation completed; not a production dependency migration.
- Observed problem: the colored surface currently represents site residues,
  not the pocket's empty space. This is misleading for the user's decision
  review, particularly in multichain structures.
- Smallest test: run pinned P2Rank 2.6-alpha on retained 2R8N coordinates in
  an isolated validation directory, export its pocket grid, and compare
  predictions with stable 2.5.1. Show pocket-local grid/volume without the
  protein-residue surface; retain chain-spanning contacts and ligand centering.
- Risks: prerelease output schemas and geometric defaults, grid construction
  cost, visual sphere/isosurface inflation, and differences from closed-cavity
  volume. Record actual alpha behavior, not assumptions from develop docs.
- Boundaries: no existing study, score, box approval or default runtime is
  replaced. Test alone does not authorize production migration. Existing
  fpocket geometry is another possible route, so alpha is not the only
  possible cavity-display method.
- Related usability finding: the evidence worker runs PLIP and the local
  renderer before opening the paired review. First-generation delay needs
  visible progress; cached and fresh latency must be measured separately.
- Evaluation: official release archive SHA256
  `d0284cf47e2605c21c6285b30076f33cb7e509359fb9ed4b1808c3274f6f2592`.
  Stable and alpha prediction CSV records match on 2R8N and two-chain 3QBF.
  Alpha exports grids in about 2–3 seconds on these small examples. On 2R8N,
  default morphological filling warns that it did not converge and exports
  1,378 assigned points versus 695 without filling. Use unfilled data for this
  evaluation, not an undocumented corrective fill. For rank 1, all 265 sampled
  centers lie outside protein atom vdW radii (checked using PyMOL radii).
  That does not validate an interpolated surface as exact cavity geometry.
- Multichain caveat: both predictor versions attempted coordinate-free CCD
  downloads for JHG/GOL/CL/HOH, blocked by sandbox DNS; both still completed
  protein-only prediction with the same result. No receptor upload occurred.
- Evidence: `validation/p2rank_pocket_volume.py` and
  `validation/runs/p2rank-alpha-pocket-volume/comparison.json`, raw-grid,
  interpolated-space and old protein-site-surface PyMOL previews. GUI/report
  migration remains open; the production 2.5.1 pin is unchanged.

### Remove the redundant observation-load button in live review

- Date accepted: 2026-10-04; requested cleanup of an existing obsolete control.
- Status: implemented.
- Observed problem: "Show selected observations in interactive structure"
  implies a second action is required even though table selection updates 3D.
- Smallest correction: hide it for embedded/full PyMOL review and describe
  select/deselect behavior. Preserve the manual load action for the companion
  fallback. Keep Render 2D interactions, multiselection and approval unchanged.
- Acceptance: no load button in embedded review after polling/selection;
  table still emits selected paths; companion action remains usable.

### Show/hide the scientific workflow rail

- Date accepted: 2026-10-04; parity correction for an existing GUI panel.
- Status: implemented; toolbar toggle and dock close button share visibility.
- Observed problem: the workflow rail cannot be hidden/restored individually
  like other docks, leaving it to crowd out the structure canvas.
- Smallest correction: "Scientific workflow" toolbar toggle using the existing
  dock-show/hide handler. Restore it docked, preserve the selected stage and
  scientific state, keep its check state synchronized with Focus canvas/closing.
- Acceptance: hide/restore, close/reopen, refresh while hidden, Focus canvas
  parity, unchanged stage/window size/state and same PyMOL engine.

### Warning repaint and plain-language window controls

- Date accepted: 2026-10-04; screenshot-backed usability correction.
- Status: implemented; native warning repaint/resize validation recorded separately.
- Observed problem: warning scrollbar shows a stray native track/arrow border
  before scrolling; "artifacts" is unexplained developer jargon; the main-window
  Full Screen toolbar action duplicates normal window-management controls.
- Smallest correction: scoped text styling and an arrow-free scrollbar with
  a reserved gutter; "Study files" labels without changing stored identities;
  remove only the main-window Full Screen toolbar action/shortcut. Keep figure
  expansion, Focus canvas and independent PyMOL detachment unchanged.
- Acceptance: initial warning pixels match scroll-return pixels; readable
  selectable warning at several widths; saved-file actions still toggle the
  existing dock; no toolbar fullscreen shortcut; viewer regression suite.

### Toggle and explain evidence review; gate report figures chronologically

- Date accepted: 2026-10-04; usability correction after non-structural user review.
- Status: implemented; regression and native macOS main/full-PyMOL validations passed.
- Observed problem: the residue highlight had no off action; users lacked a
  concise explanation of evidence review, and report figures could be selected
  before making the region decision.
- Smallest correction: a synchronized on/off residue button in the existing
  main/full-PyMOL evidence panel, plus an optional modeless Guide walkthrough.
  Removal restores only app-added sticks, preserving prior user styling,
  colors and camera. Report figures require generated artifacts and no pending
  region decision. Viewing never approves a region or modifies pipeline inputs.
- Acceptance: exact ASP30A on/off with pre-existing sticks retained, main/full
  button parity, modeless reusable guidance, pending/generated figure gate,
  unchanged scientific state. No new residue–residue analysis is implied;
  2D residue click mapping remains the separate next item below.
- Follow-up correction (2026-10-04): the residue button now toggles sticks only.
  Its temporary atom-addressing selection is deleted immediately, so pink
  selection squares do not remain. Users' native PyMOL selections are preserved.

### Historical click-to-toggle proposal, superseded by click-to-center

- Date recorded: 2026-10-04; user-designated next review enhancement.
- Status: implemented, then superseded by the user's 2026-10-04 separation:
  diagram clicks center in 3D; checkboxes alone show/hide residue sticks.
- Observed problem: diagram clicking currently activates the whole ligand,
  rather than the particular contact residue the user wants to inspect.
- Requested behavior: click a residue label/contact in 2D to show its side
  chain/highlight in the matching 3D receptor. It remains visible until that
  residue is clicked again. Multiple residues toggle independently. The second
  click removes only the app-added highlight/representation; it must not hide
  the protein cartoon or erase an existing user representation.
- Current acceptance replaces the above click-toggle behavior with centering
  while keeping visibility unchanged, including centering hidden residues.
  Native checks are retained in `validation/runs/paired-interactions/center-clicks/`.
- Mapping boundary: retain renderer-generated hit regions through image crop,
  raster scaling, fitting and zoom. Bind each region to exact residue identity.
  For deposited evidence, use the recorded source-to-current-receptor mapping;
  related PDBs must not be matched by residue number alone. Unavailable or
  ambiguous correspondence must be explained, not guessed.
- Acceptance: click on/off and multi-residue persistence in embedded/detached
  2D review; stable 2D zoom and 3D camera/colors; no reload or extra engine;
  safe cleanup on switching structures; unchanged docking inputs/approvals.
- Scope: extend the existing linked panel; no new docking option, flexibility
  decision, or independent viewer is introduced.

### Selectable obstruction warning in full PyMOL

- Date accepted: 2026-10-04; usability correction to the supported evidence review.
- Status: implemented; verification uses a UI fixture, not a new scientific finding.
- Observed problem: a forced scrollbar resembles a scientific symbol in the
  compact warning; the reported residue cannot be selected from that warning.
- Smallest correction: remove the compact scrollbar, enable copying/selecting
  warning text, and provide an explicit exact-residue highlight in the existing
  engine. Show sticks without recoloring, zooming, changing coordinates, or
  changing docking inputs. Reject absent or ambiguous residue mappings.
- Acceptance: real ASP30A selection in full PyMOL, stable camera/colors, no
  duplicate viewer, unchanged scientific study. No flexible docking is added.
- Main-interface parity (2026-10-04): the same action now appears below the
  main evidence warning when exact obstructing-residue evidence is present.
  Both interfaces share its presentation and exact-residue payload. A reserved
  action row prevents candidate changes from shifting the evidence table.
  This does not imply that every rotamer difference causes obstruction.

### Study navigation within full PyMOL

- Date accepted: 2026-10-04; explicit user request following full-detach testing.
- Status: implemented; real macOS region/evidence validation passed; user review pending.
- Observed problem: detached PyMOL obscures the main GUI, making its study
  selections impractical to use. Native PyMOL cannot discover retained study
  evidence on its own.
- Smallest correction: a collapsible Study evidence dock in the full shell,
  mirroring existing region, experimental observation, compound, cluster, and
  exact-pose navigation. Selections dispatch to existing authoritative callbacks;
  no duplicate approval or job controls. Only retained available data appears.
- Acceptance: real region box changes, multi-ligand load/hide, unchanged camera,
  no scientific approval, repeated detach/return, dock visibility, and shutdown;
  exact-pose forwarding checked in GUI tests. Main window is not activated by
  detached selection. Docking pipeline acceptance remains separate.
- Boundary: objects load locally on selection rather than eagerly importing all
  source complexes. 2D rendering/detachment remains in the main review workspace;
  no inaccessible 2D-render button is offered in the full-window study dock.

### Full PyMOL as the default 3D detach

- Date accepted: 2026-10-04; explicitly requested by the user for structural review.
- Status: implemented; macOS real-engine validation passed; user review pending.
- Observed problem: viewport-only detachment omits the PyMOL tools needed to
  inspect residues, selections, representations, and possible rotamer changes.
- Smallest correction: the existing Detach PyMOL button wraps the one live
  viewport in the upstream full Qt interface. No extra engine or subprocess.
  Closing/quit returns it; 2D/3D detachment remains mutually exclusive.
- Window behavior: opens maximized, not native full-screen, and remains
  resizable/restorable so users can work alongside other desktop windows.
- Acceptance: real 2R8N protein/surface, native command console, properties and
  builder, repeated detach/return, camera/engine identity, and clean shutdown.
- Boundary: exploratory edits never alter approved pipeline inputs. Arbitrary
  PyMOL scripts remain powerful user-directed actions; extra-window launching is
  intercepted to preserve one owned engine. Upstream Qt constructor integration
  needs revalidation after PyMOL upgrades. Windows/Linux not validated here.

### Independently detachable 2D interaction review

- Date accepted: 2026-10-03.
- Status: implemented; user layout review pending.
- Observed problem: the interaction diagram is illegible when squeezed beside
  embedded PyMOL; detaching 3D previously moved both panels together.
- Smallest correction: detach either the existing 2D panel or the existing 3D
  widget, never both simultaneously. Closing the detached window restores it.
  Fit preserves the whole diagram; explicit zoom and scrolling retain readable
  source resolution in small windows without changing scientific contacts.
- Acceptance tests: alternate 2D/3D detach and return without duplicating widgets;
  native-resolution diagram scrolls in a small window and fits without cropping.
- Scope: current linked review usability only; no new chemistry or renderer.

### Pocket-score navigation into 3D

- Date accepted: 2026-10-03.
- Status: implemented; real user interaction validation pending.
- Observed problem: the pocket-review stage offered empty retained-figure
  controls rather than a useful route from pocket ranking to structural review.
- Smallest correction: a native Qt plot of retained detector scores; click a
  point or its P# label to select the matching candidate and display its 3D
  scene through the existing viewer. Table selection follows the same path.
  Neither action approves a region. Every retained region appears in the plot,
  including unscored ligand-expanded regions below the score axis. Green rings
  identify deposited-ligand evidence; an amber exclamation marks a retained
  conformational conflict. A fixed-height scrollable plot keeps all candidates
  legible without resizing the surrounding workspace.
- Acceptance tests: real mouse clicks on P2 synchronize the table and viewer;
  retained-box numbering is distinguished from the original detector rank.
- Scope: pocket review only; interactive docking-results plots remain future
  work. No additional plotting dependency. New GUI preparation requests all
  eligible regions (`max_pockets=0`) instead of an arbitrary three-region count
  cutoff; existing overlap filtering and CLI defaults are preserved. Existing
  studies are not silently regenerated.

These are not backlog expansion. They are required to finish the active
rigid-receptor milestone:

- structured preparation interventions instead of terminal prompts;
- complete exploratory workflow through a real docking result;
- existing-protocol screening and known-ligand control/calibration routes;
- reliable stage feedback, cancellation, recovery, and clean shutdown;
- linked retained 2D/3D pose review and report generation;
- bounded branding, packaging, accessibility, and supported-platform acceptance.

### Minimal and offline Reduce2 component libraries

- Date accepted: 2026-09-28.
- Status: minimal core and consent-gated acquisition foundation implemented;
  complete offline package pending.
- User/scientific problem: a full GeoStd development clone occupies roughly
  2.4 GB, while Reduce2 must not silently lack restraints or disclose private
  structural information to obtain them.
- Implemented boundary: ship a small standard-protein restraint core; identify
  deposited modified polymer components; disclose exact pinned component
  requests; require explicit approval; cache validated responses with checksums
  and provenance. Retained non-polymer cofactors and metals remain in the
  receptor but do not trigger a restraint download merely by being present.
- Acceptance evidence: the 2R8N filtered receptor completes Reduce2 with the
  minimal core and preserves all 754 heavy atoms; tests verify refusal without
  approval and exact disclosure/audit behavior.
- Remaining acceptance: GUI decision/continuation for a real unusual component,
  Windows/Linux/macOS cache paths, and a versioned complete offline bundle.

### Reviewed GeoStd/CCD bridge for Meeko PTM templates

- Date accepted: 2026-09-28.
- Status: first peptide-PTM bridge implemented and validated with CSO in 1HVR.
- User/scientific problem: Reduce2 can understand a modified residue through
  GeoStd while Meeko may still reject it because the two programs use separate
  template systems.
- Implemented boundary: exact-ID, consent-gated CCD acquisition; local candidate
  generation only for CCD-classified peptide-linking modifications; complete
  non-leaving heavy-atom transfer, N/C peptide-link validation, source hashes,
  explicit user approval, and retained portable provenance.
- Deliberate exclusions: non-polymer ligands, metals, glycans, arbitrary
  cofactors, covalent adducts, and ambiguous backbones are not auto-converted.
- Acceptance evidence: a generated CSO/CSO_N/CSO_C set loads into Meeko 0.7.1,
  and the internal CSO residues in deposited 1HVR are retained in a real
  receptor PDBQT.
