# Validation status

Docking Universal 0.4.0 is a research preview. Validation distinguishes software-path testing from scientific validation: a command completing successfully does not establish that a predicted pose or cavity is biologically correct.

## Automated option coverage

The test suite exercises:

- all three guided study pathways: bound-ligand control, approved-protocol screening, and ligand-free exploration;
- all six initial control strategies and every guided/manual calibration-escalation route;
- default and custom ligand ensembles, including MMFF94, MMFF94s, UFF, pH, conformer count, random seed, RMSD pruning, and tautomer selection;
- macOS Finder, exact-file, directory/batch, and portable non-macOS input routing;
- all approved-protocol resume routes and multiple-protocol disambiguation;
- each prepared pocket selection plus single-pocket, competitive-pocket, and no-PyMOL review choices;
- docking-box validation, rejected choices, unapproved-protocol blocking, result parsing, and all command help entry points;
- primary AutoDock Vina command/output routing with a deterministic mock engine.

Run the automated suite with:

```bash
make test
```

The same checks and the real-tool suites are available through the public interface:

```bash
./bin/docking-universal validate quick
./bin/docking-universal validate integration
./bin/docking-universal validate release --background
```

The release suite is intentionally slow. It first repeats the integration probes, then runs the 1HVR/XK2 multi-seed pose-recovery control, a protocol-locked Rilpivirine screen, and a ligand-free 2R8N/Indinavir exploratory study. Every invocation creates a new timestamped directory in `validation_runs/` and writes `status.json`; `PASSED` means the expected software stages and artifacts completed, not that every predicted pose is biologically correct.

## Real-tool smoke checks

The maintained macOS Apple Silicon environment has been checked with fpocket, Meeko, MolScrub, RDKit, Open Babel, PLIP, PyMOL Open-Source, and AutoDock Vina 1.2.7. Real fixture-based checks cover:

- ligand-centered 1HVR/XK2 receptor preparation and box generation;
- 2R8N ligand-free preparation in conservative, expanded, and permissive fpocket modes;
- deepest-pocket and centroid box centers, including whole-protein and per-chain centroid scope;
- automatic documented fallback from fpocket score threshold 0.10 to 0.0 when no candidate passes, while retaining geometry and overlap filters;
- a two-compound approved-protocol screen plan with locked-input hash verification;
- MMFF94, MMFF94s, and UFF ensemble generation with custom pH, seeds, and tautomer policies;
- automatic HTML, JSON, Markdown, and PDF report generation, followed by rendered-page inspection.

Completed example studies retain evidence for actual multi-seed Vina redocking, ligand-free cavity analysis, unknown-compound docking, pose clustering, PyMOL sessions, interaction diagrams, and final reports.

## Scope and limitations

The suite verifies option routing, input validation, provenance, expected artifacts, and representative real-tool workflows. It does not rerun every Cartesian combination of protein, compound, seed, conformer, cavity mode, and search depth; doing so would add substantial computation without independently validating the scientific model. Docking remains rigid-receptor modeling, Vina scores are ranking estimates rather than measured binding free energies, and experimental validation remains necessary.
