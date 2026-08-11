# Scientific use and validation

Docking Universal is intended for research workflows where intermediate decisions must remain inspectable. It automates transformations and bookkeeping; it does not remove the need for structural review.

For the complete control, calibrated-screen, and ligand-free exploratory paths, begin with the [guided study workflow](guided-workflow.md).

## Input assumptions

- Protein structures use fixed-width PDB coordinate records.
- Residue names, chain identifiers, and atom naming are sufficiently conventional for the selected external tools.
- Compound SDF records contain chemically meaningful bond orders; generated 3D geometry is an input preparation step, not experimental conformational evidence.
- PDBQT files passed to result collection contain Vina-style `MODEL`, `REMARK VINA RESULT:`, and `ENDMDL` records.

## Recommended validation record

For a scientific release, retain:

1. original input checksums and provenance;
2. Docking Universal version and external-tool versions;
3. the generated run manifest/log;
4. receptor and compound-preparation outputs;
5. pocket diagnostics and the selected box configuration;
6. representative PyMOL and 2D images used for review;
7. any manual acceptance/rejection rationale.
8. the versioned control protocol, its receptor/box hashes, software versions, per-seed outcomes, and any escalation history;

## Interpretation boundaries

- Bound-control docking conformers must be independent of both CCD ideal coordinates and crystallographic ligand coordinates. Docking Universal retains only the coordinate-free chemical graph and withholds the experimental pose for post-docking RMSD evaluation. This prevents conformational or pose leakage from making a redocking control appear easier than it is.

- Pocket score and protein-centroid distance are prioritization heuristics.
- A ligand centroid is a geometric anchor, not a statement about optimal docking search space.
- Generic 2D depictions communicate molecular connectivity and layout; they do not classify interactions.
- PLIP output reflects PLIP's geometric definitions and the supplied coordinate/protonation state.
- Docking scores are engine outputs and should not be presented as measured binding free energies.
- A successful redocking control indicates that a known pose was sampled and ranked reproducibly for one target/preparation. It does not prove prospective pose or affinity accuracy.
- Search effort should be escalated by a recorded tier and stopped for input review after repeated systematic failure, rather than tuned indefinitely to one reference pose.

## Reproducibility

The package deliberately keeps configuration files, logs, tabular diagnostics, and manifests close to generated structures. The known working direct dependency set is recorded in `environment.yml`. For strict reproducibility, also archive the exact solved environment and platform because preparation and perception behavior can vary between tool builds and releases.

Approved protocol records are target-locked: changing the receptor PDBQT or box configuration invalidates the stored hashes and requires a new control. Unknown compounds receive new pH-aware conformers; crystallographic coordinates are never transferred into their starting ensembles.
