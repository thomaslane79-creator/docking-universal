# Docking execution performance

Thread count is an execution setting, not a claim about binding accuracy. Eight
threads was fastest in the original two-compound, one-receptor M2 Max example;
that does not establish a universal optimum. Retain explicit overrides and
measure complete workloads before recommending a different default.

## Subsequent optional-engine acceptance

The later AD4 numerical investigation, shared GUI/report integration and local
backed-up installation passed within the documented Apple-Silicon scope; see
[integration acceptance](ad4-gpu-integration.md). This does not change the
historical measurements or imply equal-search hardware acceleration. Vina
remains the default. The historical unresolved-gate statements below describe
their original benchmark stage, not the subsequent acceptance outcome.

## Full retained-workload Apple-GPU benchmark (2026-10-16)

User authorized the complete original two-compound, three-conformer, five-seed
workload on the isolated patched AutoDock-GPU AD4 engine. This is not GPU Vina,
not an AD4-approved reusable protocol and not a production engine installation.
Exact preparation, source Vina protocol and original study stay unchanged.

Runner: `validation/autodock_gpu_full_screen.py`. Live record:
`validation/runs/autodock-gpu-mac-20261016/full-screen-20261016/completion.json`
is the final authoritative verification; the initial `summary.json` remains a
preserved failed-postprocessing record, not the final outcome.
Thirty sequential searches use the fast heuristic/autostop profile, 20 LGA runs
each, retaining and chemistry-checking 600 run winners. New AD4 maps use union
atom types and are reused. Setup, per-compound search costs, typed pose checks,
clustering, PLIP, local approved 2D rendering, ray-rendered PyMOL and a clearly
AD4-labeled benchmark PDF are timed separately. The original explicit 2 Å
clustering override is retained only for comparison; new-study defaults stay
1.5 Å. No fake VINA score remarks or invented experimental RMSDs are written.

Shared geometry-only clustering consumes a typed SDF/score adapter. Its legacy
input filename `pose_comparison.csv` is an API contract, not a claim of crystal
comparison; adjacent provenance identifies native AD4 outputs. The Vina-specific
production PDF cannot be reused unchanged, so benchmark-PDF timing is not the
same report implementation. AD4 retains 600 winners versus up to 450 Vina poses;
postprocessing costs and distributions can differ. Preparation is reused, not
retimed. These compounds have no experimental pose reference here.

The separate added-atom-type audit's strict numerical gate remains failed on a
non-winning tipranavir state. This timing run does not waive it or establish
scientific acceptance; see `docs/autodock-gpu-control-assessment.md`. Nineteen
local validation tests pass before launch, including complete workload inventory
and non-Vina/non-crystal score labeling.

Completed: all 30 searches / 600 chemistry-checked poses, six selected clusters,
PLIP outputs, six collision-checked 2D diagrams, ray-rendered 3D images/sessions
and the seven-page AD4 benchmark PDF. All seven final pages were visually reviewed;
source inputs/maps and saved poses remain hash-verified. No search was repeated.

| Measured stage | GPU benchmark | Historical eight-thread Vina benchmark |
| --- | ---: | ---: |
| Docking phase including setup | 356.98 s (5:57) | 499.31 s (8:19) |
| Downstream analysis/visuals | 68.48 s, including failed-stage execution | 82.28 s, production analysis/report path |
| Stage-summed active processing including initial PDF | 427.83 s (7:08) | 581.60 s (9:42) |

The flexible compound's 15 GPU search processes sum to 297.54 s, versus 422.65 s
of historical Vina search time; the smaller compound sums to 52.08 versus 66.99 s.
GPU process-wall ranges are 11.15-42.64 s and 3.06-4.10 s respectively. GPU
process times include startup/output/polling, unlike Vina's search-only sums.
The broad single-input twofold estimate overstated the whole workload's gain:
the complete docking phase is about 29% shorter under these tested profiles.

This was **not an uninterrupted 7:08 end-to-end run**. The observed elapsed time
to the first complete report was 648.91 s (10:49), including manual recovery.
The first diagram attempt lacked the isolated subprocess `PYTHONPATH`; correcting
the invocation exposed a genuine label overlap at 15-unit spacing. Explicit
continuation used the renderer's supported 20-unit spacing with unchanged
collision/ambiguity gates; all six diagrams pass. Original failure logs, audits
and source snapshots remain retained. Completed docking, clustering, PLIP and ray
stages were reused, not repeated. A report-only revision fixed table wrapping,
pagination and energy-ranked panel ordering; its time and PDF visual QA are not
included in the stage-summed processing figure. Do not present the difference
as a matched-search hardware speedup or promise the same whole-screen saving.

