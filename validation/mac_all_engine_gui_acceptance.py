"""Fresh installed-Mac GUI/host docking checks, sequential and isolated.

Reuse reviewed preparation, never user results. This is a two-compound functional
smoke test, not control calibration, engine equivalence or a release accuracy test.
No scientific service or viewer is mocked. Modal notifications are recorded;
unexpected scientific decisions stop the case instead of being accepted.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time
from unittest.mock import patch


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume-completed-vina-review', action='store_true',
                        help='Resume only the inspected post-docking energy-column check; never rerun completed Vina')
    parser.add_argument('--engine', choices=('vina', 'qvinaw', 'adgpu'), required=True,
                        help='One native PyMOL/application process per engine')
    parser.add_argument('--continue-unstarted-engine', action='store_true',
                        help='Start a not-yet-run engine after previous completed case or inspected viewer initialization failure')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=args.resume_completed_vina_review or args.continue_unstarted_engine)
    project = Path(__file__).resolve().parents[1]
    prefix = Path('/opt/anaconda3/envs/docking-universal')
    runtime = prefix / 'libexec/docking-universal'
    # The desktop normally inherits Conda's base bin from its public launcher.
    # Engine-isolation helpers still resolve `conda` there, not in scientific/bin.
    os.environ['PATH'] = str(prefix.parent.parent / 'bin') + os.pathsep + os.environ.get('PATH', '')
    source = Path.home() / 'Library/Application Support/Docking Universal/studies/2R8N-Example-2/application_state.json'
    # Match the ordinary launcher rather than using a validation descriptor.
    owned_descriptor = prefix / 'share/docking-universal/adgpu/runtime.json'
    if owned_descriptor.is_file():
        os.environ.setdefault('DOCKING_UNIVERSAL_ADGPU_CONFIG', str(owned_descriptor))
    os.environ.update(DOCKING_UNIVERSAL_CLI=str(prefix / 'bin/docking-universal'),
                      DOCKING_UNIVERSAL_LIBEXEC=str(runtime),
                      DOCKING_UNIVERSAL_PYTHON=str(prefix / 'bin/python'))
    sys.path.insert(0, str(runtime))
    from docking_universal.gui.desktop import StudyWindow
    from docking_universal.gui.host_client import ApplicationHostClient
    from docking_universal.gui.qt import QtCore, QtWidgets
    from docking_universal.gui.study_viewer import StudyViewerCoordinator
    from docking_universal.gui.linked_pose_review import pose_view
    from docking_universal.services.protocol_import import inspect_protocol_bundle
    from docking_universal.state import JsonStudyStore, StudyState
    from docking_universal.viewer.embedded_pymol import EmbeddedPymolAdapter, create_embedded_pymol_widget
    import docking_universal.gui.desktop as desktop
    assert Path(desktop.__file__).resolve().parent.parent.parent == runtime
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setApplicationName('Docking Universal — isolated engine checks')
    app.setQuitOnLastWindowClosed(False)
    before = {str(p): digest(p) for p in source.parent.parent.glob('*/application_state.json')}
    for path in before:
        state = json.loads(Path(path).read_text())
        if any(j['status'] in ('queued', 'running') for j in state.get('jobs', [])):
            raise RuntimeError('A user study already has an active job; no test launched')
    original = json.loads(source.read_text())
    if original.get('pending_decisions'):
        raise RuntimeError('Reference study has an unresolved decision')
    record = dict(status='running', pid=os.getpid(), started_utc=datetime.now(timezone.utc).isoformat(),
                  runtime=str(runtime), gui_python=sys.executable, source_state=str(source),
                  source_sha256=digest(source), scope='Fresh protocol → docking → clusters → PLIP/2D → PDF → native 3D → reopen',
                  retained_preparation=True, conformers_per_state=1, seeds=1,
                  accuracy_comparison=False, cases=[], messages=[])
    if args.resume_completed_vina_review:
        previous = json.loads((out / 'summary.json').read_text())
        if previous.get('status') != 'failed' or previous.get('error') != 'Both compounds have finite retained energies':
            raise ValueError('Continuation is limited to the inspected post-docking GUI reader failure')
        if len(previous['cases']) != 1 or previous['cases'][0]['engine'] != 'vina':
            raise ValueError('Unexpected previous case inventory')
        retained = JsonStudyStore(out / 'vina/state').load('mac-vina-functional')
        if retained.active_job or retained.workflow_data.get('latest_screening_status') != 'completed':
            raise ValueError('Vina must already be fully completed before read-only review continuation')
        (out / 'failed-reader-review.json').write_text(json.dumps(previous, indent=2) + '\n')
        record = previous
        record.update(status='running', pid=os.getpid(), continuation='Retained completed Vina protocol/docking/report; corrected GUI reader only, no repeated Vina search or preparation')
        record.pop('error', None)
        record['cases'][0].pop('error', None)
        record['cases'][0]['status'] = 'running'
    if args.continue_unstarted_engine:
        if not args.engine:
            raise ValueError('Continuation requires one explicit engine')
        previous = json.loads((out / 'summary.json').read_text())
        if previous['status'] == 'failed':
            if previous.get('error') != 'Singleton already exists':
                raise ValueError('Only the inspected pre-search PyMOL singleton failure permits this continuation')
            failed = next(c for c in previous['cases'] if c['status'] == 'failed')
            if failed['engine'] != args.engine:
                raise ValueError('Continuation engine differs from failed startup')
            old_root = out / args.engine
            retained = JsonStudyStore(old_root / 'state').load('mac-' + args.engine + '-functional')
            if any(j.stage not in ('preparation_and_pocket_detection', 'pocket_review') for j in retained.jobs):
                raise ValueError('Engine already has new scientific work; do not repeat it')
            shutil.move(str(old_root), str(out / (args.engine + '-viewer-startup-failed')))
            (out / 'failed-viewer-reinitialization.json').write_text(json.dumps(previous, indent=2) + '\n')
        elif previous['status'] != 'pending_remaining_engines':
            raise ValueError('Previous case has not reached the expected terminal checkpoint')
        record = previous
        record['cases'] = [c for c in previous['cases'] if c['status'] == 'passed']
        if any(c['engine'] == args.engine for c in record['cases']):
            raise ValueError('Requested engine is already completed; no duplicate searches permitted')
        record.pop('error', None)
        record.update(status='running', pid=os.getpid(), native_process_per_engine=True)

    def save():
        (out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')

    def check(condition, description, case):
        if not condition:
            raise AssertionError(description)
        case.setdefault('checks', []).append(description)

    def pump(seconds=.15):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            app.processEvents()
            time.sleep(.02)

    def notice(*values, **kwargs):
        record['messages'].append([str(v) for v in values[1:]])
        save()
        return QtWidgets.QMessageBox.StandardButton.Ok

    def decision(*values, **kwargs):
        raise RuntimeError('Unexpected scientific/modal decision; review required, no answer supplied')

    def wait(window, store, study, case, stage, predicate):
        case['phase'] = stage
        case['phase_started_utc'] = datetime.now(timezone.utc).isoformat()
        save()
        print(case['engine'] + ': ' + stage, flush=True)
        start = time.monotonic()
        last = 0
        while time.monotonic() - start < 3600:
            pump()
            current = store.load(study)
            failed = next((j for j in reversed(current.jobs) if j.status.value in ('failed', 'cancelled', 'interrupted')), None)
            if failed:
                raise RuntimeError(f'{stage}: {failed.error or failed.status.value}')
            if predicate(current):
                window.refresh()
                metric = (stage + '_completed_result_recheck_seconds'
                          if args.resume_completed_vina_review and case['engine'] == 'vina'
                          else stage + '_seconds')
                case[metric] = round(time.monotonic() - start, 3)
                save()
                return current
            if time.monotonic() - last > 5:
                window.refresh()
                case['elapsed_phase_seconds'] = round(time.monotonic() - start, 1)
                case['progress'] = current.active_job.progress_message if current.active_job else None
                last = time.monotonic()
                save()
        raise TimeoutError(stage + ' exceeded one hour; no duplicate job will be started')

    save()
    try:
        with patch.object(QtWidgets.QMessageBox, 'information', side_effect=notice), \
             patch.object(QtWidgets.QMessageBox, 'warning', side_effect=notice), \
             patch.object(QtWidgets.QMessageBox, 'critical', side_effect=notice), \
             patch.object(QtWidgets.QMessageBox, 'exec', side_effect=decision):
            for engine in (args.engine,):
                resumed_case = args.resume_completed_vina_review and engine == 'vina'
                case = record['cases'][0] if resumed_case else dict(engine=engine, status='running', checks=[])
                if not resumed_case:
                    record['cases'].append(case)
                root = out / engine
                root.mkdir(exist_ok=resumed_case)
                study = 'mac-' + engine + '-functional'
                store = JsonStudyStore(root / 'state')
                data = json.loads(json.dumps(original))
                data.update(study_id=study, name='Isolated Mac GUI check — ' + engine,
                            completion_status='draft', current_stage=None)
                data['jobs'] = [j for j in data['jobs'] if j['stage'] in ('preparation_and_pocket_detection', 'pocket_review')]
                data['artifacts'] = [a for a in data['artifacts'] if a['kind'] not in (
                    'protocol_bundle', 'final_report', 'final_protocol', 'final_report_figure')
                    and not a['kind'].startswith(('screening_', 'pose_interaction'))]
                for key in ('latest_screening_output', 'latest_screening_status', 'next_stage'):
                    data['workflow_data'].pop(key, None)
                data['workflow_data']['completed_stages'] = ['preparation_and_pocket_detection', 'pocket_review', 'region_approval']
                data['workflow_data']['validation_source'] = {'path': str(source), 'sha256': digest(source),
                    'scope': 'Previously reviewed preparation reused for authorized isolated engine functional checks'}
                if not resumed_case:
                    store.create(StudyState.from_dict(data))
                ligand = root / 'two-compounds.sdf'
                if not resumed_case:
                    shutil.copy2(project / 'examples/test_inputs/two_compounds.sdf', ligand)
                settings = QtCore.QSettings(str(root / 'window.ini'), QtCore.QSettings.Format.IniFormat)
                options = dict(python_executable=str(prefix / 'bin/python'), timeout_seconds=30)
                window = coordinator = None
                try:
                    with ApplicationHostClient(store.root, runtime / 'docking-universal-application-host.py', **options) as host:
                        widget = create_embedded_pymol_widget()
                        adapter = EmbeddedPymolAdapter(widget)
                        coordinator = StudyViewerCoordinator(adapter)
                        window = StudyWindow(store, study, host_client=host, settings=settings,
                                             viewer_coordinator=coordinator, viewer_widget=widget)
                        window.resize(1400, 900)
                        window.show()
                        pump(.5)
                        choices = [window.protocol_engine.itemData(i) for i in range(window.protocol_engine.count())]
                        case['gui_engine_choices'] = choices
                        check(set(choices) == {'vina', 'qvinaw', 'adgpu'}, 'All three installed GUI engine choices present', case)
                        window.protocol_engine.setCurrentIndex(window.protocol_engine.findData(engine))
                        window.protocol_conformers.setValue(1)
                        window.protocol_seeds.setValue(1)
                        window.protocol_base_seed.setValue(41001)
                        window.final_output_directory.setText(str(root / 'protocol'))
                        window.exploratory_approval.setChecked(True)
                        if not resumed_case:
                            window.start_protocol_finalization()
                        state = wait(window, store, study, case, 'finalization',
                            lambda s: not s.active_job and any(a.kind == 'protocol_bundle' for a in s.artifacts))
                        bundle = next(a.path for a in state.artifacts if a.kind == 'protocol_bundle')
                        protocol = inspect_protocol_bundle(bundle)
                        check(protocol['engine'] == engine, 'Finalized bundle retains selected engine', case)
                        case.update(protocol_bundle=bundle, protocol_report=next(a.path for a in state.artifacts if a.kind == 'final_report'))
                        window.screen_ligands.setText(str(ligand))
                        window.screen_output.setText(str(root / 'screen'))
                        window.read_screening_library()
                        library = window.screening_setup_panel.library_panel
                        start = time.monotonic()
                        while library.loading and time.monotonic() - start < 120:
                            pump()
                        check(bool(library.library) and len(library.library['records']) == 2, 'Two compounds loaded through GUI reader', case)
                        library.set_all(True)
                        if not resumed_case:
                            window.preview_screening()
                            check(bool(window._screening_plan), 'GUI workload preview accepted', case)
                            check(window._screening_plan['engine'] == engine and window._screening_plan['compound_count'] == 2,
                                  'Screening preview preserves engine and compound selection', case)
                            case['screening_plan'] = window._screening_plan
                        check(window.screening_setup_panel.cpu.isEnabled() == (engine != 'adgpu'), 'CPU tuning availability matches engine', case)
                        window.screen_exploratory_approval.setChecked(True)
                        if not resumed_case:
                            window.start_screening()
                        check(any(j.stage == 'screening' for j in store.load(study).jobs), 'GUI launched real screening job', case)
                        state = wait(window, store, study, case, 'screening', lambda s:
                            not s.active_job and s.workflow_data.get('latest_screening_status') == 'completed')
                        case['screening_report'] = next(a.path for a in reversed(state.artifacts) if a.kind == 'screening_report')
                        check(window.screening_results.rowCount() == 2, 'Both compound results visible', case)
                        expected = 'AD4' if engine == 'adgpu' else 'Vina'
                        check(all(window.screening_results.item(i, 5).text() == expected for i in range(2)),
                              'Result energy model shown correctly beside kcal/mol values', case)
                        check(all(window.screening_results.item(i, 4).text() not in ('NA', '') for i in range(2)), 'Both compounds have finite retained energies', case)
                        window._activate_workflow_target('screening_results_dock')
                        case['phase'] = 'native_interaction_review'
                        save()
                        count = 0
                        for row in range(2):
                            window.screening_results.selectRow(row)
                            pump(.3)
                            choice = window.interaction_diagram_choice
                            check(choice.count() > 0, f'Compound {row + 1}: retained cluster diagrams present', case)
                            for index in range(choice.count()):
                                choice.setCurrentIndex(index)
                                window._show_selected_interaction_diagram()
                                pump(.1)
                                view = pose_view(Path(choice.currentData()))
                                check(view is not None and adapter.review_pose == view.ligand.resolve(),
                                      f'Compound {row + 1}, representative {index + 1}: exact 3D pose loaded', case)
                                check(bool(adapter._plip_contacts), f'Compound {row + 1}, representative {index + 1}: PLIP contacts displayed', case)
                                count += 1
                            window.open_selected_interaction_diagram()
                            pump(.3)
                            pair = window._paired_interaction_window
                            check(pair is not None and pair.view == view, f'Compound {row + 1}: linked 2D/3D opens exact representative', case)
                            pair.grab().save(str(root / f'compound-{row + 1}-paired-review.png'))
                            window._close_interaction_review()
                        case['reviewed_representatives'] = count
                        window.grab().save(str(root / 'completed-gui.png'))
                        case['final_state_sha256'] = digest(store.path_for(study))
                        window.close()
                        pump(.2)
                        coordinator.close()
                        window = coordinator = None
                    with ApplicationHostClient(store.root, runtime / 'docking-universal-application-host.py', **options) as host:
                        reopened = StudyWindow(store, study, host_client=host, settings=settings)
                        reopened.show()
                        pump(.3)
                        check(reopened.screening_results.rowCount() == 2, 'Fresh-host reopening retains both results', case)
                        check(digest(store.path_for(study)) == case['final_state_sha256'], 'Reopening does not change saved scientific state', case)
                        reopened.close()
                        pump()
                    case.update(status='passed', phase='completed', finished_utc=datetime.now(timezone.utc).isoformat())
                except BaseException as exc:
                    case.update(status='failed', error=str(exc))
                    raise
                finally:
                    if window is not None:
                        window.close()
                    if coordinator is not None:
                        coordinator.close()
                    pump()
                    save()
        check(all(digest(path) == value for path, value in before.items()), 'Original user study states unchanged', record)
        complete = {c['engine'] for c in record['cases'] if c['status'] == 'passed'} == {'vina', 'qvinaw', 'adgpu'}
        record.update(status='passed' if complete else 'pending_remaining_engines', finished_utc=datetime.now(timezone.utc).isoformat())
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
        raise
    finally:
        save()
    print(record['status'], flush=True)


if __name__ == '__main__':
    main()
