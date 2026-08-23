# Package provenance map

Docking Universal consolidates distinct structural-docking utilities found in the original Docking workspace and the author's local scripts directory.

| Packaged component | Source lineage | Consolidation decision |
| --- | --- | --- |
| `docking-universal run` | New study-orchestration layer | Guides complete control, approved-screen, or exploratory studies; splits libraries, isolates failures, and writes consolidated reports |
| `docking-universal prepare` | `prepare_receptor_and_conf_v1.35.13_surface_local_pockets.sh` | Latest receptor, ligand-detection, pocket-diagnostics, box, and PyMOL-scene workflow; exposed as the supported preparation command |
| `docking-universal ligands` | `prepare_ligands_from_sdf_with_smiles.sh` | Preserves SDF splitting, 3D optimization, PDBQT conversion, and metadata insertion; removes the machine-specific executable path |
| `docking-universal pockets` | Receptor/pocket preparation plus consolidated reporting | Runs an independent ligand-free cavity study, retains ranked coordinates and boxes, and writes cavity-only PDF, HTML, Markdown, and JSON reports; the smaller historical generator remains an internal compatibility stage |
| `docking-universal dock` | `dock_all.sh` | Replaces hard-coded structures and directories with one checked AutoDock Vina interface and a run manifest |
| `docking-universal control` / `calibrate` | Bound-ligand scripts plus new calibration layer | Runs the complete guided control with consolidated reports; verifies a selected crystal ligand, creates unbiased ensembles, runs tiered seed/conformer controls, and writes a reusable target-locked protocol when approved |
| `docking-universal screen` | Study orchestration plus protocol-transfer layer | Runs a complete reported compound screen, rejects unapproved or altered protocols, and applies the locked target-specific settings to the selected compound library |
| `docking-universal cluster-poses` | New cross-run analysis layer | Uses symmetry-aware receptor-frame RMSD to group poses across seeds/conformers and select energy-ranked representatives |
| `docking-universal collect` | `autodock_vina_pdbqt_to_csv.py` | Removes the pandas dependency, corrects affinity units to kcal/mol, and adds a command-line interface |
| `docking-universal interactions` | `plip_local_all_in_one.py` from the local scripts workspace | Uses the more complete local PLIP XML/PyMOL implementation and preserves the interaction manifest |
| `docking-universal render3d` | New consolidation layer | Renders existing PML/session/coordinate outputs with headless PyMOL |
| `docking-universal depict2d` | New consolidation layer | Creates generic 2D PNG/SVG depictions from existing coordinate files using RDKit or Open Babel |

Older receptor-script revisions are treated as development history, not separate public commands. Their useful behavior is represented by the latest supported workflow; known older contradictions and hard-coded paths are not shipped as active interfaces.

The supported preparation commands were further reworked for packaging: scientific executables can be supplied through options or environment variables, ligand chemistry operations use a space-safe temporary workspace, metadata insertion is cross-platform, input/mode validation is explicit, and outputs can be directed independently of the source workspace.

Generated fpocket helper scripts, completed run folders, large ligand libraries, and structure datasets are not vendored into the package. Example diagnostic tables and a representative visualization are included for documentation.
