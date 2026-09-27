import json
import tempfile
import unittest
from pathlib import Path

from docking_universal.services.structure_input import normalize_structure_input


MMCIF = """data_TEST
loop_
_atom_site.group_PDB
_atom_site.id
_atom_site.type_symbol
_atom_site.label_atom_id
_atom_site.label_alt_id
_atom_site.label_comp_id
_atom_site.label_asym_id
_atom_site.label_entity_id
_atom_site.label_seq_id
_atom_site.pdbx_PDB_ins_code
_atom_site.Cartn_x
_atom_site.Cartn_y
_atom_site.Cartn_z
_atom_site.occupancy
_atom_site.B_iso_or_equiv
_atom_site.pdbx_formal_charge
_atom_site.auth_seq_id
_atom_site.auth_comp_id
_atom_site.auth_asym_id
_atom_site.auth_atom_id
_atom_site.pdbx_PDB_model_num
ATOM 1 C CA . ALA A 1 1 ? 0 0 0 1 10 ? 1 ALA A CA 1
HETATM 2 C C1 . LIG B 2 . ? 1 1 1 1 20 ? 401 LIG B C1 1
loop_
_pdbx_struct_assembly.id
_pdbx_struct_assembly.details
_pdbx_struct_assembly.oligomeric_details
_pdbx_struct_assembly.oligomeric_count
1 'author_defined_assembly' monomeric 1
loop_
_pdbx_struct_assembly_gen.assembly_id
_pdbx_struct_assembly_gen.oper_expression
_pdbx_struct_assembly_gen.asym_id_list
1 1 A
"""


class StructureInputTests(unittest.TestCase):
    def test_mmcif_is_retained_and_pdb_is_explicit_derivative(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "entry.cif"
            source.write_text(MMCIF)
            result = normalize_structure_input(source, root / "normalized")
            self.assertEqual(result.source_path.read_bytes(), source.read_bytes())
            self.assertNotEqual(result.source_path, source.resolve())
            self.assertEqual(result.engine_pdb_path.name, "entry.pdb")
            self.assertEqual(result.source_format, "mmcif")
            self.assertTrue(result.derived_for_legacy_engine)
            self.assertTrue(result.engine_pdb_path.is_file())
            self.assertEqual(result.assemblies[0]["oligomeric_details"], "monomeric")
            metadata = json.loads(result.metadata_path.read_text())
            self.assertEqual(metadata["source_path"], str(result.source_path))
            self.assertIn("do not establish why", metadata["interpretation_limit"])
            ligand = metadata["deposited_metadata"]["deposited_hetero_atoms"][0]
            self.assertEqual(ligand["label_comp_id"], "LIG")
            self.assertEqual(ligand["occupancy"], "1")

    def test_pdb_remains_its_own_engine_input(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "entry.pdb"
            source.write_text(
                "ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 10.00           C\n"
            )
            result = normalize_structure_input(source, root / "normalized")
            self.assertEqual(result.engine_pdb_path, source.resolve())
            self.assertFalse(result.derived_for_legacy_engine)


if __name__ == "__main__":
    unittest.main()
