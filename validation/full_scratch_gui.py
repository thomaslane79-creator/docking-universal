"""Three authorized, sequential, installed-GUI coverage runs from raw structures.

Approval is conditional on an identical prepared receptor and exact P1 geometry.
Never replaces studies, retries searches, guesses chemistry, or bypasses a gate.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from unittest.mock import patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from docking_universal.gui.desktop import StudyWindow
from docking_universal.gui.host_client import ApplicationHostClient
from docking_universal.gui.qt import QtCore, QtWidgets
from docking_universal.runtime_inventory import discover_poseedit_runtime
from docking_universal.services.protocol_import import inspect_protocol_bundle
from docking_universal.services.screening import read_protocol_record
from docking_universal.state import JsonStudyStore

ROOT = Path(__file__).resolve().parents[1]
INSTALLED = Path('/opt/anaconda3/envs/docking-universal/libexec/docking-universal')
SCIENTIFIC = '/opt/anaconda3/envs/docking-universal/bin/python'
ORIGINAL = Path('/Users/crown2/Library/Application Support/Docking Universal/studies/2R8N-Example-2/application_state.json')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def geometry(path):
    values = {}
    for line in Path(path).read_text().splitlines():
        text = line.split('#', 1)[0].strip()
        if '=' in text:
            key, value = map(str.strip, text.split('=', 1))
            values[key] = str(Decimal(value).normalize())
    expected = {prefix + axis for prefix in ('center_', 'size_') for axis in 'xyz'}
    if set(values) != expected:
        raise ValueError('Box does not contain exactly the six approved geometry fields')
    return values


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--resume-before-docking', action='store_true')
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=args.resume_before_docking)
    old = json.loads(ORIGINAL.read_text())
    bundle = next(a['path'] for a in old['artifacts'] if a['kind'] == 'protocol_bundle')
    approved = inspect_protocol_bundle(bundle)
    assert approved['engine'] == 'vina'
    expected_box = {key: str(Decimal(str(value)).normalize())
                    for key, value in approved['regions'][0]['geometry'].items()}
    record = {'status': 'running', 'phase': 'preflight', 'created_utc': datetime.now(timezone.utc).isoformat(),
              'pid': os.getpid(), 'cases': [], 'original_study': str(ORIGINAL),
              'original_study_sha256': sha(ORIGINAL), 'approved_bundle': bundle,
              'approved_bundle_sha256': sha(bundle), 'parameters': approved['parameters'],
              'authorization': 'User explicitly approves both raw-input paths, sequentially. Reuse P1/exploratory approval only with an identical prepared receptor and exact box geometry; otherwise pause.',
              'approval_gate': {'receptor_sha256': approved['receptor_sha256'], 'p1_geometry': expected_box}}
    if args.resume_before_docking:
        prior = json.loads((out / 'summary.json').read_text())
        if prior['status'] != 'failed' or list(out.glob('*/screen/compounds/*/seed_*/docking/*pdbqt')):
            raise ValueError('This continuation only resumes an inspected pre-docking failure')
        (out / 'pre-docking-attempt-1.json').write_text(json.dumps(prior, indent=2) + '\n')
        record = prior
        record.update(status='running', pid=os.getpid(), phase='Resuming retained preparation and saved approval')
        record.pop('error', None)
        record['continuation'] = 'Restarted the host after an invalid response frame; preserved preparation and persisted P1 approval. No downloads, preparation or docking were repeated.'
    record['coverage_plan'] = [{'input': 'fresh-download', 'target': '2R8N', 'engine': 'vina'},
                               {'input': 'local-pdb', 'target': '2R8N', 'engine': 'qvinaw'},
                               {'input': 'ligand-present', 'target': '2R5P', 'ligand': 'MK1 B:902', 'engine': 'adgpu'}]
    record['ligand_guided_authorization'] = 'User explicitly approved 2R5P/MK1 as an exploratory ligand-defined site, not AD4 control calibration.'
    def save():
        (out / 'summary.json').write_text(json.dumps(record, indent=2) + '\n')
    def phase(name, case=None):
        record['phase'] = name
        if case is not None:
            case['phase'] = name
        save()
        print(name, flush=True)
    save()
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    app.setQuitOnLastWindowClosed(False)
    messages = []
    def message(*values, **kwargs):
        messages.append([str(v) for v in values[1:]])
        return QtWidgets.QMessageBox.StandardButton.Ok
    def unexpected_dialog(*values, **kwargs):
        raise RuntimeError('A new chemistry/template decision requires user review; no consent was supplied automatically')
    def idle():
        for path in ORIGINAL.parent.parent.glob('*/application_state.json'):
            data = json.loads(path.read_text())
            if any(j['status'] in ('queued', 'running') for j in data.get('jobs', [])):
                raise RuntimeError('Another study has an active scientific calculation: ' + path.parent.name)
    options = dict(python_executable=SCIENTIFIC, timeout_seconds=30)
    def wait(window, store, study_id, predicate, case, stage):
        phase(stage, case)
        started = time.monotonic()
        last_save = 0
        while True:
            app.processEvents()
            state = store.load(study_id)
            if any(j.status.value in ('failed', 'cancelled', 'interrupted') for j in state.jobs):
                failed = next(j for j in reversed(state.jobs) if j.status.value in ('failed', 'cancelled', 'interrupted'))
                raise RuntimeError(f'{stage}: {failed.error or failed.status.value}')
            if predicate(state):
                window.refresh()
                case[stage + '_wall_seconds'] = time.monotonic() - started
                save()
                return state
            if time.monotonic() - last_save > 5:
                window.refresh()
                case['elapsed_stage_seconds'] = time.monotonic() - started
                case['last_progress'] = state.active_job.progress_message if state.active_job else None
                save()
                last_save = time.monotonic()
            if time.monotonic() - started > 3600:
                raise TimeoutError(stage + ': exceeded one hour; stopping rather than starting duplicate work')
            time.sleep(.15)
    try:
        idle()
        runtime = discover_poseedit_runtime()
        if runtime['status'] != 'available':
            raise RuntimeError('Approved local interaction renderer unavailable: ' + runtime['detail'])
        record['renderer_runtime'] = runtime
        save()
        with patch.object(QtWidgets.QMessageBox, 'warning', side_effect=message), \
             patch.object(QtWidgets.QMessageBox, 'critical', side_effect=message), \
             patch.object(QtWidgets.QMessageBox, 'information', side_effect=message), \
             patch.object(QtWidgets.QMessageBox, 'exec', side_effect=unexpected_dialog):
            for name, target, engine in (('fresh-download', '2R8N', 'vina'), ('local-pdb', '2R8N', 'qvinaw'),
                                         ('ligand-present', '2R5P', 'adgpu')):
                idle()
                case_root = out / name
                existing = next((item for item in record['cases'] if item['name'] == name), None)
                case_root.mkdir(exist_ok=bool(existing))
                case = existing or {'name': name, 'root': str(case_root), 'started_utc': datetime.now(timezone.utc).isoformat()}
                case.update(status='running', engine=engine, target=target)
                case.pop('error', None)
                if existing is None:
                    record['cases'].append(case)
                phase(name + ': setup', case)
                store = JsonStudyStore(case_root / 'state')
                settings = QtCore.QSettings(str(case_root / 'window.ini'), QtCore.QSettings.Format.IniFormat)
                study_id = target + '-' + name
                with ApplicationHostClient(store.root, INSTALLED / 'docking-universal-application-host.py', **options) as host:
                    if existing is None:
                        host.request(study_id, 'create_study', {'name': target + ' full run — ' + name})
                    window = StudyWindow(store, study_id, host_client=host, settings=settings)
                    window.resize(1400, 900)
                    window.show()
                    window.output_directory.setText(str(case_root / 'preparation'))
                    if existing:
                        source = Path(case['source'])
                    elif name != 'local-pdb':
                        phase('Downloading ' + target + ' mmCIF from RCSB', case)
                        window.input_pdb.setText(target)
                        downloaded = window.fetch_input_pdb()
                        if not downloaded:
                            raise RuntimeError('Fresh RCSB download did not succeed: ' + str(messages))
                        source = Path(downloaded)
                    else:
                        original_pdb = ROOT / 'examples/tutorials/02_ligand_free_cavity/inputs/2R8N.pdb'
                        (case_root / 'input').mkdir()
                        source = case_root / 'input/2R8N.pdb'
                        shutil.copy2(original_pdb, source)
                        case['local_original'] = str(original_pdb)
                        case['local_original_sha256'] = sha(original_pdb)
                        window.input_pdb.setText(str(source))
                        window.refresh_input_coordinate_evidence()
                    case.update(source=str(source), source_sha256=sha(source))
                    if existing is None:
                        window.pocket_engine.setCurrentIndex(window.pocket_engine.findData('p2rank'))
                        window.study_setup_panel.pdb_evidence.setChecked(True)
                        if name == 'ligand-present':
                            window.site_mode.setCurrentIndex(window.site_mode.findData('ligand'))
                            window.detect_bound_ligands()
                            choice = next((i for i in range(window.ligand_resname.count())
                                if isinstance(window.ligand_resname.itemData(i), dict)
                                and window.ligand_resname.itemData(i).get('resname') == 'MK1'
                                and window.ligand_resname.itemData(i).get('chain_id') == 'B'
                                and str(window.ligand_resname.itemData(i).get('residue_number')) == '902'), None)
                            if choice is None:
                                raise ValueError('Exact approved MK1 B:902 is unavailable; pause for review')
                            window.ligand_resname.setCurrentIndex(choice)
                            case['ligand_identity'] = window.study_setup_panel.ligand_identity()
                        window.start_preparation()
                        if not store.load(study_id).jobs:
                            raise RuntimeError('Preparation did not start: ' + str(messages))
                        state = wait(window, store, study_id, lambda s: bool(s.pending_decisions), case, 'Receptor preparation, site detection and fresh PDB evidence')
                        # Existing lookup progress prints share stdout with host
                        # JSON replies. Reconnect only after preparation/review
                        # has completed; never interrupt or restart calculation.
                        host.restart()
                        window.refresh()
                        state = store.load(study_id)
                        case['host_reconnected_after_completed_evidence'] = True
                    else:
                        state = store.load(study_id)
                        if state.active_job or any(j.status.value in ('failed', 'cancelled', 'interrupted') for j in state.jobs):
                            raise ValueError('Continuation requires completed retained preparation and no active/failed scientific jobs')
                    preparation = Path(state.workflow_data['preparation_root'])
                    candidates = state.workflow_data['pocket_candidates']
                    candidate = (candidates[0] if len(candidates) == 1 else None) if name == 'ligand-present' else next((p for p in candidates if p['id'] == 'P1'), None)
                    if candidate is None:
                        raise RuntimeError('No P1 candidate; scientific review is required')
                    box = Path(next(a.path for a in state.artifacts if a.id == candidate['box_artifact_id']))
                    receptors = list((preparation / 'receptor').glob('*.pdbqt'))
                    if len(receptors) != 1:
                        raise RuntimeError('Expected one primary prepared receptor; review its state inventory')
                    match = {'receptor': str(receptors[0]), 'receptor_sha256': sha(receptors[0]),
                             'receptor_exact_match': sha(receptors[0]) == approved['receptor_sha256'],
                             'box': str(box), 'box_sha256': sha(box), 'geometry': geometry(box),
                             'box_geometry_exact_match': geometry(box) == expected_box}
                    case['approval_comparison'] = match
                    window.grab().save(str(case_root / 'pocket-review.png'))
                    if name != 'ligand-present' and (not match['receptor_exact_match'] or not match['box_geometry_exact_match']):
                        case['status'] = record['status'] = 'awaiting_scientific_review'
                        phase('New receptor or box differs; user review required', case)
                        window.close()
                        return 0
                    selected_id = candidate['id']
                    if state.selected_pocket_ids != [selected_id]:
                        phase('Applying explicit user site approval', case)
                        row = next(i for i, value in enumerate(candidates) if value['id'] == selected_id)
                        window.candidates.selectRow(row)
                        window.rationale.setText('User explicitly authorized the exact deposited MK1 B:902 ligand-defined exploratory site, not AD4 control calibration.' if name == 'ligand-present' else
                            'User authorized reuse of P1 only after exact prepared-receptor SHA256 and six-field box geometry equality to the previously approved protocol; both checks passed.')
                        window.approve_selected_regions()
                        deadline = time.monotonic() + 5
                        while store.load(study_id).selected_pocket_ids != [selected_id] and time.monotonic() < deadline:
                            time.sleep(.05)
                        state = store.load(study_id)
                        if state.selected_pocket_ids == [selected_id] and messages and messages[-1][0] == 'Approval rejected':
                            case['approval_response_recovery'] = messages[-1]
                            host.restart()
                            window.refresh()
                    if state.selected_pocket_ids != [selected_id]:
                        raise RuntimeError('Conditional region approval did not apply')
                    p = approved['parameters']
                    engine_index = window.protocol_engine.findData(engine)
                    if engine_index < 0:
                        raise ValueError('Requested engine is unavailable: ' + engine)
                    window.protocol_engine.setCurrentIndex(engine_index)
                    for control, key in ((window.protocol_ph, 'ph'), (window.protocol_conformers, 'conformers_per_state'),
                                         (window.protocol_base_seed, 'ensemble_seed'), (window.protocol_exhaustiveness, 'exhaustiveness'),
                                         (window.protocol_modes, 'num_modes'), (window.protocol_energy_range, 'energy_range_kcal_per_mol')):
                        control.setValue(p[key])
                    window.protocol_seeds.setValue(len(p['seeds']))
                    window.final_output_directory.setText(str(case_root / 'protocol'))
                    window.exploratory_approval.setChecked(True)
                    window.start_protocol_finalization()
                    state = wait(window, store, study_id, lambda s: not s.active_job and any(a.kind == 'protocol_bundle' for a in s.artifacts), case, 'Finalizing new protocol and report')
                    new_bundle = next(a.path for a in state.artifacts if a.kind == 'protocol_bundle')
                    fresh = inspect_protocol_bundle(new_bundle)
                    common = ('ph', 'conformers_per_state', 'ensemble_seed', 'seeds', 'forcefield', 'rmsd_prune_angstrom', 'charge_model')
                    if fresh['engine'] != engine or any(fresh['parameters'].get(key) != p.get(key) for key in common) or (engine != 'adgpu' and fresh['parameters'] != p):
                        raise RuntimeError('New protocol settings differ; no screening was launched')
                    case['protocol_bundle'] = new_bundle
                    case['protocol_report'] = next(a.path for a in state.artifacts if a.kind == 'final_report')
                    ligands = case_root / 'two-compounds.sdf'
                    shutil.copy2(ROOT / 'examples/test_inputs/two_compounds.sdf', ligands)
                    window.screen_ligands.setText(str(ligands))
                    window.screen_output.setText(str(case_root / 'screen'))
                    window.read_screening_library()
                    panel = window.screening_setup_panel.library_panel
                    deadline = time.monotonic() + 120
                    while panel.loading and time.monotonic() < deadline:
                        app.processEvents()
                        time.sleep(.05)
                    if not panel.library or len(panel.library['records']) != 2:
                        raise RuntimeError('Expected two valid compound records')
                    panel.set_all(True)
                    window.preview_screening()
                    if not window._screening_plan or window._screening_plan['compound_count'] != 2:
                        raise RuntimeError('Compound selection/workload preview failed')
                    case['screening_plan'] = window._screening_plan
                    window.screen_exploratory_approval.setChecked(True)
                    window.start_screening()
                    state = wait(window, store, study_id, lambda s: not s.active_job and s.workflow_data.get('latest_screening_status') == 'completed', case, 'Docking selected compounds and generating reports')
                    case['screening_report'] = next(a.path for a in reversed(state.artifacts) if a.kind == 'screening_report')
                    case['finished_state_sha256'] = sha(store.path_for(study_id))
                    window.grab().save(str(case_root / 'completed-gui.png'))
                    window.close()
                    app.processEvents()
                with ApplicationHostClient(store.root, INSTALLED / 'docking-universal-application-host.py', **options) as host:
                    window = StudyWindow(store, study_id, host_client=host, settings=settings)
                    window.refresh()
                    if window.screening_results.rowCount() != 2 or sha(store.path_for(study_id)) != case['finished_state_sha256']:
                        raise RuntimeError('Fresh-host reopening did not preserve the two completed results')
                    window.close()
                if sha(ORIGINAL) != record['original_study_sha256'] or sha(bundle) != record['approved_bundle_sha256']:
                    raise RuntimeError('Original reference state or bundle changed during the run')
                case.update(status='completed', finished_utc=datetime.now(timezone.utc).isoformat(), reopened=True)
                save()
            record.update(status='completed', phase='Three input/engine coverage paths completed', original_study_unchanged=True)
    except BaseException as exc:
        record.update(status='failed', error=str(exc))
        if record['cases']:
            record['cases'][-1].update(status='failed', error=str(exc))
        raise
    finally:
        record['messages'] = messages
        save()
    print(json.dumps(record, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
