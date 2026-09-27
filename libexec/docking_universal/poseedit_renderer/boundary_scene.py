import json
import argparse
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d
from matplotlib import pyplot as plt

parser = argparse.ArgumentParser()
parser.add_argument('--output-root', type=Path, required=True)
ROOT = parser.parse_args().output_root
scene = json.loads((ROOT / 'actual-pose-base.json').read_text())['scene']
plip = json.loads((ROOT / 'plip-conversion-record.json').read_text())
ligand = scene['structures'][0]
atoms = {atom['id']: atom for atom in ligand['atoms']}

xy = np.asarray([[atom['coordinates']['x'], atom['coordinates']['y']] for atom in ligand['atoms']], float)
margin = 24.0
step = 2.0
gx = np.arange(xy[:, 0].min() - 45, xy[:, 0].max() + 47, step)
gy = np.arange(xy[:, 1].min() - 45, xy[:, 1].max() + 47, step)
xx, yy = np.meshgrid(gx, gy)
distance = np.full(xx.shape, np.inf)

for px, py in xy:
    distance = np.minimum(distance, np.hypot(xx - px, yy - py))
for bond in ligand['bonds']:
    a = atoms[bond['from']]['coordinates']
    b = atoms[bond['to']]['coordinates']
    vx, vy = b['x'] - a['x'], b['y'] - a['y']
    denom = vx * vx + vy * vy
    t = np.clip(((xx - a['x']) * vx + (yy - a['y']) * vy) / (denom or 1.0), 0.0, 1.0)
    distance = np.minimum(distance, np.hypot(xx - (a['x'] + t * vx), yy - (a['y'] + t * vy)))

figure, axis = plt.subplots()
contour = axis.contour(xx, yy, distance, levels=[margin])
paths = contour.get_paths()
plt.close(figure)
boundary = max((path.vertices for path in paths), key=len)
if np.linalg.norm(boundary[0] - boundary[-1]) < step * 2:
    boundary = boundary[:-1]

# Resample uniformly before smoothing so the result is independent of grid
# contour vertex density. Periodic filtering preserves a continuous perimeter.
smooth_boundary = gaussian_filter1d(boundary, sigma=5.0, axis=0, mode='wrap')

segments = np.roll(boundary, -1, axis=0) - boundary
seglen = np.linalg.norm(segments, axis=1)
perimeter = float(seglen.sum())
cumulative = np.concatenate(([0.0], np.cumsum(seglen)))

contacts = []
for contact in plip['hydrophobicContacts']:
    point = np.asarray([atoms[contact['ligandAtomId']]['coordinates']['x'], atoms[contact['ligandAtomId']]['coordinates']['y']])
    index = int(np.argmin(np.linalg.norm(boundary - point, axis=1)))
    contacts.append((float(cumulative[index]), index, contact))
contacts.sort(key=lambda item: (item[0], item[1]))

# Break the cyclic perimeter at its largest contact-free gap, then split other
# gaps large enough to represent distinct pocket-facing regions.
groups = []
if contacts:
    gaps = [contacts[i + 1][0] - contacts[i][0] for i in range(len(contacts) - 1)]
    gaps.append(perimeter - contacts[-1][0] + contacts[0][0])
    break_at = int(np.argmax(gaps))
    ordered = contacts[break_at + 1:] + contacts[:break_at + 1]
    unwrapped = []
    last = None
    offset = 0.0
    for distance_on_boundary, index, contact in ordered:
        value = distance_on_boundary + offset
        if last is not None and value < last:
            offset += perimeter
            value += perimeter
        unwrapped.append((value, index, contact))
        last = value
    current = []
    for item in unwrapped:
        if current and item[0] - current[-1][0] > 72:
            groups.append(current)
            current = []
        current.append(item)
    if current:
        groups.append(current)

def boundary_at(distance_on_boundary):
    value = distance_on_boundary % perimeter
    index = int(np.searchsorted(cumulative, value, side='right') - 1) % len(boundary)
    local = value - cumulative[index]
    ratio = local / (seglen[index] or 1.0)
    return smooth_boundary[index] + (smooth_boundary[(index + 1) % len(boundary)] - smooth_boundary[index]) * ratio

splines = []
annotations = []
for spline_id, group in enumerate(groups):
    start = group[0][0] - 18
    end = group[-1][0] + 18
    samples = np.arange(start, end + 0.1, 9.0)
    if samples[-1] < end - 2:
        samples = np.append(samples, end)
    control_points = []
    for sample in samples:
        nearest = min(group, key=lambda item: abs(item[0] - sample))
        point = boundary_at(sample)
        control_points.append({'x': float(point[0]), 'y': float(point[1]), 'atomLinks': [nearest[2]['ligandAtomId']]})
    splines.append({'id': spline_id, 'belongsTo': 0, 'controlPoints': control_points})
    for _, index, contact in group:
        point = boundary[index]
        atom_point = np.asarray([atoms[contact['ligandAtomId']]['coordinates']['x'], atoms[contact['ligandAtomId']]['coordinates']['y']])
        outward = point - atom_point
        outward /= np.linalg.norm(outward) or 1.0
        label_point = point + outward * 18
        name = contact['residueName'][0] + contact['residueName'][1:].lower() + contact['residueNumber'] + contact['chain']
        existing = next((annotation for annotation in annotations if annotation['label'] == name and annotation['additionalInformation']['splineId'] == spline_id), None)
        if existing is not None:
            existing['additionalInformation']['contacts'].append(contact)
            if contact['ligandAtomId'] not in existing['belongsTo']['atomLinks']:
                existing['belongsTo']['atomLinks'].append(contact['ligandAtomId'])
            continue
        annotations.append({
            'id': len(annotations), 'label': name, 'color': '#009b49',
            'coordinates': {'x': float(label_point[0]), 'y': float(label_point[1])},
            'belongsTo': {'type': 'structureSpline', 'id': 0, 'atomLinks': [contact['ligandAtomId']]},
            'additionalInformation': {'interactionType': 'hydrophobic', 'splineId': spline_id, 'contacts': [contact]},
        })

# PoseEdit stacks multiple residue labels linked to the same ligand atom rather
# than drawing them at the same coordinates.
labels_by_atom = {}
for annotation in annotations:
    atom_id = annotation['belongsTo']['atomLinks'][0]
    labels_by_atom.setdefault(atom_id, []).append(annotation)
for linked in labels_by_atom.values():
    if len(linked) < 2:
        continue
    for index, annotation in enumerate(linked):
        annotation['coordinates']['y'] += (index - (len(linked) - 1) / 2) * 16

layout = {'hydrophobicContacts': splines, 'annotations': annotations}
(ROOT / 'hydrophobic-layout.json').write_text(json.dumps(layout, indent=2) + '\n')
(ROOT / 'hydrophobic-layout-data.js').write_text('window.hydrophobicLayout = ' + json.dumps(layout) + ';\n')
print(json.dumps({'splines': len(splines), 'annotations': len(annotations), 'controlPoints': sum(len(item['controlPoints']) for item in splines)}))
