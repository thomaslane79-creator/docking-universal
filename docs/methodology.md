# Docking Universal methodology

This note records what the workflow does, why the major decisions exist, and where interpretation is required.

## Docking model and batch scope

Docking Universal currently supports rigid-receptor Vina and smina workflows. Receptor coordinates do not move during a docking job. Ligand rotatable bonds may be sampled according to the engine-specific PDBQT representation, and independent ligand conformers can be docked across multiple seeds. This is not flexible-receptor or induced-fit docking.

The same preparation and search protocol can be applied to one compound, a multi-record SDF, or a directory of SDF files. Batch execution isolates every compound and retains per-seed outputs before consolidated pose clustering and reporting.

## 1. Receptor preparation

Docking Universal reads a PDB structure, retains protein atoms, `MODRES`-declared polymer modifications, and a small set of supported metal elements, and removes waters and unrelated heteroatoms from the receptor. It uses Meeko by default when available, with ADFRsuite as a selectable legacy backend, to create PDBQT output. Fixed-width PDB coordinate and element columns are used throughout.

## 2. Ligand detection

Hetero-residue names represented by at least ten atoms are considered ligand candidates after common solvents, ions, crystallization additives, and `MODRES`-declared polymer residues are excluded. Every detected candidate is written to a separate PDB and listed in a manifest. This name-and-size heuristic is intentionally transparent, but it can still misclassify unusual cofactors; users should inspect the manifest.

The bound-ligand control selects an exact `RESNAME:CHAIN:RESNUM` instance rather than accepting a residue name alone. Interactive runs display each candidate's atom count, ask the user to confirm the selected instance, and then offer strict identity verification, a recorded manual override, or an explicit not-recommended PDB bond-perception fallback. Strict mode checks a supplied template or the RCSB Chemical Component Dictionary, compares heavy-atom element inventories, transfers template bond orders onto the crystallographic coordinates, and writes an experimental-coordinate SDF. The PDB-inference fallback requires an audit reason, produces a provisional 2D review image, and requires confirmation before docking. An override requires a free-text reason in the run manifest.

The default CCD lookup retains only a coordinate-free isomeric-SMILES graph: elements, connectivity, bond orders, formal charge, and defined stereochemistry. It does not request or use CCD ideal 3D coordinates. Input coordinates are removed again through a SMILES round trip before independent conformer embedding. Crystallographic ligand coordinates remain in a separate reference used only after docking for symmetry-aware RMSD evaluation.

Calibration is lowest-complexity-first when guided mode is selected. A quick diagnostic directs the next test: adequate pose recovery with insufficient seed evidence extends repeatability at the same depth; inadequate sampling or ranking increases search depth; persistent failure expands independent conformers; the robust tier combines full conformer and seed coverage. Only the first passing tier in that recorded progression is described as the recommended efficient protocol. A manually selected tier is reported only as the tested passing or failing configuration.

## 3. Ligand-centered mode

When a detected ligand is selected, its atom centroid becomes the Vina box center. Protein atoms within 12 Å of the ligand form a local structure for `fpocket`. Alpha spheres are retained when they overlap ligand van der Waals volume, subject to a default 10 Å centroid-distance filter and a −0.5 Å overlap margin. The generated scene exposes the retained surface and ligand reference for review.

## 4. Cavity mode

Without a selected ligand, Docking Universal can run conservative, expanded, or permissive `fpocket` settings. In comparison mode, it evaluates candidate-cavity counts and uses the run with more cavities that remain within configured alpha-sphere-count and bounding-box limits. The resulting cavities are reviewed visually, and the user selects a docking box for the calculation; this is not a claim that the software has identified a biologically validated pocket.

The current pre-release uses a configurable cubic box edge (26 Å by default). In a bound-ligand control, the center is fixed at the experimental ligand coordinates; in ligand-free docking, it is centered on the reviewed cavity. It does not yet derive the box dimensions directly from cavity bounds; cavity-derived dimensions with explicit padding are a planned future option.

Pockets must meet the fpocket score threshold. With strict local filtering enabled, unusually broad pockets are excluded rather than merely warned about.

## 5. Center and rank

