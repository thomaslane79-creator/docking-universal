# Docking Universal development guidance

## Current priority

Complete and validate the chronological rigid-receptor GUI workflow described in
`docs/gui-decision-completeness-plan.md`. Prefer finishing a real vertical path
over adding more interface options.

## Scope control

Before implementing a newly suggested GUI feature, read
`docs/gui-idea-backlog.md` and apply its implementation gate. Push back when the
request does not solve a demonstrated correctness, safety, crash, or current
acceptance problem. Explain the concrete cost and record the idea instead of
silently expanding scope. Do not treat recording an idea as approval to build it.

The user may explicitly change priorities after reviewing the tradeoff. When
that happens, update the backlog status and relevant roadmap before implementation.

## Scientific boundary

Preserve explicit scientific decisions, provenance, local-only docked structures,
existing report meanings, and one authoritative active run. Flexible docking,
parallel jobs, direct 3D box manipulation, a full dark theme, and the GitHub Wiki
remain deferred until their recorded revisit conditions are satisfied.

## Existing GUI behavior

For interaction, selection, renderer or viewer changes, run `make test-gui` in
an environment with real Qt support. Do not report scientific-suite GUI skips
as GUI validation. Cover both reopened existing studies and new reviews when
changing their presentation. Preserve centering without zoom, paired exact
2D/3D identity, deselection, PLIP switches and selection through refresh.
Changes to these established behaviors require an explicit user decision.
Verify affected native interactions after installation when changing window
reparenting, rendering or event handling; offscreen tests do not prove GPU or
native-window acceptance. Record what was actually exercised.
