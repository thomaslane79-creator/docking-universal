"""Isolated fresh-study GUI import -> selection -> real screen -> fresh-host reopen.

Never prepares a receptor, edits the original study, or changes saved search settings.
An existing output directory is refused to prevent accidental duplicate searches.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import shutil
import time
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from rdkit import Chem
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.gui.workflow_panels import ProtocolImportDialog
from docking_universal.services.protocol_import import inspect_protocol_bundle
from docking_universal.services.screening import read_protocol_record
from docking_universal.state import JsonStudyStore

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'validation/runs/report-target-identity-20261014.iUnTOs/retained-copy/2R8N_site-guided-exploratory_vina.duprotocol'
USER_STATE = Path('/Users/crown2/Library/Application Support/Docking Universal/studies/2R8N-Example-2/application_state.json')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'validation/runs/protocol-reuse-20261017')
    args = parser.parse_args()
    OUT = args.out.resolve()
    OUT.mkdir(parents=True, exist_ok=False)
    record = {'status': 'running', 'phase': 'import', 'checks': [], 'source_bundle': str(SOURCE),
              'source_bundle_sha256': sha(SOURCE), 'original_study': str(USER_STATE),
              'original_study_sha256': sha(USER_STATE), 'scientific_preparation_runs': 0}
    def save():
        (OUT / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')
    def check(name, value):
        record['checks'].append({'name': name, 'passed': bool(value)})
        save()
        if not value:
            raise AssertionError(name)
    save()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    os.environ['DOCKING_UNIVERSAL_CLI'] = str(ROOT / 'bin/docking-universal')
    os.environ['DOCKING_UNIVERSAL_LIBEXEC'] = str(ROOT / 'libexec')
    source = OUT / 'relocated-input.duprotocol'
    shutil.copy2(SOURCE, source)
    library = OUT / 'three-record-library.sdf'
    molecules = [m for m in Chem.SDMolSupplier(str(ROOT / 'examples/test_inputs/two_compounds.sdf')) if m is not None]
    if len(molecules) != 2:
        raise ValueError('Expected two valid retained example records')
    with Chem.SDWriter(str(library)) as writer:
        for name, molecule in zip(('Selected-small', 'Selected-rilpivirine', 'Unselected-duplicate'),
                                   (molecules[0], molecules[1], Chem.Mol(molecules[0]))):
            molecule.SetProp('_Name', name)
            writer.write(molecule)
    store = JsonStudyStore(OUT / 'state')
    settings = QtCore.QSettings(str(OUT / 'window.ini'), QtCore.QSettings.Format.IniFormat)
    messages = []
    def message(*args, **kwargs):
        messages.append([str(v) for v in args[1:]])
        return QtWidgets.QMessageBox.StandardButton.Ok
    host_options = dict(python_executable='/opt/anaconda3/envs/docking-universal/bin/python', timeout_seconds=30)
    try:
        with patch.object(QtWidgets.QMessageBox, 'warning', side_effect=message), \
             patch.object(QtWidgets.QMessageBox, 'critical', side_effect=message), \
             patch.object(QtWidgets.QMessageBox, 'information', side_effect=message):
            with ApplicationHostClient(store.root, ROOT / 'libexec/docking-universal-application-host.py', **host_options) as host:
                host.request('reuse-check', 'create_study', {'name': 'Saved protocol reuse validation'})
                window = StudyWindow(store, 'reuse-check', host_client=host, settings=settings)
                window.resize(1400, 900)
                window.show()
                panel = window.study_setup_panel
                panel.pathway.setCurrentIndex(panel.pathway.findData('reuse'))
                panel.protocol_bundle.setText(str(source))
                def accept_review(dialog):
                    dialog.grab().save(str(OUT / 'import-review.png'))
                    QtCore.QTimer.singleShot(0, dialog.accept)
                    return QtWidgets.QDialog.exec(dialog)
                with patch.object(ProtocolImportDialog, 'exec', accept_review):
                    panel.prepare_button.click()
                state = store.load('reuse-check')
                check('fresh study imports via GUI host action', bool(state.workflow_data.get('protocol_import')))
                snapshot = Path(state.artifacts[0].path)
                record['snapshot'] = str(snapshot)
                check('no preparation or fabricated region decision', not state.jobs and not state.decisions and not state.selected_pocket_ids)
                check('import remains exploratory', state.scientific_authority.value == 'exploratory_no_control')
                check('snapshot matches source bundle', sha(snapshot) == record['source_bundle_sha256'])
                source.rename(OUT / 'source-unavailable.duprotocol')
                check('original source location no longer exists', not source.exists())
                window.screen_ligands.setText(str(library))
                window.screen_output.setText(str(OUT / 'screen'))
                window.read_screening_library()
                library_panel = window.screening_setup_panel.library_panel
                deadline = time.monotonic() + 120
                while library_panel.loading and time.monotonic() < deadline:
                    app.processEvents()
                    time.sleep(.05)
                check('embedded reader indexes three records', bool(library_panel.library) and len(library_panel.library['records']) == 3)
                for row in (0, 1):
                    library_panel.table.item(row, 0).setCheckState(QtCore.Qt.CheckState.Checked)
                check('two checked records only', len(library_panel.selection()['record_ids']) == 2)
                record['selection'] = library_panel.selection()
                window.preview_screening()
                plan = window._screening_plan
                check('screening preview accepts relocated imported snapshot', bool(plan))
                check('preview excludes unselected compound', plan['compound_count'] == 2)
                original = inspect_protocol_bundle(SOURCE)
                check('full locked settings retained', plan['parameters'] == original['parameters'])
                check('exploratory approval remains explicit', not window.screen_exploratory_approval.isChecked())
                record['screening_plan'] = plan
                window.screen_exploratory_approval.setChecked(True)
                window.start_screening()
                check('one scientific job launched', len(store.load('reuse-check').jobs) == 1)
                record.update(phase='screening', started_monotonic=time.monotonic())
                save()
                while True:
                    app.processEvents()
                    state = store.load('reuse-check')
                    if state.jobs[-1].status.value in ('failed', 'cancelled', 'interrupted'):
                        raise RuntimeError(state.jobs[-1].error or state.jobs[-1].status.value)
                    if not state.active_job and state.workflow_data.get('latest_screening_status') == 'completed':
                        break
                    time.sleep(.2)
                record['screening_wall_seconds'] = time.monotonic() - record.pop('started_monotonic')
                window.refresh()
                check('only screening was performed', len(state.jobs) == 1 and state.jobs[0].stage == 'screening')
                compound_dirs = list((OUT / 'screen/compounds').iterdir())
                record['screened_compounds'] = [p.name for p in compound_dirs]
                check('exactly selected compounds screened', len(compound_dirs) == 2 and not any('Unselected' in p.name for p in compound_dirs))
                record['report'] = next(a.path for a in state.artifacts if a.kind == 'screening_report')
                record['compound_reports'] = [str(p) for p in sorted((OUT / 'screen/compounds').glob('*/pose_analysis/*report.pdf'))]
                check('source snapshot unchanged after screen', sha(snapshot) == record['source_bundle_sha256'])
                record['completed_state_sha256'] = sha(store.path_for('reuse-check'))
                window.grab().save(str(OUT / 'completed-gui.png'))
                window.close()
                app.processEvents()
            record['phase'] = 'reopening'
            save()
            with ApplicationHostClient(store.root, ROOT / 'libexec/docking-universal-application-host.py', **host_options) as host:
                window = StudyWindow(store, 'reuse-check', host_client=host, settings=settings)
                window.show()
                app.processEvents()
                window.refresh()
                state = store.load('reuse-check')
                check('fresh-host reopen preserves completed study', not state.active_job and state.workflow_data.get('latest_screening_status') == 'completed')
                check('reopen does not mutate scientific state', sha(store.path_for('reuse-check')) == record['completed_state_sha256'])
                check('reopen retains imported pathway', window.study_pathway.currentData() == 'reuse')
                check('reopen restores two result rows', window.screening_results.rowCount() == 2)
                check('reopen retains screening duration', bool(window.screening_setup_panel.elapsed.text()))
                check('reopen retains locked bundle identity', sha(snapshot) == record['source_bundle_sha256'])
                window.screening_results.selectRow(0)
                app.processEvents()
                check('retained cluster interaction choices available', window.interaction_diagram_choice.count() > 0)
                window.grab().save(str(OUT / 'reopened-gui.png'))
                window.close()
                app.processEvents()
            check('original study untouched', sha(USER_STATE) == record['original_study_sha256'])
            check('original bundle untouched', sha(SOURCE) == record['source_bundle_sha256'])
            record.update(status='passed', phase='completed')
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
        raise
    finally:
        record['messages'] = messages
        save()
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
