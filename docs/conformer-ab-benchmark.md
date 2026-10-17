# Paired conformer preparation benchmark

## MMFF94 versus MMFF94s follow-up

`validation/mmff_variants.py` compares both vacuum MMFF variants using the exact
independent embedding pools from completed controls. MMFF94s means *static*, not
solvent-aware. Production defaults are unchanged. This follow-up requires no
xTB execution or new receptor preparation.

Preparation uses `--source` with one or more completed benchmark directories and
a new `--out` directory. It first requires the same RDKit version, identical
regenerated pool hash, and reproduction of MMFF94 minimization energies, retained
IDs and unfitted coordinates. Only then are the existing MMFF94 docking results
reused. The indinavir baseline must be the corrected `_framechecked` run.
Both variants minimize before identical heavy-atom RMSD pruning; minimized
energy ranks conformers only within each variant, not across variants.

After preparation, run the same output with `--dock`. The series runs sequential
MMFF94s docking with the original receptor, box, seeds and search budget. Only
machine-identical retained coordinates skip repeat docking. No automatic restart
of partial or completed jobs is permitted. `series.json`, case `summary.json`,
`conformation_comparison.json`, and `comparison.csv` retain provenance,
exclusions, timing and results. Lowest-Vina-score pose crystal RMSD and recovery
within 2 Å are primary; best-of-poses RMSD remains secondary.

This is a small, rigid dry-receptor benchmark using one chemical state per
ligand, not proof of superiority or experimental binding-affinity validation.

This is an isolated local test, not a change to production defaults. It uses no
LLM, GUI, network lookup, OpenFF, or Reduce2 database during conformer optimization. Upstream
receptor preparation for the matched controls uses the existing Reduce2 setup.
Both arms run sequentially
on one CPU and produce a side-by-side CSV. Use larger flexible ligands first:
the existing indinavir example is a useful starting input; then test several
known bound ligands with matched chemistry and prepared receptors. Size alone
does not guarantee that a ligand will discriminate between methods.

## Preparation-only test

Run from `/Users/crown2/Documents/ChatGPT/Docking-Universal/python-conversion`:

```sh
/opt/anaconda3/envs/docking-universal/bin/python validation/conformer_ab.py \
  --ligand examples/tutorials/02_ligand_free_cavity/inputs/indinavir_pubchem_5362440.sdf \
  --out validation/runs/conformer-ab/indinavir_mmff_vs_water \
  --xtb /absolute/path/to/xtb \
  --attempts 16 --keep 3 --rmsd 0.75
```

RDKit is required in the Python environment; the external `xtb` executable must
be available. The script does not install it, download anything, or substitute
vacuum optimization when solvent optimization fails. A missing dependency fails
before the output directory is created. Use a new output directory each time.

- `vacuum_pruned`: MMFF94 vacuum minimization, then RMSD pruning.
- `water_pruned`: GFN2-xTB/ALPB water minimization, then identical RMSD pruning.
- Both start from the exact same independent ETKDGv3 coordinates, generated from
  chemistry, never from the input/crystal coordinates. No pre-minimization
  RMSD pruning. Nonconverged geometries are excluded and audited.
- One exact supplied SDF chemical state per run. This benchmark does not
  enumerate protonation/tautomer states; supply each intended state separately.
- Greedy selection ranks converged conformers by energy **within each arm**,
  retains up to three distinct representatives, and does not pad with duplicates.
  RMSD is symmetry-aware, aligned, heavy-atom RMSD (default 0.75 Å).
- This first comparison changes both optimizer/energy model and solvent. To
  isolate solvent, repeat with `--vacuum-backend gfn2` and a new output directory:
  the two arms then use GFN2-xTB vacuum versus GFN2-xTB/ALPB water.

`comparison.csv` contains counts, exclusions and minimization time.
`summary.json` retains settings, hashes, versions, energies, selected input IDs,
pruning dispositions and failures. `shared_initial_pool.sdf` and each arm's
`retained.sdf` permit inspection; external commands and logs are retained.
Absolute MMFF and xTB energies must not be compared. Neither minimized energy is
a full conformational free energy/population estimate. ALPB water is a bulk
solution approximation, not the protein binding-site environment.

## Optional equal-budget redocking

Add these options to the same command (replace paths with a real matched control):

```sh
  --receptor-pdbqt /absolute/path/to/prepared_receptor.pdbqt \
  --receptor-pdb /absolute/path/to/prepared_receptor.pdb \
  --box /absolute/path/to/box.conf \
  --crystal-ligand /absolute/path/to/exact_bound_ligand.pdb \
  --vina /opt/anaconda3/envs/docking-universal-vina/bin/vina \
  --dock-seeds 41001 41002 41003
```

The crystal ligand must be the exact matching residue instance in the receptor's
coordinate frame, with matching chemistry. All receptor preparation, biological
assembly and box decisions remain upstream, shared and unchanged. The box config
must contain only the six `center_x/y/z` and `size_x/y/z` entries. Meeko's
`mk_prepare_ligand.py` and `mk_export.py` default to the scientific Python's bin
directory; override `--meeko`/`--mk-export` if necessary.

Both arms use Gasteiger charges for Meeko/Vina, the same receptor, box, seeds,
exhaustiveness (8), modes (9), energy range (3 kcal/mol), and one CPU. Minimized
SDF coordinates go directly to Meeko without an additional geometry optimizer.
If an arm has fewer distinct representatives, both dock the smaller number:
no duplicate padding, and the actual docked IDs/budget are recorded.