Final records: `completion.json`, `layout-continuation.json` and
`report-finalization.json` in that run directory. PDF:
`output/pdf/gpu-screen-benchmark.pdf`. The numerical gate remains unresolved;
this performance completion does not authorize production integration or prove
AD4 scoring superior to Vina. Both unknown compounds lack experimental references.

At the user's request, a later report-only revision restores portrait Letter
pages with stacked 2D/3D panels and replaces file-derived molecule headings with
the retained library `Nextval_ID` values (12388 and 27688). The prior landscape
PDF and original completion record remain preserved. Current report identity,
mapping and seven-page visual verification are recorded in
`report-portrait-revision.json` and `report-portrait-qa.json` in the same run
directory. All 2,254 scientific artifact files were hash-checked unchanged;
no docking, clustering or visual generation was repeated. This report-only
revision is excluded from benchmark processing times.

The subsequent user-requested residue-label revision adds name/number/chain
callouts to the six 3D PLIP figures, pointing to one atom per contacting residue.
Spaced screen-relative callouts avoid label overlap and remain readable in the
ray-rendered portrait PDF. The labeled PNG/PSE copies are retained separately;
original figures, coordinates, energies, PLIP reports and 2D diagrams stay
unchanged. This visual revision is also excluded from benchmark timings and does
not install or change production rendering. Latest report verification:
`report-residue-label-qa.json`, with source hashes and revision chain in
`report-residue-label-callouts-final-revision.json`.

## Broader thread pilot

`validation/vina_thread_targets.py` reuses retained prepared indinavir/protease,
imatinib/Abl and geldanamycin/HSP90 inputs. These are three larger ligands, not
a representative survey of all drug-like compounds or hardware.

- One fixed retained conformer and two matched seeds per target.
- Counts 4/8/12, two rounds with varied count order: 36 searches total.
- Exhaustiveness 16, 15 requested poses, 8 kcal/mol retained window, receptor
  refinement enabled, 1 Å within-search minimum pose separation, 0.375 Å maps.
- Preparation is reused; no preparation, PLIP or report generation is timed.
- Compare complete outputs across counts/repeats. This checks implementation
  repeatability, not experimental pose recovery or a new conformer method.
- Source files remain hash-checked and read-only. Background activity and
  thermal conditions are not controlled; repeated timings remain a small pilot.

Results: `validation/runs/vina-three-target-threads-20261015/summary.json`.
The historical geldanamycin retained coordinates are reused. The later failed
MMFF94s preparation is not restarted or described as a successful preparation.

### Completed pilot: 2026-10-15

All 18 arms (36 searches) completed. Median worker elapsed seconds across the
two repeats are shown below; each worker performs the two matched-seed searches.
These are not whole-screen times and exclude preparation and downstream analysis.

| Retained ligand / target | 4 threads | 8 threads | 12 threads |
| --- | ---: | ---: | ---: |
| Indinavir / HIV protease | 166.08 s | 94.87 s | 89.20 s |
| Imatinib / Abl | 48.71 s | 28.08 s | 28.80 s |
| Geldanamycin / HSP90 | 226.34 s | 121.02 s | 121.25 s |

All 36 complete PDBQT outputs are byte-identical to their corresponding
case/seed reference across counts and repeats. This does not compare different
seeds to each other or establish experimental correctness. Original inputs are
unchanged. Twelve threads was fastest for indinavir; eight was narrowly fastest
for imatinib, with eight and twelve essentially tied for geldanamycin. This small,
single-Mac pilot does not establish a universal optimum. The configurable
eight-thread Apple-Silicon default is unchanged.

Screen ligands exposes **Docking CPU threads** with three choices:

- **Application default (recommended):** keep the existing execution policy.
  Vina on Apple Silicon uses up to eight threads (bounded by available logical
  CPUs); other platforms and QuickVina-W retain engine automatic. Existing
  `DOCKING_UNIVERSAL_CPU` or saved box `cpu` settings still take precedence.
- **Automatic — engine decides:** explicitly request `0`, overriding existing
  environment/box CPU settings for this new screen.
