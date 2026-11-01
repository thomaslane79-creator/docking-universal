"""One installed GUI process: reviewed protocol import -> screen -> view -> reopen.

This adapter tests protocol reuse, not raw-input preparation or control approval.
It cannot choose sites, change protocol settings or grant control validation.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import sys
import time
from unittest.mock import patch


def reviewed_columns(library, requested):
    """Require operator-specified columns; suggestions are never consent."""
    table = library.get('table') or {}
    columns = {row['index'] for row in table.get('columns', [])}
    if not requested or requested.get('smiles_column') not in columns:
        raise ValueError('Explicit valid SMILES-column approval is required for a table case')
    name = requested.get('name_column')
    if name is not None and name not in columns:
        raise ValueError('The reviewed name column does not exist')
    if requested.get('sheet',table.get('sheet')) != table.get('sheet'):
        raise ValueError('The reviewed worksheet is not loaded')
    return {'source_sha256':table['source_sha256'],'sheet':table.get('sheet'),
            'smiles_column':requested['smiles_column'],'name_column':name}


def selected_indices(library, requested=None):
    records = library['records']
    indices = list(range(len(records))) if requested is None else list(requested)
    if len(set(indices)) != len(indices) or not indices:
        raise ValueError('A nonempty unique selection is required')
    if any(not isinstance(i,int) or isinstance(i,bool) or i<0 or i>=len(records) for i in indices):
        raise ValueError('Selected record index is outside the library')
    if any(not records[i]['valid'] for i in indices):
        raise ValueError('Validation cannot select invalid chemistry')
    return indices


def planning_selection(case):
    """Read the exact operator-selected subset without granting GUI approval."""
    if 'selected_record_indices' not in case and 'column_mapping' not in case:
        return None
    from docking_universal.services.ligand_library import inspect_ligand_library
    source = case['inputs']['ligands']['path']
    requested = case.get('column_mapping')
    library = inspect_ligand_library(source, sheet=(requested or {}).get('sheet'))
    mapping = reviewed_columns(library, requested) if library.get('table') else None
    if mapping is not None:
        library = inspect_ligand_library(source, column_mapping=mapping)
    indices = selected_indices(library, case.get('selected_record_indices'))
    selection = {'fingerprint':library['fingerprint'],
                 'record_ids':[library['records'][i]['record_id'] for i in indices]}
    if mapping is not None:
        selection['column_mapping'] = mapping
    return selection


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--case', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--scientific-python', required=True)
    parser.add_argument('--cli', required=True)
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    case = json.loads(args.case.read_text())
    record = {'status': 'running', 'engine': case['engine'], 'phase': 'preflight', 'checks': [],
              'coverage': 'installed GUI protocol reuse; not new preparation/control calibration',
              'visual_review': 'pending', 'real_screening_started':False}
    def save():
        (out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')
    def check(value, text):
        if not value:
            raise ValueError(text)
        record['checks'].append(text)
    sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
    save()
    sys.path.insert(0, str(args.runtime.resolve()))
    prefix = Path(args.scientific_python).resolve().parent.parent
    os.environ.update(DOCKING_UNIVERSAL_LIBEXEC=str(args.runtime.resolve()),
                      DOCKING_UNIVERSAL_CLI=args.cli, DOCKING_UNIVERSAL_PYTHON=args.scientific_python)
    os.environ['PATH'] = str(prefix.parent.parent / 'bin') + os.pathsep + str(prefix / 'bin') + os.pathsep + os.environ.get('PATH', '')
    descriptor = prefix / 'share/docking-universal/adgpu/runtime.json'
    if descriptor.is_file():
        os.environ.setdefault('DOCKING_UNIVERSAL_ADGPU_CONFIG', str(descriptor))
    app = window = coordinator = host = None
    def interrupted(*_):
        raise KeyboardInterrupt('Validation worker interrupted; cancelling its own active job')
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if not case.get('import_review_approved'):
            raise ValueError('Protocol import was not explicitly reviewed')
        for item in case['inputs'].values():
            check(sha(item['path']) == item['sha256'], 'Pinned source hash verified')
        if sys.platform == 'win32':
            from docking_universal.windows_viewer_runtime import activate_installed_viewer
            activate_installed_viewer(args.runtime)
        from docking_universal.gui.qt import QtCore, QtWidgets
        from docking_universal.gui.desktop import StudyWindow
        from docking_universal.gui.host_client import ApplicationHostClient
        from docking_universal.gui.study_viewer import StudyViewerCoordinator
        from docking_universal.viewer.embedded_pymol import create_embedded_pymol_widget, EmbeddedPymolAdapter
        from docking_universal.state import JsonStudyStore
        from docking_universal.gui.linked_pose_review import pose_view
        from docking_universal.services.protocol_import import inspect_protocol_bundle
        from docking_universal.ad4_gpu import available
        protocol = case['inputs']['protocol']['path']
        ligands = case['inputs']['ligands']['path']
        preview = inspect_protocol_bundle(protocol)
        check(preview['engine'] == case['engine'], 'Reviewed bundle matches requested engine')
        check(str(preview['target']).upper() == str(case['target']).upper(), 'Reviewed bundle matches requested target')
        if case['engine'] == 'adgpu' and not available():
            record.update(status='blocked', reason='Accepted experimental AD4 runtime is not available on this machine')
            return 3
        app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        app.setQuitOnLastWindowClosed(False)
        settings = QtCore.QSettings(str(out / 'window.ini'), QtCore.QSettings.Format.IniFormat)
        store = JsonStudyStore(out / 'studies')
        study = 'validation'
        def pump(seconds=.15):
            end = time.monotonic() + seconds
            while time.monotonic() < end:
                app.processEvents(); time.sleep(.02)
        notices = []
        def notification(*values, **_):
            notices.append([str(v) for v in values[1:]])
            return QtWidgets.QMessageBox.StandardButton.Ok
        def decision(*_, **__):
            raise ValueError('Unexpected scientific/modal decision requires human review')
        options = dict(python_executable=args.scientific_python, timeout_seconds=30)
        with patch.object(QtWidgets.QMessageBox, 'information', side_effect=notification), \
             patch.object(QtWidgets.QMessageBox, 'warning', side_effect=notification), \
             patch.object(QtWidgets.QMessageBox, 'critical', side_effect=notification), \
             patch.object(QtWidgets.QMessageBox, 'exec', side_effect=decision):
            with ApplicationHostClient(store.root, args.runtime / 'docking-universal-application-host.py', **options) as host:
                host.request(study, 'create_study', {'name': 'Isolated system validation: ' + case['id']})
                widget = create_embedded_pymol_widget()
                adapter = EmbeddedPymolAdapter(widget)
                coordinator = StudyViewerCoordinator(adapter)
                window = StudyWindow(store, study, settings=settings, host_client=host,
                                     viewer_widget=widget, viewer_coordinator=coordinator)
                window.resize(1400, 900); window.show(); pump(.3)
                try:
                    # Explicitly pinned/reviewed bundle is imported through the
                    # ordinary GUI controller. This does not simulate review of
                    # a new receptor/site or bypass a scientific decision.
                    window.host_controller.import_protocol_bundle(protocol, preview['sha256'], store.load(study).revision)
                    window.refresh()
                    window.screen_ligands.setText(ligands)
                    window.screen_output.setText(str(out / 'screen'))
                    window.read_screening_library()
                    library = window.screening_setup_panel.library_panel
                    start = time.monotonic()
                    while library.loading and time.monotonic() - start < 120:
                        pump()
                    check(bool(library.library), 'Local ligand reader completed')
                    if library.library.get('table'):
                        requested=case.get('column_mapping') or {}
                        sheet=requested.get('sheet')
                        if sheet is not None and library.sheet_combo.currentText()!=sheet:
                            library.sheet_combo.setCurrentText(sheet)
                            start=time.monotonic()
                            while library.loading and time.monotonic()-start<120:pump()
                        mapping=reviewed_columns(library.library,requested)
                        check(not library.library.get('mapping_approved'),'Table headers alone do not approve molecules')
                        library.smiles_column.setCurrentIndex(library.smiles_column.findData(mapping['smiles_column']))
                        library.name_column.setCurrentIndex(library.name_column.findData(mapping['name_column']))
                        library.approve_columns.click()
                        start=time.monotonic()
                        while library.loading and time.monotonic()-start<120:pump()
                        check(library.library.get('mapping_approved'),'Explicit GUI column approval loads the table chemistry')
                        check(library.library.get('column_mapping')==mapping,'Approved GUI mapping exactly matches the case')
                    indices=selected_indices(library.library,case.get('selected_record_indices'))
                    if case.get('expected_source_name'):
                        check(len(indices)==1 and library.library['records'][indices[0]]['name']==case['expected_source_name'],
                              'The intended named input compound is selected')
                    library.set_all(False)
                    page_size=library.page_size.currentData()
                    for index in indices:
                        library.set_page(index//page_size)
                        library.table.item(index%page_size,0).setCheckState(QtCore.Qt.CheckState.Checked)
                    window.preview_screening()
                    plan = window._screening_plan
                    check(bool(plan), 'GUI workload preview accepted')
                    check(plan['engine'] == case['engine'], 'GUI preview retains engine identity')
                    check(plan['compound_count'] == len(indices), 'Workload contains exactly the explicitly selected compounds')
                    record['workload'] = plan
                    if plan['total_docking_jobs'] > case.get('max_jobs', 50):
                        record.update(status='blocked', reason='Workload exceeds the explicitly configured per-case job budget')
                        return 3
                    if plan['exploratory_authorization_required'] and not case.get('exploratory_authorized'):
                        record.update(status='blocked', reason='Exploratory screening authorization not supplied')
                        return 3
                    window.screen_exploratory_approval.setChecked(bool(case.get('exploratory_authorized')))
                    window.start_screening()
                    check(any(j.stage == 'screening' for j in store.load(study).jobs), 'Real GUI screening job launched')
                    record['real_screening_started']=True
                    record['phase'] = 'screening'; save()
                    while True:
                        pump()
                        current = store.load(study)
                        job = current.jobs[-1]
                        if job.status.value in {'failed', 'cancelled', 'interrupted'}:
                            raise ValueError('Scientific job did not complete: ' + str(job.error or job.status.value))
                        if not current.active_job and current.workflow_data.get('latest_screening_status') == 'completed':
                            break
                    window.refresh()
                    check(window.screening_results.rowCount() == plan['compound_count'], 'All requested compounds appear in completed results')
                    record['phase'] = 'native_review'; save()
                    representatives = 0
                    for row in range(window.screening_results.rowCount()):
                        check(math.isfinite(float(window.screening_results.item(row, 4).text())), 'Retained GUI energy is finite')
                        check(window.screening_results.item(row, 5).text() == ('AD4' if case['engine'] == 'adgpu' else 'Vina'), 'GUI scoring model is correct')
                        window.screening_results.selectRow(row); pump(.2)
                        choice = window.interaction_diagram_choice
                        check(choice.count() > 0, 'Cluster interaction choices retained')
                        for index in range(choice.count()):
                            choice.setCurrentIndex(index); window._show_selected_interaction_diagram(); pump(.1)
                            view = pose_view(Path(choice.currentData()))
                            check(view is not None and adapter.review_pose == view.ligand.resolve(), 'Exact retained representative displayed in native PyMOL')
                            check(view.interactions.is_file(), 'Representative retains its own PLIP evidence')
                            representatives += 1
                        window.open_selected_interaction_diagram(); pump(.2)
                        check(window._paired_interaction_window is not None, 'Paired 2D/3D review opens')
                        window._paired_interaction_window.grab().save(str(out / f'compound-{row+1}-review.png'))
                        window._close_interaction_review()
                    reports = [Path(a.path) for a in current.artifacts if a.kind == 'screening_report']
                    check(bool(reports) and all(p.read_bytes().startswith(b'%PDF-') for p in reports), 'Screening PDF generated')
                    record.update(reports=list(map(str, reports)), reviewed_representatives=representatives)
                    check(bool(list((out/'screen').rglob('*scores.csv'))),'Actual docking score files are retained')
                    completed_hash = sha(store.path_for(study))
                finally:
                    active = store.load(study).active_job
                    if active:
                        window.host_controller.cancel_active_job(store.load(study).revision, active.id)
                        end = time.monotonic() + 30
                        while store.load(study).active_job and time.monotonic() < end:
                            pump()
                        record['active_job_after_cleanup'] = bool(store.load(study).active_job)
                    window.close(); coordinator.close(); pump()
                    window = coordinator = None
            with ApplicationHostClient(store.root, args.runtime / 'docking-universal-application-host.py', **options) as host:
                window = StudyWindow(store, study, settings=settings, host_client=host)
                window.show(); pump(.3); window.refresh()
                check(window.screening_results.rowCount() == plan['compound_count'], 'Fresh-host reopen preserves result count')
                check(sha(store.path_for(study)) == completed_hash, 'Reopen preserves saved scientific state')
                window.close(); window = None
        check(all(sha(v['path']) == v['sha256'] for v in case['inputs'].values()), 'Original reviewed inputs remain unchanged')
        record.update(status='passed', phase='completed', notifications=notices)
        return 0
    except BaseException as exc:
        record.update(status='failed', reason=str(exc))
        return 1
    finally:
        if window is not None:
            window.close()
        if coordinator is not None:
            coordinator.close()
        save()


if __name__ == '__main__':
    raise SystemExit(main())
