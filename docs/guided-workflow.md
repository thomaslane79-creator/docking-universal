# Guided studies

For the two starting cases, see [bound-ligand and ligand-free workflow examples](workflow-examples.md). Runnable inputs and direct public-command tutorials are included under `examples/tutorials/` in the repository.

`docking-universal run` is the recommended entry point for a complete study. It organizes the composable preparation, docking, clustering, interaction, and rendering commands without hiding their files or assumptions.

This release performs rigid-receptor AutoDock Vina docking. Protein coordinates are fixed during searches; ligand torsions and independently prepared ligand conformers may still be sampled. Receptor conformational change and induced fit are outside the current scope. One SDF, a multi-record SDF, or a directory of SDF files can be processed as a batch, with failures and outputs isolated by compound.

## Default or custom ligand ensemble

The interactive `docking-universal run` command is sufficient for ligand-state and conformer configuration; users do not need to call the standalone ensemble script. The recommended path uses pH 7.4, three conformers per chemical state where the selected tier does not specify otherwise, deterministic seeded ETKDG generation, MMFF94 with UFF fallback, a 0.75 A conformer-pruning threshold, tautomer enumeration, and Gasteiger charges.

Custom mode presents every ligand-ensemble setting used by the guided workflow: pH, conformers retained per chemical state, base seed, MMFF94/MMFF94s/UFF selection, RMSD pruning threshold, tautomer enumeration, and charge model. Exploratory mode also presents the number of independent docking seeds. During control calibration, a custom conformer count overrides the count in the chosen tier while seed count, exhaustiveness, and retained docking modes remain tier-controlled. The resulting values are written into the protocol and screen manifests.

Approved-protocol screening intentionally does not permit these values to be changed: it reads them from the passing target-locked protocol so unknown compounds are prepared consistently with the control.

## Choose the scientific pathway first

### Bound-ligand control

Use `--mode control` when a trustworthy experimental protein–ligand complex is available. The ligand identity and chemistry are verified, its experimental coordinates are withheld from conformer generation, and independent poses are redocked across recorded seeds. A protocol is approved only if the configured pose-recovery and repeatability rules pass.

After the quick diagnostic, interactive calibration offers **guided incremental calibration** or **manual tier selection**. Guided mode interprets the current sampling, ranking, and seed evidence, then proposes the next least-complex informative tier. It stops at the first reproducible pass and records the full escalation history. Manual mode tests only the selected settings and explicitly makes no claim that a cheaper protocol would work.

Calibration time can vary substantially with ligand flexibility, box size, engine, and hardware. After the first completed tier, the guide reports an empirical estimate for each later tier based on the observed time per docking job on the current machine. This estimate is advisory; it does not include all rendering or system-load variation.

```bash
./bin/docking-universal run --mode control --complex complex.pdb --out control_study
```

The interactive guide explicitly offers **Download from RCSB by PDB ID**, **Choose a local PDB graphically**, or **Enter an exact local path**. macOS uses Finder; graphical Ubuntu sessions prefer Zenity/GTK and use Tk as a fallback. These inputs deliberately mean different things. Both local options use exactly the selected file and never guess among prepared receptors and generated copies. The download option uses the canonical RCSB entry cached in this study or retrieves it. Downloads are stored under the study's `inputs/` folder with a source URL, retrieval time, and SHA-256 record. Manual paths remain available for headless Linux, Docker, remote shells, and automation. For unattended use, supply the ID with `--complex` and add `--download-pdb` explicitly.

This is a retrospective target-specific check. Passing it supports transfer of the recorded search settings; it is not broad validation of the scoring function.

Unless `--out` is supplied explicitly, a completed control study is named `control_<PDB>_<ligand>_<YYYYMMDD_HHMMSS>` (for example, `control_1HVR_XK2_20260811_143025`). A `control_pending_...` folder is used only while the interactive ligand decision and control are unfinished. After completion, the runner applies the final scientific name and updates retained absolute paths so its approved protocol can be resumed later. User-supplied output names are never rewritten.

### Approved-protocol screen

Use `--mode screen` for unknown compounds only after a matching control has written an approved protocol. A passing high-level control also creates a portable `.duprotocol` ZIP containing `protocol.json`, the locked receptor PDBQT and docking-box configuration, the experimental control SDF, selected control figures/evidence, and a SHA-256 manifest. It preserves the previously determined target-specific choices - receptor preparation, selected pocket and docking box, ligand-ensemble policy, exhaustiveness, independent seeds, requested pose count, and energy range - so the same protocol can be used unchanged to dock new sets of compounds. Reports for those later sets carry forward a concise protocol and validation synopsis: control status and completion date, control ligand, recovered-pose RMSD and threshold, locked pocket/box, and the control-to-new-run software comparison. This is the preferred restart input when calibration and compound docking occur at different times or on another compatible installation. Legacy `protocol.json` remains supported. A selected pocket or an exhaustiveness value is not approval by itself; the bound-ligand control must have passed the recorded sampling, ranking, and independent-seed criteria.

