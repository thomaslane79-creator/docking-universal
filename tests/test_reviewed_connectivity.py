"""Real RDKit graph checks on synthetic fixtures; no target geometry changes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock

from rdkit import Chem
from docking_universal.services.reviewed_connectivity import remove_exact_edges, reader_adapter, interresidue_adapter, validate_review, invoke_strict_main, sha, SCHEMA, READER_SHA256
from tests.test_receptor_model_review import atom


class ConnectivityGraphTests(unittest.TestCase):
    def setUp(self):
        mol = Chem.AddHs(Chem.MolFromSmiles('CC(C)C.CN'))
        conf = Chem.Conformer(mol.GetNumAtoms())
        for i in range(mol.GetNumAtoms()):
            conf.SetAtomPosition(i, (i * 2., 0., 0.))
        mol.AddConformer(conf)
        self.mol = Chem.RWMol(mol); self.mol.AddBond(1, 5, Chem.BondType.SINGLE)
        self.names = {i: ('CG' if i == 1 else 'NE' if i == 5 else 'X' + str(i)) for i in range(mol.GetNumAtoms())}

    def test_only_exact_edge_removed_with_identical_atoms_and_coordinates(self):
        before = self.mol.GetConformer().GetPositions().copy()
        fixed = remove_exact_edges(self.mol, self.names, [['CG', 'NE']])
        self.assertEqual(fixed.GetNumAtoms(), self.mol.GetNumAtoms())
        self.assertEqual(fixed.GetNumBonds(), self.mol.GetNumBonds() - 1)
        self.assertTrue((before == fixed.GetConformer().GetPositions()).all())
        self.assertIsNone(fixed.GetBondBetweenAtoms(1, 5))
        self.assertIsNotNone(self.mol.GetBondBetweenAtoms(1, 5))

    def test_unapproved_bad_edge_still_fails_strict_valence(self):
        self.mol.AddBond(1, 4, Chem.BondType.SINGLE)
        with self.assertRaises(Exception):
            remove_exact_edges(self.mol, self.names, [['CG', 'NE']])

    def test_missing_duplicate_or_hydrogen_edge_not_accepted(self):
        hydrogen = next(a.GetIdx() for a in self.mol.GetAtomWithIdx(1).GetNeighbors() if a.GetAtomicNum() == 1)
        for pairs in ([['CG', 'UNKNOWN']], [['CG', 'CG']], [['CG', 'NE'], ['CG', 'NE']], [['CG', self.names[hydrogen]]]):
            with self.subTest(pairs=pairs), self.assertRaises(ValueError):
                remove_exact_edges(self.mol, self.names, pairs)

    def test_unreviewed_residue_uses_original_backend_reader_unchanged(self):
        from types import SimpleNamespace
        original = Mock(return_value='ordinary reader')
        adapter = reader_adapter(original, [dict(resname='ARG', chain='A', number='73', insertion_code='', atom_names=['CG', 'NE'])], set())
        fields = [SimpleNamespace(resname='GLY', chain='B', resnum=2, icode='')]
        self.assertEqual(adapter(fields, None, None), 'ordinary reader')
        original.assert_called_once_with(fields, None, None)

    def test_backend_exit_never_skips_the_following_output_and_edge_checks(self):
        invoke_strict_main(Mock(side_effect=SystemExit(0)))
        for value in (1, 2, 'reader failed'):
            with self.assertRaises(RuntimeError):
                invoke_strict_main(Mock(side_effect=SystemExit(value)))

    def test_interresidue_filter_retains_unreviewed_links_and_all_molecules(self):
        first = dict(resname='GLU', chain='A', number='56', insertion_code='', atom_name='OE2')
        second = dict(resname='TYR', chain='A', number='58', insertion_code='', atom_name='CE2')
        edges = [dict(first=first, second=second), dict(first=first, second=dict(second, atom_name='HE2'))]
        mols = {'A:56': (Chem.MolFromSmiles('OC'), 'GLU'), 'A:58': (Chem.AddHs(Chem.MolFromSmiles('c1ccccc1')), 'TYR')}
        maps = {'A:56': {0: 'OE2', 1: 'CB'}, 'A:58': {0: 'CE2', 6: 'HE2', 1: 'CB'}}
        counts = {k: v[0].GetNumAtoms() for k, v in mols.items()}
        for pair, links, expected in ((('A:56', 'A:58'), [(0, 0), (0, 6), (1, 1)], [(1, 1)]),
                                      (('A:58', 'A:56'), [(0, 0), (6, 0), (1, 1)], [(1, 1)])):
            applied = set(); original = Mock(return_value={pair: links[:]})
            result = interresidue_adapter(original, edges, maps, applied)(mols)
            self.assertEqual(result, {pair: expected})
            self.assertEqual(len(applied), 2)
            self.assertEqual({k: v[0].GetNumAtoms() for k, v in mols.items()}, counts)

    def test_missing_interresidue_link_stops_instead_of_silently_broadening_scope(self):
        edge = dict(first=dict(resname='GLU', chain='A', number='56', insertion_code='', atom_name='OE2'),
                    second=dict(resname='TYR', chain='A', number='58', insertion_code='', atom_name='CE2'))
        with self.assertRaises(ValueError):
            interresidue_adapter(Mock(return_value={}), [edge], {}, set())({})


class ConnectivityReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        data = atom(1, 'CG', 'ARG', 73) + atom(2, 'NE', 'ARG', 73, xyz=(1.5, 0, 0)) + 'END\n'
        files = {}
        for name in ('Target.pdb', 'Target_filtered.pdb', 'Target_reduce2H.pdb', 'reduce2_audit.json', 'reduce2.log'):
            path = self.root / name
            path.write_text(json.dumps({'status': 'compatible', 'coordinate_frame': {'status': 'preserved'}})
                            if name.endswith('.json') else data if name.endswith('.pdb') else 'fixture log\n')
            files[name] = dict(path=str(path), sha256=sha(path))
        self.review = dict(schema_name=SCHEMA, schema_version=1, model_sha256='a' * 64, backend_input='Target_reduce2H.pdb',
                          retained_stage_files=files, authority_sha256='b' * 64, meeko_reader_sha256=READER_SHA256,
                          edges=[dict(resname='ARG', chain='A', number='73', insertion_code='', atom_names=['CG', 'NE'])])
        self.path = self.root / 'review.json'

    def validate(self):
        self.path.write_text(json.dumps(self.review))
        return validate_review(self.path, 'a' * 64)

    def test_review_binds_saved_stage_exact_edges_authority_and_model(self):
        _, change = self.validate()
        self.assertEqual(change['coordinate_changes'], 0)
        self.assertEqual(change['atoms_removed'], 0)
        self.assertTrue(change['strict_valence_checks_retained'])
        self.assertEqual(change['review_sha256'], sha(self.path))

    def test_changed_stage_wrong_model_or_different_reader_refused(self):
        self.validate()
        with self.assertRaises(ValueError):
            validate_review(self.path, 'c' * 64)
        self.review['meeko_reader_sha256'] = 'c' * 64
        with self.assertRaises(ValueError):
            self.validate()
        self.review['meeko_reader_sha256'] = READER_SHA256
        (self.root / 'Target_reduce2H.pdb').write_text('changed\n')
        with self.assertRaises(ValueError):
            self.validate()

    def test_declared_canonical_bond_backbone_or_duplicate_edge_refused(self):
        original = self.review['edges'][0]
        for edges in ([dict(original, atom_names=['CG', 'CD'])], [dict(original, atom_names=['CA', 'CG'])],
                      [original, original]):
            self.review['edges'] = edges
            with self.assertRaises(ValueError):
                self.validate()

    def test_known_standard_bond_cannot_be_rejected_even_if_both_atoms_present(self):
        for name in ('Target.pdb', 'Target_filtered.pdb', 'Target_reduce2H.pdb'):
            path = self.root / name
            path.write_text(path.read_text().replace('END\n', atom(3, 'CD', 'ARG', 73, xyz=(3, 0, 0)) + 'END\n'))
            self.review['retained_stage_files'][name]['sha256'] = sha(path)
        self.review['edges'][0]['atom_names'] = ['CG', 'CD']
        with self.assertRaisesRegex(ValueError, 'declared standard-residue bond'):
            self.validate()

    def test_portable_warning_requires_exact_history_and_never_allows_valence_waiver(self):
        from docking_universal.services.receptor_model_history import SCHEMA as HISTORY, normalize_preparation
        _, change = self.validate()
        change.update(actor='test scientist', rationale='Explicit synthetic connectivity review')
        history = dict(schema_name=HISTORY, schema_version=1, original_input_sha256='a' * 64,
                       model_input_sha256='b' * 64, prepared_receptor_sha256='c' * 64, changes=[change])
        warning = normalize_preparation({'model_change_history': history})['receptor_modification_warning']
        self.assertIn('connectivity override', warning['summary'])
        self.assertTrue(warning['persistent_warning_required'])
        change['strict_valence_checks_retained'] = False
        with self.assertRaises(ValueError):
            normalize_preparation({'model_change_history': history})

    def test_interresidue_review_requires_complete_scope_and_never_removes_declared_bonds(self):
        self.review['inter_residue_edges'] = []
        with self.assertRaises(ValueError):
            self.validate()
        self.review['interresidue_reader_sha256'] = 'c' * 64
        self.review['inter_residue_edges'] = [dict(
            first=dict(resname='ARG', chain='A', number='73', insertion_code='', atom_name='CG'),
            second=dict(resname='TYR', chain='A', number='58', insertion_code='', atom_name='CE2'))]
        for name in ('Target.pdb', 'Target_filtered.pdb', 'Target_reduce2H.pdb'):
            path = self.root / name
            path.write_text(path.read_text().replace('END\n', atom(10, 'CE2', 'TYR', 58, xyz=(2, 2, 2)) + 'CONECT    1   10\nEND\n'))
            self.review['retained_stage_files'][name]['sha256'] = sha(path)
        with self.assertRaisesRegex(ValueError, 'declared CONECT'):
            self.validate()


if __name__ == '__main__':
    unittest.main()
