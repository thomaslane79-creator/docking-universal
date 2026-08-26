# Validation status

Docking Universal 0.6.4 is a research preview. Validation distinguishes software-path testing from scientific validation: a command completing successfully does not establish that a predicted pose or cavity is biologically correct.

## Automated option coverage

The test suite exercises:

- all three guided study pathways: bound-ligand control, approved-protocol screening, and ligand-free exploration;
- all six initial control strategies and every guided/manual calibration-escalation route;
- default and custom ligand ensembles, including MMFF94, MMFF94s, UFF, pH, conformer count, random seed, RMSD pruning, and tautomer selection;
- macOS Finder, Ubuntu Zenity/Tk, exact-file, directory/batch, and headless input routing;
- all approved-protocol resume routes and multiple-protocol disambiguation;
- each prepared pocket selection plus single-pocket, competitive-pocket, and no-PyMOL review choices;
- docking-box validation, rejected choices, unapproved-protocol blocking, result parsing, and all command help entry points;
- AutoDock Vina and QuickVina-W command/output routing with deterministic mock engines.

Run the automated suite with:

```bash
make test
```

The current automated suite is exercised in GitHub Actions on current Ubuntu and macOS runners after creating the declared Conda environment. That supports portability at the software-test level. Because compiled scientific tools can differ across platforms, run integration or release validation on the target workstation before production use.

The [complete two-cohort, 100-public-PDB receptor-preparation record](receptor-preparation-validation-2026-08-21.md) documents tested preparation paths, known limitations, public entry IDs, and retained evidence for the general and covalent-linkage stress-test cohorts. The accompanying [86-report validation-evidence bundle](https://github.com/thomaslane79-creator/docking-universal/releases/download/v0.6.4/docking-universal-100-pdb-validation-evidence-86-reports.zip) contains the 79 original reports—including the guided 5NBX histidine-template case—six complete v0.6.4 reports after the `LINK`-filter correction, the audited 5KRH explicit-removal report, and machine-readable summaries. Fourteen attempted structures remain without complete reports; a single clean v0.6.4 rerun of all 100 remains pending.

The same checks and the real-tool suites are available through the public interface:

```bash
docking-universal validate quick
docking-universal validate integration
docking-universal validate release --background
```

The release suite is intentionally slow. It first repeats the integration probes, then runs the 1HVR/XK2 multi-seed pose-recovery control, a protocol-locked Rilpivirine screen, and a ligand-free 2R8N/Indinavir exploratory study. Every invocation creates a new timestamped directory in `validation_runs/` and writes `status.json`; `PASSED` means the expected software stages and artifacts completed, not that every predicted pose is biologically correct.

## Real-tool smoke checks

The maintained scientific environment has been checked with fpocket, Meeko, PDBFixer 1.11, MolScrub, RDKit, Open Babel, PLIP, PyMOL Open-Source, AutoDock Vina 1.2.7, and QuickVina-W 1.1 from the qvina 2.1.0 Conda package. Real fixture-based checks cover:

- ligand-centered 1HVR/XK2 receptor preparation and box generation;
- strict-Meeko-first receptor conversion, conservative PDBFixer fallback auditing, and explicit user-approved component-removal behavior after safe attempts fail;
- reconciled receptor-preparation robustness across 50 public PDB structures: 46/50 produced a PDBQT under the current safety policy, including two that required explicit user-approved removal; four stopped rather than silently deleting or guessing unsupported chemistry;
- a separate 50-structure linked-chemistry stress panel in which 39/50 produced PDBQTs and the remaining documented stops or timeouts were retained rather than converted into silent successes;
- unchanged prepared PDBQT hashes for the existing 1HVR and 2R8N examples when strict Meeko succeeds, plus matching selected boxes and downstream docking results;
- 2R8N ligand-free preparation in conservative, expanded, and permissive fpocket modes;
- deepest-pocket and centroid box centers, including whole-protein and per-chain centroid scope;
- automatic documented fallback from fpocket score threshold 0.10 to 0.0 when no candidate passes, while retaining geometry and overlap filters;
- a two-compound approved-protocol screen plan with locked-input hash verification;
- MMFF94, MMFF94s, and UFF ensemble generation with custom pH, seeds, and tautomer policies;
- automatic HTML, JSON, Markdown, and PDF report generation, followed by rendered-page inspection.

Completed example studies retain evidence for actual multi-seed Vina redocking, ligand-free cavity analysis, unknown-compound docking, pose clustering, PyMOL sessions, interaction diagrams, and final reports.

The integration suite builds a clearly labelled synthetic passing protocol to test fail-closed software gates, input hashes, planning, and report plumbing. It is not scientific pose-recovery evidence. The longer release suite produces the genuine bound-ligand control used for its subsequent screen; only that computed control path can establish target-specific protocol approval.

## Scope and limitations

The suite verifies option routing, input validation, provenance, expected artifacts, and representative real-tool workflows. It does not rerun every Cartesian combination of protein, compound, seed, conformer, cavity mode, and search depth; doing so would add substantial computation without independently validating the scientific model. Docking remains rigid-receptor modeling, Vina scores are ranking estimates rather than measured binding free energies, and experimental validation remains necessary.