Per seed, the comparison reports the lowest-Vina-score pose across conformers,
its experimental RMSD and recovery at 2 Å; best RMSD among all poses is secondary.
The existing redocking comparator measures symmetry-aware **unfitted** RMSD in
the receptor frame, unlike the aligned RMSD used to prune starting conformers.
Individual pose tables/overlays are retained. Tied docking scores use stable
generation order, never crystal RMSD to pick a favorable winner.

Start with 16 attempts/3 retained and one docking seed to check the workflow;
then increase attempts (e.g. 36), seeds and the number of matched controls. Large
ligands can require longer optimizations: adjust `--timeout` (600 seconds per
external command) deliberately. This is not a claim that the water arm is better.

Primary method documentation:
[xTB ALPB](https://xtb-docs.readthedocs.io/en/latest/gbsa.html),
[RDKit alignment](https://www.rdkit.org/docs/source/rdkit.Chem.rdMolAlign.html).

## Validation status (2026-10-05)

Fifteen local benchmark tests pass, including real indinavir embedding/MMFF minimization
and post-minimization pruning, deterministic input-coordinate independence,
stereocenter inversion rejection, RMSD fitting without input mutation, logged
external failures, no solvent-to-vacuum fallback, and equal-budget/top-score
redocking bookkeeping, plus relative executable-path resolution before changing
subprocess directories. External xTB and docking execution are mocked in those
bookkeeping tests, not scientific results. Missing-xTB preflight was verified.
The fixture preserves crystallographic frame metadata and checks receptor
coordinate anchors after both Reduce2 and Meeko; a frame change stops the test.

A real indinavir preparation comparison has now completed using xTB 6.7.1,
installed only in `.benchmark-tools/xtb` (48 MB; ignored by Git), without changing
the working docking environment. All 16 optimizations converged in each arm;
both retained three conformers, with different rankings. MMFF took 2.35 seconds;
GFN2-xTB/ALPB water took 302.61 seconds on one CPU. No minimized conformer pairs
were below 0.75 Å in this pool. Results and method limitations are recorded in
`validation/runs/conformer-ab/indinavir_mmff_vs_water_20261004_run2/results.md`.
The first attempt exposed a relative executable-path bug, which was fixed and
covered by the twelfth test; its failed audit directory was preserved.
The paired indinavir/2R5P redocking comparison completed in
`validation/runs/conformer-ab/indinavir_2r5p_redocking_20261004_framechecked`:
18 matched jobs (three conformers, three seeds, two arms). Both arms recovered
the crystal within 2 Å with their lowest-score pose in all three seeds.

| Seed | Vacuum lowest-score pose RMSD (Å) | Water lowest-score pose RMSD (Å) |
| --- | ---: | ---: |
| 41001 | 1.221 | 0.737 |
| 41002 | 1.316 | 0.721 |
| 41003 | 1.241 | 0.731 |

The closest vacuum pose overall was 0.955 Å at −10.463 kcal/mol, not the
lowest-score pose. The closest water pose was 0.721 Å at −11.764 kcal/mol.
Aligned cross-arm conformer comparisons show distinct retained starting
geometries (closest pair 1.715 Å). These are one-structure results and change
both the optimization model and solvent; they do not establish general
superiority, active/decoy discrimination, or a production-default change.
An earlier run without the `_framechecked` suffix is invalid because receptor
preparation translated coordinates relative to the box/reference; it is
retained for audit and must not be used as evidence.

## Four additional controls

The sequential series at `validation/runs/conformer-ab/four_more_20261005_ready`
has passed native receptor preparation, exact chemical identity/stereochemistry
and coordinate-frame checks for all four examples:

| Ligand | Structure | Exact ligand instance | Receptor chains |
| --- | --- | --- | --- |
| Tipranavir | 2O4P | TPV:A:300 | A, B |
| KNI-577 | 1MRW | K57:A:1001 | A, B |
| Imatinib | 1IEP | STI:A:201 | A |
| Geldanamycin | 1YET | GDM:A:275 | A |

The series was started on 2026-10-05; `series.json` is authoritative for current
progress. All four run sequentially with 16 embedding attempts, three retained
conformers, 0.75 Å post-minimization pruning, three matched seeds and one CPU.
Inputs are one exact neutral chemical state, without protomer/tautomer enumeration.
The dry, rigid control fixtures and limited target diversity constrain interpretation.
The original tipranavir/1D4Y candidate failed strict preparation because of
incomplete residues; that failure remains in `four_more_20261005`, and the
declared replacement is 2O4P. No unsafe-residue bypass was used.

`docking_comparison.csv` is written after all cases terminate; each case retains
its own `benchmark/summary.json`, `comparison.csv`, conformation comparison and
native logs. Independent cases continue after a failure, but failures remain
explicit in the final status. The runner refuses duplicate launches into a
running or completed series. It does not download inputs or silently retry.

To reproduce the completed preparation test with the installed local tool:

```sh
/opt/anaconda3/envs/docking-universal/bin/python validation/conformer_ab.py \
  --ligand examples/tutorials/02_ligand_free_cavity/inputs/indinavir_pubchem_5362440.sdf \
  --out validation/runs/conformer-ab/indinavir_repeat \
  --xtb .benchmark-tools/xtb/bin/xtb \
  --attempts 16 --keep 3 --rmsd 0.75
```

```sh
/opt/anaconda3/envs/docking-universal/bin/python -m unittest discover \
  -s tests -p test_conformer_ab.py
```
