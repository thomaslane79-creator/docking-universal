"""Explicit, isolated model recovery before a failed preparation has any boxes.

The accepted control/setup stays authoritative. Only a hash-bound, explicitly
approved derivative is passed to a new full preparation attempt; this module
does not choose exclusions, switch the workflow, or run a control automatically.
"""
from __future__ import annotations

from dataclasses import fields, replace
import json
from pathlib import Path
import re
import threading
import time
from uuid import uuid4

from ..application import ActiveStageError
from ..models import ArtifactRecord
from ..protocol_finalization import sha256
from .preparation import ReceptorPreparationOptions, ReceptorPreparationService, build_receptor_preparation_plan
from .receptor_model_review import preview_changes, write_model, retain_reviewed_receptor_input, validate_reviewed_model_inputs
from .structure_input import normalize_structure_input

# Observed parameter coverage, not a claim of target-specific docking accuracy.
# Extend only after checking the independent backend's parameters and output.
VERIFIED_ELEMENT_ALTERNATIVES = {'Co': 'adfr'}


def _actionable_guidance(result, setup, attempted=(), stages=None, *, element=None, blocked=()):
    """Route every diagnosis to existing controls and explain each tool's role.

    A fresh independent method is a checked candidate, not a compatibility
    assertion. Failed/used methods are never presented as fresh suggestions.
    Availability is additionally filtered by the GUI's current host capabilities.
    """
    from .preparation_interventions import RECOVERY_ACTIONS, RECOVERY_ACTION_CODES, PREPARATION_TOOL_ROLES
    code = result['diagnosis_code']
    result['attempted_backends'] = sorted(set(attempted))
    result['stage_statuses'] = stages or {}
    result['tool_roles'] = PREPARATION_TOOL_ROLES
    eligible = {'unsupported_element', 'linked_components', 'cofactor_template', 'modified_residue',
                'component_template', 'residue_template', 'nucleic_acid_template',
                'connectivity_construction', 'valence_validation', 'output_validation',
                'alternative_failed', 'unsupported_charge_assignment'}
    candidates = [backend for backend in ('adfr', 'meeko')
                  if code in eligible and backend not in attempted and backend not in blocked]
    result['method_candidates'] = [{'backend': backend,
        'basis': ('observed element coverage; model still needs output validation'
                  if VERIFIED_ELEMENT_ALTERNATIVES.get(element) == backend else
                  'independent method not yet attempted; support for this model is unverified')}
        for backend in candidates]
    result['recommended_backend'] = candidates[0] if candidates else None
    actions = []
    if candidates:
        actions.append({'id': 'method', 'label': 'Try an untried preparation method', 'target': 'method',
            'instructions': 'Review the available method and its role under Advanced. Keep components unchanged '
                'unless you separately choose an exact model change. Preview, enter your rationale and acknowledge '
                'the method change before starting. The resulting atoms, coordinates, types and charges must pass '
                'validation; this is a candidate attempt, not a promise of compatible chemistry.'})
        result['next_step'] += ' An untried method can be reviewed below; its output must still pass validation.'
    for key in RECOVERY_ACTION_CODES[code]:
        label, target, instructions = RECOVERY_ACTIONS[key]
        actions.append({'id': key, 'label': label, 'target': target, 'instructions': instructions})
    if not any(row['id'] == 'diagnostics' for row in actions):
        label, target, instructions = RECOVERY_ACTIONS['diagnostics']
        actions.append({'id': 'diagnostics', 'label': label, 'target': target, 'instructions': instructions})
    result['actions'] = actions
    if code in eligible and not candidates:
        result['next_step'] += ' The recorded methods have no untried automatic remedy; use the guided review or corrected-input actions below.'
    statuses = '\n'.join(name + ': ' + str(value).replace('_', ' ') for name, value in (stages or {}).items())
    result['details'] += ('\n\nRecorded stages:\n' + statuses if statuses else '')
    result['details'] += '\n\nTool roles:\n' + '\n\n'.join(PREPARATION_TOOL_ROLES.values())
    return result


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


