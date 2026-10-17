# Guided studies

## Desktop site discovery with a bound ligand

**Starting point for site review** chooses initial guidance, not the final
docking location. During review you can select one or more regions, including
sites elsewhere supported by related structures or optional pocket prediction.

Choose **Selected bound ligand** for its experimental site. Optionally enable
**Also run P2Rank to look for other pockets?** and leave the detector
at **P2Rank** to explore alternatives on the prepared receptor with the ligand
removed. Prediction does not dock anything or select/approve a site. The exact
input-ligand region is retained separately, without a prediction score or an
extra independent-evidence count. Effectively identical boxes share provenance
instead of becoming duplicate choices.

The related-public-PDB search is a separate checkbox, also available for a
known-ligand control. Turn it off for local-only site review. A recorded input
PDB entry is excluded from new related-entry evidence; unavailable entry IDs
are not guessed from filenames. Online failure/partial coverage is disclosed,
not interpreted as proof that no ligand evidence exists.

Without running P2Rank, qualified related-structure ligand locations can still
provide independent selectable boxes. Select these L# regions in **Review &
decide**, alone or alongside the input ligand site; a prediction score is not
required. Corresponding sites share evidence rather than becoming duplicate
boxes. Only regions you explicitly approve proceed to the next step.

The interface marks the recommended choices explicitly: experimental-ligand
redocking when a suitable control is available, related-public-PDB evidence
lookup with internet access, and optional P2Rank for additional-site review.
These labels do not turn options on automatically or approve any boxes. You
can still skip redocking (explicitly exploratory), use local-only evidence,
or use the known ligand site without running P2Rank.

These analyses are independent checkboxes, not a list of every possible
configuration. **Redock experimental ligand** controls pose-recovery testing;
leave it unchecked to create an exploratory protocol. **Search related public
PDB structures** controls online site evidence, and **Also run P2Rank to look
for other pockets?** controls extra prediction. Related-structure ligand boxes
remain selectable with P2Rank off. Turning redocking off preserves the chosen
ligand site. **Study source** separately chooses a new structure or reuse of a
saved protocol. Recommendation labels guide choices without changing defaults:
PDB lookup starts on; redocking and additional prediction remain explicit opt-ins.

For controls, prepare and gather evidence first, approve one or more sites,
then run the reviewed control. Only its tested site/receptor/engine/settings
can receive control authority. Other selected sites or receptor states remain
explicitly exploratory and require separate exploratory protocol approval.
Reopening a study does not rerun preparation, lookup or docking. Imported
protocols remain locked; they are not silently expanded with new sites.

For the two starting cases, see [bound-ligand and ligand-free workflow examples](workflow-examples.md). Runnable inputs and direct public-command tutorials are included under `examples/tutorials/` in the repository.

`docking-universal run` is the recommended entry point for a complete study. It organizes the composable preparation, docking, clustering, interaction, and rendering commands without hiding their files or assumptions.

This release performs rigid-receptor docking with AutoDock Vina or QuickVina-W. Protein coordinates are fixed during searches; ligand torsions and independently prepared ligand conformers may still be sampled according to the engine-compatible ligand representation. Receptor conformational change and induced fit are outside the current scope. One MOL (V2000/V3000), a single/multi-record SDF, or a folder containing SDF and MOL files can be processed, with failures and outputs isolated by compound. In the GUI use **File…** or **Folder…** under screening. MOL is one molecule per file; use SDF for multi-molecule libraries. Input extensions are case-insensitive. Imports preserve typed chemistry and original-source provenance; normal protocol-driven ligand preparation occurs afterward.

Batch processing attempts every independent compound by default. Successful outputs and reports are retained, but the command returns a nonzero final status if any ligand preparation or docking job fails, so automated callers cannot mistake a partial batch for complete success.

## Reuse a saved protocol in a new desktop study

Create a fresh study, then choose **Study setup → Study source → Use a
saved protocol**. Browse to a `.duprotocol` and choose **Review and import
protocol**. Review the target, scientific status, locked regions and settings,
then explicitly import. Verification checks the archive inventory and retained
input hashes; it does not establish that the scientific choices are correct.
Damaged, changed or unauthorized bundles are rejected. Existing studies cannot
be replaced by an import; create a new study instead.

The host saves a verified study-owned copy, so later screening/reopening does not
depend on the original bundle location. The prepared receptor, regions, engine,
ligand-preparation policy and search settings stay locked. Preparation and region
approval are inherited, not silently rerun or recorded as new decisions.
**Review imported settings…** remains available in Study setup. To change locked
scientific choices, create and approve a new protocol instead.

