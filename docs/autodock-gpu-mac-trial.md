# AutoDock-GPU on Apple Silicon — isolated trial, 2026-10-16

Status: default pilot and explicit no-early-stopping indinavir follow-up
completed on the actual Apple M2 Max. This is
not production acceptance. No application defaults, studies, preparation,
protocols or reports were changed.

## Runtime and provenance

The unmodified official AutoDock-GPU **v1.6 ARM64 OpenCL** executable runs on
macOS 27.0.1 and reports `OpenCL device: Apple M2 Max`. Its supplied two-run
smoke fixture finishes successfully. This is actual docking-search execution,
not CNN rescoring or a rendering-only GPU test.

- [Official release](https://github.com/ccsb-scripps/AutoDock-GPU/releases/tag/v1.6).
- Release source tag: `e63e6f6280ebfad18caa3e8f48afdc269e79e063`, clean checkout.
- Downloaded binary SHA-256:
  `8787489e84f0e6f602cc50b5dfaab19c63744a90400521f8f31cf4d800cd8519`.
  This is a locally recorded hash, not an independently published vendor checksum.
- Existing native `/usr/local/bin/autogrid4`, version **4.2.8**, generates maps.
  SHA-256 `cc7fdf7096c9d3f0d2dfd2a40a0bc998810c7eca163ea4566b3f95800fa0bc4b`.
- No Homebrew/system upgrade, security-control bypass, remote job, new working
  environment or production installation. All new files are isolated validation
  code/results and documentation.

## Inputs and declared search

One exact retained PDBQT conformer/state per case: indinavir/2R5P crystal control
(45 heavy atoms) and the slow flexible 2R8N-screen compound (37 heavy atoms).
Receptors remain dry and rigid; no new chemical states, minimization, conformer
generation or ligand fitting. Atom order, charges, AD4 types and heavy-atom graph
are preserved; stereochemistry is also independently assigned from output 3D
coordinates and checked against the input. Original file hashes are checked.

Maps use the retained centers and 0.375 Å spacing. Even grid intervals round
26 Å requested edges **up** to 26.25 Å, never reducing the search region. Centers
retain six decimals. Map generation takes 7.11 s (indinavir) and 4.05 s (screen
compound), including process polling overhead; maps are reused within each case.

Default pilot: 20 LGA runs per invocation, population 150, ADADELTA local search
with at most 300 iterations, 42,000-generation ceiling, rotatable-bond evaluation
heuristics enabled (12-million asymptotic limit), convergence autostop enabled.
All 20 run winners are retained and inspected, without filtering by crystal RMSD.
Clustering is 1.5 Å and does not filter these outputs. Two fixed seeds and a
repeat of the first seed per case give six invocations and **120 retained poses**.
All 120 pass the checked atom/charge/type/graph/stereochemistry invariants.

This is AutoDock4, **not Vina**: neither energy values, search budgets nor output
counts are interchangeable. Twenty LGA runs are not twenty Vina seeds or an
equivalent exhaustiveness. Map creation, process wall time and engine-reported
job time are recorded separately; PLIP/report rendering are not timed.

## Default pilot results

| Case / seed | Reported job time | Process wall | Lowest-energy AD4 pose | Crystal RMSD of that pose | Best-of-20 RMSD (secondary) |
| --- | ---: | ---: | ---: | ---: | ---: |
| Indinavir 41001 | 5.57 s | 6.10 s | −13.77 kcal/mol | 4.15 Å | 1.50 Å |
| Indinavir 41002 | 4.63 s | 5.07 s | −14.05 kcal/mol | 3.71 Å | 1.56 Å |
| Indinavir 41001 repeated | 8.66 s | 9.16 s | −14.27 kcal/mol | 1.77 Å | 1.26 Å |
| Flexible screen 20260808 | 13.20 s | 14.18 s | −6.65 kcal/mol | No experimental pose | — |
| Flexible screen 20260809 | 9.21 s | 10.13 s | −6.73 kcal/mol | No experimental pose | — |
| Flexible screen 20260808 repeated | 36.90 s | 37.50 s | −7.04 kcal/mol | No experimental pose | — |

Primary RMSD is RDKit symmetry-aware heavy-atom `CalcRMS` in the retained receptor
frame, without pose fitting. The first two independent indinavir seeds do not
rank a ≤2 Å pose first, although both searches contain one. The repeat does.
Do not report this as three independent seeds or a robust recovery percentage.

Repeating the same explicit seed does **not** reproduce identical poses or
runtime. Source inspection confirms the explicit seed is passed to initial-
population and GPU-PRNG initialization; the cause of the observed divergence
has not been isolated. Do not promise strict seeded reproducibility.

Subsequent user-authorized controlled investigation:
[same-seed diagnostics and isolated synchronization candidate](autodock-gpu-reproducibility.md).
The statements above describe the original unmodified-release pilot; they do
not incorporate the later instrumented/source-variant experiments.

A separate receptor-only A↔B C-alpha alignment tests the possibility of an HIV
protease dimer flip. It fits 198 anchors at 0.58 Å, but the top poses are around
9.95–10.81 Å from that alternate crystal placement. This secondary approximate
symmetry diagnostic does not explain away the primary discrepancies; it does
not alter the reported RMSDs.

## Numerical checks and limitations

The engine's CPU recomputation is retained for every final population member:
18,000 rows across the six default invocations. For the 120 run winners, maximum
absolute CPU/GPU **total search-energy** differences are 0.041 kcal/mol for
indinavir and 0.006 kcal/mol for the screen ligand. These are not independent
experimental binding-energy validations.

Across all population members, agreement is not uniformly this close. Highly
penalized/clashing states have very large absolute residuals; even the subset
with CPU/GPU absolute energies ≤1,000 kcal/mol reaches 24.001 kcal/mol difference.
Maximum scaled discrepancy reaches about 0.50 when normalized by
`max(1, abs(Ecpu), abs(Egpu))`. No rows are discarded from the audit. The cause
and effect on search decisions have not been established. Therefore the pilot
must not be labelled an exhaustive numerical correctness pass.

## Historical Vina context — not a matched speedup

Existing eight-thread Vina 1.2.7 outputs for the same retained first conformers
and first two seeds are reused rather than redocked. Indinavir searches took
44.62/46.12 s; their lowest-energy crystal RMSDs were 1.22/1.26 Å. The flexible
compound searches took 27.49/27.08 s. These are historical search timings, not
fresh side-by-side thermal controls or complete study elapsed times.

The fast AD4 defaults therefore look worth investigating, but do **not** establish
a like-for-like speedup: scoring, optimization, search budget, early stopping
and output inventory differ. The flexible-compound repeat also exceeds those
historical Vina search times. No experimental pose is available for that compound.

## Controlled early-stopping diagnostic

To distinguish premature convergence from ranking/search differences, a new
indinavir-only arm reuses the exact completed maps, with autostop and heuristics
disabled and an explicit 5,210,753-evaluations-per-run limit—the same ceiling
selected by the initial indinavir heuristic. Other declared search parameters
remain unchanged. Its two seeds are recorded separately; this is not a silent
restart, a rewritten pilot result or a production-default change.

Results: `validation/runs/autodock-gpu-mac-20261016/indinavir-no-autostop/summary.json`.

| Seed, early stopping disabled | Reported job time | Process wall | Lowest-energy AD4 pose | Crystal RMSD | Best-of-20 RMSD (secondary) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 41001 | 31.57 s | 32.43 s | −14.26 kcal/mol | 1.642 Å | 1.339 Å |
| 41002 | 31.36 s | 32.45 s | −14.25 kcal/mol | 1.645 Å | 1.332 Å |

Both independent seeds now rank a ≤2 Å pose first. These forty additional poses
also pass the retained chemistry/charge/type and independent 3D stereochemistry
checks. This supports early stopping as a contributor to the initial problem;
it does not prove it was the only cause, guarantee recovery on other targets,
or resolve the observed same-seed/numerical discrepancies. This diagnostic does
not include another same-seed repeat. No no-autostop trial was run for the screen
compound, so do not extrapolate a quality-preserving throughput gain to it.

The ~32 s per-search process wall times versus historical ~45–46 s Vina search
times suggest only a **modest cross-engine advantage**, with unlike timing
boundaries and search methods—not an established hardware acceleration factor.
First-use AD4 map generation adds ~7 s for this target; Vina also has setup costs
not included in its quoted search times. The ~5 s default is not the appropriate
quality-supported timing to advertise from this control.

Conclusion: **viable experimental candidate, not a bust and not production-ready**.
Actual local GPU search works without source repairs. Broader crystal controls,
repeatability/numerical audits and comparable quality/time measurements are
needed before any optional integration. The production Vina workflow is unchanged;
all pilot and diagnostic processes completed and exited.

## Evidence

Under `validation/runs/autodock-gpu-mac-20261016/`:

- `release.json`, `source/`, `tools/`, `help.txt`, `smoke/`.
- `pilot/summary.json`: all commands, process IDs, original/map/pose hashes,
  times, pose inventories and independent crystal RMSDs.
- `analysis-with-scaled-errors.json`: historical Vina outputs/hashes, CPU/GPU
  residuals, actual evaluation/generation counters and symmetry audit.
- `indinavir-no-autostop/summary.json`: separate controlled diagnostic.
- Every map/AutoGrid log, docking stdout/stderr, XML/DLG, 20 individual pose
  files and 20 full-population CPU/GPU energy tables per invocation.

Five harness unit tests pass (map bounds/precision, active-job guard and missing,
duplicate/non-finite run rejection). The pilot stops its own worker if another
GUI scientific job becomes active, and does not retry failed jobs automatically.
