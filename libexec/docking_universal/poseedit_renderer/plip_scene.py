import json
import math
import argparse
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
from rdkit import Chem

from docking_universal.services.residue_context import read_receptor_atoms, resolve_contact

parser = argparse.ArgumentParser()
parser.add_argument('--report', type=Path, required=True)
parser.add_argument('--ligand', type=Path, required=True)
parser.add_argument('--receptor', type=Path, required=True)
parser.add_argument('--output-root', type=Path, required=True)
parser.add_argument('--ligand-id', default='UNL')
args = parser.parse_args()
ROOT, REPORT, LIGAND, RECEPTOR = args.output_root, args.report, args.ligand, args.receptor
ROOT.mkdir(parents=True, exist_ok=True)


def coord(node, tag):
    block = node.find(tag)
    return tuple(float(block.findtext(axis)) for axis in ('x', 'y', 'z'))


mol = next(item for item in Chem.SDMolSupplier(str(LIGAND), removeHs=False) if item)
conf = mol.GetConformer()
ligand_xyz = {
    atom.GetIdx(): tuple(conf.GetAtomPosition(atom.GetIdx()))
    for atom in mol.GetAtoms() if atom.GetAtomicNum() > 1
}


def ligand_atom(point):
    idx, distance = min(
        ((idx, math.dist(point, xyz)) for idx, xyz in ligand_xyz.items()),
        key=lambda item: item[1],
    )
    return idx, distance


root = ET.parse(REPORT).getroot()
site = next(
    item for item in root.findall('.//bindingsite')
    if (item.findtext('./identifiers/hetid') or '').strip() == args.ligand_id
)
receptor_atoms = read_receptor_atoms(RECEPTOR)
hbonds = []
for call in site.findall('./interactions/hydrogen_bonds/hydrogen_bond'):
    lig_xyz = coord(call, 'ligcoo')
    prot_xyz = coord(call, 'protcoo')
    idx, mapping_distance = ligand_atom(lig_xyz)
    residue = resolve_contact(
        receptor_atoms,
        residue_name=(call.findtext('restype') or '').strip(),
        residue_number=(call.findtext('resnr') or '').strip(),
        chain=(call.findtext('reschain') or '').strip(),
        contact_xyz=prot_xyz,
    )
    hbonds.append({
        'plipId': int(call.get('id')),
        'residueName': (call.findtext('restype') or '').strip().upper(),
        'residueNumber': (call.findtext('resnr') or '').strip(),
        'chain': (call.findtext('reschain') or '').strip(),
        'sidechain': (call.findtext('sidechain') or '').strip().lower() == 'true',
        'proteinAtom': residue.interacting_atom if residue else None,
        'contextKind': residue.context_kind if residue else None,
        'ligandAtomIndex': idx,
        'ligandAtomId': 10000 + idx,
        'ligandElement': mol.GetAtomWithIdx(idx).GetSymbol(),
        'coordinateMappingDistanceAngstrom': mapping_distance,
        'distanceDonorAcceptorAngstrom': float(call.findtext('dist_d-a')),
        'distanceHydrogenAcceptorAngstrom': float(call.findtext('dist_h-a')),
        'donorAngleDegrees': float(call.findtext('don_angle')),
        'proteinIsDonor': (call.findtext('protisdon') or '').strip().lower() == 'true',
        'donorType': (call.findtext('donortype') or '').strip(),
        'acceptorType': (call.findtext('acceptortype') or '').strip(),
        'ligandCoordinates': lig_xyz,
        'proteinCoordinates': prot_xyz,
    })

hydrophobic = []
for call in site.findall('./interactions/hydrophobic_interactions/hydrophobic_interaction'):
    lig_xyz = coord(call, 'ligcoo')
    idx, mapping_distance = ligand_atom(lig_xyz)
    hydrophobic.append({
        'plipId': int(call.get('id')),
        'residueName': (call.findtext('restype') or '').strip().upper(),
        'residueNumber': (call.findtext('resnr') or '').strip(),
        'chain': (call.findtext('reschain') or '').strip(),
        'ligandAtomIndex': idx,
        'ligandAtomId': 10000 + idx,
        'distanceAngstrom': float(call.findtext('dist')),
        'coordinateMappingDistanceAngstrom': mapping_distance,
        'ligandCoordinates': lig_xyz,
        'proteinCoordinates': coord(call, 'protcoo'),
    })

