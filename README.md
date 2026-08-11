# Docking Universal

Docking Universal is a scientific workflow, orchestration, validation, and reporting layer built around **AutoDock Vina**, which performs the actual docking search and scoring. Docking Universal does not introduce a new docking engine or scoring function. It prepares receptors and ligand ensembles, defines and reviews docking boxes, calibrates target-specific search settings, runs reproducible Vina batches, clusters and analyzes poses, and produces auditable visual and PDF reports.

In short: **Vina docks; Docking Universal makes the surrounding scientific workflow reproducible and reviewable.** The optional smina path is retained for engine-comparison work, but Vina is the default and presently validated path in this research preview.

The current release supports **rigid-receptor docking only**: receptor coordinates remain fixed during each Vina or optional smina search. Prepared ligand torsions may remain flexible, and independent ligand conformers can be searched, but receptor side-chain or backbone flexibility is not modeled. The guided runner accepts a multi-record SDF or a directory of SDF files for batch docking, with one isolated result folder per compound.

It consolidates a series of working research scripts behind one consistent command while retaining the provenance and diagnostics that made the original workflow auditable.

The project was created in part to make this compiled scientific toolchain practical and reproducible on Apple-silicon M-series computers. Its current reference platform is an M2 Mac (`osx-arm64`); portability to other platforms remains a tested goal rather than an assumed guarantee.

## Project status

**Research preview.** The core workflow has produced useful outputs across the author's working structural-docking cases. A matched public 1HVR/XK2 case passes raw preparation, ligand-free pocket recovery, engine execution, score collection, PLIP processing, and visual rendering on an M2 Mac. Its five-seed Vina ensemble control passed the target-specific 2 Å sampling/ranking rule; the tested smina rigid-macrocycle control did not. This single retrospective case is not broad accuracy validation. See [Validation](docs/validation.md).

![A ligand-centered pocket rendered from a Docking Universal PyMOL scene](docs/assets/ligand-pocket.png)

## Example scientific report

[View the complete automatically generated PDF report](docs/assets/docking-universal-example-report.pdf).

This representative 1HVR/XK2 study shows the standard report produced by the pipeline: retrospective bound-ligand control and PASS criteria, the selected target-matched protocol, two-compound docking results, score-versus-RMSD cluster panels, color-matched 3D cluster representatives, SDF-aware 2D interaction diagrams, ranked docking tables, limitations, software versions, and references. It is included as a format and workflow example; its target-specific retrospective result is not general validation of docking accuracy.

## Package map

| Stage | Command | Main outputs |
| --- | --- | --- |
| Guided study | `docking-universal run` | control, approved-screen, or exploratory workflow; per-compound folders; CSV/JSON/Markdown/HTML reports |
| Independent ensemble | `docking-universal ensemble` | pH-aware protomer/tautomer states and reproducible ETKDG/MMFF conformers |
| Bound-ligand control | `docking-universal control` | verified experimental-coordinate SDF, redocked poses, scores, pose RMSDs, PLIP/PyMOL visuals |
| Receptor + sites | `docking-universal prepare` | receptor PDB/PDBQT, ligand manifest, pocket diagnostics, Vina boxes, PyMOL scenes |
| Compound library | `docking-universal ligands` | optimized per-compound PDBQT files with name and SMILES metadata |
| Pocket coordinates | `docking-universal pockets` | ranked pocket coordinates, box PDBs, and configuration files |
| Batch execution | `docking-universal dock` | per-compound PDBQT models, logs, and run manifest |
| Result collation | `docking-universal collect` | tidy CSV preserving Vina and smina score/RMSD formats |
| Pose comparison | `docking-universal compare-redock` | symmetry-aware pose RMSDs, summary, complexes, and overlay scene |
| Control evaluation | `docking-universal evaluate-control` | sampling/ranking/seed acceptance and versioned protocol gate |
| Protocol-locked unknown | `docking-universal screen` | independent unknown-ligand ensemble, replicated poses, combined scores, audit manifest |
| Cross-run pose clustering | `docking-universal cluster-poses` | all-pose inventory, energy-ranked clusters, three representative scenes, seed/conformer support |
| Interactions | `docking-universal interactions` | PLIP XML/text, fixed coordinates, all-in-one PyMOL PML, manifest |
| 3D output | `docking-universal render3d` | headless PyMOL PNG from an existing PML or coordinate file |
| 2D output | `docking-universal depict2d` | generic PNG/SVG molecular depictions from existing coordinate files |

