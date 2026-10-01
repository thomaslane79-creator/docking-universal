import hashlib
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

from docking_universal.services.geostd_components import (
    GEOSTD_REVISION,
    bundled_minimal_library,
    download_components,
    missing_components,
    modified_polymer_component_ids,
    network_disclosure,
    reduce2_required_component_ids,
    retained_component_ids_from_pdb,
)


GEOSTD_CSO = b"""data_comp_list
_chem_comp.id CSO
data_comp_CSO
loop_
_chem_comp_tree.comp_id
_chem_comp_tree.atom_id
CSO N
"""


class _Response(BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


class GeoStdComponentTests(unittest.TestCase):
    def test_bundled_core_contains_standard_protein_restraints(self):
        root = bundled_minimal_library()
        self.assertTrue((root / "list" / "mon_lib_list.cif").is_file())
        self.assertEqual(missing_components(root, ["ALA", "HIS", "CSO"]), ("CSO",))

    def test_disclosure_states_exact_shared_and_unshared_data(self):
        record = network_disclosure(["cso"])
        self.assertEqual(record["component_ids"], ["CSO"])
        self.assertEqual(record["revision"], GEOSTD_REVISION)
        self.assertIn("CSO", record["request_urls"][0])
        self.assertTrue(any("IP address" in value for value in record["shared"]))
        self.assertTrue(any("Receptor coordinates" in value for value in record["not_shared"]))

    def test_network_is_refused_without_explicit_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PermissionError, "explicit approval"):
                download_components(["CSO"], Path(temporary) / "geostd", approved=False)

    def test_approved_component_is_validated_cached_and_audited(self):
        calls = []

        def opener(request, timeout):
            calls.append((request.full_url, timeout))
            return _Response(GEOSTD_CSO)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "geostd"
            record = download_components(["CSO"], root, approved=True, opener=opener)
            output = root / "c" / "data_CSO.cif"
            self.assertEqual(output.read_bytes(), GEOSTD_CSO)
            self.assertEqual(len(calls), 1)
            self.assertEqual(
                record["downloads"][0]["sha256"], hashlib.sha256(GEOSTD_CSO).hexdigest(),
            )
            retained = json.loads(
                (root / "docking-universal-component-provenance.json").read_text()
            )
            self.assertEqual(retained["disclosure"]["component_ids"], ["CSO"])

    def test_ordinary_bound_ligand_is_not_requested_but_modres_is(self):
        pdb = """MODRES 1ABC CSO A   2  CYS  S-HYDROXYCYSTEINE
ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 10.00           C
HETATM    2  CA  CSO A   2       1.000   0.000   0.000  1.00 10.00           C
HETATM    3  C1  LIG A 100       2.000   0.000   0.000  1.00 10.00           C
HETATM    4 ZN   ZN  A 200       3.000   0.000   0.000  1.00 10.00          ZN
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.pdb"
            path.write_text(pdb)
            self.assertEqual(retained_component_ids_from_pdb(path), ("ALA", "CSO", "ZN"))
            self.assertEqual(modified_polymer_component_ids(path), ("CSO",))
            self.assertEqual(reduce2_required_component_ids(path), ("ALA", "CSO"))

    def test_linked_nonpolymer_is_retained_but_not_required_by_reduce2(self):
        pdb = """LINK         FE  COH A 500                 NE2 HIS A  90
ATOM      1  CA  ALA A   1       0.000   0.000   0.000  1.00 10.00           C
ATOM      2  CA  HIS A  90       1.000   0.000   0.000  1.00 10.00           C
HETATM    3 FE   COH A 500       2.000   0.000   0.000  1.00 10.00          FE
HETATM    4  C1  COH A 500       3.000   0.000   0.000  1.00 10.00           C
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cofactor.pdb"
            path.write_text(pdb)
            self.assertIn("COH", retained_component_ids_from_pdb(path))
            self.assertEqual(reduce2_required_component_ids(path), ("ALA", "HIS"))

    def test_mmcif_nonpolymer_is_not_required_by_reduce2(self):
        mmcif = """data_test
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
ATOM 2 C CA . HIS A 1 2 ? 1 0 0 1 10 ? 2 HIS A CA 1
HETATM 3 FE FE . COH B 2 . ? 2 0 0 1 10 ? 500 COH A FE 1
"""
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "cofactor.cif"
            path.write_text(mmcif)
            self.assertEqual(reduce2_required_component_ids(path), ("ALA", "HIS"))


if __name__ == "__main__":
    unittest.main()