ring_xyz = []
for ring_index, atom_indices in enumerate(mol.GetRingInfo().AtomRings()):
    center = tuple(sum(ligand_xyz[index][axis] for index in atom_indices) / len(atom_indices) for axis in range(3))
    ring_xyz.append((ring_index, atom_indices, center))
pi_stacks = []
for call in site.findall('./interactions/pi_stacks/pi_stack'):
    lig_xyz = coord(call, 'ligcoo')
    ring_index, atom_indices, center = min(ring_xyz, key=lambda item: math.dist(lig_xyz, item[2]))
    pi_stacks.append({
        'plipId': int(call.get('id')),
        'residueName': (call.findtext('restype') or '').strip().upper(),
        'residueNumber': (call.findtext('resnr') or '').strip(),
        'chain': (call.findtext('reschain') or '').strip(),
        'ligandRingId': 4000000 + ring_index,
        'ligandRingAtomIds': [10000 + index for index in atom_indices],
        'coordinateMappingDistanceAngstrom': math.dist(lig_xyz, center),
        'centroidDistanceAngstrom': float(call.findtext('centdist')),
        'angleDegrees': float(call.findtext('angle')),
        'offsetAngstrom': float(call.findtext('offset')),
        'stackingType': (call.findtext('type') or '').strip(),
        'ligandCoordinates': lig_xyz,
        'proteinCoordinates': coord(call, 'protcoo'),
    })

# Fit the least-squares 3D-pose -> 2D-depiction transform once, then retain the
# projected protein-facing direction for obstacle-aware interaction layout.
base_path = ROOT / 'actual-pose-base.json'
if base_path.exists():
    base = json.loads(base_path.read_text())
    display_atoms = base['scene']['structures'][0]['atoms']
    xyz = np.asarray([ligand_xyz[index] for index in sorted(ligand_xyz)], dtype=float)
    xy_by_index = {int(atom['additionalInformation']['sdfAtomIndex']): atom['coordinates'] for atom in display_atoms}
    xy = np.asarray([[xy_by_index[index]['x'], xy_by_index[index]['y']] for index in sorted(ligand_xyz)], dtype=float)
    design = np.column_stack((xyz, np.ones(len(xyz))))
    transform, *_ = np.linalg.lstsq(design, xy, rcond=None)
    linear = transform[:3, :]
    for contact in hydrophobic + hbonds + pi_stacks:
        delta = np.asarray(contact['proteinCoordinates']) - np.asarray(contact['ligandCoordinates'])
        projected = delta @ linear
        norm = float(np.linalg.norm(projected))
        if norm > 1e-8:
            contact['projectedProteinDirection2D'] = [float(projected[0] / norm), float(projected[1] / norm)]

record = {
    'schemaName': 'docking-universal-plip-to-interaction-drawer',
    'schemaVersion': 1,
    'source': {
        'plipReport': str(REPORT),
        'plipVersion': (root.findtext('plipversion') or '').strip(),
        'ligandSdf': str(LIGAND),
        'receptorPdb': str(RECEPTOR),
        'ligandId': ':'.join((args.ligand_id, (site.findtext('./identifiers/chain') or '').strip(), (site.findtext('./identifiers/position') or '').strip())),
    },
    'hydrogenBonds': hbonds,
    'hydrophobicContacts': hydrophobic,
    'piStackings': pi_stacks,
}
(ROOT / 'plip-conversion-record.json').write_text(json.dumps(record, indent=2) + '\n')
(ROOT / 'plip-conversion-data.js').write_text('window.plipConversion = ' + json.dumps(record) + ';\n')
print(json.dumps({'hydrogenBonds': len(hbonds), 'hydrophobicContacts': len(hydrophobic), 'piStackings': len(pi_stacks)}, indent=2))
