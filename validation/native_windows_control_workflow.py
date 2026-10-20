"""Native installed GUI control acceptance; public fixture, status-only artifact.

The normal installer must enable the independently accepted control capability.
No fixture override or installation mutation is permitted. No user study or
scientific default is changed. Quick tiers must NOT authorize screening (two seeds, minimum five);
separate five-seed fixtures exercise the approved-protocol path without override.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import sys
import time
import traceback
import urllib.request


class GateError(RuntimeError):
    pass


def require_enabled_controls(configuration):
    if configuration.get('native_control_supported') is not True:
        raise GateError('Fresh installation did not enable the accepted control capability; no fixture override is permitted')


def runtime_failure_metadata(root):
    """Retain code locations/types only, never log text or scientific values."""
    exceptions, locations, report_errors, missing_versions = set(), [], set(), set()
    for path in Path(root).rglob('*.log'):
        for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
            if 'PDF report error: complete version provenance is required for every software component used.' in line:
                report_errors.add('incomplete_used_software_provenance')
                for label in ('P2Rank', 'fpocket', 'Meeko', 'RDKit', 'PLIP', 'Open Babel', 'QuickVina-W', 'AutoDock Vina'):
                    if label + ': not recorded' in line or label + ': not detected' in line:
                        missing_versions.add(label)
            match = re.match(r'^([A-Za-z_]\w*(?:Error|Exception)):', line)
            if match:
                exceptions.add(match.group(1))
            match = re.match(r'\s*File "([^"]+)", line (\d+), in ([\w<>]+)', line)
            if match:
                name = match.group(1).replace('\\', '/').rsplit('/', 1)[-1]
                if re.fullmatch(r'[A-Za-z0-9_.-]+\.py', name):
                    locations.append({'file': name, 'line': int(match.group(2)), 'function': match.group(3)})
    return {'runtime_exception_types': sorted(exceptions), 'runtime_traceback_locations': locations[-16:],
            'report_failure_codes': sorted(report_errors), 'missing_version_software': sorted(missing_versions)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if platform.system() != 'Windows':
        parser.error('Real native Windows required')
    app, out = args.app.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    configuration_path = app / 'native-preview.json'
    original = configuration_path.read_bytes()
    configuration = json.loads(original)
    status = {'status': 'running', 'native_windows': True, 'cases': [],
              'candidate_configuration_only': False, 'capability_override_used': False, 'scientific_accuracy_claim': False,
              'production_control_enabled': bool(configuration.get('native_control_supported'))}
    client = window = application = None
    dialogs, callbacks = [], []
    def save():
        (out / 'summary.json').write_text(json.dumps(status, indent=2) + '\n', encoding='utf-8')
    save()
    try:
        require_enabled_controls(configuration)
        source = out / '1STP.cif'
        with urllib.request.urlopen('https://files.rcsb.org/download/1STP.cif', timeout=60) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != '36be77b9722ebb9f603b27bf16cbc30057f87ab9923a2d2adab0eadbdb30c30f':
            raise GateError('Public fixture checksum changed; no preparation/control was started')
        source.write_bytes(data)
        sys.path.insert(0, str(app))
        from docking_universal.windows_scientific_runtime import scientific_environment
        from docking_universal.native_entrypoint import isolated_environment
        from docking_universal.windows_viewer_runtime import activate_installed_viewer
        scientific, inherited, _ = scientific_environment(app, configuration, os.environ)
        os.environ.clear(); os.environ.update(isolated_environment(Path(sys.prefix), inherited))
        os.environ.update(MPLCONFIGDIR=str(out / 'matplotlib-cache'), XDG_CACHE_HOME=str(out / 'cache'))
        os.environ.pop('QT_QPA_PLATFORM', None)
        activate_installed_viewer(app)
        from docking_universal.gui.qt import QtCore, QtWidgets
        from docking_universal.gui.desktop import StudyWindow
        from docking_universal.gui.host_client import ApplicationHostClient
        from docking_universal.gui.study_viewer import StudyViewerCoordinator
        from docking_universal.viewer.embedded_pymol import create_embedded_pymol_widget, EmbeddedPymolAdapter
        from docking_universal.state import JsonStudyStore
        from docking_universal.host import ApplicationHostLease
        from docking_universal.protocol_finalization import sha256
        application = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
        application.setQuitOnLastWindowClosed(False)
        def callback(kind, value, tb):
            callbacks.append(kind.__name__)
            with (out / 'callbacks.local.log').open('a', encoding='utf-8') as stream:
                traceback.print_exception(kind, value, tb, file=stream)
        sys.excepthook = callback
        def dialog(_parent, title, message, *_a, **_kw):
            dialogs.append(title)
            with (out / 'dialogs.local.log').open('a', encoding='utf-8') as stream:
                stream.write(title + '\n' + message + '\n')
            return QtWidgets.QMessageBox.StandardButton.Ok
        QtWidgets.QMessageBox.critical = staticmethod(dialog)
        QtWidgets.QMessageBox.warning = staticmethod(dialog)
        root = out / 'Studies Ω 日本語'
        store = JsonStudyStore(root)
        client = ApplicationHostClient(root, app / 'docking-universal-application-host.py',
                                       python_executable=scientific, timeout_seconds=30)
        client.start()
        if not client.runtime.get('known_ligand_control_supported'):
            raise GateError('Installed host did not expose the normally enabled accepted control capability')
        settings = QtCore.QSettings(str(out / 'desktop.ini'), QtCore.QSettings.Format.IniFormat)
        def wait(study, predicate, seconds=300):
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                application.processEvents()
                state = store.load(study)
                if dialogs or callbacks:
                    raise GateError('Native control GUI raised a failure dialog/callback; details retained locally')
                if state.completion_status.value == 'failed' or any(j.status.value == 'failed' for j in state.jobs):
                    raise GateError('Native control job/orchestration failed; scientific diagnostics remain local')
                if any(d.kind != 'select_pockets' for d in state.pending_decisions):
                    raise GateError('Preparation requires an unaccepted chemical intervention; decision preserved')
                if predicate(state):
                    window.refresh()
                    return state
                time.sleep(.05)
            raise GateError('Native control fixture exceeded its bounded deadline; incomplete, not a successful control')
        def close_window():
            nonlocal window
            if window is not None:
                window.close()
                window.viewer_coordinator.close()
                window.deleteLater()
                application.sendPostedEvents(None, QtCore.QEvent.Type.DeferredDelete)
                application.processEvents()
                window = None
        for engine, prediction, tier in (('vina', False, 'quick'), ('qvinaw', True, 'quick'),
                                        ('vina', False, 'repeatability'), ('qvinaw', True, 'repeatability')):
            study = 'control-' + engine + '-' + tier
            case = {'engine': engine, 'additional_p2rank': prediction, 'tier': tier,
                    'status': 'running', 'phase': 'setup'}
            status['cases'].append(case); save()
            started = time.monotonic()
            client.request(study, 'create_study', {'name': 'Disposable public control fixture ' + engine})
            widget = create_embedded_pymol_widget()
            viewer = StudyViewerCoordinator(EmbeddedPymolAdapter(widget))
            window = StudyWindow(store, study, settings=settings, host_client=client,
                                 viewer_coordinator=viewer, viewer_widget=widget)
            window.show(); application.processEvents()
            window.input_pdb.setText(str(source))
            window.output_directory.setText(str(out / ('Control Ω ' + engine + ' ' + tier)))
            window.study_pathway.setCurrentIndex(window.study_pathway.findData('control'))
            window.study_setup_panel.pdb_evidence.setChecked(False)
            window.study_setup_panel.predict_with_ligand.setChecked(prediction)
            window.control_engine.setCurrentIndex(window.control_engine.findData(engine))
            window.control_tier.setCurrentIndex(window.control_tier.findData(tier))
            window.detect_bound_ligands(quiet=True)
            combo = window.ligand_resname
            index = next((i for i in range(combo.count()) if (combo.itemData(i) or {}).get('resname') == 'BTN'
                          and (combo.itemData(i) or {}).get('chain_id') == 'A'
                          and str((combo.itemData(i) or {}).get('residue_number')) == '300'), -1)
            if index < 0:
                raise GateError('Exact public control ligand was not detected')
            combo.setCurrentIndex(index)
            window.start_preparation_button.click()
            case['phase'] = 'preparation'; save()
            state = wait(study, lambda s: bool(s.pending_decisions))
            if state.selected_pocket_ids or any(j.stage == 'control_validation' for j in state.jobs):
                raise GateError('Control ran or a site was approved before explicit fixture review')
            native = json.loads((Path(state.workflow_data['preparation_root']) / 'native-preparation.json').read_text(encoding='utf-8'))
            if bool(native['pocket_prediction_requested']) != prediction:
                raise GateError('Native preparation did not preserve the optional predictor choice')
            candidates = state.workflow_data['pocket_candidates']
            selected = next((i for i, row in enumerate(candidates)
                             if row['evidence'].get('source') == 'input_bound_ligand'
                             or row['evidence'].get('input_bound_ligand')), -1)
            if selected < 0 or not prediction and len(candidates) != 1:
                raise GateError('Native ligand-only/optional-prediction review candidates are incorrect')
            window.candidates.selectRow(selected)
            window.rationale.setText('Disposable CI fixture only: inspect native control, not target accuracy')
            window.approve_button.click()
            state = wait(study, lambda s: bool(s.selected_pocket_ids) and not s.pending_decisions)
            from docking_universal.services.control_review import reviewed_control_inputs
            sealed = reviewed_control_inputs(state)
            protected = {asset['path']: asset['sha256'] for asset in sealed['assets'].values()}
            if not window.protocol_finalization_panel._control_mode or not window.finalize_button.isEnabled():
                raise GateError('Reviewed control action is not available after the explicit site decision')
            window.finalize_button.click()
            case['phase'] = 'redocking'; save()
            state = wait(study, lambda s: not s.active_job and bool(s.workflow_data.get('latest_control_status')), seconds=1200)
            control_output = Path(state.workflow_data['latest_control_output'])
            protocols = list((control_output / 'control/04_redocking' / engine / tier).glob('protocol.json'))
            if len(protocols) != 1:
                raise GateError('Native control did not retain its shared selected-tier protocol record')
            protocol = json.loads(protocols[0].read_text(encoding='utf-8'))
            approved = tier == 'repeatability'
            if (bool(protocol.get('unknown_docking_allowed')) != approved
                    or state.workflow_data['latest_control_status'] != ('approved' if approved else 'not_approved')
                    or bool(protocol['acceptance']['seed_requirement_pass']) != approved):
                raise GateError('Native control did not preserve the real quick/five-seed approval outcome; no criterion changed')
            if any(sha256(Path(path)) != expected for path, expected in protected.items()):
                raise GateError('Control changed the reviewed source/receptor/box or repeated preparation')
            bundles = [Path(a.path) for a in state.artifacts if a.kind == 'protocol_bundle']
            if bool(bundles) != approved:
                raise GateError('Native control bundle publication disagrees with its actual approval outcome')
            if approved:
                from docking_universal_bundle import extract_bundle, resolve_locked_path
                restored = extract_bundle(bundles[0])
                portable = json.loads(restored.read_text(encoding='utf-8'))
                if portable['engine'] != engine or not portable['unknown_docking_allowed']:
                    raise GateError('Approved portable protocol lost its engine or real control authority')
                for key in ('receptor', 'receptor_pdb', 'box'):
                    asset = resolve_locked_path(restored, portable['locked_inputs'][key])
                    if sha256(asset) != portable['locked_inputs'][key + '_sha256']:
                        raise GateError('Approved portable protocol failed its retained input checksums')
            reports = [Path(a.path) for a in state.artifacts if a.kind == 'final_report']
            if not reports or not all(p.read_bytes().startswith(b'%PDF-') for p in reports):
                raise GateError('Native control did not retain its ordinary report PDF')
            case.update(status='passed', phase='completed', seconds=round(time.monotonic()-started, 3),
                        review_before_search=True, reviewed_inputs_unchanged=True, minimum_seed_gate_preserved=True,
                        report_pdf=True, approved_bundle=approved, portable_inputs_verified=approved)
            save(); close_window()
        reader = client._reader; client.close()
        if reader.is_alive():
            raise GateError('Native control host reader survived close')
        with ApplicationHostLease(root):
            pass
        status.update(status='passed', failure_dialog_count=0, host_lease_released=True)
    except BaseException as exc:
        if status['cases'] and status['cases'][-1]['status'] == 'running':
            status['cases'][-1]['status'] = 'failed'
        status.update(status='failed', error_type=type(exc).__name__,
                      error=str(exc) if isinstance(exc, GateError) else 'Native control candidate failed; details retained locally',
                      locations=[{'file': Path(f.filename).name, 'function': f.name, 'line': f.lineno}
                                 for f in traceback.extract_tb(exc.__traceback__)[-8:]])
        (out / 'error.local.log').write_text(traceback.format_exc(), encoding='utf-8')
        status.update(runtime_failure_metadata(out))
    finally:
        if client is not None:
            try:
                client.close()  # cancel/reap; never rewrite installation capability
            except BaseException as exc:
                status.update(status='failed', host_cleanup_error_type=type(exc).__name__)
        if window is not None:
            try:
                window.viewer_coordinator.close()
                window.hide(); window.deleteLater()
                application.processEvents()
            except BaseException:
                status['viewer_cleanup_failed'] = True; status['status'] = 'failed'
        status['installation_configuration_unchanged'] = configuration_path.read_bytes() == original
        if not status['installation_configuration_unchanged']:
            status['status'] = 'failed'
        save()
    return 0 if status['status'] == 'passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
