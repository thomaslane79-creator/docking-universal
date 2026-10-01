# GUI idea backlog and implementation gate

Status: active scope-control record, established 2026-09-24.

## Purpose

Docking Universal benefits from ideas discovered while testing the interface,
but repeatedly implementing them before the core workflow is complete makes the
GUI harder to finish and validate. This document preserves those ideas without
silently turning each one into current work.

The active objective is one reliable, chronological, rigid-receptor workflow:

> structure input → preparation → scientific interventions → pocket and
> experimental-evidence review → region approval → protocol finalization →
> screening → linked 2D/3D results review → final reports.

An idea can be valuable and still be deferred. Recording it is not approval to
implement it.

## Implementation gate

Before adding an unplanned GUI option, panel, workflow branch, or dependency,
answer these questions:

1. Does it correct scientific validity, data loss, privacy, or a reproducible
   crash in the supported workflow?
2. Is it necessary to complete an already-supported step in the chronological
   rigid-receptor workflow?
3. Does a current acceptance test or real end-to-end run fail without it?
4. Does it replace existing complexity with a demonstrably simpler interaction
   rather than adding another way to do the same thing?
5. Can it be implemented and tested without delaying the current vertical
   milestone?

Implement immediately only when questions 1, 2, or 3 have a concrete yes and
the change is the smallest defensible correction. Question 4 can justify a
replacement after its migration and regression risk are understood. Otherwise,
record the idea here and continue the active milestone.

The implementation case must name the observed problem, evidence, affected
workflow stage, smallest proposed change, acceptance test, and what current work
would be displaced. “Useful,” “nice,” or “might help” is not enough by itself.

## Expected pushback

When a new request does not pass the gate, the development response should:

- acknowledge the scientific or usability value;
- explain why it is not required for the current milestone;
- identify the additional state, dependency, testing, or interface complexity;
- record it below with a clear revisit condition; and
- recommend continuing the current blocking task.

Pushback should be specific and evidence-based, not dismissive. The user can
explicitly change the active milestone, but the cost and displaced work should
be stated before implementation begins.

## Idea record template

Copy this block for each new idea:

```text
### Idea title

- Date recorded:
- Status: inbox | deferred | accepted for current milestone | rejected | implemented
- User/scientific problem:
- Proposed behavior:
- Evidence or example:
- Dependencies and risks:
- Smallest acceptance test:
- Revisit condition:
- Related roadmap section:
```

## Deferred ideas

### Flexible docking and flexible-residue selection

- Date recorded: 2026-09-24 (consolidating earlier design discussions).
- Status: deferred until the complete rigid-receptor GUI passes acceptance.
- User/scientific problem: related structures, B-factors, occupancy, backbone
  movement, and rotamer changes may show that a rigid receptor makes an
  experimentally supported site inaccessible.
- Proposed behavior: review consolidated evidence, synchronize candidate
  residues with PyMOL, explicitly select flexible residues, and run a validated
  AutoDock Vina flexible-receptor workflow.
- Dependencies and risks: separate receptor preparation, atom/residue mapping,
  control evidence, protocol designation, report semantics, and engine-specific
  validation. Evidence must never be presented as proof of flexibility.
- Smallest acceptance test: a target-matched control demonstrates a valid
  rigid/flexible preparation and reproducible pose-recovery path with retained
  mappings and exclusions.
- Revisit condition: the rigid-receptor GUI completes its real-engine acceptance
  matrix.

### Parallel studies or simultaneous docking jobs

- Date recorded: 2026-09-24.
- Status: deferred.
- User/scientific problem: experienced users may eventually want throughput
  across studies.
- Proposed behavior: manage several independent jobs concurrently.
- Dependencies and risks: resource scheduling, process ownership, progress and
  cancellation semantics, GPU/CPU contention, and substantially broader failure
  recovery. The current design deliberately has one authoritative run.
- Smallest acceptance test: isolated outputs and deterministic cancellation for
  two concurrent studies without oversubscription or state crossover.
- Revisit condition: single-run lifecycle, recovery, and shutdown are proven on
  supported platforms.

### Direct manipulation of docking boxes in 3D

