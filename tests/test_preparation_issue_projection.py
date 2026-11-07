"""Exact omission warnings must survive a review performed before boxes exist."""

import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from docking_universal.services.preparation_site_issues import (
    backend_residue_ids, candidate_with_model_change_review, collect_site_issues,
)
from docking_universal.services.receptor_model_history import SCHEMA
from docking_universal.services.receptor_model_review import preview_changes, write_model


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atom(serial, name, resname, chain, number, x, element, icode=''):
    return (f'HETATM{serial:5d} {name:>4} {resname:>3} {chain:1}{number:4d}{icode:1}   '
            f'{x:8.3f}{0:8.3f}{0:8.3f}{1:6.2f}{20:6.2f}          {element:>2}\n')


class LaterBoxProjectionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'source.pdb'
        self.source.write_text(atom(1, 'CA', 'ALA', 'A', 1, 0, 'C').replace('HETATM', 'ATOM  ')
                               + atom(2, 'C1', 'NAG', 'B', 200, 1, 'C', 'A')
                               + atom(3, 'CO', 'COH', 'A', 602, 14, 'Co') + 'END\n')
        choices = {'exclusions': [{'resname': 'NAG', 'chain': 'B', 'number': '200', 'insertion_code': 'A'}]}
        preview, derivative = preview_changes(self.source, choices,
            context={'original_input_sha256': digest(self.source), 'selected_regions': []})
        preview.update(source_path=str(self.source), selected_box_review=[], box_review_pending=True)
        model, self.review = write_model(self.root / 'review', 'source.pdb', preview, derivative,
                                         actor='scientist', rationale='Exact synthetic omission test')
        self.record = self.root / 'review/reviewed_model.json'
        self.prepared = self.root / 'prepared.pdbqt'
        self.prepared.write_bytes(derivative)
        self.history = self.root / 'history.json'
        self.history.write_text(json.dumps({'schema_name': SCHEMA, 'schema_version': 1,
            'original_input_sha256': digest(self.source), 'model_input_sha256': digest(model),
            'prepared_receptor_sha256': digest(self.prepared), 'review_record_sha256': digest(self.record),
            'changes': [dict(change, actor='scientist', rationale='Exact synthetic omission test')
                        for change in self.review['changes']]}))
        self.box = self.root / 'later.conf'
        self.set_box(0)
        self.state = SimpleNamespace(artifacts=[
            self.artifact('history', 'receptor_model_history', self.history),
            self.artifact('prepared', 'prepared_receptor', self.prepared),
            self.artifact('review', 'reviewed_receptor_model', self.record),
            self.artifact('box', 'docking_box', self.box),
        ])
        self.candidate = {'id': 'pocket', 'box_artifact_id': 'box', 'evidence': {}}

    def artifact(self, identity, kind, path):
        return SimpleNamespace(id=identity, kind=kind, path=str(path), sha256=digest(path))

    def set_box(self, center):
        self.box.write_text(''.join(f'center_{axis} = {center if axis == "x" else 0}\nsize_{axis} = 4\n'
                                   for axis in 'xyz'))

    def shown(self):
        return candidate_with_model_change_review(self.state, self.candidate)['evidence']['receptor_model_review']

    def test_prebox_exclusion_is_located_and_warns_inside_the_generated_box(self):
        shown = self.shown()
        self.assertEqual(shown['status'], 'prepared_with_reviewed_model_changes')
        self.assertTrue(shown['changes_inside_box'])
        self.assertEqual(shown['severity'], 'high')
        self.assertEqual(shown['residues'][0]['number'], '200A')
        self.assertIn('NAG B:200A', shown['warning'])
        self.assertIn('inside this box', shown['warning'])
        self.assertNotIn('receptor_model_review', self.candidate['evidence'])
        self.assertIn('COH', self.prepared.read_text())

    def test_later_box_outside_the_omission_keeps_warning_and_actual_distance(self):
        self.set_box(100)
        self.state.artifacts[-1].sha256 = digest(self.box)
        shown = self.shown()
        self.assertFalse(shown['changes_inside_box'])
        self.assertEqual(shown['residues'][0]['minimum_distance_to_box_angstrom'], 97)
        self.assertTrue(shown['persistent_warning_required'])
        self.assertFalse(shown['distance_is_permission_to_ignore'])

    def test_tampered_source_does_not_claim_the_box_is_unaffected(self):
        self.source.write_text(self.source.read_text().replace('   1.000', ' 100.000'))
        shown = self.shown()
        self.assertEqual(shown['status'], 'model_change_evidence_unverified')
        self.assertEqual(shown['severity'], 'high')

    def test_tampered_box_is_a_visible_evidence_failure(self):
        self.set_box(100)
        self.assertEqual(self.shown()['status'], 'model_change_evidence_unverified')

    def test_missing_approval_record_does_not_claim_the_box_is_unaffected(self):
        self.state.artifacts = [a for a in self.state.artifacts if a.kind != 'reviewed_receptor_model']
        shown = self.shown()
        self.assertEqual(shown['status'], 'model_change_evidence_unverified')
        self.assertEqual(shown['severity'], 'high')
        self.assertNotIn('changes_inside_box', shown)

    def test_box_specific_omission_warning_survives_bundle_export_and_reopen(self):
        from docking_universal_bundle import SITE_GUIDED_EXPLORATORY, create_bundle, extract_bundle
        impact = self.shown()
        region = {'box_label': 'L1', 'box': str(self.box), 'box_sha256': digest(self.box),
                  'receptor_model_review': impact}
        record = {'schema_name': 'docking-universal-protocol', 'schema_version': 1,
                  'protocol_type': SITE_GUIDED_EXPLORATORY, 'control_status': 'not_performed',
                  'unknown_docking_allowed': False, 'exploratory_screening_allowed': True,
                  'screening_authority': 'user-confirmed-exploratory-use',
                  'locked_inputs': {'receptor': str(self.prepared), 'receptor_pdb': str(self.prepared),
                                    'box': str(self.box), 'boxes': [region]},
                  'docking_regions': [region],
                  'receptor_preparation': {'model_change_history': json.loads(self.history.read_text())}}
        protocol = self.root / 'protocol.json'
        protocol.write_text(json.dumps(record))
        bundle = self.root / 'reviewed.duprotocol'
        create_bundle(protocol, self.root, bundle)
        reopened = json.loads(extract_bundle(bundle).read_text())
        self.assertEqual(reopened['docking_regions'][0]['receptor_model_review'], impact)
        self.assertTrue(reopened['receptor_preparation']['receptor_modification_warning']['persistent_warning_required'])


