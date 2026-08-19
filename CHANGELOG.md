# Changelog

## 0.5.0 — 2026-08-18

- Added active-Conda installation and self-contained installed validation.
- Added clearer preparation/protocol routing and guided low-level docking selection.
- Added portable, hash-verified `.duprotocol` bundles so a previously determined and control-approved target protocol - including receptor preparation, selected pocket/docking box, ligand-ensemble policy, exhaustiveness, seeds, pose count, and energy range - can be applied unchanged to new sets of compounds.
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
- Verified a ligand-free exploratory smoke workflow and a distinct-compound approved-protocol workflow on the macOS arm64 reference system.
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
- Added Meeko/Vina macrocycle preparation and fixed portable PyMOL PML loading on Apple silicon.

## 0.2.0 — 2026-08-08

- Consolidated receptor preparation, ligand-library preparation, standalone pocket coordinates, batch execution, score collection, and PLIP interaction scenes behind one command.
- Added portable dependency discovery in place of workstation-specific paths.
- Added headless PyMOL PNG rendering for existing scenes and coordinate files.
- Added generic RDKit/Open Babel 2D depiction for existing molecular coordinates.
- Corrected collected Vina affinity units to kcal/mol.
- Added scientific-method documentation, example diagnostics, tests, citation metadata, and a GitHub Pages project site.

## 0.1.0

- Initial packaging of the latest auditable receptor and pocket-preparation workflow.
