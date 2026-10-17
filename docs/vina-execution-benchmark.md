# Retained-input Vina execution benchmark

This is an isolated performance experiment, not a new production engine/default.
It uses the authorized 2R8N exploratory protocol and the two selected compounds
from the completed 2026-10-14 screen (source library records 1 and 51).
There is no experimental ligand pose for these two compounds: agreement with the
historical docked poses is an implementation-consistency check, not pose recovery.

## Fixed inputs and search budget

- Hash-verified original `.duprotocol`, receptor and 26 × 26 × 26 Å P1 box.
- Exact retained, typed ligand preparation: three conformers per compound, one
  retained chemical state each; no re-enumeration/minimization or changed charge.
- Vina 1.2.7, seeds 20260808–20260812, exhaustiveness 16, 15 saved poses per
  search, 8 kcal/mol output window, 1 Å within-search minimum pose separation.
- Explicit receptor-atom refinement remains enabled (`no_refine=False`).
- Thirty searches per arm, sequentially; no reduced sampling or parallel jobs.
- Baseline's explicit **2 Å** cross-run clustering override and three detailed
  representatives remain unchanged; software's new-study default remains 1.5 Å.
- Same clustering, PyMOL views, PLIP analysis, diagrams and PDF report pipeline.

## Execution variants

Historical baseline: existing command-line screen, one Vina process per
conformer/seed. The saved supervising job records **729.075674 seconds (12:09)**
for the whole screen. This differs from the user's roughly 16-minute observation;
the benchmark does not substitute one measurement for the other.

Shared-grid API arms: one in-memory Vina object per seed, receptor maps computed
for all atom types before loading a ligand, then reused across the six prepared
inputs. No disk map serialization/precision change. Vina 1.2.7 reinitializes the
search RNG from its seed at each `global_search` call. CPU settings are automatic
(`0`) and eight threads (`8`); eight threads does not pin to performance cores.

Measured separately: receptor setup, map generation, ligand loading, docking
search/refinement wall time and process CPU time, output writing and downstream
analysis/reporting. New preparation is excluded because exact prepared inputs
are deliberately reused. Historical file-log lifetimes are only approximate
diagnostics, not equivalent to the new instrumented stage timings.

## Validation and limits

Each new output is matched by compound, conformer and seed to its retained
baseline. `comparison.csv` records both lowest energies, their difference,
symmetry-aware heavy-atom RMSD of matching lowest-energy poses without fitting,
pose counts, and byte identity of the **entire** PDBQT output. Cluster tables are
also compared, not only selected representatives. Source/baseline hashes remain
unchanged. No production study state is modified by the benchmark.

This is one sequential run per setting on one M2 Max, against a historical
baseline, without randomized arm order or controlled temperature/background load.
It does not establish a universal speedup or a better docking/scoring method.
Original report filenames preserve their baseline study date; actual execution
timestamps and CPU settings are in each arm's `execution.json`.

The first analysis attempt selected the wrong Python via the shell wrapper and
failed to import RDKit. Analysis was explicitly resumed with the scientific
runtime; the completed 30 searches were not repeated. That recovery error is
retained in the series summary; recovery/validation idle time is not hidden in
the reported processing totals or described as engine work.

## Reproduction and retained results

Runner: `validation/vina_execution_benchmark.py`. A new run requires an unused
output directory, a completed baseline and no active scientific stage. Failed
analysis can be explicitly continued using `--resume-analysis`; completed docking
outputs are checked and reused, never silently rerun.

Current result directory: `validation/runs/vina-execution-20261015_095135/`.
The series `summary.json` is authoritative for completion/failure; per-arm
`execution.json`, `comparison.csv`, `comparison_summary.json`, full `report/`
outputs, native GUI-duration checks and retained logs provide the evidence.

Completed result: automatic shared-grid processing took 630.82 s (10:31),
eight-thread processing 581.60 s (9:42), both excluding reused preparation.
Each arm retained 450 poses across 30 searches; all complete PDBQT outputs,
both cluster tables and six PLIP interaction subtrees per arm match the baseline.
Five map builds consumed only about 3.58 s per arm; search/refinement dominated.
The observed improvement is modest and does not establish a universal optimal
thread count. Original protocol/baseline hashes stayed unchanged.

The GUI separately retains **total supervised run time** at the top of Screen
ligands after completion/reopen. This uses existing start/finish timestamps and
includes preparation, docking, analysis and reporting; missing timestamps are
explicitly unavailable. The benchmark does not overwrite that historical time.

## Subsequent thread policy and higher-count pilot

The user subsequently authorized a bounded eight-thread default for Vina on
Apple Silicon (limited to the available CPU count). Other platforms and
QuickVina-W retain engine-automatic behavior. Override it with `dock --cpu N`,
or set `DOCKING_UNIVERSAL_CPU=N` for CLI/GUI workflows. `0` explicitly requests
automatic threading. CLI, environment and saved config settings take priority,
in that order; `run_manifest.tsv` records the selected CPU value and its source.
More threads are permitted, not silently clamped to eight. Thread count does
not imply CPU affinity, and eight has not been established as universally best.

That initial production change selected only CPU threads. Subsequent persistent
batch integration and broader validation are documented in
[Docking execution performance](docking-performance.md). The original benchmark
reused maps across six inputs per seed; production batches retain maps across
the prepared inputs of one compound/seed. Its whole-run timing must not be
attributed to thread selection alone or presented as production timing.

`validation/vina_thread_sweep.py` tests 12, eight and ten threads sequentially
using both compounds, all three retained starting conformers, and two matched
seeds (12 searches per arm). Exhaustiveness 16, 15 requested poses and the
8 kcal/mol window remain unchanged for every search. This smaller timing pilot
does not repeat preparation, PLIP or reports, does not alter the saved protocol,
and compares complete PDBQT outputs to the retained baseline. One pass per count
with sequential order and uncontrolled background/thermal conditions cannot
establish a universal optimum.

Results: `validation/runs/vina-threads-20261015_12_8_10/summary.json` and each
arm's `execution.json`. The source inputs remain hash checked; an existing output
directory or active scientific study prevents an accidental duplicate launch.

Completed pilot (12 matched searches per count, preparation reused):

| Threads | Worker elapsed | Search/refinement | Complete outputs matching baseline |
| --- | --- | --- | --- |
| 8 | 197.45 s (3:17) | 193.36 s | 12/12 |
| 10 | 207.04 s (3:27) | 203.27 s | 12/12 |
| 12 | 223.13 s (3:43) | 219.16 s | 12/12 |

Eight remains the bounded default; ten and twelve are valid explicit overrides,
not demonstrated improvements on this machine/example. The independent native
GUI checks ran briefly during the sweep, another uncontrolled background factor.
No chemistry, sampling or result differences were observed, and retained source
inputs stayed hash-identical. This is not a full five-seed screen timing or a
universal hardware recommendation.
