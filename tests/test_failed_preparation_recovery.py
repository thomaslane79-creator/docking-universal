"""Failed-control recovery uses synthetic workers; no scientific calculation runs."""
import copy
import json
import os
import shlex
from pathlib import Path
import shlex
from types import SimpleNamespace
import tempfile
import time
import unittest

from docking_universal.application import StudyController
from docking_universal.host import CommandDispatcher
from docking_universal.orchestration import ProtocolWorkflowRunner
from docking_universal.protocol_finalization import sha256
from docking_universal.state import JsonStudyStore
from docking_universal.viewer.messages import Command


def atom(serial, name, residue, chain, number, x=0, record='HETATM'):
    return (f'{record:<6}{serial:5d} {name:>4} {residue:>3} {chain}{number:4d}    '
            f'{x:8.3f}{0:8.3f}{0:8.3f}{1:6.2f}{20:6.2f}           C\n')


def link(first, second):
    row = list(' ' * 80); row[:6] = 'LINK  '
    for offset, (name, residue, chain, number) in ((0, first), (30, second)):
        row[12 + offset:16 + offset] = f'{name:>4}'
        row[17 + offset:20 + offset] = residue
        row[21 + offset] = chain
        row[22 + offset:26 + offset] = f'{number:4d}'
    return ''.join(row) + '\n'


