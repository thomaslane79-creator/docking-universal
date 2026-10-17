# Development checkpoint — October 17, 2026

This checkpoint preserves the pending development work since the October 3
`architecture/scientific-gui-transition` commit `eb3116a`. It is a development
snapshot, not a new release or a claim that every supported platform/engine has
passed a fresh end-to-end test.

Included work covers the interactive desktop and linked PyMOL/2D review,
visual exports, shared reporting, clustering, compound selection and tabular
SMILES import, protocol reuse/site-first evidence review, receptor frame guards,
CPU execution work and the optional experimental AD4 GPU integration. Source,
tests, compact fixtures, documentation, validation drivers and the local upstream
GPU patch are versioned together. Engine differences, numerical checks, known
limitations and acceptance records are described in the corresponding documents.

## Storage boundary

The development files being checkpointed total approximately 3.4 MiB before Git
compression; no newly added individual file approaches GitHub's 100 MiB limit.
The repository reported approximately 59 MiB on GitHub before this push.
No Git LFS storage, release upload or paid service is introduced.

Approximately 8 GiB of generated/untracked data is deliberately **not** uploaded:
raw `validation/runs/` experiments (including downloaded packages/build trees),
`GUI Tests/` study folders, `.docking-universal-state/`, generated `output/`
reports and `tmp/` previews. Existing ignore rules also exclude logs, PyMOL
sessions, caches and dependency installations. Nothing in these folders is
deleted. They remain local and require a separate backup if they must survive
loss of this computer. Raw local run paths mentioned in validation documents
are not downloadable assets in this GitHub checkpoint.

## Checks at checkpoint time

- Python syntax parsing passed for 331 source/test/validation files.
- 87 focused scientific import, selection, screening and host checks passed.
- 121 focused GUI, host, workflow and protocol-import checks passed.
- Application/documentation whitespace checks passed. The saved upstream GPU
  patch deliberately retains upstream context indentation/blank-line whitespace,
  which produces Git whitespace warnings; those context lines are not rewritten
  merely to silence warnings and potentially affect patch applicability.
  The pending development files were checked for
  oversized additions and common private-key/API-token patterns with no findings.
  This is a bounded scan, not a guarantee of exhaustive security review.
- The preceding installed tabular-import acceptance passed 22 real GUI/host/
  subset-materialization checks and verified source/installed module hashes and
  unchanged protected study/result hashes. See
  [tabular import validation](tabular-ligand-import-validation.md).

No preparation, docking, scientific approvals, changes to saved studies, history
rewrite, merge to `main`, or full integration benchmark is part of this Git
checkpoint. Existing historical validation claims retain their original scope.
