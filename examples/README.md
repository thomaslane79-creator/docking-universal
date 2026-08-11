# Tutorials

This folder contains only copy-ready, public-input tutorials. They show the
commands and decision points a user would use; no wrapper scripts hide the
workflow.

- `tutorials/01_bound_ligand/`: retrospective 1HVR/XK2 pose-recovery control.
- `tutorials/02_ligand_free_cavity/`: 2R8N cavity-search workflow with an
  external compound SDF.

Each tutorial keeps its public inputs beside its instructions. A locally
generated `study/` directory is intentionally ignored by Git. Curated results
from a completed run are kept separately under
`tests/expected_runs/`, so they cannot be mistaken for an input or required
output of a fresh tutorial run.
