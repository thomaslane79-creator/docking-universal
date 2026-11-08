# Experimental-ligand site grouping and expansion

The user's clarification defines the rule: **if both complete experimental
ligands fit in both boxes, present one site**. The same exact input ligand in
both boxes is the single-ligand special case. An overlap percentage is not a
site-identity threshold. The earlier 95% proposal was removed before acceptance.

## Automatic consolidation

Compare every retained heavy atom against both boxes with zero boundary
tolerance. Require pinned, unchanged ligand and box files in the same receptor
coordinate frame. A group must satisfy the rule for every pair; an intermediate
proposal cannot bridge two distinct sites. Exactly identical box geometries
are also one option. Box overlap fractions remain descriptive provenance only.

Choose one original geometry without averaging or taking a union. Prefer the
exact input-ligand box, or an identical predicted box if available; preserve any
already reviewed reference anchor. Keep all original IDs, geometries, artifact
hashes, detector scores and ligand observations in the expanded source record.
A detector score remains attached to its original source geometry. Input and
related-structure observations retain their different origins and do not grant
control authority. Model-change warnings use the actual chosen geometry.

For an older pending review, reopening projects the grouping without writing
the study. Explicit region approval recomputes it, verifies the retained files
and seals its sources with the existing approval. Hidden aliases are rejected,
not silently mapped onto another box. Previously approved studies and protocols
are preserved. Unregistered or changed old related-ligand assets do not justify
automatic consolidation; fresh reviews now register the aligned ligand files
as well as the evidence record.

## Optional expansion

Select two or more pending site rows and choose **Combine selected sites…**.
Its separate, modeless window shows each old/new center and size, exact outward
face extensions, the retained ligand count and receptor-model warnings. Choose
the starting box. Extend only faces needed to enclose the selected ligands plus
the existing 4 Å bound-ligand margin; no face moves inward. The numerical extent
is always visible. There is no hidden size or overlap cutoff.

**Preview in 3D** displays the proposal while the main viewport stays interactive.
Cancellation restores the selected original view and writes no scientific
state. A rationale enables **Use box for review**. The sole application host
rechecks the revision, file hashes and exact preview, then stages one unscored
E# option. Normal region approval is still required. Portable region metadata
retains source boxes, ligand hashes, the preview, actor and rationale.

An incomplete-reference review tied to an exact box cannot silently transfer to
an expansion. Its separate scientific review remains required. Older omission
records lacking original coordinates produce an explicit unverified warning
instead of claiming that a changed box is unaffected.

## Acceptance and limits

- The real retained public 1N6O pending review now has one B1 site from P1/B1,
  with the original B1 geometry and P1's **11.85** P2Rank score in source details.
  Native main-table, green-ring, detached selector and expanded-source checks
  pass. The exact GNP shows on one native row click and disappears on the next,
  with the camera preserved. The original prepared study is unchanged.
- A clearly labeled synthetic GUI fixture adds one synthetic ligand/proposal to
  an isolated 1N6O state copy. Native selection, preview, 3D viewport access,
  cancellation and staging pass. The proposed X dimension changes from 26.000
  to 30.500 Å; Y/Z remain 26.000 Å. The Mg A201 inside-box warning survives.
  Cancellation stays at revision 12. Staging creates revision 13 with one E1,
  **zero approvals**, no selected scientific region and no calculation. Original
  boxes and ligand files remain hash-identical. This synthetic check makes no
  experimental or docking-performance claim.
- **208 focused regressions pass**, covering ligand containment with much lower
  box overlap, partial containment, distinct neighbors, chained proposals,
  different receptor states, invalid/tampered assets, read-only reopening,
  source-score preservation, host replay, explicit expansion, modeless GUI
  routing and omission-warning projection. A separate 56-test workflow set
  passed before the final ligand-rule clarification; do not count it as a
  separate native end-to-end run.
- Native detached Rilpivirine cluster-002 selection enables **Open 2D/3D review**
  and opens its exact retained side-by-side pair with PLIP/residue controls.
  The retained diagram is an older static style with no verified 2D residue
  links. Subsequent [current-renderer dependency/diagram acceptance](current-2d-renderer-2026-11-08.md)
  passes in a separate regenerated copy; it is not inferred from that saved image.

Local evidence is retained in `validation/runs/site-consolidation-20261108/`
and `validation/runs/site-expansion-native-20261108/`. Installed changes retain
before/after hashes in `local-fix-backups/site-consolidation-20261108/manifest.json`.
These generated private fixtures and backups are not included in Git.

The screening PDF's missing ADFRsuite version remains a separate open provenance
repair. Template-guided docking and charge surfaces remain queued.

## Existing completed-run correction

The first implementation grouped pending reviews only. That omission left
P1/B1 separately visible in an already approved or completed study. The session
now also groups existing-run presentation, retaining the historically approved
box as representative and keeping source P1/B1 records in expanded details.
Presentation metadata is separate from scientific approval receipts. Existing
selected IDs, exact geometry, approvals, protocol construction and saved study
bytes are unchanged. Two distinct historically approved calculation boxes stay
identifiable rather than hiding a calculation that actually ran.

Native installed acceptance used the completed public 1N6O study copy (revision
58): one B1 row in the main table; opening the detached PyMOL Regions selector
shows exactly one B1 entry; returning to the workspace preserves that view.
The Mg A201 inside-box warning remains visible. The protected original Cox-2
state and 5IKR input hashes remain unchanged. Backups are recorded under
`local-fix-backups/existing-site-display-20261108/manifest.json`.

`make test-gui` now requires real Qt and runs the interaction contract suite,
including pending and historical grouping, source details, exact 2D/3D pairing,
diagram mouse activation, centering without zoom, selection persistence,
deselection and PLIP controls. A dedicated macOS/Windows/Linux Actions matrix
runs the same suite. Offscreen tests are not native GPU/window acceptance.

## Combined detector and ligand information

The grouped site's table summary now includes its source detector scores,
without requiring expanded details. With one detector prediction, the graph
uses that recorded value and labels the source (for the actual public 1N6O
copy, `P1: 11.85` on site B1). Ligand evidence retains its green ring. Every
source score remains individually identified; no scores are averaged and no
new detector calculation or revised box geometry is implied. Native restart
confirmed `P2Rank 11.85 (P1)` alongside GNP A200 in the single B1 table row;
the inside-box Mg A201 warning is still present.