- Date recorded: 2026-09-24.
- Status: deferred.
- User/scientific problem: dragging a box may feel more immediate than editing
  numeric center and size fields.
- Proposed behavior: manipulate box faces or handles in embedded PyMOL.
- Dependencies and risks: coordinate-frame fidelity, picking conflicts, unit
  conversion, accidental scientific changes, undo, and approval invalidation.
- Smallest acceptance test: round-trip geometry exactly matches the retained
  numeric configuration and invalidates stale approval.
- Revisit condition: numeric box editing and immediate 3D updates are complete
  and validated.

### Full dark theme

- Date recorded: 2026-09-24.
- Status: deferred.
- User/scientific problem: a dark workspace may be preferable in some viewing
  environments.
- Proposed behavior: theme the full desktop using the approved inverted assets.
- Dependencies and risks: scientific colors, warning contrast, figures, PyMOL,
  platform styling, and accessibility must remain consistent.
- Smallest acceptance test: contrast and semantic-color review across all
  workflow states at standard and high DPI.
- Revisit condition: the restrained light-theme token system and functional GUI
  acceptance are complete.

### Versioned GitHub Wiki

- Date recorded: 2026-09-24.
- Status: deferred.
- User/scientific problem: users will need an approachable teaching and
  troubleshooting layer in addition to versioned technical documentation.
- Proposed behavior: publish version-aware workflow, installation, evidence,
  viewer, and troubleshooting pages.
- Dependencies and risks: publishing before the workflow stabilizes creates
  duplicated and quickly outdated instructions.
- Smallest acceptance test: every page identifies a compatible release and
  links to the repository documentation that remains authoritative.
- Revisit condition: the first stable GUI workflow is usable.

## Accepted current work

These are not backlog expansion. They are required to finish the active
rigid-receptor milestone:

- structured preparation interventions instead of terminal prompts;
- complete exploratory workflow through a real docking result;
- existing-protocol screening and known-ligand control/calibration routes;
- reliable stage feedback, cancellation, recovery, and clean shutdown;
- linked retained 2D/3D pose review and report generation;
- bounded branding, packaging, accessibility, and supported-platform acceptance.

### Minimal and offline Reduce2 component libraries

- Date accepted: 2026-09-28.
- Status: minimal core and consent-gated acquisition foundation implemented;
  complete offline package pending.
- User/scientific problem: a full GeoStd development clone occupies roughly
  2.4 GB, while Reduce2 must not silently lack restraints or disclose private
  structural information to obtain them.
- Implemented boundary: ship a small standard-protein restraint core; identify
  deposited modified polymer components; disclose exact pinned component
  requests; require explicit approval; cache validated responses with checksums
  and provenance. Retained non-polymer cofactors and metals remain in the
  receptor but do not trigger a restraint download merely by being present.
- Acceptance evidence: the 2R8N filtered receptor completes Reduce2 with the
  minimal core and preserves all 754 heavy atoms; tests verify refusal without
  approval and exact disclosure/audit behavior.
- Remaining acceptance: GUI decision/continuation for a real unusual component,
  Windows/Linux/macOS cache paths, and a versioned complete offline bundle.

### Reviewed GeoStd/CCD bridge for Meeko PTM templates

- Date accepted: 2026-09-28.
- Status: first peptide-PTM bridge implemented and validated with CSO in 1HVR.
- User/scientific problem: Reduce2 can understand a modified residue through
  GeoStd while Meeko may still reject it because the two programs use separate
  template systems.
- Implemented boundary: exact-ID, consent-gated CCD acquisition; local candidate
  generation only for CCD-classified peptide-linking modifications; complete
  non-leaving heavy-atom transfer, N/C peptide-link validation, source hashes,
  explicit user approval, and retained portable provenance.
- Deliberate exclusions: non-polymer ligands, metals, glycans, arbitrary
  cofactors, covalent adducts, and ambiguous backbones are not auto-converted.
- Acceptance evidence: a generated CSO/CSO_N/CSO_C set loads into Meeko 0.7.1,
  and the internal CSO residues in deposited 1HVR are retained in a real
  receptor PDBQT.
