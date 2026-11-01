# Systematic local software validation

For confidence-oriented GUI/pipeline coverage (including the separately labeled
100-scenario foundation), see [acceptance gates](gui-pipeline-acceptance.md).

This framework turns repeatable examples into a retained acceptance matrix.
It does not use an LLM and does not upload scientific data. Expensive work is
explicitly launched, runs sequentially, and is never silently repeated on resume.

## What the results mean

| Gate | Question | Evidence |
| --- | --- | --- |
| Regression | Did code-level contracts change? | Nonempty test discovery, executed/skipped counts and local logs |
| Workflow | Does an approved protocol actually run? | Real installed GUI/host, locked bundle, selection, docking, PLIP/2D, PDF, native 3D and reopening |
| Scientific | How well were experimental poses recovered? | Per-pose experimental RMSD in the receptor frame, matched seeds, lowest-energy pose primary, best-of-poses secondary |
| Presentation | Are images, labels and explanations usable? | Human visual review of retained screenshots/PDFs; file existence alone cannot pass this gate |
| Boundary | Does an invalid/unsupported request fail correctly? | Specific expected rejection evidence, not just an arbitrary nonzero exit |

A completed workflow does not prove a correct pose or affinity. A scientific
adapter with no predeclared recovery gate computes descriptive metrics; its
successful execution is not an accuracy endorsement. Set acceptance criteria
before running comparisons, not after seeing results.

## Protein workflow completion target

User-defined goal (2026-10-24): **at least 90% of proteins in a representative,
predeclared validation panel should run to completion**. This measures functional
compatibility, not accurate poses, affinity prediction or experimental binding.
It is a development target, not an achieved coverage claim.

A successful case must accept the input, complete receptor/ligand preparation,
use the explicitly reviewed site and settings, perform actual docking, and
produce usable retained poses, clustering, interactions and reports that reopen
in the application. Pocket prediction alone, successful parameterization alone,
an engine exit without valid outputs, or a correctly rejected request is not
completion. Keep visual acceptance and pose-recovery accuracy as separate gates.

Measure primary coverage by distinct protein targets with predeclared input
structures and cases. Repeated seeds, ligands, engines and PDB/mmCIF versions
provide scenario coverage; they must not inflate the protein denominator.
Also report structure-level outcomes so a different successful structure cannot
hide a failed input for the same target. Keep difficult cases in the original
panel and retain failed/blocked outcomes; define any scope exclusions before
testing rather than removing failures afterward. The historical 100-workflow
cohort is not 100 independent proteins and does not establish this percentage.

Report routine-preparation completion and completion after explicit reviewed
model changes separately, including a combined application-supported rate.
Externally/manual-edited rescue inputs are separate retests, not silent changes
to original outcomes. Model changes retain their warnings even when the workflow
finishes. No automatic gap/loop building, undeclared residue deletion or relaxed
chemistry validation is authorized by the coverage target; extensive incomplete
inputs such as the retained 1FM6 case may remain failures.

Record per-engine and per-platform coverage separately. A target completing on
one supported engine is not evidence that every engine supports it. The target
does not launch a new panel, repeat completed science, or change scientific
approval thresholds. Current work remains the bounded preparation and workflow
corrections in the [four-area checkpoint](four-area-completion-20261023.md).

The [implementation and acceptance plan](protein-completion-plan.md) prioritizes
the observed preparation boundaries and defines the larger independent panel.
`validation/validate.py protein-coverage` verifies local retained evidence
without launching calculations. Retrospective/small panels cannot pass the
prospective target, and supplemental cases cannot replace failed primaries.

The starter catalogue has eight public examples, 24 engine/example slots,
eight fast regression groups and five scientific adapter templates (37 cases).
Examples already appear in repository validation plans: 2R8N, 1HVR, 5IKT, 2R5P,
2O4P, 1MRW, 1IEP and 1YET. Features include small/large/flexible ligands,
macrocycles, repeated ligand instances, multiple chains/sites and different
protein families. Protease examples are overrepresented: this is an initial
coverage panel, not a diverse-enough universal accuracy benchmark.

