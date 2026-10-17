# AutoDock-GPU remaining numerical checks — 2026-10-16

Completed: **48 additional search invocations**, one expected native rejection
before any GPU launch, and ten native unit tests passing. Calculations were
sequential, reused existing preparation/maps, and respected the active-GUI-job
guard. No working engine, application defaults, studies or reports were changed.

Outcome: the large energy discrepancies are explained by comparing different
evaluators. The one-work-item Apple-GPU defect is **not repaired**; it is
explicitly quarantined in an isolated guarded candidate. These are different
outcomes, not a claim that every diagnostic passed.

## One work-item: failed, contained rather than accepted

The [previous investigation](autodock-gpu-reproducibility.md) established the
shared-force synchronization repair for 128 work-items, but not for one.
This follow-up adds profiled command events, explicit event waits, smaller
launches with preserved entity/RNG indexing, fewer LGA runs, and a separate
unchanged-kernel control with `clFinish` after every launch.

- The original raw one-work-item trace can suddenly contain an entirely zeroed
  population. This is not ordinary small floating-point drift.
- Profiled events report completion without an execution error. No relevant
  timeout/reset evidence was established from the targeted kernel-log check.
  Therefore a watchdog timeout is **not** a demonstrated diagnosis.
- Smaller launches still produce differing populations. They also add substantial
  overhead and are not a proposed performance optimization.
- The unchanged-kernel explicit-completion control matches only **one of six**
  repeat comparisons. Waiting for completion alone is not a repair.
- The precise one-work-item compiler/runtime/kernel defect remains unresolved.
  We do not attribute it conclusively to Apple hardware or its driver.

The upstream [pinned README](../validation/runs/autodock-gpu-mac-20261016/source/README.md)
accepts one as a build value, recommends 64/128 for modern GPUs, and specifically
mentions one for macOS **CPUs**. That recommendation does not turn a one-work-item
GPU launch into an independent serial CPU reference. Our rejection is a local
evidence-based acceptance policy, not a claim that upstream rejects the value.

The isolated `source-gpu-candidate-guarded` adds an early native check for
`__APPLE__ && GPU_DEVICE && NUM_OF_THREADS_PER_BLOCK == 1`. It returns **64**
with a clear explanation **before creating the OpenCL device or launching a
docking calculation**. The negative test verifies that exact exit/message and
absence of a launch. Native one-work-item guard executable SHA-256:
`f40220fea3fbbe07190c8f5f92f0abd7ca2611533476afef2fbaa374b8936760`.

Separate untraced 32-, 64- and guarded 128-work-item builds each complete nine
short ADADELTA invocations (1/5/20 generations, three repeats each). **All six
repeat comparisons per build match** in poses and complete printed populations.
Outputs are compared within a build, not promised identical across different
work-group sizes. Full-budget repeat evidence on both ligands remains available
for the 128-work-item synchronization candidate from the preceding investigation.
No binary is installed or offered through the GUI by this experiment.

## Energy differences: matched coordinates and matched formulas

Two new full searches use the same corrected 128-work-item kernels, inputs,
seeds and fixed budgets as the previous candidate. The audit retains every
population member: **3,000 per ligand, 6,000 total**. Both searches reproduce
their preceding uninstrumented candidate's complete printed populations and
poses. All forty retained run-winner poses pass identity/order, charge/type,
mapped graph and independent 3D stereochemistry checks.

After the searches, diagnostic-only instrumentation preserves the original
genotypes/search energies, re-evaluates those genotypes into scratch GPU memory,
and records actual GPU coordinates. It does not substitute re-evaluated energies
into the original search results. CPU coordinate transforms and CPU scoring are
evaluated separately on both their own and the **identical GPU** coordinates.

An independent NumPy implementation evaluates intramolecular terms three ways:

1. The actual CPU lookup tables, including their float-generated distance grid.
2. Continuous AD4 distance-dependent dielectric/Gaussian formulas.
3. The continuous rational approximations actually used by the GPU.

The grid-interaction reference uses the engine's separately implemented CPU
interpolation on the recorded GPU coordinates. Thus this is independent
intramolecular evaluation plus a CPU/GPU grid-interpolation cross-check, not a
wholly separate implementation of every AD4 preparation/scoring component.
No rounded PDBQT coordinates or printed three-decimal genotypes are substituted
for raw floating-point arrays.

### What caused the large discrepancies?

CPU intramolecular reporting selects table entries at distances rounded to
**0.01 Å**. GPU scoring uses continuous distances. CPU reporting also uses the
original dielectric/Gaussian functions, whereas the GPU uses fitted rational
approximations. These are not identical evaluators, even on identical coordinates.
Steep repulsive terms amplify distance rounding in clashing conformations.

| Maximum absolute discrepancy, kcal/mol | Indinavir | Flexible screen ligand |
| --- | ---: | ---: |
| Legacy CPU report versus stored GPU search energy, bounded population | 12.71730 | 8.10635 |
| Independent matched GPU-formula reference versus GPU re-evaluation, same bounded population | **0.000307** | **0.000264** |
| Same matched reference versus GPU re-evaluation, twenty run winners | 0.00000311 | 0.00000286 |

