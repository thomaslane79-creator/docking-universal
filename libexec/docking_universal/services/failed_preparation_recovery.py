"""Explicit, isolated model recovery before a failed preparation has any boxes.

The accepted control/setup stays authoritative. Only a hash-bound, explicitly
approved derivative is passed to a new full preparation attempt; this module
does not choose exclusions, switch the workflow, or run a control automatically.
"""
from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path
import threading
import time
from uuid import uuid4

from ..application import ActiveStageError
from ..models import ArtifactRecord
from ..protocol_finalization import sha256
from .preparation import ReceptorPreparationOptions, ReceptorPreparationService, build_receptor_preparation_plan
from .receptor_model_review import preview_changes, write_model, retain_reviewed_receptor_input, validate_reviewed_model_inputs
from .structure_input import normalize_structure_input


def failed_preparation_job(state):
    """Require the exact terminal failed stage, never a completed control/run."""
    setup = state.workflow_data.get('study_setup') or {}
    jobs = [job for job in state.jobs if job.stage == 'preparation_and_pocket_detection']
    if (setup.get('explore_sites_first') or not jobs or jobs[-1].status.value != 'failed'
            or state.jobs[-1].id != jobs[-1].id
            or any(job.status.value == 'completed' for job in jobs)
            or state.pending_decisions or state.active_job or state.selected_pocket_ids
            or state.workflow_data.get('latest_control_status')
            or any(a.kind in {'prepared_receptor', 'protocol_bundle'} for a in state.artifacts)):
        raise ValueError('Exact model recovery requires a failed preparation before any accepted receptor or box review')
    return jobs[-1]


def recovery_input(state):
    """Reconstruct missing failure artifacts from the locked, hash-bound source.

    A failed engine may never have registered input artifacts. Normalization
    uses an isolated deterministic review cache, then compares any existing
    normalized input instead of silently replacing it.
    """
    failed_preparation_job(state)
    setup = state.workflow_data['study_setup']
    source = Path(setup.get('input_structure') or setup.get('input_pdb') or '')
    expected = setup.get('input_structure_sha256')
    if not expected or not source.is_file() or sha256(source) != expected:
        raise ValueError('Original receptor source changed or lacks its locked input hash')
    for artifact in state.artifacts:
        if artifact.kind in {'source_receptor_structure', 'normalized_receptor_input', 'structure_input_metadata'}:
            if not artifact.sha256 or not Path(artifact.path).is_file() or sha256(Path(artifact.path)) != artifact.sha256:
                raise ValueError('Registered original receptor input changed before model review')
    working = Path(setup['working_directory'])
    normalized = normalize_structure_input(source, working / '.docking-universal-model-review-inputs')
    if normalized.source_sha256 != expected:
        raise ValueError('Original receptor source changed during model review')
    existing = Path(setup.get('input_pdb') or '')
    if existing.is_file() and sha256(existing) != sha256(normalized.engine_pdb_path):
        raise ValueError('Normalized original receptor input changed before model review')
    return normalized


def options_from_setup(setup):
    keys = {field.name for field in fields(ReceptorPreparationOptions)}
    values = {key: value for key, value in setup.items() if key in keys}
    values['input_pdb'] = setup.get('input_structure') or values.get('input_pdb')
    for key in ('input_pdb', 'working_directory', 'geostd_library', 'meeko_template_file'):
        if values.get(key):
            values[key] = Path(values[key])
    return values