Continue to **Screen ligands**, read/select compounds, preview the workload and
choose an output folder. Exploratory protocols still require explicit
exploratory-use approval; importing does not turn them into control-validated
protocols. A saved AD4 protocol remains AD4 and still requires its supported
local engine installation; it is never silently switched to Vina. The bundle is
portable, but it does not install engines or dependencies on the receiving
machine. Reopen the study to review retained results, interactions, reports and
elapsed time without repeating docking.

## Choose compounds for screening

In the desktop screening step, **File…** reads SDF, MOL, CSV, TSV or XLSX locally;
**Folder…** reads an SDF/MOL folder. For a manually entered path, click
**Read/select compounds…**. Click a
row to inspect the input molecule's 2D structure; use its **Dock** checkbox to
include it. Inspection does not select it. **Select all valid** and **Clear
selection** are explicit batch shortcuts; invalid records stay visible and cannot
be selected. Once a library is read, nothing is selected until you check it.
Preview the selected workload, approve exploratory use if required, then choose
**Dock selected compounds**. Changing selection invalidates the previous preview.
Changing a source file requires reading/selecting again. Input records and file
hashes are saved in `inputs/ligand_library_review.json`; only selected compounds
appear in the docking inventory. This does not change locked protocol chemistry.
The unreviewed/all-compound path remains available for SDF/MOL, explicitly
labeled, as does the existing SDF/MOL CLI default.

For **CSV/TSV/XLSX**, the first nonempty row is the header. Choose the Excel
worksheet, then review the **SMILES column** and optional **Name / ID column**.
A recognized header such as `SMILES`, `isomeric_smiles` or `canonical_smiles`
prefills the dropdown only: click **Use these columns** to approve it before any
compounds load. Every header is selectable, including duplicate/unnamed headers
identified by column number. Choose **None** for generated Compound numbers.
Changing a column or worksheet clears selected compounds and invalidates the
workload; approve the new mapping and select compounds again. No compounds are
selected by approval alone.

CSV uses commas and TSV uses tabs; quoted fields and UTF-8/BOM or UTF-16/BOM text
are supported. Excel cells must contain literal SMILES text: formulas (even with
cached results), numeric SMILES, dates, booleans and error cells are invalid.
Macros, formulas and external links are never executed. Blank rows are ignored;
nonempty rows with missing/invalid SMILES remain visible with a reason. Import
does not deduplicate molecules, generate conformations or change charge/stereo.
Only explicitly selected valid records are materialized into individual typed
SDF inputs for the existing preparation/engine workflow.

Original file hashes, worksheet, source row, submitted SMILES and approved column
positions are retained in the review ledger and selected compound inventory.
The selection fingerprint includes the mapping: a changed file or mapping is
rejected before launch and again before materialization, including after a host
restart. The CLI can consume the same reviewed selection JSON with
`--ligands table.csv --ligand-selection selection.json`; it will not guess/approve
table columns on an unattended run. Interactive terminal file pickers remain
SDF/MOL-only; table mapping is available in the desktop or the host review API.
Tables must be opened individually, not as a mixed-table folder. Only `.xlsx`
is supported (not legacy `.xls` or `.xlsm`); worksheets are imported one at a
time. Limits are 100,000 data rows, 4,096 columns, and 128 MB of file/uncompressed
Excel XML. These bounds and pagination do not imply unlimited-memory streaming.

The compound table defaults to **50 records per page**. Choose 25, 50, 100 or
250 rows, use Previous/Next, or enter a page number. Dock selections persist
across pages; the selected count and workload include the entire library, not
just the visible page. Select all valid and Clear selection also cover all pages.
Page navigation alone does not alter a selection or invalidate its workload.
The scientific host initially indexes the full local library, then reuses bounded
review/2D caches while browsing. File-change guards protect preview reuse, and
full source hashes are checked again for workload and launch. Initial loading
still depends on library size and chemistry; pagination is not unlimited-memory
streaming. Library indexing runs off the GUI thread with visible read feedback.

The library's 2D preview, formula and charge describe the **submitted input**,
not a structure recalculated at the protocol pH. During screening, ligand-state
preparation considers protonation and tautomers using the locked pH before
generating/preparing starting conformers for docking. The input drawing is not
silently replaced with a single supposedly definitive pH-dependent state.

