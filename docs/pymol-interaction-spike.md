# PyMOL interaction spike

Status: controller-driven operations passed; manual mouse-pick and real pocket
artifact acceptance remain open.

## Implemented

The spike launches the existing PyMOL executable in its compatible environment
and starts a token-authenticated server bound to `127.0.0.1`. The bridge accepts
only named operations; it has no arbitrary Python, PyMOL command, or shell
operation. The controller removes inherited Qt/Python path overrides before
launching PyMOL and retains separate stdout/stderr logs.

The implemented operations are handshake/version, load coordinate structure,
apply and read an explicit structural selection, draw a numeric docking box,
get/set the camera, and close. Coordinate loading is restricted to PDB, PDBQT,
MOL2, and SDF during the spike. PML and PSE are not accepted as `load_structure`
inputs because those formats require a separate trust and replay policy.

Selection responses include model, segment, chain, residue number, insertion
code, residue name, atom name, alternate location, and the current PyMOL atom
index. The index is returned for diagnosis only; the other structural fields
drive replay after relaunch.

## Results on the development Mac

- A headless real-PyMOL run loaded the 1HVR tutorial receptor (1,890 atoms),
  highlighted chain A residues 1 and 2, returned their atom identities, drew a
  20 x 20 x 20 A box at the requested center, and returned the camera.
- A synthetic identity fixture proved that chain A residue 10A is distinct from
  chain A residue 10 and chain B residue 10. Both A/B alternate locations were
  retained.
- The same fixture loaded from a path containing spaces.
- Close/relaunch replay restored the structure, selection, box, and exact
  18-value camera record.
- A visible launch initialized OpenGL 2.1 and remained responsive to bridge
  requests. The process completed handshake, structure, selection, box, camera,
  and clean close operations.
- The desktop automation inventory did not expose the Conda-launched PyMOL
  window as an addressable application. This affects automated GUI testing and
  packaging; it did not prevent PyMOL or the bridge from running.

The visible run contained no `pk1` selection because no manual atom was clicked.
Consequently literal mouse-pick return is not yet accepted. The next visible
harness must make the pending pick obvious, observe `pk1` or use a small PyMOL
pick wizard, and return the selection to a controller table. It must also load
two real fpocket candidate artifacts instead of using residue selections as
stand-ins.

## Reproduction

Headless tests use the source checkout and existing environment:

```bash
PYTHONPATH=libexec /opt/anaconda3/envs/docking-universal/bin/python \
  libexec/docking-universal-pymol-spike.py \
  tests/fixtures/pymol_selection_identity.pdb \
  --pymol /opt/anaconda3/envs/docking-universal/bin/pymol \
  --headless --relaunch --chain A --residue 10A \
  --center 12 10 10 --size 10 12 14
```

Omit `--headless` for a visible run. The script waits for the user before it
reads `pk1` and closes PyMOL. This interactive script is feasibility tooling,
not the production viewer adapter described by roadmap task 06.

No study, protocol, or report schema is changed by this spike.
