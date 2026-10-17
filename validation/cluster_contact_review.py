"""Native retained-cluster contacts check in a disposable study; no docking."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

sys.path.insert(0, os.environ.get('DOCKING_UNIVERSAL_VALIDATION_LIBEXEC',
                               str(Path(__file__).resolve().parents[1] / 'libexec')))
from docking_universal.application import StudyController
from docking_universal.state import JsonStudyStore, StudyState
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.linked_pose_review import pose_view, PoseView
from docking_universal.gui.study_viewer import StudyViewerCoordinator
from docking_universal.viewer.embedded_pymol import create_embedded_pymol_widget, EmbeddedPymolAdapter
from PyQt6.QtTest import QTest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--state-file', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Validation output already exists')
    args.output.mkdir(parents=True)
    app = QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    result = {'checks': []}
    def check(name, condition):
        result['checks'].append(dict(name=name, passed=bool(condition)))
        if not condition:
            raise AssertionError(name)
    with TemporaryDirectory() as temporary:
        store = JsonStudyStore(Path(temporary) / 'state')
        StudyController(store).create_study('contacts', 'Retained cluster contact validation')
        source_state = args.state_file.read_bytes() if args.state_file else None
        if source_state:
            state = StudyState.from_dict(json.loads(source_state))
            if state.active_job:
                raise ValueError('Source study is still running')
            state.study_id = 'contacts'
            state.name = 'Read-only validation copy — ' + state.name
            state.revision = store.load('contacts').revision
            store.save(state)
        original = store.path_for('contacts').read_bytes()
        widget = create_embedded_pymol_widget()
        adapter = EmbeddedPymolAdapter(widget)
        window = StudyWindow(store, 'contacts', viewer_widget=widget,
            viewer_coordinator=StudyViewerCoordinator(adapter),
            settings=QtCore.QSettings(str(Path(temporary) / 'window.ini'), QtCore.QSettings.Format.IniFormat))
        exit_code = [0]
        def exercise():
            try:
                check('only interactive review remains', window.review_tabs.count() == 1
                      and window.review_tabs.currentWidget() is window.live_page)
                check('no static figure export action', not any('report figure' in action.text().lower()
                      for action in window.save_image.menu().actions()))
                diagrams = sorted(args.baseline.glob('compounds/*/pose_analysis/cluster_*/interactions/representative_plip2d.png'))
                check('six retained representative diagrams are available', len(diagrams) == 6)
                hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
                          for diagram in diagrams for p in (diagram, pose_view(diagram).interactions)}
                adapter.launch()
                window.viewer_coordinator.connected = True
                window._activate_workflow_target('screening_results_dock')
                first_camera = None
                for index, diagram in enumerate(diagrams):
                    view = pose_view(diagram)
                    # Exercise the ordinary cluster-choice handler, not only
                    # the paired-window loader that already supported contacts.
                    if args.state_file:
                        compound = diagram.parents[3].resolve()
                        for row in range(window.screening_results.rowCount()):
                            value = window.screening_results.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole)
                            if Path(value).resolve() == compound:
                                window.screening_results.selectRow(row)
                                break
                        choice = window.interaction_diagram_choice
                        target = next((i for i in range(choice.count())
                            if Path(choice.itemData(i)).resolve() == diagram.resolve()), -1)
                        check(f'cluster {index+1}: available through real result selection', target >= 0)
                        choice.setCurrentIndex(target)
                    else:
                        window.interaction_diagram_choice.blockSignals(True)
                        window.interaction_diagram_choice.clear()
                        window.interaction_diagram_choice.addItem(view.label, str(diagram))
                        window.interaction_diagram_choice.blockSignals(False)
                    window._show_selected_interaction_diagram()
                    QTest.qWait(50)
                    controls = window.cluster_contact_controls
                    check(f'cluster {index+1}: exact representative loaded', adapter.review_pose == view.ligand.resolve())
                    check(f'cluster {index+1}: PLIP geometry enabled',
                          'du_review_plip_contacts' in adapter.cmd.get_names('objects', enabled_only=1))
                    check(f'cluster {index+1}: type controls match its own report',
                          set(controls.styles) == {c['kind'] for c in adapter._plip_contacts})
                    check(f'cluster {index+1}: all contacting residues displayed',
                          len(adapter._contact_highlights) == len(controls.residues) > 0)
                    camera = tuple(adapter.cmd.get_view())
                    if first_camera is None:
                        adapter.cmd.turn('y', 22)
                        first_camera = tuple(adapter.cmd.get_view())
                    else:
                        check(f'cluster {index+1}: camera rotation retained', camera[:15] == first_camera[:15])
                    kind = next(iter(controls.styles))
                    controls.key.linkActivated.emit(kind)
                    check(f'cluster {index+1}: independent type toggle', not adapter._plip_types_visible[kind]
                          and all(v for k, v in adapter._plip_types_visible.items() if k != kind))
                    controls.contacts.setChecked(False)
                    controls.contacts.setChecked(True)
                    check(f'cluster {index+1}: master preserves type choice', not adapter._plip_types_visible[kind])
                    controls.key.linkActivated.emit(kind)
                    if index == 0:
                        window.resize(1440, 920)
                        QTest.qWait(100)
                        window.grab().save(str(args.output / 'cluster-with-contacts.png'))
                # A paired view temporarily borrows the engine and must restore
                # the cluster's contacts and toggle bookkeeping on return.
                controls = window.cluster_contact_controls
                kind = next(iter(controls.styles))
                controls.key.linkActivated.emit(kind)
                before = tuple(adapter.cmd.get_view())
                contacts_before = list(adapter._plip_contacts)
                window.open_selected_interaction_diagram()
                check('paired review button opens exact selected cluster', window._paired_interaction_window is not None
                      and window._paired_interaction_window.view == pose_view(diagrams[-1]))
                QTest.qWait(100)
                window._close_interaction_review()
                check('paired close restores selected cluster contacts', adapter._plip_contacts == contacts_before)
                check('paired close restores camera and type visibility', tuple(adapter.cmd.get_view()) == before
                      and not adapter._plip_types_visible[kind])
                window.open_full_pymol()
                QTest.qWait(100)
                detached = window._detached_structure_window
                check('detached full PyMOL borrows same contact controls',
                      detached.study_panel.contact_controls is controls and detached.isAncestorOf(controls))
                detached.study_panel.tabs.setCurrentIndex(1)
                controls.key.linkActivated.emit(kind)
                check('contacts toggle in detached full PyMOL', adapter._plip_types_visible[kind])
                detached.close()
                check('contact controls return to workspace', window.live_page.isAncestorOf(controls))
                missing = PoseView(view.ligand, view.receptor, view.diagram, args.output / 'missing.xml',
                                   'Missing report fixture', coordinate_kind='docked')
                window._highlight_linked_ligand(missing, highlight=False)
                check('missing report cannot leave stale contacts', not adapter._plip_contacts and
                      'du_review_plip_contacts' not in adapter.cmd.get_names('objects', enabled_only=1))
                check('missing report is explicitly explained', 'unavailable' in controls.key.text())
                check('original diagrams and PLIP reports unchanged', all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
                      for p, h in hashes.items()))
                check('study remains read-only', store.path_for('contacts').read_bytes() == original)
                if args.state_file:
                    check('real source study unchanged', args.state_file.read_bytes() == source_state)
                result['status'] = 'passed'
            except BaseException as exc:
                result.update(status='failed', error=str(exc))
                exit_code[0] = 1
                import traceback
                traceback.print_exc()
            finally:
                (args.output / 'verification.json').write_text(json.dumps(result, indent=2) + '\n')
                window.close()
                app.exit(exit_code[0])
        window.show()
        QtCore.QTimer.singleShot(300, exercise)
        app.exec()
        if exit_code[0]:
            raise SystemExit(exit_code[0])


if __name__ == '__main__':
    main()
