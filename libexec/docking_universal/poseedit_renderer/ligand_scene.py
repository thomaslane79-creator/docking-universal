import json
import argparse
from pathlib import Path

from rdkit import Chem
from rdkit.Chem import rdDepictor

parser = argparse.ArgumentParser()
parser.add_argument('pose', type=Path)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
POSE = args.pose
OUTPUT = args.output

mol = Chem.SDMolSupplier(str(POSE), removeHs=False)[0]
if mol is None:
    raise SystemExit(f'RDKit could not read {POSE}')
source = mol.GetConformer()
source_points = [tuple(source.GetAtomPosition(i)) for i in range(mol.GetNumAtoms())]
rdDepictor.Compute2DCoords(mol)
coords = mol.GetConformer()
points = [(coords.GetAtomPosition(i).x, coords.GetAtomPosition(i).y) for i in range(mol.GetNumAtoms())]
cx = sum(x for x, _ in points) / len(points)
cy = sum(y for _, y in points) / len(points)

atoms = []
for atom in mol.GetAtoms():
    idx = atom.GetIdx()
    p2 = coords.GetAtomPosition(idx)
    p3 = source_points[idx]
    atoms.append({
        'id': 10000 + idx,
        'element': atom.GetSymbol(),
        'label': None if atom.GetSymbol() == 'C' else atom.GetSymbol(),
        'charge': atom.GetFormalCharge(),
        'hydrogenCount': atom.GetTotalNumHs(),
        'coordinates': {'x': (p2.x - cx) * 15.0, 'y': -(p2.y - cy) * 15.0},
        'aromatic': atom.GetIsAromatic(),
        'stereoCenter': bool(atom.HasProp('_CIPCode')),
        'additionalInformation': {
            'sdfAtomIndex': idx,
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
        'from': 10000 + bond.GetBeginAtomIdx(),
        'to': 10000 + bond.GetEndAtomIdx(),
        'type': bond_types.get(bond.GetBondType(), 'single'),
        'aromatic': bond.GetIsAromatic(),
    })

rings = []
for ring_idx, ring_atoms in enumerate(mol.GetRingInfo().AtomRings()):
    rings.append({'id': 4000000 + ring_idx, 'atoms': [10000 + idx for idx in ring_atoms]})

scene = {
    'scene': {
        'structures': [{
            'id': 0,
            'structureName': POSE.stem,
            'structureLabel': POSE.stem,
            'structureType': 'ligand',
            'additionalInformation': {'source': str(POSE), 'coordinateSource': 'retained docked SDF'},
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
