# Explicit preparation review: development checkpoint

Status: development source/private Mac validation, **not installed**. The goal is
workflow completion across more proteins, with accuracy assessed separately.
The working Mac installation, original studies, historical failed cases and
scientific defaults remain unchanged. No dependencies, engine registrations,
GitHub branch, release or operating-system acceptance have been changed.

Final local [audit and linked receipts](../validation/runs/preparation-review-20261025-final/summary.json):
three functionally completed workflows, three new searches, nine native
representatives and 395 unchanged installed application files. Presentation
limits and unsupported preparation cases remain disclosed separately.

## What the review step does

After approving docking regions, choose ordinary preparation or **Review an
explicit receptor-model change…**. The latter also remains available after a
safely failed preparation. The original input, old failure and reviewed boxes
are retained. Every modified attempt gets a new directory.

- Alternate-location choices show each exact residue and its deposited
  occupancies. Nothing is selected automatically. A/B are deposited labels,
  not quality grades; greater occupancy does not establish the correct binding
  conformation. Shared blank-location atoms are retained; the selected deposited
  coordinates remain exact, and their location labels are normalized to blank.
- Exclusions require exact residue name, chain, number and insertion code.
  They are optional and not recommended. A similarly numbered ligand or another
  chain is not removed accidentally. Standard-amino-acid exclusions carry high
  severity and need an additional explicit acknowledgement. Removing all protein
  coordinates is refused. No backend-wide `allow_bad_res` flag is substituted.
- Preview shows the actual changes, excluded atom count and affected residues'
  distances to every selected box. A residue inside a box has distance zero.
  Distance is review evidence, not permission to ignore chemistry or remove it.
- Editing a choice invalidates the preview and acknowledgement. Execution needs
  the current revision, exact preview hash, approval actor and rationale.
  Changed original inputs, boxes or approval evidence are rejected.
- The reviewed derivative receives one strict Meeko preparation attempt. It
  does not automatically try more repairs, choose other locations, remove more
  residues or use a legacy fallback. An additional issue remains a stopped case.
- Successful preparation binds portable model history to the original input,
  derivative and prepared-receptor hashes. The warning remains on box review,
  through protocol export/import, screening summaries and the shared reports.
  Reopening does not repeat preparation or docking, and does not erase warnings.

This is not automatic gap/loop construction or a general repair builder. In
particular, PDBFixer's earlier `missingResidues = {}` policy did not prevent
backbone atoms from being constructed inside an observed partial residue. The
source helper now inventories missing atom names and rejects that construction
before writing a repaired receptor. The original 1UY6 candidate remains on hold;
extensive 1FM6 reconstruction/deletion remains disallowed under the user's latest
direction. An arbitrary externally edited input still needs a separate explicit
declaration/adoption path; the application cannot infer its history from one file.

## Retained evidence

The [local joined checkpoint](../validation/runs/preparation-review-20261025-v5/summary.json)
links the source contracts, native stages, prepared model, portable bundle and
new docking evidence. One 1A4G receptor parameterization and one new Vina search
completed, with three native representative reviews and a fresh-host reopen.
Exactly NAG A:1 and B:1 were excluded under the prior explicit approval; no atom
was constructed or retained coordinate moved by that exclusion. The saved-box
warning was then checked natively from a copied study without a new scientific
job. The final display/integrity increment passes 118 focused source and 123 GUI
contracts; these overlap broader test groups and are not independent proteins.

The application stages completed across linked validation attempts. Preserve
the interrupted coordinator records: the first adapter conflicted with an
inherited mocked dialog method; the isolated package then lacked the real
`VERSION` file; a later assertion omitted the archive's established `protocol/`
prefix. Corrected adapter/package continuations reused the exact reviewed sites
and successful prepared receptor. They did not repeat successful preparation or
searches, invent versions or weaken the report's provenance requirement.

Both original protocol PDF pages and all six screening PDF pages were inspected. The
model-change warning is present and legible. The screening report's reference
list spills onto a mostly empty sixth page, so its presentation gate remains
failed; dense plot/molecular labels also need further layout review. This is
separate from successful docking/output generation and is not concealed as
blanket visual acceptance. The original 100-case cohort counts are unchanged.

