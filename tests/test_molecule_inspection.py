from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from docking_universal.services.molecule_inspection import (
    input_molecules, library_molecules, molecule_for_entry, drawing_for_entry, compound_3d_block,
)


def component_fixture(root, smiles='CCO'):
    import gemmi
    from rdkit import Chem
    molecule = Chem.AddHs(Chem.MolFromSmiles(smiles))
    molecule.SetProp('_Name', 'fixture')
    structure = gemmi.Structure()
    model = gemmi.Model('1')
    for chain_id, number in (('A', 101), ('B', 102)):
        chain = gemmi.Chain(chain_id)
        residue = gemmi.Residue()
        residue.name, residue.het_flag, residue.seqid = 'LIG', 'H', gemmi.SeqId(number, ' ')
        for index, rd_atom in enumerate(molecule.GetAtoms()):
            if rd_atom.GetAtomicNum() == 1:
                continue
            atom = gemmi.Atom()
            atom.name = 'A' + str(index)
            atom.element = gemmi.Element(rd_atom.GetSymbol())
            atom.pos = gemmi.Position(index * 1.4, 1, 1)
            residue.add_atom(atom)
        chain.add_residue(residue)
        model.add_chain(chain)
    structure.add_model(model)
    structure.setup_entities()
    block = structure.make_mmcif_document().sole_block()
    atoms = block.init_loop('_chem_comp_atom.', ['comp_id', 'atom_id', 'type_symbol', 'charge', 'pdbx_stereo_config'])
    for index, atom in enumerate(molecule.GetAtoms()):
        atoms.add_row(['LIG', 'A' + str(index), atom.GetSymbol(), str(atom.GetFormalCharge()),
                       atom.GetProp('_CIPCode') if atom.HasProp('_CIPCode') else 'N'])
    bonds = block.init_loop('_chem_comp_bond.', ['comp_id', 'atom_id_1', 'atom_id_2', 'value_order'])
    orders = {1.0: 'sing', 2.0: 'doub', 3.0: 'trip', 1.5: 'arom'}
    for bond in molecule.GetBonds():
        bonds.add_row(['LIG', 'A' + str(bond.GetBeginAtomIdx()), 'A' + str(bond.GetEndAtomIdx()), orders[bond.GetBondTypeAsDouble()]])
    path = Path(root) / 'input.cif'
    path.write_text(block.as_string())
    return path, molecule


