"""Isolated native validation of paired 2D/3D review; never edits a real study."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'libexec'))
from docking_universal.application import StudyController
from docking_universal.models import ArtifactRecord, PocketCandidate
from docking_universal.state import JsonStudyStore
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.linked_pose_review import PoseView, contact_residues, pose_view
from docking_universal.gui.study_viewer import StudyViewerCoordinator
from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter, create_embedded_pymol_widget
from PyQt6.QtTest import QTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, required=True)
    parser.add_argument('--diagram', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--docked-diagram', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    result = {'checks': []}
    def check(name, value):
        result['checks'].append({'name': name, 'passed': bool(value)})
        if not value:
            raise AssertionError(name)
    with TemporaryDirectory() as temporary:
        store = JsonStudyStore(Path(temporary) / 'state')
        controller = StudyController(store)
        controller.create_study('pair', 'Isolated paired review')
        evidence = {'geometry': {'center_x': 45, 'center_y': 43, 'center_z': -23,
                                'size_x': 20, 'size_y': 20, 'size_z': 20},
                    'conformational_site_evidence': {'status': 'conformationally_incompatible',
                        'occluding_residues': [{'name': 'ASP', 'chain': 'A', 'number': '30'}]}}
        controller.start_simulated_pocket_review('pair', [PocketCandidate('P1', 'P1', 1, 'box', 'Validation', evidence)])
        state = store.load('pair')
        receptor = Path(__file__).resolve().parents[1] / 'examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb'
        state.artifacts.append(ArtifactRecord('receptor', 'prepared_receptor_structure', str(receptor), hashlib.sha256(receptor.read_bytes()).hexdigest()))
        store.save(state)
        original = store.path_for('pair').read_bytes()
        widget = create_embedded_pymol_widget()
        adapter = EmbeddedPymolAdapter(widget)
        coordinator = StudyViewerCoordinator(adapter)
        window = StudyWindow(store, 'pair', viewer_widget=widget, viewer_coordinator=coordinator,
            settings=QtCore.QSettings(str(Path(temporary) / 'window.ini'), QtCore.QSettings.Format.IniFormat))
        exit_code = [0]
        def exercise():
            try:
                result['command_times'] = {}
                for operation in ('get_session', 'set_session', 'load', 'get_model'):
                    original_command = getattr(adapter.cmd, operation)
                    def timed(*a, _operation=operation, _command=original_command, **kw):
                        start = time.perf_counter()
                        try:
                            return _command(*a, **kw)
                        finally:
                            times = result['command_times'].setdefault(_operation, {'seconds': 0, 'calls': 0})
                            times['seconds'] += time.perf_counter() - start
                            times['calls'] += 1
                    setattr(adapter.cmd, operation, timed)
                engine = adapter.cmd._COb
                adapter.cmd.select('user_selection', 'du_receptor and resi 5')
                camera = tuple(adapter.cmd.get_view())
                original_float_labels = adapter.cmd.get_setting_int('float_labels')
                objects = adapter.cmd.get_names('objects', enabled_only=1)
                source = json.loads((args.cache / 'input.json').read_text())
                view = PoseView(args.cache / 'ligand.sdf', args.cache / 'receptor.pdb', args.diagram,
                                args.cache / 'plip/report.xml', f"{source['entry']} · deposited interactions",
                                ligand_name=source['ligand'])
                diagram_hash = hashlib.sha256(args.diagram.read_bytes()).hexdigest()
                opening = time.perf_counter()
                check('paired window opens', window._open_interaction_review(view))
                result['first_open_seconds'] = time.perf_counter() - opening
                pair = window._paired_interaction_window
                check('experimental coordinates are explicitly not a docked pose',
                      pair.basis.text().startswith('Experimental structure only — not a docked pose'))
                QTest.qWait(200)
                window.refresh()
                check('GUI polling retains paired view', window._paired_interaction_window is pair and window.linked_pose_panel.query == view)
                check('one engine and borrowed viewport', adapter.cmd._COb is engine and pair.isAncestorOf(widget))
                check('window is non-modal and not fullscreen', not pair.isModal() and not pair.isFullScreen())
                check('all report residues have working toggles', len(pair.residue_buttons) == len(contact_residues(view))
                      and all(b.isChecked() and b.isEnabled() for b in pair.residue_buttons.values()))
                camera_pair = tuple(adapter.cmd.get_view())
                for axis, angle in (('x', 90), ('y', 45), ('z', 60)):
                    adapter.cmd.turn(axis, angle)
                    turned = tuple(adapter.cmd.get_view())
                    adapter.cmd.clip('atoms', 6, 'enabled')
                    needed = tuple(adapter.cmd.get_view())
                    check(f'paired starting slab shows complete receptor after {axis} rotation',
                          turned[15] <= needed[15] and turned[16] >= needed[16])
                    adapter.cmd.set_view(camera_pair)
                check('initial review centers on matching ligand', all(
                    abs(camera_pair[12+i] - adapter.cmd.get_position('du_review_pose')[i]) < 0.001
                    for i in range(3)))
                check('cartoon is available without protein surface', adapter.cmd.count_atoms(
                    'du_linked_receptor and rep cartoon') and not adapter.cmd.count_atoms('du_linked_receptor and rep surface'))
                pair.cartoon.setChecked(False)
                check('cartoon toggle hides it without moving camera', not adapter.cmd.count_atoms('du_linked_receptor and rep cartoon')
                      and tuple(adapter.cmd.get_view()) == camera_pair)
                pair.cartoon.setChecked(True)
                check('same-report PLIP contacts are displayed', 'du_review_plip_contacts' in adapter.cmd.get_names('objects', enabled_only=1)
                      and len(adapter._plip_contacts) > 0)
                pair.contacts.setChecked(False)
                check('PLIP contacts independently toggle', not adapter._plip_contacts_visible and tuple(adapter.cmd.get_view()) == camera_pair)
                pair.contacts.setChecked(True)
                diagram_size = pair.diagram_panel.query_image.pixmap().size()
                types = pair.contact_type_actions
                from docking_universal.viewer.plip_contacts import STYLES
                from pymol import cgo
                def expected_colors(kinds):
                    return {tuple(round(int(STYLES[k][1][i:i+2], 16) / 255, 5) for i in (1, 3, 5)) for k in kinds}
                def displayed_contact_colors():
                    # Inspect the native object's DISPLAYED state, not our
                    # visibility booleans or submitted load_cgo arguments.
                    objects = adapter.cmd.get_session('du_review_plip_contacts', partial=1, cache=0, compress=0)['names']
                    data = objects[0][5][2][0][0][1]
                    assert len(data) % 14 == 0 and all(round(data[i]) == cgo.CYLINDER for i in range(0, len(data), 14))
                    return {tuple(round(v, 5) for v in data[i+8:i+11]) for i in range(0, len(data), 14)}
                check('clickable key includes exactly the displayed contact types', set(types) == set(adapter._plip_types_visible))
                check('native displayed contact state initially includes every type', displayed_contact_colors() == expected_colors(types))
                for kind, type_button in types.items():
                    pair.contact_key.linkActivated.emit(kind)
                    check(f'{kind} hides independently', not adapter._plip_types_visible[kind]
                          and all(v for k, v in adapter._plip_types_visible.items() if k != kind))
                    check('type toggle preserves camera and diagram size', tuple(adapter.cmd.get_view()) == camera_pair
                          and pair.diagram_panel.query_image.pixmap().size() == diagram_size)
                    check('type toggle replaces the displayed contact geometry state', adapter.cmd.count_states('du_review_plip_contacts') == 1)
                    check(f'{kind} is absent from visible native geometry while others remain',
                          displayed_contact_colors() == expected_colors(set(types) - {kind}))
                    pair.contact_key.linkActivated.emit(kind)
                    check('restored native geometry contains all types again', displayed_contact_colors() == expected_colors(types))
                first_type = next(iter(types))
                types[first_type].setChecked(False)
                pair.contacts.setChecked(False)
                pair.contacts.setChecked(True)
                check('master visibility preserves individual type choice', not adapter._plip_types_visible[first_type]
                      and not types[first_type].isChecked())
                types[first_type].setChecked(True)
                for type_button in types.values():
                    type_button.setChecked(False)
                check('all types off hides contact object', 'du_review_plip_contacts' not in adapter.cmd.get_names('objects', enabled_only=1))
                for type_button in types.values():
                    type_button.setChecked(True)
                check('restoring types restores contact object', 'du_review_plip_contacts' in adapter.cmd.get_names('objects', enabled_only=1))
                selections = adapter.cmd.get_names('selections')
                for modifier in (QtCore.Qt.KeyboardModifier.ShiftModifier, QtCore.Qt.KeyboardModifier.ControlModifier):
                    QTest.mousePress(widget, QtCore.Qt.MouseButton.LeftButton, modifier, QtCore.QPoint(50, 50))
                    QTest.mouseMove(widget, QtCore.QPoint(200, 150))
                    QTest.mouseRelease(widget, QtCore.Qt.MouseButton.LeftButton, modifier, QtCore.QPoint(200, 150))
                    check('modified paired drag creates no selection and leaves camera alone',
                          adapter.cmd.get_names('selections') == selections and tuple(adapter.cmd.get_view()) == camera_pair
                          and not widget._du_blocked_gesture)
                chains = {r['chain'] for r in contact_residues(view)}
                result['contact_chains'] = sorted(chains)
                for residue in contact_residues(view):
                    check(f"exact contact maps in chain {residue['chain']}",
                          bool(adapter._contact_residue_atoms(residue)))
                record = source
                window._show_evidence_render_progress(record)
                progress = window._evidence_2d_progress
                check('fresh rendering has visible non-modal activity', progress.isVisible()
                      and not progress.isModal() and progress.minimum() == progress.maximum() == 0
                      and 'PLIP' in progress.labelText() and 'Elapsed:' in progress.labelText())
                window._close_evidence_render_progress()
                check('render activity closes cleanly', window._evidence_2d_progress is None)
                panel = pair.diagram_panel
                hits = panel.query_image.hit_regions
                check('fresh diagram has source-verified click regions', bool(hits))
                check('every verified clickable name has an outline', len(panel.query_image.residue_boxes()) == len(hits))
                hit = hits[0]
                picked = dict(hit['residue'], object='du_linked_receptor')
                atom = adapter._contact_residue_atoms(hit['residue'])[0]
                check('residue labels start optional and off', not pair.labels.isChecked()
                      and not adapter.has_review_residue_labels())
                camera_labels = tuple(adapter.cmd.get_view())
                for visible in (True, False, True, False):
                    pair.labels.setChecked(visible)
                    check('master residue label switch controls real PyMOL labels',
                          bool(adapter.cmd.count_atoms('du_linked_receptor and rep labels')) == visible
                          and adapter.has_review_residue_labels() == visible)
                    check('label switch preserves camera and contact visibility',
                          tuple(adapter.cmd.get_view()) == camera_labels and adapter._plip_contacts_visible)
                from docking_universal.gui.image_export import pymol_export, diagram_export, paired_export
                pair.labels.setChecked(True)
                export_type = next(iter(pair.contact_type_actions))
                pair.contact_type_actions[export_type].setChecked(False)
                export_camera = tuple(adapter.cmd.get_view())
                export_labels = set(adapter._review_labels)
                export_types = dict(adapter._plip_types_visible)
                protected = (view.diagram, view.ligand, view.receptor, view.interactions)
                source_hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in protected]
                scene = pymol_export(widget, {'coordinate_kind': 'experimental'}, protected)
                scene.save(args.output / 'custom-3d.png')
                diagram = diagram_export(view)
                diagram.save(args.output / 'original-2d.png')
                combined = paired_export(view, widget, pair._export_contact_legend())
                combined.save(args.output / 'clean-panels.png')
                check('native current-view export creates nonempty 3D PNG',
                      not scene.image.isNull() and scene.image.width() > 100 and scene.image.height() > 100)
                from docking_universal.gui.qt import QtGui
                original_diagram = QtGui.QImage(str(view.diagram))
                check('2D export retains original pixel resolution and pixels',
                      diagram.image.size() == original_diagram.size()
                      and diagram.image == original_diagram)
                check('clean paired PNG declares experimental basis and only visible contact types',
                      combined.context['coordinate_kind'] == 'experimental'
                      and all(name != pair.contact_type_actions[export_type].text()
                              for name, color in combined.context['visible_3d_contacts']))
                check('export preserves customized camera labels and contact choices',
                      tuple(adapter.cmd.get_view()) == export_camera
                      and adapter._review_labels == export_labels
                      and adapter._plip_types_visible == export_types)
                check('export leaves all retained scientific files unchanged',
                      source_hashes == [hashlib.sha256(p.read_bytes()).hexdigest() for p in protected])
                ticks = []
                ray_timer = QtCore.QTimer()
                ray_timer.timeout.connect(lambda: ticks.append(time.perf_counter()))
                ray_timer.start(10)
                ray_scene = pymol_export(widget, {'coordinate_kind': 'experimental'}, protected, ray=True)
                ray_timer.stop()
                ray_scene.save(args.output / 'ray-3d.png')
                check('real experimental CPU ray export is valid and identified',
                      not ray_scene.image.isNull() and ray_scene.context['rendering'] == 'ray_traced')
                check('ray rendering keeps the GUI event loop responsive', bool(ticks))
                check('ray export preserves camera contact choices labels and native dimensions',
                      tuple(adapter.cmd.get_view()) == export_camera and adapter._review_labels == export_labels
                      and adapter._plip_types_visible == export_types and ray_scene.image.size() == scene.image.size())
                pair.contact_type_actions[export_type].setChecked(True)
                pair.labels.setChecked(False)
                for expected in (True, False):
                    adapter.cmd.select('pk1', f'du_linked_receptor and index {atom.index}')
                    adapter.cmd.get_wizard().do_pick(0)
                    check('3D pick toggles a residue label without selection markers', bool(adapter._review_labels) == expected
                          and not adapter.cmd.get_names('selections', enabled_only=1) == ['pk1']
                          and not adapter.cmd.count_atoms('?pk1'))
                    check('review labels are large and foreground',
                          adapter.cmd.get_setting_float('label_size', 'du_linked_receptor') == 22
                          and adapter.cmd.get_setting_int('float_labels', 'du_linked_receptor') == 1)
                    check('individual picks synchronize the label switch', pair.labels.isChecked() == expected)
                button = pair.residue_buttons[pair.key(hit['residue'])]
                pixmap = panel.query_image.pixmap()
                rect = hit['rect']
                x = (rect[0] + rect[2] / 2) * pixmap.width() + (panel.query_image.width() - pixmap.width()) / 2
                y = (rect[1] + rect[3] / 2) * pixmap.height() + (panel.query_image.height() - pixmap.height()) / 2
                size = pixmap.size()
                for checked in (True, False):
                    button.setChecked(checked)
                    camera_before_click = tuple(adapter.cmd.get_view())
                    QTest.mouseClick(panel.query_image, QtCore.Qt.MouseButton.LeftButton, pos=QtCore.QPoint(round(x), round(y)))
                    centered = tuple(adapter.cmd.get_view())
                    check(f'diagram click leaves checkbox {checked}', button.isChecked() == checked)
                    check('centering preserves scale rotation and 2D size', centered[:9] == camera_pair[:9] and centered[11] == camera_pair[11]
                          and centered[15:] == camera_pair[15:] and panel.query_image.pixmap().size() == size)
                    if checked:
                        check('diagram click pans the camera', centered != camera_before_click)
                    residue = hit['residue']
                    target = adapter._contact_residue_atoms(residue)
                    visible = {a.index for a in adapter.cmd.get_model('du_linked_receptor and rep sticks').atom}
                    check('checkbox determines sticks even after centering', all((a.index in visible) == checked for a in target))
                check('boxed ligand name is an explicit target', source['ligand'] in panel.heading.text()
                      and 'Center ligand' in panel.heading.text())
                panel.heading.click()
                centered = tuple(adapter.cmd.get_view())
                check('ligand click centers without changing zoom or checkbox', centered[:9] == camera_pair[:9] and centered[11] == camera_pair[11]
                      and centered[15:] == camera_pair[15:] and not button.isChecked())
                origin = adapter.cmd.get_position('du_review_pose')
                check('camera origin is matching ligand center', all(abs(centered[12+i] - origin[i]) < 0.001 for i in range(3)))
                current_camera = tuple(adapter.cmd.get_view())
                button.setChecked(True)
                check('checkbox toggle does not pan', tuple(adapter.cmd.get_view()) == current_camera)
                check('no temporary atom-selection markers', not any(n.startswith(('du_contact_', 'du_center_')) for n in adapter.cmd.get_names('selections')))
                pair.showNormal()
                pair.resize(1100, 740)
                pair.splitter.setSizes([420, 620])
                QTest.qWait(150)
                # Actual Qt link click, not just a programmatically emitted signal.
                key = pair.contact_key
                fm = key.fontMetrics()
                x = fm.horizontalAdvance('3D contacts: ') + fm.horizontalAdvance('■ ') + 20
                QTest.mouseClick(key, QtCore.Qt.MouseButton.LeftButton,
                                pos=QtCore.QPoint(x, fm.lineSpacing()//2))
                check('native inline legend link responds to a mouse click', not types[first_type].isChecked())
                types[first_type].setChecked(True)
                check('legend remains a compact text key', key.height() <= 2 * fm.lineSpacing() + 4)
                pair.clicked_3d_residue(picked)
                QTest.qWait(300)
                result['frame_latency'] = window._paired_review_latency
                check('both panes remain visible after resize', widget.isVisible() and panel.query_image.isVisible())
                check('contact legend precedes cartoon and master contact switches',
                      pair.contact_key.geometry().bottom() < pair.cartoon.geometry().top()
                      and pair.contacts.geometry().bottom() < pair.residue_scroll.geometry().top())
                check('residue controls use less height than old row', pair.residue_scroll.height() < 68)
                box = panel.query_image.residue_boxes()[0][1]
                adapter.center_contact_residue(hit['residue'])
                expected_center = tuple(adapter.cmd.get_view())
                pair.clicked_ligand()
                QTest.mouseClick(panel.query_image, QtCore.Qt.MouseButton.LeftButton, pos=box.center().toPoint())
                centered = tuple(adapter.cmd.get_view())
                check('resized residue box centers the matching source residue',
                      centered == expected_center)
                check('detailed retained diagram remains unchanged',
                      hashlib.sha256(args.diagram.read_bytes()).hexdigest() == diagram_hash)
                pair.grab().save(str(args.output / 'paired.png'))
                pair.close()
                QTest.qWait(150)
                check('closing restores viewport and study camera', widget.parentWidget() is window.pose_split and tuple(adapter.cmd.get_view()) == camera)
                check('closing restores scene, selection and same engine', adapter.cmd._COb is engine and adapter.cmd.get_names('objects', enabled_only=1) == objects
                      and 'user_selection' in adapter.cmd.get_names('selections'))
                check('closing restores unrestricted input behavior', not widget._du_interaction_review and not widget._du_blocked_gesture)
                check('closing restores original foreground-label setting', adapter.cmd.get_setting_int('float_labels') == original_float_labels)
                check('diagram no longer crowds the main viewer', window.linked_pose_panel.isHidden())
                reopening = time.perf_counter()
                check('cached pair reopens', window._open_interaction_review(view))
                result['cached_reopen_seconds'] = time.perf_counter() - reopening
                window._close_interaction_review()
                if args.docked_diagram:
                    docked = pose_view(args.docked_diagram)
                    check('retained docking artifact resolves exact pose', docked is not None)
                    retained_paths = (docked.ligand, docked.receptor, docked.diagram, docked.interactions)
                    hashes = [hashlib.sha256(p.read_bytes()).hexdigest() for p in retained_paths]
                    check('same paired viewer opens retained docked pose', window._open_interaction_review(docked))
                    dock_pair = window._paired_interaction_window
                    QTest.qWait(200)
                    check('docked view states exact retained pose basis', 'exact retained docking pose' in dock_pair.basis.text())
                    before = tuple(adapter.cmd.get_view())
                    dock_pair.diagram_panel.heading.click()
                    check('boxed target centers retained dock without zoom change', tuple(adapter.cmd.get_view())[:12] == before[:12]
                          and tuple(adapter.cmd.get_view())[15:] == before[15:])
                    kind = next(iter(dock_pair.contact_type_actions))
                    dock_pair.contact_key.linkActivated.emit(kind)
                    check('docked interaction type toggles independently', not adapter._plip_types_visible[kind])
                    dock_pair.contact_key.linkActivated.emit(kind)
                    residue = dict(contact_residues(docked)[0], object='du_linked_receptor')
                    dock_camera_labels = tuple(adapter.cmd.get_view())
                    dock_pair.clicked_3d_residue(residue)
                    check('docked residue label is large and foreground',
                          adapter.cmd.get_setting_float('label_size', 'du_linked_receptor') == 22
                          and adapter.cmd.get_setting_int('float_labels', 'du_linked_receptor') == 1)
                    check('docked pick activates the same optional label switch', dock_pair.labels.isChecked())
                    dock_pair.labels.setChecked(False)
                    check('docked label switch clears actual label representation without moving camera',
                          not adapter.cmd.count_atoms('du_linked_receptor and rep labels')
                          and tuple(adapter.cmd.get_view()) == dock_camera_labels)
                    dock_export = paired_export(docked, widget, dock_pair._export_contact_legend(), ray=True)
                    dock_export.save(args.output / 'docked-clean-panels.png')
                    check('docked export uses the same path with correct docked provenance and unchanged camera',
                          dock_export.context['coordinate_kind'] == 'docked'
                          and dock_export.context['rendering_3d'] == 'ray_traced'
                          and tuple(adapter.cmd.get_view()) == dock_camera_labels)
                    dock_pair.showNormal()
                    dock_pair.resize(1100, 740)
                    QTest.qWait(300)
                    dock_pair.grab().save(str(args.output / 'docked-paired.png'))
                    window._close_interaction_review()
                    check('retained docking files were not changed', hashes == [hashlib.sha256(p.read_bytes()).hexdigest() for p in retained_paths])
                    check('docked review restores initial scene camera', tuple(adapter.cmd.get_view()) == camera)
                panel = window.pocket_evidence_panel
                panel.obstruction_details_button.click()
                check('details popup is modeless and explains rule', panel._obstruction_details_window is not None and not panel._obstruction_details_window.isModal()
                      and '0.5' in panel._obstruction_details_window.findChild(QtWidgets.QTextBrowser).toPlainText())
                panel._obstruction_details_window.close()
                check('review leaves scientific state unchanged', store.path_for('pair').read_bytes() == original)
                adapter.cmd.clip('slab', 2, 'enabled')
                report = Path(temporary) / 'deliberately_clipped.pse'
                adapter.cmd.save(str(report))
                report_hash = hashlib.sha256(report.read_bytes()).hexdigest()
                adapter.load_report_session(report)
                starting = tuple(adapter.cmd.get_view())
                adapter.cmd.clip('atoms', 6, 'enabled')
                needed = tuple(adapter.cmd.get_view())
                check('loading a clipped retained report starts with complete scene geometry',
                      starting[15] <= needed[15] and starting[16] >= needed[16])
                check('report initialization does not rewrite its retained PSE',
                      hashlib.sha256(report.read_bytes()).hexdigest() == report_hash)
            except Exception as exc:
                result['error'] = str(exc)
                exit_code[0] = 1
            finally:
                (args.output / 'verification.json').write_text(json.dumps(result, indent=2))
                print(json.dumps(result, indent=2), flush=True)
                window.close()
                app.quit()
        window.show()
        QtCore.QTimer.singleShot(1000, exercise)
        app.exec()
    return exit_code[0]


if __name__ == '__main__':
    raise SystemExit(main())
