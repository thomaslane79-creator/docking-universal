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
| 1.5 Å | Default; moderately strict |
| 2.0 Å | Broader grouping; may combine modest variations of one mode |
| 2.5–3.0 Å | Broad; may combine scientifically distinct poses |

Butina clustering is center-based. Membership does not require every pair of peripheral poses in a cluster to be within the cutoff of each other. Docking Universal records the cutoff and method in `clustering_manifest.json` so the result can be interpreted and reproduced.

## Selecting representatives

Each cluster representative is its lowest-energy member. Clusters are ranked by representative energy, and the three lowest-energy distinct clusters are analyzed by default.

The prospective cluster graph displays the top 20 energy-ranked clusters, with
the top three colored red, blue, and gold and the remainder gray. Experimental
control graphs retain the top 20 cluster summaries and also include
the actual globally lowest-RMSD evaluable pose at its own binding
energy, even if its cluster is outside that set. This circle with a green outline
represents one pose, not its cluster's population or independent minima.
Its fill follows its cluster's top-three energy color, otherwise gray. The
closest ligand also keeps its cluster's energy color in the 3D overlay, and is
green only when its cluster is outside the top three.
The same identities and ligand colors are used in the GUI's embedded/detached
linked 2D/3D review and exported comparisons. Control diagrams include exact
top-three representatives and the actual closest pose; the experimental
reference is magenta in production views. Verified diagram/source hashes prevent
an old image from linking to changed coordinates. Existing saved reports need
regeneration from retained outputs; no redocking is necessary.
Per-seed redocking browsers are explicitly local diagnostics (global cluster
ranks do not exist yet at that stage), not substitutes for the final landscape.
All points are circles;
circle size indicates the number of docked poses in the cluster, not the number
of different compounds. For experimental controls, a point combines the
cluster's lowest binding energy and lowest experimental RMSD, which may belong
to different member poses. This is distinct from the three representatives
receiving detailed 3D and interaction analysis by default.

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

Controls cluster granularity in angstroms. The CLI and GUI default is **1.5 Å**.
It can also be set explicitly with `--cluster-rmsd 1.5`. Existing studies and
saved user settings retain their selected cutoff rather than being silently
rewritten. Lower values create more narrowly defined clusters; higher
values create fewer, broader clusters. Compare several cutoffs when scientific
conclusions depend strongly on the exact grouping.

This clustering cutoff is separate from the **2.0 Å experimental-pose recovery
threshold** used in retrospective controls; that recovery threshold is unchanged.

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
- The selected 1.5 Å clustering cutoff is a grouping choice, not a universal physical boundary.
- Distinct interaction patterns may sometimes be useful even when geometric poses fall in the same broad cluster.

The recommended review order is energy rank, seed/conformer support, geometry and clashes, interaction pattern, and finally the biological context of the target.
