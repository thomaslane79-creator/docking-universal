# Portable Mac viewer and optional GPU installation

This closes two omissions in the original five-environment installer. The
scientific engine, sampling settings, reports and user approval rules are not
changed. Vina remains the default.

## User installation

Use `bash install.sh` for the usual installation. On Apple Silicon with macOS
15 or later, it also installs the pinned **embedded PyMOL** into the Python 3.12
Qt6 GUI environment. The separate PyMOL companion is retained. No Qt5 bindings
are added to the Qt6 environment.

For the optional experimental Apple GPU engine, use:

```bash
bash install.sh --with-gpu
```

The exact accepted GPU binary requires **Apple Silicon and macOS 26.2 or later**,
plus an available Apple OpenCL GPU. The installer rejects other systems before
changing environments when this option is requested. Its device check does not
dock a ligand, calibrate a target or establish cross-machine reproducibility.
Other platforms retain their existing CPU/companion paths; Windows/Linux GPU
support still requires separate native validation.

GPU binaries, AutoGrid, source archives, licenses and a checksum manifest are
installed below the scientific environment's `share/docking-universal/adgpu/`.
The descriptor is `runtime.json` in that folder. The GUI launcher passes this
installation's descriptor to its separate Python interpreter. The command-line
engine finds it in its own prefix. Nothing is written to the user's old
`~/.config/docking-universal/adgpu.json`.

An explicit `DOCKING_UNIVERSAL_ADGPU_CONFIG` remains authoritative: an absent
override fails closed instead of selecting another installation. Existing custom
desktop registrations are preserved. The GPU binary's accepted hash is still
mandatory, and the packaged AutoGrid hash is checked when the descriptor is
opened. There is no silent Vina fallback.

The bundled files need no runtime download. The initial Conda, npm and P2Rank
installation still needs internet. Online PDB evidence is separately optional;
local visualization and docking do not upload structures. See the
[AD4 learning guide](ad4-gpu-guide.md) for scoring and scientific limitations.

## Provenance and small runtime bundle

`dependencies/runtime/macos-arm64/manifest.json` records file sizes, SHA-256,
upstream commits and changes. The bundle is about 53 MiB, including complete
corresponding source archives and licenses—not the multi-gigabyte Conda
environments. Each asset is below GitHub's ordinary 100 MiB per-file limit;
no Git LFS or hosted dependency environment is needed.

- PyMOL: upstream commit `5e8bfca5a7f5dc4d5e7f84fa1d15af707cc86e69`,
  Python 3.12, version 3.2.0a0. Only absolute Mach-O runtime-library search paths
  in the pinned prototype wheel are replaced by paths relative to the extension.
  Ad-hoc signatures and wheel RECORD checksums are regenerated. The scientific
  source is unchanged. This removes the dependency on the original build folder.
- AutoDock-GPU: upstream v1.6 commit
  `e63e6f6280ebfad18caa3e8f48afdc269e79e063`. The **unchanged accepted**
  128-work-item binary has SHA-256
  `062b5816f8342fa4c2150d65852e83f52940fe2f2cb603710e27527b33a9d02a`.
  Local source changes are the shared-force synchronization barrier and the
  one-work-item Apple configuration guard, documented in the README and
  `validation/patches/autodock-gpu-v1.6-local.patch`. The archive includes the
  corresponding patched sources and generated kernel header, not experimental
  diagnostic builds. Redistribution retains GPL/LGPL notices and source.
- AutoGrid: unmodified version 4.2.8, commit
  `18879446506d1750510e26f8a5344b159533dbae`, rebuilt serially with double
  precision and the 8 Å nonbonded cutoff. It is not an upgrade to 4.2.9.
  `validation/build_autogrid_428.py` records the build recipe. The complete
  source archive and GPL notice accompany the binary.

