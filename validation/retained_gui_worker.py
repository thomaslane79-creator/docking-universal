"""Exercise real installed GUI/PyMOL controls on verified retained pipeline output.

No docking, preparation, PLIP regeneration or scientific approval is permitted.
The source study is copied; retained science remains read-only and hash checked.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch

import system_validation as system


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-case', required=True, type=Path)
    parser.add_argument('--runtime', required=True, type=Path)
    parser.add_argument('--scientific-python', required=True)
    parser.add_argument('--cli', required=True)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--ray', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve(); out.mkdir(parents=True, exist_ok=False)
    source = args.source_case.resolve()
    row = json.loads(source.read_text())
    if row.get('status')!='passed' or row.get('layer')!='workflow':
        raise ValueError('Native review requires a completed passing real workflow record')
    source_run = source.parents[2]
    system.verify_saved(row, source_run)
    original = source.parent / 'worker/studies/validation/application_state.json'
    destination = out / 'studies/review/application_state.json'
    destination.parent.mkdir(parents=True)
    state = json.loads(original.read_text())
    # The store resolves its ID independently; keep all artifact references to
    # the exact retained sources rather than copying/reconstructing chemistry.
    state['study_id'] = 'review'
    system.write(destination, state)
    before = system.sha(destination)
    record = {'status':'running','phase':'preflight','checks':[], 'scientific_jobs_launched':0,
              'coverage':'Native installed controls on retained real output; not a fresh raw-input pipeline run'}
    def save():
        system.write(out/'summary.json', record)
    def check(condition, label):
        if not condition:
            raise ValueError(label)
        record['checks'].append(label)
    save()
    # system_validation imports project helpers before this point; clear only
    # that namespace so the window/viewer come from the installed runtime.
    for name in list(sys.modules):
        if name == 'docking_universal' or name.startswith('docking_universal.'):
            del sys.modules[name]
    sys.path.insert(0, str(args.runtime.resolve()))
    prefix = Path(args.scientific_python).parent.parent
    os.environ.update(DOCKING_UNIVERSAL_LIBEXEC=str(args.runtime), DOCKING_UNIVERSAL_PYTHON=args.scientific_python,
                      DOCKING_UNIVERSAL_CLI=args.cli)
    os.environ.pop('QT_QPA_PLATFORM', None)
    os.environ['PATH'] = str(prefix.parent.parent/'bin') + os.pathsep + str(prefix/'bin') + os.pathsep + os.environ.get('PATH','')
    from docking_universal.gui.qt import QtCore, QtWidgets
    from docking_universal.gui.desktop import StudyWindow
    from docking_universal.gui.host_client import ApplicationHostClient
    from docking_universal.gui.study_viewer import StudyViewerCoordinator
    from docking_universal.gui.linked_pose_review import pose_view
    from docking_universal.gui.image_export import diagram_export, paired_export, pymol_export
    from docking_universal.viewer.embedded_pymol import create_embedded_pymol_widget, EmbeddedPymolAdapter
    from docking_universal.state import JsonStudyStore
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    def pump():
        for _ in range(8):
            app.processEvents(); time.sleep(.025)
    def camera_equal(a,b):
        return len(a)==len(b) and all(abs(x-y)<1e-5 for x,y in zip(a,b))
    def unexpected(*_, **__):
        raise ValueError('Unexpected dialog: no scientific decision or repair is authorized')
    window = coordinator = None
    try:
        store = JsonStudyStore(out/'studies')
        with patch.object(QtWidgets.QMessageBox,'exec',side_effect=unexpected), \
             patch.object(QtWidgets.QMessageBox,'warning',side_effect=unexpected), \
             patch.object(QtWidgets.QMessageBox,'critical',side_effect=unexpected):
            with ApplicationHostClient(store.root,args.runtime/'docking-universal-application-host.py',
                                       python_executable=args.scientific_python,timeout_seconds=30) as host:
                widget = create_embedded_pymol_widget(); adapter = EmbeddedPymolAdapter(widget)
                coordinator = StudyViewerCoordinator(adapter)
                settings = QtCore.QSettings(str(out/'window.ini'),QtCore.QSettings.Format.IniFormat)
                window = StudyWindow(store,'review',settings=settings,host_client=host,
                                     viewer_widget=widget,viewer_coordinator=coordinator)
                window.resize(1400,900);window.show();pump();window.refresh()
                check(window.screening_results.rowCount()==1,'Retained compound result is visible')
                window.screening_results.selectRow(0);pump()
                choice = window.interaction_diagram_choice
                check(choice.count()>=1,'Retained representative choices are available')
                for index in range(choice.count()):
                    record.update(phase='native-controls',representative=index+1);save()
                    choice.setCurrentIndex(index); window._show_selected_interaction_diagram();pump()
                    view = pose_view(Path(choice.currentData()))
                    check(view is not None and adapter.review_pose==view.ligand.resolve(),'Exact-pose link is verified')
                    diagram_hash = system.sha(view.diagram)
                    window.open_selected_interaction_diagram();pump()
                    pair = window._paired_interaction_window
                    check(pair is not None and pair.isVisible(),'Native paired review opens')
                    camera = adapter.cmd.get_view()
                    pair.cartoon.click();pump()
                    check(adapter.cmd.count_atoms('du_linked_receptor and rep cartoon')==0,'Cartoon can be hidden')
                    pair.cartoon.click();pump()
                    check(adapter.cmd.count_atoms('du_linked_receptor and rep cartoon')>0,'Cartoon can be restored')
                    pair.labels.setChecked(True);pump()
                    check(not pair._residues or adapter.has_review_residue_labels(),'Visible contact labels can be enabled')
                    pair.labels.setChecked(False);pump()
                    check(not adapter.has_review_residue_labels(),'Contact labels can be cleared')
                    for kind,action in pair.contact_type_actions.items():
                        original_types = dict(adapter._plip_types_visible)
                        pair.contact_key.linkActivated.emit(kind);pump()
                        check(adapter._plip_types_visible[kind] is False,'One legend type switches off')
                        check(all(adapter._plip_types_visible[k]==v for k,v in original_types.items() if k!=kind),
                              'Other interaction types remain unchanged')
                        pair.contact_key.linkActivated.emit(kind);pump()
                        check(adapter._plip_types_visible==original_types,'Individual legend type restores')
                    pair.contacts.click();pump()
                    check(adapter._plip_contacts_visible is False,'Master PLIP toggle switches off')
                    pair.contacts.click();pump()
                    check(adapter._plip_contacts_visible is True,'Master PLIP toggle restores')
                    for residue in pair._residues:
                        button = pair.residue_buttons[pair.key(residue)]
                        if not button.isEnabled():
                            raise ValueError('A recorded contact residue cannot be mapped')
                        key = adapter._obstruction_key([residue])
                        button.click();pump()
                        check(key not in adapter._contact_highlights,'One residue can be hidden')
                        button.click();pump()
                        check(key in adapter._contact_highlights,'One residue can be restored')
                    check(camera_equal(camera,adapter.cmd.get_view()),'Visibility toggles preserve camera')
                    pair.clicked_ligand();pump()
                    check(system.sha(view.diagram)==diagram_hash,'3D interactions never rewrite the 2D diagram')
                    check(not adapter.cmd.get_names('selections',enabled_only=1),'No atom-selection markers remain enabled')
                    if index==0:
                        for width,height in [(1280,800),(1500,950)]:
                            pair.resize(width,height);pump()
                            check(widget.width()>250 and widget.height()>200,'Resize preserves a usable native viewport')
                            pair.grab().save(str(out/f'paired-{width}.png'))
                        diagram_export(view).save(out/'diagram.png')
                        paired_export(view,widget,pair._export_contact_legend()).save(out/'panel.png')
                        pymol_export(widget,{'validation':True}).save(out/'pymol.png')
                        check(all((out/p).is_file() for p in ['diagram.png','panel.png','pymol.png']),
                              'Local clean 2D, 3D and paired image exports succeed')
                        if args.ray:
                            pymol_export(widget,{'validation':True},ray=True).save(out/'pymol-ray.png')
                            check((out/'pymol-ray.png').is_file(),'Optional native ray-traced export succeeds')
                    window._close_interaction_review();pump()
                check(not store.load('review').active_job,'Read-only review launches no scientific job')
                check(system.sha(destination)==before,'Native controls leave saved scientific state unchanged')
                window.close();coordinator.close();pump();window=coordinator=None
        system.verify_saved(row,source_run)
        record.update(status='passed',phase='completed',source_evidence_unchanged=True)
        save();return 0
    except BaseException as exc:
        record.update(status='failed',reason=str(exc));save();return 1
    finally:
        if window is not None:window.close()
        if coordinator is not None:coordinator.close()


if __name__=='__main__':
    raise SystemExit(main())
