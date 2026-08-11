# Representative inputs

These are small public inputs for manual smoke tests and for inspecting the
expected input layout.

- `protein_ligand_complex/1HVR.pdb`: a public PDB containing both the protein
  and its bound ligand, for the bound-ligand control tutorial.
- `protein_ligand_complex/nevirapine_pubchem_4463.sdf`: a public held-out known
  RT-inhibitor input for the protocol-screening demonstration.
- `protein_ligand_complex/rilpivirine_pubchem.sdf`: the larger, flexible
  held-out known-inhibitor input used by the primary screening demonstration.
- `protein_only_and_compound/2R8N.pdb`: public protein structure for the
  cavity-search workflow.
- `protein_only_and_compound/indinavir_pubchem_5362440.sdf`: public compound input for the
  ligand-free tutorial.

Each downloaded file has an adjacent provenance record. Tutorial copies remain
under `examples/tutorials/` so users can run a tutorial without locating test
data first.
