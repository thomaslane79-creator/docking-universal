# Mac source recovery checkpoint — 2026-11-01

Use branch `recovery/mac-backup-20261027` as the recovery starting point. It is a
self-contained checkout of the saved Mac work, based on published commit
`5719a7ff955f292ded4f0087195366932ab08ba6`. The first recovery commit,
`3bb20ef`, preserves the backed-up working source before recovery-specific test
changes. It adds 60 versioned files and modifies 65. Two generated/cache files
were recovered locally but remain ignored. No raw studies, poses or campaign
outputs were added to Git.

## Source identity and recovered features

The read-only Drive recovery inventoried 721 files, including every tracked file
in the published baseline. All 247 corresponding source files match the SHA-256
hashes in the frozen v13 campaign runtime manifest. The other 179 manifest
entries are dependency files. A separately staged Windows candidate matches
423/426 runtime entries; its three differences are Windows Playwright launch
shims and npm's installation lock metadata. This does not establish Mac GPU
compatibility on replacement hardware.

Recovered work includes Tight (1.0 Å), Default (1.5 Å), Loose (2.0 Å) and Custom
clustering choices, retained-pose reclustering, coordinate-first site review,
explicit receptor/reference review histories, and control-aware reporting.
The experimental GPU engine is AutoDock-GPU/AD4. Native Windows GPU support is
still gated by the existing capability checks.

The source's box-duplicate rule still compares each geometry value within
0.5 Å. It does not implement a new overlap-based duplicate policy. Scientific
defaults, approval thresholds and historical results were preserved.

### Follow-up to the first GitHub CI run

The first general CI run (`41321535367`) passed the six native/build foundation
jobs but failed the Mac and Ubuntu CLI jobs. Mac reached an outdated assertion
that expected clusters without evaluable RMSD to disappear from the CSV, despite
the recovered N/A-strip behavior. That assertion now requires the retained
global rank, unchanged energy, `NA` distance and `unavailable` status.

Ubuntu timed out waiting for preparation cancellation and retained an orphaned
`sleep`. Inspection identified a POSIX cleanup gap: an exited wrapper could leave
descendants holding the reader pipes, and the helper skipped group cleanup once
the leader exited. The follow-up cleans the owned POSIX process group before
joining readers, including signal-ignoring descendants. A deterministic test
fails on the old helper, and real POSIX tests cover completed and cancelled
wrappers. Windows continues to use its existing owned Job Object path.

This is a deliberate process-lifecycle fix after the byte-identical recovery;
it does not change docking parameters, scoring, clustering or scientific
approval rules. Local follow-up checks pass the 48 landscape/report tests and
the 133-test native-foundation group (two platform skips). The real POSIX
regression and complete CLI suites require the corrected GitHub CI run.

## Windows validation

A separate candidate was staged beside the existing Windows application and
used its owned runtimes. The existing application source and launcher were not
replaced. A separate launcher uses an isolated recovery study directory.

- Scientific/recovery tests: 187 run, 165 passed, 22 skipped.
- Qt workflow/review tests: all 147 passed, including exact clustering preset
  values and launch payloads.
- Native portability foundations: 131 run, 130 passed, one skipped.
- Actual Vina and QuickVina-W GUI rehearsals: all 11 steps passed for each,
  including preparation, explicit approval, real docking, PDFs/bundles, linked
  2D/3D review, host/window reopening, cancellation and host lease cleanup.
- Two control PDFs were regenerated from retained five-seed Windows results,
  without redocking. Both include RMSD results and engine provenance and omit
  the earlier false no-docking statement. All 336 retained PDBQT/SDF files in
  each copied control remained unchanged. All six PDF pages were rendered and
  inspected; dense figure labels remain a presentation limitation.

The skips comprise 21 tests using the POSIX preparation fixture and two
platform/symlink comparisons. Their Mac/POSIX coverage remains required. The
recovery follow-up changes only test fixture portability: byte-stable synthetic
PDB records, normalized local-path assertions, platform-aware AD4 expectations
and an explicit POSIX-fixture skip on Windows. It does not weaken application
guards or change molecular data handling.

The first scientific test attempt stopped during plotting initialization;
the first full GUI rehearsal encountered sandbox temporary-directory access
errors. Both failed attempts were retained. The passing runs used a writable
workspace TEMP/TMP, the owned scientific runtime paths and an Agg plotting
backend. These are test-harness settings, not product capability overrides.

## Focused Mac/Windows comparison

Three prepared biotin conformers, the prepared 1STP receptor and box, and the
saved Mac outputs were recovered and verified against their recorded hashes.
Both systems produced 15 poses per conformer at seed 20260810, CPU 8,
exhaustiveness 16, 15 modes and an 8 kcal/mol energy window.

| Conformer | Mac top score | Windows top score | Top-pose heavy-atom RMSD |
|---|---:|---:|---:|
| 1 | -7.463 | -7.437 | 0.316 Å |
| 2 | -7.518 | -7.502 | 0.450 Å |
| 3 | -7.426 | -7.444 | 0.127 Å |

Scores are kcal/mol. RMSD uses recorded atom order in the fixed receptor frame,
without fitting or symmetry correction. Outputs are not byte-identical. The
Mac reference used Vina 1.2.7's persistent Python API with shared maps; Windows
used its pinned Vina 1.2.7 CLI in separate processes. This comparison therefore
does not isolate operating-system differences or establish complete platform
equivalence. New-Mac validation should also match the execution backend.

## Resume the 100-target campaign

The authoritative progress description is
[the protein-panel campaign](protein-panel-100-20261025.md). Its frozen target is
more than 90%, meaning at least 91/100 distinct targets. The latest saved v15
summary records two passes (4ZZN, 7B7R), one interrupted worker (6Q49) and 83
unrun cases, including six reference holds. Earlier records list eleven
completed distinct targets across development builds. That gives thirteen
recorded completions across builds, not a measured single-candidate success
rate or proof that the 91/100 goal was achieved.

Retain the original source/input/library/settings hashes, prior failed cases,
explicit scientific approvals and all outputs. Before continuing, inspect
6Q49's retained worker evidence and cleanup status. Create a versioned
continuation for unaffected unstarted original cases; do not silently retry
completed science, replace targets or adjust the denominator.

## On the new Mac

Clone this branch, or clone its self-contained recovery Git bundle with
`git clone -b recovery/mac-backup-20261027 /path/to/docking-universal-recovery.bundle docking-universal`.
If cloning the bundle, set `origin` to the project's GitHub repository before
fetching or pushing. Follow the existing installation instructions for the
machine's architecture, then run the repository's Mac checks and real-engine
gates before accepting the GPU or resuming the campaign.

Restore the original `validation/local`, `validation/runs` and scientific study
folders separately from the backup. The Git branch does not contain those raw
records. Preserve the original backup unchanged.

The backed-up `python-conversion/.git` was an absolute pointer into
`quickvina-protocol-test/.git/worktrees/python-conversion`. The recovered
checkout/bundle removes that dependency. Do not copy the old `.git` pointer over
the recovered checkout. Old receipts may also contain the original Mac's
absolute scientific paths; adapt a new launch receipt while verifying the same
input bytes and scientific decisions, rather than blindly executing old paths.
