# Changelog

## Unreleased

- Made batch ligand preparation and docking return failure when any compound fails while retaining and reporting every successful compound output.
- Added early protein-PDB validation and receptor/docking-box geometric preflight checks so invalid or mismatched inputs stop with a specific explanation before an engine is launched.
- Made explicit engine requests fail on conflict with a protocol's locked engine instead of silently ignoring the request.
- Added resumable Conda installation retries for transient network failures and clearer guidance after retry exhaustion.
- Added real Vina and QuickVina-W integration validation to Ubuntu and macOS CI, and separated installed-copy `validate smoke` checks from the full source-only `validate quick` suite.
- Began the staged preparation refactor by moving protein-PDB validation and receptor/box geometry checks into a unit-tested Python structure module; also consolidated common audited subprocess execution, narrowed nonessential broad exception handling, and added focused robustness regressions.
- Added a real protocol-restart equivalence stage that runs the same ligand twice with one locked receptor, box, engine, ensemble policy, and seed list, then requires identical prepared ligand files, per-seed poses, scores, and cluster assignments after excluding paths and timestamps.

## 0.6.5 — 2026-08-27

**Patch release focus:** QuickVina-W broad-search support and explicit docking-region selection.

- Added bound-ligand, predicted-pocket, selected-residue, and whole-protein region definitions with recorded box geometry and automatic engine recommendations.
- Added QuickVina-W selection for broad or whole-protein searches, including locked engine provenance in protocol bundles and complete screening reports.
- Fixed installed-copy packaging for the new region-selection helper and complete software-version provenance for newly created protocols.
- Added real whole-protein screening coverage: 225 poses across five seeds, clustering, PLIP, PyMOL rendering, and PDF generation.

- Added QuickVina-W as a second Vina-family docking engine across low-level docking, bound-ligand calibration, exploratory studies, reusable protocols, protocol-locked screening, pose clustering, manifests, and scientific reports. Engine choice is retained as part of the protocol and cannot be silently changed during reuse.
- Added an isolated `docking-universal-qvinaw` Conda environment, installer routing, cross-platform environment checks, mocked command/provenance tests, and a real QuickVina-W integration smoke stage.
- Made QuickVina-W ligand preparation explicitly rigidify macrocycles instead of emitting newer Meeko flexible-macrocycle pseudo-atoms that its older Vina-derived implementation may not support.

## 0.6.4 — 2026-08-25

**Patch release focus:** receptor-model changes are now explicit, durable, and propagated, and ligand-free pocket review is visually unambiguous before selection.

- Corrected receptor filtering so coordination waters and unsupported single-atom ions are not retained merely because they appear in a deposited `LINK` record; multi-atom linked components remain eligible for the narrow compatibility fallback.
- Made final component removal an explicitly audited, user-approved route. Reports now state that the receptor model changed, give the number of removed residues/components, and retain the exact removal inventory and raw preparation log in the study artifacts and portable protocol bundle.
- Classified removed standard amino-acid residues separately from other components and propagate a high-severity receptor-model warning through protocol selection and every subsequent JSON, Markdown, HTML, and PDF screening report. The approval prompt now displays the current failure diagnosis and warns that complete protein/peptide residues may be removed.
- Rechecked six receptors affected by the filtering distinction (`1GYN`, `5K8R`, `3ET8`, `1P5S`, `4ER8`, and `2NSY`) and added a real 5KRH report demonstrating the approved-removal disclosure. These are focused regression checks, not a new biological-validation claim.
- Replaced ambiguous separate pocket-review windows with one labeled, color-matched PyMOL scene containing all retained fpocket candidates. Full exploratory runs and site-guided protocol creation now use the same scored review and numbered box selection; the terminal names each matching color, and individual boxes remain available as uncluttered toggles.

## 0.6.3 — 2026-08-24

**Defining release change:** Docking Universal now organizes its report-producing workflows around creating, reviewing, reusing, and screening with explicit Docking Universal protocols, with confirmed graphical operation on both Ubuntu and macOS.