## Requirements

The dispatcher and file-processing commands require Bash 3.2+, Python 3, and standard Unix tools. Scientific dependencies are stage-specific:

- receptor and pocket preparation: Meeko `mk_prepare_receptor.py` plus `fpocket`, with ADFRsuite `prepare_receptor` as a legacy backend;
- ligand-library preparation: Open Babel (`obabel`) plus Meeko `mk_prepare_ligand.py`, with ADFRsuite `prepare_ligand` as a legacy backend;
- batch engines: smina in the main environment and AutoDock Vina in an optional engine environment;
- interaction analysis: PLIP (`plip`), followed by Docking Universal's custom consolidated PyMOL-scene writer;
- 3D rendering: `pymol`;
- 2D rendering: RDKit when available, with Open Babel as a fallback.

Check what is visible on the current workstation:

```bash
./bin/docking-universal doctor
```

Only dependencies used by the selected stage are required.

The direct versions verified in a fresh macOS arm64 environment are pinned in [environment.yml](environment.yml), with a complete historical conda build snapshot in `environment-lock-osx-arm64.txt` and a Python distribution snapshot in `requirements-pip-lock.txt`. See the [installation guide](docs/installation.md) and [working scientific environment](docs/environment.md). Receptor and ligand conversion in the original workflow used ADFRsuite 1.0 as a separate installation; a portable Meeko backend is included in the clean environment while compatibility work is completed.

## Install

Create the tested scientific environment:

```bash
conda env create -f environment.yml
conda activate docking-universal
./bin/docking-universal doctor
make test
```

To run comparison jobs with AutoDock Vina as well as smina, create the small optional engine environment:

```bash
conda env create -f environments/vina.yml
```

The `dock` command discovers Vina there automatically. The two engines are run as separate, auditable batches against the same receptor, ligand directory, and box configuration.

For exact reproduction of the M2 Vina test environment, use `environments/vina-lock-osx-arm64.txt`; use the readable YAML for normal installation.

Then use the repository directly through `./bin/docking-universal`, or install the command system-wide:

```bash
make install
```

Or install without administrator access:

```bash
make install PREFIX="$HOME/.local"
```

On Apple silicon, install the conda-forge package named `pymol-open-source`, not the official native bundle. The pinned PyMOL 3.0.0, PyCairo 1.27.0, RDKit 2023.09.6, and Python 3.9 matrix was freshly solved and its headless rendering path verified on macOS arm64 on 2026-08-08. See [Installation](docs/installation.md) for the M2 note, stage-by-stage dependencies, and troubleshooting.

## Command overview

```text
docking-universal run
docking-universal run --mode control --complex 1HVR --download-pdb --out control_study --non-interactive
docking-universal run --mode screen --protocol protocol.json --ligands library.sdf --out study
docking-universal run --mode exploratory --receptor-pdb receptor.pdb --receptor-pdbqt receptor.pdbqt --box pocket.conf --ligands library.sdf --out study
docking-universal run --mode exploratory --complex protein_only.pdb --ligands library.sdf --review-pockets --out study
docking-universal control --complex bound_complex.pdb
docking-universal control --complex bound_complex.pdb --control-tier broader --non-interactive
docking-universal ensemble ligand_template.sdf --out ensemble.sdf --ph 7.4 --conformers 10
docking-universal prepare <complex.pdb>
docking-universal ligands <library.sdf> [-n SDF_NAME_FIELD]
docking-universal pockets <protein_only.pdb> <name> [quick|robust]
docking-universal dock --engine smina --receptor receptor.pdbqt --ligands DIR --config box.conf --out results_smina
docking-universal dock --engine vina --receptor receptor.pdbqt --ligands DIR --config box.conf --out results_vina
docking-universal collect RESULTS_DIR --out scores.csv
docking-universal screen --protocol protocol.json --ligand unknown.sdf --out unknown_run
docking-universal interactions complex.pdb --plip-command plip
docking-universal render3d scene.pml --out scene.png
docking-universal depict2d ligand.pdb ligand.sdf --out-dir 2d_depictions
```

