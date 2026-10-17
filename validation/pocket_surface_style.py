"""Compare object-local probe smoothing on unchanged alpha grid points."""
import argparse
import json
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'libexec'))
from docking_universal.services.pocket_space import sha


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--rank', type=int, default=1)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads(args.manifest.read_text())
    assert sha(manifest['grid']) == manifest['grid_sha256']
    import pymol2
    result = {'styles': []}
    with pymol2.PyMOL() as engine:
        engine.start()
        cmd = engine.cmd
        cmd.set('auto_zoom', 0)
        cmd.bg_color('white')
        cmd.set('orthoscopic', 1)
        cmd.set('ray_shadows', 0)
        cmd.set('two_sided_lighting', 1)
        cmd.set('ray_interior_color', 'red')
        cmd.set('antialias', 2)
        cmd.load(manifest['receptor'], 'receptor')
        cmd.load(manifest['grid'], 'grid')
        cmd.create('space', f'grid and resi {args.rank}')
        cmd.delete('grid')
        cmd.hide('everything', 'all')
        cmd.show('sticks', 'byres (receptor within 4 of space)')
        cmd.color('gray70', 'receptor and elem C')
        cmd.color('red', 'space')
        cmd.alter('space', 'vdw=1.02')
        cmd.set('surface_solvent', 0, 'space')
        cmd.set('surface_quality', 1, 'space')
        cmd.set('transparency', 0.4, 'space')
        cmd.show('surface', 'space')
        cmd.orient('space', animate=0)
        cmd.zoom('space or (receptor and rep sticks)', buffer=4, animate=0)
        camera = tuple(cmd.get_view())
        coords = cmd.get_coords('space').tolist()
        for probe in (0.0, 0.8, 1.4):
            start = time.perf_counter()
            cmd.set('solvent_radius', probe, 'space')
            cmd.rebuild('space')
            cmd.set_view(camera)
            cmd.png(str(args.out / f'probe-{probe}.png'), width=1000, height=800, ray=1)
            assert cmd.get_coords('space').tolist() == coords
            assert tuple(cmd.get_view()) == camera
            result['styles'].append(dict(probe=probe, seconds=time.perf_counter()-start))
        result['points_unchanged'] = True
        result['grid_unchanged'] = sha(manifest['grid']) == manifest['grid_sha256']
        result['receptor_unchanged'] = sha(manifest['receptor']) == manifest['receptor_sha256']
        # Record what PyMOL's clipping command changes; no guessed matrix convention.
        cmd.clip('slab', 4, 'space')
        clipped = tuple(cmd.get_view())
        cmd.clip('atoms', 3, 'space')
        expanded = tuple(cmd.get_view())
        result['clip_changed_indices'] = [i for i, (a, b) in enumerate(zip(clipped, expanded)) if a != b]
        result['clipped_planes'] = clipped[15:17]
        result['expanded_planes'] = expanded[15:17]
        result['camera'] = camera
    (args.out / 'comparison.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