Scientific templates are deliberately **unbound** until reviewed inputs, a
blocking benchmark adapter and its expected groups/seeds are supplied. Raw
preparation and strict control-calibration paths remain covered by the existing
[chronological acceptance plan](gui-real-workflow-validation.md) and native
control drivers; protocol-reuse screening does not substitute for those paths.
The default GUI worker tests protocol reuse, not a new site decision, download
or receptor preparation. The excluded AD4 macrocycle slot is not a pass; the
corresponding unsupported-request guard is tested separately.

## Quick start

Use the scientific Python, not a general Python lacking RDKit. This Mac example
shows explicit runtimes; use the corresponding installed paths on other systems.
No existing application installation is changed by these commands.

```bash
/opt/anaconda3/envs/docking-universal/bin/python validation/validate.py init \
  --out validation/local/my-machine.json \
  --python /opt/anaconda3/envs/docking-universal/bin/python \
  --gui-python /path/to/registered/desktop/python \
  --runtime /path/to/installed/libexec/docking-universal \
  --cli /path/to/docking-universal \
  --study-root "/path/to/original/studies"

python validation/validate.py plan --suite validation/local/my-machine.json
python validation/validate.py run --suite validation/local/my-machine.json \
  --out validation/runs/system/my-release --layer regression --execute
```

`init` creates a local suite, not a scientific approval. Specify `--node` for an
explicit local diagram runtime if needed. `--ad4` declares a capability for
planning only: the actual accepted AD4 runtime is still checked by the worker.
Do not copy an Apple-GPU acceptance claim to another OS or device.

To bind a matrix slot, first inspect/approve a matching engine/target protocol
in the normal application. The binding step verifies its integrity and pins
both the bundle and local SDF/MOL library. It refuses a different target or
engine. For tables, approve the column mapping/selection in the application
and export the selected local molecule library for this adapter.

```bash
python validation/validate.py bind --suite validation/local/my-machine.json \
  --case 2r8n-screen-vina --protocol /local/reviewed-vina.duprotocol \
  --ligands /local/selected-compounds.sdf --approve-import --approve-exploratory

python validation/validate.py plan --suite validation/local/my-machine.json --layer workflow
python validation/validate.py run --suite validation/local/my-machine.json \
  --out validation/runs/system/my-release --layer workflow --resume --execute
```

The GUI adapter imports the explicitly reviewed bundle through the ordinary GUI
controller. It never grants control validation, chooses a site or changes locked
search settings. A default 50-job ceiling blocks unexpectedly large screens;
raise `max_jobs` in the local case only after reviewing the plan. A native GUI
run needs desktop/graphics access. Offscreen widget tests do not certify a
working native viewport. Every GUI case gets its own application process.

## Evidence, progress and review

Each run retains `suite.json`, `summary.json`, `results.md` and independent
`case/attempt-NNN/` directories. Logs, worker receipts, screenshots, PDFs,
input/runtime hashes, output inventories and elapsed time remain local. Live
`summary.json` updates identify the running case, child PID and elapsed time.
Inspect `worker/summary.json` for finer GUI stage/workload progress.

Statuses are distinct: `not_run`, `blocked`, `excluded`, `running`, `passed`,
`failed`, `interrupted`. A visually unreviewed functional pass leaves the run
`needs_visual_review`. A partial catalogue stays `incomplete`; selecting only
regressions does not turn all unrun workflows into passes. Missing hardware or
reviewed inputs are blocked coverage, not evidence that the engine failed.

```bash
python validation/validate.py status --run validation/runs/system/my-release
python validation/validate.py review --run validation/runs/system/my-release \
  --case 2r8n-screen-vina --decision passed \
  --note "Inspected the native paired views and rendered PDF pages; labels complete."
```

Review cannot override a failed calculation. It verifies retained artifact
hashes before recording the human decision. Use `failed` if anything is clipped,
misleading or unusable; retaining a PNG is not equivalent to visual acceptance.

## Resume and failure policy

Acceptance exit codes: 0 means the entire requested suite is accepted, 1 means
a failure/attention condition, 2 means invalid configuration, and 3 means
incomplete coverage or visual review still required. A regression-only run of
the full catalogue therefore returns 3 even when all selected tests pass.
Queries such as `plan` and `status` do not grant acceptance. `compare` is nonzero
for regressions, removed coverage or noncomparable inputs/contracts.

