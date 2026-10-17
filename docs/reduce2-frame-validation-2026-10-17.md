# Reduce2 native-output and receptor-frame corrections

## Outcome

The installed application now recognizes and audits native mmCIF Reduce2
output, preserves deposited crystal/frame records when filtering PDB input,
and rejects an optimized receptor whose fixed backbone has moved. Both raw
2R8N input routes complete Reduce2, Meeko and P2Rank in isolated validation
directories. No docking, new scientific approvals or network lookups were
performed for these correction checks. Existing studies and results were not
rewritten.

Restart Docking Universal before further GUI testing so the host loads the
corrected evidence-progress code as well as the external preparation helpers.

## What was wrong

1. Reduce2 wrote `2R8N_filteredFH.cif` successfully, but the wrapper searched
   only for `*H.pdb`. Its heavy-atom audit was also PDB-only. The mmCIF route
   therefore fell back to the original filtered receptor instead of consuming
   the actual optimized model.
2. The PDB filter dropped `CRYST1`. Without crystal context, the installed
   CCTBX Reduce2 implementation boxes/translates the model. The prepared
   pockets moved with it, while public-PDB ligand evidence was still aligned
   to the original input. For this case a translation of
   (−24.387, −18.510, +32.131) Å turned 17 P1 evidence associations into zero.
3. Evidence-lookup progress was printed to stdout, which the GUI host reserves
   for framed JSON replies. This could corrupt an approval acknowledgement
   even though the approval had already persisted.

These were integration defects, not differences in the deposited protein
coordinates or proof that P2Rank had chosen a different physical pocket.
The original diagnostic records remain in
`validation/runs/full-scratch-two-paths-20261017/receptor-investigation/`.

## Implemented safeguards

- Detect one unambiguous native-format Reduce2 output. Distinguish process
  failure, missing output, ambiguous output and failed structural validation.
- For mmCIF, check that the author identifiers/model/atom count can be
  represented by the engine PDB; convert with Gemmi, retain the accepted native
  CIF alongside the PDB, and audit both heavy-atom inventories. Atom identity
  includes alternate location and element, not only atom name.
- Preserve `CRYST1`, `SCALE1–3` and `ORIGX1–3` through the PDB receptor filter.
  Use the immutable filtered PDB as the recorded Reduce2 input.
- Require matching protein-backbone coordinates within 0.01 Å, **without
  fitting away a translation or rotation**. If there are no backbone anchors,
  use shared heavy atoms rather than passing an empty comparison. Side-chain
  optimization is allowed; missing/changed/extra heavy atoms and internal
  peptide nitrogen overprotonation remain rejected.
- Do not publish a shifted optimized model. A cell-less input for which
  Reduce2 changes the frame is rejected by this audit. `required` mode stops;
  existing `auto` policy may retain the original unshifted receptor, with the
  failure recorded. No new automatic protonation fallback was introduced.
- Send evidence progress to stderr, leaving host stdout exclusively for
  responses. Correct contradictory preparation-route log messages.

## Actual checks

The installed-runtime tests use the bundled minimal GeoStd protein core, not
the full GeoStd database. The raw input files are the retained downloaded
2R8N mmCIF and the existing tutorial 2R8N PDB. Each route prepares a new
receptor and detects new pockets sequentially.

| Check | Installed result |
| --- | --- |
| Reduce2 heavy atoms | All 754 preserved in each route |
| Added hydrogens | 813 in each route |
| Fixed backbone | All 396 anchors unchanged; maximum displacement 0 Å |
| Final receptor heavy-atom coordinates | Identical across formats |
| Final partial charges and atom types | Identical across formats |
| P1 center | (40.0182, 34.7353, −6.2114) Å in both routes |
| P1 dimensions | 26 × 26 × 26 Å in both routes |
| Retained experimental ligand reassociation | 17 P1 matches and one unmatched observation, in both routes |

The PDBQT files are **not byte-identical**: two added polar-H coordinates
round differently by 0.001 Å because native CIF retains more precision than
PDB. This is not a different atom inventory, heavy-atom shape or charge model.
The initial validation harness over-required byte identity; its failed
assertion and subsequent output-only reassessment are retained. Preparation
was not repeated to conceal that assertion.

A separate real Reduce2 test removes the crystal records from an isolated
copy. It verifies that the resulting translation is rejected and no accepted
PDB is published.

Automated coverage: 44 focused Python tests, seven receptor shell suites and
21 GUI-host/client tests pass. Coverage includes native CIF/MMCIF output,
dropped atoms, changed elements/alternate locations/residue identities,
translation/rotation rejection, allowed side-chain optimization, peptide
nitrogen validation and stdout isolation during evidence collection.

## Records and remaining authority

- Source checks and recoverable installation backups:
  `validation/runs/reduce2-frame-fix-20261017/`.
- Installed Reduce2/Meeko/P2Rank results:
  `validation/runs/reduce2-frame-fix-installed-20261017/summary.json`.
- Cell-less rejection check:
  `validation/runs/reduce2-frame-fix-installed-20261017/missing-cell-guard/summary.json`.
- Installed file checksums:
  `validation/runs/reduce2-frame-fix-20261017/installation.json`.

The 18 experimental observations were reassociated locally from their retained
original-frame aligned ligands using the production contact and containment
functions; this was not a new PDB search. It verifies the frame correction,
not independent biological validation of the site.

The corrected receptor differs from the earlier approved fallback receptor:
Reduce2's hydrogen placement and permitted side-chain optimization now actually
reach Meeko. The P1 box is unchanged, but the user's earlier permission required
an exactly unchanged receptor as well. Therefore the remaining full engine
tests must wait for approval of the corrected preparation. Historical studies,
protocol bundles, approvals and docking outputs have not been migrated or
silently relabeled as Reduce2-optimized results.