- Added `docking-universal create-protocol`, a guided workflow that prepares the receptor and docking region and produces both a scientific PDF protocol report and a reusable Docking Universal `.duprotocol` bundle.
- Added three explicit protocol types: control-validated, ligand-guided exploratory, and site-guided exploratory. Their evidence basis, screening authority, creation time, receptor preparation, docking box, and software provenance are retained in the protocol record and presented during later selection.
- Allowed exploratory protocols to be deliberately reused for exploratory screening without implying pose-recovery validation. Interactive use requires an explicit user decision; unattended use requires an explicit command-line authorization.
- Made `docking-universal screen` the direct guided command for docking one or multiple new compounds with a required Docking Universal protocol. It displays the selected protocol before requesting ligands and reuses its locked receptor, docking box, and search settings.
- Extended `.duprotocol` bundles to retain protocol-type-specific evidence, the source receptor when available, protocol/cavity/box report assets, cryptographic file verification, and compatibility with earlier approved Docking Universal controls. `.duprotocol` remains a Docking Universal-specific workflow format rather than a general input format for other docking software.
- Updated scientific reports to distinguish protocols created in the current study from previously created protocols, distinguish control-validated from exploratory evidence, carry forward retained receptor-preparation and control evidence when applicable, and avoid describing a supplied prepared receptor as merely “not recorded.”
- Added one graphical file-and-folder selection layer across the guided workflows and low-level `dock` command: Zenity/GTK on Ubuntu, Tk as an Ubuntu fallback, Finder on macOS, and exact-path prompts for headless or scripted use.
- Reorganized command help and the README around the three report-producing workflows, the simple repository installer, and standalone receptor/ligand PDBQT preparation for other compatible software. The documentation now clearly distinguishes generally usable prepared files from Docking Universal-only `.duprotocol` bundles.
- Expanded protocol records with creation timestamps and detected Docking Universal, Python, RDKit, MolScrub, Meeko, PDBFixer, and docking-engine provenance where available.
- Added protocol-type, graphical-chooser, installed-command, and cross-platform routing tests. The complete local suite contains 83 tests, and the branch checks pass on current Ubuntu and macOS GitHub runners.
- Added installed-copy checks for the user-facing installer, host-side Conda launcher, `create-protocol` command, and installer shell syntax. Normal use continues to require no manual Conda activation.
- Hardened unattended validation: background runs now avoid the PID-file startup race, and the host launcher detaches the complete Conda invocation so validation can continue after the initiating shell returns.
- Restored the documented `--ligand-id` control option as a compatible alias, updated release validation for the current orchestrated control directory, and added regression coverage for both paths.
- Corrected control-only PDFs so they do not invent an empty ligand-docking section from the study-folder name; the report now proceeds directly from control evidence to reproducibility and references.
- Made public environment documentation platform-neutral while retaining Ubuntu-first and macOS CI coverage plus explicit platform-specific lock snapshots.

## 0.6.0 — 2026-08-21

**Defining release change:** A material receptor-preparation compatibility expansion enables many more real deposited PDB structures to proceed to Vina-style PDBQT workflows, backed by a public 100-PDB validation record.

- Updated Meeko to 0.7.1 and added an iterative, least-invasive receptor-preparation sequence: strict Meeko first; conservative PDBFixer repair only after rejection; diagnosed disulfide/histidine handling only when needed; then a narrow ADFRsuite fallback for Meeko-diagnosed linked deposited chemistry. Together these routes substantially broaden preparation coverage, including many linked small-molecule adducts without applying unnecessary model-changing fixes.
- Removed automatic unmatched-component deletion. When safe routes fail, component removal is a final explicit user choice; its decision and logs are retained and it cannot itself approve a screening protocol.
- Added a complete two-cohort, 100-public-PDB receptor-preparation validation record, including manifests, outcomes, safeguards, known limitations, and links to retained automated evidence.
- Added concise public README and GitHub repository metadata describing the validation scope and limitations.

See the [receptor-preparation validation record](docs/receptor-preparation-validation-2026-08-21.md) for complete outcomes and limitations.

## 0.5.0 — 2026-08-18

**Defining release change:** A previously determined, control-approved target protocol can now be packaged and reused unchanged to dock new sets of compounds.

- Added portable, hash-verified `.duprotocol` bundles containing receptor preparation, the selected pocket/docking box, ligand-ensemble policy, exhaustiveness, seeds, pose count, energy range, software provenance, hashes, and retained control evidence. Later compound-set reports carry forward a synopsis of that protocol and its control-validation result.
- Added active-Conda installation and self-contained installed validation.
- Added clearer preparation/protocol routing and guided low-level docking selection.
- Reworked control-backed, new-ligand, and ligand-free cavity reports for clearer scientific roles and concise defaults.
- Added an always-present control-to-new-run scientific software comparison table.
- Expanded unit, CLI, integration, release, installed-command, and visual PDF validation.
- Added a scientist-focused GitHub essentials PDF and linked it from the README and installation manual.
- Corrected Linux CI coverage for the mocked Finder interface and installed the pinned RDKit dependency used by screening tests.

See [Changes completed on 2026-08-18](docs/changes-2026-08-18.md) for the complete inventory.

## 0.4.0 — 2026-08-09

