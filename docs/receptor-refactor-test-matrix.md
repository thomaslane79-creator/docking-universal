# Receptor preparation refactor test matrix

This matrix is the gate for splitting and later migrating the receptor
preparation workflow. A green general test suite is not sufficient: the test
listed for a stage must exist before that stage is changed.

| Current behavior | Characterization test | Status before further extraction |
|---|---|---|
| Reject invalid input before prompts or artifacts | `test_receptor_input_validation.sh` | Covered |
| Strict Meeko succeeds without repair | `test_receptor_preparation_routes.sh` | Covered |
| Strict Meeko failure followed by PDBFixer and strict Meeko | `test_receptor_preparation_routes.sh` | Covered |
| Depositor `SSBOND` produces targeted CYX retry | `test_receptor_preparation_routes.sh` | Covered |
| Ambiguous histidine requires a user-selected template | `test_receptor_preparation_routes.sh` | Covered through a PTY |
| Linked deposited component permits the narrow ADFRsuite fallback | `test_receptor_preparation_routes.sh` | Covered |
| Component removal occurs only after explicit approval | `test_receptor_preparation_routes.sh` | Covered through a PTY |
| Approved removal writes residue manifest and approval record | `test_receptor_preparation_routes.sh` | Covered |
| MODRES/CCD audit helper records template resolution | `test_ccd_audit.py` | Covered at helper level |
| PDBFixer writes its conservative repair audit | `test_pdbfixer_preclean.py` | Covered at helper level |
| Preparation route and removal warnings propagate to protocols | `test_protocol_types.py` | Covered |
| Preparation route and removal warnings propagate to reports | `test_report_cavity.py` | Covered |
| Chain summary and guidance helpers | `test_prepare_support.sh` | Covered |
| fpocket count, geometry threshold, and diagnostic summary helpers | `test_prepare_support.sh` | Covered |
| Receptor input filtering retains supported metals and linked components, normalizes MODRES polymer records, and excludes waters and ordinary ligands | `test_receptor_input_filter.sh` | Covered and extracted |
| Failure diagnosis distinguishes heme/cofactor, nucleic acid, unsupported modified amino acid, alternate-location, incomplete-residue, and unclassified failures | `test_receptor_failure_diagnosis.sh` | Covered and extracted |
| Conservative-versus-expanded fpocket selection uses reasonable localized-pocket counts and preserves modified-mode ties | `test_fpocket_selection.sh` | Covered and extracted |
| Ligand-local fpocket merge applies VDW overlap and centroid-distance filtering, honors OFF, and rejects a missing ligand | `test_ligand_pocket_merge.sh` | Covered and extracted; first-record indexing defect corrected in isolation |
| Pocket eligibility records missing-score, low-score, broad-geometry, and accepted decisions, with explicit strict/review behavior | `test_fpocket_candidate_classification.sh` | Covered and extracted |
| Ligand-free pocket ranking applies centroid weighting, overlap suppression, maximum retention, and a complete decision audit | `test_fpocket_ranked_selection.sh` | Covered and extracted |
| Docking center, visible box corners/connectivity, and Vina configuration share identical coordinates and dimensions | `test_docking_box_artifacts.sh` | Covered and extracted |
| Adjacent pocket extension includes only non-core candidates inside the strict touching-distance boundary | `test_adjacent_pocket_extension.sh` | Covered and extracted |
| PyMOL review scenes preserve selected identity, labels, representations, box visibility, optional layers, and disabled reference ligands | `test_pymol_review_scene.sh` | Covered and extracted |
| Preparation summary is a presentation-only renderer and successful preparation retains the complete review/reuse artifact inventory | `test_receptor_preparation_routes.sh` | Covered and extracted |
| Strict and explicitly permissive Meeko commands and the primary ADFRsuite command retain visible, auditable option boundaries | `test_receptor_command_builders.sh` | Covered and extracted |
| Depositor SSBOND records alone produce CYX assignments, and approved removal produces a sorted residue-level manifest | `test_receptor_structural_audits.sh` | Covered and extracted |
| External preparation attempts retain complete logs and artifact-required routes reject empty outputs | `test_receptor_attempt_runner.sh` | Covered and extracted |
| Ligand detection excludes solvent/ions/MODRES polymer chemistry, preserves reference files, and computes ligand/protein centroids deterministically | `test_ligand_detection_helpers.sh` | Covered and extracted |
| Ligand-guided preparation uses the complete selected ligand to define its docking center | `test_receptor_preparation_routes.sh` | Covered; first-record indexing defect corrected in isolation |
| fpocket execution records conservative versus explicit probe modes and normalizes each run to a declared output directory | `test_fpocket_runner.sh` | Covered and extracted |
| Reusable functions are separated into interaction, receptor, ligand, pocket, and artifact modules in source and installed copies | `test_install.sh` and focused helper tests | Covered and extracted |
| Installed copy contains sourced preparation libraries | `test_install.sh` | Covered |

## Tests required before extracting later stages

These remain mandatory but do not block splitting the already covered receptor
backend route selector:

- target-adaptive fallback paths outside the receptor-preparation monolith.

No listed stage should be moved or translated to Python until its missing
fixture has been added against the current implementation. Every extraction is
followed by its focused characterization test, the full fast suite, and the
relevant real-tool integration run.
