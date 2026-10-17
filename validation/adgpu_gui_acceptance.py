#!/usr/bin/env python3
"""Real GUI/host acceptance after retained preparation; never edits the source study."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.state import JsonStudyStore, StudyState

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-state', type=Path, required=True)
    parser.add_argument('--resume-after-launch-rejection', action='store_true', help='Reuse a completed protocol after a pre-search GUI launch rejection, never rerun docking')
    parser.add_argument('--screen-name', default='screen')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=args.resume_after_launch_rejection)
    original = sha(args.source_state)
    record = {'status': 'running', 'phase': 'fixture', 'source_state': str(args.source_state),
              'source_state_sha256': original, 'production_installed': False}
    def save():
        (out/'summary.json').write_text(json.dumps(record, indent=2)+'\n')
    if args.resume_after_launch_rejection:
        prior = json.loads((out/'summary.json').read_text())
        if prior.get('status')!='failed' or (out/args.screen_name).exists():
            raise ValueError('Resume requires a new screening folder after the explicitly inspected pre-search rejection')
        if list(out.glob('screen*/compounds/*/seed_*/docking/*_adgpu.pdbqt')):
            raise ValueError('This preflight repair must not repeat existing docking')
        failure = out/f'acceptance-attempt-{len(list(out.glob("acceptance-attempt-*.json")))+1}.json'
        failure.write_text(json.dumps(prior, indent=2)+'\n')
        record['prior_failure'] = str(failure)
    save()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    os.environ['DOCKING_UNIVERSAL_CLI'] = str(ROOT/'bin/docking-universal')
    os.environ['DOCKING_UNIVERSAL_LIBEXEC'] = str(ROOT/'libexec')
    state_root = out/'state'
    study_id = 'ad4-gui-acceptance'
    store = JsonStudyStore(state_root)
    data = json.loads(args.source_state.read_text())
    data.update(study_id=study_id, name='AD4 isolated GUI acceptance', completion_status='draft', current_stage=None)
    data['jobs'] = [j for j in data['jobs'] if j['stage'] in ('preparation_and_pocket_detection', 'pocket_review')]
    data['artifacts'] = [a for a in data['artifacts'] if a['kind'] not in (
        'protocol_bundle', 'final_report', 'final_protocol', 'final_report_figure')
        and not a['kind'].startswith(('screening_', 'pose_interaction'))]
    for key in ('latest_screening_output', 'latest_screening_status', 'next_stage'):
        data['workflow_data'].pop(key, None)
    data['workflow_data']['completed_stages'] = ['preparation_and_pocket_detection', 'pocket_review', 'region_approval']
    data['workflow_data']['validation_source'] = {'path': str(args.source_state), 'sha256': original,
        'scope': 'Retained preparation and pocket approval reused only in an isolated validation copy'}
    state = store.load(study_id) if args.resume_after_launch_rejection else store.create(StudyState.from_dict(data))
    config = json.loads((ROOT/'validation/runs/autodock-gpu-mac-20261016/full-screen-20261016/source-config.json').read_text())
    # Preserve the two exact compound records, including their library identifiers.
    ligand = out/'two-compounds.sdf'
    ligand.write_bytes(b''.join(Path(c['input']).read_bytes() for c in config['compounds']))
    record['ligand_sha256'] = sha(ligand)
    settings = QtCore.QSettings(str(out/'window.ini'), QtCore.QSettings.Format.IniFormat)
    messages = []
    def message(*values, **kwargs):
        messages.append([str(v) for v in values[1:]])
        return QtWidgets.QMessageBox.StandardButton.Ok
    with patch.object(QtWidgets.QMessageBox, 'information', side_effect=message), \
         patch.object(QtWidgets.QMessageBox, 'warning', side_effect=message), \
         patch.object(QtWidgets.QMessageBox, 'critical', side_effect=message):
        try:
            with ApplicationHostClient(state_root, ROOT/'libexec/docking-universal-application-host.py',
                    python_executable='/opt/anaconda3/envs/docking-universal/bin/python', timeout_seconds=30) as host:
                window = StudyWindow(store, study_id, settings=settings, host_client=host)
                window.show()
                def wait(predicate, phase):
                    record['phase'] = phase; save()
                    deadline = time.monotonic()+900
                    while time.monotonic()<deadline:
                        app.processEvents(); window.refresh()
                        current = store.load(study_id)
                        if predicate(current):
                            window.refresh()
                            return current
                        if current.jobs and current.jobs[-1].status.value in ('failed', 'cancelled'):
                            raise RuntimeError(f'{phase}: {current.jobs[-1].error}')
                        time.sleep(.15)
                    raise TimeoutError(phase)
                index = window.protocol_engine.findData('adgpu')
                if index<0: raise ValueError('Configured experimental engine absent from GUI')
                window.protocol_engine.setCurrentIndex(index)
                window.protocol_conformers.setValue(1)
                window.protocol_seeds.setValue(1)
                window.protocol_base_seed.setValue(41001)
                window.final_output_directory.setText(str(out/'protocol'))
                window.exploratory_approval.setChecked(True)
                if not args.resume_after_launch_rejection:
                    window.start_protocol_finalization()
                state = wait(lambda s: any(a.kind=='protocol_bundle' for a in s.artifacts) and not s.active_job, 'finalization')
                record.update(protocol_bundle=next(a.path for a in state.artifacts if a.kind=='protocol_bundle'),
                              protocol_report=next(a.path for a in state.artifacts if a.kind=='final_report'))
                window.screen_ligands.setText(str(ligand))
                window.screen_output.setText(str(out/args.screen_name))
                window.preview_screening()
                if not window._screening_plan: raise ValueError('GUI screening preview rejected: '+str(messages))
                record['screening_plan'] = window._screening_plan
                if window.screening_setup_panel.cpu.isEnabled(): raise ValueError('GPU preview still offers CPU tuning')
                window.screen_exploratory_approval.setChecked(True)
                window.start_screening()
                if not any(j.stage=='screening' for j in store.load(study_id).jobs):
                    raise ValueError('GUI did not launch screening: '+str(messages))
                state = wait(lambda s: s.workflow_data.get('latest_screening_status')=='completed' and not s.active_job, 'screening')
                record['screening_report'] = next(a.path for a in state.artifacts if a.kind=='screening_report')
                record['finished_state_sha256'] = sha(store.path_for(study_id))
                window.grab().save(str(out/'completed-gui.png'))
                window.close(); app.processEvents()
            # Reopen with a fresh host rather than relying on in-memory objects.
            record['phase'] = 'reopen'; save()
            with ApplicationHostClient(state_root, ROOT/'libexec/docking-universal-application-host.py',
                    python_executable='/opt/anaconda3/envs/docking-universal/bin/python', timeout_seconds=30) as host:
                window = StudyWindow(store, study_id, settings=settings, host_client=host)
                window.show(); app.processEvents(); window.refresh()
                reopened = store.load(study_id)
                if reopened.active_job or reopened.workflow_data.get('latest_screening_status')!='completed':
                    raise ValueError('Completed screening did not reopen correctly')
                record['reopened_artifacts'] = [{'kind': a.kind, 'path': a.path, 'sha256': a.sha256}
                    for a in reopened.artifacts if a.kind.startswith('screening_')]
                window.grab().save(str(out/'reopened-gui.png'))
                window.close(); app.processEvents()
            if sha(args.source_state)!=original: raise ValueError('Original user study changed')
            record.update(status='completed_gui_acceptance', phase='completed', source_state_unchanged=True)
        except BaseException as exc:
            record.update(status='failed', error=str(exc)); raise
        finally:
            record['messages'] = messages; save()
    print(json.dumps(record, indent=2))


if __name__=='__main__': main()
