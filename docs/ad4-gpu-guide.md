# Learning guide: AutoDock-GPU and AD4

AutoDock Vina remains the default. AutoDock-GPU is an **optional experimental
engine**, not a faster switch for the same Vina calculation. The surrounding
compound review, pose clustering, PLIP analysis, PyMOL review and portrait report
pipeline is shared. The search method and estimated binding-energy formula are
different and are recorded explicitly.

## Three concepts that are easy to confuse

A **scoring function** estimates how favorable a proposed protein–ligand pose
is. A **search algorithm** explores ligand positions, orientations and internal
rotations to find favorable poses. The **GPU** is hardware performing the work.
Moving to AutoDock-GPU changes the first two as well as the hardware; this is
not a controlled comparison of CPU versus GPU execution of identical Vina work.

AD4 means the AutoDock4 scoring function. It combines atom attraction/repulsion,
hydrogen bonding, electrostatics, approximate desolvation and a ligand torsional
entropy penalty. Desolvation approximates part of the cost of taking chemical
groups out of water; it does not mean the program simulates explicit water.
This application’s ligand starting-shape minimization still uses vacuum MMFF94
(with its existing UFF fallback), separately from the docking energy.

Both Vina and AD4 report estimated binding energy in **kcal/mol**. More negative
values are generally favored by that method. But their formulas differ: AD4
−9 and Vina −8 do not establish a 1 kcal/mol improvement, or prove stronger
experimental binding. Do not pool the two engines’ values into one hit ranking.
Neither method is guaranteed more accurate. A lower energy also need not mean
a smaller RMSD to an experimental pose. See the
[official AD4/Vina comparison warning](https://autodock-vina.readthedocs.io/en/latest/docking_flexible.html).

## Choosing and learning about the option in the GUI

In **Finalize protocol → Docking program**, a locally accepted installation adds
**AutoDock-GPU (AD4, experimental)**. A short warning appears beside the choice.
Use its **?** button or **Settings guide…** for the bundled, modeless learning
guide. Reading it needs no internet and changes no approval or setting.

The AD4 choice replaces Vina-only search controls with its own controls:

| Setting | Meaning in this integration |
| --- | --- |
| Starting shapes and chemical states | Prepared independently, using the existing ligand chemistry policy. |
| Independent repeat seeds | A separate GPU repeat for each shape, state, site and compound. |
| Genetic-search runs per repeat | Default **20**. Each genetic/local search contributes one winner. All winners are retained, even if some are similar. This is not 20 distinct clusters. |
| Heuristic evaluation cap | Default **12,000,000**. The heuristic derives a budget from ligand flexibility, bounded by this cap; convergence autostop can finish sooner. This is not a wall-clock limit or Vina exhaustiveness. |
| Fixed profile | Population 150, maximum 42,000 generations, ADADELTA local optimization with 300 local iterations; 0.375 Å AutoGrid spacing. |
| Saved-pose window | No Vina energy-window filtering. All genetic-run winners go into the shared clustering stage. |
| CPU threads | Not applied to the GPU search. The GUI disables this control without discarding a saved CPU choice for Vina. |

The genetic algorithm keeps a population of possible placements, varies and
combines them, and refines them locally. More runs or a larger budget can cost
more time without guaranteeing a correct pose. Starting shapes × states × seeds
× sites × compounds multiply the repeats. Compounds remain sequential.

AutoGrid first prepares atom-type energy maps for the selected receptor and
region. Its even number of whole grid intervals may enlarge a requested box
slightly: a 26 Å side becomes **26.25 Å** at the tested spacing. The requested
center is preserved. Both requested and actual extents are locked and reported;
this discretization is not hidden as an unchanged box.

## Scientific and operational boundaries

- This first option uses **dry, rigid receptors** and ordinary supported ligand
  atom types. Unvalidated macrocycles, metals and special parameters are rejected;
  the application does not silently alter their treatment or switch to Vina.
- Production bound-ligand control calibration is not enabled for this engine.
  The available protocol route is explicitly exploratory. The retained small
  crystal-control development panel does not validate a new user target.
- A Vina protocol cannot be reused as AD4 by overriding its engine. Create an
  explicitly AD4 exploratory protocol. Selecting an engine is not hit approval.
- Native XML, PDBQT winners, population records, build identity, map/input hashes
  and native-run-to-model mappings are retained. Reported AD4 binding energy is
  not relabeled as Vina energy or confused with the GPU’s total search energy.
- Completed-job skipping verifies method/input/output identity. Partial,
  cancelled, failed or modified batches are not silently restarted. Cancellation
  keeps partial logs and remains cancellation, not successful completion.
- Same-seed repeats were checked in the tested build/device scope. They are not
  a promise of identical coordinates across engines, GPUs, drivers or platforms.
- Speed varies with chemistry, search budget, setup and hardware. The previous
  full-workload timing is a cross-engine measurement, not an equal-work Vina GPU
  speedup or evidence of more accurate binding energies.

## macOS, Windows and Linux

The shared protocol, adapter, analysis and GUI design is intended for **all three
platforms**. The currently accepted GPU executable is specifically the patched
Apple-Silicon OpenCL 128-work-item build tested on this Mac. It is not a Windows
binary, a Linux/CUDA binary, or a portable scientific-validation certificate.
Untested GPU builds remain unavailable rather than inheriting the Mac result.
Windows/Linux activation needs native build/driver, scoring, chemistry,
repeatability, failure/cancellation and full-workflow acceptance on those systems.
Existing non-GPU engine availability follows the normal platform support record.

The optional runtime descriptor is separate from scientific protocols.
`bash install.sh --with-gpu` installs the exact pinned build and AutoGrid on
Apple-Silicon macOS 26.2+, recording its descriptor inside the scientific prefix
at `share/docking-universal/adgpu/runtime.json`. An explicit
`DOCKING_UNIVERSAL_ADGPU_CONFIG` takes precedence; the older
`~/.config/docking-universal/adgpu.json` remains a compatibility fallback only
when no prefix-local descriptor exists. Runtime discovery checks the accepted
executable hash, platform, minimum OS and installed AutoGrid identity. Arbitrary
rebuilt binaries are not automatically accepted. No GPU is required for the
normal Vina workflow or reading an existing PDF. See
[portable runtime installation and checks](mac-runtime-packaging.md).

## Corrections and validation record

The accepted candidate is pinned upstream v1.6 plus the
[retained two-change patch](../validation/patches/autodock-gpu-v1.6-local.patch):
a shared-force synchronization barrier, and a guard rejecting the defective
one-work-item Apple configuration. A work item is a GPU execution lane, not a
compound or CPU-thread choice. The one-work-item defect is **blocked, not fixed**.

The later near-8 Å numerical disagreement was a reference cutoff-boundary issue,
not another production kernel change. Exact scoring-kernel replay preserved all
coordinates and energies. Native-branch-conditioned component checks retain all
states and the original energy gates; they are not a wholly independent
double-precision scorer. KNI-577 passes its original unconditioned reference
gates. See the [cutoff-resolution record](autodock-gpu-cutoff-resolution.md),
[control assessment](autodock-gpu-control-assessment.md) and
[integration acceptance](ad4-gpu-integration.md).

For the underlying methods and parameter definitions, see the
[AutoDock-GPU paper](https://pmc.ncbi.nlm.nih.gov/articles/PMC8063785/) and
[upstream documentation](https://github.com/ccsb-scripps/AutoDock-GPU#supported-arguments).
These external links are optional; structures are not uploaded to render reports.
