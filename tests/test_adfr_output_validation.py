"""Independent legacy-export validation; fixtures never assert charge accuracy."""
import json
from pathlib import Path
import tempfile
import unittest

from docking_universal.services.preparation_atom_inventory import audit_adfr_receptor_output


def atom(serial, name, element, *, chain='A', residue='ALA', number=10,
         insertion='', xyz=(1, 2, 3), pdbqt_type=None, charge=0.123):
    prefix = (f'ATOM  {serial:5d} {name:>4} {residue:>3} {chain:1}{number:4d}{insertion:1}   '
              f'{xyz[0]:8.3f}{xyz[1]:8.3f}{xyz[2]:8.3f}  1.00 20.00')
    if pdbqt_type is None:
        return prefix + f'          {element:>2}\n'
    return prefix + f'    {charge:6.3f} {pdbqt_type}\n'


class AdfrOutputValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'source.pdb'
        self.output = self.root / 'export.pdbqt'
        self.log = self.root / 'backend.log'
        self.audit = self.root / 'audit' / 'adfr.json'
        self.rows = [(1, 'CA', 'C', {}),
                     (2, 'CO', 'Co', {'residue': 'COH', 'number': 602}),
                     (3, 'CO', 'Co', {'chain': 'B', 'residue': 'COH', 'number': 603}),
                     (4, 'O6', 'O', {'chain': 'C', 'residue': 'NAG', 'number': 1}),
                     (5, 'H1', 'H', {})]
        self.source.write_text(''.join(atom(i, n, e, **options) for i, n, e, options in self.rows))
        self.output_rows = [atom(i + 100, n, e, pdbqt_type={'C': 'C', 'Co': 'Co', 'O': 'OA'}[e],
                                 **options) for i, n, e, options in self.rows if e != 'H']
        self.output.write_text(''.join(self.output_rows))
        self.log.write_text('Unable to assign MAP type to atom Co\n' * 2)

    def check(self):
        return audit_adfr_receptor_output(self.source, self.output, self.log, self.audit)

    def test_accepts_retained_cobalt_glycan_and_hydrogen_merging_without_accuracy_claim(self):
        before = self.source.read_bytes()
        result = self.check()
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['source_heavy_atom_count'], 4)
        self.assertEqual(result['output_heavy_atom_count'], 4)
        self.assertEqual(result['scope'], 'atom_retention_and_parameter_completeness_not_accuracy')
        self.assertEqual(result['missing_charge_parameters'], [])
        self.assertEqual(json.loads(self.audit.read_text()), result)
        self.assertEqual(self.source.read_bytes(), before)

    def test_zero_charge_alone_is_not_a_missing_parameter_diagnosis(self):
        self.output.write_text(''.join(line[:70] + ' 0.000' + line[76:] for line in self.output_rows))
        result = self.check()
        self.assertEqual(result['status'], 'accepted')
        self.assertEqual(result['output_total_charge'], 0)

    def test_zero_exit_missing_gasteiger_warning_rejects_otherwise_complete_output(self):
        warning = 'Sorry, there are no Gasteiger parameters available for atom target:B:NAG607:O6'
        self.log.write_text(self.log.read_text() + warning + '\n')
        result = self.check()
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['missing_charge_parameters'], [warning])
        self.assertIn('ADFR reported missing Gasteiger parameters', result['reasons'])
        self.assertEqual(result['missing_heavy_atoms'], [])

    def test_retained_nonstandard_component_cannot_disappear(self):
        self.output.write_text(''.join(self.output_rows[:-1]))
        result = self.check()
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['missing_heavy_atoms'], [dict(chain='C', number='1',
            insertion_code='', resname='NAG', atom_name='O6')])
        self.assertIn('Output dropped 1 source heavy atom(s)', result['reasons'])

    def test_each_identity_field_is_exact(self):
        replacements = [(12, 16, '  O5'), (17, 20, 'MAN'), (21, 22, 'D'),
                        (22, 26, '   2'), (26, 27, 'A')]
        for start, stop, value in replacements:
            with self.subTest(field=(start, stop)):
                changed = self.output_rows[-1]
                changed = changed[:start] + value + changed[stop:]
                self.output.write_text(''.join(self.output_rows[:-1]) + changed)
                result = self.check()
                self.assertEqual(result['status'], 'rejected')
                self.assertEqual(len(result['missing_heavy_atoms']), 1)
                self.assertEqual(len(result['extra_heavy_atoms']), 1)

    def test_duplicate_source_or_export_heavy_atoms_require_review(self):
        originals = self.source.read_text(), self.output.read_text()
        self.source.write_text(originals[0] + originals[0].splitlines(keepends=True)[0])
        result = self.check()
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(len(result['duplicate_source_heavy_atoms']), 1)
        self.source.write_text(originals[0])
        self.output.write_text(originals[1] + self.output_rows[0])
        result = self.check()
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(len(result['duplicate_output_heavy_atoms']), 1)

    def test_changed_element_and_one_pdb_unit_movement_are_rejected(self):
        self.output.write_text(self.output_rows[0].rstrip()[:-1] + 'N\n' + ''.join(self.output_rows[1:]))
        result = self.check()
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(len(result['element_mismatches']), 1)
        self.output.write_text(self.output_rows[0][:30] + '   1.001' + self.output_rows[0][38:]
                               + ''.join(self.output_rows[1:]))
        result = self.check()
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(len(result['coordinate_mismatches']), 1)

    def test_unknown_types_and_missing_or_nonfinite_charge_are_rejected(self):
        for value in ('', 'XX', 'CO', 'G0', 'W'):
            with self.subTest(atom_type=value):
                self.output.write_text(self.output_rows[0][:77] + value + '\n' + ''.join(self.output_rows[1:]))
                result = self.check()
                self.assertEqual(result['status'], 'rejected')
                self.assertIn('unknown or missing Vina atom type', result['invalid_output_records'][0]['problems'])
        for value in ('      ', '   nan', '   inf', ' -inf ', 'bad!!!'):
            with self.subTest(charge=value):
                self.output.write_text(self.output_rows[0][:70] + value + self.output_rows[0][76:]
                                       + ''.join(self.output_rows[1:]))
                result = self.check()
                self.assertEqual(result['status'], 'rejected')
                self.assertIsNone(result['output_total_charge'])
                self.assertIn('missing, malformed or nonfinite partial charge',
                              result['invalid_output_records'][0]['problems'])

    def test_added_hydrogens_allowed_but_still_need_finite_charge_and_coordinates(self):
        added = atom(900, 'H2', 'H', pdbqt_type='HD')
        self.output.write_text(''.join(self.output_rows) + added)
        self.assertEqual(self.check()['status'], 'accepted')
        self.output.write_text(''.join(self.output_rows) + added[:30] + '     nan' + added[38:])
        result = self.check()
        self.assertEqual(result['status'], 'rejected')
        self.assertTrue(result['invalid_output_records'])

    def test_nonfinite_source_and_overflowed_total_still_write_json_audit(self):
        original = self.source.read_text()
        self.source.write_text(original[:30] + '     inf' + original[38:])
        result = self.check()
        self.assertEqual(result['status'], 'rejected')
        self.assertTrue(result['invalid_source_records'])
        self.source.write_text(original)
        self.output.write_text(''.join(line[:70] + ' 1e308' + line[76:] for line in self.output_rows))
        result = self.check()
        self.assertEqual(result['status'], 'rejected')
        self.assertIn('Output has a nonfinite total charge', result['reasons'])
        self.assertIsNone(result['output_total_charge'])
        self.assertEqual(json.loads(self.audit.read_text()), result)

    def test_unreadable_or_empty_artifacts_retain_rejected_audit(self):
        self.output.unlink()
        result = self.check()
        self.assertEqual(result['status'], 'rejected')
        self.assertEqual(result['unreadable_files'][0]['file'], 'output')
        self.assertIsNone(result['output_sha256'])
        self.assertTrue(self.audit.is_file())
        self.output.write_text('REMARK no atoms\n')
        self.assertIn('Output contains no heavy atoms', self.check()['reasons'])
        self.output.write_text(''.join(self.output_rows))
        self.log.unlink()
        self.assertEqual(self.check()['unreadable_files'][0]['file'], 'backend_log')

    def test_missing_source_element_uses_pdb_alignment_without_confusing_ca_with_calcium(self):
        lines = self.source.read_text().splitlines(keepends=True)
        lines[0] = lines[0][:76] + '  \n'
        self.source.write_text(''.join(lines))
        self.assertEqual(self.check()['status'], 'accepted')


if __name__ == '__main__':
    unittest.main()
