# Apple-GPU docking feasibility — 2026-10-15

Status: **full-search acceptance failed; do not integrate this candidate.** The
isolated engine builds after repairs and numerical checks pass, but the first
real Metal docking search crashes. No completed paired speed comparison exists.
No production engine, protocol or study was changed.
The cancelled CPU-splitting follow-up remains cancelled.

## Machine and post-update checks

The user independently upgraded from macOS 15.7.9 to **27.0.1**. The device
identified by Metal is **Apple M2 Max**, with unified memory. Scientific Python
3.9.23, RDKit chemistry, gemmi 0.7.3, Meeko 0.7.1 and Vina 1.2.7 load correctly.
Ninety-one Qt workflow-panel/workspace tests pass after the update. These are
runtime/regression checks, not a completed native interactive user journey.

## Pinned candidate and source audit

Candidate: the experimental [GNINA Metal contribution](https://github.com/gnina/gnina/pull/345),
with a sparse local checkout at commit
`c8d5500fcf8ee7ec0ebfdc0583fb0fcb47daf86c`. No pretrained CNN weights were fetched.

The source has actual pair-energy/force and tree-gradient Metal kernels, not
only CNN rescoring. However, cached grid evaluation and BFGS coordination retain
CPU code, with synchronous GPU dispatches. The upstream empirical GPU path
explicitly warns that it is experimental. Neither GPU saturation nor a large
docking speedup follows from the presence of these kernels. GNINA is derived
from smina/Vina but is not the same executable/search as stock Vina 1.2.7.

Inspect the pinned [scoring implementation](https://github.com/fnachon/gnina/blob/c8d5500fcf8ee7ec0ebfdc0583fb0fcb47daf86c/gninasrc/lib/gpucode.cu)
and [Metal kernels](https://github.com/fnachon/gnina/blob/c8d5500fcf8ee7ec0ebfdc0583fb0fcb47daf86c/gninasrc/lib/gnina_kernels.metal).

Druse's documented macOS 26 minimum is no longer an OS-version obstacle after
the user's update, but that engine has not been built or tested here. It changes
the search implementation and is not a ready interchangeable Vina backend.

## Actual GPU smoke test

`validation/apple_metal_probe.mm` loads the unmodified pinned shader source
through Metal's runtime compiler. It does not use the fork's full host runtime,
Torch, libmolgrid, preparation routines, or docking search. No optional compiler
component or new dependency package was installed for this test.

- All six upstream Metal functions compile on this device.
- Scalar multiply: maximum absolute error **0**.
- Pair energy and force: maximum absolute error **7.63e-6**.
- Curl, out-of-bounds correction and total-energy reduction: maximum absolute
  error **1.53e-5**, below the **1e-4** test tolerance.
- Fixtures use a controlled quadratic spline, heavy atoms plus an ignored
  hydrogen, receptor cutoff and an out-of-bounds ligand atom. Non-finite results
  fail explicitly. This is not an exhaustive chemical scoring validation.
- Command buffers report successful GPU execution and nonzero GPU timestamps.
  Microsecond kernel timings are not docking acceleration measurements.
- At this initial smoke-test stage, tree kernels only compiled. The later native
  checks below numerically exercise them; the full-search gate still fails.

Evidence, source/probe SHA-256 hashes and exact executable arguments:
`validation/runs/apple-gpu-feasibility-20261015/post-update/metal-probe.json`.
The same folder retains stdout/stderr and the isolated probe executable.

## Authorized isolated full-engine validation

The user approved the optional Apple Metal compiler and full validation. Component
**17C7003j** installed successfully. Explicit selection with toolchain identifier
`com.apple.dt.toolchain.Metal.32023.864` works; unqualified `xcrun metal` still does
not locate it. No OS/Homebrew upgrade or working Conda environment change was
performed. Apple documents [additional Xcode components](https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components).

Build dependencies live under the validation directory in `build-env`, `deps`
and `gnina-build`. GNINA remains pinned as above; libmolgrid is pinned at
`14a762508f5cf720fe910a306b2a705d60f95d09`. ARM libtorch 2.10.0 was fetched;
unused CNN weights/Python bindings were omitted explicitly. CNN scoring is off,
not substituted with a different neural scoring model. The experimental executable
was **not installed** into Docking Universal. Dependency lock, patch snapshots,
binary/Torch hashes and command logs are retained in the run directory.

| Gate | Observed result |
| --- | --- |
| Original embedded-library loader | Fails: invalid library. Replacing an invalid NSData-to-dispatch-data cast with actual dispatch data passes. |
| Original arena allocation | Native test requests ~21 GiB as one buffer and fails. Tested build caps arenas at 1 GiB per worker and respects maximum buffer length. |
| Original spline host pointers | Intramolecular scoring crashes because the Metal constructor never populates pointer-bearing `deviceData`. An isolated repair populates this table. |
| Native libmolgrid tests | **11/11 pass**, including four Metal-specific test executables. Two initial fixture-path failures are retained; correcting their working directory resolves them. Python-binding tests were not built/run. |
| GNINA numerical checks | **5/5 pass for each of three seeds** (41001–41003): pair scoring/forces, intramolecular scoring/forces, coordinate transforms, actual Metal tree gradients, cached grids. Existing tree skip stubs were replaced with real comparisons. Energy/force/generalized-gradient tolerances are 0.01; command errors and non-finite tree outputs fail. All five dispatched kernel types report nonzero GPU execution times. |
| Direct retained-PDBQT compatibility | Fails chemical round-trip verification after CPU local refinement: output lacks the expected hydrogen/bond/stereochemical information. This is not evidence that the original retained input was chemically wrong. |
| Explicit mapped-SDF path | Meeko SMILES/atom-map reconstruction preserves chemical identity and heavy coordinates (no fitting, minimization or state enumeration). CPU/Metal local-refinement outputs retain the expected graph/stereochemistry for indinavir, imatinib and the flexible current-screen compound. |
| Full docking search | Indinavir CPU finishes; the matched Metal search crashes with SIGSEGV after 2.88 s, before returning poses. **Acceptance fails.** |

Fixed-coordinate score agreement for the starting conformers is only a limited
preflight: imatinib and the current-screen input start away from the receptor and
both score zero. This is not an informative bound-pose energy/ranking validation.
Local refinements use different optimization paths and are not identical: for
indinavir they return −1.12873 versus −1.04483 kcal/mol. These local results must
not be described as matched docking recovery or speed measurements.

### Full-search failure and boundary

The retained failure log and macOS crash report identify:
`gpu_data::node_idx_cpu2gpu` → `change_gpu` → `quasi_newton` → `monte_carlo`.
Source inspection finds that `model` copies initialize `gdata.device_on` to false,
while the task-copy constructor tests the copied flag before copying GPU atom/tree
mappings. Consequently, the GPU cache optimizer can receive missing mappings.
This is a specific likely cause supported by the null-pointer crash stack, not a
verified repair. Further work also needs to audit arena lifetime/allocation growth,
thread ownership, parameter equivalence and complete output chemistry.

The single completed GNINA CPU search took 30.09 s and returned a lowest-energy
pose of −12.50542 kcal/mol with experimental no-fit heavy-atom RMSD 1.296 Å.
That is **not a CPU/GPU comparison**, and the crashed 2.88 s run is not a speedup.
Remaining seeds, repeats, imatinib/current-screen full searches, bound-pose ranking
checks and stock-Vina comparison were not completed after the fail-closed gate.
There is no validated acceleration, ranking, recovery-rate or repeatability claim.
All validation workers have exited; no unattended retry or production fallback
was activated. The working CPU application remains unchanged.

Evidence under `validation/runs/apple-gpu-feasibility-20261015/`:

- `molecular-validation-01/summary.json`: direct PDBQT compatibility failure.
- `molecular-validation-mapped-sdf-01/summary.json`: explicit alternate format,
  complete preflight records and the first full-search failure.
- `numerical-1g-41001.log` through `41003.log`: repaired numerical suites.
- `libmolgrid-ctest-corrected-cwd.log`: eleven native dependency tests.
- `patches/`, `build-env-explicit.txt`, `validation-sha256.txt`: reproducibility.

Conclusion: the OS/hardware/compiler now support native Metal work, but this
experimental fork is not a safe drop-in docking backend. Its kernel smoke tests
do not establish full-engine correctness or NVIDIA-like acceleration.

## Subsequent alternative — 2026-10-16

The user authorized a separate test of official AutoDock-GPU v1.6. Its release
includes an ARM64 macOS OpenCL executable and earlier Apple-Silicon fixes; the
older README platform table alone understated this support. Actual M2 Max
pilot searches completed without source repairs, but later same-seed tests exposed
a shared-force race. The corrected isolated candidate and its safety guard are
documented in the [main README](../README.md#experimental-gpu-assessment-and-upstream-code-corrections).
This uses AutoDock4, not the GNINA
fork or Vina. See [separate AutoDock-GPU results](autodock-gpu-mac-trial.md) for
timing, recovery, early-stopping and numerical/repeatability limitations. This
does not change the failed acceptance status of the GNINA Metal candidate.
