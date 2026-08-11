# Example 1: bound ligand defines and tests the pocket

## Scientific question

Can the workflow identify the crystallographic XK2 inhibitor in 1HVR, use it to define the docking region, and recover its experimental pose under repeatable search settings?

This is the appropriate pathway when a relevant bound ligand is present. It is both a geometric pocket reference and a retrospective control. The experimental coordinates are withheld from independent conformer generation and used only during RMSD evaluation.

Docking uses a rigid receptor. Ligand flexibility and independent conformers are sampled according to the recorded engine protocol. After a protocol passes, the same settings can be applied to a multi-compound SDF or SDF directory through the batch-capable `run --mode screen` workflow.

## What the workflow helps you find

Before preparation, the Bash guide inventories every exact non-protein `HETATM` group in the PDB. It separates eligible ligand candidates from water, crystallization additives, ions/metals, modified polymer residues, and very small groups. Eligible candidates are displayed as `RESNAME:CHAIN:RESIDUE` with atom counts, so multiple copies of the same compound are not silently combined.

For this structure, the relevant question is not merely “is a hetero group present?” but “which exact compound is a biologically relevant experimental ligand suitable for defining and testing this pocket?” The user confirms XK2; the CCD lookup then verifies chemical identity without supplying a docking conformation.

In general, a **ligand** is a molecule or ion associated with a macromolecule. PDB hetero groups can also be buffers, solvents, crystallization additives, cofactors, metals, substrates, products, or inhibitors. Automated candidate detection narrows the list but does not replace biological interpretation.

## Included inputs

- `inputs/1HVR.pdb`: original RCSB experimental complex.
- `inputs/rilpivirine_pubchem.sdf`: a public 2D chemical definition of rilpivirine, used only after calibration as a held-out, flexible known-inhibitor screen.
- `inputs/nevirapine_pubchem_4463.sdf`: an optional smaller known-inhibitor input for comparison.
- XK2 chemical identity is retrieved automatically as coordinate-free isomeric SMILES from the RCSB Chemical Component Dictionary after the ligand instance is confirmed. No CCD ideal-coordinate SDF is included or used.

“Coordinate-free” retains the 2D chemical graph—atoms, bonds, bond orders, charge, and defined stereochemistry—but no supplied 3D conformation. The docking ensemble is embedded independently. Only the ligand coordinates extracted from `1HVR.pdb` are retained as the withheld RMSD reference.

## Run

From the repository root, activate the main environment and invoke the public interface directly:

```bash
conda activate docking-universal
./bin/docking-universal run \
  --mode control \
  --complex examples/tutorials/01_bound_ligand/inputs/1HVR.pdb \
  --out examples/tutorials/01_bound_ligand/study
```

What each option means:

- `--mode control` selects retrospective pose-recovery calibration rather than prospective screening.
- `--complex` identifies the original experimental protein–ligand PDB.
- `--out` creates a self-contained study folder without modifying the packaged input.

The command remains interactive because ligand identity, chemistry verification, and escalation of search effort are scientific decisions. In the guided questions:

1. Select the exact ligand instance `XK2:A:263` after reviewing its atom count.
2. Use strict chemistry verification. The CCD-derived template should match XK2.
3. Begin with the quick diagnostic tier.
4. If the quick tier is not approved, choose **Guided incremental calibration**. The guide interprets whether the limitation is seed evidence, search depth, or conformer coverage and proposes the next least-complex informative tier.
5. Confirm each proposed tier after reviewing its conformer count, seed count, exhaustiveness, and job count. The first reproducible passing tier becomes the recommended protocol.

Manual tier selection remains available for experienced users, but a manually chosen passing tier cannot establish that less expensive settings are adequate. In the current 1HVR/XK2 example, guided repeatability (three conformers × five seeds at exhaustiveness 16) passed, so it is the efficient protocol record to transfer.

## Expected logic

```text
experimental complex
  → identify and verify XK2
  → copy immutable inputs
  → prepare receptor with XK2 removed
  → define ligand-centered box
  → generate independent ligand conformers
  → redock across seeds
  → compare every pose with crystal XK2
  → approve or reject a target-locked protocol
```

The control result may fail. Failure is scientifically useful: it means those settings should not authorize unknown docking. A passing retrospective control supports the recorded target-specific protocol but does not prove prospective accuracy.

## Held-out known-inhibitor demonstration

After an approved control, screen rilpivirine with the resulting locked protocol:

```bash
./bin/docking-universal run \
  --mode screen \
  --protocol examples/tutorials/01_bound_ligand/study/control/04_redocking/vina/repeatability/protocol.json \
  --ligands examples/tutorials/01_bound_ligand/inputs/rilpivirine_pubchem.sdf \
  --out examples/tutorials/01_bound_ligand/study/rilpivirine_held_out_screen
```

Rilpivirine is a known HIV-1 RT non-nucleoside inhibitor, so this is not presented as a blind prospective prediction. It is larger and more conformationally flexible than the calibration ligand, making it a useful demonstration of independent conformer generation and pose clustering. It demonstrates that the locked control protocol can prepare and dock a different compound in the same target context. Its docking score and proposed pose remain computational hypotheses, not experimental confirmation.

The terminal reports each major stage in plain language and sends detailed Meeko, fpocket, Vina/smina, PLIP, and PyMOL diagnostics to retained log files. This keeps progress readable while preserving evidence for troubleshooting.

## Principal outputs

Look under `study/control/` for experimental-ligand chemistry, prepared receptor and box files, per-seed docking scores, RMSD comparisons, PyMOL scenes, PLIP reports, and—only when acceptance rules pass—`protocol.json`.
