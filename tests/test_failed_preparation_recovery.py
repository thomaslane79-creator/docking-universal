"""Failed-control recovery uses synthetic workers; no scientific calculation runs."""
import copy
import json
import os
from pathlib import Path
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

    def test_backend_only_retry_and_invalid_backend_payload_are_not_model_approval(self):
        preview = self.preview({'preparation_backend': 'adfr'})
        self.assertEqual(preview['changes'], [])
        response = self.dispatch('prepare_receptor_changes', self.payload(preview), self.failed.revision, 'backend-only')
        self.assertEqual(response.status, 'rejected')
        self.assertIn('No molecular changes', response.error)
        response = self.dispatch('preview_receptor_changes', {'choices': {'preparation_backend': {'arbitrary': 'command'}}},
                                 self.failed.revision, 'invalid-backend')
        self.assertEqual(response.status, 'rejected')
        self.assertFalse((self.root / 'run/preparation/.docking-universal-reviewed-models').exists())
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

    def test_stale_revision_and_parallel_worker_are_rejected(self):
        payload = self.payload()
        response = self.dispatch('prepare_receptor_changes', payload, self.failed.revision - 1, 'stale')
        self.assertEqual(response.status, 'rejected')
        self.engine.write_text('#!/bin/sh\nsleep .3\nmkdir -p Target_receptor_prep/receptor\n'
            'printf "reviewed attempt failed\\n" > Target_receptor_prep/run.log\nexit 1\n')
        response = self.dispatch('prepare_receptor_changes', payload, self.failed.revision, 'first-worker')
        self.assertEqual(response.status, 'applied', response.error)
        running = self.store.load('test')
        rejected = self.dispatch('preview_receptor_changes', {'choices': payload['choices']}, running.revision, 'parallel')
        self.assertEqual(rejected.status, 'rejected')
        self.assertIn('active stage', rejected.error)
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


if __name__ == '__main__':
    unittest.main()