def prepare_failed_receptor_changes(runner, state, model_changes, *, request_id, expected_revision):
    """Retry only the existing full preparation route with reviewed input bytes."""
    failed_preparation_job(state)
    if (not isinstance(model_changes, dict) or set(model_changes) != {'choices', 'preview_sha256', 'actor', 'rationale'}
            or any(not isinstance(model_changes[key], str) or not model_changes[key].strip()
                   for key in ('preview_sha256', 'actor', 'rationale'))):
        raise ValueError('Exact preview, actor and rationale are required for receptor changes')
    setup = state.workflow_data['study_setup']
    preview = runner.preview_receptor_changes(state.study_id, model_changes['choices'], expected_revision=expected_revision)
    if preview['preview_sha256'] != model_changes['preview_sha256']:
        raise ValueError('Receptor changes differ from the reviewed preview')
    if not preview['changes']:
        raise ValueError('No molecular changes were selected for an exact-model recovery')
    if preview.get('connectivity_execution'):
        raise ValueError('Saved coordinate-stage connectivity recovery requires the existing reviewed-site route')
    _, derivative = preview_changes(preview['source_path'], model_changes['choices'], context=preview['context'])
    values = options_from_setup(setup)
    original = build_receptor_preparation_plan(runner.preparation_executable, ReceptorPreparationOptions(**values))
    if original.structure_input.source_sha256 != setup['input_structure_sha256']:
        raise ValueError('Original receptor source changed before the reviewed attempt')
    model_root = Path(setup['working_directory']) / '.docking-universal-reviewed-models' / uuid4().hex
    model, model_record = write_model(model_root, original.receptor_pdb.name, preview, derivative,
        actor=model_changes['actor'], rationale=model_changes['rationale'])
    model_record['reviewed_receptor_input'] = retain_reviewed_receptor_input(model_root, preview, derivative)
    model_record['execution_policy'] = dict(preparation_backend=preview['preparation_backend'],
        pdbfixer='off', reduce2='off', protonation='off', reviewed_model_only=True,
        parameterization_only=False)
    record_path = model_root / 'reviewed_model.json'
    record_path.write_text(json.dumps(model_record, indent=2) + '\n')
    record_hash = sha256(record_path)
    values.update(input_pdb=model, working_directory=model_root / 'preparation', pdbfixer='off',
                  reduce2='off', protonation='off',
                  preparation_backend=preview['preparation_backend'])
    plan = build_receptor_preparation_plan(runner.preparation_executable, ReceptorPreparationOptions(**values))
    environment = dict(plan.request.environment)
    environment.update(DOCKING_UNIVERSAL_REVIEWED_MODEL_ONLY='1',
                       DOCKING_UNIVERSAL_PARAMETERIZATION_ONLY='0', MEEKO_DEFAULT_ALTLOC='',
                       DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT=model_record['reviewed_receptor_input']['path'],
                       DOCKING_UNIVERSAL_REVIEWED_RECEPTOR_INPUT_SHA256=model_record['reviewed_receptor_input']['sha256'])
    # The worker reads the derivative; artifact registration retains the exact
    # original source/normalized identity needed by bound-reference review.
    plan = replace(plan, structure_input=original.structure_input,
                   request=replace(plan.request, environment=environment))
    if plan.output_root.exists():
        raise ValueError('The isolated reviewed preparation output already exists')

    def mark(latest):
        latest.workflow_data['receptor_parameterization_status'] = 'running'
        latest.workflow_data.setdefault('reviewed_receptor_models', []).append({
            'request_id': request_id, 'record': str(record_path), 'preview_sha256': preview['preview_sha256'],
            'status': 'preparing', 'actor': model_record['actor'], 'rationale': model_record['rationale']})
        for suffix, kind, path in (('record', 'reviewed_receptor_model', record_path),
                                   ('input', 'reviewed_receptor_input', model),
                                   ('filtered', 'reviewed_receptor_filtered_input', Path(model_record['reviewed_receptor_input']['path']))):
            latest.artifacts.append(ArtifactRecord('reviewed-model-' + model_root.name + '-' + suffix,
                kind, str(path), sha256(path), 'Explicitly reviewed receptor change; control validation remains pending'))

    retained, _ = runner.controller.store.update(state.study_id, mark, expected_revision=expected_revision)
    cancellation = threading.Event()
    original_pins = {str(original.structure_input.source_path): setup['input_structure_sha256'],
                     str(original.structure_input.engine_pdb_path): sha256(original.structure_input.engine_pdb_path),
                     str(original.structure_input.metadata_path): sha256(original.structure_input.metadata_path)}

    def validate_before_finish():
        validate_reviewed_model_inputs(model_record, record_path, record_hash, additional_pins=original_pins)

    def work():
        result_status = 'failed'
        try:
            result = ReceptorPreparationService(runner.controller).run(state.study_id, plan,
                cancel_event=cancellation, request_id=request_id, expected_revision=retained.revision,
                allow_template_decision=False, stage='preparation_and_pocket_detection',
                before_finish=validate_before_finish)
            result_status = result.status.value
            history_path = None
            if result_status == 'completed':
                validate_before_finish()
                from .receptor_model_history import SCHEMA, normalize_preparation
                history = {'schema_name': SCHEMA, 'schema_version': 1,
                    'original_input_sha256': setup['input_structure_sha256'],
                    'model_input_sha256': preview['model_input_sha256'],
                    'prepared_receptor_sha256': sha256(plan.receptor_pdbqt), 'review_record_sha256': record_hash,
                    'preparation_backend': preview['preparation_backend'],
                    'execution_policy': model_record['execution_policy'],
                    'reviewed_receptor_input_sha256': model_record['reviewed_receptor_input']['sha256'],
                    'baseline_receptor_input_sha256': model_record['reviewed_receptor_input']['baseline_sha256'],
                    'changes': [dict(change, actor=model_record['actor'], rationale=model_record['rationale'])
                                for change in model_record['changes']]}
                normalize_preparation({'model_change_history': history}, sha256(plan.receptor_pdbqt))
                history_path = plan.output_root / 'receptor/receptor_model_history.json'
                history_path.write_text(json.dumps(history, indent=2) + '\n')

            def finish(latest):
                latest.workflow_data['receptor_parameterization_status'] = result_status
                latest.workflow_data['receptor_parameterization_attempt_root'] = str(plan.output_root)
                latest.workflow_data.setdefault('receptor_preparation_attempts', []).append({
                    'request_id': request_id, 'root': str(plan.output_root), 'status': result_status,
                    'reviewed_model': str(model_root), 'stage': 'preparation_and_pocket_detection'})
                for review in latest.workflow_data['reviewed_receptor_models']:
                    if review['request_id'] == request_id:
                        review['status'] = result_status
                if history_path:
                    latest.artifacts.append(ArtifactRecord('receptor-model-history', 'receptor_model_history',
                        str(history_path), sha256(history_path), 'Portable record of explicitly reviewed receptor changes'))
                if result_status != 'completed':
                    from .preparation_site_issues import collect_site_issues
                    issues = collect_site_issues(plan.output_root, original.structure_input.engine_pdb_path)
                    latest.workflow_data['preparation_site_issues'] = issues
                    paths = [Path(path) for path in issues['diagnostic_logs']] + [plan.run_log]
                    paths.extend(plan.output_root / 'receptor' / name for name in
                                 ('preparation_intervention.json', 'receptor_failure_diagnosis.txt', 'adfr_output_audit.json'))
                    for index, path in enumerate(paths):
                        if path.is_file():
                            latest.artifacts.append(ArtifactRecord('reviewed-attempt-' + model_root.name + '-' + str(index),
                                'preparation_diagnostic', str(path), sha256(path), 'Retained isolated reviewed-attempt failure'))

            # History must be registered before box review projects its warning.
            runner.controller.store.update(state.study_id, finish)
            if result_status == 'completed':
                if setup.get('pdb_pocket_evidence', 'related-structures') == 'related-structures':
                    runner._collect_pdb_pocket_evidence(state.study_id, plan)
                runner._start_review(state.study_id, plan.output_root)
        except Exception as exc:
            def retain_failure(latest):
                latest.workflow_data['receptor_parameterization_status'] = 'failed'
                latest.workflow_data['receptor_parameterization_attempt_root'] = str(plan.output_root)
                attempts = latest.workflow_data.setdefault('receptor_preparation_attempts', [])
                if not any(attempt['request_id'] == request_id for attempt in attempts):
                    attempts.append({'request_id': request_id, 'root': str(plan.output_root), 'status': 'failed',
                        'reviewed_model': str(model_root), 'stage': 'preparation_and_pocket_detection'})
                for review in latest.workflow_data['reviewed_receptor_models']:
                    if review['request_id'] == request_id and review['status'] == 'preparing':
                        review['status'] = 'failed'
            runner.controller.store.update(state.study_id, retain_failure)
            runner._record_orchestration_failure(state.study_id, exc)
        finally:
            with runner._guard:
                runner._cancellations.pop(state.study_id, None)
                runner._threads.pop(state.study_id, None)

    thread = threading.Thread(target=work, name=f'du-reviewed-preparation-{state.study_id}', daemon=True)
    with runner._guard:
        if runner._threads:
            raise ActiveStageError('Another scientific workflow is already running')
        runner._threads[state.study_id] = thread
        runner._cancellations[state.study_id] = cancellation
        thread.start()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        latest = runner.controller.get_study(state.study_id)
        job = next((job for job in latest.jobs if job.request_id == request_id), None)
        if job:
            return {'job_id': job.id, 'stage': job.stage, 'output_root': str(plan.output_root)}
        if not thread.is_alive():
            break
        time.sleep(.01)
    raise RuntimeError('Reviewed preparation worker did not persist its job start')
