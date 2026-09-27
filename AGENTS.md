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