class FailedPreparationRecoveryTests(unittest.TestCase):
    def setUp(self):
        if os.name == 'nt':
            self.skipTest('POSIX host recovery; Windows retains its explicit native acceptance gate')
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'Target.pdb'
        data = ''.join(link(('CA', 'GLY', 'A', 1), endpoint) for endpoint in
                       (('C1', 'NAG', 'A', 200), ('C1', 'COH', 'A', 602), ('C1', 'COH', 'B', 603)))
        data += atom(1, 'CA', 'GLY', 'A', 1, record='ATOM')
        data += atom(2, 'C1', 'NAG', 'A', 200, 10) + atom(3, 'C2', 'NAG', 'A', 200, 11)
        data += atom(4, 'C1', 'COH', 'A', 602, 20) + atom(5, 'C2', 'COH', 'A', 602, 21)
        data += atom(6, 'C1', 'COH', 'B', 603, 30) + atom(7, 'C2', 'COH', 'B', 603, 31)
        data += ''.join(atom(8 + i, 'C' + str(i), 'ID8', 'B', 602, 14 + i / 10) for i in range(10))
        self.source.write_text(data + 'END\n')
        self.source_hash = sha256(self.source)
        self.store = JsonStudyStore(self.root / 'state')
        self.controller = StudyController(self.store)
        self.controller.create_study('test', 'Control fixture')
        self.engine = self.root / 'bin/docking-universal-prepare'
        self.engine.parent.mkdir()
        self.engine.write_text('#!/bin/sh\nmkdir -p Target_receptor_prep/receptor\n'
            'printf "original preparation failed\\n" > Target_receptor_prep/run.log\nexit 1\n')
        self.engine.chmod(0o755)
        self.engine.with_name('docking-universal-run.py').write_text('# retained control fixture\n')
        library = self.root / 'geostd'; library.mkdir()
        self.runner = ProtocolWorkflowRunner(self.controller, self.engine)
        self.addCleanup(self.runner.shutdown)
        self.runner.start_control_validation('test', {
            'input_structure': str(self.source), 'output_directory': str(self.root / 'run'),
            'ligand_resname': 'ID8', 'ligand_chain_id': 'B', 'ligand_residue_number': '602',
            'engine': 'vina', 'control_tier': 'repeatability', 'geostd_library': str(library),
            'pocket_engine': 'p2rank', 'predict_pockets_with_ligand': True, 'pdb_pocket_evidence': 'off',
        }, request_id='original', expected_revision=self.store.load('test').revision)
        self.failed = self.wait(lambda state: state.jobs[-1].status.value == 'failed')
        self.setup = copy.deepcopy(self.failed.workflow_data['study_setup'])
        self.original_log = self.root / 'run/preparation/Target_receptor_prep/run.log'
        self.original_log_hash = sha256(self.original_log)
        self.dispatcher = CommandDispatcher(self.controller, 'fixture-session')
        self.dispatcher.workflow_runner = self.runner
        self.nag = dict(resname='NAG', chain='A', number='200', insertion_code='')

    def wait(self, predicate):
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            state = self.store.load('test')
            if predicate(state):
                return state
            time.sleep(.02)
        self.fail('Timed out: ' + repr(self.store.load('test')))

    def dispatch(self, operation, payload, revision, request):
        return self.dispatcher.dispatch(Command('test', 'fixture-session', request, operation, payload, revision))

    def preview(self, choices=None):
        choices = choices if choices is not None else {'exclusions': [self.nag], 'preparation_backend': 'adfr'}
        response = self.dispatch('preview_receptor_changes', {'choices': choices}, self.failed.revision, 'preview-' + str(time.monotonic()))
        self.assertEqual(response.status, 'applied', response.error)
        return response.result['preview']

    def payload(self, preview=None):
        preview = preview or self.preview()
        return dict(choices=preview['choices'], preview_sha256=preview['preview_sha256'],
                    actor='scientist', rationale='Exact synthetic glycan exclusion reviewed for this control model')

    def successful_worker(self):
        self.engine.write_text('#!/bin/sh\nset -eu\n'
            'test "$DOCKING_UNIVERSAL_REVIEWED_MODEL_ONLY" = 1\n'
            'test "$DOCKING_UNIVERSAL_PARAMETERIZATION_ONLY" = 0\n'
            'test "$DOCKING_UNIVERSAL_PDBFIXER" = off\n'
            'test "$DOCKING_UNIVERSAL_REDUCE2" = off\n'
            'test "$DOCKING_UNIVERSAL_PROTONATION" = off\n'
            'test "$DOCKING_UNIVERSAL_PREP_BACKEND" = adfr\n'
            'test "$DOCKING_UNIVERSAL_LIGAND_RESNAME" = ID8\n'
            'test "$DOCKING_UNIVERSAL_LIGAND_CHAIN" = B\n'
            'test "$DOCKING_UNIVERSAL_LIGAND_RESSEQ" = 602\n'
            'test "$DOCKING_UNIVERSAL_POCKET_ENGINE" = p2rank\n'
            'test "$DOCKING_UNIVERSAL_SITE_MODE" = pockets\n'
            'root=Target_receptor_prep\nmkdir -p "$root/receptor" "$root/cavity"\n'
            'cp "$1" "$root/receptor/Target.pdb"\n'
            'printf "prepared fixture\\n" > "$root/receptor/Target.pdbqt"\n'
            'printf "isolated full preparation\\n" > "$root/run.log"\n'
            'printf "center_x = 15\\ncenter_y = 0\\ncenter_z = 0\\nsize_x = 26\\nsize_y = 26\\nsize_z = 26\\n" > "$root/cavity/Target_pocket1.conf"\n')

    def test_preview_recovers_missing_failure_artifacts_without_changing_control(self):
        self.assertFalse(any(a.kind == 'normalized_receptor_input' for a in self.failed.artifacts))
        preview = self.preview()
        self.assertEqual(preview['review_stage'], 'failed_preparation')
        self.assertTrue(preview['box_review_pending'])
        self.assertEqual(preview['selected_box_review'], [])
        self.assertEqual(preview['preparation_backend'], 'adfr')
        self.assertEqual(preview['context']['original_input_sha256'], self.source_hash)
        self.assertEqual(self.store.load('test').workflow_data['study_setup'], self.setup)
        self.assertEqual(sha256(self.source), self.source_hash)
        self.assertEqual(sha256(self.original_log), self.original_log_hash)
        self.assertEqual(len(self.store.load('test').jobs), 1)

    def test_exact_retry_preserves_source_control_settings_and_registers_history_before_boxes(self):
        payload = self.payload(); self.successful_worker()
        response = self.dispatch('prepare_receptor_changes', payload, self.failed.revision, 'reviewed')
        self.assertEqual(response.status, 'applied', response.error)
        self.assertEqual(response.result['stage'], 'preparation_and_pocket_detection')
        done = self.wait(lambda state: bool(state.pending_decisions))
        self.assertEqual(done.workflow_data['study_setup'], self.setup)
        self.assertNotIn('explore_sites_first', done.workflow_data['study_setup'])
        self.assertEqual([job.stage for job in done.jobs], ['preparation_and_pocket_detection', 'preparation_and_pocket_detection', 'pocket_review'])
        self.assertEqual(done.approvals, [])
        self.assertNotIn('latest_control_status', done.workflow_data)
        originals = {a.kind: a for a in done.artifacts if a.kind in {'source_receptor_structure', 'normalized_receptor_input'}}
        self.assertEqual(originals['source_receptor_structure'].path, str(self.source.resolve()))
        self.assertEqual(originals['normalized_receptor_input'].path, self.setup['input_pdb'])
        model = next(a for a in done.artifacts if a.kind == 'reviewed_receptor_input')
        self.assertNotIn('NAG', Path(model.path).read_text())
        self.assertEqual(sum(line.startswith(('ATOM  ', 'HETATM')) and line[17:20] == 'COH'
                             for line in Path(model.path).read_text().splitlines()), 4)
        self.assertEqual(Path(model.path).read_text().count(' ID8 '), 10)
        filtered = next(a for a in done.artifacts if a.kind == 'reviewed_receptor_filtered_input')
        self.assertEqual(Path(filtered.path).read_text().count(' COH '), 4)
        self.assertNotIn('NAG', Path(filtered.path).read_text())
        history = next(a for a in done.artifacts if a.kind == 'receptor_model_history')
        self.assertEqual(json.loads(Path(history.path).read_text())['original_input_sha256'], self.source_hash)
        self.assertNotEqual(Path(response.result['output_root']), self.original_log.parent)
        self.assertEqual(sha256(self.original_log), self.original_log_hash)
        self.assertEqual(sha256(self.source), self.source_hash)
        from docking_universal.services.preparation_site_issues import candidate_with_model_change_review
        candidate = candidate_with_model_change_review(done, done.workflow_data['pocket_candidates'][0])
        self.assertEqual(candidate['evidence']['receptor_model_review']['status'], 'prepared_with_reviewed_model_changes')
        self.assertEqual(self.dispatch('prepare_receptor_changes', payload, self.failed.revision, 'reviewed').status, 'replayed')

    def test_selected_reference_and_stale_or_changed_preview_never_launch(self):
        reference = dict(resname='ID8', chain='B', number='602', insertion_code='')
        rejected = self.dispatch('preview_receptor_changes', {'choices': {'exclusions': [reference]}}, self.failed.revision, 'reference')
        self.assertEqual(rejected.status, 'rejected')
        self.assertIn('reference ligand', rejected.error)
        payload = self.payload()
        for request, changed in (('changed-backend', {**payload, 'choices': {'exclusions': [self.nag], 'preparation_backend': 'meeko'}}),
                                 ('no-actor', {**payload, 'actor': ''}), ('wrong-preview', {**payload, 'preview_sha256': '0' * 64})):
            response = self.dispatch('prepare_receptor_changes', changed, self.failed.revision, request)
            self.assertEqual(response.status, 'rejected')
        self.assertFalse((self.root / 'run/preparation/.docking-universal-reviewed-models').exists())
        self.source.write_text(self.source.read_text() + 'REMARK changed\n')
        response = self.dispatch('prepare_receptor_changes', payload, self.failed.revision, 'changed-source')
        self.assertEqual(response.status, 'rejected')
        self.assertIn('source changed', response.error)
        self.assertEqual(len(self.store.load('test').jobs), 1)

    def test_unchanged_method_and_invalid_backend_payload_are_not_model_approval(self):
        preview = self.preview({'preparation_backend': 'meeko'})
        self.assertEqual(preview['changes'], [])
        response = self.dispatch('prepare_receptor_changes', self.payload(preview), self.failed.revision, 'backend-only')
        self.assertEqual(response.status, 'rejected')
        self.assertIn('No preparation changes', response.error)
        response = self.dispatch('preview_receptor_changes', {'choices': {'preparation_backend': {'arbitrary': 'command'}}},
                                 self.failed.revision, 'invalid-backend')
        self.assertEqual(response.status, 'rejected')
        self.assertFalse((self.root / 'run/preparation/.docking-universal-reviewed-models').exists())
        self.assertEqual(len(self.store.load('test').jobs), 1)

    def test_method_only_retry_keeps_the_complete_input_and_records_method_scope(self):
        preview = self.preview({'preparation_backend': 'adfr'})
        self.assertEqual([row['kind'] for row in preview['changes']], ['preparation_method_change'])
        self.assertEqual(preview['removed_atom_count'], 0)
        self.assertEqual(preview['model_input_sha256'], preview['source_sha256'])
        payload = self.payload(preview)
        self.successful_worker()
        response = self.dispatch('prepare_receptor_changes', payload, self.failed.revision, 'keep-all')
        self.assertEqual(response.status, 'applied', response.error)
        done = self.wait(lambda state: bool(state.pending_decisions))
        model = next(a for a in done.artifacts if a.kind == 'reviewed_receptor_input')
        self.assertEqual(Path(model.path).read_bytes(), self.source.read_bytes())
        filtered = next(a for a in done.artifacts if a.kind == 'reviewed_receptor_filtered_input')
        self.assertEqual(Path(filtered.path).read_text().count(' COH '), 4)
        self.assertEqual(Path(filtered.path).read_text().count(' NAG '), 2)
        self.assertEqual(done.workflow_data['study_setup'], self.setup)
        from docking_universal.services.preparation_site_issues import candidate_with_model_change_review
        impact = candidate_with_model_change_review(done, done.workflow_data['pocket_candidates'][0])['evidence']['receptor_model_review']
        self.assertTrue(impact['preparation_method_changed'])
        self.assertTrue(impact['changes_inside_box'])
        self.assertIn('whole receptor', impact['warning'])
        history = json.loads(Path(next(a.path for a in done.artifacts if a.kind == 'receptor_model_history')).read_text())
        history['changes'][0]['removed_other_components'] = 1
        from docking_universal.services.receptor_model_history import validate_history
        with self.assertRaisesRegex(ValueError, 'unchanged input'):
            validate_history(history)

    def test_already_attempted_alternative_is_not_a_fresh_method_only_retry(self):
        receptor = self.original_log.parent / 'receptor'
        (receptor / 'adfr_output_audit.json').write_text(json.dumps({'backend': 'adfr',
            'missing_charge_parameters': ['Unsupported charge assignment']}))
        preview = self.preview({'preparation_backend': 'adfr'})
        self.assertEqual(preview['changes'], [])
        self.assertIn('unsupported charge', preview['recovery_guidance']['summary'])
        response = self.dispatch('prepare_receptor_changes', self.payload(preview), self.failed.revision, 'repeat-alternative')
        self.assertEqual(response.status, 'rejected')
        self.assertEqual(len(self.store.load('test').jobs), 1)

    def test_failed_reviewed_attempt_keeps_both_attempts_and_locked_settings(self):
        payload = self.payload()
        response = self.dispatch('prepare_receptor_changes', payload, self.failed.revision, 'failed-retry')
        self.assertEqual(response.status, 'applied', response.error)
        done = self.wait(lambda state: len(state.jobs) == 2 and state.jobs[-1].status.value == 'failed'
                         and state.workflow_data.get('receptor_preparation_attempts'))
        self.assertEqual(done.workflow_data['study_setup'], self.setup)
        self.assertEqual(sha256(self.original_log), self.original_log_hash)
        self.assertTrue(Path(response.result['output_root']).is_dir())
        self.assertFalse(done.pending_decisions)
        self.assertFalse(any(a.kind == 'prepared_receptor' for a in done.artifacts))
        self.assertTrue(any(a.kind == 'preparation_diagnostic' for a in done.artifacts))
        self.assertIsNone(done.active_job)

    def test_worker_source_mutation_fails_before_job_completion_or_prepared_artifacts(self):
        payload = self.payload(); self.successful_worker()
        with self.engine.open('a') as worker:
            worker.write('printf "REMARK mutated after outputs\\n" >> ' + shlex.quote(str(self.source)) + '\n')
        response = self.dispatch('prepare_receptor_changes', payload, self.failed.revision, 'mutating-worker')
        self.assertEqual(response.status, 'applied', response.error)
        done = self.wait(lambda state: len(state.jobs) == 2 and state.jobs[-1].status.value == 'failed'
                         and bool(state.workflow_data.get('receptor_preparation_attempts')))
        self.assertIn('Original receptor', done.jobs[-1].error)
        self.assertIn('changed during preparation', done.jobs[-1].error)
        self.assertFalse(any(a.kind in {'prepared_receptor', 'prepared_receptor_structure', 'receptor_model_history'}
                             for a in done.artifacts))
        self.assertFalse(done.pending_decisions)
        self.assertEqual(done.workflow_data['study_setup'], self.setup)
        self.assertEqual(done.workflow_data['receptor_preparation_attempts'][-1]['status'], 'failed')
        self.assertTrue(Path(response.result['output_root']).is_dir())
        self.assertEqual(sha256(self.original_log), self.original_log_hash)
        self.assertTrue(any(event.type.value == 'stage_failed' and 'changed during preparation' in event.explanation
                            for event in done.events))
        self.assertFalse(any(event.type.value == 'stage_completed' for event in done.events))

    def test_stale_revision_and_parallel_worker_are_rejected(self):
        payload = self.payload()
        response = self.dispatch('prepare_receptor_changes', payload, self.failed.revision - 1, 'stale')
        self.assertEqual(response.status, 'rejected')
        ready, release = self.root / 'worker-ready', self.root / 'release-worker'
        self.engine.write_text('#!/bin/sh\ntouch ' + shlex.quote(str(ready)) + '\n'
            'while [ ! -f ' + shlex.quote(str(release)) + ' ]; do sleep .01; done\n'
            'mkdir -p Target_receptor_prep/receptor\n'
            'printf "reviewed attempt failed\\n" > Target_receptor_prep/run.log\nexit 1\n')
        response = self.dispatch('prepare_receptor_changes', payload, self.failed.revision, 'first-worker')
        self.assertEqual(response.status, 'applied', response.error)
        try:
            # Wait for PID and initial progress registration, then hold the
            # worker at a barrier. A timed sleep lets those writes race this
            # request and correctly trigger a stale-revision guard instead.
            running = self.wait(lambda state: len(state.jobs) == 2 and ready.exists()
                                and state.jobs[-1].process_id and state.jobs[-1].progress_phase)
            rejected = self.dispatch('preview_receptor_changes', {'choices': payload['choices']}, running.revision, 'parallel')
            self.assertEqual(rejected.status, 'rejected')
            self.assertIn('active stage', rejected.error)
            self.assertEqual(len(self.store.load('test').jobs), 2)
        finally:
            release.touch()
        self.wait(lambda state: len(state.jobs) == 2 and state.jobs[-1].status.value == 'failed')

    def test_mmcif_failure_can_preview_without_registered_input_artifacts(self):
        import gemmi
        source = self.root / 'Modern.cif'
        gemmi.read_structure(str(self.source)).make_mmcif_document().write_file(str(source))
        self.controller.create_study('modern', 'Modern control')
        self.runner.start_control_validation('modern', {
            'input_structure': str(source), 'output_directory': str(self.root / 'modern-run'),
            'ligand_resname': 'ID8', 'ligand_chain_id': 'B', 'ligand_residue_number': '602',
            'engine': 'vina', 'control_tier': 'repeatability', 'geostd_library': str(self.root / 'geostd'),
            'pocket_engine': 'p2rank', 'predict_pockets_with_ligand': True, 'pdb_pocket_evidence': 'off',
        }, request_id='modern-original', expected_revision=self.store.load('modern').revision)
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            state = self.store.load('modern')
            if state.jobs[-1].status.value == 'failed':
                break
            time.sleep(.02)
        setup = copy.deepcopy(state.workflow_data['study_setup'])
        preview = self.runner.preview_receptor_changes('modern', {'exclusions': [self.nag]}, expected_revision=state.revision)
        self.assertEqual(preview['context']['original_input_sha256'], sha256(source))
        self.assertTrue(preview['box_review_pending'])
        self.assertEqual(self.store.load('modern').workflow_data['study_setup'], setup)
        self.assertFalse(any(a.kind == 'normalized_receptor_input' for a in state.artifacts))


