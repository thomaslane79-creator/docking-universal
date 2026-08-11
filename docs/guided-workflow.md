# Guided studies

For the two starting cases, see [bound-ligand and ligand-free workflow examples](workflow-examples.md). Runnable inputs and direct public-command tutorials are included under `examples/tutorials/` in the repository.

`docking-universal run` is the recommended entry point for a complete study. It organizes the composable preparation, docking, clustering, interaction, and rendering commands without hiding their files or assumptions.

This release performs rigid-receptor docking. Protein coordinates are fixed during Vina/smina searches; ligand torsions and independently prepared ligand conformers may still be sampled. Receptor conformational change and induced fit are outside the current scope. One SDF, a multi-record SDF, or a directory of SDF files can be processed as a batch, with failures and outputs isolated by compound.

## Choose the scientific pathway first

### Bound-ligand control

Use `--mode control` when a trustworthy experimental protein–ligand complex is available. The ligand identity and chemistry are verified, its experimental coordinates are withheld from conformer generation, and independent poses are redocked across recorded seeds. A protocol is approved only if the configured pose-recovery and repeatability rules pass.

After the quick diagnostic, interactive calibration offers **guided incremental calibration** or **manual tier selection**. Guided mode interprets the current sampling, ranking, and seed evidence, then proposes the next least-complex informative tier. It stops at the first reproducible pass and records the full escalation history. Manual mode tests only the selected settings and explicitly makes no claim that a cheaper protocol would work.

Calibration time can vary substantially with ligand flexibility, box size, engine, and hardware. After the first completed tier, the guide reports an empirical estimate for each later tier based on the observed time per docking job on the current machine. This estimate is advisory; it does not include all rendering or system-load variation.

```bash
./bin/docking-universal run --mode control --complex complex.pdb --out control_study
```

The interactive guide explicitly offers **Download from RCSB by PDB ID**, **Choose a local PDB with Finder** on macOS, or **Enter an exact local path**. These inputs deliberately mean different things. Both local options use exactly the selected file and never guess among prepared receptors and generated copies. The download option uses the canonical RCSB entry cached in this study or retrieves it. Downloads are stored under the study's `inputs/` folder with a source URL, retrieval time, and SHA-256 record. Finder selection is a convenience for local macOS use; manual paths remain portable to Linux, Docker, remote shells, and automation. For unattended use, supply the ID with `--complex` and add `--download-pdb` explicitly.

This is a retrospective target-specific check. Passing it supports transfer of the recorded search settings; it is not broad validation of the scoring function.

Unless `--out` is supplied explicitly, a completed control study is named `control_<PDB>_<ligand>_<YYYYMMDD_HHMMSS>` (for example, `control_1HVR_XK2_20260811_143025`). A `control_pending_...` folder is used only while the interactive ligand decision and control are unfinished. After completion, the runner applies the final scientific name and updates retained absolute paths so its approved protocol can be resumed later. User-supplied output names are never rewritten.

### Approved-protocol screen

Use `--mode screen` for unknown compounds only after a matching control has written an approved `protocol.json`. This is also the restart/resume path when calibration and compound docking are performed at different times. In an interactive run, omitting `--protocol` opens a guided choice: select `protocol.json` with Finder, select the completed control/study folder and discover its approved protocol, or enter either path manually. The protocol is accepted only if its recorded sampling, ranking, and independent-seed criteria passed. The receptor and box hashes must still match. Inputs can be one SDF, a multi-record SDF, or a directory of SDF files.

When `--ligands` is omitted during an interactive macOS run, the guide offers a Finder chooser for a single SDF. It also retains exact-path and SDF-directory choices for portable or batch use. The same chooser is used when continuing directly from a completed control into unknown-compound screening.

```bash
./bin/docking-universal run \
  --mode screen \
  --protocol control/05_calibration/broader/protocol.json \
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

When a raw ligand-free PDB is supplied, the runner prepares an expanded cavity search by default, retains candidate boxes with diagnostics, and chooses the first box deterministically in unattended mode. Interactive use lists the generated PyMOL cavity scenes and offers to open the review before docking. Use `--review-pockets` to request that launch explicitly, or adjust `--cavity-mode`, `--max-pockets`, and `--center-mode` for a different cavity-search policy.

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
│   ├── study_report.pdf
│   ├── report_figure_manifest.json
│   ├── run_details.md
│   └── index.html
└── study_manifest.json
```

`study_status` records scientific authority (`CONTROL_APPROVED` or `EXPLORATORY_NO_CONTROL`). `completion_status` independently records whether computation is planned, running, complete, or complete with warnings. Keeping these separate prevents a technically successful run from being mistaken for a scientifically calibrated one.

`report/run_details.md` consolidates the readable run record: what was found in the input PDB, every accepted SDF compound, the scientific mode, coordinate policy, receptor/box/protocol information, seeds, job counts, calibration history, failures, and the locations of raw outputs and logs.

The PDF report stage automatically generates numbered control and compound figures from the retained pose, cluster, receptor, and protocol artifacts. Control provenance is recovered from the protocol path stored in the screen manifest, so a screen launched separately from its control still produces a combined report. Figure distances use the same symmetry-aware, no-fit heavy-atom RMSD in the fixed receptor frame as pose clustering; the RMSD display includes a small margin below zero so a 0 A reference point is not clipped, while labeled ticks remain nonnegative. A control report includes SDF-aware interaction diagrams for the experimental pose, globally lowest-energy redocked pose, and globally lowest-RMSD redocked pose. Compound results similarly include the three top energy-ranked cluster representatives. Ligand chemistry comes from retained SDF files and PLIP calls come from retained XML; the report-figure manifest and per-diagram manifests record these sources and the coordinate-mapping check.

Every automatically generated PDF ends with a reproducibility section that assigns each reported quantity or visual to the program that produced it, lists run-specific software versions, and provides primary scientific/software references. The same information is written in machine-readable form as `report/software_versions_and_references.json`.

At completion, the terminal prints the exact `report/study_report.pdf` path. If optional PDF dependencies or figure generation fail, the workflow retains its HTML/Markdown/JSON reports and prints an explicit warning with the PDF-generation error rather than silently omitting the PDF.

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
