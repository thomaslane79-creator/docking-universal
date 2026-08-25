# Docking Universal

**Current research-preview release: v0.6.0**

**Docking Universal is a scientific workflow orchestration, validation, analysis, visualization, and reporting system built around AutoDock Vina and established open-source structural-bioinformatics tools.**

It provides one guided, interactive command-line interface for control-guided or ligand-free docking studies while retaining configurable, independently composable commands for scripted use, complete provenance, PyMOL Open-Source visualizations, and automatic scientific PDF reports.

Every automated workflow decision is traceable through retained parameters, manifests, intermediate artifacts, and raw tool logs. A guided interface should make clear when a step rests on an assumption or requires scientific judgment, rather than allowing convenience to imply certainty. When chemistry or structural ambiguity falls outside the workflow's defined automation boundaries, Docking Universal stops, explains the issue, and requests explicit user review instead of silently guessing or modifying the molecular model. The user's selection, approval, or documented override—and the context that required it—is retained as part of the audit trail.

**AutoDock Vina performs the actual docking search and scoring.** Docking Universal does not introduce a new docking engine or scoring function; it makes the surrounding multi-tool scientific workflow reproducible, reviewable, batch-capable, and easier to run without launching each script manually.

In short: **Vina docks; Docking Universal makes the surrounding scientific workflow reproducible and reviewable.** AutoDock Vina is the only docking engine supported in this research preview. A smina comparison backend may be evaluated for a later version, but it is not part of the current installation or interface.

## Install

Docking Universal includes a repository-local installer that creates its isolated Conda environments and makes `docking-universal` available from any directory. Clone the repository, or download and extract it, then run the installer from that folder:

```bash
git clone https://github.com/thomaslane79-creator/docking-universal.git
cd docking-universal
bash install.sh
```

The installer creates or updates the main scientific environment and the separate Vina engine environment, verifies the installation, and installs a small launcher. **No manual Conda activation or environment management is required for normal use.**

Confirm that the command is available from any directory:

```bash
docking-universal check-install
docking-universal --help
```

See the [installation guide](docs/installation.md) for updating, troubleshooting, and platform details.

## Start here: guided workflows that generate reports

These are the three commands most users need. They open an interactive interface, explain each requested choice before asking for it, ask where the completed study should be saved, and generate a scientific PDF report. macOS uses Finder for graphical file and folder selection. On Ubuntu, the confirmed graphical path uses the scalable Zenity/GTK chooser, with Tk as a fallback. Headless sessions accept exact paths, which are also available for scripted use on both platforms.

Choose the task that matches what you want to do:

| What you want to do | Command | What the guided workflow does |
| --- | --- | --- |
| Start a complete new study | `docking-universal run` | Guides you through a bound-ligand control or an exploratory site-selection study, optionally docks one or multiple new compounds, and generates the complete report. |
| Create a reusable protocol and its report | `docking-universal create-protocol` | Prepares the receptor and docking region, records the scientific basis and settings, and generates a scientific PDF protocol report plus a portable `.duprotocol` bundle. |
| Dock new compounds using a Docking Universal protocol | `docking-universal screen` | Requires a previously created Docking Universal `.duprotocol`, lets you select a new SDF file or SDF directory, reuses the recorded receptor, docking box, and search settings, and generates the complete screening report. |

### Start a complete study

```bash
docking-universal run
```

Use this when starting with a protein structure and you want the workflow to guide the study from input selection through the final report. The interface identifies whether you are performing a bound-ligand control or an exploratory study and makes the evidence boundary explicit.

### Create a reusable protocol and protocol report

```bash
docking-universal create-protocol
```

**Generates a scientific PDF protocol report and a portable `.duprotocol` bundle.**

The interface offers three protocol types:

- **Control-validated:** redocks a known bound ligand and requires the pose-recovery control to pass before the protocol can authorize screening.
- **Ligand-guided exploratory:** uses a ligand in the selected structure only to define the docking region; it does not redock that ligand.
- **Site-guided exploratory:** uses fpocket cavity analysis and a user-reviewed docking box when no suitable site-defining ligand is used.

The protocol type is recorded in the report, protocol metadata, and `.duprotocol` filename. The bundle contains the prepared receptor, docking box, settings, provenance, and available supporting evidence needed for later reuse.

### Dock new compounds using a Docking Universal protocol

```bash
docking-universal screen
```

This command docks new compounds without recreating the receptor preparation, docking box, or search settings. It requires a reusable `.duprotocol` created by `docking-universal create-protocol` or a compatible earlier Docking Universal control. A `.duprotocol` is specific to Docking Universal and is not a general protocol format for use by other docking software. The interface asks you to select the protocol first and displays its target, protocol type, evidence basis, screening authority, creation date, and docking box. It then asks for one SDF, a multi-record SDF, or a directory of SDF files. Each compound receives an isolated result folder, and the final report contains the protocol provenance plus individual docking, clustering, 3D, and 2D interaction results. A batch report also begins with a summary of all compounds.

Every guided workflow retains its PDF report, machine-readable summaries, parameters, intermediate artifacts, and raw tool logs. Exploratory protocols and results remain explicitly identified as exploratory; running them does not convert them into control-validated evidence.

The current release supports **rigid-receptor docking only**: receptor coordinates remain fixed during each Vina search. Prepared ligand torsions may remain flexible, and independent ligand conformers can be searched, but receptor side-chain or backbone flexibility is not modeled. The guided runner accepts a multi-record SDF or a directory of SDF files for batch docking, with one isolated result folder per compound.

It consolidates a series of working research scripts behind one consistent command while retaining the provenance and diagnostics that made the original workflow auditable.