class LegacyIssueLocationTests(unittest.TestCase):
    def test_gasteiger_diagnostic_retains_exact_chain_and_insertion_code(self):
        text = ('Sorry, there are no Gasteiger parameters available for atom target:B:NAG607:O6\n'
                'Sorry, there are no Gasteiger parameters available for atom target:C:NAG-2A:O4\n'
                '/tmp/target:D:NAG333:O4\n')
        self.assertEqual(backend_residue_ids(text), {('B', '607'), ('C', '-2A')})

    def test_element_error_locates_the_whole_retained_component(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'receptor').mkdir()
            source = root / 'source.pdb'
            source.write_text(atom(1, 'CO', 'COH', 'A', 602, 0, 'Co')
                              + atom(2, 'NA', 'COH', 'A', 602, 1, 'N')
                              + atom(3, 'C1', 'NAG', 'B', 607, 2, 'C'))
            (root / 'receptor/receptor_backend.log').write_text(
                "RuntimeError: Element Co doesn't have an implemented covalent radius\n")
            (root / 'receptor/receptor_adfr_fallback.log').write_text(
                'Sorry, there are no Gasteiger parameters available for atom target:B:NAG607:O6\n')
            record = collect_site_issues(root, source)
            rows = {(row['chain'], row['number']): row for row in record['residues']}
            self.assertEqual(set(rows), {('A', '602'), ('B', '607')})
            self.assertEqual(len(rows[('A', '602')]['coordinates']), 2)
            self.assertFalse(record['automatic_exclusions'])


if __name__ == '__main__':
    unittest.main()
