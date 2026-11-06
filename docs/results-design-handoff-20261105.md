# Docking Universal — Docking Results design handoff
Date: 2026-11-05
Status: design decisions captured from discussion; no implementation performed.

## Purpose and placement
Add a dedicated Docking Results portion of the pipeline. Help scientists inspect results and help non-protein specialists understand what the evidence means. Present evidence for expert decisions; retain uncertainties and provenance.

Repository: https://github.com/thomaslane79-creator/docking-universal

## User-confirmed priorities
1. Add protein electrostatic surface visualization and ligand partial-charge maps regardless of whether an interpretation section is implemented.
2. Add optional molecule-similarity/template-guided docking.
3. Account for how consistently independent seeds and starting conformers recover a pose cluster as a confidence trend.
4. Provide interactive cluster graphics linked to a representative pose displayed with the protein and the cluster's docking energy/score range.
5. Explore a plain-language "What does this mean?" interpretation section.
6. Electrostatic and lipophilic interactions are important explanatory views.

## Current-state grounding and implementation boundary
During this conversation, main-branch README, docs/methodology.md, and docs/pocket-evidence-validation-v0.7.0.md were read. They describe v0.7.0, fpocket, Vina and QuickVina-W, related-structure ligand evidence, multi-seed/conformer controls, symmetry-aware RMSD clustering, PLIP, PyMOL, reports, and portable protocols.
P2Rank had been discussed previously, but the inspected documentation still names fpocket. Verify actual current code and local uncommitted work before choosing adapters.
Related-structure evidence is already documented as implemented. Template-guided query-pose generation is a proposed additional capability.
No repository modifications, new viewer, maps, or docking calculations were made in this conversation. The local development computer and its checkout were not accessed.

## Interactive results explorer
User requirement: select a cluster and display an example cluster pose with protein and energy range.

Proposed linked views:
- Seed-by-cluster heatmap: rows = independent seed runs; columns = global pose clusters. Show recovery, with a marker for each run's best-scoring pose.
- Separate panels or filters for starting conformers; retain chemical-state distinctions.
- Recovery bars: searches recovering each cluster, and searches ranking it first.
- Protein/ligand viewer: selecting a cluster updates representative pose and metrics; retain camera, protein orientation, and surface display settings.
- Pose controls: representative only, all cluster members overlaid, or individual members colored by seed.
- Keep cluster colors consistent across plots and report; when coloring by seed use a clear separate legend.

Proposed default representative: actual cluster medoid (most central observed pose), with a separate best-scoring-member button. This was an assistant proposal, not a separately confirmed user choice.

Cluster metrics:
- Number of distinct seed runs recovering the cluster / eligible completed runs.
- Number of runs whose best-scoring pose belongs to the cluster / eligible completed runs.
- Recovery across independently generated starting conformers.
- Number of retained member poses, separately from run recovery.
- Best, median, and range of docking scores, with units and engine.
- Within-cluster RMSD spread and clustering settings.
- Competing clusters and score differences.
- Explicit failed-run counts; do not silently include failures as pose-search failures or hide them.

Vina may retain multiple poses per calculation. Count each run at most once for cluster recovery. Do not equate retained-pose fractions with independent-search recovery or equilibrium populations.
Define run identity using seed plus starting conformer and chemical state. Distinguish seed summaries from seed-conformer job summaries so denominators are explicit.
Keep sites, engines, chemical states, and independent versus template-guided calculations distinguishable.
Greater convergence is a useful confidence trend, not a calibrated probability of pose correctness or binding.
Illustrative interpretation: "Independent searches consistently recover this binding mode"; or "Several competing binding modes remain." Any numeric example in prior chat was hypothetical.

## Charge and electrostatic visualization
Terminology: atomic partial charges and surface electrostatic potential are related but distinct. Neither is electron density.
Protein route proposed: PDB2PQR charge/radius preparation -> APBS potential grid -> PyMOL surface coloring.
Ligand first increment proposed: RDKit Gasteiger or MMFF partial-charge coloring on atoms and/or 2D depiction.
Later increment: ligand electrostatic surface from explicit geometry, charges, radii, and a documented potential model.

Controls:
- Independent protein and ligand toggles.
- Surface transparency, pocket-focused display, legends, units, and fixed comparable scales.
- Cache calculation outputs; toggles should reuse maps.
- Keep protein and ligand surface/property choices independently selectable.
- Lipophilicity/hydrophobicity surface is a separate view; exact model is undecided.

