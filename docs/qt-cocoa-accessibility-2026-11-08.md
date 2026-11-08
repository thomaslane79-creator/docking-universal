# Native Mac table accessibility repair, 2026-11-08

The installed Mac GUI now loads an app-owned Cocoa platform plugin built from
its exact Qt 6.11.2 source plus the merged upstream accessibility fix. Repeated
native pocket/evidence selections, multi-selection, quitting and reopening no
longer reproduced the previously observed selected-table crash. This bounded
acceptance is separate from the remaining scientific workflow walkthrough.

## Cause and upstream repair

The reproduced stack entered `QMacAccessibilityElement` selected-child queries.
Qt's [QTBUG-149612](https://qt-project.atlassian.net/browse/QTBUG-149612) records
this failure family. The merged [upstream change b74d6cb](https://github.com/qt/qtbase/commit/b74d6cb3c5e8418602494ae549b60839d88ef858)
stops native accessibility-element teardown from deleting an interface owned
by Qt. We applied its two Cocoa source changes to the installed Qt version.
Accessibility remains enabled. No table-selection workaround hides the fault.

An older isolated Qt 6.10.2 runtime also crashed during the preceding investigation.
Its failure does not establish that every older or newer Qt release is affected.
This repair supports the reproduced Apple-Silicon Qt 6.11.2 profile only.
Windows and Linux keep their existing platform plugins.

## Programs and their roles

| Program or source | Why it is used | Input and output | Limits |
| --- | --- | --- | --- |
| Qt / PyQt6 | Draw and control the desktop windows; PyQt6 connects Python to Qt | Application widgets and native events become visible controls | GUI stability does not establish scientific validity |
| Cocoa plugin | Connect Qt windows, input and accessibility to macOS | Qt requests become native Mac behavior | Must match the exact Qt private interfaces used to build it |
| CMake 4.4.4 | Configure the component against the installed Qt development headers | Source, SDK and build settings become Ninja compiler instructions | Does not itself compile or run docking |
| Ninja 1.13.2 | Execute the compiler instructions and incremental rebuilds | Build instructions become compiled objects and a linked plugin | Its wheel reports the additional `git.kitware.jobserver-pipe-1` version suffix |
| AppleClang / Command Line Tools | Compile and link Objective-C++ and C++ against Apple's SDK | Source files become `libqcocoa.dylib` | The tested local SDK is 27.2; Qt's SDK compatibility warnings remain enabled |
| Vulkan-Headers | Satisfy the graphics declarations referenced by Qt's private headers | Header declarations are read during compilation | No Vulkan engine, new renderer or scientific method is installed |
| `codesign --verify` | Verify the linked plugin's local signature structure | The built library yields a signature verification result | Local linker signing is not Apple notarization |
| Conda / Miniforge | Keep GUI and scientific dependencies in separate environments | Environment specifications become installed runtimes | An activated environment alone does not guarantee every external tool is on PATH |

A **backport** applies an upstream repair to an older installed version while
keeping the rest of that version. Here it avoids replacing the scientific
Python environment or trying another unverified Qt release.

## Packaging and verification

`qt_cocoa_runtime.py` owns the complete build/registration operation; small
commands are not split into separate Python scripts. The source specification
pins the Qt and Vulkan source commits, archive SHA-256 values, upstream patch
SHA-256 and exact pre/post hashes for both changed source files. Cached build
sources are checked against the downloaded archive. Only the two expected
upstream changes are permitted.

The build uses the existing Conda development/private headers and libraries.
It skips only Qt's full-Xcode version probe because Command Line Tools supply
the required compiler and SDK. Qt's SDK minimum/maximum checks remain enabled.
The output is checked with `codesign`, then registered under:

```
<GUI prefix>/share/docking-universal/qt-cocoa-accessibility/
```

The registration stores the plugin checksum and the exact Qt Core/Gui library
checksums. Startup verifies all three, version, architecture, source identity
and prefix before choosing the app-owned plugin. A mismatch stops with rebuild
guidance. The original Conda plugin/libraries are not replaced. Previous managed
registrations are retained in uniquely named backup directories.

`install.sh` builds this repair for the existing embedded Apple-Silicon profile.
The generic GUI environment now pins PyQt6 6.11.0 and Qt 6.11.2; native Windows
has its separate environment specification. A new installation needs network
access for pinned source/build packages and Apple's Command Line Tools. Build
logs remain in `share/docking-universal/qt-cocoa-build`. Failed steps name their
log file. Re-running the installer reuses verified source/build caches.

Local build output SHA-256:
`0425df5bcac79548a22685ea3700aa9a8f1834c69d270cef056ca3cddbaafef4`.
Source identities/checksums are in
`libexec/docking_universal/data/qt-cocoa-accessibility.json`; this hash is a
local result, not a promise of bit-identical output with another SDK/compiler.

## Actual native observations

Public 1N6O was reopened in an isolated state/preferences root. The existing
reviewed Mg omission and exact reference-role separation were retained. The
validation copy has its own future control output directory. No live Cox-2
study or original structure was changed.

1. The staged repair loaded with the original Qt Core/Gui libraries.
2. P1/B1 selections updated the evidence panel and retained the Mg A:201 warning.
3. Ten alternating keyboard selections, evidence-row selection and simultaneous
   P1/B1 selection completed with native accessibility reads and screenshots.
4. Embedded PyMOL displayed the receptor/selected box and input GNP ligand.
5. Quitting and reopening retained revision 12 and the unapproved decision.
6. The same app then reopened through the installed loader, without a validation
   plugin-path override. Qt debug output confirmed the registered plugin loaded.
7. Actual region approval reached the separate explicit known-ligand-control
   start action. The first test launcher omitted Conda from PATH; ligand
   preparation completed, docking stopped with its actual missing-runtime error,
   and no control approval was granted. That failed state/output is preserved.
8. A fresh copy with Conda on PATH started real Vina redocking. Its later outcome
   belongs in the chronological workflow record; this document does not claim
   full workflow acceptance from a running calculation.

Ignored local receipts/logs: `validation/local/qt-cocoa-a11y-20261107` and
`validation/runs/qt-cocoa-acceptance-20261108`. Installed loader backups:
`local-fix-backups/qt-cocoa-runtime-20261108`.

## Automated checks

Six runtime contracts cover exact identity, platform isolation, stale/damaged
libraries/plugins, malformed registration, source/cache checks and retained
failure diagnostics. Together with launcher/runtime-layout checks, 14 checks
pass in the GUI environment. Installed-copy and bootstrap shell checks pass;
the latter verifies Apple-Silicon builder routing with mocked installations.
These do not substitute for the native observations above or a fresh native
Windows installation. Runtime contracts are included in cross-platform CI.

A second clean build extracted only the declared Cocoa/license/Vulkan inputs,
used a build directory containing a space, and passed compilation and signature
verification. Its output was retained separately, without replacing the plugin
undergoing native acceptance. The preceding branch's general CI and both native
Windows jobs also passed; new CI runs remain a separate check for this change.
