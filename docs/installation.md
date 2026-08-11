# Installation

## Recommended Conda installation

Docking Universal uses external scientific programs as composable stages. The repository's `environment.yml` contains the smallest direct dependency set verified together on macOS arm64.

```bash
git clone YOUR_REPOSITORY_URL
cd Docking_Universal
conda env create -f environment.yml
conda activate docking-universal
./bin/docking-universal doctor
make test
```

The main environment includes the historically compatible smina executable. smina is a fork of AutoDock Vina with additional scoring and minimization features, not a wholly separate docking framework. To compare the same inputs with current AutoDock Vina, create its optional environment:

```bash
conda env create -f environments/vina.yml
```

No manual activation is required for normal package use. If `vina` is not already on `PATH`, Docking Universal automatically looks for it in `docking-universal-vina`.

The environment does not modify or replace an existing environment. To remove it later:

```bash
conda env remove -n docking-universal
```

## Apple silicon and PyMOL

Docking Universal was created partly to make this multi-program workflow reproducible on Apple-silicon M-series systems, where compiled chemistry, docking, and graphics packages do not always share compatible release schedules. The current reference machine is an M2 Mac using native `osx-arm64` Conda builds.

The tested M1/M2/M3 route is the conda-forge package `pymol-open-source`, not the official proprietary PyMOL bundle. A newer 3.1.0 build was present during development, but the working scientific environment settled on this compatible matrix:

| Component | Version |
| --- | ---: |
| Python | 3.9.23 |
| PyMOL Open Source | 3.0.0 |
| PyCairo | 1.27.0 |
| RDKit | 2023.09.6 |
| smina | 2020.12.10 |

Conda installs Qt, Cairo, OpenGL support libraries, and other low-level PyMOL dependencies automatically. They should not be installed one by one. This matrix was solved in a new native `osx-arm64` environment and produced a headless 640 × 480 PNG on 2026-08-08.

## What each package does

| Pipeline stage | Required package | Purpose |
| --- | --- | --- |
| Receptor preparation | ADFRsuite `prepare_receptor` (legacy) or Meeko | Create docking-ready receptor PDBQT |
| Compound preparation | Open Babel plus ADFRsuite `prepare_ligand` (legacy) or Meeko | Split, convert, optimize, and create ligand PDBQT |
| Chemical states + conformers | MolScrub 0.2.2 plus RDKit | pH-aware protomer/tautomer enumeration and independent seeded ETKDG/MMFF ensembles |
| Pocket discovery | fpocket | Detect and rank candidate cavities |
| Docking | smina (main environment) and AutoDock Vina (optional environment) | Run separate comparison batches with the selected engine |
| Interaction analysis | PLIP | Calculate interactions and write XML/text/fixed-coordinate output |
| Interaction scene | Docking Universal | Convert PLIP output into one consolidated PyMOL `.pml` scene |
| 3D image | PyMOL Open Source | Render `.pml` or coordinate files headlessly to PNG |
| Generic 2D image | RDKit, with Open Babel fallback | Render molecule depictions to PNG or SVG |

Only the packages needed by the selected stage must be available. `environment.yml` installs the full preparation, analysis, visualization, and smina toolchain. `environments/vina.yml` adds current Vina without destabilizing the historically compatible smina/PyMOL library set.

## Why Vina has a small separate environment

On current macOS arm64 conda-forge builds, Vina 1.2.7 requires a newer Python/libboost generation than smina 2020.12.10. Keeping Vina isolated is a standard scientific-software solution to that compiled-library conflict. It is still accessed through the same Docking Universal command, and all outputs remain in the same study directory.

Run both engines explicitly:

```bash
docking-universal dock --engine smina --receptor receptor.pdbqt --ligands prepared_ligands --config box.conf --out results_smina
docking-universal dock --engine vina  --receptor receptor.pdbqt --ligands prepared_ligands --config box.conf --out results_vina
```

Each output directory receives a manifest containing the selected engine, version, executable source, receptor, ligand directory, and configuration file.

The `control` command uses this same arrangement automatically. Vina is the default because its supported Meeko preparation can sample flexible macrocycles. `--engine smina` uses an independently generated rigid-macrocycle ensemble, and `--engine both` calibrates the engines separately. Users do not switch environments manually.

After a five-seed control passes, use its target-locked record for an unknown compound:

```bash
docking-universal screen --protocol CONTROL/04_redocking/vina/broader/protocol.json \
  --ligand compound.sdf --out compound_run
```

Screening verifies the recorded receptor and box hashes before starting. A control record cannot be reused after either input changes.

## PLIP visualization design

PLIP is used for interaction calculation, not as the sole visual-output layer. The original PLIP-native visualization route was unreliable in the development environment. `docking-universal interactions` therefore runs PLIP, preserves its scientific reports and fixed coordinates, and writes a custom all-in-one PyMOL script from those outputs. `docking-universal render3d` can then render that scene without opening the PyMOL GUI.

The final PDF includes SDF-aware PLIP interaction diagrams for the three top energy-ranked cluster representatives. Docking Universal draws bond orders, aromaticity, formal charges, and stereochemistry from each retained representative SDF, then maps PLIP XML contact coordinates onto those atoms. This prevents the loss of ligand chemistry that occurs when a PDB complex is treated as the molecular-graph source. Each diagram receives a provenance manifest containing the chemistry source, interaction source, and maximum coordinate-mapping distance.

The separately licensed customized `plip_to_2D` runner remains an optional fallback. Docking Universal can detect `DOCKING_UNIVERSAL_PLIP2D_RUNNER`, a script on `PATH`, or `~/tools/plip_to_2D/plip_2D_direct_unl.py`, but it is no longer the preferred report renderer. In every path, retained PLIP `report.xml` and `report.txt` files remain the authoritative interaction records.

## Preparation backends

The original validated receptor and ligand PDBQT outputs used ADFRsuite 1.0, installed separately. Meeko 0.6.1 is included in the clean Conda environment because it is the portable preparation tool maintained with AutoDock Vina. Preparation backend changes can affect atom typing, protonation, charge assignment, and therefore scientific results; the backend and version should always be recorded.

Meeko now passes an end-to-end raw 1HVR/XK2 test, including strict handling of RCSB `MODRES` chemical-component metadata. That establishes a verified portable path for this case; it does not prove Meeko and ADFRsuite produce scientifically equivalent structures. Use ADFRsuite to reproduce original preparation behavior and record the selected backend for every study.

## Verification performed

The following checks passed from the new `docking-universal-test` environment on macOS arm64:

- all required executables were installed and discoverable;
- PyMOL imported and rendered an existing PDB to a valid PNG in headless mode;
- RDKit rendered an existing ligand SDF to a valid PNG;
- PLIP analyzed an existing protein–ligand complex;
- the custom interaction stage wrote a fixed PDB, consolidated PML scene, and run manifest.
- matched 1HVR/XK2 raw inputs passed strict receptor preparation, ligand preparation, ligand-centered preparation, and ligand-free pocket recovery;
- Vina 1.2.7 and smina 2020.12.10 both completed smoke runs on the same prepared inputs;
- the PLIP interaction scene and ligand-centered pocket scene rendered to visually inspected nonblank PNGs.

These are software and representative-data checks. They are not a claim that every receptor, ligand chemistry, operating system, or scientific use case has been validated.

See [Raw-input validation](validation.md) for the matched public 1HVR/XK2 test and the issues it exposed.