The project was created in part to make this compiled scientific toolchain practical and reproducible across supported Unix-like systems. Current automated testing covers macOS and Ubuntu; portability to other platforms remains a tested goal rather than an assumed guarantee.

## Why I built it: a scientist's perspective

Docking Universal began with a practical scientific question: **how should I determine where to dock?** While building it, I learned how many consequential assumptions can sit behind an apparently straightforward docking result. I wanted a practical end-to-end workflow that would not hide those choices: automated decisions remain auditable, and ambiguity prompts documented user review rather than silent guesses. [Read more about why the workflow is designed this way](docs/design-philosophy.md).

## Current capabilities and validation

**Functional research preview.** Automated installation, command routing, preparation, protocol reuse, docking, clustering, interaction analysis, visualization, and reporting checks run on current macOS and Ubuntu CI systems. The longer release validation has completed a public 1HVR/XK2 bound-ligand pose-recovery control, a held-out screen using its locked protocol, and a ligand-free 2R8N/Indinavir exploratory study, including Vina, PLIP, PyMOL, and final reports.

**Tested structural coverage.** Receptor preparation has also been evaluated against two documented 50-PDB cohorts: a general public-structure sample and a deliberately difficult covalent-linkage panel. Under the current safety policy, the general cohort produced 46/50 receptor PDBQTs; the linked-chemistry stress panel historically produced 39/50. The retained failures define known limitations involving some covalent adducts, linked glycans, metals/heme, modified backbones, and nucleic-acid complexes rather than being hidden by automatic component deletion.

These results verify that the implemented workflows and safeguards operate on representative and deliberately difficult inputs. They do not establish broad prospective docking accuracy or biological validity. See the [validation index](docs/validation.md) and complete [100-PDB receptor-preparation record](docs/receptor-preparation-validation-2026-08-21.md).

![Two end-to-end Docking Universal pathways: control-guided screening and ligand-free exploratory screening](docs/assets/end-to-end-workflows-current-capabilities.png)

## Example scientific reports

[View a complete current-style PDF report](docs/assets/docking-universal-example-report.pdf).

Docking Universal produces scenario-specific reports for:

- fresh bound-ligand control studies, with or without subsequent new-ligand docking;
- new compounds docked with an existing approved protocol;
- exploratory ligand-free cavity selection, with or without subsequent docking;
- receptor preparation and cavity analysis without ligand docking; and
- single- or multi-ligand docking studies.

The linked example shows the current report organization, figures, tables, provenance, software-version recording, and scientific limitations. It demonstrates report format and workflow outputs; its individual docking results are not general validation of docking accuracy.

## Prepare proteins and compounds for docking

Docking Universal can also be used simply to create auditable PDBQT inputs for Vina or another compatible workflow. A complete Docking Universal study is not required.

### Prepare a protein

```bash
docking-universal prepare-receptor protein.pdb
```

The guided preparation pipeline writes a prepared receptor PDBQT and diagnostic logs. It tries strict Meeko first, applies repair or compatibility fallbacks only when needed, and stops for review before any model-changing removal.

### Prepare compounds

```bash
docking-universal prepare-ligand compounds.sdf
```

This accepts a single compound or multi-record SDF and writes one prepared PDBQT per compound with retained preparation metadata.

## Other standalone tools

The commands below expose additional stages for scripting or for analyzing files that already exist. They generally produce stage-specific manifests and logs rather than the complete scientific PDF described above.

| Stage | Command | Main outputs |
| --- | --- | --- |
| Independent ensemble | `docking-universal ensemble` | pH-aware protomer/tautomer states and reproducible ETKDG/MMFF conformers |
| Pocket coordinates | `docking-universal pockets` | ranked pocket coordinates, box PDBs, and configuration files |
| Batch execution | `docking-universal dock` | per-compound PDBQT models, logs, and run manifest |
| Result collation | `docking-universal collect` | tidy CSV preserving Vina score and RMSD-bound fields |
| Pose comparison | `docking-universal compare-redock` | symmetry-aware pose RMSDs, summary, complexes, and overlay scene |
| Control evaluation | `docking-universal evaluate-control` | sampling/ranking/seed acceptance and versioned protocol gate |
| Cross-run pose clustering | `docking-universal cluster-poses` | all-pose inventory, energy-ranked clusters, three representative scenes, seed/conformer support |
| Interactions | `docking-universal interactions` | PLIP XML/text, fixed coordinates, all-in-one PyMOL PML, manifest |
| 3D output | `docking-universal render3d` | headless PyMOL PNG from an existing PML or coordinate file |
| 2D output | `docking-universal depict2d` | generic PNG/SVG molecular depictions from existing coordinate files |

## Documentation

- [Installation and troubleshooting](docs/installation.md)
- [Guided workflow and command options](docs/guided-workflow.md)
- [Workflow examples](docs/workflow-examples.md)
- [Scientific methodology and assumptions](docs/methodology.md)
- [Validation evidence and known limitations](docs/validation.md)
- [Design philosophy](docs/design-philosophy.md)
- [GitHub essentials for scientific users](docs/assets/github-essentials-for-docking-universal.pdf)

Every command also provides `--help`.

## Test

```bash
make test
```

Longer integration and release checks are described in the [validation documentation](docs/validation-status.md).

## Scope

Docking Universal currently supports rigid-receptor structural docking. It does not perform molecular dynamics, induced-fit refinement, or free-energy calculations, and its computational results require scientific interpretation.

## License and citation

MIT. See [LICENSE](LICENSE). If Docking Universal contributes to your work, cite the repository release and the underlying scientific tools used. Machine-readable citation metadata is provided in [CITATION.cff](CITATION.cff); generated reports include applicable software versions and references.