In an interactive run, omitting `--protocol` opens a guided choice: select `.duprotocol` or `protocol.json` graphically, select a completed control/study folder and discover its reusable protocol, or enter a path manually. A bundle is extracted safely, every retained file hash is verified, and its recorded screening authority is checked before use. The receptor and box hashes must still match. Inputs can be one SDF, a multi-record SDF, or a directory of SDF files.

When `--ligands` is omitted during an interactive desktop run, the guide offers Finder on macOS or Zenity/Tk on Ubuntu for a single SDF. It also retains exact-path and SDF-directory choices for portable or batch use. The same chooser is used when continuing directly from a completed control into unknown-compound screening.

```bash
./bin/docking-universal run \
  --mode screen \
  --protocol target_control_20260818_120000.duprotocol \
  --ligands compounds.sdf \
  --out approved_study
```

The default runs the protocol's independent conformers and seeds, retains every pose, clusters poses at 2 Å receptor-frame RMSD, and creates detailed outputs for up to three low-energy distinct clusters per compound. If only one cluster is present, its lowest-energy representative is used.

### Ligand-free exploratory docking

Use `--mode exploratory` when no suitable experimental control ligand exists. Prepare and review a ligand-free pocket first, then supply the receptor and chosen box.

```bash
./bin/docking-universal run \
  --mode exploratory \
  --receptor-pdb receptor.pdb \
  --receptor-pdbqt receptor.pdbqt \
  --box pocket.conf \
  --ligands compounds.sdf \
  --out exploratory_study
```

The output is permanently marked `EXPLORATORY_NO_CONTROL`. Convergence across seeds can reveal whether the search repeatedly finds similar poses, but it cannot substitute for pose-recovery evidence or experimental validation.

When a raw ligand-free PDB is supplied, the runner starts with conservative fpocket settings, retains candidate boxes with diagnostics, and chooses the first box deterministically only in unattended mode. It first applies the 0.10 score threshold. If no cavity survives, guided use offers a documented retry at 0.0 while retaining geometry, broad-pocket, and overlap filtering. The relaxed threshold expands the hypotheses available for review; it is not evidence of biological relevance.

Interactive use lists each generated box with its source pocket and fpocket score. Candidates within 0.05 score units or 20% of the best score (whichever tolerance is larger) are marked as competitive. The interface can open all competitive PyMOL scenes and then waits for the user to select the numbered pocket/box. The automatic cavity-report figure shows all retained pocket hypotheses on the receptor before a separate figure records the chosen box. Use `--review-pockets` to request PyMOL review explicitly, or adjust `--cavity-mode`, `--max-pockets`, and `--center-mode` for a different cavity-search policy.

## Useful options

- `--plan-only` checks inputs, splits a library, and writes reports without docking.
- `--analysis summary` writes pose and cluster tables without representative visuals.
- `--analysis none` retains docking and score outputs only.
- `--representatives 3` controls how many distinct low-energy clusters receive detailed output.
- `--cluster-rmsd 2.0` controls the heavy-atom RMSD grouping threshold in ångströms.
- `--stop-on-error` stops at the first failed compound. By default the study records that failure and continues.
- `--non-interactive` requires all scientifically meaningful inputs on the command line and is suitable for recorded batch work.

## Output structure

```text
study/
├── inputs/compounds/          one authoritative SDF per compound
├── compounds/<compound_id>/   input-named 2D depiction, ensembles, preparation, every seed, scores, clusters
│   └── pose_analysis/         tables, selected SDF/PDB, PML/PSE/PNG, PLIP results
├── report/
│   ├── compound_summary.csv
│   ├── study_summary.json
│   ├── study_report.md
│   ├── <PDB>_<ligand-or-library>_<YYYY-MM-DD>_<report-type>.pdf
│   ├── report_figure_manifest.json
│   ├── run_details.md
│   └── index.html
└── study_manifest.json
```

`study_status` records scientific authority (`CONTROL_APPROVED` or `EXPLORATORY_NO_CONTROL`). `completion_status` independently records whether computation is planned, running, complete, or complete with warnings. Keeping these separate prevents a technically successful run from being mistaken for a scientifically calibrated one.

`report/run_details.md` consolidates the readable run record: what was found in the input PDB, every accepted SDF compound, the scientific mode, coordinate policy, receptor/box/protocol information, the observed or protocol-carried receptor-preparation path, seeds, job counts, calibration history, failures, and the locations of raw outputs and logs. The Markdown, HTML, and JSON study summaries also identify that preparation path.

The PDF report stage automatically generates numbered control and compound figures from retained pose, cluster, receptor, and protocol artifacts. A control-backed screen is divided explicitly into configured protocol, experimental control redocking, and new-ligand docking sections. The target/new-ligand label appears only in the new-ligand section. The concise default control material shows the control date, ligand, PASS/REVIEW status, best-sampled RMSD, acceptance threshold, locked pocket/box, and one combined experimental-versus-redocked overlay. Detailed control interaction figures and provenance remain in `.duprotocol`; pass `--include-control-appendix` to the report generator for a full audit appendix.