- **Custom thread count:** set a positive count, including values above eight.
  This overrides existing environment/box CPU settings for this new screen only.

GUI overrides are passed in the isolated screening child's environment; they do
not change the host environment, existing runs or the reusable scientific recipe.
Every docking manifest retains the actual resolved CPU count/source (GUI overrides
are environment-sourced). More threads may be slower and use more machine
resources; thread count is not exhaustiveness, repeat count or concurrent compounds.

## Persistent Vina batches

The dispatcher can use one Vina Python worker for each prepared-ligand batch
at one seed/receptor/box. It computes all atom-type maps before loading a ligand,
then replaces ligand state between searches while retaining maps in memory.
This avoids repeated process/map setup without reducing conformers, independent
seeds, search effort, saved poses or the energy window. It does not yet keep one
worker alive across every compound, box or seed in an entire study.

This is supported by the [Vina Python API](https://autodock-vina.readthedocs.io/en/latest/docking_python.html).
In the pinned 1.2.7 implementation, each global search initializes its RNG from
the configured seed; batch reuse is checked against complete CLI pose outputs.
See the [upstream search implementation](https://github.com/ccsb-scripps/AutoDock-Vina/blob/v1.2.7/src/lib/vina.cpp).

Selection is conservative:

- `dock --vina-backend auto` is the default; `api` requires the supported path,
  while `cli` explicitly retains one engine invocation per ligand.
- Automatic API selection requires at least two pending ligand inputs; a single
  pending search keeps the CLI to avoid adding batch/Python setup overhead.
- `DOCKING_UNIVERSAL_VINA_BACKEND=cli` applies to CLI/GUI child workflows without
  changing a scientific protocol. `DOCKING_UNIVERSAL_CPU=N` sets threads;
  `dock --cpu N` overrides that variable. CPU `0` requests engine automatic.
- Require matching Vina 1.2.7 CLI/API installations, a fixed nonzero seed and
  explicit box geometry. Only standard Vina scoring/default refinement, default
  spacing/within-search separation and the supported search settings are mapped.
- Unknown/advanced config options, other versions, QuickVina-W, unavailable APIs
  and unseeded searches retain the original CLI before any search starts. The
  selected backend and reason are recorded, not silently substituted.
- The default managed Conda Vina executable can be resolved once and verified
  for direct execution. Custom environments keep their activation wrapper.
- After an API batch starts, failures are not retried through the CLI. A bad
  ligand is recorded once; subsequent ligands get a clean engine/map set.
  Successful outputs are retained, and the batch still reports failure.
- Temporary pose writes do not end in `.pdbqt`, so interrupted writes cannot
  appear in downstream pose inventories. Only complete scored outputs are
  promoted to the established filenames.

`run_manifest.tsv` records CPU/backend provenance. Unique `batch_requests/` and
`batch_records/` JSON retain input hashes, settings, worker identity, map/search
timing and per-ligand outcomes. `batch_request.json` / `batch_execution.json` are
latest-run convenience aliases; rerunning with skip-existing does not erase the
original per-request record. Skips preserve existing output bytes and do not
claim a new search. Host cancellation still terminates the process group.

Native acceptance is in `validation/vina_batch_acceptance.py`. It waits until
the timing pilot finishes, compares nine complete output files across the current
screen and three retained targets, checks real skip/failure behavior, and installs
the three execution files only after all checks pass. Source inputs and old
reports are not rewritten. Status is authoritative in
`validation/runs/vina-batch-acceptance-20261015_b/summary.json`.

### Native acceptance and installation: passed 2026-10-15

All 22 native checks passed across the current screen and three retained targets.
All nine complete API output files match the retained CLI references byte for
byte. Each initial batch builds maps once. Skip-existing checks preserve output
bytes and build no maps. A deliberately bad ligand is not retried; the next good
ligand succeeds after a clean map rebuild, retaining only the valid complete
output. Retained scientific inputs and original outputs are unchanged.

Only `docking_universal_dock.py`, `docking-universal-vina-batch.py` and
`docking_universal/vina_batch.py` were installed into the managed runtime after
acceptance. An independent read-only SHA-256 check confirmed all three installed
files match the implementation hashes recorded in the acceptance summary.
No reinstallation, redocking, CPU-default change or scientific-setting change
was performed during the completion check.

For the fresh same-thread current-screen comparison (three conformers, one seed),
API batch wall time was **14.57 s**, versus **13.87 s** for direct CLI execution.
The API was slightly slower in this small batch; map reuse is verified, but this
measurement does not demonstrate a whole-screen acceleration. Do not attribute
the earlier broader shared-grid benchmark's whole-workload gains to this narrower
per-compound/seed integration. The installed path preserves sampling/refinement,
falls back to CLI only before searches for unsupported configurations, and is
neither a whole-study persistent worker nor a GPU backend.

## Mac-local CPU concurrency pilot: completed 2026-10-15

The user authorized an isolated `validation/vina_concurrency_benchmark.py` pilot:
one eight-thread worker, two four-thread workers, and four two-thread workers.
Each worker is the installed compound/seed API batch, not a newly substituted
docking engine. Simultaneous docking-search threads are capped at eight; this
is not CPU affinity or a cap on all helper/operating-system threads.

Reuse both compounds, all three prepared conformers and the first two matched
seeds from the retained 2R8N screen: four batches / twelve searches per arm.
Repeat each layout twice in reversed layout and task order (72 searches total).
Search effort 16, 15 requested poses, 8 kcal/mol window, maps, refinement and
chemistry remain unchanged. Preparation, PLIP, reports and other analysis are
excluded. Compare total arm wall time (not summed overlapping search times) and
every complete PDBQT against its retained seed/conformer reference. Original
inputs, reference outputs and installed execution files are hash-checked.

The pilot stops its own worker process groups if a new GUI calculation starts;
it never cancels the user's GUI work. Failed/interrupted runs are not silently
restarted. This is not a production scheduling change. Twenty-three combined
benchmark/batch tests pass, including workload, bounds, failure cleanup and the
active-calculation guard. Results:
`validation/runs/vina-concurrency-20261015/summary.json`.

All six arms completed. Median total wall time for the same twelve searches:

| Concurrent workers × threads each | Repeat 1 | Repeat 2 | Median | Time versus 1×8 |
| --- | ---: | ---: | ---: | ---: |
| 1 × 8 | 203.57 s | 206.56 s | 205.07 s | Baseline |
| 2 × 4 | 212.40 s | 231.29 s | 221.85 s | 8.2% longer |
| 4 × 2 | 343.67 s | 344.45 s | 344.06 s | 67.8% longer |

All 72 complete output files match their corresponding retained CLI references
byte for byte (24 per layout). Post-completion verification reconfirmed output
equality and unchanged original input/reference/implementation hashes. No arm
failed, no production setting changed and no scheduler was installed. Keep one
eight-thread worker for this workload: the tested concurrency layouts did not
improve throughput. This does not establish that all larger or differently
balanced libraries will behave the same way.

This two-compound workload has heterogeneous batch costs and only four batches;
load imbalance and the last unfinished batch can limit concurrency gains.
Thermal/background activity is uncontrolled despite two reversed-order repeats.
Output equality is an implementation check, not experimental pose recovery or
evidence of a general speedup across compounds/hardware.

### Full-workload follow-up: cancelled by the user

The user initially requested all five retained seeds (thirty searches per layout,
one pass each), then decided further job-splitting tests were not worth pursuing.
The follow-up at `validation/runs/vina-concurrency-full5-20261015/` was stopped
during the first 1×8 arm. The recorded coordinator, dispatcher and API worker
exited. No full arm completed: interrupted outputs/logs are retained, not presented
as full-workload timing results. No restart or production setting change.

Compound-specific inspection of the earlier completed five-seed eight-thread run
found 422.65 s of search time for the 37-heavy-atom, 15-rotatable-bond compound,
versus 66.99 s for the 27-heavy-atom, 3-rotatable-bond compound (RDKit definitions).
The larger/more flexible compound accounts for 86.3% of that search time. This
does not isolate molecular size from flexibility or other chemical differences.

## Larger speed options: feasibility review, not an installed GPU backend

Reviewed against upstream documentation on 2026-10-15:

| Option | Relevant boundary | Next evaluation |
| --- | --- | --- |
| Uni-Dock | Official support is Linux with NVIDIA compute capability ≥7.0; supports Vina/Vinardo/AD4 scoring. | Candidate for a separately authorized NVIDIA workstation test, not a local M2 installation. |
| Vina-GPU 2.1 | Published build instructions cover Windows/Linux with NVIDIA or AMD OpenCL; uses modified search/optimization methods. | Check pose recovery and ranking, not speed alone; Apple-GPU support has not been verified here. |
| AutoDock-GPU | GPU implementation of AutoDock4.2.6, not the same Vina search/scoring pipeline. | A separate scientifically validated engine/protocol comparison. |

Sources: [Uni-Dock installation](https://github.com/dptech-corp/Uni-Dock/blob/main/unidock/README.md),
[Vina-GPU 2.1](https://github.com/DeltaGroupNJUPT/Vina-GPU-2.1),
[AutoDock-GPU](https://github.com/ccsb-scripps/AutoDock-GPU).

At that initial review, no GPU packages, drivers, cloud instances or remote jobs were installed/launched;
no ligand or receptor data was uploaded. An upstream advertised speedup against
a single CPU core is not a speedup measured against this application's workload.
The current CPU change removes overhead; it is not expected to eliminate the
dominant docking search/refinement cost. Concurrent independent production jobs
remain deferred under the project's workflow/scheduling scope rules; the isolated
Mac concurrency experiment above is a specifically authorized benchmark exception.

### Post-update native Apple-GPU validation: failed acceptance

The user independently upgraded macOS, then authorized Apple's optional Metal
compiler and an isolated native-engine evaluation. The compiler installed; a
pinned experimental GNINA Metal fork builds after recorded repairs. Eleven
libmolgrid native tests and five CPU/Metal numerical checks across three seeds
pass. Direct PDBQT round-trip chemistry verification fails; an explicit mapped-SDF
path preserves retained chemistry and coordinates, but its first full Metal
indinavir search crashes before returning poses. Further paired searches stopped
at this correctness gate. No GPU speedup, pose-recovery comparison or production
integration is claimed. Working application environments and studies are unchanged.
See [native Apple-GPU validation](apple-gpu-feasibility.md) for exact failures,
patches, evidence paths and the distinction between kernel tests and docking.

### Official AutoDock-GPU local trial: viable, not accepted for production

On 2026-10-16 the user authorized testing the official v1.6 ARM64 OpenCL release.
It executes actual search on the M2 Max without source repairs. Two cases × two
seeds plus a repeated first seed × 20 LGA winners finish; all 120 retained poses
pass the checked atom/charge/type/graph/3D stereochemistry invariants. Autostop
defaults are fast but indinavir's lowest-energy crystal RMSDs are 4.15/3.71 Å,
with a same-seed repeat at 1.77 Å. Same-seed poses/timings are not identical.

A controlled, separately recorded indinavir follow-up disables autostop and uses
the initial heuristic's 5,210,753-evaluation ceiling explicitly. Both seeds rank
~1.64 Å crystal poses first in ~32 s process wall each. Historical eight-thread
Vina search times for those inputs are ~45–46 s, with top RMSDs 1.22/1.26 Å.
This is a modest cross-engine observation, not a matched speedup: AD4 scoring,
search budget, output count and timing boundaries differ. The flexible screen
compound's default GPU searches range ~9–37 s before map/setup; it has no known
experimental pose and no no-autostop follow-up, so accuracy/speed equivalence
cannot be established for it.

Map generation adds ~7 s / ~4 s for the control/screen target and is reused.
CPU/GPU energy residuals for winners are small, but larger population discrepancies
need investigation. No production integration/default changes. Details and all
result links: [AutoDock-GPU Mac trial](autodock-gpu-mac-trial.md).

The subsequent [same-seed investigation](autodock-gpu-reproducibility.md)
completes 213 isolated invocations and identifies a shared atom-force race in
OpenCL ADADELTA refinement. A single-barrier 128-work-item candidate reproduces
full outputs on both retained ligands, with autostop off and with original
defaults. This is not production installation or a Vina speedup benchmark:
one-work-item failures and wider population CPU/GPU energy residuals remain
unresolved numerical gates. All workers exited; original studies are unchanged.

The [next numerical follow-up](autodock-gpu-numerical-validation.md) completes
48 more searches and explains the large energy tails as differences between
CPU table-based reporting and GPU continuous/approximated evaluation. Independent
matched-formula bounded-population residuals are ≤0.000307 / 0.000264 kcal/mol;
all 6,000 entities and extreme-state statistics are retained. The one-work-item
defect remains unrepaired and is rejected in an isolated guarded candidate;
32/64/guarded-128 repeat controls pass. This is no production installation,
engine-switch approval or new performance claim.
