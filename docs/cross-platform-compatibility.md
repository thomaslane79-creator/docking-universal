# Older macOS, Linux and native Windows compatibility

User direction, 2026-10-18: native Windows is required. WSL2 is **not** the
substitute or the definition of Windows support. Existing Mac installations and
scientific defaults remain unchanged while the port is developed.

## Current boundaries

| Platform/path | Current evidence | What is not established |
| --- | --- | --- |
| Apple Silicon, current Mac | Fresh installer, embedded/full PyMOL and accepted AD4 build tested | Identical results on all Apple GPUs/drivers |
| macOS 15 candidate GPU host | Same patched source compiled with minimum target 15.0; kernel unchanged; two synthetic repeats exactly match the accepted build on the current Mac | Older-OS native GPU execution and scientific acceptance; candidate is not activated |
| Linux | Existing Unix installer/environment and CI path; restored a failing test import | Complete release-level desktop/GPU acceptance across distributions |
| Native Windows | Native process locks, atomic-state/browser-discovery contracts and synthetic prepared-input Vina CPU adapter tests passed on Windows Server 2022/x64; native Python, not WSL/Git Bash | Complete native installer, preparation/docking/report journey, embedded PyMOL or GPU acceptance |

The minimum operating-system field in an executable is a build setting, not a
proof of driver compatibility. The accepted Mac GPU runtime still requires
macOS 26.2+. The older candidate is isolated and cannot pass the production
accepted-hash guard. No version check was simply removed.

## Older-Mac candidate

`validation/build_adgpu_compatibility.py` builds from the bundled pinned patched
source archive, using OpenCL, 128 work items, serial host execution and `-O3`.
Only the host deployment target changes to 15.0. The generated kernel header is
required to remain byte-identical. It records compiler command, binary/source
hashes, dependencies, deployment target and native executable-help loading.

The local candidate has SHA-256
`fc29b57d5471c552fbd49936b039bed858693ed4ff94abbaf7f6e94d5e6ae58e`.
Two retained nonbiological synthetic repeats on this Mac each match the
accepted-build normalized output byte-for-byte (20 winners each). This is not an
older-macOS driver test. Build and comparison records remain local under
`validation/runs/adgpu-macos15-compatibility-20261018/`.

CI separately builds and runs the help/loading check on `macos-15`, retaining
build metadata/logs only. It does not label help output as GPU search acceptance.
That native macOS 15 host-build/loading job passed in
[compatibility CI run 39131637146](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39131637146).
Before activation, the **exact intended distributed binary** must also undergo
native older-OS GPU tests, method/input identity checks and repeatability/failure
checks. A candidate rebuilt by a different toolchain is a different identity.

## Native Windows work, staged honestly

1. **Safety foundation:** real native inter-process workspace/state locking,
   atomic writes and ownership rejection. Previously, the missing `fcntl` import
   caused process locking to be silently skipped on Windows; that is corrected
   using the Windows CRT lock API. No application may silently run unlocked.
   State locks retain blocking behaviour; host ownership remains nonblocking.
2. **Dependency/installation:** a native launcher and installer, exact Windows
   engine provenance, supported Python/Conda layouts and paths containing spaces
   or Unicode. The current `install.sh`/public dispatcher are Unix shell programs,
   not an already-complete native Windows installer.
3. **Preparation/execution:** port the remaining POSIX preparation orchestration
   without changing its chemical/scientific decisions; native process-tree
   cancellation; P2Rank Java launch without unsafe batch-file argument handling;
   correct Windows executable resolution and failure/skip behaviour.
4. **Full native review/report journey:** local 2D rendering, PyMOL backend,
   controls, protocol creation/reuse, screening, PLIP, reports and exports. Local
   browser discovery now includes Chrome and Microsoft Edge in standard Windows
   machine/user locations; explicit browser overrides remain authoritative.
5. **GPU separately:** pinned native Windows/Linux CUDA/OpenCL builds, drivers,
   energy conventions, mapping/chemistry, repeatability and failure handling on
   actual GPUs. Mac acceptance does not transfer. Vina remains the default, and
   an AD4 protocol must never silently become a Vina calculation.

This is a substantial port, not a promise that a Windows entry point alone
establishes full compatibility. CPU functionality is verified before optional
GPU enablement. Installing dependencies that change a scientific method requires
its own explicit review, not an unrecorded package substitution.

## Dependency audit

The read-only official Conda-forge metadata audit on 2026-10-18 found no matching
`win-64` builds for the currently pinned **Vina 1.2.7** and **fpocket 4.2.2**.
All examined pinned versions had published Linux/macOS builds. Publication or
`noarch` presence is **not** a complete dependency solve, executable test, or a
promise that every Python ABI combination works.

Vina's [official 1.2.7 release](https://github.com/ccsb-scripps/AutoDock-Vina/releases/tag/v1.2.7)
is the source to assess for a native standalone Windows executable; do not
change the scoring method or version merely to make Conda solve. P2Rank remains
the primary detector. A missing optional fpocket fallback must be reported and
must not silently replace P2Rank or block otherwise valid primary-detector use.
Native package resolution and full installation acceptance remain work items.

The official `vina_1.2.7_win.exe` is now checksum-pinned in
`dependencies/vina-windows.json` (Apache-2.0 upstream license). A separate native
Windows CI job downloads and verifies that exact executable, then exercises the
existing Python docking adapter twice using synthetic prepared inputs, fixed
seed and paths with spaces. It does not depend on WSL/Git Bash, does not add a
half-working Windows installer, and does not upload structures or pose outputs.
This tests the native CPU adapter, not preparation, the full GUI or GPU support.
The test **passed** on native Windows Server 2022/x64 in
[CI run 39132054556](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39132054556):
both fixed-seed runs retained three finite-energy poses and their output files
were byte-identical. Input/output paths included spaces. This establishes
neither native Windows ARM support nor the unfinished full application journey.

The audit script is `validation/audit_platform_dependencies.py`; the local record
is `validation/runs/cross-platform-compatibility-20261018/dependency-builds.json`.
It accesses public package metadata only and installs nothing.

## Tests and limits

- Local full `make test` passed after correcting the site-review fixture import
  that had failed Ubuntu CI. This corrects test loading, not scientific logic.
- CI run 39131637146 completed successfully, including full CLI checks and
  real-tool integration validation on both Ubuntu and macOS. Production source
  was unchanged by the subsequent standalone Windows adapter-test addition.
- Native Windows/Ubuntu 22.04/macOS 15 CI runs the standard-library-only locking,
  state-transaction and browser-discovery contracts. These are foundational
  tests, not a full native Windows scientific installation.
  All three native jobs passed in CI run 39131637146.
- The older-macOS job checks a real host build and executable loading. GPU
  kernels/driver correctness remain a separate acceptance gate.
- CI uses standard public-repository runners, no paid GPU runner. Test logs/build
  metadata are retained; no local study or structural output is uploaded.
- All 697 protected working installation/configuration/study files remain
  hash-identical. None of this milestone is installed into the working app;
  changes are checkpointed on the existing feature branch, not merged to main.

References: [Microsoft CRT byte-range locks](https://learn.microsoft.com/en-us/cpp/c-runtime-library/reference/locking),
[Apple deployment targets](https://developer.apple.com/documentation/xcode/running-code-on-a-specific-version),
[GitHub standard runner platforms](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