Resume verifies the exact suite, source/installed code, pinned engines/runtime
files, inputs and retained outputs. Completed cases are skipped only after
their evidence hashes match. A code/settings/input change needs a new run.
Conda package records and Python distribution metadata are fingerprinted too,
so an ordinary chemistry/renderer package upgrade invalidates cached acceptance.
This is not a byte-level audit of every third-party library: add custom or
unversioned binaries to `identity_files` when their contents can change in place.
Failures remain failures unless `--retry CASE_ID` is explicitly requested;
retries create new attempt directories and retain the failed record.

One cross-platform OS lock excludes a second runner. Active application study
jobs block new scientific workers. Configure all real `study_roots` and
`protected_paths`; output inside protected studies is refused. Input/protected
hash checks detect unintended changes. These checks are not a filesystem sandbox
for a malicious adapter: suite commands are trusted local operator configuration.

Timeouts/interruption or unexpected scientific-adapter exits do not start
another job. Detached scientific children can outlive a crashed GUI: a
missing/nonterminal cleanup receipt stops the queue conservatively, even if
the GUI process has already exited. The runner retains an unresolved-worker marker.
Inspect the recorded worker/application study, stop only that work, and verify
no calculation is active before `reconcile --confirm-workers-stopped`. This
command is an operator attestation, not automatic process cleanup. Interrupted
cases stay interrupted; use a new reviewed run rather than silently restarting.

## Scientific adapters and release comparisons

Command adapters use argument arrays, never shell interpolation. Placeholders
include `{python}`, `{runtime}`, `{project}`, `{out}` and named pinned input paths.
Pin every scientific input consumed by an adapter, not just its summary file.
Every adapter must provide artifact assertions; exit code zero alone is not
acceptance. Existing strict-control/redocking drivers can be wrapped without
changing their scientific settings or approval thresholds. Network-dependent
setup is blocked here; do separately authorized acquisition before local runs.

Scientific adapters write a per-pose CSV containing `arm`, `seed`,
`affinity_kcal_per_mol` and `crystal_rmsd_angstrom`. Declare the no-fit experimental
coordinate basis, exact matched seeds/groups and recovery threshold. Vina's
internal lower/upper RMSD columns are explicitly rejected as an experimental
reference. The reporting recovery threshold defaults to 2 A; this is separate
from the production **1.5 A clustering** threshold. It does not change software
approval rules.

The lowest-energy pose is primary. Exact energy ties retain a minimum/maximum
experimental RMSD interval and both any-tie/all-ties recovery counts; the
framework never picks the closest pose to break an energy tie. Best-of-all-poses
RMSD is clearly secondary. Missing seeds/groups, negative/nonfinite RMSD or
nonfinite energy prevent complete scientific acceptance. Optional
`minimum_recovered_seeds` applies a predeclared conservative all-ties gate.

```bash
python validation/validate.py compare \
  --baseline validation/runs/system/previous-release \
  --candidate validation/runs/system/current-release \
  --out validation/local/release-comparison.json
```

Comparisons distinguish new/removed coverage, regressions and noncomparable
changed inputs/engines/contracts. Scientific deltas require matched groups,
seeds and thresholds. Energy models are not pooled across engines. Timing deltas
are descriptive; matching hardware/search budgets must be established before
claiming acceleration. Do not cherry-pick examples that happened to improve.

## Privacy and portability

Live GUI cases require the actual engine executable in `profile.identity_files`.
`init` discovers the current Mac Conda CPU binaries and accepted GPU descriptor;
other layouts must supply their exact paths explicitly in the local profile.
An unpinned engine is blocked, so a changed external executable cannot silently
reuse an earlier pass. Verify that these are the executables used by the chosen
installation, especially with custom environment overrides.

`validation/local/` and `validation/runs/` are ignored by Git. Never commit or
upload raw summaries/logs/structures/poses/PLIP/images/reports or derived
structural numerical evidence. `export-status` emits anonymous layer/status
counts only, without targets, paths, hashes, error text or scientific metrics.
It does not itself upload anything.

