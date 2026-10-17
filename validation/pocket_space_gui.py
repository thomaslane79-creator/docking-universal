"""Isolated fresh/cached GUI acceptance for the installed alpha visual worker."""
import argparse
import json
from pathlib import Path
import shutil
import sys
from tempfile import TemporaryDirectory
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'libexec'))
from docking_universal.application import StudyController
from docking_universal.models import ArtifactRecord, PocketCandidate
from docking_universal.state import JsonStudyStore
from docking_universal.services.pocket_space import sha, rows
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.gui.study_viewer import StudyViewerCoordinator, POCKET_COLORS
from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter, create_embedded_pymol_widget
from PyQt6.QtTest import QTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--receptor', type=Path, required=True)
    parser.add_argument('--predictions', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    result = {'checks': []}
    def check(name, value):
        result['checks'].append(dict(name=name, passed=bool(value)))
        assert value, name
    with TemporaryDirectory() as directory:
        root = Path(directory)
        cavity = root / 'cavity'
        cavity.mkdir()
        stable = cavity / 'stable.csv'
        shutil.copy2(args.predictions, stable)
        (cavity / 'pocket_detection_provenance.json').write_text(json.dumps(dict(
            engine='p2rank', receptor=str(args.receptor.resolve()), source_predictions=str(stable))))
        store = JsonStudyStore(root / 'state')
        controller = StudyController(store)
        controller.create_study('visual', 'Isolated alpha surface')
        candidates, artifacts = [], []
        for index, row in enumerate(rows(stable)):
            rank = int(row['rank'])
            if rank == 3:  # exercise retained original IDs after a filtered rank
                continue
            geometry = {f'center_{a}': float(row[f'center_{a}']) for a in 'xyz'}
            geometry.update({f'size_{a}': 26 for a in 'xyz'})
            box = cavity / f'box_{rank}.conf'
            box.write_text('\n'.join(f'{k} = {v}' for k, v in geometry.items()))
            identity = f'P{rank}'
            candidates.append(PocketCandidate(identity, identity, len(candidates)+1,
                f'box-{rank}', 'p2rank validation fixture', dict(geometry=geometry, kind='p2rank')))
            artifacts.append(ArtifactRecord(f'box-{rank}', 'docking_box', str(box), sha(box)))
        controller.start_simulated_pocket_review('visual', candidates)
        state = store.load('visual')
        state.artifacts.extend(artifacts + [ArtifactRecord('receptor', 'prepared_receptor_structure',
            str(args.receptor.resolve()), sha(args.receptor))])
        store.save(state)
        original = store.path_for('visual').read_bytes()
        widget = create_embedded_pymol_widget()
        adapter = EmbeddedPymolAdapter(widget)
        window = StudyWindow(store, 'visual', viewer_widget=widget,
            viewer_coordinator=StudyViewerCoordinator(adapter),
            settings=QtCore.QSettings(str(root / 'window.ini'), QtCore.QSettings.Format.IniFormat))
        # No application-host job is launched: only its installed worker environment.
        window.host_client = ApplicationHostClient(root / 'state',
            '/opt/anaconda3/envs/docking-universal/libexec/docking-universal/docking-universal-application-host.py',
            python_executable='/opt/anaconda3/envs/docking-universal/bin/python')
        window.refresh_timer.stop()
        window.resize(1280, 850)
        window.show()
        def exercise():
            code = 0
            try:
                started = time.perf_counter()
                window._select_plotted_candidate('P1')
                for _ in range(300):
                    QTest.qWait(100)
                    if 'du_pocket_space_1' in adapter.cmd.get_names('objects', enabled_only=1):
                        break
                result['fresh_seconds'] = time.perf_counter() - started
                check('fresh GUI worker attaches surface',
                      'du_pocket_space_1' in adapter.cmd.get_names('objects', enabled_only=1))
                geometry = (window.width(), window.height(), widget.width(), widget.height())
                adapter.cmd.turn('y', 37)
                adapter.cmd.move('x', 4)
                positioned = tuple(adapter.cmd.get_view())
                views = []
                for identity in ('P2', 'P4', 'P1', 'P2'):
                    start = time.perf_counter()
                    window._select_plotted_candidate(identity)
                    QTest.qWait(100)
                    views.append(tuple(adapter.cmd.get_view()))
                    rank = int(identity[1:])
                    check('matched grid ' + identity, [n for n in adapter.cmd.get_names('objects', enabled_only=1)
                        if n.startswith('du_pocket_space_')] == [f'du_pocket_space_{rank}'])
                    candidate = next(c for c in candidates if c.id == identity)
                    colors = []
                    adapter.cmd.iterate(f'du_pocket_space_{rank}', 'colors.append(color)', space={'colors': colors})
                    check('same palette as box ' + identity, all(adapter.cmd.get_color_tuple(c) ==
                        adapter.cmd.get_color_tuple(POCKET_COLORS[candidate.rank-1]) for c in colors))
                    check('fixed layout ' + identity, geometry == (window.width(), window.height(), widget.width(), widget.height()))
                    result.setdefault('cached_seconds', []).append(time.perf_counter() - start)
                check('switches preserve user rotation pan zoom and pivot',
                      all(v[:15] == positioned[:15] and v[17] == positioned[17] for v in views))
                check('switches only widen clipping planes', all(b[15] <= a[15] and b[16] >= a[16]
                    for a, b in zip(views, views[1:])))
                camera = tuple(adapter.cmd.get_view())
                window.open_full_pymol()
                QTest.qWait(200)
                full = window._detached_structure_window
                check('surface transfers to full PyMOL', full is not None and full.pymolwidget is widget
                    and 'du_pocket_space_2' in adapter.cmd.get_names('objects', enabled_only=1))
                check('detachment preserves surface camera', tuple(adapter.cmd.get_view()) == camera)
                full.close()
                QTest.qWait(200)
                check('surface returns to embedded GUI', window._detached_structure_window is None
                    and window.isAncestorOf(widget) and 'du_pocket_space_2' in adapter.cmd.get_names('objects', enabled_only=1))
                check('scientific state unchanged', store.path_for('visual').read_bytes() == original)
                window.grab().save(str(args.out / 'gui-surface.png'))
            except Exception as exc:
                code = 1
                result['error'] = str(exc)
            finally:
                (args.out / 'verification.json').write_text(json.dumps(result, indent=2))
                window.close()
                app.exit(code)
        QtCore.QTimer.singleShot(500, exercise)
        return app.exec()


if __name__ == '__main__':
    raise SystemExit(main())
