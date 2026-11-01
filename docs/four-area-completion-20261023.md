# Four-area completion checkpoint

2026-10-25 continuation: the [explicit preparation review checkpoint](preparation-review-20261025.md)
records the new model-change handoff, strict-attempt boundaries, missing-backbone
guard and native 1A4G/Vina evidence. That workflow completed across retained
adapter/package continuations; a copied-study reopen verifies persistent per-box
warnings. The explicitly approved 4EY7 choices now passed a full native Vina
workflow, and an ordinary mmCIF/P2Rank/QuickVina-W workflow also passed: three
new searches in total. Original presentation failures remain recorded; copied
reports separately verify warning pagination and the P2Rank/B1 distinction.
Full visual acceptance remains limited by other figure/layout issues. All 395
installed application files remain unchanged. The independent
[100-target panel](protein-panel-100-20261025.md) is now frozen; its first ten
native workflows have launched. The strict goal is at least 91/100 completed
primaries. Preserve older statements below as historical checkpoints.

Status: in progress, authorized 2026-10-23. This is not a claim that any of the
four requested areas has already passed. Keep independent scientific, functional,
presentation and platform gates; preserve prior failed attempts and completed
results. No automatic chemistry decisions or repeated successful docking.

Completion objective clarified by the user on 2026-10-24: **at least 90% of
proteins in a representative panel should run to completion**, not necessarily
recover an accurate pose. This is the functional-compatibility target for the
current fixes, not an achieved result or permission to force incomplete models
through preparation. Count distinct protein targets, retain failed input
structures, and distinguish routine completion from explicit reviewed changes.
The historical 100 scenarios are not 100 independent proteins. See the
[measurement definition](validation-system.md#protein-workflow-completion-target);
accuracy, visual acceptance, engine coverage and platform acceptance remain
separate.

## Completion-target implementation plan, 2026-10-24

The user asks how to make the 90% completion objective achievable and is open to
revising it if representative deposited inputs prove too incomplete. The
[staged plan](protein-completion-plan.md) prioritizes common preparation
boundaries and the unfinished native review/adoption flow, then a frozen
independent-protein panel. Incomplete experimental coordinates, unsupported
preparation features and application defects remain different causes; do not
label all of them database errors.

Implemented a read-only `validation/validate.py protein-coverage` command with
52 coverage/supervisor contracts passing. It verifies retained output hashes,
raw preparation, actual screening, downstream products and reopening receipts;
counts one predeclared primary case per protein; keeps blocked/unrun cases in
the denominator; discloses supplemental successes; and separates routine,
reviewed-change, external-manual and unclassified routes. Application-supported
classification requires an explicit review bound to the prepared receptor hash.
Small/retrospective panels and mixed runtime/platform profiles cannot establish
the prospective target. This is local measurement, not chemistry approval.

The [local verification receipt](../validation/runs/protein-completion-20261024-v1/summary.json)
records the retrospective raw-cohort check: ten original biological groups,
five completed original primary cases and one additional group completing only
supplemental scenarios. Primaries were mechanically the first original cases,
not selected for good outcomes; 1YET/1UY6 stay one HSP90 group. These old-build
outcomes are **not a current-build score, representative population rate or
90% acceptance claim**. Earlier protocol-reuse20 and separate BEN retests are
not silently added. All 395 installed files and original run summaries remain
unchanged. No preparation, modeling, docking, network retrieval or installation
was performed. The larger acceptance panel is not yet curated or launched.

Latest direction supersedes the broad repair discussion for extensive cases:
leave 1FM6 failed rather than automatically rebuilding or deleting its incomplete
residues. Users may manually edit a copy and submit it as a modified receptor for
fresh preparation, retaining original inputs and warnings. No automatic missing
residue/loop filling, new gap model, or 1FM6 residue exclusion is authorized.

Additional audit finding: the old 1UY6 intermediate's eight added atoms complete
LYS A224, which had only N deposited. This includes backbone atoms; the candidate
must not be described as a side-chain-only repair or adopted under the newer
no-automatic-backbone-completion preference. Its strict-preparation success is
retained as historical test evidence, not permission to deploy it. No further
molecular modeling or docking has been performed on that candidate.

Latest user approval/clarification (2026-10-23): the listed exploratory repair
and exclusion choices are acceptable for isolated testing. This includes using
the previously tested 1UY6 candidate for an exploratory retest, not silently
replacing an installed or production model. It is not a blanket instruction to
delete all 50 diagnostic residues in 1FM6. The user explicitly does **not** want
missing residues/loops built from sequence. Keep gap filling disabled; distinguish
it from optional, flagged reconstruction of side chains on observed backbones.

The first approved isolated variants are retained in
[their local receipt](../validation/runs/four-area-20261023/approved-receptor-variants-v1/summary.json):
1A4G passes strict Meeko after excluding only NAG A:1/B:1; 4EY7's exact listed
sugar-exclusion variant stops at unresolved alternate locations (not a successful
preparation). No new docking ran, no original evidence changed, and no additional
residue was omitted to force success. Its historical alternate-location choices
must be reviewed or explicitly carried forward before a separately versioned test.

1FM6's deposited `REMARK 470` explicitly lists the missing side-chain atoms.
Of the 50 backend-named residues, 41 have backbone atoms only and nine partial
side chains; 48 are in receptor chains and two in coactivator peptide chains.
They are not 50 entirely absent residues or one disposable peptide. The original
193-atom reconstruction failed and is not accepted merely because the missing
atom identities are known. The source-only exact-exclusion helper now permits
explicit standard-amino-acid exclusions with high-severity, persistent warnings;
five focused guards pass. GUI/host approval and downstream warning integration
remain unfinished, and this helper has not been installed.

1. Preparation: inspect/reproduce five retained failures, fix bounded software
   faults in isolated copies, and require review before rebuilding unobserved
   coordinates or changing retained chemistry. The user approved an isolated
   rebuild of the three zero-occupancy GLU A75 side-chain atoms in 1UY6. That
   candidate passes strict Meeko, preserves every other retained coordinate
   and the heavy-atom identity set, and introduces no gross overlap. It has
   **not** been adopted or docked; model review remains required. See the local
   [repair receipt](../validation/runs/four-area-20261023/1uy6-authorized-rebuild-v1/summary.json).
   3ERT's problematic padding connects HIS A550 and PRO A552 after
   reconstruction of a mostly absent PRO residue; 1FM6's generated coordinates
   fail the installed gross-overlap guard. Glycan-linked NAG/FUC in 4EY7/1A4G
   need supported and verified linkage parameterization, not deletion or a
   successful exit forced through permissive flags.
2. Presentation/multi-site: review retained PDFs locally and exercise explicit
   multiple-region reports without inheriting new scientific approval. Report
   pending or failed visual gates separately from successful searches.
3. Reclustering: add a host-owned explicit operation from retained poses. Use a
   new analysis revision, retain original scores/poses/site/engine metadata,
   never run docking or alter an old report in place, and require exact source
   hashes. Separate sites/chemical states. GUI refresh and report references
   must refer to the selected revision, not mix old and new cluster identities.
4. Platforms/install: validate changed source and installation packaging locally;
   native Windows/Linux evidence requires the actual matching runtime/CI. No
   upload of structures, poses, reports or numerical structural evidence. Ask
   before any new external action that exceeds the approved branch/CI scope.

Initial baseline: installed Mac v4 contains 395 non-cache application files,
with verified receipt at
`validation/runs/software-fixes-install-20261023-v4/summary.json`. Historical
cohort remains 60 completed workflows, six measured pre-docking failures and
34 related unattempted blocked cases. Two new corrected-build BEN/Vina workflows
are separate retests; they do not overwrite those historical counts.

## Site-first preparation correction — source increment, not installed

The user explicitly clarified that a whole-receptor parameterization failure
must not prevent pocket discovery or box review. Local distance is review
evidence, not automatic permission to omit residues. Original deposited inputs
must remain intact; explicit repairs/exclusions must retain permanent model-change
warnings, including when the resulting model passes preparation.

Implemented in the development source:

- Coordinate-only P2Rank or exact deposited-ligand site review, followed by a
  separate explicit receptor-parameterization action after site approval.
- Coordinates used for site review have their own artifact type/structural
  identity: they are never advertised as a prepared docking receptor.
- Parameterization does not repeat prediction or replace reviewed boxes.
  A safely failed preparation retains box selection, backend diagnostics,
  existing repair audits, and per-box distances for backend-named residues.
- The GUI shows the failure category/concern and distances to the entire box
  (zero for an affected atom inside), not just the box center. Unlocated or
  unrecognized issues remain unresolved; the list is not a complete chemistry audit.
- Host finalization and GUI finalization remain disabled without successful
  parameterization. Automatic retries, model exclusions and new repair choices
  are not enabled. Hash changes invalidate the retained handoff.
- The existing control and explicit fpocket fallback paths are not silently
  migrated. The new GUI path is advertised only by the Mac development host;
  native Windows/Linux acceptance remains separate.

Actual coordinate-only P2Rank on the previously blocked 1A4G input succeeded,
retaining linked components and producing 15 candidate box files without any
parameterization or docking. See its local
[coordinate-only receipt](../validation/runs/four-area-20261023/1a4g-coordinate-sites-v1/site_exploration.json).
The [read-only distance audit](../validation/runs/four-area-20261023/site-aware-failure-audit/summary.json)
also demonstrates why issues must be assessed against each box: the 1FM6
findings are distant from one reference region but overlap the other.

Source acceptance checks and unchanged installed-file audit are retained in the
[source increment receipt](../validation/runs/four-area-20261023/site-first-source-v1/summary.json).
The final run passes 74 host/pipeline contracts, 113 GUI contracts and two shell
groups; the failed-preparation evidence registration also passed a focused recheck.
All 395 installed non-cache application files still match the prior deployment.
These synthetic host/GUI contracts and one actual coordinate-prediction run are
not installed, native end-to-end docking or platform acceptance.

Remaining before deploying this flow: explicit model-change declaration/adoption
controls and native two-stage acceptance; the other preparation boundaries.
Permanent generic model-change provenance is now implemented/tested in source
as described below, but does not itself adopt a repaired input. The 1UY6
candidate remains on hold under the latest backbone-completion preference.

The retained-output reclustering worker prototype also passes eight synthetic
guards (stable coordinates/energies, exact input hashes, chemical states, new
revision only, no docking). Host/GUI revision selection, regenerated interaction
and report references, and real retained-output acceptance remain unfinished.

## Portable warning fixes — source increment, not installed

The [v3 local receipt](../validation/runs/four-area-20261023/model-change-warning-fixes-v3/summary.json)
records 165 focused source contracts and 116 GUI contracts passing. An earlier
broader 182-case run, including actual synthetic protocol-only PDF rendering,
also passed; these overlapping counts must not be summed as unique coverage.
All 395 installed non-cache application files remain unchanged. No docking,
new molecular repair, dependency installation, push or platform certification.

Corrected defects: warning display previously required a legacy removal flag;
screening PDF provenance did not recover inline preparation history when the
original protocol was absent; and the saved-protocol dialog displayed a raw
dictionary. New inline model history is bound to the exact prepared-receptor
hash, persists in bundles and reports, retains high severity and old warnings,
and rejects malformed or mismatched records. Full details stay in the inventory;
reader-facing warnings remain compact. Existing inputs and approval thresholds
are unchanged. The native adoption/declaration path remains unfinished.

The shared warning component was rendered and visually checked for Vina,
QuickVina-W and experimental AD4 labels. This is a component/report check,
not new docking or all-engine native workflow acceptance. The source-dialog
warning preview was also inspected without importing a protocol or granting
approval. The first verification harness reached PDF generation, then failed
metadata extraction because its Python lacks pypdf; the correction uses already
installed Poppler, without changing dependencies. Its record remains preserved.
The second preview's orphaned heading failed presentation review; v3 keeps
headings with their notes and passes the one-page check.

Additional retained detail: 1A4G strict Meeko exchanged terminal O/OXT names at
LEU A465/B465. The heavy-atom coordinate sets are identical, with no heavy atom
added or removed by that exchange. This is recorded as atom-label normalization,
not falsely reported as four physical atom displacements or an extra repair.
