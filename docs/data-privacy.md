# Data privacy boundary

Docking Universal is local-first for scientific structures.

## Non-negotiable invariant

Docked receptors, docked ligand poses, protein–ligand complexes, PLIP XML/text
records, interaction diagrams, and any derived structural evidence must never be
uploaded, submitted, or transmitted to a web service or third-party API.

This applies equally to automated workflows, GUI actions, optional renderers,
diagnostics, crash reporting, and “polished” visualization shortcuts. A network
connection must not be required to inspect or render a docked result.

All interaction analysis and visualization of docked structures therefore runs
locally. External services may be discussed as visual references or used by a
scientist manually with unrelated public structures, but they are not valid
rendering backends for Docking Universal results.

Any future feature that could access the network must be separately approved,
must state exactly what data would leave the machine, and must be disabled for
docked-structure workflows by construction. The GUI should make this boundary
visible in its help text and, where relevant, show a clear “local-only” status.
