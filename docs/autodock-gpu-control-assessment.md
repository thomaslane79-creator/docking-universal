# Corrected AutoDock-GPU crystal-control assessment — 2026-10-16

Status: main panel completed. The originally failed numerical gate is now
explained by an actual-kernel cutoff replay; KNI-577's outstanding audit passes.
See [cutoff resolution](autodock-gpu-cutoff-resolution.md) for the exact reference
boundary and unchanged gates. **Not production integration or blanket numerical
acceptance**. Historical failed results below remain preserved as reported.
The user authorized continued assessment before offering another engine, accepts
documented differences between engines, and requested that upstream-code
corrections be recorded in the README. Existing Vina settings, preparation,
studies and reports remain unchanged.

## Declared panel and measures

Reuse the first retained vacuum-MMFF94 conformer and exact existing neutral
chemical state, dry rigid receptor, deposited crystal ligand and approved box:

- Indinavir / HIV protease, 2R5P.
- Tipranavir / HIV protease, 2O4P.
- KNI-577 / HIV protease, 1MRW.
- Imatinib / Abl kinase, 1IEP.
- Geldanamycin / HSP90, 1YET: **unsupported, no search launched**. Its Meeko
  `CG0`/`G0` macrocycle pseudoatoms need a separate AD4 parameter/mapping review.
  Do not silently close the ring, change preparation, or treat this as a pass.

For each supported case, run seeds 41001/41002/41003 and repeat 41001, with
20 LGA run winners retained per invocation. Compare two declared settings:

1. Rotatable-bond heuristic plus convergence autostop, 12M evaluation cap.
2. Heuristics/autostop disabled, explicit 12M average-evaluation stopping target.

Both retain population 150, ADADELTA at 100% local-search rate, up to 300 local
iterations and 42,000 generations. This is the engine's average evaluation
stopping target across runs, not a hard individual-run cap. No settings are
silently increased after seeing a poor pose-recovery result.

Primary: experimental crystal heavy-atom RMSD of the upstream lowest estimated
binding-energy run winner, in the deposited receptor frame **without fitting the
ligand**, and recovery within 2 Å for each independent seed. Minimum RMSD across
all 20 winners is secondary, never substituted for the energy-ranked result.
The 2 Å recovery threshold is not the 1.5 Å pose-clustering cutoff.

Preserve XML's original ranking order. It is based on unrounded upstream
intermolecular values; two-decimal printed energy ties must not be re-sorted by
run ID or crystal RMSD. Tests explicitly cover this distinction.

Record complete printed populations, all pose inventories/charge/type/graph and
independent coordinate stereochemistry, native GPU completion, same-seed
pose/population/score equality, input/map/executable hashes and receptor-frame
checks. A correctness failure stops the series; no automatic failed-job retry.
Unsupported inputs remain explicit outcomes, not successful controls.

AD4 map-generation wall time, process wall time (including GPU setup/output),
and engine-reported job time are separate. Original chemical preparation,
PLIP/report generation and full-library throughput are not timed here. Historical
Vina outputs are read, not rerun: their scoring, effort and output budgets differ,
so they are scientific context rather than equivalent-work speedup measurements.

## Energy and ranking meanings

In pinned upstream `host/src/processresult.cpp`, the freely roaming dry-ligand
path ranks the 20 search winners using CPU-evaluated **intermolecular** energy.
Its estimated binding energy adds the constant torsional term; under the default
`unbound_same_as_bound` convention, intramolecular energy cancels. The GPU search
itself minimizes a total that includes intramolecular energy. These are
deliberately distinct quantities, not two interchangeable binding energies.

Each result retains upstream XML binding/intermolecular/internal/torsional
components plus the corresponding population winner's GPU search total and CPU
diagnostic total. The earlier large intramolecular distance-table discrepancies
must not be described as equally large errors in reported binding energy, since
that internal term cancels in this scoped reporting path. No scoring formulas or
original energies have been rewritten to force agreement.

