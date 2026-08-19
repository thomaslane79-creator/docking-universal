# Installation

If GitHub is new to you, begin with the
[GitHub essentials guide for Docking Universal](assets/github-essentials-for-docking-universal.pdf).
It explains how to obtain and update the repository, record an exact software
state for reproducibility, and report problems without exposing research data.

## Recommended Conda installation

Docking Universal uses external scientific programs as composable stages. The repository's `environment.yml` contains the smallest direct dependency set verified together on macOS arm64.

```bash
git clone YOUR_REPOSITORY_URL
cd Docking_Universal
conda env create -f environment.yml
conda activate docking-universal
./bin/docking-universal check-install
make test
```

Install the public command into the active environment:

```bash
conda activate docking-universal
make install-conda
which docking-universal
docking-universal --help
```

`make install-conda` uses the active `CONDA_PREFIX`; it fails rather than guessing when no Conda environment is active. The installed command and its private helpers remain relocatable within that environment.

`make install-conda` installs the Docking Universal files; it does not independently install or change scientific packages. A new environment created from `environment.yml` receives PDBFixer 1.11 and its OpenMM dependency automatically. To update an existing Docking Universal environment after pulling this release, run:

```bash
conda activate docking-universal
conda env update -f environment.yml --prune
make install-conda
docking-universal check-install
```

The final check reports whether PDBFixer is available. The strict Meeko path remains first, but PDBFixer must be installed so the documented automatic repair path is available when a receptor needs it.

AutoDock Vina is kept in a small engine environment so its compiled dependencies do not destabilize the preparation, analysis, and PyMOL stack:

```bash
conda env create -f environments/vina.yml
```

No manual activation is required for normal package use. If `vina` is not already on `PATH`, Docking Universal automatically looks for it in `docking-universal-vina`.

An installed copy can run validation from any writable directory:

```bash
conda activate docking-universal
mkdir -p validation-work
cd validation-work
docking-universal validate quick
docking-universal validate integration
```

Installed validation uses packaged scientific fixtures and writes a new `validation_runs/` directory below the invocation directory. It does not write inside the Conda installation. Source checkouts additionally run the repository's developer unit tests.

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

Conda installs Qt, Cairo, OpenGL support libraries, and other low-level PyMOL dependencies automatically. They should not be installed one by one. This matrix was solved in a new native `osx-arm64` environment and produced a headless 640 × 480 PNG on 2026-08-08.

## What each package does

| Pipeline stage | Required package | Purpose |
| --- | --- | --- |
| Receptor pre-cleaning | PDBFixer | Resolve alternate locations, repair missing side-chain atoms, and standardize recognized modified residues before PDBQT conversion |
| Receptor preparation | ADFRsuite `prepare_receptor` (legacy) or Meeko | Validate chemistry and create docking-ready receptor PDBQT |
| Compound preparation | Open Babel plus ADFRsuite `prepare_ligand` (legacy) or Meeko | Split, convert, optimize, and create ligand PDBQT |
| Chemical states + conformers | MolScrub 0.2.2 plus RDKit | pH-aware protomer/tautomer enumeration and independent seeded ETKDG/MMFF ensembles |
| Pocket discovery | fpocket | Detect and rank candidate cavities |
| Docking | AutoDock Vina 1.2.7 (engine environment) | Perform docking search and scoring |
| Interaction analysis | PLIP | Calculate interactions and write XML/text/fixed-coordinate output |
| Interaction scene | Docking Universal | Convert PLIP output into one consolidated PyMOL `.pml` scene |
| 3D image | PyMOL Open Source | Render `.pml` or coordinate files headlessly to PNG |
| Generic 2D image | RDKit, with Open Babel fallback | Render molecule depictions to PNG or SVG |

Only the packages needed by the selected stage must be available. `environment.yml` installs preparation, analysis, and visualization tools. `environments/vina.yml` supplies AutoDock Vina without destabilizing the PyMOL and chemistry library set.

## Why Vina has a small separate environment

On current macOS arm64 conda-forge builds, Vina 1.2.7 may require a different Python/libboost generation than parts of the visualization and preparation stack. Keeping Vina isolated is a standard scientific-software solution to that compiled-library conflict. It is still accessed through the same Docking Universal command, and all outputs remain in the same study directory.

Run Vina explicitly:

```bash
docking-universal dock --engine vina  --receptor receptor.pdbqt --ligands prepared_ligands --config box.conf --out results_vina
```

Each output directory receives a manifest containing the selected engine, version, executable source, receptor, ligand directory, and configuration file.

The `control` command uses this arrangement automatically. Users do not switch environments manually. Vina is the only docking engine supported in this research preview; a smina comparison backend may be evaluated in a future version.

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

Docking Universal tries the filtered original receptor with strict Meeko first. PDBFixer runs only if that attempt fails. It selects one alternate location, repairs missing side-chain heavy atoms, and applies recognized nonstandard-residue mappings. It deliberately reports rather than builds missing loops or terminal atoms. Its full audit is retained as `receptor/pdbfixer_audit.json`. Set `DOCKING_UNIVERSAL_PDBFIXER=off` to disable this repair attempt, or `required` to fail when PDBFixer is unavailable.

If strict Meeko also rejects the PDBFixer result, Docking Universal makes one documented quick retry against the filtered original using Meeko's batch cleanup. This may omit unmatched residues and therefore requires review, especially near a docking pocket. Disable this retry with `DOCKING_UNIVERSAL_AUTO_RECEPTOR_RETRY=0`.

If the remaining error is specifically an ambiguous histidine tautomer, guided preparation explains HIE, HID, and HIP and asks which template to use before retrying. The choice is recorded. For unattended execution, set an exact Meeko assignment such as `MEEKO_SET_TEMPLATE=A:36=HIE`; no histidine state is chosen silently.

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
- Vina 1.2.7 completed smoke runs on the prepared inputs;
- the PLIP interaction scene and ligand-centered pocket scene rendered to visually inspected nonblank PNGs.

These are software and representative-data checks. They are not a claim that every receptor, ligand chemistry, operating system, or scientific use case has been validated.

See [Raw-input validation](validation.md) for the matched public 1HVR/XK2 test and the issues it exposed.
