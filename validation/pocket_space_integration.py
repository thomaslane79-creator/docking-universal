"""Generate and exercise real, hash-bound alpha surfaces without changing a study."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'libexec'))
from docking_universal.services.pocket_space import VERSION, sha, cached


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receptor', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--prank', type=Path, required=True)
    parser.add_argument('--scientific-python', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    root = args.out.resolve()
    root.mkdir(parents=True, exist_ok=True)
    record = dict(version=VERSION, receptor=str(args.receptor.resolve()),
                  predictions=str(args.predictions.resolve()), cache=str(root),
                  receptor_sha256=sha(args.receptor), predictions_sha256=sha(args.predictions))
    request = root / 'request.json'
    request.write_text(json.dumps(record, indent=2))
    environment = os.environ.copy()
    environment['JAVA_HOME'] = str(args.scientific_python.parent.parent / 'lib/jvm')
    subprocess.run([str(args.scientific_python),
                    str(Path(__file__).resolve().parents[1] / 'libexec/docking-universal-pocket-space.py'),
                    '--request', str(request), '--prank', str(args.prank.resolve())],
                   env=environment, check=True)
    manifest = cached(record)
    assert manifest is not None
    from docking_universal.gui.qt import QtCore, QtWidgets
    from PyQt6.QtTest import QTest
    from docking_universal.viewer.embedded_pymol import create_embedded_pymol_widget, EmbeddedPymolAdapter
    app = QtWidgets.QApplication([])
    widget = create_embedded_pymol_widget()
    widget.resize(1000, 780)
    widget.show()
    adapter = EmbeddedPymolAdapter(widget)
    adapter.launch()
    cmd = adapter.cmd
    cmd.load(record['receptor'], 'receptor')
    cmd.hide('everything', 'all')
    cmd.show('cartoon', 'receptor')
    cmd.color('gray70', 'receptor')
    # Represent the old site-residue surface too, to verify replacement.
    cmd.create('du_pocket_1', 'receptor and resi 30+50')
    cmd.show('surface', 'du_pocket_1')
    cmd.orient('receptor', animate=0)
    cmd.zoom('receptor', buffer=5, animate=0)
    camera = tuple(cmd.get_view())
    checks = []

    def check(name, condition):
        checks.append(dict(name=name, passed=bool(condition)))
        assert condition, name

    def exercise():
        try:
            for rank, color in [(int(r), ('red', 'marine', 'gold', 'magenta')[(int(r)-1) % 4])
                                for r in manifest['counts']]:
                names = adapter.show_pocket_space(manifest, [rank], color)
                obj = 'du_pocket_space_' + str(rank)
                check('one matching rank enabled ' + str(rank), names == [obj] and
                      [n for n in cmd.get_names('objects', enabled_only=1)
                       if n.startswith('du_pocket_space_')] == [obj])
                check('surface, not dots ' + str(rank), cmd.count_atoms(obj + ' and rep surface') > 0
                      and cmd.count_atoms(obj + ' and rep spheres') == 0)
                check('camera unchanged ' + str(rank), tuple(cmd.get_view()) == camera)
                check('rank assignments preserved ' + str(rank),
                      {a.resi for a in cmd.get_model(obj).atom} == {str(rank)})
                colors = []
                cmd.iterate(obj, 'colors.append(color)', space={'colors': colors})
                check('matching palette ' + str(rank),
                      all(cmd.get_color_tuple(c) == cmd.get_color_tuple(color) for c in colors))
                QTest.qWait(150)
            check('old residue surface hidden', cmd.count_atoms('du_pocket_1 and rep surface') == 0)
            adapter.show_pocket_space(manifest, [1], 'red')
            points = cmd.get_coords('du_pocket_space_1').tolist()
            radii = [a.vdw for a in cmd.get_model('du_pocket_space_1').atom]
            check('object-local smoothing enabled', cmd.get_setting_float('solvent_radius', 'du_pocket_space_1') == 1.4
                  and cmd.get_setting_int('surface_solvent', 'du_pocket_space_1') == 0
                  and cmd.get_setting_int('surface_quality', 'du_pocket_space_1') == 2)
            check('protein surface settings unchanged', cmd.get_setting_float('solvent_radius', 'receptor') == 1.4)
            cmd.clip('slab', 4, 'du_pocket_space_1')
            clipped = tuple(cmd.get_view())
            adapter.show_pocket_space(manifest, [1], 'red')
            expanded = tuple(cmd.get_view())
            check('clipped pocket expands slab without zoom or pan', expanded[:15] == clipped[:15]
                  and expanded[17] == clipped[17] and expanded[15] < clipped[15] and expanded[16] > clipped[16])
            cmd.clip('atoms', 3.42, 'du_pocket_space_1')
            needed = tuple(cmd.get_view())
            check('expanded slab encloses pocket with buffer', expanded[15] <= needed[15] and expanded[16] >= needed[16])
            cmd.set_view(expanded)
            adapter.show_pocket_space(manifest, [1], 'red')
            check('repeat never shrinks clipping slab', tuple(cmd.get_view()) == expanded)
            check('grid-point geometry and radii unchanged', cmd.get_coords('du_pocket_space_1').tolist() == points
                  and [a.vdw for a in cmd.get_model('du_pocket_space_1').atom] == radii)
            cmd.set_view(camera)
            QTest.qWait(300)
            widget.grabFramebuffer().save(str(root / 'native-surface.png'))
            check('cached manifest reusable', cached(record) == manifest)
            (root / 'verification.json').write_text(json.dumps(dict(checks=checks, counts=manifest['counts'],
                stable_predictions_unchanged=sha(args.predictions) == record['predictions_sha256'],
                receptor_unchanged=sha(args.receptor) == record['receptor_sha256']), indent=2))
            app.exit(0)
        except Exception as exc:
            print(str(exc), file=sys.stderr)
            app.exit(1)
        finally:
            adapter.close()
            widget.close()

    QtCore.QTimer.singleShot(400, exercise)
    return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
