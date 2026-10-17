"""Backed-up installation and installed-host smoke check; no scientific searches."""
import json
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess

from autodock_gpu_trial import ROOT, check_idle, digest

OUT = ROOT / 'validation/runs/protocol-reuse-20261017_b'
DESTINATION = Path('/opt/anaconda3/envs/docking-universal/libexec/docking-universal')
FILES = ('docking_universal/services/protocol_import.py', 'docking_universal/host.py',
         'docking_universal/gui/application_host_controller.py', 'docking_universal/gui/host_client.py',
         'docking_universal/gui/workflow_panels.py', 'docking_universal/gui/desktop.py',
         'docking-universal-pdf-report.py')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--attempt', type=int, default=1)
    attempt = parser.parse_args().attempt
    qa = json.loads((OUT / 'summary.json').read_text())
    native = json.loads((OUT / 'native-review/verification.json').read_text())
    assert qa['status'] == native['status'] == 'passed'
    suites = {}
    for name in ('gui', 'report'):
        log = (OUT / (name + '-regressions.log')).read_text()
        assert re.search(r'\nOK\s*$', log)
        suites[name] = int(re.search(r'Ran (\d+) tests', log)[1])
    check_idle()
    assert digest(qa['original_study']) == qa['original_study_sha256']
    assert digest(qa['source_bundle']) == qa['source_bundle_sha256']
    assert not json.loads((OUT / 'state/reuse-check/application_state.json').read_text())['completion_status'] == 'running'
    backup = OUT / f'installation-backup-{attempt}'
    backup.mkdir(exist_ok=False)
    record = {'status': 'installing', 'files': [], 'regressions': suites,
              'native_checks': len(native['checks']), 'workflow_checks': len(qa['checks']),
              'scientific_searches_during_installation': 0}

    def publish(source, target):
        temporary = target.with_name(target.name + '.protocol-reuse-new')
        shutil.copy2(source, temporary)
        temporary.replace(target)

    try:
        for relative in FILES:
            source, target = ROOT / 'libexec' / relative, DESTINATION / relative
            existed = target.is_file()
            before = digest(target) if existed else None
            saved = backup / relative
            if existed:
                saved.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, saved)
                assert digest(target) == before
            record['files'].append({'relative': relative, 'previous_sha256': before,
                                     'sha256': digest(source)})
            publish(source, target)
            assert digest(target) == digest(source)
        env = {**os.environ, 'PYTHONPATH': str(DESTINATION), 'QT_QPA_PLATFORM': 'offscreen'}
        code = '''
import json, sys
from pathlib import Path
from unittest.mock import patch
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.gui.workflow_panels import ProtocolImportDialog
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.state import JsonStudyStore
from docking_universal.services.protocol_import import inspect_protocol_bundle
out, installed = Path(sys.argv[1]), Path(sys.argv[2])
qa = json.loads((out/'summary.json').read_text())
app = QtWidgets.QApplication([])
options = dict(python_executable='/opt/anaconda3/envs/docking-universal/bin/python', timeout_seconds=30)
store = JsonStudyStore(out/('installed-smoke-state-' + sys.argv[3]))
settings = QtCore.QSettings(str(out/'installed-window.ini'), QtCore.QSettings.Format.IniFormat)
with ApplicationHostClient(store.root, installed/'docking-universal-application-host.py', **options) as host:
    host.request('installed-reuse', 'create_study', {'name':'Installed protocol import check'})
    window = StudyWindow(store, 'installed-reuse', host_client=host, settings=settings)
    panel = window.study_setup_panel
    panel.pathway.setCurrentIndex(panel.pathway.findData('reuse'))
    panel.protocol_bundle.setText(qa['snapshot'])
    with patch.object(ProtocolImportDialog, 'exec', return_value=QtWidgets.QDialog.DialogCode.Accepted):
        panel.prepare_button.click()
    state = store.load('installed-reuse')
    assert state.workflow_data['protocol_import']['sha256'] == qa['source_bundle_sha256']
    assert not state.jobs and not state.decisions
    assert not window.screen_exploratory_approval.isChecked()
    plan = window.host_controller.screening_plan(str(out/'three-record-library.sdf'), qa['selection'])
    assert plan['compound_count'] == 2 and plan['engine'] == 'vina'
    assert plan['parameters'] == qa['screening_plan']['parameters']
    assert panel.review_protocol_button.isEnabled()
    window.close()
store = JsonStudyStore(out/'state')
before = store.path_for('reuse-check').read_bytes()
with ApplicationHostClient(store.root, installed/'docking-universal-application-host.py', **options) as host:
    window = StudyWindow(store, 'reuse-check', host_client=host, settings=settings)
    window.refresh()
    assert window.screening_results.rowCount() == 2
    assert window.study_pathway.currentData() == 'reuse'
    assert store.path_for('reuse-check').read_bytes() == before
    window.close()
print('Installed GUI import, locked preview and completed-results reopening passed; no docking')
'''
        smoke = subprocess.run(['/opt/anaconda3/envs/docking-universal-gui-next/bin/python', '-c', code,
                                str(OUT), str(DESTINATION), str(attempt)], env=env, text=True, capture_output=True,
                               check=True, timeout=60)
        record['smoke_check'] = smoke.stdout.strip()
        assert digest(qa['original_study']) == qa['original_study_sha256']
        record.update(status='installed', original_study_unchanged=True)
    except BaseException as exc:
        if isinstance(exc, subprocess.CalledProcessError):
            record['smoke_stderr'] = exc.stderr
        for row in reversed(record['files']):
            target = DESTINATION / row['relative']
            if row['previous_sha256']:
                publish(backup / row['relative'], target)
            elif target.is_file():
                target.unlink()
        record.update(status='failed', error=str(exc), previous_installation_restored=True)
        raise
    finally:
        (OUT / f'installation-{attempt}.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps(record, indent=2))


if __name__ == '__main__':
    main()