Two center definitions are available:

- **Deepest:** the coordinate of the largest fpocket alpha sphere.
- **Centroid:** the geometric alpha-sphere centroid, snapped to the nearest real alpha-sphere coordinate so the point remains inside sampled pocket geometry.

Candidates receive a combined score:

```text
rank = fpocket_score × exp(−distance_to_reference_centroid / 10)
```

The reference centroid is either the whole protein or the largest chain. Higher pocket score raises rank; distance from the protein reference centroid lowers it exponentially. This is a prioritization heuristic, not a calibrated probability of ligand binding.

## 6. Bound-ligand redocking control

The retrospective control removes the confirmed experimental ligand, prepares the ligand-free receptor, centers a box on the withheld ligand coordinates, and redocks independently generated ligand conformers. Vina and smina run independently. Docked poses are mapped back to typed chemistry and compared with the experimental pose using symmetry-aware heavy-atom RMSD in the receptor coordinate frame, without fitting the docked ligand onto the reference. A 2.0 Å threshold is reported by default but remains configurable.

This tests pose recovery for a known ligand/site under the selected preparation and docking settings. It is separate from prospective compound docking and from ligand-free pocket ranking, and success on one complex does not validate a scoring function generally.

The crystal ligand is withheld from docking input and used only as the RMSD reference. Authoritative CCD or supplied-SDF chemistry is converted to isomeric SMILES to discard all coordinates, followed by pH-dependent chemical-state enumeration and seeded independent conformer generation. Control evaluation reports sampling success (any pose within threshold), ranking success (the globally lowest-energy pose within threshold), and reproducibility across independent engine seeds. A crystal-coordinate local-refinement calculation is a biased diagnostic and cannot approve an unknown-docking protocol.

Calibration escalates in explicit tiers. Quick diagnostics use three conformers and two seeds; repeatability increases to five seeds; broader search raises exhaustiveness and retained poses; conformer expansion increases independent starting geometries; robust mode combines those changes. The default approval rule requires sampling and ranking recovery for five independent seeds. Repeated failure should trigger input inspection rather than indefinite parameter escalation.

An approved v1 protocol locks the receptor and docking-box SHA-256 hashes, engine, macrocycle treatment, pH, charge model, conformer count, seeds, exhaustiveness, retained modes, and energy range. Unknown docking refuses changed or unapproved records. Transferring these parameters tests unknown compounds consistently with the control but does not transfer proof of pose or affinity accuracy.

## 7. Redundant pocket suppression

Docking Universal compares equal-size cubic boxes by overlapping volume. A lower-ranked box is skipped when its overlap with an accepted box exceeds `MAX_OVERLAP_FRAC` (0.60 by default).

## 8. Audit artifacts

The workflow records:

- chain sizes and centroid context;
- every parsed pocket's score, alpha-sphere count, dimensions, eligibility, and warnings;
- the selected fpocket run when modes are compared;
- rank order, center, overlap, and selection decision;
- exact settings and timestamps in the run log and generated summary.

These artifacts are designed to make a result reproducible and reviewable.

## 9. Ligand preparation and engine compatibility

Open Babel splits ordinary SDF input and can generate an optimized 3D representation. Calibration and protocol-locked screening instead preserve the independently generated ETKDG conformers. Meeko or the legacy ADFRsuite backend writes PDBQT. Vina-only preparation retains Meeko's flexible-macrocycle representation; smina 2020.12.10 receives rigid macrocycle conformers because it cannot parse the newer `CG0/G0` closure atom types. The selected backend and target engine are written to the preparation manifest.

## Limitations

- Alternate locations and insertion codes are not modeled explicitly.
- Ligand detection relies on residue-name exclusions and atom count.
- Protein preparation behavior depends on the selected Meeko or ADFRsuite version and on available residue templates.
- Protein-centroid proximity is only a proxy for pocket interiority.
- A fixed cubic box may be too small for large ligands or too large for compact sites.
- The workflow does not choose biologically correct protonation states, perform experimental validation, or establish that a docking score implies biological activity.

Treat generated boxes as hypotheses and inspect them in structural context before committing compute or drawing biological conclusions.
