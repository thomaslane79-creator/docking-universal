import tempfile
from pathlib import Path
import unittest
from docking_universal.services.reviewed_exclusions import create_reviewed_exclusion, sha256


class ReviewedExclusionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = self.root / 'receptor.pdb'
        self.source.write_text(
            'ATOM      1  CA  GLU A  75       1.000   2.000   3.000  1.00 20.00           C\n'
            'HETATM    2  C1  NAG A   1       4.000   2.000   3.000  1.00 20.00           C\n'
            'HETATM    3  C1  NAG B   1       8.000   2.000   3.000  1.00 20.00           C\n'
            'CONECT    1    2    3\nCONECT    2    1\nEND\n')
        self.hash = sha256(self.source)

    def make(self, residues, **kwargs):
        return create_reviewed_exclusion(self.source, self.root / 'new', residues,
            reviewed_source_sha256=kwargs.get('hash', self.hash), actor=kwargs.get('actor', 'reviewer'),
            rationale='Approved isolated exploratory test')

    def test_exact_exclusion_preserves_other_atoms_and_prunes_only_incident_connections(self):
        record = self.make([('NAG', 'A', '1', '')])
        self.assertEqual(sha256(self.source), self.hash)
        result = Path(record['derivative']).read_text()
        self.assertIn('NAG B   1', result)
        self.assertNotIn('NAG A   1', result)
        self.assertIn('CONECT    1    3', result)
        self.assertNotIn('CONECT    2', result)
        self.assertEqual(record['excluded_atom_count'], 1)
        self.assertTrue(record['remaining_atom_records_unchanged'])
        self.assertFalse(record['docking_ready'])

    def test_standard_residue_override_is_allowed_but_remains_high_severity(self):
        record = self.make([('GLU', 'A', '75', '')])
        self.assertEqual(record['receptor_modification_warning']['severity'], 'high')
        self.assertEqual(record['receptor_modification_warning']['standard_amino_acids_excluded'], 1)

    def test_wrong_identity_or_missing_approval_does_not_create_output(self):
        for residues, kwargs in [([('NAG', 'X', '1', '')], {}),
                                 ([('FUC', 'A', '1', '')], {}),
                                 ([('NAG', 'A', '1', '')], {'actor': ''}),
                                 ([('NAG', 'A', '1', '')], {'hash': '0' * 64})]:
            with self.subTest(residues=residues, kwargs=kwargs), self.assertRaises(ValueError):
                self.make(residues, **kwargs)
            self.assertFalse((self.root / 'new').exists())

    def test_existing_output_never_overwritten(self):
        self.make([('NAG', 'A', '1', '')])
        with self.assertRaisesRegex(ValueError, 'new output'):
            self.make([('NAG', 'B', '1', '')])

    def test_link_to_removed_sugar_is_recorded_not_silently_retained(self):
        self.source.write_text('LINK         CA  GLU A  75                 C1  NAG A   1\n' + self.source.read_text())
        self.hash = sha256(self.source)
        record = self.make([('NAG', 'A', '1', '')])
        self.assertFalse(any(line.startswith('LINK') for line in Path(record['derivative']).read_text().splitlines()))
        self.assertTrue(any(row['original'].startswith('LINK') for row in record['changed_connection_records']))


if __name__ == '__main__':
    unittest.main()