Every subcommand provides `--help`.

`docking-universal run` is the recommended entry point. In interactive use it explains and offers three scientifically distinct paths: a retrospective bound-ligand control, screening with a target-locked approved protocol, or explicitly uncalibrated exploratory docking when no suitable bound ligand exists. It accepts one SDF, a multi-record SDF, or a directory of SDF files. Each compound is isolated in its own folder so a failure does not erase completed work, and the final `report/` contains CSV, JSON, Markdown, HTML, and PDF summaries. The PDF stage automatically rebuilds the control and per-compound cluster figures from retained artifacts. A control report includes SDF-aware PLIP interaction diagrams for the experimental, globally lowest-energy, and globally lowest-RMSD poses. Each compound includes the approved A/B cluster figure, a compact color-matched 3D snapshot figure for up to three low-energy distinct clusters, and chemically typed 2D interaction diagrams for those representatives. The ligand drawing uses the retained pose SDF rather than inferring bond order from a PDB; PLIP XML supplies the interaction calls and ligand contact coordinates. It does not depend on manually prepared images. Use `--plan-only` to validate and split inputs without docking. See the [guided workflow](docs/guided-workflow.md) for the choices, outputs, and interpretation limits.

The guided command also offers **recommended defaults** or a **custom ligand ensemble**. Custom mode presents pH, conformers per chemical state, deterministic base seed, MMFF94/MMFF94s/UFF selection, conformer RMSD pruning, tautomer enumeration, charge model, and—during exploration—independent docking-seed count. These choices are passed to the actual ensemble and docking stages and recorded in protocol or screening manifests. An approved-protocol screen displays and reuses its locked ensemble settings rather than allowing an inconsistent override.

The approved-protocol screen is the supported restart path after a completed control. If `--protocol` is omitted interactively, the runner can select `protocol.json` with Finder or discover approved protocols inside a selected control/study folder before asking for the new compound SDF input.

Default completed control folders use the readable form `control_<PDB>_<ligand>_<YYYYMMDD_HHMMSS>`, such as `control_1HVR_XK2_20260811_143025`. Explicit `--out` folder names remain unchanged.

### Run end-to-end or in separate stages

You can run the entire guided workflow with `docking-universal run`, or pause between stages. In a split workflow, first run the bound-ligand control, then pass its resulting `protocol.json` to the approved screen:

```bash
# Stage 1: control and protocol calibration
docking-universal run --mode control --complex bound_complex.pdb --out control_study

# Stage 2: unknown-compound screening with the recorded protocol
docking-universal run --mode screen --protocol control_study/control/04_redocking/vina/repeatability/protocol.json --out screen_study
```

When `--ligands` is omitted in the interactive screen on macOS, the workflow offers Finder selection for a single SDF, plus exact-path and SDF-directory choices. The same chooser appears when continuing directly from a successful control. The report is generated automatically at the end of each study. When a screen uses a recorded control protocol, the report stage recovers that control from the compound manifest even if control and screening were launched as separate commands. A multi-record batch can be tested with `examples/test_inputs/two_compounds.sdf` when that test input is present. Up to three low-energy cluster representatives are reported; if only one cluster exists, its lowest-energy representative is used.

Exploratory mode is intentionally labeled `EXPLORATORY_NO_CONTROL` in every consolidated report. Its poses and scores are hypotheses for structural review; that label cannot be converted into protocol approval by completing the run.

## Bound-ligand control

Two [complete workflow tutorials](examples/tutorials/README.md) show the major starting cases: a 1HVR/XK2 bound-ligand control and a 2R8N unbound cavity-search study.

`docking-universal control` is the guided retrospective-control workflow. It lists exact bound-ligand instances as `RESNAME:CHAIN:RESNUM` with atom counts and requires confirmation. The Bash prompt then offers strict chemistry verification (recommended) or a manual override whose reason is recorded in `run_manifest.tsv`.

The default path now performs independent-ensemble calibration and writes a versioned, target-locked `protocol.json`. The superseded single-conformer implementation is available only through `--legacy-single-conformer` to reproduce historical output and cannot authorize unknown docking.

