import json
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from docking_universal.sdf_io import read_sdf

from rdkit import Chem
from rdkit.Chem import rdDepictor

parser = argparse.ArgumentParser()
parser.add_argument('pose', type=Path)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--spacing', type=float, default=15.0)
parser.add_argument('--alignment-reference', type=Path)
args = parser.parse_args()
POSE = args.pose
OUTPUT = args.output

mol = next(iter(read_sdf(POSE, removeHs=False)), None)
if mol is None:
    raise SystemExit(f'RDKit could not read {POSE}')
# Keep PLIP's original SDF atom identities while suppressing explicit H atoms
# only in the 2D drawing. The retained molecule and interaction analysis are
# untouched; attached H counts still describe the supplied chemical structure.
for atom in mol.GetAtoms():
    atom.SetIntProp('_du_source_atom_index', atom.GetIdx())
source = mol.GetConformer()
source_points = [tuple(source.GetAtomPosition(i)) for i in range(mol.GetNumAtoms())]
mol = Chem.RemoveHs(mol)
if args.alignment_reference:
    reference = next(iter(read_sdf(args.alignment_reference, removeHs=False)), None)
    if reference is None or not reference.GetNumConformers():
        raise SystemExit('The 2D alignment reference is unavailable')
    reference = Chem.RemoveHs(reference)
    if (mol.GetNumAtoms() != reference.GetNumAtoms()
            or Chem.MolToSmiles(mol, isomericSmiles=True) != Chem.MolToSmiles(reference, isomericSmiles=True)):
        raise SystemExit('The control ligand does not match the 2D alignment reference')
    # For symmetric ligands, choose the chemically valid atom correspondence
    # closest in the original receptor frame, without fitting or moving atoms.
    matches = mol.GetSubstructMatches(reference, uniquify=False, useChirality=True, maxMatches=4096)
    if not matches:
        raise SystemExit('No complete stereochemistry-preserving atom mapping for 2D alignment')
    source_conf, reference_conf = mol.GetConformer(), reference.GetConformer()
    def distance(match):
        return sum((source_conf.GetAtomPosition(target) - reference_conf.GetAtomPosition(index)).LengthSq()
                   for index, target in enumerate(match))
    match = min(matches, key=distance)
    rdDepictor.Compute2DCoords(reference)
    rdDepictor.GenerateDepictionMatching2DStructure(mol, reference,
        [(index, target) for index, target in enumerate(match)])
else:
    rdDepictor.Compute2DCoords(mol)
coords = mol.GetConformer()
points = [(coords.GetAtomPosition(i).x, coords.GetAtomPosition(i).y) for i in range(mol.GetNumAtoms())]
cx = sum(x for x, _ in points) / len(points)
cy = sum(y for _, y in points) / len(points)

atoms = []
for atom in mol.GetAtoms():
    idx = atom.GetIdx()
    p2 = coords.GetAtomPosition(idx)
    source_idx = atom.GetIntProp('_du_source_atom_index')
    p3 = source_points[source_idx]
    atoms.append({
        'id': 10000 + source_idx,
        'element': atom.GetSymbol(),
        'label': None if atom.GetSymbol() == 'C' else atom.GetSymbol(),
        'charge': atom.GetFormalCharge(),
        'hydrogenCount': atom.GetTotalNumHs(),
        'coordinates': {'x': (p2.x - cx) * args.spacing, 'y': -(p2.y - cy) * args.spacing},
        'aromatic': atom.GetIsAromatic(),
        'stereoCenter': bool(atom.HasProp('_CIPCode')),
        'additionalInformation': {
            'sdfAtomIndex': source_idx,
            'poseCoordinates': list(p3),
        },
    })

bond_types = {
    Chem.BondType.SINGLE: 'single',
    Chem.BondType.DOUBLE: 'double',
    Chem.BondType.TRIPLE: 'triple',
    Chem.BondType.AROMATIC: 'single',
}
bonds = []
for bond in mol.GetBonds():
    bonds.append({
        'id': 20000 + bond.GetIdx(),
        'from': 10000 + bond.GetBeginAtom().GetIntProp('_du_source_atom_index'),
        'to': 10000 + bond.GetEndAtom().GetIntProp('_du_source_atom_index'),
        'type': bond_types.get(bond.GetBondType(), 'single'),
        'aromatic': bond.GetIsAromatic(),
    })

rings = []
for ring_idx, ring_atoms in enumerate(mol.GetRingInfo().AtomRings()):
    rings.append({'id': 4000000 + ring_idx, 'atoms': [
        10000 + mol.GetAtomWithIdx(idx).GetIntProp('_du_source_atom_index') for idx in ring_atoms]})

scene = {
    'scene': {
        'structures': [{
            'id': 0,
            'structureName': POSE.stem,
            'structureLabel': POSE.stem,
            'structureType': 'ligand',
            'additionalInformation': {'source': str(POSE), 'coordinateSource': 'retained ligand SDF'},
            'atoms': atoms,
            'bonds': bonds,
            'rings': rings,
        }],
        'atomPairInteractions': [],
        'piStackings': [],
        'cationPiStackings': [],
        'hydrophobicContacts': [],
        'annotations': [],
    }
}
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
OUTPUT.write_text(json.dumps(scene, indent=2) + '\n')
print(OUTPUT)
