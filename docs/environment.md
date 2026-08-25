# Working scientific environment

`environment.yml` records the direct packages and versions used by the scientific workflow. Ubuntu and macOS are exercised by the automated test matrix, and the graphical chooser supports Zenity/GTK with Tk fallback on Ubuntu and Finder on macOS. Because compiled chemistry packages may differ across platforms, a new workstation should still run `validate integration` before production use. Native Windows support has not been established as equivalent.

Three levels of environment information are included:

- `environment.yml`: clean, readable direct scientific dependencies;
- `environment-lock-osx-arm64.txt`: a supplemental exact conda build snapshot for `osx-arm64`;
- `requirements-pip-lock.txt`: versioned Python distributions visible in that environment without machine-local build paths.
- `environments/vina.yml`: isolated current AutoDock Vina environment for comparison runs;
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

AutoDock Vina 1.2.7 is intentionally separated from the main compatibility matrix because its conda package can require a different Python/libboost generation than parts of the preparation and visualization stack. Docking Universal invokes it from `docking-universal-vina` and records that environment in the run manifest.

Receptor and ligand PDBQT preparation in the original workflow used the `prepare_receptor` and `prepare_ligand` executables from **ADFRsuite 1.0**, installed separately from conda. The packaged commands now try strict Meeko receptor conversion first. Only after rejection do they apply conservative PDBFixer repair—alternate-location resolution, recognized nonstandard-residue mapping, and missing side-chain heavy atoms, without constructing missing loops or terminal atoms—and retry strict Meeko. If a depositor-annotated disulfide causes Meeko's padding error, the workflow retries with paired `CYX` templates and records the retained bridge; it does not remove the cysteines. If Meeko specifically rejects linked deposited chemistry, a final, logged ADFRsuite fallback can be tried to retain the component; approval still requires target-matched control redocking. When safe options fail, the interactive workflow offers a final explicit component-removal attempt; it is never automatic, and the decision and log are retained. Reports identify the path actually used and record both Meeko and PDBFixer versions. `--backend adfr` and the `DOCKING_UNIVERSAL_PREP_*` variables preserve the legacy path. Preparation backends and repair paths must not be treated as scientifically interchangeable without comparison.

The PyMOL route uses conda-forge's `pymol-open-source`, together with the compatible Python 3.9, PyCairo 1.27, and RDKit 2023.09 matrix. Conda resolves the lower-level Qt, Cairo, and graphics libraries. Headless PNG rendering is included in real-tool validation.

PLIP calculates the interaction data and writes its reports and fixed coordinates. Docking Universal's custom interaction script then writes a consolidated PML scene from that output because PLIP's native visual path was not reliable in the original setup. PyMOL is the renderer for that scene; it is not the interaction calculator.

The installed host launcher runs commands in the declared Conda environment without requiring users to activate it manually. It does not alter the parent shell's active environment. Advanced users may still supply an equivalent validated environment through Conda, containers, or a workstation module system.

`environment.yml` is the reproducible installation starting point, while platform-specific locks provide exact supplemental snapshots. Neither replaces validation on a new machine. For a formal study, archive the solved environment and platform together with the analysis inputs and outputs. See [Installation](installation.md) for setup and verification details.
