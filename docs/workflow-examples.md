# Two ways to start a docking study

Docking Universal includes two complete public-input tutorials under `examples/tutorials/`. They demonstrate different scientific evidence states rather than treating every PDB identically. The tutorials intentionally use the public command directly; no example-specific wrapper scripts hide the options or guided decisions.

Both tutorials use rigid-receptor docking and are compatible with the same batch workflow used for compound libraries. Replace the example ligand SDF with a multi-record SDF or an SDF directory to process multiple compounds; each compound receives independent preparation, replicated docking, clustering, and reporting.

## 1. A relevant ligand is already bound

The 1HVR/XK2 tutorial uses the experimental inhibitor to locate the pocket and test whether the chosen docking settings recover its pose.

```bash
./bin/docking-universal run --mode control \
  --complex examples/tutorials/01_bound_ligand/inputs/1HVR.pdb \
  --out examples/tutorials/01_bound_ligand/study
```

The workflow verifies XK2 chemistry, removes it from receptor preparation, defines a ligand-centered box, generates independent conformers, redocks across seeds, and evaluates sampling and score ranking against the withheld crystal pose. Only a passing control can write an approved target-locked protocol.

## 2. No suitable control ligand is bound

The 2R8N tutorial uses an unbound HIV-1 subtype C protease structure. Water and glycerol crystallization additives are present, but neither is treated as a relevant inhibitor or pose-recovery control. Protein cavities must therefore be detected and reviewed.

```bash
./bin/docking-universal run --mode exploratory \
  --complex examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb \
  --ligands examples/tutorials/02_ligand_free_cavity/inputs/indinavir_pubchem_5362440.sdf \
  --out examples/tutorials/02_ligand_free_cavity/study
```

The workflow prepares the receptor, ranks fpocket cavities, writes candidate centers and docking boxes, pauses for structural review, then asks you to select the docking box to test before docking the example compound. All results are labeled `EXPLORATORY_NO_CONTROL` because cavity ranking and repeated docking cannot replace experimental pose recovery.

## Why both examples matter

| Evidence available | Pocket definition | Result status |
| --- | --- | --- |
| Relevant crystallographic ligand | Ligand-centered box plus retrospective pose recovery | Protocol may be approved or rejected |
| No relevant bound ligand | Ranked protein cavities plus manual structural review | Always exploratory |

Both tutorials create self-contained `study/inputs/`, preparation, compound, pose-analysis, and report folders. Their READMEs explain every guided choice and the expected outputs. The repository ships only compact inputs and representative artifacts; full pose collections are generated locally.

The Bash guide is also a discovery interface. It prints and records all exact PDB hetero groups with candidate/exclusion reasons, then inventories every accepted SDF compound with formula, formal charge, heavy-atom count, stable identifier, and isomeric SMILES. External-tool detail is retained in logs while stage summaries explain what is being calculated and why.