“Bounded” means both original CPU-report and GPU-search absolute total energies
are ≤1,000 kcal/mol: 2,369 indinavir and 2,333 screen entities. This is a
pre-existing diagnostic subgroup, **not** a filter deleting other results.
All 6,000 entities remain in the analysis and its full-population statistics.

For the worst bounded indinavir entity, the signed report-minus-search
difference is −12.71730 kcal/mol: −12.69706 is the distance-table effect,
−0.02006 the formula-approximation effect; coordinate transforms and numerical
evaluation account for the small remainder. For the screen ligand's worst
entity, table rounding contributes −8.12399, partly offset by +0.01718 from
coordinate/lookup-boundary effects. The total is −8.10635.

CPU/GPU coordinate transformations differ by at most 0.0000653 Å and
0.0000891 Å. Tiny changes can still cross a discrete CPU table boundary, so
coordinate effects and distance-table effects must not be conflated.

### Extreme populations and residual limits

Across **all** entities, maximum matched-model scaled discrepancies are
`4.85e-6` (indinavir) and `2.56e-6` (screen), using
`abs(reference-GPU)/max(1,abs(reference),abs(GPU))`.
Absolute residuals can remain large in extremely penalized states: 68.76 at
an energy of 587,484,928, where adjacent float32 values are 64 apart; the
screen's maximum is 58.37 at 188,727,920, with float32 spacing 16. These are
reported, not silently excluded or passed using a newly relaxed tolerance.

Stored search energy versus the separate energy-only re-evaluation differs by
up to 0.006714 / 0.007202 kcal/mol in the bounded positive-energy tail, and is
identical for all forty run winners. That smaller implementation/cached-state
difference is recorded separately; it is not the 12.7/8.1 kcal/mol reporting
discrepancy, nor evidence of exact bitwise parity between every kernel path.

The observed bounded-population agreement and decomposition support the
different-evaluator explanation. They do **not** validate arbitrary chemical
states, flexible receptors, reactive/ring-glue atom types, all hardware, or
experimental affinity. This reference is explicitly scoped to the retained
ordinary dry rigid-ligand cases. General scientific acceptance and broader
pose-recovery benchmarking remain separate from this diagnosis.

## Reporting and integration consequences

- Subsequent source audit for the [broader crystal-control panel](autodock-gpu-control-assessment.md)
  establishes the scoped upstream ranking convention: for a freely roaming
  ligand and rigid receptor, reported AD4 binding energy is CPU intermolecular
  energy plus the constant torsional term, with internal energy canceled by
  `unbound_same_as_bound`. GPU total search energy still includes internal
  energy. Thus the large intramolecular table discrepancies above must not be
  presented as equally large binding-energy reporting errors. The panel retains
  both meanings and preserves original XML ranking when printed scores tie.
- Do not describe legacy CPU-table versus GPU-continuous differences as a
  same-formula numerical check. Keep search energy and legacy report rescore
  distinctly identified if this engine is integrated later.
- Do not silently change CPU report formulas or old scores to force agreement;
  no existing scores/reports were rewritten here.
- Keep the one-work-item Apple-GPU route rejected until it is genuinely repaired
  and validated. A completed process/event is insufficient proof of valid output.
- Normal-size repeatability and this two-ligand numerical audit do not by
  themselves authorize a production engine switch or establish superiority to Vina.

## Reproducible evidence

All paths are under `validation/runs/autodock-gpu-mac-20261016/`:

- [Combined follow-up analysis](../validation/runs/autodock-gpu-mac-20261016/remaining-limitations-analysis.json):
  all outcomes, executable/source hashes and pinned-source diffs.
- [Execution controls](../validation/runs/autodock-gpu-mac-20261016/execution-limits-ready/summary.json):
  ten invocations; all event records, launch sizes, timing and numerical outputs.
- [Unchanged-kernel completion control](../validation/runs/autodock-gpu-mac-20261016/repro-finish-control/summary.json):
  nine invocations; unsuccessful comparisons retained.
- [Candidate sizes and native rejection](../validation/runs/autodock-gpu-mac-20261016/gpu-candidate-checks.json):
  27 search invocations plus one expected rejection without docking.
- [Full matched-coordinate search audit](../validation/runs/autodock-gpu-mac-20261016/energy-audit/summary.json):
  two invocations, unchanged original search outputs and forty checked poses.
- [Matched-coordinate/formula analysis](../validation/runs/autodock-gpu-mac-20261016/energy-reference-analysis-v2.json):
  all populations, decomposition, residual statistics, hashes and worst entities.

The earlier empty `execution-limits` directory is a failed preflight before the
instrumented executable was available. No docking ran there. The isolated build
error was repaired and actual execution used the fresh `execution-limits-ready`
directory; no failed scientific calculation was automatically restarted.

Harnesses: `validation/autodock_gpu_execution_limits.py`,
`validation/autodock_gpu_followup_series.py`,
`validation/autodock_gpu_candidate_checks.py`,
`validation/autodock_gpu_energy_reference.py`, and
`validation/autodock_gpu_remaining_analysis.py`. Ten native unit tests cover
the earlier guards/inventories/fingerprints and independent formula, cutoff,
distance-rounding and batching controls.
