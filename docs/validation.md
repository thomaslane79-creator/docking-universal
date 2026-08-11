# Raw-input validation

The packaged ligand-free tutorial input, unbound RCSB 2R8N, was also passed through the quick fpocket route on the macOS arm64 reference environment. The run completed and wrote five ranked candidate cavities with positive dimensions and Vina configuration files. This verifies tutorial execution through cavity generation; it does not validate any cavity as a biological binding site.

## Reference case

Docking Universal was tested from public raw inputs using RCSB PDB entry [1HVR](https://www.rcsb.org/structure/1HVR), a 1.80 Å HIV-1 protease structure containing the bound inhibitor XK2.

Downloaded inputs:

| Input | Source | SHA-256 |
| --- | --- | --- |
| `1HVR.pdb` | `https://files.rcsb.org/download/1HVR.pdb` | `c8d3f238d3269a66823454d4681b71467b4677a18751ce094047961620b338cb` |

The control retrieves coordinate-free XK2 chemical identity from the RCSB CCD metadata API. No CCD ideal-coordinate SDF is an input to the default control.

The downloaded raw inputs are not redistributed in this repository. The checksums identify the files used for the test. A small set of derived, self-contained PyMOL validation artifacts is included under `tests/expected_runs/1hvr_xk2/pymol`.

## What was tested

The raw PDB and SDF were processed on an M2 Mac using the clean main environment and the isolated Vina environment:

1. Receptor atoms and `MODRES`-declared polymer residues were selected from the raw PDB and converted strictly with Meeko; no permissive bad-residue deletion was used. Meeko fetched the official CSO chemical-component definition from RCSB to type the two modified cysteines.
2. XK2 was prepared from the raw SDF with Open Babel and Meeko.
3. Meeko prepared AutoDock Vina PDBQT input while retaining the recorded ligand chemistry and conformer provenance.
4. For the ligand-free tests, XK2 was withheld from fpocket. Both the guided conservative workflow and the standalone robust command ranked and boxed sites from protein coordinates alone.
5. A retrospectively selected recovered site was used for a low-exhaustiveness software smoke run with Vina 1.2.7.
6. Vina output was collected to CSV with its score and RMSD-bound fields retained explicitly.
7. The top Vina pose was combined with receptor coordinates for PLIP analysis, custom PML generation, headless PyMOL rendering, and generic RDKit depiction.
8. The confirmed `XK2:A:263` instance was also processed through the complete retrospective `control` command: automatic CCD-backed experimental-coordinate SDF creation, Vina docking at the package defaults, pose comparison, filtered PLIP analysis, and PNG/PSE rendering.

## Ligand-centered preparation result

The guided `prepare` command was also run directly on the untouched complex PDB with strict Meeko preparation and ligand-centered mode selected. `MODRES`-declared CSO residues were retained as polymer context rather than misclassified as free ligands; XK2 was the only ligand candidate.

- prepared receptor: 99 residues and 922 atoms in chain A, and 99 residues and 922 atoms in chain B;
- ligand atoms detected: 46;
- local protein atoms passed to fpocket: 796;
- ligand-overlapping alpha spheres retained: 183;
- generated box center: `(-9.191565, 15.906261, 27.946478)` Å;
- independently calculated XK2 centroid: the same coordinates to displayed precision;
- generated box size: 26 × 26 × 26 Å.

The generated ligand-centered PML was rendered headlessly to 800 × 600 PNG and visually inspected on the M2 reference system.

## Ligand-free pocket result

The bound XK2 coordinates in the original complex were withheld from fpocket and used only after prediction as a reference.

### Guided full-pipeline run

The interactive `prepare` workflow was run on the prepared protein-only PDB, with conservative fpocket settings, a maximum of three cavities, centroid-based centers, and per-chain reference centroids. It detected no ligand and selected the two candidates that passed its score and geometry filters:

| Selected cavity | Distance from predicted center to withheld XK2 centroid |
| --- | ---: |
| Cavity 1 | 20.726 Å |
| Cavity 2 | **5.100 Å** |

Both generated pocket scenes rendered as nonblank 800 × 600 PNGs and were visually inspected. Cavity 2 occupied the protease central cleft, but it was the second selected cavity and its center was not as close to the withheld ligand as the standalone robust result below.

### Standalone robust-mode run

| Site | Distance from predicted center to withheld XK2 centroid |
| --- | ---: |
| Top-ranked pocket | 22.740 Å |
| Second-ranked pocket | **0.551 Å** |
| Third-ranked pocket | 12.671 Å |

The known ligand site was therefore recovered as the second-ranked robust-mode candidate. This is a retrospective recovery check on one known complex, not a general benchmark of pocket-prediction accuracy. The rank-2 site was selected for the engine smoke runs only after comparison with the withheld ligand; this was not a prospective top-pocket selection.

## Interaction and image outputs

PLIP completed on the corrected receptor plus derived top Vina pose. For the docked ligand (`UNL`), PLIP recorded 16 hydrophobic contacts and 3 hydrogen bonds. PLIP also treated the two modified CSO residues as separate small-molecule binding sites and assigned them 3 additional hydrogen bonds, giving 6 hydrogen bonds across the complete unfiltered report. The custom PML preserves all three records explicitly. It rendered to a visually inspected 800 × 600 headless PyMOL PNG. RDKit produced a visually inspected 900 × 700 generic 2D depiction from the raw XK2 SDF; this is an isolated ligand-identity image, not a docked-pose interaction diagram.

## Bound-ligand control result

The guided control identified the exact candidate `XK2:A:263` with 46 atoms. In strict automatic mode, the RCSB Chemical Component Dictionary classified XK2 as a non-polymer; the experimental and coordinate-free CCD-SMILES heavy-atom element inventories matched (`C41 N2 O3`), and RDKit transferred graph bond orders onto the experimental reference coordinates. The workflow then wrote `XK2_experimental.sdf` automatically.

Vina was run at the package defaults of exhaustiveness 8 and up to 9 poses. The workflow completed, but this initial configuration did not recover the experimental pose within the default 2.0 Å symmetry-aware heavy-atom RMSD threshold:

| Engine | Top-score affinity (kcal/mol) | Top-score pose RMSD (Å) | Best sampled RMSD (Å) | Control passed |
| --- | ---: | ---: | ---: | --- |
| Vina 1.2.7 | -11.574 | 6.8366 | 3.7973 | No |

The score values are recorded only to identify the compared models; they are not affinity claims. Filtered PLIP analysis selected only the requested experimental or docked ligand rather than the two CSO polymer modifications. For the experimental XK2 site, it recorded 14 hydrophobic contacts and 4 hydrogen bonds. All five requested 1800 × 1400 PNGs and their PyMOL sessions rendered successfully and were visually inspected, including the crystal-versus-top-pose overlays that expose the failed recovery.

This is an important negative control result: the software workflow and audit trail functioned, but these default settings did not reproduce the known XK2 pose. The case should therefore not be presented as docking-accuracy validation. Possible scientific follow-up includes protocol-specific protonation/charge review, box and search-setting sensitivity, and comparison with a ligand preparation that preserves an experimentally justified starting chemistry; those require a documented validation study rather than silent parameter tuning.

### Independent-ensemble calibration follow-up

The failed preparation was diagnosed as unconditional Open Babel 3D regeneration/minimization, which changed XK2 by 3.82 Å heavy-atom RMSD even after optimal superposition. A crystal-coordinate self-docking diagnostic recovered the pose but was recognized as biased and excluded from protocol approval.

An unbiased follow-up requested only coordinate-free CCD isomeric SMILES, enumerated the pH 7.4 chemical state with MolScrub, and generated three seeded ETKDG/MMFF94 conformers independently. Their aligned RMSDs from the withheld crystal pose were 3.70–4.48 Å. Each conformer was prepared separately for Vina. Docking used exhaustiveness 32, 20 modes, an 8 kcal/mol output range, and fixed seeds.

Across an initial three Vina seeds (`20260808`, `20260809`, and `20260810`), every conformer/seed top-ranked pose was below 2 Å. The test was then extended through seeds `20260811` and `20260812` using the integrated broader-search tier: three independent conformers, five seeds, exhaustiveness 32, 20 modes, and an 8 kcal/mol output range. All 15 conformer/seed top-ranked poses were below 2 Å. Their top-ranked RMSDs ranged from 0.815 to 1.558 Å (median 1.198 Å); best sampled RMSDs ranged from 0.720 to 1.335 Å (median 0.898 Å). The globally lowest-energy pose had RMSD 0.898 Å and the overall best sampled pose had RMSD 0.720 Å.

Sampling, ranking, and the five-independent-seed requirement therefore passed. The workflow wrote a stable v1 target-locked protocol containing the engine-specific macrocycle treatment, preparation/search settings, seed list, per-seed outcomes, and receptor/box SHA-256 hashes. This permits consistent unknown-ligand docking for this exact prepared target through the protocol gate; it remains a retrospective control on one complex, not validation of prospective pose or affinity accuracy.

## Issues discovered by raw validation

The test exposed and led to corrections for:

- metal detection that previously matched symbols anywhere in a `HETATM` line instead of the PDB element column;
- fpocket 4.2 report filenames and pocket-coordinate layout;
- report parsing that confused `Score` with `Druggability Score` and `Volume` with `Volume score`;
- nonnumeric pocket extents and invalid negative box sizes;
- configuration files that incorrectly named a source PDB as a docking receptor;
- quoted PyMOL PML paths that produced a valid but blank PNG on the M2 reference build;
- `MODRES` polymer modifications that could otherwise be misclassified as ligands;
- Bash `/dev/fd` restrictions in headless execution, handled by the recorded file-only logging mode.
- active Conda environments that exposed `python` but allowed macOS `python3` to resolve outside the environment; Python-backed stages now consistently use the active environment interpreter;
- interaction reports that included unrelated modified residues; the interaction stage now supports exact ligand residue, chain, and position filters;
- the absence of an auditable distinction between inferred and verified bound-ligand chemistry; the control now uses strict CCD/template checks or a reasoned manual override.

## Limits

The earlier engine smoke runs used exhaustiveness 1 for rapid software verification. The separate bound-ligand control used exhaustiveness 8 and failed its pose-recovery threshold as reported above. The resulting affinities are not scientific findings. One public case does not establish broad accuracy across proteins, ligand chemistries, metals, modified residues, protonation states, or platforms. Production studies require justified parameters, replicate strategy, structural review, and domain-specific validation.