class MoleculeInspectionTests(unittest.TestCase):
    def test_supporting_display_filter_preserves_unknowns_and_exact_depositor_interest(self):
        import gemmi
        with TemporaryDirectory() as root:
            source, _ = component_fixture(root)
            structure = gemmi.read_structure(str(source))
            for chain in structure[0]:
                chain[0].name = 'BOG'
            block = structure.make_mmcif_document().sole_block()
            features = block.init_loop('_pdbx_entity_instance_feature.',
                                       ['ordinal', 'comp_id', 'auth_asym_id', 'auth_seq_num', 'feature_type'])
            features.add_row(['1', 'BOG', 'B', '102', "'SUBJECT OF INVESTIGATION'"])
            source.write_text(block.as_string())
            entries = input_molecules(source)[1:]
            self.assertTrue(entries[0]['supporting_component'])
            self.assertIn('additive or detergent', entries[0]['display_reason'])
            self.assertFalse(entries[1]['supporting_component'])
            self.assertIn('SUBJECT OF INVESTIGATION', entries[1]['display_reason'])
            self.assertIn('not specified', entries[1]['display_reason'])

    def test_known_additives_sugars_cofactors_and_ions_are_only_display_classifications(self):
        import gemmi
        with TemporaryDirectory() as root:
            source, _ = component_fixture(root)
            structure = gemmi.read_structure(str(source))
            chain = structure[0][0]
            for i, code in enumerate(('NH4', 'BOG', 'NAG', 'COH', 'ZN', 'XYZ')):
                residue = chain[0].clone()
                residue.name = code
                residue.seqid = gemmi.SeqId(200 + i, ' ')
                chain.add_residue(residue)
            source.write_text(structure.make_mmcif_document().as_string())
            before = source.read_bytes()
            entries = input_molecules(source)[1:]
            self.assertTrue(all(entry['supporting_component'] for entry in entries if entry['resname'] in {'NH4', 'BOG', 'NAG', 'COH', 'ZN'}))
            self.assertTrue(all(not entry['supporting_component'] for entry in entries if entry['resname'] in {'LIG', 'XYZ'}))
            self.assertEqual(source.read_bytes(), before)

    def test_local_components_keep_instance_identity_and_use_declared_connectivity(self):
        from rdkit import Chem
        with TemporaryDirectory() as root:
            source, expected = component_fixture(root)
            before = source.read_bytes()
            entries = input_molecules(source)
            self.assertEqual(len(entries), 3)
            self.assertEqual([(e['chain'], e['resi']) for e in entries[1:]], [('A', '101'), ('B', '102')])
            molecule = molecule_for_entry(entries[1])
            self.assertEqual(Chem.MolToSmiles(Chem.RemoveHs(molecule)), Chem.MolToSmiles(Chem.RemoveHs(expected)))
            png, basis = drawing_for_entry(entries[2])
            self.assertTrue(png.startswith(b'\x89PNG'))
            self.assertIn('loaded mmCIF', basis)
            self.assertEqual(source.read_bytes(), before)
            source.write_text('changed source')
            with self.assertRaisesRegex(ValueError, 'changed'):
                drawing_for_entry(entries[1])

    def test_declared_tetrahedral_stereochemistry_is_preserved(self):
        from rdkit import Chem
        with TemporaryDirectory() as root:
            source, expected = component_fixture(root, 'C[C@H](O)C(=O)O')
            molecule = molecule_for_entry(input_molecules(source)[1])
            self.assertEqual(Chem.MolToSmiles(Chem.RemoveHs(molecule)), Chem.MolToSmiles(Chem.RemoveHs(expected)))

    def test_missing_definition_and_whole_receptor_do_not_get_guessed_drawings(self):
        import gemmi
        with TemporaryDirectory() as root:
            source, _ = component_fixture(root)
            with self.assertRaisesRegex(ValueError, 'individual component'):
                drawing_for_entry(input_molecules(source)[0])
            block = gemmi.cif.read_file(str(source)).sole_block()
            block.find_mmcif_category('_chem_comp_atom.').erase()
            source.write_text(block.as_string())
            with self.assertRaisesRegex(ValueError, 'No local component'):
                drawing_for_entry(input_molecules(source)[1])

    def test_loaded_compounds_share_identity_for_2d_and_supplied_3d_without_source_changes(self):
        from rdkit import Chem
        from rdkit.Chem import AllChem
        from docking_universal.services.ligand_library import inspect_ligand_library
        with TemporaryDirectory() as root:
            path = Path(root) / 'compounds.sdf'
            molecule = Chem.AddHs(Chem.MolFromSmiles('CCO'))
            self.assertEqual(AllChem.EmbedMolecule(molecule, randomSeed=17), 0)
            molecule.SetProp('_Name', 'local ethanol')
            path.write_text(Chem.MolToMolBlock(molecule) + '\n$$$$\n')
            before = path.read_bytes()
            library = inspect_ligand_library(path)
            entry = library_molecules(library)[0]
            self.assertEqual(entry['record_id'], library['records'][0]['record_id'])
            self.assertTrue(drawing_for_entry(entry)[0].startswith(b'\x89PNG'))
            loaded = Chem.MolFromMolBlock(compound_3d_block(entry), removeHs=False)
            self.assertTrue(loaded.GetConformer().Is3D())
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaisesRegex(ValueError, 'no supplied 3D'):
                compound_3d_block({'origin': 'smiles', 'smiles': 'CCO'})
