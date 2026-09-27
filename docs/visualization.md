# Visualization commands

The visualization layer consumes files that already exist. It does not run docking or alter input coordinate files.

## Headless PyMOL rendering

```bash
docking-universal render3d scene.pml --out figures/scene.png
```

Accepted input types are `.pml`, `.pse`, `.pdb`, `.pdbqt`, `.mol2`, and `.sdf`.

For an existing PML, Docking Universal lets the scene define its own molecular objects and styling, then applies neutral render settings and writes a ray-traced PNG. For a raw coordinate file, it uses a protein-cartoon/organic-sticks/inorganic-spheres default view.

Useful options:

```text
--width 1800
--height 1400
--dpi 200
--transparent
--pymol /path/to/pymol
```

## Generic 2D depictions

```bash
docking-universal depict2d ligand.pdb ligand_02.sdf --out-dir figures/2d
```

The command uses RDKit when importable. If RDKit is unavailable, it calls Open Babel with 2D coordinate generation. Supported output formats are PNG and SVG:

```bash
docking-universal depict2d ligand.mol2 --format svg --legend none
```

PDBQT input is converted through Open Babel before RDKit drawing when both tools are available. These figures are molecule depictions, not interaction classifications.

## Interaction scenes

```bash
docking-universal interactions complex.pdb --plip-command /path/to/plip
```

This creates PLIP XML/text outputs and an all-in-one PML with interaction objects grouped by type. Ligands use conventional element coloring with gray carbon, and hydrogen-bond markers are yellow. The PML can then be passed to `render3d` for PNG output.

During automatic PDF generation, Docking Universal sends each selected retained
representative SDF, receptor/complex coordinates, and PLIP XML record through the
same approved local PoseEdit-style renderer used by expanded GUI review. The
resulting diagrams retain SDF bond orders and aromaticity, display interacting
side-chain or backbone context, and summarize PLIP contacts for the three top
energy-ranked cluster representatives. Existing report section order, captions,
panel dimensions, and pagination are unchanged. The earlier native SDF-aware
renderer remains an explicit compatibility path when the browser renderer is
unavailable; the generated manifest and log identify the backend actually used.
The external `plip_to_2D` workflow remains the final optional compatibility path.

The graphical screening workspace uses this as its default **cluster synopsis**: one diagram for the lowest-energy member of each selected distinct pose cluster, with clusters ordered by that representative energy. An **expanded all-pose review** is a separate view. It follows the exact pose selected from the retained pose inventory and generates its chemically typed PLIP diagram on demand, caching the result with the pose ID, cluster, score, seed, conformer, model, ligand-chemistry hash, receptor hash, and PLIP record. This prevents the top-scoring poses from one populous cluster from obscuring distinct binding modes, while still allowing every individual docking pose to be inspected.

Expanded review uses the bundled local `docking-universal-render-poseedit.py`
backend. It requires Node.js, Playwright, and a local Chrome/Chromium executable;
paths may be supplied with `DOCKING_UNIVERSAL_NODE` and
`DOCKING_UNIVERSAL_CHROME`. Renderer assets are installed with the application
and never fetched from a CDN. A result is accepted only when collision,
contour-association, crop, renderer-policy, and local-only provenance checks pass.
`docking-universal runtime-inventory` reports Node.js, Playwright,
Chrome/Chromium, and bundled-asset readiness separately and also reports the
composite rendering capability. The Screening Results panel shows this status
before an uncached pose is requested; cache hits remain reviewable even when a
renderer dependency later becomes unavailable.

When live PyMOL is already connected, selecting an expanded-review row also
loads that exact pose's materialized SDF into the dedicated `du_review_pose`
object. This replaces only the prior review pose and leaves the receptor and
retained report session intact. The user can resynchronize explicitly, filter
the pose inventory by cluster, and inspect the 2D diagram at an independent zoom.