While screening runs, the existing activity area shows the current compound,
preparation/docking/analysis phase, site and repeat/seed when docking, and report
generation. Docking output counts are compared with the **initial planned** job
count; chemical-state enumeration can change the actual count. Phase messages and
written files do not prove scientific success or whole-run completion: the
supervised process's final status and retained failures remain authoritative.
Some searches/rendering phases can be quiet; elapsed time is not proof of
progress. Logs remain available for diagnostics. These worker phase records are
available for newly launched runs; an already running process is not restarted.

**Screen ligands** also keeps the latest screening's total elapsed time after
completion and reopening. This is supervised wall time for preparation, docking,
analysis and reporting together. Running time continues to update; older jobs
without usable timestamps explicitly show that the duration is unavailable.

Screening options include brief explanations beside their controls.
**Representative clusters** sets how many lowest-energy distinct pose groups per
compound receive detailed output, using each group's lowest-energy pose; it does
not limit the number of compounds or total retained poses. **Clustering cutoff**
uses symmetry-aware heavy-atom RMSD in the receptor frame without realignment:
smaller values separate more groups and larger values merge more. The default is
1.5 Å; explicit saved choices remain unchanged. This distance is not RMSD to an
experimental pose or the separate pose-recovery acceptance threshold. Analysis
choices affect post-docking outputs, not the docking search itself.

## Default or custom ligand ensemble

The interactive `docking-universal run` command is sufficient for ligand-state and conformer configuration; users do not need to call the standalone ensemble script. The recommended path uses pH 7.4, three conformers per chemical state where the selected tier does not specify otherwise, deterministic seeded ETKDG generation, MMFF94 with UFF fallback, a 0.75 A conformer-pruning threshold, tautomer enumeration, and Gasteiger charges.

The current MMFF94/MMFF94s/UFF ligand minimization uses a **vacuum-energy model**,
without explicit solvent or an implicit-water term. Its energy ranks starting
conformers within the same chemical state; it is not a solution free energy or
a docking/binding-affinity score. pH-aware state enumeration does not make this
geometry minimization solvent-aware. Docking subsequently applies the selected
engine's separate scoring function in the receptor environment.

An opt-in solvent-aware preparation method is being evaluated in an isolated
[paired benchmark](conformer-ab-benchmark.md), with a substantial runtime cost.
It is not yet a production GUI/CLI backend or an automatic recommendation based
on ligand size. Benefits with other scoring functions, including AD4 or smina,
would require matched validation rather than being inferred from Vina results.

Custom mode presents every ligand-ensemble setting used by the guided workflow: pH, conformers retained per chemical state, base seed, MMFF94/MMFF94s/UFF selection, RMSD pruning threshold, tautomer enumeration, and charge model. Exploratory mode also presents the number of independent docking seeds. During control calibration, a custom conformer count overrides the count in the chosen tier while seed count, exhaustiveness, and retained docking modes remain tier-controlled. The resulting values are written into the protocol and screen manifests.

Approved-protocol screening intentionally does not permit these values to be changed: it reads them from the passing target-locked protocol so unknown compounds are prepared consistently with the control.

## Choose the scientific pathway first

### Bound-ligand control

Use the control pathway when a trustworthy experimental protein–ligand complex is available. The ligand identity and chemistry are verified, its experimental coordinates are withheld from conformer generation, and independent poses are redocked across recorded seeds. A protocol is approved only if the configured pose-recovery and repeatability rules pass.

After the quick diagnostic, interactive calibration offers **guided incremental calibration** or **manual tier selection**. Guided mode interprets the current sampling, ranking, and seed evidence, then proposes the next least-complex informative tier. It stops at the first reproducible pass and records the full escalation history. Manual mode tests only the selected settings and explicitly makes no claim that a cheaper protocol would work.

Calibration time can vary substantially with ligand flexibility, box size, engine, and hardware. After the first completed tier, the guide reports an empirical estimate for each later tier based on the observed time per docking job on the current machine. This estimate is advisory; it does not include all rendering or system-load variation.

```bash
docking-universal run control --complex complex.pdb --out control_study
```

The interactive guide explicitly offers **Download from RCSB by PDB ID**, **Choose a local PDB graphically**, or **Enter an exact local path**. macOS uses Finder; graphical Ubuntu sessions prefer Zenity/GTK and use Tk as a fallback. These inputs deliberately mean different things. Both local options use exactly the selected file and never guess among prepared receptors and generated copies. The download option uses the canonical RCSB entry cached in this study or retrieves it. Downloads are stored under the study's `inputs/` folder with a source URL, retrieval time, and SHA-256 record. Manual paths remain available for headless Linux, Docker, remote shells, and automation. For unattended use, supply the ID with `--complex` and add `--download-pdb` explicitly.

