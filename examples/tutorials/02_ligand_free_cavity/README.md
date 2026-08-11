# Example 2: no suitable bound ligand, so cavities are ranked

## Scientific question

Where are plausible docking regions when the experimental structure has no relevant bound inhibitor that can define and validate the pocket?

RCSB 2R8N is the unbound form of HIV-1 subtype C protease. Its coordinate file contains water and glycerol from crystallization. Those small molecules are not treated as a pharmacologically relevant control ligand. The workflow therefore uses protein-cavity detection and marks the docking study `EXPLORATORY_NO_CONTROL`.

The receptor remains rigid during docking. The example supplies one compound for clarity, but `--ligands` can instead point to a multi-record SDF or directory for batch docking. Batch compatibility does not remove the exploratory scientific status or introduce receptor flexibility.

## What the workflow helps you find

The initial PDB inventory shows every exact hetero group and explains why water and glycerol are excluded from automatic control-ligand candidates. Finding a small molecule in a crystal structure does not automatically make it an appropriate pocket-defining ligand. With no relevant inhibitor available, fpocket searches the protein geometry and reports candidate cavities, scores, centers, dimensions, and warnings for review.

The compound-library inventory then identifies every readable SDF record before docking. It displays the compound name, stable folder identifier, formula, formal charge, heavy-atom count, and coordinate-free isomeric SMILES. For a multi-record SDF or SDF directory, all compounds are listed before the first job starts.

Here, indinavir is an example prospective ligand: its chemistry is supplied independently of 2R8N and it does not define the pocket. Its input coordinates are discarded before conformer generation. The resulting poses ask where the configured rigid-receptor search places the molecule; they do not establish binding or biological activity.

## Included inputs

- `inputs/2R8N.pdb`: original unbound RCSB structure.
- `inputs/2R8N_provenance.json`: source and checksum.
- `inputs/indinavir_pubchem_5362440.sdf`: an ordinary prospective compound input from PubChem. It does not define the pocket and is unrelated to the coordinate-free CCD identity lookup used by bound controls.

## Run

From the repository root, activate the main environment and invoke the public interface directly:

```bash
conda activate docking-universal
./bin/docking-universal run \
  --mode exploratory \
  --complex examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb \
  --ligands examples/tutorials/02_ligand_free_cavity/inputs/indinavir_pubchem_5362440.sdf \
  --review-pockets \
  --out examples/tutorials/02_ligand_free_cavity/study
```

`--review-pockets` asks the package to launch PyMOL with the ranked cavity
scenes after preparation. If PyMOL is unavailable, the same `.pml` scenes are
still written for later review. In a non-interactive or headless run, omit the
flag and select the box explicitly with `--box` after inspecting those files.

What each option means:

- `--mode exploratory` records that no approved pose-recovery control is available.
- `--complex` supplies the unbound protein structure for preparation and cavity detection.
- `--ligands` supplies the compound chemistry independently of pocket definition.
- `--out` keeps original inputs, derived structures, poses, and reports together.

The command remains interactive because cavity review and box selection should not be hidden by an example script. In the guided preparation questions:

1. Do not select glycerol (`GOL`) as a bound control ligand.
2. Choose ligand-free cavity detection.
3. Review the ranked fpocket candidates, dimensions, warnings, and PyMOL pocket scenes.
4. Select a cavity and box only after structural review.
5. Confirm the planned exploratory docking effort.

## Expected logic

```text
unbound protein structure
  → distinguish crystallization additives from control ligands
  → prepare receptor
  → detect and rank protein cavities
  → review candidate pocket geometry
  → select an explicit docking box
  → dock independent compound conformers across seeds
  → cluster poses and inspect representatives
  → report EXPLORATORY_NO_CONTROL
```

Repeated poses across seeds show search convergence, not pose correctness. Because no relevant experimental ligand was available for pose recovery, this pathway never writes an approved target-specific protocol.

The terminal explains receptor preparation, hetero-group classification, cavity-mode choices, candidate counts, box selection, compound preparation, docking-job counts, clustering, and report locations. Full third-party output remains in logs so warnings are available without overwhelming the guided display.

## Principal outputs

The `study/preparation/` folder contains receptor and cavity diagnostics. Each compound folder contains its input-named 2D depiction, conformer preparation, per-seed poses and scores, cluster tables, representative PyMOL PNG/PSE files, and PLIP records. The `study/report/` folder provides CSV, JSON, Markdown, and HTML summaries with the exploratory warning.
