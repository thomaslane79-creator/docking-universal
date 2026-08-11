# Pose clustering and representative analysis

Docking produces alternative hypotheses, not one experimentally established answer. Multiple seeds and starting conformers may repeatedly find the same binding mode, or they may produce several distinct placements and ligand shapes. Docking Universal clusters these results so repeated poses are summarized without deleting the original output.

## What is clustered

The clustering distance is symmetry-aware heavy-atom RMSD measured directly in the fixed receptor coordinate frame. It includes both:

- ligand position and orientation within the pocket;
- internal ligand conformation, including rotatable bonds and macrocycle shape.

Poses are not aligned onto one another before measurement. The same ligand conformation in a different pocket position is therefore a different binding-mode cluster. Different protonation or tautomer states are clustered separately because their atom mapping and interaction chemistry may differ.

## How the cluster count is determined

The user does not request a particular number of clusters. RDKit Butina clustering determines the count from the pairwise RMSD distribution and the selected cutoff.

| RMSD cutoff | Practical interpretation |
| ---: | --- |
| 1.0 Å | Strict; may separate modest variations of one mode |
| 1.5 Å | Moderately strict |
| 2.0 Å | Default; useful starting point for binding-mode grouping |
| 2.5–3.0 Å | Broad; may combine scientifically distinct poses |

Butina clustering is center-based. Membership does not require every pair of peripheral poses in a cluster to be within the cutoff of each other. Docking Universal records the cutoff and method in `clustering_manifest.json` so the result can be interpreted and reproduced.

## Selecting representatives

Each cluster representative is its lowest-energy member. Clusters are ranked by representative energy, and the three lowest-energy distinct clusters are analyzed by default.

Energy is kept separate from repeatability. Every cluster also reports:

- total pose count;
- number of independent seeds represented;
- number of starting conformers represented;
- minimum and median docking energy;
- chemical state;
- the exact seed, conformer, and model used as its representative.

A low-energy cluster found by one seed is less reproducible than a similar cluster recovered by all five seeds. Conversely, a large or reproducible cluster is not automatically the biologically correct pose. These values support structural judgment; they do not replace it.

## Screening analysis options

### `--analysis representatives`

Default. Writes the cluster tables and creates PML, PSE, PNG, and PLIP output for the selected cluster representatives. Use this for routine scientific review.

### `--analysis summary`

Writes clustering tables, the combined pose SDF, representative coordinate files, and PML scripts without running PLIP or PyMOL rendering. Use this for larger screens or headless systems where visuals will be generated later.

### `--analysis none`

Retains docking poses and scores but skips clustering. Use only when another downstream system will perform pose organization.

### `--representatives N`

Controls how many energy-ranked distinct clusters receive detailed output. The default is 3. Increasing this does not rerun docking when the poses already exist; it only expands post-processing.

### `--cluster-rmsd A`

Controls cluster granularity in angstroms. The default is 2.0 Å. Lower values create more narrowly defined clusters; higher values create fewer, broader clusters. Compare several cutoffs when scientific conclusions depend strongly on the exact grouping.

### `--contact-cutoff A`

Controls which receptor residues appear around a representative in the PyMOL scene. The default is 5.0 Å. This affects visualization, not clustering or docking.

## Main outputs

| File | Meaning |
| --- | --- |
| `pose_inventory.csv` | Every pose with seed, conformer, energy, and cluster assignment |
| `cluster_summary.csv` | Energy rank, population, seed support, and conformer support for every cluster |
| `all_poses.sdf` | Typed coordinates for every retained pose |
| `clustering_manifest.json` | Method, cutoff, counts, and selected cluster identifiers |
| `representative_browser.pse` | One switchable PyMOL scene per selected representative |
| `cluster_###/` | Representative coordinates, metadata, image/session, and interaction analysis |

## Scientific limits

- Docking energies are ranking scores, not measured binding free energies.
- Repeated recovery across seeds describes search convergence, not biological correctness.
- Clustering cannot repair incorrect protonation, receptor preparation, atom typing, or pocket selection.
- A 2 Å cutoff is a conventional starting point, not a universal physical boundary.
- Distinct interaction patterns may sometimes be useful even when geometric poses fall in the same broad cluster.

The recommended review order is energy rank, seed/conformer support, geometry and clashes, interaction pattern, and finally the biological context of the target.