New-ligand results include the three top energy-ranked cluster representatives. Ligand chemistry comes from retained SDF files and PLIP calls come from retained XML; the report-figure manifest and per-diagram manifests record these sources and coordinate mapping. Filename-only provenance suffixes such as `_pubchem` and `_pubchem_<CID>` are not presented as part of a ligand's chemical name.

When no bound-ligand control is supplied, the generator writes a distinct **Ligand-Free Cavity and Docking Report** instead of silently omitting validation. Its summary identifies the selected pocket and fpocket druggability score; the retained technical record contains candidate ranks, fpocket score, volume, alpha-sphere count, cavity bounds, box center, dimensions, and volume. Panel A shows ranked decisions; Panel B places retained pocket hypotheses on the receptor. A following figure records the chosen pocket and docking box. These are site-selection records, not pose-recovery validation or evidence that a predicted cavity is biologically correct. A preparation-only run receives cavity results only—no empty ligand, docking, RMSD, 2D interaction, or protocol section. Missing descriptors in older runs are reported as `NA`, never reconstructed or guessed.

Every automatically generated PDF ends with a reproducibility section that assigns each reported quantity or visual to the program that produced it and provides primary references. The section records whether receptor conversion succeeded with strict Meeko, used conservative PDBFixer repair before retrying strict Meeko, required the documented ADFRsuite compatibility fallback, or used an explicitly user-approved removal of unmatched components after safe attempts failed. If removal is approved, the PDF states that the receptor model changed and gives the number and classification of removed residues/components. Removal of any standard amino-acid residue is labeled a high-severity structural modification. That warning is stored in the protocol record and propagated through protocol selection and every subsequent JSON, Markdown, HTML, and PDF screening report. The exact inventory, approval record, and raw preparation log remain in the study artifacts and portable protocol bundle. PDBFixer is not described as having modified a receptor unless retained preparation artifacts show that it ran. When it ran, the PDF gives a short summary of added and deliberately unbuilt atoms/residues and states whether that repaired intermediate entered the final receptor. Detailed changes remain in the retained `receptor/pdbfixer_audit.json`; portable approved protocols retain the audit as `control/assets/pdbfixer_audit.json`. Every control-backed new run includes a full comparison table for Docking Universal, Python, RDKit, MolScrub, Meeko, PDBFixer, and AutoDock Vina. Matching reports state `Checked: no software version differences detected`; differences or unavailable versions are identified row by row. Additional analysis/reporting tools are listed separately. The same information and preparation record are written to `report/software_versions_and_references.json`.

At completion, the terminal prints the exact descriptive PDF path. The filename records the target, ligand scope, date, and report type. One to three ligand names are included directly; larger libraries use a bounded count such as `15-ligands`, while the full names remain inside the report and machine summary. If optional PDF dependencies or figure generation fail, the workflow retains its HTML/Markdown/JSON reports and prints an explicit warning with the PDF-generation error rather than silently omitting the PDF.

For multi-record SDF libraries, compound labels always come from each individual SDF record rather than the shared source filename. The PDF is published atomically only after every approved-style A/B panel and SDF-aware interaction diagram has been rebuilt successfully; a figure-generation failure cannot silently replace the approved report with raw fallback renders.

Each compound section also includes a compact 3D snapshot figure for up to the three lowest-energy distinct cluster representatives. The snapshots are labeled by energy rank, cluster ID, and Vina score, with red/blue/gold borders matching the A/B cluster figure. They supplement rather than replace the overlaid A/B comparison and the chemically typed 2D interaction diagrams. When only one cluster exists, only its lowest-energy representative is shown at a readable size.

Report pagination is content-driven rather than one-artifact-per-page. Compound snapshot figures, compact interaction diagrams, and ranked tables flow into available page space while each figure/caption unit remains intact. This reduces avoidable blank space without shrinking tables below the approved readable typography or violating standard margins.

### Heavy-atom RMSD and chemical-state mapping

Pose clustering uses symmetry-aware heavy-atom RMSD. Hydrogens are excluded because
their placement depends on protonation and preparation choices. During ensemble
generation, each parent compound receives stable heavy-atom map numbers that are
carried through protonation, tautomer, and conformer generation. This makes atom
correspondence explicit and avoids relying on incidental SDF atom order. States
with a changed heavy-atom scaffold are rejected rather than assigned an
unreliable RMSD. Chemical-state identity remains recorded alongside each pose;
cross-state comparisons are made only when the parent heavy-atom mapping is
unambiguous.

## Interpreting a completed study

Docking energy is a model score used for ranking under one protocol; it is not a measured binding free energy. A cluster supported by several seeds indicates repeatability of the search, not necessarily pose correctness. Review steric fit, chemical plausibility, protonation, interactions, alternative clusters, and relevant experimental evidence before drawing conclusions.