The supervisor uses the existing native Windows/Unix file locks and standard
Python process APIs. Actual desktop, chemistry and engine acceptance still
requires native evidence on each OS/hardware profile. Arbitrary configured
command adapters are trusted executable code, not a network-security sandbox.
This implementation adds no GUI controls, dependencies or production defaults.

## Implementation verification, 2026-10-22

### Expanded panel launched separately

The bounded expansion uses five larger ligands (indinavir, tipranavir, KNI-577,
imatinib and geldanamycin). Four native-target comparisons add three matched
QuickVina-W searches each, reusing the exact retained first MMFF94 conformer,
receptor, box and completed Vina outputs. Current experimental-RMSD comparisons
are recalculated locally for both engines. Original effort, pose count and energy
window are retained; QuickVina-W uses eight CPU threads versus the historical
single-thread Vina baseline. This is neither a speed comparison nor a
whole-ensemble accuracy/calibration claim. Both absolute energy models and
different search implementations must remain identified.

Fourteen additional one-compound GUI screens use the already reviewed 2R8N P1
protocols across Vina, QuickVina-W and experimental AD4, including native linked
review, retained PLIP evidence, PDF creation and reopening. These are workflow
robustness tests: imatinib/geldanamycin screening on protease is **not** experimental
pose recovery on their native kinase/HSP90 targets. GUI preparation uses the
ordinary protocol chemistry policy, unlike the exact single-state prepared
recovery arm. The AD4 macrocycle case remains excluded; flexible-macrocycle
prepared PDBQT is not forced through QuickVina-W's different rigid-macrocycle route.

An old biotin control bundle fails the current safe portable-member import check
because it retained an absolute box path. That additional GUI case is blocked,
not passed or bypassed. The old bundle and original studies remain unchanged.

`validation/build_expanded_mac_suite.py` creates an ignored local suite and pins
all consumed inputs. `validation/prepared_engine_worker.py` adds no production
behavior or scientific approvals. Actual completion, failures and visual-review
status must be read from the new run; this plan is not an acceptance result.

- All 37 supervisor tests pass: locks, interrupted/crashed workers, immutable
  inputs/evidence, explicit retries, package-version changes, pinned external
  engines, visual gates, anonymous export and experimental-RMSD/tie handling.
- The final runner executes eight regression groups: 232 cases, zero skips.
  The complete existing `make test` suite also passes: 775 discovered cases,
  683 executed and 92 environment-dependent skips, plus 21 shell checks. Skipped
  cases are not represented as executed native-platform acceptance.
- A fresh two-compound native Mac GUI case used the parameterized worker and
  reviewed 2R8N Vina protocol. Import, workload preview, docking, six retained
  representative views, paired 2D/3D, PDF and fresh-host reopening passed.
  Both screenshots and all eight PDF pages were reviewed before recording the
  visual pass. A same-checkpoint resume launched no worker and created no new
  attempt. The current GUI-worker source hash still matches that live run;
  later supervisor-only crash/package-pin hardening was tested separately,
  without repeating completed docking.
- The live demonstration matrix records 9 passed, 27 blocked and 1 excluded,
  therefore **incomplete**, not 37 successful scientific validations. The final
  regression-only run records 8 passed and 29 not run. Local benchmark adapters
  and other examples must still be bound/reviewed before their execution.
- The original study/protocol inputs remain unchanged, no scientific processes
  were left running, and the existing 697-entry installation protection audit
  has no unexpected changes (including the same absent stale metadata entry).
  No working installation/dependencies were updated for this framework.

Local evidence (ignored by Git): `validation/runs/systematic-validation-20261022-c/`
for native integration/review and same-checkpoint resume, and
`validation/runs/systematic-validation-20261022-final-metadata/` for the final
regression matrix. Machine bindings and anonymous exports are in
`validation/local/`. Earlier development checkpoints remain separate; source
fingerprint changes intentionally prevent resuming them as current acceptance.
There is no new Windows/Linux native or broad scientific-accuracy acceptance
claim from this implementation.
