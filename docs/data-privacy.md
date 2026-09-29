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

## Public chemical-component restraints

The standard-protein Reduce2 route uses a bundled minimal GeoStd library and
does not require a network request. If an unusual retained receptor component
lacks local restraints, an optional request may retrieve only that public
component's GeoStd CIF from a pinned revision of the official
`phenix-project/geostd` repository. Before retrieval, the application must show
the exact component identifiers and URLs. GitHub receives those identifiers in
the URL plus ordinary connection metadata such as IP address and request time.

No coordinate file, atom coordinates, ligand file, private chemical structure,
docking box, pose, score, result, study name, or report is included. Retrieval
is disabled until explicitly approved. Custom or unrecognized identifiers must
not be submitted automatically. Each approved response is validated, checksummed,
cached locally, and recorded in provenance. A complete offline-library option is
planned for installations that cannot make such requests.
