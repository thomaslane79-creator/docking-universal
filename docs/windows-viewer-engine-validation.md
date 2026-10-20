# Remaining native Windows validation

Date: 2026-10-20. These are isolated validation candidates, not new installed
capabilities. The previously accepted native P2Rank/Meeko/Vina GUI workflow is
unchanged. This record does not transfer Mac GPU approval to Windows.

Outcome: baseline installation/scientific/GUI and all eight general CI jobs pass
at `20e96a7`. The isolated Windows software viewer passes; default graphics
still crashes. QuickVina-W has a reproducible Unicode-path failure, and native
AD4 GPU execution is hardware/build-blocked. These are not all-engine/full-
desktop acceptance results.

## Viewer

The same upstream PyMOL source used for the Mac viewer
(`5e8bfca5a7f5dc4d5e7f84fa1d15af707cc86e69`, archive SHA-256
`81053fb954161ac7c8b34be581b5d2d0ae01bdd1ba7150c8d8f4a9c6537680b0`)
builds and installs in a fresh Windows Python 3.12/Qt6 prefix. Source is not
patched; the optional COLLADA, fast MMTF and VMD-plugin build switches match the
bounded Mac build. No Qt5 PyMOL package is inserted into the Qt6 runtime.

The first [native run 39414227294](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39414227294)
**failed**. Dependency installation took 98.1 seconds, source build 142.1 seconds,
and wheel installation 2.2 seconds. The viewer process then exited with native
access-violation code `3221225477`, after verifying the copied application and
prefix-owned extension but before recording a rendered framebuffer. This does
not establish rendering, detachment or export acceptance, nor identify the root
cause by itself.