Scientific requirements:
- Preserve and record protonation, tautomer, coordinates, receptor components, charge model, radii, solver/settings, pH assumptions, ionic strength, temperature, and dielectric choices where relevant.
- Electrostatic preprocessing must not silently change the docking model.
- Flag unsupported cofactors, metals, modified residues, or missing parameters; do not silently parameterize them.
- Maps correspond to the displayed chemical state and conformation.
- An isolated ligand potential and protein potential are interpretive views, not a computed binding free energy.
- Do not imply standard Vina scores include a direct Coulombic evaluation of these displayed partial charges.

Preliminary engineering estimate only, not a code audit:
- Ligand charge-color prototype: 1–2 working days.
- Protein APBS prototype: 3–5 days.
- Ligand electrostatic surface: another 2–4 days.
- Integrated reliable feature: approximately 2–3 weeks total, assuming working viewer infrastructure. Re-estimate after code inspection.

## Optional similarity/template-guided docking
Proposed flow:
1. Reuse qualified experimental ligand observations from accepted related protein structures.
2. Rank template ligands by query chemical similarity.
3. Display source PDB/ligand, protein alignment quality, similarity method/value, scaffold correspondence, stereochemical compatibility, and pocket compatibility.
4. Let user select a template.
5. Align query ligand to template and generate/refine candidate poses.
6. Retain independent docking alongside this pathway and compare agreement.

Similarity is a retrieval filter, not sufficient proof of transferable geometry. No fingerprint, cutoff, alignment algorithm, refinement engine, or licensing choice has been finalized.
Keep template-guided evidence separate from independent-search convergence.
Experimental-coordinate/template-initialized refinement must not be used to approve an independent redocking control.

## "What does this mean?" interpretation
Explain selected-pose evidence with atom/residue highlighting:
- Complementary charged regions.
- Nonpolar groups occupying hydrophobic regions.
- Hydrogen bonds and shape complementarity.
- Clashes, buried polar groups without clear partners, and competing poses.
- Recovery across seeds/conformers.
- Experimental pocket evidence and control results.

Use phrases such as "may favor binding" or "supports a reproducible docking result." Avoid turning surface colors, contact counts, cluster populations, or docking scores into proof of binding, potency, or activity.
Interpretation should be generated from traceable computed observations; define rules and thresholds before implementation. No interpretation model has been selected.

## P2Rank versus CurPocket conclusion
Keep P2Rank as a reasonable intended primary predictor; no evidence was found establishing CurPocket as generally superior.
CurPocket is geometric/curvature-based; P2Rank predicts ligandability from learned surface features.
CB-Dock2's reported 85.9% pose recovery on Astex used templates in 82/85 cases and is not a standalone pocket-detector benchmark.
CurPocket could later be a complementary source. A fair test should separate top-one/top-five site recovery, full ligand containment, and downstream pose recovery, using matched structures and controlled docking settings.

## Suggested implementation sequence (proposal)
1. Inspect current checkout, instructions, GUI status, cluster outputs, provenance and atom mappings.
2. Define run/pose/cluster records and recovery denominators; verify symmetry-aware clustering and representative selection.
3. Build results explorer using existing output data.
4. Add required ligand charge maps and protein APBS surfaces with cached provenance.
5. Add independent hydrophobicity view once its model is specified.
6. Add optional template-guided docking branch and comparisons.
7. Add evidence-grounded plain-language interpretation.
Use focused scientific checks: one recovered cluster across seeds, multiple competing clusters, missing/failed jobs, conformer/state separation, and map/coordinate consistency. Do not assume any proposed defaults are validated.

## Primary references and project documents
- CB-Dock2: https://doi.org/10.1093/nar/gkac394
- FitDock: https://doi.org/10.1093/bib/bbac087
- CoBDock comparison: https://doi.org/10.1186/s13321-023-00793-x
- PocketNet ensemble study: https://openreview.net/pdf?id=XhfIVsvwHl
- P2Rank: https://github.com/rdk/p2rank
- Vina search/seed behavior: https://autodock-vina.readthedocs.io/en/latest/faq.html
- PDB2PQR: https://pdb2pqr.readthedocs.io/en/latest/using/index.html
- APBS: https://apbs.readthedocs.io/en/stable/using/index.html
- PyMOL APBS display: https://pymolwiki.org/index.php/APBS_Electrostatics_Plugin
- RDKit partial charges: https://rdkit.org/new_docs/source/rdkit.Chem.rdPartialCharges.html
- Project methodology: https://github.com/thomaslane79-creator/docking-universal/blob/main/docs/methodology.md
- Pocket evidence validation: https://github.com/thomaslane79-creator/docking-universal/blob/main/docs/pocket-evidence-validation-v0.7.0.md

## Resume instruction
Read this handoff, inspect the current local Docking Universal checkout and its instructions, reconcile current implemented features, then implement the agreed Docking Results additions. Preserve scientific provenance, separate independent and template-guided evidence, and include partial-charge/electrostatic maps independently of the interpretation feature.