class ReviewedReceptorInventoryTests(unittest.TestCase):
    def test_excluded_link_parent_does_not_silently_remove_its_remaining_child(self):
        from docking_universal.services.receptor_model_review import preview_changes, write_model, retain_reviewed_receptor_input
        from docking_universal.receptor_filter import filter_receptor_pdb
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); source = root / 'linked.pdb'
            source.write_text(link(('CA', 'GLY', 'A', 1), ('C1', 'NAG', 'C', 2))
                + link(('C2', 'NAG', 'C', 2), ('C1', 'MAN', 'C', 3))
                + atom(1, 'CA', 'GLY', 'A', 1, record='ATOM')
                + atom(2, 'C1', 'NAG', 'C', 2) + atom(3, 'C2', 'NAG', 'C', 2)
                + atom(4, 'C1', 'MAN', 'C', 3) + atom(5, 'C2', 'MAN', 'C', 3))
            choice = {'exclusions': [dict(resname='NAG', chain='C', number='2', insertion_code='')]}
            preview, derivative = preview_changes(source, choice, context={})
            preview['source_path'] = str(source)
            model, _ = write_model(root / 'review', 'linked.pdb', preview, derivative,
                                   actor='scientist', rationale='Exact parent-only exclusion')
            filter_receptor_pdb(model, root / 'naively-refiltered.pdb')
            self.assertNotIn('MAN', (root / 'naively-refiltered.pdb').read_text())
            retained = retain_reviewed_receptor_input(root / 'review', preview, derivative)
            text = Path(retained['path']).read_text()
            self.assertNotIn('NAG', text)
            self.assertEqual(text.count(' MAN '), 2)
            self.assertEqual(sha256(retained['path']), retained['sha256'])


class RecoveryGuidanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'Target.pdb'
        self.receptor = self.root / 'Target_receptor_prep/receptor'
        self.receptor.mkdir(parents=True)
        self.state = SimpleNamespace(jobs=[SimpleNamespace(request_id='failed', status=SimpleNamespace(value='failed'))],
            workflow_data={'study_setup': {'working_directory': str(self.root)}})

    def guidance(self):
        from docking_universal.services.failed_preparation_recovery import recovery_guidance
        return recovery_guidance(self.state, self.source)

    def cobalt(self):
        (self.receptor / 'receptor_backend.log').write_text(
            "RuntimeError: Element Co doesn't have an implemented covalent radius\n")

    def write_record(self, name, record):
        (self.receptor / name).write_text(json.dumps(record))

    def test_cobalt_suggests_an_alternative_without_selecting_changes_or_promising_success(self):
        self.cobalt()
        self.write_record('reduce2_audit.json', {'status': 'component_definitions_required', 'missing_components': ['COH']})
        self.write_record('pdbfixer_audit.json', {'status': 'completed_conservative_repair'})
        before = copy.deepcopy(self.state.workflow_data)
        result = self.guidance()
        self.assertEqual(result['recommended_backend'], 'adfr')
        self.assertIn('cobalt', result['summary'])
        self.assertIn('must still pass validation', result['next_step'])
        self.assertIn('Missing component definitions: COH', result['details'])
        self.assertIn('PDBFixer', result['details'])
        self.assertEqual(self.state.workflow_data, before)

    def test_alternative_charge_failure_explains_remaining_work(self):
        self.cobalt()
        self.write_record('preparation_intervention.json', {'adfr_fallback': {'status': 'validation_failed'}})
        self.write_record('adfr_output_audit.json', {'missing_charge_parameters': [
            'Sorry, there are no Gasteiger parameters available for atom Target:B:NAG607:O6']})
        result = self.guidance()
        self.assertIn('unsupported charge', result['summary'])
        self.assertIn('No component is selected for removal', result['next_step'])
        self.assertIn('NAG607:O6', result['details'])
        self.assertEqual(result['recommended_backend'], 'adfr')

    def test_unavailable_alternative_does_not_recommend_an_unusable_retry(self):
        self.cobalt()
        self.write_record('preparation_intervention.json', {'adfr_fallback': {'status': 'startup_failed', 'reason': 'Bad CPU type'}})
        result = self.guidance()
        self.assertIsNone(result['recommended_backend'])
        self.assertIn('Resolve the unavailable', result['next_step'])
        self.assertIn('Bad CPU type', result['details'])

    def test_latest_attempt_does_not_reuse_the_original_cobalt_diagnosis(self):
        self.cobalt()
        latest = self.root / 'latest'
        (latest / 'receptor').mkdir(parents=True)
        self.state.workflow_data['receptor_preparation_attempts'] = [{'request_id': 'failed', 'root': str(latest)}]
        result = self.guidance()
        self.assertIsNone(result['recommended_backend'])
        self.assertNotIn('rejected cobalt', result['details'])

    def test_missing_or_malformed_evidence_is_not_a_claim_of_tool_compatibility(self):
        self.write_record('adfr_output_audit.json', {'missing_charge_parameters': 'not an atom list', 'reasons': None})
        (self.receptor / 'reduce2_audit.json').write_text('{broken')
        result = self.guidance()
        self.assertIsNone(result['recommended_backend'])
        self.assertIn('unrecognized reason', result['summary'])
        self.state.jobs[-1].status.value = 'completed'
        self.assertIsNone(self.guidance())

    def test_existing_diagnostic_categories_generate_specific_recovery_text(self):
        cases = (
            ('Explicit alternate-location selection required', 'alternate conformations', 'Choose'),
            ('Incomplete deposited backbone requires review', 'backbone', 'corrected structure'),
            ('Covalently linked nonstandard residues or glycans', 'linked components', 'linkage definitions'),
            ('Unsupported heme or cofactor template', 'cofactor', 'keep it'),
            ('Preparation backend valence-validation error', 'valences', 'hydrogens'),
            ('Ambiguous histidine protonation', 'Histidine', 'state'),
        )
        for category, problem, action in cases:
            with self.subTest(category=category):
                self.write_record('preparation_intervention.json', {'category': category})
                result = self.guidance()
                self.assertNotEqual(result['diagnosis_code'], 'unclassified')
                self.assertIn(problem, result['summary'])
                self.assertIn(action, result['next_step'])
                self.assertIsNone(result['recommended_backend'])

    def test_engine_intervention_publishes_a_stable_diagnostic_identifier(self):
        from docking_universal.services.preparation_interventions import write_intervention_record, read_intervention_record
        diagnosis = self.root / 'diagnosis.txt'
        diagnosis.write_text('Receptor preparation failure category: Explicit alternate-location selection required\n')
        self.source.write_text('END\n')
        path = self.receptor / 'preparation_intervention.json'
        write_intervention_record(diagnosis, self.source, path)
        self.assertEqual(read_intervention_record(path)['diagnosis_code'], 'alternate_conformation')
        self.assertEqual(self.guidance()['diagnosis_code'], 'alternate_conformation')

    def test_another_unsupported_element_is_named_without_claiming_cobalt_compatibility(self):
        self.write_record('preparation_intervention.json', {
            'category': 'Unsupported element in receptor preparation',
            'detected_detail': "RuntimeError: Element Se doesn't have an implemented covalent radius"})
        result = self.guidance()
        self.assertEqual(result['diagnosis_code'], 'unsupported_element')
        self.assertIn('selenium', result['summary'])
        self.assertIsNone(result['recommended_backend'])
        self.assertIn('no verified alternative', result['next_step'].lower())

    def test_unknown_failure_retains_raw_evidence_and_does_not_invent_a_fix(self):
        (self.receptor / 'receptor_backend.log').write_text('UnexpectedWidgetError: synthetic failure 729\n')
        result = self.guidance()
        self.assertEqual(result['diagnosis_code'], 'unclassified')
        self.assertIn('No verified workaround', result['next_step'])
        self.assertIn('UnexpectedWidgetError', result['details'])
        self.assertIsNone(result['recommended_backend'])

    def test_predictor_startup_failure_does_not_reuse_old_receptor_errors(self):
        self.cobalt()
        self.state.workflow_data['study_setup']['preparation_backend'] = 'auto'
        self.state.jobs[-1].error = 'ERROR: P2Rank launcher not found'
        result = self.guidance()
        self.assertEqual(result['diagnosis_code'], 'pocket_runtime')
        self.assertIn('pocket-prediction', result['summary'])
        self.assertIsNone(result['recommended_backend'])
        self.assertEqual(result['last_backend'], 'meeko')
        self.assertNotIn('rejected element Co', result['details'])


