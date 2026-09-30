import hashlib
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest import mock

from docking_universal.services.meeko_template_bridge import (
    ccd_network_disclosure,
    download_ccd_components,
    generate_reviewed_polymer_templates,
)


CCD_CSO = b"""data_CSO
_chem_comp.id CSO
_chem_comp.name 'S-HYDROXYCYSTEINE'
_chem_comp.type 'L-PEPTIDE LINKING'
_chem_comp.mon_nstd_parent_comp_id CYS
_chem_comp.pdbx_formal_charge 0
loop_
_chem_comp_atom.comp_id
_chem_comp_atom.atom_id
_chem_comp_atom.type_symbol
_chem_comp_atom.charge
_chem_comp_atom.pdbx_leaving_atom_flag
CSO N N 0 N
CSO CA C 0 N
CSO CB C 0 N
CSO SG S 0 N
CSO C C 0 N
CSO O O 0 N
CSO OXT O 0 Y
CSO OD O 0 N
CSO H H 0 N
CSO H2 H 0 Y
CSO HA H 0 N
CSO HB2 H 0 N
CSO HB3 H 0 N
CSO HXT H 0 Y
CSO HD H 0 N
loop_
_chem_comp_bond.comp_id
_chem_comp_bond.atom_id_1
_chem_comp_bond.atom_id_2
_chem_comp_bond.value_order
CSO N CA SING
CSO N H SING
CSO N H2 SING
CSO CA CB SING
CSO CA C SING
CSO CA HA SING
CSO CB SG SING
CSO CB HB2 SING
CSO CB HB3 SING
CSO SG OD SING
CSO C O DOUB
CSO C OXT SING
CSO OXT HXT SING
CSO OD HD SING
"""

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


class MeekoTemplateBridgeTests(unittest.TestCase):
    def _component_inputs(self, root: Path, ccd_payload: bytes = CCD_CSO):
        geostd = root / "geostd"
        (geostd / "c").mkdir(parents=True)
        (geostd / "c" / "data_CSO.cif").write_bytes(GEOSTD_CSO)
        ccd = root / "ccd"
        ccd.mkdir()
        (ccd / "CSO.cif").write_bytes(ccd_payload)
        return geostd, ccd

    def test_ccd_disclosure_is_exact_and_refuses_unapproved_download(self):
        disclosure = ccd_network_disclosure(["cso"])
        self.assertEqual(disclosure["component_ids"], ["CSO"])
        self.assertEqual(disclosure["request_urls"], [
            "https://files.rcsb.org/ligands/download/CSO.cif",
        ])
        self.assertTrue(any("Receptor coordinates" in item for item in disclosure["not_shared"]))
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(PermissionError, "explicit approval"):
                download_ccd_components(["CSO"], temporary, approved=False)

    def test_approved_ccd_is_cached_with_checksum(self):
        with tempfile.TemporaryDirectory() as temporary:
            record = download_ccd_components(
                ["CSO"], temporary, approved=True,
                opener=lambda _request, timeout: _Response(CCD_CSO),
            )
            self.assertEqual(
                record["downloads"][0]["sha256"], hashlib.sha256(CCD_CSO).hexdigest(),
            )
            self.assertEqual((Path(temporary) / "CSO.cif").read_bytes(), CCD_CSO)

    def test_cso_generates_validated_internal_and_terminal_templates(self):
        try:
            import meeko  # noqa: F401
        except ImportError:
            self.skipTest("Meeko is required for template-generation validation")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            geostd, ccd = self._component_inputs(root)
            output = root / "templates.json"
            audit = root / "audit.json"
            with mock.patch(
                "docking_universal.services.meeko_template_bridge.installed_meeko_missing_components",
                return_value=("CSO",),
            ):
                record = generate_reviewed_polymer_templates(
                    ["CSO"], geostd_library=geostd, ccd_cache=ccd,
                    output_json=output, audit_json=audit,
                )
            templates = json.loads(output.read_text())
            self.assertEqual(set(templates["ambiguous"]["CSO"]), {"CSO", "CSO_N", "CSO_C"})
            self.assertEqual(
                set(templates["residue_templates"]["CSO"]["link_labels"].values()),
                {"N-term", "C-term"},
            )
            self.assertEqual(record["status"], "review_required")
            self.assertEqual(record["components"][0]["parent_component_id"], "CYS")
            self.assertEqual(record["components"][0]["ccd_formal_charge"], 0)
            self.assertEqual(record["components"][0]["embedded_template_formal_charge"], 0)
            self.assertEqual(json.loads(audit.read_text())["template_sha256"], record["template_sha256"])

    def test_generation_rejects_non_peptide_component_classification(self):
        try:
            import meeko  # noqa: F401
        except ImportError:
            self.skipTest("Meeko is required for template-generation validation")
        payload = CCD_CSO.replace(b"'L-PEPTIDE LINKING'", b"NON-POLYMER")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            geostd, ccd = self._component_inputs(root, payload)
            with mock.patch(
                "docking_universal.services.meeko_template_bridge.installed_meeko_missing_components",
                return_value=("CSO",),
            ):
                with self.assertRaisesRegex(ValueError, "limited to peptide-linking PTMs"):
                    generate_reviewed_polymer_templates(
                        ["CSO"], geostd_library=geostd, ccd_cache=ccd,
                        output_json=root / "templates.json", audit_json=root / "audit.json",
                    )

    def test_generation_rejects_a_changed_internal_formal_charge(self):
        try:
            import meeko  # noqa: F401
        except ImportError:
            self.skipTest("Meeko is required for template-generation validation")
        payload = CCD_CSO.replace(b"_chem_comp.pdbx_formal_charge 0", b"_chem_comp.pdbx_formal_charge 1")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            geostd, ccd = self._component_inputs(root, payload)
            with mock.patch(
                "docking_universal.services.meeko_template_bridge.installed_meeko_missing_components",
                return_value=("CSO",),
            ):
                with self.assertRaisesRegex(ValueError, "formal charge changed"):
                    generate_reviewed_polymer_templates(
                        ["CSO"], geostd_library=geostd, ccd_cache=ccd,
                        output_json=root / "templates.json", audit_json=root / "audit.json",
                    )


if __name__ == "__main__":
    unittest.main()