def recovery_guidance(state, source_path):
    """Explain observed failures without authorizing a change or promising a fix.

    Advice belongs to the most recent failed attempt. The reviewed choices and
    their preview hash remain the only authority for an eventual retry.
    """
    if not state.jobs or state.jobs[-1].status.value != 'failed':
        return None
    job = state.jobs[-1]
    setup = state.workflow_data.get('study_setup') or {}
    from .preparation_interventions import diagnosis_code, RECOVERY_DESCRIPTIONS
    process_error = str(getattr(job, 'error', None) or '')
    if 'P2Rank launcher not found' in process_error or 'P2Rank could not start' in process_error:
        # Preflight may fail before writing fresh receptor logs. Do not use an
        # older run directory to propose a molecular workaround for this case.
        summary, action = RECOVERY_DESCRIPTIONS['pocket_runtime']
        return _actionable_guidance({'diagnosis_code': 'pocket_runtime', 'summary': summary, 'next_step': action,
                'recommended_backend': None, 'last_backend': setup.get('preparation_backend')
                    if setup.get('preparation_backend') in {'meeko', 'adfr'} else 'meeko',
                'details': process_error + '\n\nNo molecular correction is inferred from a predictor startup failure.'}, setup)
    from .preparation import _canonical_name
    root = Path(setup['working_directory']) / (_canonical_name(Path(source_path)) + '_receptor_prep')
    original_root = root
    attempt = next((row for row in reversed(state.workflow_data.get('receptor_preparation_attempts') or [])
                    if row.get('request_id') == job.request_id), None)
    if attempt:
        root = Path(attempt['root'])
    receptor = root / 'receptor'

    def read_record(name):
        try:
            value = json.loads((receptor / name).read_text())
            return value if isinstance(value, dict) else {}
        except (OSError, ValueError):
            return {}

    def record_rows(record, key):
        value = record.get(key)
        return value if isinstance(value, list) else []

    logs = []
    for name in ('receptor_backend.log', 'receptor_after_pdbfixer.log', 'receptor_adfr_fallback.log'):
        try:
            with (receptor / name).open(errors='replace') as handle:
                logs.append(handle.read(256000))
        except OSError:
            pass
    text = '\n'.join(logs)
    intervention = read_record('preparation_intervention.json')
    element_match = re.search(r"Element ([A-Z][a-z]?) (?:doesn't|does not) have an implemented covalent radius",
        text + '\n' + str(intervention.get('detected_detail') or ''))
    element = element_match.group(1) if element_match else None
    code = intervention.get('diagnosis_code')
    if not isinstance(code, str) or code not in RECOVERY_DESCRIPTIONS:
        code = diagnosis_code(intervention.get('category'))
    if code == 'unclassified' and element:
        code = 'unsupported_element'
    fallback = intervention.get('adfr_fallback') or read_record('ccd_modification_audit.json').get('adfr_fallback') or {}
    if not isinstance(fallback, dict):
        fallback = {}
    output = read_record('adfr_output_audit.json')
    missing_charges = [row for row in record_rows(output, 'missing_charge_parameters') if isinstance(row, str)]
    summary, action = RECOVERY_DESCRIPTIONS[code]
    result = {'summary': summary, 'next_step': action, 'diagnosis_code': code,
              'recommended_backend': None,
              'last_backend': setup.get('preparation_backend') if setup.get('preparation_backend') in {'meeko', 'adfr'} else 'meeko'}
    if output.get('backend') == 'adfr' or fallback.get('status') in {'validation_failed', 'failed', 'succeeded'}:
        result['last_backend'] = 'adfr'
    details = []
    missing_definitions = []
    for name, label in (('reduce2_audit.json', 'Hydrogen placement (Reduce2)'),
                        ('pdb2pqr_audit.json', 'Protonation assessment (PDB2PQR/PROPKA)'),
                        ('pdbfixer_audit.json', 'Structural repair (PDBFixer)')):
        record = read_record(name)
        if record:
            details.append(label + ': ' + str(record.get('status', 'result recorded')).replace('_', ' ') + '.')
            if name == 'reduce2_audit.json':
                missing_definitions = [str(item) for item in record_rows(record, 'missing_components')]
                if missing_definitions:
                    details.append('Missing component definitions: ' + ', '.join(missing_definitions) + '.')
    if element:
        details.append('Standard preparation (Meeko) rejected element ' + element + ' because its covalent-radius definition is unavailable.')
    if intervention.get('category'):
        details.append('Recorded diagnosis: ' + str(intervention['category']) + '.')
    if intervention.get('detected_detail'):
        details.append('Detected detail: ' + str(intervention['detected_detail']))
    if fallback:
        details.append('Alternative preparation (ADFRsuite): ' + str(fallback.get('status', 'result recorded')).replace('_', ' ')
                       + '. ' + str(fallback.get('reason') or ''))
    if missing_charges:
        summary, action = RECOVERY_DESCRIPTIONS['unsupported_charge_assignment']
        result.update(summary=summary, next_step=action,
            diagnosis_code='unsupported_charge_assignment')
        details.append('Atoms without supported charge assignments:\n' + '\n'.join(missing_charges))
        affected = []
        for message in missing_charges:
            match = re.search(r'for atom\s+[^:\s]+:([^:]*):\s*([^:\s]+):([^\s:]+)', message)
            if match:
                chain, component_number, atom = match.groups()
                affected.append(f'{component_number} chain {chain or "(blank)"}, atom {atom}')
        if affected:
            result['affected_components'] = affected
            result['summary'] += ' Affected: ' + '; '.join(affected[:3]) + (f'; {len(affected)-3} more.' if len(affected)>3 else '.')
    elif output.get('backend') == 'adfr' and output.get('status') == 'rejected':
        summary, action = RECOVERY_DESCRIPTIONS['output_validation']
        result.update(summary=summary, next_step=action, diagnosis_code='output_validation')
        details.extend(str(reason) for reason in record_rows(output, 'reasons'))
    elif fallback.get('status') in {'validation_failed', 'failed', 'startup_failed', 'unavailable'}:
        unavailable = fallback.get('status') in {'startup_failed', 'unavailable'}
        failure_code = 'runtime_unavailable' if unavailable else 'output_validation' if fallback['status'] == 'validation_failed' else 'alternative_failed'
        summary, action = RECOVERY_DESCRIPTIONS[failure_code]
        result.update(summary=summary, next_step=action, diagnosis_code=failure_code)
        details.extend(str(reason) for reason in record_rows(output, 'reasons'))
    elif element and code == 'unsupported_element':
        names = {'Co': 'cobalt', 'Se': 'selenium', 'Cu': 'copper', 'Ni': 'nickel', 'Zn': 'zinc', 'Fe': 'iron'}
        result['summary'] = 'Standard preparation lacks parameters for ' + names.get(element, 'element ' + element) + ' in this structure.'
        # Co coverage has been checked in the independent backend. Other
        # elements get an explanation without an invented compatibility claim.
        if element in VERIFIED_ELEMENT_ALTERNATIVES:
            details.append('The independent backend has observed cobalt element coverage; support for the whole current model still requires output validation.')
    elif missing_definitions and code == 'unclassified' and setup.get('reduce2') == 'required':
        summary, action = RECOVERY_DESCRIPTIONS['missing_component_definitions']
        result.update(summary=summary, next_step=action, diagnosis_code='missing_component_definitions')
        result['affected_components'] = missing_definitions
        result['summary'] += ' Components: ' + ', '.join(missing_definitions[:5]) + '.'
    if result['diagnosis_code'] == 'unclassified' and text.strip():
        details.append('Unrecognized diagnostic excerpt:\n' + text.strip()[-4000:])
    if result['diagnosis_code'] == 'unclassified':
        protonation = read_record('pdb2pqr_audit.json')
        hydrogen = read_record('reduce2_audit.json')
        repair = read_record('pdbfixer_audit.json')
        required_code = ('protonation_review' if setup.get('protonation') == 'required'
                         and protonation and protonation.get('status') != 'compatible' else
                         'hydrogen_preparation' if setup.get('reduce2') == 'required'
                         and hydrogen and hydrogen.get('status') not in {'compatible', 'completed'} else
                         'incomplete_backbone' if repair.get('status') == 'review_required_missing_backbone_atoms' else
                         'repair_geometry' if repair.get('status') == 'rejected_generated_geometry' else None)
        if required_code:
            summary, action = RECOVERY_DESCRIPTIONS[required_code]
            result.update(diagnosis_code=required_code, summary=summary, next_step=action)
    details.append('Retained diagnostic directory: ' + str(receptor))
    details.append('Any suggested method is a candidate to test, not a guarantee. Only explicitly approved changes run; '
                   'atom retention, types and charges are checked. Successful preparation does not establish docking accuracy.')
    result['details'] = '\n\n'.join(details)
    result['diagnostic_files'] = [{'path': str(path.resolve()), 'sha256': sha256(path)}
        for path in sorted(receptor.iterdir() if receptor.is_dir() else [])
        if path.is_file() and path.suffix.lower() in {'.log', '.json', '.txt'}]
    stages = {}
    for name, label, option in (('reduce2_audit.json', 'Hydrogen placement', 'reduce2'),
                                ('pdb2pqr_audit.json', 'Protonation assessment', 'protonation'),
                                ('pdbfixer_audit.json', 'Structural repair', 'pdbfixer')):
        record = read_record(name)
        stages[label] = record.get('status') or ('disabled by settings' if setup.get(option) == 'off' else 'not recorded for this attempt')
    stages['Alternative preparation'] = str(fallback.get('status') or 'not recorded for this attempt')
    attempted = set()
    roots = {root, original_root}
    roots.update(Path(row['root']) for row in state.workflow_data.get('receptor_preparation_attempts', [])
                 if row.get('root') and any(j.request_id == row.get('request_id') for j in state.jobs))
    for prior_root in roots:
        directory = prior_root / 'receptor'
        try:
            prior_output = json.loads((directory / 'adfr_output_audit.json').read_text())
        except (OSError, ValueError):
            prior_output = {}
        if not isinstance(prior_output, dict):
            prior_output = {}
        adfr_primary = (setup.get('preparation_backend') == 'adfr' and prior_root == original_root) or (
            prior_output.get('backend') == 'adfr' and
            Path(str(prior_output.get('backend_log_path') or '')).name == 'receptor_backend.log')
        if (directory / 'receptor_backend.log').is_file():
            attempted.add('adfr' if adfr_primary else 'meeko')
        if prior_output.get('backend') == 'adfr' or (directory / 'receptor_adfr_fallback.log').is_file():
            attempted.add('adfr')
    attempted.add(result['last_backend'])
    blocked = {'adfr'} if fallback.get('status') in {'startup_failed', 'unavailable'} else set()
    return _actionable_guidance(result, setup, attempted, stages, element=element, blocked=blocked)


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
        raise ValueError('No preparation changes were selected for a reviewed recovery')
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