Maintainer tools: `validation/package_mac_runtimes.py` builds the bundle from
explicit pinned inputs without modifying installed environments. PyMOL's source
build uses `pip wheel --no-deps --no-build-isolation` with `libxml=no`,
`use-msgpackc=no`, `vmd-plugins=no`, CMake 4.4.3 and Apple Clang, with GLEW 2.3,
libpng 1.6 and FreeType 2.14 in a Python 3.12 prefix. The GPU archive retains its
upstream Makefile; the accepted profile is OpenCL GPU, `NUMWI=128`, without
OpenMP. Rebuilding does not automatically grant a new executable the accepted
hash or support status.

## Acceptance record

Completed **2026-10-18** on this Apple M2 Max, macOS 27.0.1. This is installation
validation on the current Mac, not new target calibration or a clean OS/VM test.
Native Windows/Linux and older-supported-macOS checks remain separate.

- A new Miniforge prefix, new package cache and five fresh environments passed
  the public `install.sh --with-gpu` in **174.3 seconds overall** (including
  bootstrap and subsequent checks). No existing application environment was
  cloned. Version, full installation check, smoke validation and desktop help
  passed. GPU discovery resolved the **new prefix**, not the working HOME config.
- All **15 native viewer checks** passed: real Qt6/OpenGL rendering, surface and
  box, same-engine full PyMOL detachment, command area, return to workspace,
  preserved camera and ray-traced PNG export. Loaded libraries came from the new
  prefix/system; no prototype, working Conda or Qt5 library was used. The installed
  complete desktop also opened with isolated preferences and a new empty study.
- Two same-seed native AD4 adapter runs using **nonbiological butane/methanol
  fragments** passed, retaining 20 winners each with correct AD4/kcal/mol labels.
  Normalized output files were byte-identical. Both engine and AutoGrid came
  from the fresh prefix. This checks installation functionality only.
- AutoGrid's printed numerical payload matched the working 4.2.8 reference
  exactly for eight small upstream-test maps and eight larger retained local
  maps (357,911 values each). Reused local inputs were not changed or uploaded.
- **37 packaging/AD4 tests**, **114 GUI/viewer/workflow tests**, and the installer
  and installed-copy shell suites passed. Corrupted assets, unsupported OS,
  prefix/explicit-override discovery and tampered runtime binaries are covered.
- **697 protected files** in the working environments, launcher, user config
  and study states remained hash-identical. No biological docking or scientific
  approval was performed.

Two initial synthetic GPU-test fixtures were rejected by AutoGrid before any
search: an all-zero-charge dummy receptor, then a dummy lacking polar hydrogen.
Those failed test records are retained. A properly prepared molecular fragment
replaced the invalid fixture; **no engine code or search setting was changed**
to make it pass. The native viewer also emitted the previously observed macOS
`GLD_TEXTURE_INDEX_2D` diagnostic once; rendering, detach/return and ray export
still passed. This packaging change does not claim to fix that driver warning.

Local evidence (ignored by Git because outputs stay local):

- `validation/runs/clean-install-native-20261018/summary.json`
- `validation/runs/clean-install-native-20261018/native-acceptance-molecular-fixture.json`
- `validation/runs/clean-install-native-20261018/native-viewer/summary.json`
- `validation/runs/clean-install-native-20261018/native-desktop/workspace.png`
- `validation/runs/clean-install-native-20261018/native-gpu-molecular-fixture/summary.json`
- `validation/runs/mac-runtime-packaging-20261017/autogrid-parity/summary.json`
- `validation/runs/mac-runtime-packaging-20261017/autogrid-parity-retained/summary.json`

Maintainer reproduction: `validation/clean_install_mac_runtime.py --out NEW_DIR`
creates the isolated installation (specify a usable `--git` if needed).
`validation/finish_clean_mac_runtime.py --installation NEW_DIR` runs its viewer
and corrected synthetic GPU checks. The separate
`validation/native_mac_runtime_desktop.py` launches the installed workspace with
isolated preferences. Each attempt requires a new output directory; failures
are not silently overwritten or restarted.
