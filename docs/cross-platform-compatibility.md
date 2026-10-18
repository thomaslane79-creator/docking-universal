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
| Native Windows | Safety contracts, fresh preview bootstrap, actual Qt desktop/host startup and installed prepared-input Vina repeats passed on Windows Server 2022/x64; native Python/PowerShell, not WSL/Git Bash | Complete scientific installer, preparation/screening/report journey, native PyMOL or GPU acceptance |

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

### Scientific port continuation (2026-10-18)

The user requests the next dependency/preparation/docking/report slice fully.
Fresh native scientific tests preserve every scientific pin in `environment.yml`;
only Unix installer tooling (`make`) and the unavailable optional fpocket build
are explicitly omitted. Missing fpocket must not silently change the detector.
All Windows GUI scientific stages remain disabled until real workflow acceptance.

The scientific package set **solves on Windows**. Its first actual installation
then failed in Conda-forge's `khronos-opencl-icd-loader=2024.10.24=hfd05255_2`
activation scripts with a spaced prefix. `windows_activation.py` applies a
hash-guarded, backed-up quoting/synchronous-call repair in the fresh test prefix,
before installing the unchanged pip pins. It also handles an empty vendor
directory. Unknown upstream script revisions stop for review. No OpenCL DLL,
scientific package version, chemistry setting or engine is replaced. This repair
and the subsequent imports passed on native Windows Server 2022/x64 in
[scientific dependency CI 39152906751](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39152906751)
at `c85b283`. Python 3.9.23, RDKit 2023.09.6, Meeko 0.7.1, PDB2PQR 3.6.2,
ReportLab 4.2.5 and the complete declared Conda stack installed/imported in a
fresh spaced prefix. The first import probe incorrectly imported Reduce2's CLI,
which exits after printing help; the accepted probe imports its program module.
This is dependency acceptance, not a completed native scientific product.
Source package SHA-256:
`245bd150a9f0b922dc34f173027631a20f18b009604d827a796d792a79bac178`;
[upstream feedstock revision](https://github.com/conda-forge/khronos-opencl-icd-loader-feedstock/tree/80ef539ea6232963e476eb9e616dd4a3379603dc),
Apache-2.0. Original scripts and before/after hashes remain in the test prefix.

Native process ownership uses Windows kill-on-close job objects. A trusted,
isolated Python wrapper joins the private job and closes its own job handle
before starting a scientific command; the supervisor then owns its lifetime.
No shell/process-name killing or private thread-resume APIs are used. All six
native job tests passed at `285f859`: cancellation, timeout, owner crash,
closed-owner rejection, normal-completion descendant cleanup and missing-owner
refusal. The native safety job passed 55 tests, including real spaced-prefix
activation-script execution, and the desktop host now uses the same ownership
boundary. Jobs also
cover descendants that inherit output pipes, so those pipes cannot keep a
cancelled calculation alive indefinitely. This implements the documented
[Windows job-object contract](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects),
including [nested jobs](https://learn.microsoft.com/en-us/windows/win32/procthread/nested-jobs).

The scientific candidate is deliberately not wired to the Windows desktop yet.
`native_preparation.py` ports the established fixed-column component filter,
native mmCIF projection, audited Reduce2, strict Meeko/conservative PDBFixer and
direct Java/P2Rank 2.5.1 invocation. It requires fresh outputs, preserves failed
partial artifacts and never lets them satisfy a subsequent attempt's guard.
Unported ADFR/fpocket/ligand-only routes and deletion-permitting legacy retries
stop explicitly instead of silently changing methods. The selected native
route is not advertised as full compatibility for all preparation cases.

Python scientific scripts on Windows are invoked with their explicit
interpreter instead of relying on .PY file associations; .CMD/.BAT scientific
commands are rejected rather than sending coordinate paths through a shell.
Unix command invocation and scientific defaults remain unchanged.

Native scientific CI at `e848732` additionally passes the real public PDB and
mmCIF preparation paths and protocol PDF/portable bundle generation with four
rendered pocket panels. The earlier PATH-selected Java failed at startup;
the candidate now bypasses system/Conda command proxies, selects the real executable inside
the scientific prefix and verifies Java 17/P2Rank 2.5.1 before calculation.
The next boundary exposed pinned RDKit's narrow Windows filename API: writing
an SDF under a Unicode directory failed. `sdf_io.py` uses Python-opened streams
on Windows, preserving the existing RDKit reader/writer operations and options;
Unix still calls the original filename APIs. Meeko export is staged locally and
copied byte-for-byte because its own pinned writer has the same limitation.
Native stream tests compare atoms, maps, hydrogens, standard SDF round-trip
stereochemistry, coordinates and properties; no geometry optimization is added.

Local parity against the established Bash route finds byte-identical prepared
2R8N PDB/PDBQT. The candidate preserves the actual legacy box geometry and
center precision rather than only the normalizer's rounded coordinates. A
legacy ordinal overwrite that would assign one retained detector rank another
pocket's box stops for review; it is not silently reproduced or fixed by
changing an existing study. The working Unix preparation source is untouched.

A later protection check found the pre-existing, stale Conda ReportLab 5.0.0
record absent while the active pip-installed ReportLab 4.2.5 and all other
protected installation/study files still matched. No package was installed or
replaced to repair that record. Because Conda's pip reconciliation can remove
stale metadata even during listing, runtime inventory now reads Conda JSON and
Python distribution metadata directly, without importing scientific code or
invoking `conda list`. A regression test verifies a pip override is reported
while its stale Conda record remains byte-identical. The original 697-file guard
therefore has one metadata-only exception; it must not be reported as entirely
unchanged.

Further native execution exposed a Windows entry-point naming difference:
Meeko installs `mk_prepare_ligand.exe` / `mk_export.exe`, not the Unix `.py`
command names. Default native ligand preparation now invokes the pinned Meeko
module with the scientific Python; explicit custom commands stay authoritative.
Other standard script-tool discovery accepts the installer-stripped suffix.
Native run `39157453834` reaches completed chemical states, Meeko ligand atoms,
Vina docking and pose clustering after correcting the exporter lookup. It then
stops inside PLIP; this is not a completed native scientific workflow. The next
candidate runs pinned PLIP with unchanged flags and byte-identical copied input
through ASCII relative filenames in its owned output directory, avoiding
OpenBabel's narrow Windows filename boundary. Custom commands remain explicit,
and Unix invocation is unchanged. This correction still needs native acceptance;
backend diagnostics remain local and CI exposes only fixed failure categories.
Protocol ZIP manifests now serialize relative paths with forward slashes, so a
Windows-produced bundle does not encode OS-specific separators for Linux/macOS.
No coordinates or scoring parameters are changed by these corrections.

The Windows renderer gate installs the already-pinned Playwright dependency
with lifecycle scripts and audit submission disabled, uses local Chrome/Edge,
and requires the approved renderer policy rather than treating any fallback
PNG as full renderer acceptance. Browser navigation constructs a proper file
URL (including Windows drive letters, spaces and Unicode) instead of string
concatenation. Structures remain local throughout.

The public 2R8N PDB and locally generated equivalent mmCIF both complete the
candidate preparation path on this Mac. A small synthetic-carbamate rehearsal
also completes protocol PDF/bundle creation, pH-aware independent ligand states,
Vina docking, 1.5 Å clustering, PLIP, 2D/3D panels and the screening PDF through
the existing report pipeline. It explicitly uses one conformer/seed and
exhaustiveness 1 **only as process acceptance**, not affinity/pose accuracy or a
new default. Its native Windows counterpart is a separate gate. CI exports only
dependency/stage metadata: no structure, pose, diagram, report or scientific
tool log is uploaded.

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

### Native bootstrap under validation

`install-windows.ps1` is a **development bootstrap, not the finished installer**.
It requires native x64 Windows, Miniforge/Conda, a new destination directory and
explicit `-AcceptDevelopmentPreview`. It creates two isolated Python 3.12
bootstrap environments (host and Qt6 desktop), copies application code/bundled
assets only, and checksum-verifies the official Windows Vina 1.2.7 executable.
These are not replacements for the pinned Python 3.9 scientific environment.
No Bash, Git Bash, WSL, administrator access, global PATH changes or existing
environment updates are used. Failed/old destinations are retained, not deleted.

The preview exposes version, installation status, runtime inventory, desktop
startup and prepared-input Vina CLI only. `check-install --full` **fails** because
the scientific installation is unfinished. Unsupported workflow commands and
GUI scientific-stage requests are rejected before registering a job or changing
study state. Desktop defaults to a separate preview study root and no PyMOL
backend; no native PyMOL/OpenGL acceptance is claimed. Native preparation,
complete screening/reporting, dependency solving and native process-tree
cancellation still require their own implementation/acceptance.

The host client now reads framed responses on a dedicated, session-owned thread
rather than applying Unix pipe selection to Windows. Complete-frame timeouts
also cover partial lines; malformed/incomplete replies and timeouts close the
session so a late acknowledgement cannot be used for another mutation. The
reader is stopped/joined on normal shutdown/restart. Windows Python prefixes
and DLL/executable directories are resolved using their native layout.
UTF-8 is explicit for pipe messages, independent of the Windows console locale.
Large library replies remain supported; the 1 MB command-size guard is not
incorrectly applied to response indexes.

CI tests both public PowerShell/CMD entry points, an actual Qt window connected
to the installed host, Unicode/spaced paths, restart/lease release, rejection
without state changes, and repeat docking through the **installed** dispatcher.
Only status metadata is retained as an artifact, not screenshots, studies or
pose files. This bootstrap acceptance **passed** on Windows Server 2022/x64 in
[run 39136914638, native bootstrap job](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39136914638/job/117703179381),
at source checkpoint `252466b`. All six checks passed. Bootstrap/runtime and
study paths include Unicode; the Vina fixture's input/output paths include
spaces. Unicode coordinate-file paths, interactive PyMOL/OpenGL, consumer
Windows variants and full scientific journeys are not established by this test.
Both installed-dispatcher Vina runs retained three finite-energy poses, with
identical output SHA-256
`9f7a5658d234c5b934c44ff89c985ea429fca29cfe9d044db4ca24ecc8383103`.

The first two native bootstrap attempts failed during Conda environment
creation and were not counted as acceptance. The completed fresh run follows
explicit UTF-8 setup and native path derivation instead of parsing console text;
the installation script restores the caller's environment on exit. Existing or
failed destinations are still refused rather than silently overwritten/restarted.
Final source checkpoint `1f1b582` repeated the complete bootstrap acceptance
successfully in
[run 39137350895](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39137350895/job/117704472636),
including the later host-shutdown safeguards. All 37 safety/transport/entry-point
tests passed natively on each of Windows, Ubuntu and macOS 15. Local `make test`
passed 599 Python tests plus the shell checks; the separate Qt/workspace suite
passed 109 tests (some transport cases overlap). All 697 protected working
installation/configuration/study files remain hash-identical. These source
changes are on the existing feature branch, not installed into the working Mac
app or merged to main. The broader Mac/Linux real-tool jobs in that final CI
run were still running when this bounded bootstrap milestone was recorded;
native bootstrap success is not a claim that those jobs already completed.

Example for developers only (fresh destination required):

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\install-windows.ps1 -Destination "$env:LOCALAPPDATA\DockingUniversalNativePreview" -AcceptDevelopmentPreview
& "$env:LOCALAPPDATA\DockingUniversalNativePreview\bin\docking-universal.cmd" desktop
```

The execution-policy option applies only to that installer process; no machine
policy is changed. Inspect the trusted repository script before running it.

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
