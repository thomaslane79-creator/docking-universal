# Current 2D renderer and centering acceptance

The saved public Rilpivirine test run contained an older static interaction
diagram. Native paired-view access worked, but that image lacked the current
renderer’s verified residue hit regions. Its ligand click still worked: moving
the 3D focus to another atom and clicking the drawn ligand recentered it with
the same zoom. A centered ligand naturally shows no further movement.

The user clarified that **centering must preserve zoom**. The temporary proposed
zoom change was reverted before installation or commit. The heading and diagram
retain the same exact-ligand centering action; residue-label clicks center their
exact source residue without changing scale or visibility.

## Missing browser dependency

The installed renderer had Node.js and pinned Playwright 1.63.0, but no local
Chromium-family browser. Report generation already prefers the current renderer
when available and can retain the older drawing as a fallback. Completing this
dependency restores that preferred path; opening a saved image alone does not
regenerate it or change its provenance.

The installer now checks for an existing local browser and, when needed, obtains
Playwright’s compatible private Chromium revision inside the selected Conda
prefix. On this Mac that is Chrome for Testing 153.0.8010.12, revision 1243.
The package also acquired its FFmpeg runtime; no movie generation was used.
The ordinary browser installation is unchanged. Playwright documents its
[version-specific browser installation](https://playwright.dev/docs/browsers).

The registration records the executable path/digest, browser/package versions
and acquisition origin in `share/docking-universal/renderer-browser.json`.
GUI and scientific-worker discovery share this registration, accept only paths
inside the application’s browser cache, reject a changed executable and preserve
explicit browser overrides. Browser acquisition uses the network; structure
rendering uses bundled scripts and local inputs, with no structure upload.

## Actual verification

The installed current renderer regenerated Rilpivirine cluster 002 from the same
retained ligand, receptor and PLIP report into an isolated validation copy.
No docking, receptor preparation or PLIP calculation was rerun. The original
diagram and sources remain hash-identical. Its layout audit reports zero label
collisions, and its image/report-bound map contains 17 residue-label regions.

The native GUI now shows this current image beside the exact retained 3D pose.
Clicking its LYS A:134 label centers that residue; clicking the drawn ligand then
recenters the ligand. Both retain zoom. PLIP/residue visibility controls remain
available. The installed runtime inventory reports every renderer component
available. A terminal-sandbox attempt could not start macOS Chromium services;
the normal native-host render completed successfully.

The complete local `make test` regression suite passes, together with 31 focused
browser/runtime/Windows-installer contracts and the bootstrap shell checks.
The broader branch checks also exposed one old assertion requiring
P1 to remain a separate option even when it shares the complete ligand with B1.
That assertion now verifies retained predictor provenance inside the grouped
site, consistent with the user’s requested behavior.

Local receipts/images are under `validation/runs/current-renderer-20261108/`;
installed originals and hashes are under
`local-fix-backups/private-renderer-20261108/manifest.json`. These generated
private records are not committed. The screening PDF’s missing ADFRsuite version
remains an independent open repair.
