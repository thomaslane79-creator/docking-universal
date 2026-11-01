# Software defects found by the 100-workflow cohort

Status: **installed on the working Mac**, 2026-10-23, following explicit
authorization. The earlier sections retain the pre-installation history; see
the deployment checkpoint below. The user
requested software defects be addressed before receptor/chemistry review.
The historical cohort remains 60 executed docking workflows/searches, six
pre-docking failures and 34 unattempted blocked cases. These repairs do not
retroactively change those outcomes or add new docks.

The candidate is a new copy of the frozen installed-code-derived validation
runtime, at `validation/local/full-docks-100-20261022/isolated-software-fixes-v2/`.
The installed Mac app, dependency environments, original studies and earlier
private runtime remain unchanged. No push, installation or release was done.

## Corrections

| Defect | Bounded correction | Verification |
| --- | --- | --- |
| GUI-approved nine-atom BEN rejected by the shell's automatic ten-atom candidate filter | Validate an explicitly selected component/chain/residue/insertion/alternate-location identity with the same detector as the GUI. Keep the automatic suggestion floor unchanged. Never substitute another instance. | Exact deposited BEN succeeds at the handoff; missing/wrong/incomplete identities still fail. No receptor preparation or new docking was needed. |
| Native contacts and residue links reject a report containing both calcium and the docked ligand | Share an identity-based PLIP selector. Multi-component retained reports select the normalized UNL Z:1 site written by the complex builder. Missing/duplicate identities fail closed; ions are not substituted for a missing ligand. The 2D renderer also rejects ambiguous component matches. | Both real saved trypsin workflows, three representatives each: exact contacts, residue links, labels, individual/master toggles, camera preservation, exports and unchanged saved science. |
| Executable permission mistaken for a runnable legacy ADFRsuite fallback | Probe help without passing a receptor; retain a startup audit and skip an unavailable fallback, while preserving the original Meeko diagnosis. | Real incompatible local wrapper is detected; synthetic runnable/failing/missing backends are covered. This does not install a compatible ADFRsuite or make glycans supported. |
| Dependency connectivity/valence exceptions described only as ordinary residue-template failures | Give backend construction/valence errors their own explanations. Keep the original and repaired models and traceback; do not recommend deleting residues as an automatic workaround. | Read the five retained receptor failure logs without rerunning preparation. |
| Gross overlaps in a generated PDBFixer model allowed through to parameterization | Audit introduced heavy atoms for sub-Angstrom overlaps. Retain but reject such a repair, record the rejected geometry and stop it from being adopted. This is only a gross-overlap guard, not stereochemical validation. | The retained 1FM6 repaired model is rejected by the new guard; unchanged original coordinates are not falsely marked as newly generated damage. No new repair was attempted. |
| ABL residue label overlaps the ligand ring | Reserve conservative text extents around residue-label anchors; prioritize nonoverlapping geometry and reject unresolved structure collisions. Audit unavoidable connector crossings separately. Bump the renderer layout revision. | All three retained ABL representative diagrams re-rendered and visually inspected; original poses, receptor and PLIP hashes unchanged. |
| One final report reference spills onto an almost-empty extra page | Slightly tighten reference line spacing in the shared report style, preserving font size, text and values. | Two copied AD4/Vina reports retain identical text and numerical values; final pages inspected. The affected BRD4 copy is five pages rather than six. Original PDFs remain unchanged. |
| Validation accepted an open paired dialog despite unavailable contacts; error metadata retained an old search count | Stage a stricter future GUI worker that verifies contact loading/mapping, not file existence alone. Keep deferred-error execution counters synchronized with the verified progress audit. | The strengthened native review checks succeed on both repaired views; count remains 60, not an earlier live checkpoint or 100. |

## Verification and remaining limits