This is a retrospective target-specific check. Passing it supports transfer of the recorded search settings; it is not broad validation of the scoring function.

Unless `--out` is supplied explicitly, a completed control study is named `control_<PDB>_<ligand>_<YYYYMMDD_HHMMSS>` (for example, `control_1HVR_XK2_20260811_143025`). A `control_pending_...` folder is used only while the interactive ligand decision and control are unfinished. After completion, the runner applies the final scientific name and updates retained absolute paths so its approved protocol can be resumed later. User-supplied output names are never rewritten.

### Protocol-based screen

Use `docking-universal screen` to dock unknown compounds with a reusable `.duprotocol` bundle. The bundle contains the internal protocol record, locked receptor PDBQT and docking-box configuration, a manifest, and the supporting evidence available for its protocol type. It preserves the previously determined target-specific choices—receptor preparation, selected pocket and docking box, ligand-ensemble policy, exhaustiveness, independent seeds, requested pose count, and energy range—so new compounds use the same settings. Control-validated bundles carry the control status, completion date, control ligand, recovered-pose RMSD and threshold, and control-to-new-run software comparison. Ligand-guided and site-guided bundles remain explicitly exploratory and require user authorization when reused.

In an interactive run, omitting `--protocol` opens a guided choice for a `.duprotocol` bundle or exact bundle path. The bundle is extracted safely, every retained file hash is verified, and its recorded scientific authority is checked before use. The receptor and box hashes must still match. Inputs can be one SDF, a multi-record SDF, or a directory of SDF files.

When `--ligands` is omitted during an interactive desktop run, the guide offers Finder on macOS or Zenity/Tk on Ubuntu for a single SDF. It also retains exact-path and SDF-directory choices for portable or batch use. The same chooser is used when continuing directly from a completed control into unknown-compound screening.

```bash
docking-universal screen \
  --protocol target_control_20260818_120000.duprotocol \
  --ligands compounds.sdf \
  --cluster-rmsd 1.5 \
  --out approved_study
```

This workflow runs the protocol's independent conformers and seeds, retains every pose, clusters poses at **1.5 Å receptor-frame RMSD by default**, and creates detailed outputs for up to three low-energy distinct clusters per compound. `--cluster-rmsd 1.5` makes the default explicit; the GUI uses the same default unless a saved user setting overrides it. If only one cluster is present, its lowest-energy representative is used. The separate 2 Å experimental-pose recovery threshold is unchanged.

### Ligand-free exploratory docking

Use the exploratory pathway when no suitable experimental control ligand exists. The guided workflow prepares the receptor, generates and reviews candidate pockets, and records the selected box before docking.

```bash
docking-universal run exploratory \
  --complex receptor.pdb \
  --ligands compounds.sdf \
  --out exploratory_study
```

The output is permanently marked `EXPLORATORY_NO_CONTROL`. Convergence across seeds can reveal whether the search repeatedly finds similar poses, but it cannot substitute for pose-recovery evidence or experimental validation.

Exploratory protocol creation also supports four explicit region definitions: selected bound ligand, predicted fpocket pocket, selected residue/group, or whole-protein search. A whole-protein search retains fpocket cavity evidence for interpretation but defines its box from prepared-receptor bounds. QuickVina-W is the default engine for exploratory regions, including localized boxes; standard AutoDock Vina is retained for explicit overrides or compatibility requirements. Multiple evidence-backed boxes may be retained during exploratory review, and the selected engine and any override are recorded and carried into later screening.

When a raw ligand-free PDB is supplied, the runner starts with conservative fpocket settings, retains candidate boxes with diagnostics, and chooses the first box deterministically only in unattended mode. It first applies the 0.10 score threshold. If no cavity survives, guided use offers a documented retry at 0.0 while retaining geometry, broad-pocket, and overlap filtering. Protocol creation also offers this retry when fewer than three cavities survive, so a single surviving cavity does not suppress alternative sites from review. Its unattended equivalent performs the retry automatically and records the threshold used. The relaxed threshold expands the hypotheses available for review; it is not evidence of biological relevance.

