# Installation

If GitHub is new to you, begin with the
[GitHub essentials guide for Docking Universal](assets/github-essentials-for-docking-universal.pdf).
It explains how to obtain and update the repository, record an exact software
state for reproducibility, and report problems without exposing research data.

## Recommended Conda installation

Docking Universal uses external scientific programs as composable stages. The repository's `environment.yml` contains the direct dependency set exercised on current Ubuntu and macOS GitHub runners. The 0.6.5 validation interface uses this declared environment; run integration or release validation on the intended workstation before production use because compiled scientific packages can differ across platforms.

### Beginner route: no Git required

To try the software without learning Git first:

1. Open <https://github.com/thomaslane79-creator/docking-universal>.
2. Select **Code**, then **Download ZIP**.
3. Extract the ZIP.
4. Install [Miniforge](https://github.com/conda-forge/miniforge) if Conda is not already installed.
5. Open a terminal in the extracted folder and run:

```bash
bash install.sh
docking-universal run
```

On macOS, Finder can open a terminal at a folder through **Services → New
Terminal at Folder** when that service is enabled. On common Linux desktops,
right-click the extracted folder and choose **Open in Terminal**.

### Git route

The recommended setup creates both required environments, installs the public
command, and verifies the complete pipeline:

```bash
git clone https://github.com/thomaslane79-creator/docking-universal.git
cd docking-universal
bash install.sh
docking-universal run
```

If Conda is unavailable, `install.sh` stops before changing anything and links
to the recommended Miniforge installer. Running `make setup` is equivalent to
running `./install.sh`. The installer is idempotent: missing environments are
created and existing environments receive required updates without removing
user-added packages. Experts who want strict declared-only environments can use
`conda env update -f FILE --prune` manually.

The installed `docking-universal` launcher works for every subcommand without
manual activation, including `run`, `prepare-ligand`, `prepare-receptor`,
`check-install`, and `validate`. It routes the command through the main
environment and the software invokes the selected isolated engine environment when needed.
The interactive runner asks for a parent folder before creating its named study
folder. Graphical Ubuntu sessions prefer the desktop-native Zenity/GTK chooser,
with Tk as a fallback; macOS opens Finder initially at the front Finder folder.
Headless Linux falls back to a path prompt. Supplying `--out` bypasses all
automatic folder selection.

For manual installation, create all three environments and install the public
command into the active main environment:

```bash
conda env create -f environment.yml
conda env create -f environments/vina.yml
conda env create -f environments/qvinaw.yml
conda activate docking-universal
make install-conda
docking-universal check-install --full
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

No manual activation is required for normal package use. If an engine is not already on `PATH`, Docking Universal automatically looks for `vina` in `docking-universal-vina` or `qvinaw` in `docking-universal-qvinaw`.

An installed copy can run validation from any writable directory without manual Conda activation:

```bash
mkdir -p validation-work
cd validation-work
docking-universal validate quick
docking-universal validate integration
```

Installed validation uses packaged scientific fixtures and writes a new `validation_runs/` directory below the invocation directory. It does not write inside the Conda installation. Source checkouts additionally run the repository's developer unit tests.

The installer updates declared packages but does not prune user-added packages from any environment.
To remove the complete installation later:

```bash
conda env remove -n docking-universal
conda env remove -n docking-universal-vina
conda env remove -n docking-universal-qvinaw
```

## PyMOL and compiled dependencies

The supported route is the conda-forge package `pymol-open-source`, not the official proprietary PyMOL bundle. The declared environment uses this compatible matrix:

| Component | Version |
| --- | ---: |
| Python | 3.9.23 |
| PyMOL Open Source | 3.0.0 |
| PyCairo | 1.27.0 |
| RDKit | 2023.09.6 |

Conda installs Qt, Cairo, OpenGL support libraries, and other low-level PyMOL dependencies automatically. They should not be installed one by one. Headless PyMOL rendering is included in the real-tool validation checks.

## What each package does

| Pipeline stage | Required package | Purpose |
| --- | --- | --- |
| Receptor pre-cleaning | PDBFixer | Resolve alternate locations, repair missing side-chain atoms, and standardize recognized modified residues before PDBQT conversion |
| Receptor preparation | Meeko, with conditional PDBFixer repair and a narrow ADFRsuite compatibility fallback | Validate chemistry and create docking-ready receptor PDBQT |
| Compound preparation | Open Babel plus Meeko | Split, validate, convert, optimize, and create ligand PDBQT |
| Chemical states + conformers | MolScrub 0.2.2 plus RDKit | pH-aware protomer/tautomer enumeration and independent seeded ETKDG/MMFF ensembles |
| Pocket discovery | fpocket | Detect and rank candidate cavities |
| Docking | AutoDock Vina 1.2.7 or QuickVina-W 1.1 (qvina package 2.1.0; isolated engine environments) | Perform docking search and scoring |
| Interaction analysis | PLIP | Calculate interactions and write XML/text/fixed-coordinate output |
| Interaction scene | Docking Universal | Convert PLIP output into one consolidated PyMOL `.pml` scene |
| 3D image | PyMOL Open Source | Render `.pml` or coordinate files headlessly to PNG |
| Generic 2D image | RDKit, with Open Babel fallback | Render molecule depictions to PNG or SVG |

Only the packages needed by the selected stage must be available. `environment.yml` installs preparation, analysis, and visualization tools. `environments/vina.yml` supplies AutoDock Vina and `environments/qvinaw.yml` supplies QuickVina-W without destabilizing the PyMOL and chemistry library set.

## Why the docking engines have small separate environments

The Vina-family packages can require different compiled-library generations from parts of the visualization and preparation stack. Keeping Vina and QuickVina-W in separate engine environments avoids those conflicts and prevents their differently versioned binaries from replacing one another. Both are accessed through the same Docking Universal command, and all outputs remain in the same study directory.

Run Vina explicitly:

```bash
docking-universal dock --engine vina  --receptor receptor.pdbqt --ligands prepared_ligands --config box.conf --out results_vina
```

Run QuickVina-W explicitly:

```bash
docking-universal dock --engine qvinaw --receptor receptor.pdbqt --ligands prepared_ligands --config box.conf --out results_qvinaw
```

Each output directory receives a manifest containing the selected engine, version, executable source, receptor, ligand directory, and configuration file.

All report-producing workflows use this arrangement automatically. Users do not switch environments manually. AutoDock Vina is the default; `--engine qvinaw` selects QuickVina-W when creating or running an engine-specific workflow.

After creating a reusable protocol, use its portable Docking Universal bundle for new compounds:

```bash
docking-universal screen --protocol 1HVR_XK2_control-validated_20260825.duprotocol \
  --ligands compound.sdf --out compound_run
```

Screening verifies the receptor and box recorded inside the bundle before starting. A protocol cannot be reused after either locked input changes. The public `screen` command runs the complete guided screen and writes PDF, HTML, Markdown, and JSON reports. Control-validated protocols carry passing pose-recovery evidence; exploratory protocols remain explicitly exploratory and require user authorization when reused.

## PLIP visualization design

PLIP is used for interaction calculation, not as the sole visual-output layer. The original PLIP-native visualization route was unreliable in the development environment. `docking-universal interactions` therefore runs PLIP, preserves its scientific reports and fixed coordinates, and writes a custom all-in-one PyMOL script from those outputs. `docking-universal render3d` can then render that scene without opening the PyMOL GUI.

The final PDF includes SDF-aware PLIP interaction diagrams for the three top energy-ranked cluster representatives. Docking Universal draws bond orders, aromaticity, formal charges, and stereochemistry from each retained representative SDF, then maps PLIP XML contact coordinates onto those atoms. This prevents the loss of ligand chemistry that occurs when a PDB complex is treated as the molecular-graph source. Each diagram receives a provenance manifest containing the chemistry source, interaction source, and maximum coordinate-mapping distance.

The separately licensed customized `plip_to_2D` runner remains an optional fallback. Docking Universal can detect `DOCKING_UNIVERSAL_PLIP2D_RUNNER`, a script on `PATH`, or `~/tools/plip_to_2D/plip_2D_direct_unl.py`, but it is no longer the preferred report renderer. In every path, retained PLIP `report.xml` and `report.txt` files remain the authoritative interaction records.

## Preparation backends

Docking Universal tries the filtered original receptor with strict Meeko first. PDBFixer runs only if that attempt fails. It selects one alternate location, repairs missing side-chain heavy atoms, and applies recognized nonstandard-residue mappings. It deliberately reports rather than builds missing loops or terminal atoms. Its full audit is retained as `receptor/pdbfixer_audit.json`. Set `DOCKING_UNIVERSAL_PDBFIXER=off` to disable this repair attempt, or `required` to fail when PDBFixer is unavailable.

When a depositor-annotated `SSBOND` pair triggers Meeko's disulfide-padding error, Docking Universal retries with both cysteines assigned the standard disulfide `CYX` template. The bridge is retained and listed in `receptor/disulfide_template_selection.tsv`; it is never silently removed. If all safe fallbacks then fail in an interactive terminal, Docking Universal displays the current diagnosis and offers one final, explicit option to omit unmatched components with Meeko. The prompt warns that complete protein/peptide residues may be removed, not merely missing atoms or optional hetero components. Declining leaves the receptor unchanged and stops. Accepting writes the exact TSV inventory, approval record, and raw log; removal of any standard amino-acid residue is labeled a high-severity structural modification in the original and all protocol-reuse reports. Target-matched control redocking remains required before screening.

When a retained multi-atom `LINK`ed component is present and strict Meeko rejects it, or Meeko explicitly reports unsupported linked deposited chemistry, Docking Universal can make one final ADFRsuite compatibility attempt (`DOCKING_UNIVERSAL_ADFR_FALLBACK=1`, the default). Coordination waters and unsupported single-atom ions are not treated as covalent components solely because they appear in a `LINK` record. This narrow fallback is intended for linked small-molecule adducts, not glycans, DNA/RNA, heme, metals, or arbitrary cofactors. It retains `receptor/receptor_adfr_fallback.log`, records the backend switch, and requires a successful target-matched control redocking before approval. The preparer discovers `~/ADFRsuite-1.0/bin/prepare_receptor` when installed in that conventional location; otherwise set `DOCKING_UNIVERSAL_ADFR_FALLBACK_BIN` to its executable path. Set `DOCKING_UNIVERSAL_ADFR_FALLBACK=0` to disable it.

If the remaining error is specifically an ambiguous histidine tautomer, guided preparation explains HIE, HID, and HIP and asks which template to use before retrying. The choice is recorded. For unattended execution, set an exact Meeko assignment such as `MEEKO_SET_TEMPLATE=A:36=HIE`; no histidine state is chosen silently.

If preparation still stops, both the interactive terminal and `receptor_failure_diagnosis.txt` report a likely failure category, why it cannot be resolved safely, and the next review step. Recognized categories include unsupported non-standard amino acids, DNA/RNA or mixed protein–nucleic-acid template conflicts, heme/cofactor templates, linked glycans or other covalent fragments, alternate-location conflicts, incomplete residues, and histidine ambiguity. Detected residue identifiers are included where the PDB and backend logs expose them. This explanation supplements—not replaces—the retained Meeko and PDBFixer logs.

An earlier installed-copy problem prevented the PDBFixer helper from being found at its packaged location; that path-resolution defect is fixed. A later Meeko rejection does not mean PDBFixer failed to run: PDBFixer may successfully repair ordinary missing atoms or alternate locations while leaving specialized cofactors, covalent linkages, or unsupported templates unresolved.

Meeko 0.7.1 is the primary preparation backend in the declared environment. Backend changes can affect atom typing, protonation, charge assignment, and therefore scientific results; Docking Universal records the backend and version used. The ADFRsuite route is a narrow compatibility fallback and must not be assumed scientifically equivalent to Meeko without target-specific review and control evidence.

## Verification performed

The following checks passed in the declared scientific environment:

- all required executables were installed and discoverable;
- PyMOL imported and rendered an existing PDB to a valid PNG in headless mode;
- RDKit rendered an existing ligand SDF to a valid PNG;
- PLIP analyzed an existing protein–ligand complex;
- the custom interaction stage wrote a fixed PDB, consolidated PML scene, and run manifest.
- matched 1HVR/XK2 raw inputs passed strict receptor preparation, ligand preparation, ligand-centered preparation, and ligand-free pocket recovery;
- Vina 1.2.7 completed smoke runs on the prepared inputs;
- QuickVina-W 1.1 from the qvina 2.1.0 package completed the same integration smoke route with engine-compatible ligand preparation;
- the PLIP interaction scene and ligand-centered pocket scene rendered to visually inspected nonblank PNGs.

These are software and representative-data checks. They are not a claim that every receptor, ligand chemistry, operating system, or scientific use case has been validated.

See [Raw-input validation](validation.md) for the matched public 1HVR/XK2 test and the issues it exposed.