class ReviewedSitePrecompletionTests(unittest.TestCase):
    # Reuse the synthetic coordinate-first fixture without duplicating its tests.
    from tests.test_receptor_model_review import ReviewedModelWorkflowTests as _fixture
    setUp = _fixture.setUp
    wait = _fixture.wait
    explore = _fixture.explore
    approve = _fixture.approve
    ready = _fixture.ready
    payload = _fixture.payload

    def test_site_first_worker_mutation_cannot_publish_a_prepared_model(self):
        state = self.ready()
        payload = self.payload(state)
        self.engine.write_text('#!/bin/sh\nset -eu\nroot=Target_receptor_prep\n'
            'mkdir -p "$root/receptor" "$root/cavity"\ncp "$1" "$root/receptor/Target.pdb"\n'
            'printf "synthetic prepared output\\n" > "$root/receptor/Target.pdbqt"\n'
            'printf "worker finished\\n" > "$root/run.log"\n'
            'printf "REMARK source mutation\\n" >> ' + shlex.quote(str(self.source)) + '\n')
        self.runner.prepare_reviewed_receptor('test', request_id='mutating-site-worker',
            expected_revision=state.revision, model_changes=payload)
        done = self.wait(lambda current: current.workflow_data.get('receptor_parameterization_status') == 'failed')
        self.assertEqual(done.jobs[-1].stage, 'receptor_parameterization')
        self.assertEqual(done.jobs[-1].status.value, 'failed')
        self.assertIn('changed', done.jobs[-1].error)
        self.assertFalse(any(a.kind in {'prepared_receptor', 'prepared_receptor_structure', 'receptor_model_history'}
                             for a in done.artifacts))
        self.assertFalse(any(event.message == 'receptor_parameterization completed' for event in done.events))
        self.assertTrue(Path(done.workflow_data['receptor_parameterization_attempt_root']).is_dir())


if __name__ == '__main__':
    unittest.main()
