# Working scientific environment

The pipeline was developed against a specific macOS arm64 conda environment. `environment.yml` now records the minimal direct packages and versions recreated and checked in a fresh `docking-universal-test` environment on 2026-08-08.

This platform focus is intentional: the package was created in part to make the combined PyMOL, chemistry-toolkit, and docking stack reproducible on Apple-silicon M-series computers. The current reference system is an M2 Mac. Linux and Windows/WSL support should be verified independently before being advertised as equivalent.

Three levels of environment information are included:

- `environment.yml`: clean, readable direct scientific dependencies;
- `environment-lock-osx-arm64.txt`: all conda packages and exact builds from the original working platform;
- `requirements-pip-lock.txt`: versioned Python distributions visible in that environment without machine-local build paths.
- `environments/vina.yml`: isolated current AutoDock Vina environment for comparison runs;
- `environments/vina-lock-osx-arm64.txt`: exact solved Vina environment on the M2 reference platform.

Key tested versions:

| Component | Version |
| --- | ---: |
| Python | 3.9.23 |
| fpocket | 4.2.2 |
| Open Babel | 3.1.1 |
| PLIP | 2.3.1 |
| PyMOL Open Source | 3.0.0 |
| RDKit | 2023.09.6 |
| smina | 2020.12.10 |
| pycairo | 1.27.0 |
| Pillow | 11.3.0 |
| Meeko | 0.6.1 |

AutoDock Vina 1.2.7 is intentionally separated from this historical compatibility matrix. Its current macOS arm64 conda package requires a newer Python/libboost generation than smina 2020.12.10. Docking Universal can invoke it from the optional `docking-universal-vina` environment and records that environment in the run manifest.

Receptor and ligand PDBQT preparation in the original workflow used the `prepare_receptor` and `prepare_ligand` executables from **ADFRsuite 1.0**, installed separately from conda. The packaged commands now prefer Meeko automatically when its `mk_prepare_receptor.py` and `mk_prepare_ligand.py` executables are available, while `--backend adfr` and the `DOCKING_UNIVERSAL_PREP_*` variables preserve the legacy path. Meeko passed the matched raw 1HVR/XK2 test, but preparation backends must not be treated as scientifically interchangeable without comparison.

The Apple-silicon PyMOL route uses conda-forge's `pymol-open-source`, together with the compatible Python 3.9, PyCairo 1.27, and RDKit 2023.09 matrix. Conda resolves the lower-level Qt, Cairo, and graphics libraries. A headless PNG render was verified in a clean native `osx-arm64` environment.

PLIP calculates the interaction data and writes its reports and fixed coordinates. Docking Universal's custom interaction script then writes a consolidated PML scene from that output because PLIP's native visual path was not reliable in the original setup. PyMOL is the renderer for that scene; it is not the interaction calculator.

The package intentionally does not activate an environment automatically. This avoids hidden state changes and allows an equivalent validated environment to be supplied by conda, containers, or a workstation module system.

`environment.yml` is the reproducible installation starting point, while the explicit lock is the closer snapshot of the original development platform. Neither replaces validation on a new machine. For a formal study, archive the solved environment and platform together with the analysis inputs and outputs. See [Installation](installation.md) for setup and verification details.
