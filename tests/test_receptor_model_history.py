import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from docking_universal.services.receptor_model_history import normalize_preparation, attach_retained_history, SCHEMA
from docking_universal.services.protocol_import import inspect_protocol_bundle
from docking_universal_bundle import create_bundle, extract_bundle, build_receptor_modification_warning

ROOT = Path(__file__).resolve().parents[1]
def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'libexec' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
REPORT = load('model_history_pdf', 'docking-universal-pdf-report.py')
RUN = load('model_history_run', 'docking-universal-run.py')

def note_text(note):
    return '\n'.join(item.getPlainText() for group in note
                     for item in getattr(group, '_content', [group])
                     if hasattr(item, 'getPlainText'))


class ReceptorModelHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.receptor = self.root / 'receptor.pdbqt'
        self.receptor.write_text('ATOM\n')
        self.digest = hashlib.sha256(self.receptor.read_bytes()).hexdigest()
        self.history = {'schema_name': SCHEMA, 'schema_version': 1,
            'original_input_sha256': 'a' * 64, 'model_input_sha256': 'b' * 64,
            'prepared_receptor_sha256': self.digest,
            'changes': [{'kind': 'sidechain_reconstruction', 'description': 'Rebuilt three GLU A75 side-chain atoms.',
                         'actor': 'reviewer', 'rationale': 'Approved isolated exploratory repair', 'modeled_heavy_atoms': 3}]}

    def preparation(self):
        return {'model_change_history': copy.deepcopy(self.history)}

    def test_warning_is_derived_without_legacy_removal_flag(self):
        record = normalize_preparation(self.preparation(), self.digest)
        self.assertEqual(record['receptor_modification_warning']['code'], 'reviewed-receptor-model-changes')
        self.assertIn('GLU A75', RUN.removal_warning_from_preparation(record))
        self.assertNotIn('user_approved_component_removal', record)

    def test_normalization_is_idempotent_and_preserves_old_high_severity(self):
        record = self.preparation()
        record['receptor_modification_warning'] = build_receptor_modification_warning([{'residue_name': 'LYS'}])
        result = normalize_preparation(record)
        self.assertEqual(result, normalize_preparation(result))
        self.assertEqual(result['receptor_modification_warning']['severity'], 'high')
        self.assertEqual(result['receptor_modification_warning']['removed_standard_amino_acid_count'], 1)
        self.assertIn('standard amino-acid', result['receptor_modification_warning']['summary'])
        self.assertNotIn('receptor_modification_warning', self.preparation())

    def test_wrong_receptor_or_incomplete_approval_rejected(self):
        with self.assertRaisesRegex(ValueError, 'different prepared receptor'):
            normalize_preparation(self.preparation(), '0' * 64)
        for key in ('actor', 'rationale', 'description'):
            record = self.preparation()
            record['model_change_history']['changes'][0][key] = ''
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, 'approval actor'):
                normalize_preparation(record)

    def test_unknown_change_types_and_invalid_counts_fail_closed(self):
        for edit in ({'kind': 'fill_missing_loops'}, {'modeled_heavy_atoms': -1}, {'modeled_heavy_atoms': True}):
            record = self.preparation()
            record['model_change_history']['changes'][0].update(edit)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                normalize_preparation(record)

    def test_standard_exclusion_and_unspecified_manual_edit_stay_high_severity(self):
        for kind, count in (('component_exclusion', 1), ('manual_receptor_edit', 0), ('partial_residue_reconstruction', 0)):
            record = self.preparation()
            record['model_change_history']['changes'][0].update(kind=kind, removed_standard_amino_acids=count)
            self.assertEqual(normalize_preparation(record)['receptor_modification_warning']['severity'], 'high')

    def test_preparation_history_is_bound_to_actual_pdbqt(self):
        folder = self.root / 'preparation/receptor'
        folder.mkdir(parents=True)
        (folder / 'receptor_model_history.json').write_text(json.dumps(self.history))
        self.assertIn('receptor_modification_warning', attach_retained_history({}, folder.parent, self.receptor))
        self.receptor.write_text('CHANGED\n')
        with self.assertRaisesRegex(ValueError, 'different prepared receptor'):
            attach_retained_history({}, folder.parent, self.receptor)

    def test_bundle_and_import_preview_keep_inline_history_without_original_folder(self):
        box = self.root / 'box.conf'
        box.write_text('center_x = 0\ncenter_y = 0\ncenter_z = 0\nsize_x = 26\nsize_y = 26\nsize_z = 26\n')
        protocol = {'schema_name': 'docking-universal-protocol', 'schema_version': 1,
            'engine': 'vina', 'protocol_type': 'site-guided-exploratory',
            'exploratory_screening_allowed': True, 'screening_authority': 'user-confirmed-exploratory-use',
            'parameters': {'conformers_per_state': 1, 'seeds': [11]},
            'locked_inputs': {'receptor': str(self.receptor), 'box': str(box),
                              'receptor_sha256': self.digest, 'box_sha256': hashlib.sha256(box.read_bytes()).hexdigest()},
            'receptor_preparation': self.preparation()}
        path = self.root / 'protocol.json'
        path.write_text(json.dumps(protocol))
        bundle = self.root / 'model-change.duprotocol'
        create_bundle(path, self.root, bundle)
        self.receptor.unlink()  # Only synthetic fixture input; prove portability.
        box.unlink()
        preview = inspect_protocol_bundle(bundle)
        self.assertIn('GLU A75', preview['receptor_modification_warning']['summary'])
        extracted = extract_bundle(bundle)
        retained = json.loads(extracted.read_text())['receptor_preparation']
        self.assertEqual(retained['model_change_history'], self.history)
        self.assertTrue((extracted.parent / retained['model_change_history_record']).is_file())
        self.assertIn('GLU A75', RUN.removal_warning_from_preparation(retained))

    def test_screening_report_uses_inline_preparation_when_original_protocol_is_absent(self):
        (self.root / 'report').mkdir()
        (self.root / 'report/study_summary.json').write_text(json.dumps({'protocol_receptor_preparation': self.preparation()}))
        record = REPORT.receptor_preparation_record(self.root)
        self.assertIn('GLU A75', record['receptor_modification_warning']['summary'])
        from reportlab.lib.styles import getSampleStyleSheet
        note = REPORT.user_approved_removal_report_note(record, self.root, getSampleStyleSheet())
        self.assertTrue(note)
        self.assertIn('GLU A75', note_text(note))
        self.assertNotIn('safe preparation fallbacks failed', note_text(note))

    def test_report_escapes_user_descriptions(self):
        record = self.preparation()
        record['model_change_history']['changes'][0]['description'] = 'User <edited> receptor & retained warning.'
        from reportlab.lib.styles import getSampleStyleSheet
        note = REPORT.user_approved_removal_report_note(record, self.root, getSampleStyleSheet())
        self.assertIn('User <edited> receptor & retained warning.', note_text(note))

    def test_all_engine_records_keep_the_same_model_change_warning(self):
        for engine in ('vina', 'qvinaw', 'adgpu'):
            with self.subTest(engine=engine):
                self.assertIn('GLU A75', RUN.protocol_removal_warning({
                    'engine': engine, 'receptor_preparation': self.preparation()}))

    def test_report_summary_is_compact_without_discarding_full_inventory(self):
        record = self.preparation()
        change = record['model_change_history']['changes'][0]
        change['description'] = 'Detailed observed repair ' * 100
        record['model_change_history']['changes'] = [copy.deepcopy(change) for _ in range(50)]
        result = normalize_preparation(record)
        self.assertLess(len(result['receptor_modification_warning']['summary']), 1000)
        self.assertEqual(len(result['model_change_history']['changes']), 50)


if __name__ == '__main__':
    unittest.main()
