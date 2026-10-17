import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from docking_universal.application import StudyController
from docking_universal.host import CommandDispatcher
from docking_universal.models import ScientificAuthority, Job, JobStatus
from docking_universal.services.protocol_import import inspect_protocol_bundle, import_protocol_bundle
from docking_universal.state import JsonStudyStore, RevisionConflictError
from docking_universal.viewer.messages import Command
from docking_universal_bundle import create_bundle


class ProtocolImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = JsonStudyStore(self.root / 'studies')
        self.controller = StudyController(self.store)
        self.state = self.controller.create_study('fresh', 'Fresh import')
        receptor, box = self.root / 'receptor.pdbqt', self.root / 'box.conf'
        receptor.write_text('RECEPTOR\n')
        box.write_text('center_x = 1\ncenter_y = 2\ncenter_z = 3\nsize_x = 20\nsize_y = 20\nsize_z = 20\n')
        digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
        protocol = self.root / 'protocol.json'
        protocol.write_text(json.dumps({
            'schema_name': 'docking-universal-protocol', 'schema_version': 1,
            'protocol_type': 'site-guided-exploratory',
            'screening_authority': 'user-confirmed-exploratory-use', 'exploratory_screening_allowed': True,
            'target': 'Test target', 'engine': 'vina',
            'parameters': {'conformers_per_state': 3, 'seeds': [11, 12], 'exhaustiveness': 16},
            'locked_inputs': {'receptor': str(receptor), 'receptor_sha256': digest(receptor),
                              'box': str(box), 'box_sha256': digest(box),
                              'boxes': [{'site_number': 1, 'box': str(box), 'box_sha256': digest(box)}]},
        }))
        self.bundle = create_bundle(protocol, self.root, self.root / 'saved.duprotocol')
        self.preview = inspect_protocol_bundle(self.bundle)

    def tearDown(self):
        self.tmp.cleanup()

    def do_import(self, **kwargs):
        return import_protocol_bundle(self.controller, 'fresh', self.bundle, self.preview['sha256'],
                                      expected_revision=kwargs.get('revision', self.state.revision),
                                      request_id=kwargs.get('request_id', 'import-one'))

    def rewrite(self, update, rehash=True, extra=None):
        with zipfile.ZipFile(self.bundle) as z:
            files = {name: z.read(name) for name in z.namelist()}
        manifest = json.loads(files['bundle_manifest.json'])
        record = json.loads(files[manifest['protocol']])
        update(record)
        files[manifest['protocol']] = json.dumps(record).encode()
        if rehash:
            for item in manifest['files']:
                item['sha256'] = hashlib.sha256(files[item['path']]).hexdigest()
            files['bundle_manifest.json'] = json.dumps(manifest).encode()
        if extra:
            files.update(extra)
        with zipfile.ZipFile(self.bundle, 'w') as z:
            for name, value in files.items():
                z.writestr(name, value)

    def test_preview_is_readonly_and_import_snapshots_without_jobs_or_decisions(self):
        before = self.store.path_for('fresh').read_bytes()
        self.assertEqual(self.preview['engine'], 'vina')
        self.assertEqual(self.store.path_for('fresh').read_bytes(), before)
        result = self.do_import()
        self.assertFalse(result.jobs)
        self.assertFalse(result.decisions)
        self.assertFalse(result.selected_pocket_ids)
        self.assertEqual(result.scientific_authority, ScientificAuthority.EXPLORATORY_NO_CONTROL)
        self.assertEqual(result.workflow_data['next_stage'], 'screening')
        snapshot = Path(result.artifacts[0].path)
        self.bundle.unlink()
        retained = inspect_protocol_bundle(snapshot)
        self.assertEqual(retained['parameters'], self.preview['parameters'])
        self.assertEqual(retained['sha256'], self.preview['sha256'])
        self.assertEqual(self.store.load('fresh').artifacts[0], result.artifacts[0])

    def test_idempotent_request_and_second_import_rejected(self):
        result = self.do_import()
        self.assertEqual(self.do_import().revision, result.revision)
        with self.assertRaisesRegex(ValueError, 'fresh study'):
            self.do_import(revision=result.revision, request_id='second')

    def test_stale_revision_creates_no_snapshot(self):
        with self.assertRaises(RevisionConflictError):
            self.do_import(revision=self.state.revision + 1)
        self.assertFalse((self.store.path_for('fresh').parent / 'inputs').exists())

    def test_changed_after_review_rejected(self):
        self.rewrite(lambda record: record['parameters'].update(exhaustiveness=32))
        with self.assertRaisesRegex(ValueError, 'changed after review'):
            self.do_import()
        self.assertFalse(self.store.load('fresh').artifacts)

    def test_modified_inventory_file_rejected(self):
        self.rewrite(lambda record: record.update(target='Changed'), rehash=False)
        with self.assertRaisesRegex(ValueError, 'failed verification'):
            inspect_protocol_bundle(self.bundle)

    def test_receptor_hash_mismatch_rejected_even_with_valid_archive_inventory(self):
        self.rewrite(lambda record: record['locked_inputs'].update(receptor_sha256='0' * 64))
        with self.assertRaisesRegex(ValueError, 'Locked receptor'):
            inspect_protocol_bundle(self.bundle)

    def test_traversal_and_unlisted_files_rejected(self):
        self.rewrite(lambda record: None, extra={'../escape': b'no'})
        with self.assertRaisesRegex(ValueError, 'Unsafe path'):
            inspect_protocol_bundle(self.bundle)

    def test_unauthorized_protocol_rejected(self):
        self.rewrite(lambda record: record.update(exploratory_screening_allowed=False))
        with self.assertRaisesRegex(ValueError, 'not authorized'):
            inspect_protocol_bundle(self.bundle)

    def test_control_authority_is_preserved_not_created_by_import(self):
        self.rewrite(lambda record: record.update(protocol_type='control-validated',
                     unknown_docking_allowed=True, control_status='approved'))
        self.preview = inspect_protocol_bundle(self.bundle)
        self.assertFalse(self.preview['exploratory_authorization_required'])
        self.assertEqual(self.do_import().scientific_authority, ScientificAuthority.CONTROL_APPROVED)

    def test_host_inspection_import_replay_and_global_active_guard(self):
        dispatcher = CommandDispatcher(self.controller, session_id='session')
        def command(operation, payload, request='request', revision=None):
            return dispatcher.dispatch(Command('fresh', 'session', request, operation, payload, revision))
        preview = command('inspect_protocol_bundle', {'protocol_bundle': str(self.bundle)})
        self.assertEqual(preview.status, 'applied')
        payload = {'protocol_bundle': str(self.bundle), 'reviewed_sha256': self.preview['sha256']}
        overridden = command('import_protocol_bundle', {**payload, 'engine': 'adgpu'}, 'override', self.state.revision)
        self.assertEqual(overridden.status, 'rejected')
        self.assertIn('overrides', overridden.error)
        self.assertEqual(command('import_protocol_bundle', payload, 'missing-revision').status, 'rejected')
        other = self.controller.create_study('other', 'Active elsewhere')
        other.jobs.append(Job('active', 'screening', JobStatus.RUNNING))
        self.store.save(other)
        rejected = command('import_protocol_bundle', payload, 'busy', self.state.revision)
        self.assertEqual(rejected.status, 'rejected')
        self.assertIn('active', rejected.error)
        other.jobs.clear()
        self.store.save(other)
        applied = command('import_protocol_bundle', payload, 'import', self.state.revision)
        self.assertEqual(applied.status, 'applied', applied.error)
        self.assertEqual(command('import_protocol_bundle', payload, 'import', self.state.revision).status, 'replayed')

    def test_unlisted_entry_rejected(self):
        self.rewrite(lambda record: None, extra={'unexpected.txt': b'no'})
        with self.assertRaisesRegex(ValueError, 'without a verified inventory'):
            inspect_protocol_bundle(self.bundle)

    def test_damaged_snapshot_blocks_reuse_without_replacing_it(self):
        result = self.do_import()
        snapshot = Path(result.artifacts[0].path)
        snapshot.write_bytes(b'changed')
        from docking_universal.services.screening import build_screening_plan
        with self.assertRaisesRegex(ValueError, 'changed'):
            build_screening_plan(snapshot, self.root / 'unused.sdf', expected_protocol_sha256=self.preview['sha256'])


if __name__ == '__main__':
    unittest.main()
