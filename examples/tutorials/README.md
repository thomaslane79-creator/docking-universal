# Two complete workflow examples

These tutorials cover the two scientifically different ways to begin a Docking Universal study.

1. [`01_bound_ligand`](01_bound_ligand/README.md): use the experimental XK2 ligand in 1HVR to define the pocket and test pose recovery before unknown docking.
2. [`02_ligand_free_cavity`](02_ligand_free_cavity/README.md): use the unbound 2R8N protease structure, ignore crystallization additives as control ligands, rank cavities, and label subsequent docking exploratory.

Each example includes small public starting inputs and explains the actual Docking Universal command and guided scientific choices. There are no example-specific wrapper scripts: users work through the same public interface they would use for their own study. Generated docking poses are intentionally not committed; following a tutorial creates a self-contained `study/` folder beside its inputs.

Both examples use a fixed receptor during docking. Ligands may retain rotatable bonds and may be represented by independent conformers. The same workflow accepts compound libraries for batch docking; it does not model receptor flexibility or induced fit.