The candidate passes 17 focused defect regressions, 33 existing service contracts
and 31 GUI/viewer contracts (81 Python cases, no skips), plus four existing
synthetic shell contract groups. The shell fixtures were adapted only to locate
the isolated runtime and model the backend's help command. An initial fixture
path failure remains retained separately. Two native retained-output reviews
exercise six representatives; they launch zero scientific jobs. No new control
approval or engine search was granted.

This does **not** establish successful preparation of 1UY6, 3ERT, 4EY7, 1FM6 or
1A4G. In particular, the underlying Meeko/PDBFixer connectivity and repaired
geometry cases remain unresolved, not fixed merely by a better error message.
The generated 1FM6 model, unlike its filtered original, reproduces the valence
exception during a read-only conversion check. A safe replacement model has
not been chosen. Linked glycan templates and the zero-occupancy GLU A75 model
still require structural/compatibility review. No permissive valence handling,
component deletion, template invention or dependency replacement was used.

The all-report visual gates remain incomplete. These bounded diagram/native
and pagination checks are not a retroactive signoff of every historical report,
multi-site behavior, accuracy, engine equivalence or another operating system.

Local evidence is `validation/runs/software-defects-20261023-v2/`; its summary
and candidate manifest retain code hashes, changed files, tests and protection
checks. Scientific inputs and derived evidence remain local and ignored by Git.
The earlier 100-workflow automation remains paused. A corrected-build workflow
continuation must be separately versioned; it must not overwrite failed runs.

## Corrected-build retest (2026-10-23)

At the user's request, two **new actual full GUI workflows** were run with the
isolated v2 candidate: the formerly rejected trypsin/BEN ligand-only route,
once from local PDB and once from a fresh GUI mmCIF download. Both passed
preparation, exact BEN A:1/B1 site handoff, reviewed exploratory finalization,
new Vina docking, clustering, PLIP/2D, PDFs, native linked 3D and fresh-host
reopening. The original scientific settings and retained calcium were preserved.
These are two corrected-build retests of the same target, not broad target
coverage, two pose-recovery controls or a claim of 100 successful workflows.
The original cohort remains 60 completed searches with its failures unchanged.

The original small-ligand and PLIP failures were reproduced with the earlier
runtime on the same inputs; the corrected paths passed. Native read-only
reviews checked every representative in both new Vina workflows and a retained
QuickVina-W workflow: **nine representatives**, exact contacts and residue links,
labels, individual/master toggles, camera preservation and exports. These
reviews launched no additional scientific jobs. The macOS texture warning still
appeared; it did not prevent these exact native checks from passing.

Retesting passed **113 Python cases with no skips** (the earlier 81 plus 32
report-provenance/synchronization cases) and four shell contract groups. Three
ABL diagrams were freshly rendered and visually inspected; the prior label
overlap did not recur. Two copied AD4/Vina reports retained identical text and
values, with both final pages inspected; BRD4 is five rather than six pages.

Report review found one additional defect: both new protocol-only PDFs claimed
preparation occurred outside the recorded run, despite retained finalization
metadata. The original v2 PDFs are preserved as **failed provenance gates**,
not retrospectively passed. A separately versioned **v3 isolated copy** fixes
the shared report fallback to use the retained protocol preparation summary
when no local preparation route is discoverable. Local audits and screen
handoffs retain precedence; missing history still does not invent preparation
success. Six new focused cases and 26 existing synchronization cases passed.
Only copies of the two protocol reports were regenerated—no preparation or
docking was repeated. The only text change is the incorrect preparation
sentence. All four corrected protocol pages and all ten new docking-report
pages were inspected; this is not signoff of every historical report.

Final integrity checks reverify all 60 historical result inventories, the two
new case inventories, original protected studies, the frozen prior runtime and
all 392 installed application files. Neither candidate was installed, and no
production source, dependency, threshold or GPU registration was changed.
The five unresolved receptor/chemistry boundaries listed above remain unresolved.