Immediately before docking, a geometric preflight verifies that the chosen box contains receptor atoms. A mismatch stops before the engine is launched and usually indicates that receptor and box files from different preparations were combined. Passing this check establishes input consistency only, not that the selected region is a biologically valid binding site.

Interactive use lists each generated box with its source pocket and fpocket score. Candidates within 0.05 score units or 20% of the best score (whichever tolerance is larger) are marked as competitive. Before selection, the full exploratory and site-guided `create-protocol` pathways can open one unified PyMOL review containing every retained candidate. Pocket numbers, distinct colors, and descriptive object groups match the terminal list; each group records its fpocket score and priority, while its docking box can be toggled on for inspection without crowding the default view. The interface then waits for the user to select the numbered pocket/box. The automatic cavity-report figure shows all retained pocket hypotheses on the receptor before a separate figure records the chosen box. Use `--review-pockets` to request PyMOL review explicitly, or adjust `--cavity-mode`, `--max-pockets`, and `--center-mode` for a different cavity-search policy.

## Useful options

- `--plan-only` checks inputs, splits a library, and writes reports without docking.
- `--analysis summary` writes pose and cluster tables without representative visuals.
- `--analysis none` retains docking and score outputs only.
- `--representatives 3` controls how many distinct low-energy clusters receive detailed output.
- `--cluster-rmsd 1.5` sets the current workflow's heavy-atom RMSD clustering threshold to 1.5 Å.
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

The PDF report stage automatically generates numbered control and compound figures from retained pose, cluster, receptor, and protocol artifacts. A control-backed screen is divided explicitly into configured protocol, experimental control redocking, and ligand docking sections. The configured-protocol table contains only selectable options: docking program, preparation pH, starting shapes, independent repeats, starting seed and engine-specific search/output controls. Scoring-function identification belongs beside the best docking score in the results: an adjacent column in the overview and an adjacent row in each compound summary identify AD4 or Vina. Energy values remain in kcal/mol. Fixed defaults, derived values and approval/file metadata are not included in protocol options. Full technical details stay in the saved protocol and study files; actual AD4 grid dimensions belong with pocket geometry. The target and ligand labels appear only where they describe the corresponding evidence or docking result. The report shows the approved control figures and the recorded control date, ligand, PASS/REVIEW status, best-sampled RMSD, acceptance threshold, and locked pocket/box. Detailed artifacts and provenance remain in the `.duprotocol` bundle and retained study directory.

New-ligand results include the three top energy-ranked cluster representatives. Ligand chemistry comes from retained SDF files and PLIP calls come from retained XML; the report-figure manifest and per-diagram manifests record these sources and coordinate mapping. Filename-only provenance suffixes such as `_pubchem` and `_pubchem_<CID>` are not presented as part of a ligand's chemical name.

Report headings identify the protein name and annotated fragment, structure accession,
and source species from the exact local PDB/mmCIF annotations. Source species is
not the expression host. Multi-protein structures retain chain-specific identity
and species; unavailable annotations are explicitly marked as not recorded.
New exploratory protocol bundles retain an identity snapshot for later reports.
No internet lookup is performed for these labels, and opening an older study does
not silently rewrite its completed PDF or bundle.

When no bound-ligand control is supplied, the generator writes a distinct **Ligand-Free Cavity and Docking Report** instead of silently omitting validation. Its summary identifies the selected pocket and fpocket druggability score; the retained technical record contains candidate ranks, fpocket score, volume, alpha-sphere count, cavity bounds, box center, dimensions, and volume. Panel A shows ranked decisions; Panel B places retained pocket hypotheses on the receptor. A following figure records the chosen pocket and docking box. These are site-selection records, not pose-recovery validation or evidence that a predicted cavity is biologically correct. A preparation-only run receives cavity results only—no empty ligand, docking, RMSD, 2D interaction, or protocol section. Missing descriptors in older runs are reported as `NA`, never reconstructed or guessed.

