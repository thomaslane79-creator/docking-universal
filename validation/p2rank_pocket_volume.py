"""Isolated comparison and PyMOL preview of released P2Rank alpha pocket grids.

No production dependency, receptor preparation, study or approval is changed.
The interpolated surface is a display of sampled space, not a cavity-volume
measurement. In particular, spheres can extend beyond the sampled coordinates.
"""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import json
from pathlib import Path


def predictions(path):
    with path.open() as stream:
        return [{key.strip(): value.strip() for key, value in row.items()}
                for row in csv.DictReader(stream)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--receptor', type=Path, required=True)
    parser.add_argument('--stable', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    unfilled = root / 'unfilled_output'
    name = args.receptor.name
    stable = predictions(args.stable)
    alpha = predictions(unfilled / f'{name}_predictions.csv')
    default = predictions(root / 'alpha_output' / f'{name}_predictions.csv')
    assert stable == alpha == default, 'Prediction outputs differ'
    grids = {}
    for mode, directory in [('unfilled', unfilled), ('default', root / 'alpha_output')]:
        with gzip.open(directory / f'{name}_pocket_grid.csv.gz', 'rt') as stream:
            rows = [{k.strip(): v.strip() for k, v in row.items()}
                    for row in csv.DictReader(stream)]
        grids[mode] = dict(points=len(rows), by_rank=dict(Counter(r['pocket'] for r in rows)))
    import pymol2
    import numpy as np
    with pymol2.PyMOL() as engine:
        engine.start()
        cmd = engine.cmd
        cmd.set('auto_zoom', 0)
        cmd.bg_color('white')
        cmd.set('ray_shadows', 0)
        cmd.set('two_sided_lighting', 1)
        cmd.set('ray_interior_color', 'red')
        cmd.set('orthoscopic', 1)
        cmd.load(str(args.receptor), 'receptor')
        cmd.load(str(unfilled / 'visualizations' / 'data' / f'{name}_pocket_grid.pdb.gz'), 'grid')
        cmd.hide('everything', 'all')
        cmd.create('pocket_space', 'grid and resi 1')
        cmd.delete('grid')
        cmd.select('contacts', 'byres (receptor within 5 of pocket_space)')
        cmd.show('sticks', 'contacts')
        cmd.color('gray70', 'receptor and elem C')
        # Compare centers with all protein atom radii, not only nearest atom.
        protein = cmd.get_model('receptor and polymer.protein').atom
        coords = cmd.get_coords('pocket_space')
        centers = np.array([a.coord for a in protein])
        radii = np.array([a.vdw for a in protein])
        margins = (np.linalg.norm(coords[:, None, :] - centers[None, :, :], axis=2)
                   - radii[None, :]).min(axis=1)
        grids['unfilled']['rank1_minimum_center_clearance_from_pymol_vdw_angstrom'] = float(margins.min())
        grids['unfilled']['rank1_centers_inside_pymol_protein_vdw'] = int((margins < 0).sum())
        assert not (margins < 0).any(), 'Grid centers overlap protein atoms'
        cmd.color('red', 'pocket_space')
        cmd.alter('pocket_space', 'vdw=1.02')  # released alpha display radius: 0.85 * spacing
        cmd.set('solvent_radius', 0, 'pocket_space')
        cmd.rebuild('pocket_space')
        cmd.show('surface', 'pocket_space')
        cmd.set('transparency', 0.35, 'pocket_space')
        cmd.orient('pocket_space', animate=0)
        cmd.zoom('pocket_space or contacts', buffer=3, animate=0)
        cmd.deselect()
        cmd.png(str(root / 'pocket_space.png'), width=1100, height=850, ray=1)
        cmd.hide('surface', 'pocket_space')
        cmd.show('spheres', 'pocket_space')
        cmd.set('sphere_scale', 0.18, 'pocket_space')
        cmd.png(str(root / 'pocket_grid.png'), width=1100, height=850, ray=1)
        # Same camera, old visualization: surface is on protein site residues.
        cmd.disable('pocket_space')
        residue_numbers = '+'.join(r.split('_', 1)[1] for r in alpha[0]['residue_ids'].split())
        cmd.create('old_site_surface', f'receptor and chain A and resi {residue_numbers}')
        cmd.hide('everything', 'old_site_surface')
        cmd.show('surface', 'old_site_surface')
        cmd.color('red', 'old_site_surface')
        cmd.set('transparency', 0.35, 'old_site_surface')
        cmd.png(str(root / 'protein_site_surface.png'), width=1100, height=850, ray=1)
    multichain_alpha = predictions(root / 'multichain_alpha' / '3QBF.pdb_predictions.csv')
    multichain_stable = predictions(root / 'multichain_stable' / '3QBF.pdb_predictions.csv')
    assert multichain_alpha == multichain_stable, 'Multichain predictions differ'
    assert {r.split('_', 1)[0] for r in multichain_alpha[0]['residue_ids'].split()} == {'A', 'B'}
    result = dict(
        release='2.6-alpha', production_dependency_unchanged='2.5.1',
        archive_sha256=hashlib.sha256((root / 'p2rank_2.6-alpha.tar.gz').read_bytes()).hexdigest(),
        receptor_sha256=hashlib.sha256(args.receptor.read_bytes()).hexdigest(),
        stable_and_alpha_predictions_equal=True, predictions=alpha, grids=grids,
        default_fill_warning='MorphologicalCloser hit maxIters=10 without converging',
        preview_fill='none',
        multichain=dict(entry='3QBF', chains=['A', 'B'],
                        stable_and_alpha_predictions_equal=True,
                        predictions=multichain_alpha,
                        component_download_errors=['JHG', 'GOL', 'CL', 'HOH'],
                        note='Both versions completed despite sandbox-blocked CCD requests; ligands ignored'),
        limitations=['two small HIV-protease examples, not broad target validation',
                     'sampled predicted pocket space, not proof of an enclosed cavity',
                     'display sphere radius can inflate the shown volume',
                     'not integrated into GUI or reports'])
    (root / 'comparison.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