Strict mode maps an RCSB Chemical Component Dictionary template—or an explicitly supplied `--ligand-template` SDF—onto the selected crystallographic coordinates. It writes `<RESNAME>_experimental.sdf`, removes the selected ligand for receptor preparation, discards the bound coordinates before conformer generation, and redocks independent chemical-state/conformer ensembles. Vina and smina are calibrated separately because their supported macrocycle representations differ.

For an unpublished local complex with no authoritative ligand SDF, `--infer-ligand-chemistry --force-ligand --override-reason "..."` is an explicit **not-recommended** fallback. It uses Open Babel to perceive a provisional graph from PDB geometry, writes a labeled 2D review image, and requires interactive confirmation before docking. The resulting manifest records that the chemistry was inferred; a curated SDF remains the appropriate choice whenever available.

An internet connection is not required to use a local complex. When the CCD lookup is unavailable in an interactive run, the same provisional-review option is offered rather than silently substituting chemistry or failing without recourse. A control using inferred PDB chemistry may be inspected as exploratory output, but its protocol is intentionally ineligible to authorize screening of unknown compounds.

In the default path, “CCD chemistry” means only the coordinate-free molecular graph represented by isomeric SMILES: atom identities, connectivity, bond orders, formal charge, and defined stereochemistry. CCD ideal 3D coordinates are not requested or used. The experimental coordinates extracted from the PDB are stored separately and withheld for RMSD evaluation; docking conformers are embedded independently.

The default `quick` tier runs 3 conformers × 2 seeds at exhaustiveness 16 as a diagnostic and cannot satisfy the default five-seed approval rule. If it fails or is incomplete, interactive use offers targeted repeatability, broader-search, conformer-expansion, robust, or input-inspection choices and shows the planned docking-job count. No slow retry begins without confirmation. For unattended work, choose a tier explicitly with `--control-tier` and add `--non-interactive`.

```bash
docking-universal control --complex 1HVR.pdb
```

For a recorded noninteractive run, use the exact candidate identifier:

```bash
docking-universal control --complex 1HVR.pdb --ligand-id XK2:A:263
```

The explicit override is also available from Bash for exceptional chemistry, but it requires an audit note:

```bash
docking-universal control --complex unusual_complex.pdb --ligand-id LIG:A:401 \
  --force-ligand --override-reason "Curated local ligand identity and bond orders"
```

This control is separate from prospective docking and ligand-free pocket evaluation. Its interaction visuals describe the experimental ligand and redocked control poses; they are not reused as evidence for unrelated screened compounds.

The calibration path deliberately strips all template coordinates before ensemble generation. MolScrub enumerates pH-dependent chemical states; Docking Universal then generates seeded ETKDG conformers and force-field minimizes them. The crystallographic pose is withheld until RMSD evaluation. A v1 protocol is eligible for unknown docking only when both the best sampled pose and globally top-ranked pose meet the configured RMSD threshold for every required independent seed. It records the engine, macrocycle treatment, search settings, seeds, receptor and box paths, and SHA-256 hashes.

`docking-universal screen` consumes an approved protocol and one unknown-compound SDF. It verifies that the receptor and box are unchanged, independently generates the recorded number of pH-aware conformers, repeats docking with the recorded seeds, and combines scores. Failed, incomplete, altered, or engine-incompatible protocols are rejected. Protocol transfer preserves a tested search configuration; it does not prove that an unknown pose or score is correct.

By default, screening then clusters all poses across seeds and conformers at a 2.0 Å symmetry-aware no-fit heavy-atom RMSD cutoff. It selects the lowest-energy members of the three lowest-energy distinct clusters for PLIP and PyMOL output while retaining every raw pose. See [Pose clustering and representative analysis](docs/pose-clustering.md) for option meanings and scientific interpretation.

PyMOL scenes load chemically typed ligand SDFs so bond display does not depend on PDB distance perception. PLIP still receives a PDB complex, but ligand atom serials are made unique and template-derived `CONECT` records are retained; the custom scene combines PLIP interaction coordinates with the authoritative SDF ligand.

## Receptor cavities and docking-box selection

`docking-universal prepare` is the guided, high-audit workflow. It prepares the receptor, detects bound ligand candidates, supports ligand-centered and ligand-free cavity modes, produces coordinates and equal-size Vina boxes, and writes PyMOL review scenes.

