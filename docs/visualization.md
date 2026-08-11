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

During automatic PDF generation, Docking Universal draws each selected ligand from its retained representative SDF and maps the PLIP XML contact coordinates onto that chemically typed molecular graph. The resulting diagrams retain SDF bond orders and aromaticity while summarizing PLIP contacts for the three top energy-ranked cluster representatives. They are convenient review figures rather than replacements for the retained PLIP XML/text records. The modified external `plip_to_2D` workflow is retained only as an optional fallback when an SDF-aware diagram cannot be produced.
