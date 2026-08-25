# Docking Universal

**v0.6.3 · Research preview**

Docking Universal provides fully guided, interactive docking workflows on Ubuntu and macOS, from selecting inputs through generating scientific PDF reports. It uses AutoDock Vina and established open-source tools for receptor and ligand preparation, site selection, docking, analysis, and visualization.

**Vina performs the docking; Docking Universal manages and documents the surrounding workflow.**

## Why I built it: a scientist's perspective

Docking Universal began with a practical question: **how should I determine where to dock?** While building it, I learned how many consequential assumptions can sit behind an apparently straightforward result. I wanted a practical workflow that would make those choices reviewable rather than hide them. [Read more about the design philosophy](docs/design-philosophy.md).

## Install

Clone the repository, or download and extract it, then run:

```bash
git clone https://github.com/thomaslane79-creator/docking-universal.git
cd docking-universal
bash install.sh
```

The installer creates the required isolated Conda environments and makes `docking-universal` available from any directory. Normal use does not require manual Conda activation or environment management.

```bash
docking-universal check-install
docking-universal --help
```

See the [installation guide](docs/installation.md) for updating, troubleshooting, and platform details.

## The three main workflows

These are the three commands most users need. Each launches an interactive interface on Ubuntu and macOS (Zenity/GTK on Ubuntu, with Tk as a fallback; Finder on macOS), explains requested choices, asks where to save the study, and generates a scientific PDF report. Exact paths are also accepted for headless or scripted use.

| What you want to do | Command | What you get |
| --- | --- | --- |
| Start a complete new study | `docking-universal run` | A complete control-validated or exploratory study, optionally including one or multiple new compounds, with a scientific PDF report and retained supporting files. |
| Create a reusable Docking Universal protocol | `docking-universal create-protocol` | A prepared receptor and docking region, a scientific protocol report, and a reusable `.duprotocol` bundle. |
| Dock new compounds with a saved protocol | `docking-universal screen` | A complete screening report plus individual docking, clustering, 3D, and 2D interaction results for every compound. |

### Docking Universal protocol types

| Protocol type | How the docking region is established | Evidence status |
| --- | --- | --- |
| **Control-validated** | A known bound ligand is redocked and must pass pose-recovery criteria. | Supports screening with target-specific control evidence. |
| **Ligand-guided exploratory** | A ligand in the selected structure defines the region but is not redocked. | Explicitly exploratory. |
| **Site-guided exploratory** | fpocket cavity analysis and a user-reviewed box define the region. | Explicitly exploratory. |

A `.duprotocol` contains the prepared receptor, docking box, settings, provenance, and supporting evidence. It can be saved, shared, and reused by another Docking Universal installation, but it is not a general protocol format for other docking software. Exploratory use remains identified as exploratory and requires explicit user authorization.

Every guided workflow retains its report, machine-readable summaries, parameters, intermediate artifacts, and raw tool logs. Single-record SDFs, multi-record SDFs, and directories of SDF files are supported for compound screening.

![Two end-to-end Docking Universal pathways: control-guided screening and ligand-free exploratory screening](docs/assets/end-to-end-workflows-current-capabilities.png)

## Standalone tools for other systems

Prepared receptor and ligand PDBQT files are separate from Docking Universal `.duprotocol` bundles and can be used with Vina or other compatible docking software. A complete Docking Universal study is not required.

| What you want to prepare | Command | Output |
| --- | --- | --- |
| Protein receptor | `docking-universal prepare-receptor protein.pdb` | Prepared receptor PDBQT and diagnostic logs. Model-changing removal requires review. |
| One or more compounds | `docking-universal prepare-ligand compounds.sdf` | One prepared ligand PDBQT per compound with preparation metadata. |

Additional component commands can also be used independently in compatible workflows:

| Task | Command | Output |
| --- | --- | --- |
| Find candidate pockets | `docking-universal pockets` | Ranked pocket coordinates, box structures, and Vina configuration files. |
| Dock prepared inputs | `docking-universal dock` | Per-compound Vina poses, logs, and a run manifest. |
| Collect docking scores | `docking-universal collect` | Tidy CSV results. |
| Compare a docked pose with a reference | `docking-universal compare-redock` | Symmetry-aware RMSD results, complexes, and an overlay scene. |
| Analyze interactions | `docking-universal interactions` | PLIP interaction records and a PyMOL scene. |
| Render existing molecular files | `docking-universal render3d` / `docking-universal depict2d` | 3D PNGs or generic 2D PNG/SVG depictions. |

## Current evidence and limitations

| Evidence | Result |
| --- | --- |
| Automated workflow checks | Installation, routing, preparation, protocol reuse, docking, analysis, visualization, and reporting pass on current Ubuntu and macOS CI systems. |
| End-to-end validation | Completed a public 1HVR/XK2 control, a held-out screen using its saved protocol, and a ligand-free 2R8N/Indinavir exploratory study. |
| Receptor-preparation testing | 46/50 general public structures and 39/50 deliberately difficult linked-chemistry structures produced receptor PDBQTs under the documented safety policies. |

Known preparation limitations include some covalent adducts, linked glycans, metals/heme, modified backbones, and nucleic-acid complexes. These results test workflow behavior and safeguards; they do not establish broad prospective docking accuracy or biological validity. See the [validation index](docs/validation.md) and [100-PDB receptor-preparation record](docs/receptor-preparation-validation-2026-08-21.md).

## Example scientific reports

- [Complete current-style docking report](docs/assets/docking-universal-example-report.pdf)
- [Site-guided protocol report after explicit user-approved receptor-component removal](docs/assets/5KRH-user-approved-removal-cavity-report.pdf)

Reports adapt to control-validated, exploratory, protocol-reuse, and single- or multi-compound studies while retaining individual compound results. The 5KRH example shows how a model-changing removal is disclosed in the report; its exact component inventory and raw preparation log remain in the retained study artifacts and `.duprotocol` bundle.

## Documentation

- [Installation and troubleshooting](docs/installation.md)
- [Guided workflows and command options](docs/guided-workflow.md)
- [Workflow examples](docs/workflow-examples.md)
- [Scientific methodology and assumptions](docs/methodology.md)
- [Validation evidence and known limitations](docs/validation.md)
- [Design philosophy](docs/design-philosophy.md)
- [GitHub essentials for scientific users](docs/assets/github-essentials-for-docking-universal.pdf)

Every command also provides `--help`.

## Scope

Docking Universal currently supports rigid-receptor structural docking with AutoDock Vina. It does not perform molecular dynamics, induced-fit refinement, or free-energy calculations, and its results require scientific interpretation.

## License and citation

MIT. See [LICENSE](LICENSE). If Docking Universal contributes to your work, cite the repository release and the underlying scientific tools used. Machine-readable citation metadata is provided in [CITATION.cff](CITATION.cff); generated reports include applicable software versions and references.
