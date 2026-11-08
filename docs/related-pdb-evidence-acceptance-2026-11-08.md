# Related-PDB evidence acceptance — 8 November 2026

## Why the previous window had lookup off

The reopened public 1N6O validation copy inherited an explicitly local-only
study setup from earlier preparation/recovery checks. The product checkbox is
checked by default. Testing only that fixture left a gap in acceptance of
merged related-structure evidence; it did not establish that network lookup
or related-evidence merging passed.

## Live automatic lookup result

Ran the production `ProtocolWorkflowRunner._collect_pdb_pocket_evidence` in a
separate study, enabling related-structure lookup against the original public
1N6O sequence. The RCSB sequence request timed out. The study correctly retained
`status: unavailable`, with the read-timeout detail, rather than zero qualifying
evidence. Separate POST/GET sequence requests also timed out; ordinary RCSB
metadata and coordinate downloads succeeded. This does not establish the cause
of the sequence-service timeout or successful automatic discovery.

The unavailable result is retained locally under
`validation/runs/public-evidence-20261108/state/public-evidence/`.
No permanent networking behavior, thresholds or default settings were changed.

## Real-coordinate comparison and GUI acceptance

To test the remaining path independently, explicitly supplied candidate IDs
from the publication linked on the official [1N6O page](https://www.rcsb.org/structure/1N6O):
1N6H, 1N6I, 1N6K, 1N6L, 1N6N, 1N6P and 1N6R. Coordinate retrieval, sequence
alignment, C-alpha superposition, ligand-chain association, ligand placement,
site grouping and conformation comparisons all used the production functions.
The fixture records curated candidate discovery and the failed automatic
sequence search. This is not automatic-search acceptance.

- All seven Rab5A entries supplied one qualifying ligand observation each:
  GNP, GDP or GTP. Each is classified as same protein, with 99.4% aligned
  sequence identity and C-alpha RMSD 0.103–0.306 Angstrom.
- Input 1N6O was excluded from independent supporting counts.
- Initially selected 5P21/1QRA H-Ras examples were unsuitable positive controls;
  both were rejected at 32.12% identity. They were retained as negative controls.
- One B1 site contains P1/B1 sources, P2Rank 11.85, one input ligand and seven
  related observations from seven PDB entries. The graph retains its green ring.
- Native selection of 1N6I GDP displayed the aligned ligand. Rendering locally
  opened the paired experimental 2D/3D view, identified as experimental rather
  than docked coordinates. Ligand centering and the hydrogen-bond switch worked.
- The test exposed a merge defect: P1's 1,112 existing residue/ligand comparison
  records remained in source details but were missing from the representative
  B1 summary. Merging now retains these comparisons and deduplicates shared
  records. The actual result is reviewed with no geometric incompatibility,
  rather than incorrectly claiming obstruction was not evaluated. This is not
  validation of docking suitability.
- The compact summary now includes the same-protein category. It previously
  showed zero exact/zero homolog while omitting all seven same-protein matches.
- Native restart confirmed the corrected table and evidence panel. The study
  remains at revision 4, with no region approval or docking calculation added.

The curated fixture, raw downloaded coordinates, alignment files, source
hashes, retained comparisons and local interaction outputs are under
`validation/runs/public-evidence-20261108/curated-rab5a/` (ignored local scientific
artifacts). Product module backups are in
`local-fix-backups/related-evidence-merge-20261108/manifest.json`.

Permanent regression tests cover multiple related ligands plus the input,
shared-observation deduplication, obstruction-warning preservation from merged
sources, read-only restoration for older grouped studies and same-protein
summary counts. `make test-gui` requires Qt and runs these contracts. Native
acceptance and a successful automatic search remain distinct checks.