## Explicit 4EY7 follow-up

The user approved testing these deposited conformations on 2026-10-25:

| Residue | Selected location | Deposited occupancy |
| --- | --- | --- |
| GLN A54 | B | 0.57 |
| GLU A313 | B | 0.55 |
| HIS A381 | A | 0.54 |
| ARG A525 | B | 0.56 |
| HIS B381 | A | 0.51 |
| ARG B525 | A | 0.55 |

The previously approved exclusions are NAG B604, C1, C2, D1 and D2; FUC C3
and D3. The [exact-choice staging record](../validation/runs/preparation-review-4ey7-20261025-v1/staging.json)
retains the explicit authorization; the [native outcome](../validation/runs/preparation-review-4ey7-20261025-v1/postflight.json)
now confirms one successful strict preparation and one new Vina search. The
case completed clustering, PLIP/2D, protocol and screening PDFs, three native
representative reviews and fresh-host reopening. Only the seven exclusions and
six deposited-location choices above were applied. The original input, reviewed
box and permanent model-change history remain bound to their hashes. No heavy
atoms were reconstructed by the model-change step. All workers cleaned up. This
retest is exploratory and separate from the historical cohort.

## Ordinary mmCIF path and report corrections

A separate new 1STP/BTN workflow passed the ordinary two-stage path using the
original mmCIF input, optional P2Rank and QuickVina-W. Site review preceded
parameterization; the exact approved B1 box and original mmCIF source identity
survived it. No explicit model changes or PDBFixer rescue were used. One new
search completed with PLIP/2D, PDFs, three native representative checks and a
fresh-host reopen. See its [native receipt](../validation/runs/preparation-review-routine-20261025-v1/native/routine-1stp-mmcif-qvinaw/attempt-001/worker/raw-preparation.json).

These three new workflows comprise two reviewed-change Vina paths and one
ordinary mmCIF/P2Rank/QuickVina-W path: **three actual searches**. The known
structures were used to develop this flow; they do not establish the prospective
90% protein-completion target or change the original cohort counts.

Visual inspection failed the original reports' presentation gates. The long
4EY7 warning split across pages and short bibliography tails were orphaned.
The ordinary case also retained an incorrect fpocket caption and ligand-free
heading even though P2Rank was requested and B1 was ligand-defined. Development
source now keeps the warning and page-sized bibliography together, uses the
recorded detector name, and distinguishes approved B1 from colored predicted
P1 in the ranking legend and caption. It assigns no prediction score to B1.
The [pagination copies](../validation/runs/preparation-review-report-layout-20261025-v1/summary.json)
and [B1/P2Rank copies](../validation/runs/preparation-review-report-layout-20261025-v2/summary.json)
use retained local evidence with no new preparation or search. Original files,
coordinates, poses and other scientific assets were verified unchanged.
Original failed presentation records remain failed. Dense figure labels,
whitespace and partial native-cartoon occlusion still limit blanket visual
acceptance; the specific warning/selection corrections are separate gates.

The actual GNU Make test target passed all 52 recipes: 31 Python groups reported
851 case executions including 95 runtime skips, followed by 21 shell checks.
These groups overlap and are not 851 unique executed passes. After the final
report-only correction, 84 focused report/model-history/figure tests passed.
The separate 123 GUI checks and 118 source contracts overlap those broader
groups. The final installed-app audit still matches all 395 non-cache files.

## Remaining scope

The approved 4EY7 retest and ordinary mmCIF vertical path are complete
functionally. Side-chain repair generation/review, manual-input declaration,
multiple-region coverage, retained-result reclustering and the remaining report/platform
gates are still open. New native Windows model-change operations are explicitly
rejected until accepted; their controls and CPU support claims remain those of
the earlier bounded Windows profile. No GPU or engine-equivalence claim follows
from these CPU tests. The independent 100-protein acceptance panel is not yet
curated or launched; see the [completion plan](protein-completion-plan.md).

Subsequent checkpoint: the [prospective panel](protein-panel-100-20261025.md)
is now frozen and its first ten workflows have launched. The three development
retests above remain separate and are not counted as new panel outcomes.
