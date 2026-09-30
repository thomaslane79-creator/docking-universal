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


if __name__ == "__main__":
    unittest.main()