Every automatically generated PDF ends with a reproducibility section that assigns each reported quantity or visual to the program that produced it and provides primary references. The section records whether receptor conversion succeeded with strict Meeko, used conservative PDBFixer repair before retrying strict Meeko, required the documented ADFRsuite compatibility fallback, or used an explicitly user-approved removal of unmatched components after safe attempts failed. If removal is approved, the PDF states that the receptor model changed and gives the number and classification of removed residues/components. Removal of any standard amino-acid residue is labeled a high-severity structural modification. A structured `receptor_modification_warning` object—severity, summary, removal counts, and mandatory review/control flags—is stored directly in `protocol.json` and the `.duprotocol` bundle. Protocol selection and every subsequent JSON, Markdown, HTML, and PDF screening report use that recorded warning; older compatible protocols fall back to deriving it from their retained inventory. The exact inventory, approval record, and raw preparation log remain in the study artifacts and portable protocol bundle. PDBFixer is not described as having modified a receptor unless retained preparation artifacts show that it ran. When it ran, the PDF gives a short summary of added and deliberately unbuilt atoms/residues and states whether that repaired intermediate entered the final receptor. Detailed changes remain in the retained `receptor/pdbfixer_audit.json`; portable approved protocols retain the audit as `control/assets/pdbfixer_audit.json`. Every control-backed new run includes a full comparison table for Docking Universal, Python, RDKit, MolScrub, Meeko, PDBFixer, and the selected docking engine. Matching reports state `Checked: no software version differences detected`; differences or unavailable versions are identified row by row. Additional analysis/reporting tools are listed separately. The same information and preparation record are written to `report/software_versions_and_references.json`.

At completion, the terminal prints the exact descriptive PDF path. The filename records the target, ligand scope, date, and report type. One to three ligand names are included directly; larger libraries use a bounded count such as `15-ligands`, while the full names remain inside the report and machine summary. If optional PDF dependencies or figure generation fail, the workflow retains its HTML/Markdown/JSON reports and prints an explicit warning with the PDF-generation error rather than silently omitting the PDF.

For multi-record SDF libraries, compound labels always come from each individual SDF record rather than the shared source filename. The PDF is published atomically only after every approved-style A/B panel and SDF-aware interaction diagram has been rebuilt successfully; a figure-generation failure cannot silently replace the approved report with raw fallback renders.

Each compound section also includes a compact 3D snapshot figure for up to the three lowest-energy distinct cluster representatives. The snapshots are labeled by energy rank, cluster ID, and the selected engine's score, with red/blue/gold borders matching the A/B cluster figure. They supplement rather than replace the overlaid A/B comparison and the chemically typed 2D interaction diagrams. When only one cluster exists, only its lowest-energy representative is shown at a readable size.

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

## Understanding Finalize protocol

The Finalize protocol screen also serves as a teaching step: every setting has a
visible explanation beside its control, including runtime/workload tradeoffs.
**Settings guide…** and each **?** button open a reusable, modeless guide showing
current values and fuller definitions. Reading help does not change settings or
authorize anything. Defaults are starting values, not target-specific validation.
The live shapes × repeats hint is per chemical state and approved site; it is not
the full library job count or a runtime prediction. Review the actual workload in
the later screening step. Finalization packages the approved recipe; it does not
dock new ligands.

## Saving custom GUI images

Use **Save image…** in the main workspace or the 2D/3D review window. Available
choices include the current customized PyMOL view, the selected 2D diagram at its
original pixel resolution, and a clean side-by-side 2D/3D panel. The main workspace
also saves the selected retained report figure or pocket-ranking plot. Full
PyMOL has the same **Save image…** menu for its current 3D view.

Adjust orientation, zoom, residue labels, cartoon and contact visibility before
saving. The quick OpenGL 3D PNG uses the current native viewport resolution and appearance,
without Qt controls or PyMOL's object sidebar; active native selection markers
remain part of that appearance, so deselect them first if unwanted. Saving the
2D diagram uses its retained original resolution regardless of Fit/zoom and
omits clickable GUI outlines. Clean paired panels include the experimental or
docked coordinate basis and the color key for contact types currently shown in
3D; hiding a 3D contact type does not alter the retained 2D diagram.

Choose **3D PyMOL view — ray-traced PNG** for optional CPU ray rendering instead
of the quick OpenGL image. The paired window also offers **2D / 3D panel —
ray-traced 3D**; full PyMOL offers **Save image… → Ray-traced 3D PNG…**. Ray rendering
preserves current scene choices but may look different because it uses ray-traced
lighting rather than OpenGL. Labels floated in front of the OpenGL view can be
occluded by geometry in a ray image; inspect the saved result. It uses native viewport dimensions, not a larger
requested resolution. A busy dialog stays responsive and allows cancellation;
cancellation leaves the destination unchanged. The same live engine is used.

These local PNG exports contain context metadata and are presentation derivatives,
not newly generated scientific reports. They do not rerun docking/PLIP, modify
coordinates, approve a selection, or replace retained source files. Native-view
export does not add arbitrary output dimensions or vector formats.