Local receipts:
`validation/runs/software-defects-retest-20261023-v3/retest-verification.json`,
the run's unchanged `summary.json`, and `report-provenance-v3/summary.json`.
The final candidate manifest is
`validation/local/full-docks-100-20261022/isolated-software-fixes-v3/candidate-manifest.json`.
The original cohort automation remains paused; no new queue was launched.

## Authorized Mac deployment and qualitative RMSD controls (2026-10-23)

The user requested applying the tested repairs and adding qualitative choices.
Pinned v4 includes v3 plus one GUI-panel change: **Tight (1.0 Å), Default
(1.5 Å), Loose (2.0 Å), Custom** with the exact number visible and editable.
The saved number remains authoritative. Custom values restore as Custom and
preset values with their matching category; fresh approvals are still required.
Changing the category alone does not launch a job or modify completed analysis.
Inline help distinguishes grouping from experimental RMSD/accuracy and states
that completed results are not automatically reclustered.

Twenty application files were applied to the Mac runtime, including the six
previously isolated ligand-only provenance corrections. Three files are new;
the runtime now contains 395 non-cache files. All 375 unrelated existing files
are byte-identical to the pre-update inventory. Replaced files have recoverable
local backups. Source promotion preserves existing browser/SDF compatibility
and diagnostic changes; only the pinned Mac candidate was deployed, not the
entire dirty checkout. Existing installer package/file rules include the new
helpers. No dependency, engine binary, configuration, GPU registration, default
cutoff, original study or existing report was changed.

Before and after installation, the exact runtime passed **100 scientific,
report and repair contracts plus 131 Mac GUI/viewer contracts**, without skips.
Three source-only Windows capability fixtures are explicitly outside this Mac
profile, not renewed Windows acceptance. Four installed synthetic shell groups
passed. Nine new portable source regressions and 103 source GUI tests passed.
Early harness attempts (nonexistent Python test filename, Node absent from the
harness PATH, and Windows-only fixtures absent from the Mac package) remain
retained; corrected and explicitly scoped runs passed.

Installed native Vina and QuickVina-W reviews exercised all six retained
representatives: exact contacts, labels, residue/type/master toggles, camera
preservation and exports. Both source inventories stayed unchanged. A separate
disposable installed GUI check verified all four preset displays, numeric fit,
saved 1.25 Å restoration and no inherited approval/state mutation; screenshots
were inspected. The known macOS texture warning still appears despite passing
native checks; its removal is not claimed. No preparation, docking, PLIP or
report regeneration was done for deployment. The prior two full corrected-build
docks remain separate from the original cohort's 60 searches and failures.

Local deployment receipt:
`validation/runs/software-fixes-install-20261023-v4/summary.json`.
Recoverable originals are in that run's `installation-backup/`; installed
files are checked against `installation-plan.json`. Original result inventories
remain protected. No Git push, PR or release was made.

### Remaining work, in order

1. Resolve five preparation boundaries safely: 1UY6's zero-occupancy GLU
   model/template issue, 3ERT's Meeko connectivity/padding failure, 1FM6's
   invalid generated repair, and linked glycan/template handling in 4EY7 and
   1A4G. Separate dependency/software fixes from molecular decisions requiring
   review. Better diagnostics and rejecting a bad repair do not fix the
   underlying cases. Incompatible legacy ADFRsuite is detected, not replaced.
2. Run separately versioned acceptance for affected failed and unattempted
   paths after safe fixes/decisions. Do not repeat the 60 successful searches,
   erase failures or silently add replacements to claim 100 successes.
3. Finish historical full-report visual review and add explicit multi-site
   workflow/report coverage. All original cases used one selected site;
   pending visual gates are not converted into passes by this deployment.
4. Implement an explicit retained-output reclustering operation if completed
   results should update without docking again. Presets only choose the next
   screening analysis's cutoff; they do not provide this separate capability.
5. Run cross-platform/fresh-install regression acceptance for changed code.
   Local Mac application acceptance does not renew Windows/Linux or GPU-platform
   certification.
