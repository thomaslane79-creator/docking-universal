# Pocket-evidence validation record — v0.7.0

This record documents the focused validation used for Docking Universal's evidence-led exploratory protocol workflow. It is intentionally separate from the README: most users only need to know that related-structure evidence is available and auditable, while readers evaluating the method can inspect the search, alignment safeguards, test selection, and observed outcomes here.

## Scientific purpose

The workflow does not treat fpocket rank, a deposited ligand, or sequence similarity as automatic proof of a biologically correct docking site. It gathers independent evidence, reports where those sources agree or disagree, and presents one or more labeled boxes for user selection. The resulting decision and its evidence are retained in the report and `.duprotocol` bundle.

This six-structure set tests software behavior and scientific safeguards. It does not establish prospective docking accuracy or validate any automatically selected cavity as biologically correct.

## Related-structure search and alignment safeguards

For the tested evidence-search path, Docking Universal:

1. Extracts the selected receptor protein chain and queries the official RCSB PDB sequence-search service for related protein polymer entities.
2. Uses a 0.90 sequence-identity cutoff for the database search and records the returned candidate entries.
3. Reconstructs the coordinate sequence of each candidate chain and aligns it to the selected receptor chain.
4. Requires at least 0.90 aligned sequence identity, at least 0.70 query coverage, and no more than 2.0 Å C-alpha RMSD before accepting the structural alignment.
5. Compares authoritative protein accessions when they are available. Exact/same-protein evidence and qualified related-sequence evidence remain distinguishable in the retained record.
6. Requires a deposited ligand to physically contact a structurally accepted source-protein chain. The ligand's chain label is preferred, but contact geometry is checked because deposited ligand and polymer chain identifiers are not universally reliable.
7. Rejects and records ambiguous chain assignments, inadequate sequence/coverage, excessive C-alpha RMSD, absent chain contact, and other excluded candidates rather than projecting them into the target frame.
8. Transforms accepted ligand coordinates using the selected chain alignment, groups spatially overlapping observations into candidate sites, and compares each site with fpocket cavities.
9. Calls direct fpocket correspondence only when cavity contact and complete docking-box containment agree. Ligand evidence without a corresponding cavity remains a separately identified ligand-defined option rather than receiving an invented fpocket score.

These checks are intended to reduce symmetry-mate, paralog/homolog, truncated-chain, and wrong-chain errors. They cannot determine biological relevance by themselves, which is why the evidence remains reviewable and the user retains the final choice.

## Test-set design and results

The set was deliberately balanced. Three apo or unbound targets produced qualifying aligned ligand evidence from related PDB structures; three produced no qualifying deposited-ligand evidence. The latter outcome is important: the workflow must remain useful with fpocket alone and must clearly state that structural ligand support was not found.

| Selected PDB | Why it was included | Observed workflow result |
| --- | --- | --- |
| **1RTJ** | HIV-1 reverse transcriptase case with many same-protein ligand-bearing structures available for alignment. | The RCSB search considered 20 candidate entries. Thirteen retained same-protein ligand poses formed one site group that directly corresponded to fpocket P1. |
| **2PC0** | Apo, open-form HIV protease case intended to challenge multiple related ligand locations and chain assignment. | The search considered 20 entries and retained 28 aligned ligand poses. Three reportable site groups contained exact-sequence and qualified related-sequence evidence; one group corresponded to fpocket P2, while ligand-supported alternatives remained explicit. |
| **2R8N** | Unbound HIV-1 subtype C protease case intended to test exact and qualified related sequences and disagreement between evidence sources. | The search considered 20 entries and retained 18 aligned ligand observations. The main site group corresponded to fpocket P2, while the automatically highest-ranked fpocket choice remained P1; the report therefore showed that fpocket rank and the related-structure evidence did not agree. |
| **1P5S** | Protein-domain case with only a small related-structure search set and no qualifying deposited ligand. | Two candidate entries were considered, but no ligand-site group qualified. The report used fpocket evidence alone and explicitly stated that related-structure ligand evidence was unavailable. |
| **4ER8** | Protein–DNA structural case used to test that non-ligand structural context does not become false ligand-site evidence. | One candidate entry was considered and no qualifying deposited-ligand evidence was retained; fpocket candidates remained available for review. |
| **6FXS** | Enzyme case used as an independent no-related-ligand-evidence path. | One candidate entry was considered and no qualifying deposited-ligand evidence was retained; the protocol completed from fpocket evidence without inventing structural support. |

Every case generated:

- a preliminary **Pocket-Review Report (Not a Protocol)**;
- a final site-guided exploratory protocol report after selection; and
- a `.duprotocol` bundle that passed full manifest SHA-256 verification.

The repository's fast validation suite also passed installed-copy checks, maintained shell tests, and 174 Python tests. The branch's Ubuntu and macOS GitHub jobs passed environment creation, CLI checks, docking-engine verification, and real-tool integration.

## Report examples

The following pair shows the same 2R8N evidence-led workflow at its two decision stages:

- [Preliminary evidence and docking-box review report—not yet a protocol](assets/pocket-evidence-review-example.pdf)
- [Final protocol report after a docking region is selected](assets/pocket-evidence-protocol-example.pdf)

The preliminary report exposes the available evidence and selectable regions without authorizing screening. The final report records the selected box, its geometry, the evidence relationship, and the reusable protocol identity.

## Interpretation limits

- An RCSB-deposited ligand is evidence that a ligand occupied the aligned source structure; it does not establish that the same site or pose is relevant to every target state or intended compound.
- A good sequence and C-alpha alignment supports coordinate transfer but does not eliminate conformational, oligomeric, crystal-packing, mutation, protonation, or biological-context differences.
- fpocket is a geometric cavity predictor. Agreement with aligned ligand evidence strengthens the site rationale but does not validate binding affinity or prospective pose accuracy.
- A ligand-defined region without fpocket correspondence may still be scientifically useful, but the disagreement is retained for the user to evaluate.
- Only a target-matched bound-ligand pose-recovery control can provide the workflow's control-validated protocol status. Site-guided protocols remain explicitly exploratory.
