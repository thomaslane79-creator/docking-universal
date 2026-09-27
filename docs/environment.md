# Working scientific environment

`environment.yml` records the direct packages and versions used by the scientific workflow. Ubuntu and macOS are exercised by the automated test matrix, and the graphical chooser supports Zenity/GTK with Tk fallback on Ubuntu and Finder on macOS. Because compiled chemistry packages may differ across platforms, a new workstation should still run `validate integration` before production use. Native Windows support has not been established as equivalent.

Run `docking-universal runtime-inventory` for a read-only human summary or
`docking-universal runtime-inventory --json` for the versioned record intended
for installation diagnostics and the future GUI. The command observes declared
Conda environments, selected solved packages, executable paths, platform
choosers, and installation prerequisites. It does not import PyMOL, alter an
environment, or infer incompatibility from an absent or unobserved component.

Three levels of environment information are included:

- `environment.yml`: clean, readable direct scientific dependencies;
- `environment-lock-osx-arm64.txt`: a supplemental exact conda build snapshot for `osx-arm64`;
- `requirements-pip-lock.txt`: versioned Python distributions visible in that environment without machine-local build paths.
- `environments/vina.yml`: isolated current AutoDock Vina environment for comparison runs;
- `environments/qvinaw.yml`: isolated QuickVina-W 1.1 engine from the qvina 2.1.0 Conda package;
- `environments/vina-lock-osx-arm64.txt`: a supplemental exact Vina build snapshot for `osx-arm64`.

Key tested versions:

| Component | Version |
| --- | ---: |
| Python | 3.9.23 |
| fpocket | 4.2.2 |
| Open Babel | 3.1.1 |
| PLIP | 2.3.1 |
| PyMOL Open Source | 3.0.0 |
| RDKit | 2023.09.6 |
| pycairo | 1.27.0 |
| Pillow | 11.3.0 |
| Meeko | 0.7.1 |
| PDBFixer | 1.11 |

AutoDock Vina 1.2.7 and QuickVina-W 1.1 (distributed in the qvina 2.1.0 Conda package) are intentionally separated from the main compatibility matrix because their conda packages can require different compiled-library generations from parts of the preparation and visualization stack. Docking Universal invokes them from `docking-universal-vina` and `docking-universal-qvinaw`, respectively, and records the selected executable, environment, and version in the run manifest.

The packaged commands use strict Meeko conversion first. Only after rejection do they apply conservative PDBFixer repair—alternate-location resolution, recognized nonstandard-residue mapping, and missing side-chain heavy atoms, without constructing missing loops or terminal atoms—and retry strict Meeko. If a depositor-annotated disulfide causes Meeko's padding error, the workflow retries with paired `CYX` templates and records the retained bridge; it does not remove the cysteines. If Meeko specifically rejects linked deposited chemistry, a final, logged ADFRsuite compatibility fallback can be tried to retain the component. A target-matched control is required to call the resulting protocol control-validated; when no suitable control exists, the user may instead approve it explicitly for exploratory screening after reviewing the preparation and site evidence. When safe options fail, the interactive workflow offers a final explicit component-removal attempt; it is never automatic, and the decision and log are retained. Reports identify the path actually used and record the relevant software versions. Advanced backend overrides exist for compatibility testing, but preparation routes must not be treated as scientifically interchangeable without comparison.

The PyMOL route uses conda-forge's `pymol-open-source`, together with the compatible Python 3.9, PyCairo 1.27, and RDKit 2023.09 matrix. Conda resolves the lower-level Qt, Cairo, and graphics libraries. Headless PNG rendering is included in real-tool validation.

## Parallel modern GUI/PyMOL candidate

`environments/gui-next.yml` defines the Python 3.12/PyQt6 application host.

The desktop framework is PyQt6, the Python bindings for Qt 6 maintained by
Riverbank Computing. PyQt6 is a GUI dependency and is deliberately not listed
as scientific result-generating software in docking reports. See the
[PyQt introduction](https://www.riverbankcomputing.com/software/pyqt) and
[Qt 6 documentation](https://doc.qt.io/qt-6/).

The approved 2D interaction-diagram path is a local Docking Universal renderer
inspired by the visual conventions of
[PoseEdit](https://www.zbh.uni-hamburg.de/en/forschung/amd/software/poseedit.html).
It uses [Playwright](https://playwright.dev/docs/intro) and
[Node.js](https://nodejs.org/docs/latest/api/) locally; docked structures are
never submitted to PoseEdit or another web service. Reports record these three
renderer components only when that rendering path was actually used.
`environments/pymol-next.yml` defines the Python 3.12/PyMOL Open Source 3.1
companion, including PLIP 2.3.1 so PLIP's native session writer imports that
exact PyMOL runtime. They are intentionally separate because conda-forge's PyMOL 3.1
build currently selects PyQt5/Qt5; importing it in the PyQt6 host loads both Qt
generations and produces unsafe duplicate Objective-C runtime classes on macOS.
Both candidate definitions use only conda-forge packages (`nodefaults`) so a
workstation's configured default channels cannot silently change the solve.
The pair becomes supported only after GUI startup, the supervised bridge,
selection synchronization, retained-session loading, and headless report
rendering pass on macOS, Linux, and Windows.

The macOS arm64 candidate successfully generated native PLIP `.pse` sessions
for three retained QuickVina poses, reopened a session in a fresh PyMOL 3.1
process, and rendered it headlessly. A public experimental-complex panel then
covered hydrophobic contacts, hydrogen bonds, water bridges, salt bridges,
pi-stacking, pi-cation interactions, halogen bonds, and metal complexes. Every
representative session reopened and rendered with PyMOL 3.1 when PLIP was run
with `--maxthreads 1`. With PLIP's default parallelism, XML calculation
succeeded across nine public structures but native session output appeared for
only one; native visualization must therefore remain serialized.

Native PLIP writes one `.pse` per binding site rather than the consolidated
`.pml` scene used by Docking Universal. It is a viable retained-session path,
but the custom scene remains necessary for stable GUI object identity,
multi-site consolidation, report cameras, and selection synchronization.

The installed launcher routes `docking-universal desktop` through the GUI host
and resolves the PyMOL executable from the companion automatically. Advanced
installations may override the environment names with
`DOCKING_UNIVERSAL_GUI_ENV` and `DOCKING_UNIVERSAL_PYMOL_ENV`. The serialized
application host is launched with the established scientific environment's
Python (`DOCKING_UNIVERSAL_ENV`, default `docking-universal`), so receptor
preparation and analysis dependencies never need to be duplicated into the
PyQt6 process.

PLIP calculates the interaction data and writes its reports and fixed coordinates. Docking Universal's custom interaction script then writes a consolidated PML scene from that output because PLIP's native visual path was not reliable in the original setup. PyMOL is the renderer for that scene; it is not the interaction calculator.

The installed host launcher runs commands in the declared Conda environment without requiring users to activate it manually. It does not alter the parent shell's active environment. Advanced users may still supply an equivalent validated environment through Conda, containers, or a workstation module system.

`environment.yml` is the reproducible installation starting point, while platform-specific locks provide exact supplemental snapshots. Neither replaces validation on a new machine. For a formal study, archive the solved environment and platform together with the analysis inputs and outputs. See [Installation](installation.md) for setup and verification details.
