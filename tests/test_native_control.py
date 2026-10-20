"""Native control orchestration preserves sealed inputs and existing methods."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from docking_universal.native_control import parse_args, run_reviewed_control, selected_ligand_lines


class NativeControlTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'public fixture Ω.pdb'
        self.ligand = 'HETATM    2  C1  LIG A 101       1.000   2.000   3.000  1.00 10.00           C'
        self.source.write_text('ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 10.00           C\n' + self.ligand + '\nEND\n')
        receptor = self.root / 'prepared.pdb'; receptor.write_text(self.source.read_text().splitlines()[0] + '\nEND\n')
        pdbqt = self.root / 'prepared.pdbqt'; pdbqt.write_text('prepared fixture\n')
        box = self.root / 'site.conf'; box.write_text('center_x = 1\ncenter_y = 2\ncenter_z = 3\nsize_x = 26\nsize_y = 26\nsize_z = 26\n')
        def asset(path):
            return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
        record = {'schema_name': 'docking-universal-reviewed-control-inputs', 'schema_version': 1,
            'approval_id': 'explicit-fixture-approval', 'ligand_id': 'LIG:A:101', 'engine': 'vina',
            'assets': {key: asset(value) for key, value in [('source_structure', self.source),
                ('source_pdb', self.source), ('receptor_pdb', receptor), ('receptor_pdbqt', pdbqt), ('box', box)]},
            'tested_box_label': 'B1', 'selected_regions': [{'box_label': 'B1', 'box': str(box),
                'box_sha256': asset(box)['sha256']}], 'preparation_root': str(self.root / 'retained-preparation')}
        self.record = self.root / 'reviewed.json'; self.record.write_text(json.dumps(record))
        self.argv = ['--complex', str(self.source), '--ligand-id', 'LIG:A:101', '--out', str(self.root / 'control'),
            '--reviewed-inputs', str(self.record), '--reviewed-inputs-sha256', hashlib.sha256(self.record.read_bytes()).hexdigest(),
            '--non-interactive', '--no-visuals']

    def test_port_reuses_chemistry_and_calibrator_without_repreparing_or_crystal_pose_seeding(self):
        args = parse_args(self.argv)
        before = self.source.read_bytes()
        calls = []
        with patch.dict(os.environ, {'DOCKING_UNIVERSAL_CLI': str(self.root / 'native.py')}):
            output = run_reviewed_control(args, libexec=self.root / 'libexec', runner=lambda c: calls.append(list(map(str, c))))
        self.assertEqual(self.source.read_bytes(), before)
        self.assertEqual(len(calls), 2)
        self.assertTrue(calls[0][1].endswith('docking-universal-bound-sdf.py'))
        self.assertNotIn('--infer-from-pdb', calls[0]); self.assertNotIn('--force', calls[0])
        calibration = calls[1]
        self.assertTrue(calibration[1].endswith('docking-universal-calibrate.py'))
        self.assertEqual(calibration[calibration.index('--tier') + 1], 'quick')
        self.assertEqual(calibration[calibration.index('--approval-min-seeds') + 1], '5')
        self.assertEqual(calibration[calibration.index('--rmsd-threshold') + 1], '2.0')
        self.assertEqual(calibration[calibration.index('--forcefield') + 1], 'mmff94')
        self.assertNotIn('--conformers-override', calibration)
        self.assertNotIn('--engine-command', calibration)
        self.assertFalse(any('prepare-native' in value or value in ('bash', 'env', 'cmd.exe') for call in calls for value in call))
        self.assertEqual((output / '02_experimental_pose/crystal_ligand.pdb').read_text(), self.ligand + '\nEND\n')
        self.assertIn('user_reviewed_retained_preparation', (output / 'run_manifest.tsv').read_text())

    def test_changed_sealed_input_fails_before_any_output_or_search(self):
        args = parse_args(self.argv)
        self.source.write_text('changed')
        with self.assertRaisesRegex(ValueError, 'changed or is missing'):
            run_reviewed_control(args, runner=lambda c: self.fail('A changed input launched a child'))
        self.assertFalse(args.out.exists())

    def test_changed_record_or_engine_is_not_accepted(self):
        args = parse_args(self.argv)
        args.engine = 'qvinaw'
        with self.assertRaisesRegex(ValueError, 'engine differs'):
            run_reviewed_control(args)
        self.assertFalse(args.out.exists())
        args.engine = 'vina'; self.record.write_text('{}')
        with self.assertRaisesRegex(ValueError, 'record changed'):
            run_reviewed_control(args)
        self.assertFalse(args.out.exists())

    def test_existing_output_is_preserved(self):
        args = parse_args(self.argv)
        args.out.mkdir(); sentinel = args.out / 'completed'; sentinel.write_bytes(b'preserve')
        with self.assertRaises(FileExistsError):
            run_reviewed_control(args)
        self.assertEqual(sentinel.read_bytes(), b'preserve')

    def test_ambiguous_ligand_is_not_merged_and_missing_exact_instance_is_not_substituted(self):
        self.source.write_text(self.ligand[:16] + 'A' + self.ligand[17:] + '\n')
        with self.assertRaisesRegex(ValueError, 'alternate-location'):
            selected_ligand_lines(self.source, 'LIG:A:101')
        with self.assertRaisesRegex(ValueError, 'missing'):
            selected_ligand_lines(self.source, 'LIG:B:101')

    def test_unreviewed_interactive_and_legacy_paths_are_not_inferred(self):
        for extra in (['--legacy-single-conformer'], ['--infer-ligand-chemistry'], ['--force-ligand']):
            with self.assertRaises(SystemExit):
                parse_args(self.argv + extra)


if __name__ == '__main__':
    unittest.main()