The diagnostic follow-up records the native OpenGL context/driver before widget
creation and independently tests an explicitly selected, checksum-pinned Mesa
26.2.4 software path. It preserves the system-graphics result separately. Mesa
is loaded only inside this test process; no system driver, registry, working
installation or scientific setting is changed. A software-rendering pass is not
consumer GPU/driver acceptance. The [Qt Windows graphics guide](https://doc.qt.io/qt-6/windows-graphics.html)
explains the distinction between Qt's dynamically selected renderer and native
OpenGL dependencies; [Mesa's Windows distribution](https://github.com/pal1000/mesa-dist-win)
documents the llvmpipe software path. The pinned archive metadata is in
`dependencies/mesa-windows-validation.json`.

The [diagnostic native run 39415460688](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39415460688)
completed with **a system-graphics failure and a passed software path**, not an
all-paths pass. The default Qt context reported VMware llvmpipe, Mesa
12.0.0-rc2/OpenGL 3.0; context creation succeeded, but the process again terminated
with `3221225477` at engine launch. With the independently pinned per-process
Mesa 26.2.4 llvmpipe/OpenGL 4.6 path, **all 17 checks passed** in Windows
Python 3.12.15/Qt 6.11.2: real framebuffer colors, surface/box, same-engine full
detachment/return, preserved camera, ray export, prefix-owned extension, and no
Qt5 Python/native DLL mixing. No hardware GPU was used. The graphics-path
difference is demonstrated; a precise native crash/root-cause audit and actual
consumer-driver acceptance remain open. The test-only wheel/renderer is not
bundled into or activated by the default installer.

The test harness itself passes all 14 applicable checks against the previously
fresh-installed Mac runtime: native framebuffer colors, surface/box, same-engine
full detachment/return, camera preservation and ray export. This is a local
harness check, not Windows evidence. Its first local invocation used a Qt-only
prefix lacking PyMOL; a sandboxed native-graphics invocation also terminated.
Neither is counted as a passed viewer test. The correctly isolated native-
graphics invocation passed without changing a working environment.

## QuickVina-W

The [native package/guard probe 39414455353](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39414455353)
confirmed that conda-forge publishes `qvina=2.1.0` for `win-64`. The subsequent
[execution gate 39415104686](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39415104686)
installed the exact `he453025_8` package (package SHA-256
`354cdf5dcc9f2105999b7fd64d85fa7b3f8c57cea15dcc20e322dfe4ace1f5cc`).
Its executable reports `QuickVina-W 1.1 (24 Dec, 2017)` and hashes to
`89509afc51bd1576ab73c8684986991178f8ceec9438796073f2499a90594d1d`.

Two source-adapter runs with ASCII paths containing spaces produced three poses
each and **byte-identical complete outputs**, SHA-256
`cfb83e71e1c58ae11f6e870dd5eede5053333af989be7c3b8aa9992bee619495`.
The Greek/Japanese input-folder case **failed**, exit 1 with no output. Therefore
the prepared-input gate is not fully passed and the Windows GUI/installer still
does not enable QuickVina-W.

These nonbiological carbon fragments test execution, not accuracy, realistic
chemistry, performance or repeatability on other systems. They use seed 41001,
one CPU thread, exhaustiveness 1 and three requested poses. A separate explicit
diagnostic control tests the existing byte-preserving Vina path carrier with the
QuickVina executable; it does not change the production adapter or erase its
failure. Protocol/report/GUI and broader prepared-input acceptance remain separate.

The [diagnostic follow-up 39415652364](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39415652364)
retained the same successful repeats and the production Unicode failure, then
ran the separate path carrier with the **same executable, input/configuration
bytes and scientific flags**. That control exited 0 and returned complete pose
bytes identical to the ASCII reference. This isolates a viable filename-
transport correction; it is not installed or enabled for QuickVina-W. The CI
gate deliberately remains failed because the current adapter still fails.

## AD4 GPU and physical-machine limits

The native package/guard probe found **no OpenCL platform** (`-1001`) and zero
usable GPU devices on the Windows Server 2022 hosted runner. The application
correctly rejects its accepted Apple-only AD4 descriptor before execution.
No AD4 search was started and no GPU result is claimed. A Windows executable,
native AutoGrid path, supported device/driver and numerical/execution acceptance
are still required; installing a CPU software renderer cannot satisfy that gate.

A hosted runner is also not a pristine first-time consumer Windows machine.
Consumer-profile/private-browser and actual Windows GPU/driver coverage remain
separate. Known-ligand controls and other unsupported chemistry remain gated;
this test does not implement their missing native orchestration.

## Privacy and retained evidence

Only small status, package/build identity, graphics identity, check names,
exception types and code locations leave the runner. Synthetic inputs, docked
poses, interaction files, images, sessions and process logs stay runner-local.
The status-only copies are under
`validation/runs/windows-validation-20261020/`. No original study, scientific
default or working Mac installation is changed, and no change is merged to main.
Targeted local regressions for the embedded viewer, desktop, Windows guards and
Vina path carrier pass 108 tests. Superseded general CI runs were cancelled to
avoid redundant work; their cancellations are not test failures or passes.
The complete local suite also passes **671 Python cases** (expected platform/Qt
skips) and **21 shell checks**, including the four new diagnostic/redaction cases.

## Fresh installation rerun

The general CI rerun at `fcd0a48` exposed a separate failed bootstrap before any
study was created: Conda stopped while collecting GUI dependency metadata. The
uploaded dependency excerpt kept the start of a long traceback but truncated
the final cause. This record does **not** label it a transient network error or
an application regression without that evidence. Validation diagnostics now
retain bounded head/tail context (still stripping Conda's environment dump),
covered by four tests. A fresh native installer/scientific/general rerun at
`20e96a7` checks whether this is reproducible without changing package/scientific
pins, retrying a scientific job or altering existing environments.

The fresh no-prerequisite bootstrap in
[general run 39416428246](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39416428246)
**passed all ten checks**, including installation with Python/Conda hidden from
the installer PATH, unchanged persistent PATH/Python registration, installed
Qt/host startup, Unicode state/paths and exact Vina repeats. The metadata failure
did not reproduce; its original final cause remains unconfirmed. No dependency
pin or installed application code was changed to obtain that result.
All **eight** jobs in that general run subsequently passed, including full
Linux/macOS CLI and real-tool integration, native Windows/Linux/macOS safety,
Windows bootstrap/Qt-host and Vina, and the older-Mac host build (not GPU
acceptance). The separate source scientific dependency/workflow job in
[39416428076](https://github.com/thomaslane79-creator/docking-universal/actions/runs/39416428076)
also passed. These successes do not erase the separate viewer/QuickVina gaps.

Both jobs in that native scientific run subsequently **passed**. The installed
status record, five installed CLI scientific stages, and all nine real Qt/host
workflow steps report `passed`: mmCIF preparation/site review, explicit fixture
approval, protocol PDF/bundle, compound selection/workload/screen/results,
pending/completed reopening and actual process cancellation/cleanup. Preparation,
finalization and screening took 18.0, 52.0 and 72.0 seconds with tiny integration
settings, not an accuracy or performance benchmark. The combined all-capability
flag correctly remains false: interactive viewer/other engines were not enabled.

Final evidence: `validation/runs/windows-validation-20261020/20e96a7/installed/`,
`20e96a7/source-science/`, `20e96a7/bootstrap/`, `d905dce/viewer/`,
`fcd0a48/qvinaw/` and `a5ac28d/engine-preflight/` below that run root.
The final 697-file working-install/study protection audit has only its known
pre-existing stale ReportLab metadata exception; 696 files match. No main merge,
working-install change or original-study modification was performed.