## Corrections relative to upstream

Pinned AutoDock-GPU v1.6 source:
`e63e6f6280ebfad18caa3e8f48afdc269e79e063`.
This panel uses the previously built guarded 128-work-item candidate, not a
tracing/profiling/energy-audit build. Executable SHA-256:
`062b5816f8342fa4c2150d65852e83f52940fe2f2cb603710e27527b33a9d02a`.

1. `device/calcMergedEneGra.cl`: replace the erroneous no-barrier comment after
   the intermolecular atom loop with `barrier(CLK_LOCAL_MEM_FENCE);`. Finish
   non-atomic shared atom-force writes before other work-items atomically add
   intramolecular forces to the same arrays. Generated `host/inc/stringify.h`
   is rebuilt from the corrected kernel; it is not a separate hand-authored fix.
2. `host/src/main.cpp`: Apple-GPU builds with one work-item per group return
   status 64 before OpenCL initialization/search. This is a safety guard for
   a still-unrepaired configuration, not a claim of a one-work-item repair or
   an upstream platform prohibition.

The [README](../README.md#experimental-gpu-assessment-and-upstream-code-corrections)
summarizes these changes; the [exact two-file patch](../validation/patches/autodock-gpu-v1.6-local.patch)
is retained outside the run directories. Exact source diffs, previous failed controls and
executable hashes remain in the [numerical validation record](autodock-gpu-numerical-validation.md)
and [reproducibility investigation](autodock-gpu-reproducibility.md). Earlier
GNINA Metal fixes belong to a different, failed experimental candidate and
are linked separately from the README.

## Evidence and acceptance limits

Live record:
[`control-panel-20261016_checked/summary.json`](../validation/runs/autodock-gpu-mac-20261016/control-panel-20261016_checked/summary.json).
Harness: `validation/autodock_gpu_control_panel.py`; seventeen local validation
unit tests pass, including unsupported types, search budgets, energy semantics
and rounded ties. An initial preflight exposed the need to reject macrocycle
pseudoatoms before applying the ordinary-ligand graph audit; it launched no
AutoGrid or docking job. The corrected preflight passes supported inputs and
explicitly rejects the macrocycle case without changing its chemistry.

The initial `control-panel-20261016` coordinator stopped after a successful native
map-generation and first GPU calculation: a too-literal log check rejected
alignment spaces between `OpenCL device:` and `Apple M2 Max`. Its failed summary
is preserved. A narrow, tested validator correction accepts whitespace, not a
different device or missing success message. The `_checked` assessment verifies
the exact native command, unchanged inputs/maps/engine and complete outputs,
records original file hashes, and reuses that completed calculation and its maps.
It does **not** rerun the first docking, restart a failed scientific calculation,
or overwrite the failed validator record. All subsequent searches are new work.

This panel is small: three controls share HIV protease, all four ligands are
relatively large, and only one starting conformer/state is used. Even a complete
technical pass does not establish universal pose recovery, experimental affinity,
all ligand sizes/targets, flexible-receptor support, all hardware, or superiority
to Vina. No automatic installation or default switch follows completion. Review
recovery, coverage and unsupported cases before deciding the scope of an optional
experimental engine.

## Observed results

The main panel completed **32 searches / 640 checked run-winner poses**. This
includes one verified successful calculation reused after the device-log parser
correction, not an additional duplicate search. All eight same-seed comparisons
match poses, complete printed populations and scores. All checked poses preserve
the validated chemical inventory and coordinate stereochemistry; source inputs,
maps and executable hashes are unchanged. Seventeen local unit tests pass.

| Control | Fast-setting primary recovery | Fixed-12M primary recovery | Median process wall, fast / fixed |
| --- | --- | --- | --- |
| Indinavir | 2/3; RMSDs 1.755, 3.705, 1.608 Å | 2/3; 1.645, 3.702, 1.643 Å | 9.12 / 73.94 s |
| Tipranavir | 3/3; 1.756, 1.846, 1.721 Å | 3/3; 1.734, 1.719, 1.733 Å | 9.14 / 61.81 s |
| KNI-577 | 3/3; 0.848, 0.879, 0.861 Å | 3/3; 0.858, 0.861, 0.864 Å | 5.08 / 56.74 s |
| Imatinib | 3/3; 0.396, 0.443, 0.514 Å | 3/3; 0.467, 0.471, 0.471 Å | 4.07 / 53.71 s |

Primary recovery is the upstream lowest binding-energy run winner within **2 Å
of the experimental ligand**, three independent seeds; repeated seed 41001 is
not counted twice. Best-of-20 recovery is 3/3 for every case/arm, **secondary**.
Thus indinavir finds a close pose but does not always rank it first. Longer search
does not improve the primary recovery count in this small panel. New AD4 maps
cost another 7.09/8.11/7.12/10.16 s per receptor/type set, reused across searches;
the table is not a full-library or equivalent-work Vina speedup measurement.

Detailed energies, secondary RMSDs, timing boundaries, historical Vina context,
repeat counts and hashes:
[`control-panel-analysis.json`](../validation/runs/autodock-gpu-mac-20261016/control-panel-analysis.json).

### Additional atom-type numerical audit: failed strict gate, no retry

A separate post-panel audit was declared for the newly added fluorine/sulfur
controls, using raw-coordinate capture and the existing independent reference.
Its gates were saved **before** seeing results: bounded absolute residual
≤0.001 kcal/mol, winner residual ≤0.0001 kcal/mol, and all-population scaled
residual ≤1e-5, where scale is `max(1, abs(reference), abs(GPU))`.

Tipranavir's instrumented search exactly reproduces the uninstrumented poses,
scores and complete printed populations; its twenty output poses also pass the
chemistry checks. Its matched-coordinate/formula winner maximum discrepancy is
**0.00000363 kcal/mol**, but one of 3,000 population members fails the scaled
gate. Run 2/entity 24 has GPU energy −0.907500744 and reference −0.908432894
kcal/mol, a difference of **0.000932150**. It meets the separate 0.001 absolute
gate but not the stricter scaled gate near zero. We have **not** changed the
gates, removed this state, or declared overall numerical acceptance.

The precise source of this small residual is not yet isolated; do not assume
that explaining the earlier CPU distance-table discrepancy explains this new
matched-formula residual. All absolute extremes remain retained too (maximum
66.54 at a GPU energy of 302,790,976; float32 spacing 32). The audit stops at
the failed gate: **KNI-577's additional numerical audit was not launched**.
No automatic restart, tolerance relaxation, production installation or default
change follows this failure. All search workers have exited.

Evidence:
[`control-panel-atomtype-audit/summary.json`](../validation/runs/autodock-gpu-mac-20261016/control-panel-atomtype-audit/summary.json).
The next numerical task is to isolate the near-zero residual in the retained
raw arrays/grid evaluation before claiming the expanded audit passes. Cross-
engine differences remain acceptable and explicitly labeled; this stricter
same-formula check is a separate question.

## Subsequent optional-engine integration boundary

After reviewing these results, integration is a distinct end-to-end task, not
just adding a dropdown item. It needs an engine-specific AD4 map/search/output
adapter, exact patched-build provenance, explicit unsupported-input failures,
and GUI explanations of LGA/search effort rather than relabeling those settings
as Vina exhaustiveness. Record actual grid extents separately from requested
box geometry; map-cell expansion must not be hidden in a locked protocol.

Reports, graphs, pose browsing and PLIP inputs must preserve exact pose identity
and identify AD4 estimated binding energy instead of labeling it Vina energy.
Keep GPU total search energies distinct. A Vina control cannot authorize AD4
screening, and a failed GPU search cannot silently fall back to Vina and mix
its results into an AD4 run. Existing Vina defaults and previous reports stay
unchanged. These are integration requirements, not claims of completed work.
