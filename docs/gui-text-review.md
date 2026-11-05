# GUI text review — 2026-11-04

The requested presentation is a short useful summary, with the full explanation
in a separate window. This pass changes GUI presentation only. The inline 2D
ligand preview, paired 2D/3D window, exact 3D picking, supporting-component reveal
and explicit bound-reference selection remain in place.

## Surface audit

| Surface | Presentation after review |
| --- | --- |
| Study launcher | Short next step; full study/pathway explanation in a window. Reopening and deletion consequences remain visible. |
| Study setup | Labels beside controls when space permits; compact annotated structure counts. Full deposited inventory opens separately. Redocking, region choice and PDB guidance use short summaries with Explain links. |
| Molecule inspector | Compact source summary with a source/selection explanation. Same 2D drawing, 2D/3D window, molecule list and reference action; no chemistry or selection change. |
| Protocol import | Target, recorded scientific status, locked-region count and verification summary stay visible. Import semantics move to explanations. Model/reference warnings remain visible. |
| Preparation | Short stage description; detailed operations in a window. Actual progress, failures, outputs and cancellation stay on the panel. |
| Pocket and ligand evidence | Short lookup and observation summaries. Obstruction warning and residues remain prominent; existing Details and Guide windows retain the geometric rule and limitations. Full counts remain available in Explain and the table. |
| Scientific decisions | Existing separate decision window retained. Choices, consequences and rationale remain beside approval; existing explanation levels retain background/technical detail. |
| Receptor-model review | Short introduction and occupancy/candidate explanations. Exact inventory, changes, box distances, severity and required acknowledgements remain visible. |
| Finalize protocol | One short description per setting; existing ? buttons and Settings guide retain definitions, examples and current values. Workload and exploratory approval remain visible. Site-specific control scope is unchanged. |
| Screening | Short descriptions for analysis, CPU, representative groups and clustering. Full algorithms, examples and platform-specific CPU constraints open separately. Approvals, failure handling and workload remain explicit. |
| Compound library | Short preview-chemistry summary with full explanation. Column approval, selection counts, paging, record errors and 2D inspection controls are unchanged. |
| Results | Short PLIP interpretation with more detail in a window. Energy/affinity warning and scoring-function identity remain visible. Renderer readiness moves into the explanation; missing-renderer errors stay visible. |
| Paired interaction review | Short source statement distinguishes experimental, docked and unknown coordinates; full provenance explanation opens separately. Contacts, residue links, comparisons and image controls stay intact. |
| Full PyMOL and main structural workspace | Inherit compact evidence summaries. Keep already-short navigation/selection/status text, contact legends and existing detail windows. No new viewer, camera or selection behavior. |
| Scientific Detail | Full details opens a separate live technical record without changing the chosen inline detail level. Mandatory event messages are retained. |
| Logs, study files, exports | Keep full diagnostics, paths, export/overwrite consequences and brief progress messages. These are evidence and decisions, not redundant teaching text. |

## Interaction and scientific boundaries

The shared `gui/explanations.py` component opens reusable, modeless, scrollable
windows. Explain links work by mouse and by Tab followed by Enter/Space. Source
strings are escaped as literal data; help does not fetch external content.
Repeated passive refreshes preserve reading position, and changed context updates
the existing window. Close remains usable when study inputs are locked.

PDB sequence disclosure, exploratory status, untested control scope, receptor
changes, incomplete references and explicit approval wording remain visible.
All scientific defaults, exact ligand identities, source hashes, numerical
settings, one-run policy, reports and persisted study data are unchanged.

## Verification

- 200 targeted GUI, viewer, protocol-import and authority tests pass. The import
  fixture now uses the executing interpreter instead of one developer's absolute
  Anaconda path.
- The shared explanation is tested with literal markup, mouse and keyboard
  activation, reopening/current content, scroll preservation and locked inputs.
- Native macOS rendering checks ten surfaces at 960 and 1280 pixels: 138 checks
  pass, including wrapping, horizontal fit, unchanged input and no approvals.
- Existing protocol layout validation passes 231 checks at three sizes across
  Vina, QuickVina-W and AD4 presentation. AD4 is a display-only fixture where the
  isolated process has no configured GPU runtime; no engine is launched.
- Screening layout and explanation validation passes 80 checks at three sizes.
- The real native ligand-viewer test still selects ID8 B:602 by mouse in the
  filtered full-structure view, synchronizes 2D and applies only through the
  explicit reference action. Source/private-study bytes, camera, wizard state,
  redocking option and screening selections are preserved.
- Twelve installed GUI modules match source hashes, with previous files backed
  up. Four additional checks against the installed modules pass.

The comparison uses identical display fixtures and Qt settings before/after
commit `7030f57`. Counts below are visible label/button words at width 960, not
full documents or generated scientific records. Full explanations are excluded
from the inline count but remain available.

| Surface | Before | After | Reduction |
| --- | ---: | ---: | ---: |
| Setup form, without the separate molecule inspector | 168 | 94 | 44% |
| Preparation | 44 | 31 | 30% |
| Protocol settings | 395 | 193 | 51% |
| Screening settings | 325 | 153 | 53% |
| Site evidence | 63 | 39 | 38% |
| Results | 77 | 60 | 22% |
| Protocol import | 81 | 41 | 49% |
| Receptor review | 176 | 105 | 40% |
| Decision review | 33 | 33 | Unchanged |
| Study launcher | 44 | 33 | 25% |

Reproduce the surface review with `validation/gui_text_review.py --output <out>`;
optionally supply `--structure <local.cif>` and `--baseline-gui <prior-gui-dir>`.
The two existing settings-guidance scripts cover narrower layout and help
checks. Native screenshots are private validation artifacts, not repository
assets or scientific results. This acceptance covers presentation on this Mac;
it is not a fresh cross-platform docking accuracy assessment.