In ligand-centered mode, the selected ligand centroid anchors the docking box. A local protein region is passed to `fpocket`; alpha spheres are retained when they overlap ligand van der Waals volume and remain within the configured centroid cutoff. The ligand identifies the reference site; it is not itself a biological proof of pocket identity.

The pre-release control workflow uses a configurable cubic docking-box edge (26 Å by default) centered on the selected experimental ligand coordinates. The control center is fixed; only the edge length is chosen. For ligand-free workflows, the edge is centered on the reviewed cavity. The current edge is not automatically derived from cavity dimensions. Cavity-derived box sizing with user-controlled padding is planned as a future enhancement.

In cavity mode, candidates pass score and geometry checks, then receive a combined rank:

```text
fpocket_score × exp(−distance_to_reference_centroid / 10)
```

The reference is the whole protein or largest chain. Boxes that exceed the configured volume-overlap fraction with an earlier choice are suppressed. See [Methodology](docs/methodology.md) for assumptions and limitations.

## Visual output from existing files

The visualization commands do not run docking or modify the input structures.

`render3d` accepts an existing `.pml`, `.pse`, `.pdb`, `.pdbqt`, `.mol2`, or `.sdf`. It starts PyMOL in quiet headless mode, applies a neutral default style for raw coordinates, ray-traces the view, and writes a PNG.

```bash
docking-universal render3d output_scene.pml --out figures/output_scene.png
```

`depict2d` accepts one or more existing coordinate files and creates generic molecular depictions. PNG and SVG are supported.

```bash
docking-universal depict2d ligand.pdb ligand_02.sdf --format svg --out-dir figures/2d
```

These are generic structure depictions. Protein–ligand interaction visuals use a separate path: PLIP computes and writes interaction reports and fixed coordinates, then Docking Universal reads those outputs and writes a consolidated PyMOL PML scene. This custom scene step avoids depending on PLIP's native visualization path, which was unreliable in the original environment.

The repository includes small, provenance-recorded inputs for the 1HVR/XK2 bound-ligand tutorial and the 2R8N ligand-free cavity tutorial. The [example PDF report](docs/assets/docking-universal-example-report.pdf) demonstrates the automatic consolidated-report path without adding bulky intermediate docking runs to the repository. A separate generic XK2 depiction demonstrates the SDF-to-2D path without implying docking or receptor interactions.

## Output provenance

Depending on the stage, Docking Universal records:

- chain sizes and centroid context;
- detected ligand names, atom counts, and source files;
- pocket score, alpha-sphere count, dimensions, warnings, rank, overlap, and selection state;
- exact box centers and dimensions;
- per-compound engine logs and a run manifest;
- PLIP reports, interaction counts, and the coordinate file used for visualization.

Every guided study also writes `report/run_details.md`: a single readable record of the input inventories, scientific status, coordinate policy, selected protocol or exploratory settings, seeds, compound-level manifests, calibration history when applicable, and retained output locations. Raw engine and preparation logs remain alongside their respective stages.

Pose clustering compares compatible ligand states with symmetry-aware heavy-atom
RMSD. The ensemble generator preserves parent-compound heavy-atom map numbers
through protonation, tautomer, and conformer generation, so RMSD matching does
not depend on accidental atom ordering in an SDF. Hydrogens are excluded from
pose RMSD; state and formal-charge metadata remain available for interpretation.

## Test

```bash
make test
```

The automated suite checks every public command's help interface, Bash syntax, Python syntax, version output, and dependency reporting. Local rendering smoke tests are also used when the optional tools are available. Broader end-to-end scientific validation remains ongoing.

## Scope

Docking Universal is limited to rigid-receptor structural docking preparation, batch execution support, result parsing, and visualization. It does not perform flexible-receptor docking, molecular dynamics, induced-fit refinement, or free-energy calculations. It does not claim biological validity, predict clinical outcomes, or replace expert review. Pocket ranks and generated depictions are transparent computational artifacts, not experimental conclusions.

## GitHub Pages

The `docs/` directory is a zero-build static project page. In GitHub repository settings, select **Deploy from a branch**, choose the default branch, and publish `/docs`.

## License

MIT. See [LICENSE](LICENSE).

## Citation

If the software contributes to published work, cite the repository release and the scientific tools used by the relevant stages. Machine-readable project citation metadata is provided in [CITATION.cff](CITATION.cff).