- Narrowed the research preview to AutoDock Vina only. The earlier experimental smina comparison path and dependency were removed from the interface; a new backend may be evaluated in a future release.
- Added `run`, a guided study orchestrator with bound-control, approved-screen, and explicitly uncalibrated exploratory pathways.
- Added multi-record SDF and SDF-directory handling with collision-safe per-compound folders, retained partial outputs, failure records, and optional stop-on-error behavior.
- Added plan-only validation plus consolidated CSV, JSON, Markdown, and HTML study reports with separate scientific and completion statuses.
- Integrated five-seed/conformer docking, cross-run clustering, three representative poses, PyMOL PNG/PSE output, and PLIP interaction analysis into the default completed-compound path.
- Added headless PNG/PSE rendering of each selected PLIP interaction scene.
- Verified a ligand-free exploratory smoke workflow and a distinct-compound approved-protocol workflow through retained integration runs.
- Added explicit guided incremental versus manual calibration strategies. Guided mode records escalation history and stops at the first reproducible passing tier; manual mode makes no claim about cheaper settings.
- Calibration now records tier elapsed time and estimates later-tier time from completed jobs before confirmation.

## 0.3.0 — 2026-08-08

- Connected the default bound-ligand `control` command to independent ensemble calibration; the historical single-conformer path now requires an explicit legacy flag.
- Added quick, repeatability, broader-search, conformer-expansion, and robust calibration tiers with job-count feedback and confirmed interactive escalation.
- Added stable v1 protocol records that lock engine-specific preparation/search settings plus receptor and box SHA-256 hashes.
- Added `screen` for one-compound, protocol-gated unknown docking; unapproved, incomplete, altered, or engine-incompatible protocols fail closed.
- Added selected top-ranked/best-sampled PyMOL PNG/PSE outputs and PLIP interaction scenes to ensemble calibration.
- Expanded CLI tests for five-seed protocol approval, multi-ligand docking, and rejection of unapproved screening records.
- Annotated shell and Python entry points with scientific purpose, assumptions, boundaries, and non-obvious engine behavior.
- Added cross-seed/conformer Butina pose clustering, energy-ranked representatives, seed/conformer support, and three-representative PyMOL/PLIP analysis as the screening default.
- Added plain-language clustering documentation and expanded command help describing option effects, output meanings, and scientific limitations.
- Added pinned MolScrub 0.2.2 for independent pH-aware chemical-state and conformer preparation.
- Added reproducible docking seeds and retained-pose energy-range controls to the engine interface and manifests.
- Added a guided bound-ligand redocking control with exact ligand-instance selection, automatic experimental-coordinate SDF generation, strict CCD/template verification, and an audited manual override.
- Added symmetry-aware no-fit pose RMSD comparison, per-engine control summaries, and crystal-versus-docked PyMOL overlays.
- Added crystal-versus-all-poses PyMOL sessions with individually toggleable, score/RMSD-named pose objects and explicit top-score/best-RMSD tags.
- Made the default control comparison a scene-based pose browser: one pose at a time, labeled energy/RMSD status, and labeled receptor residues within 5 Å; arrow keys cycle poses.
- Added configurable pose counts to docking runs and made the active Conda environment's Python interpreter explicit.
- Added an optional isolated AutoDock Vina 1.2.7 environment and automatic engine discovery.
- Recorded docking-engine version and executable source in run manifests.
- Added native Meeko ligand and receptor preparation backends alongside ADFRsuite compatibility.
- Parsed AutoDock Vina score and RMSD-bound records into tidy output.
- Corrected receptor metal filtering to use the fixed-width PDB element column instead of matching metal symbols anywhere in a `HETATM` record.
- Excluded `MODRES`-declared polymer modifications from bound-ligand candidates.
- Added fpocket 4.2 report/coordinate compatibility and strict positive box-dimension checks.
- Added Meeko/Vina macrocycle preparation and fixed portable PyMOL PML loading across supported platforms.

## 0.2.0 — 2026-08-08

- Consolidated receptor preparation, ligand-library preparation, standalone pocket coordinates, batch execution, score collection, and PLIP interaction scenes behind one command.
- Added portable dependency discovery in place of workstation-specific paths.
- Added headless PyMOL PNG rendering for existing scenes and coordinate files.
- Added generic RDKit/Open Babel 2D depiction for existing molecular coordinates.
- Corrected collected Vina affinity units to kcal/mol.
- Added scientific-method documentation, example diagnostics, tests, citation metadata, and a GitHub Pages project site.

## 0.1.0

- Initial packaging of the latest auditable receptor and pocket-preparation workflow.
