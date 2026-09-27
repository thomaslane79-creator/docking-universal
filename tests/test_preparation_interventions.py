import json
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from docking_universal.services.preparation_interventions import (
    classify_histidine_affected_boxes,
    decision_from_intervention,
    neutral_sensitivity_assignments,
    template_assignments,
    write_intervention_record,
)


class PreparationInterventionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.diagnosis = self.root / "diagnosis.txt"
        self.diagnosis.write_text(
            "Receptor preparation failure category: Ambiguous histidine protonation\n"
            "Why this matters: The local environment does not identify one tautomer.\n"
            "Recommended next step: Review nearby hydrogen bonds.\n"
        )
        self.receptor = self.root / "filtered.pdb"
        self.receptor.write_text(
            "ATOM      1  ND1 HIS A  57       0.000   0.000   0.000  1.00 12.00           N\n"
            "ATOM      2  NE2 HIS A  57       2.000   0.000   0.000  1.00 13.00           N\n"
            "ATOM      3  ND1 HIS A  90       8.000   0.000   0.000  1.00 14.00           N\n"
            "ATOM      4  NE2 HIS A  90      10.000   0.000   0.000  1.00 15.00           N\n"
        )

    def tearDown(self):
        self.temporary.cleanup()

    def test_histidine_record_becomes_explicit_nonautomatable_decision(self):
        output = self.root / "intervention.json"
        record = write_intervention_record(
            self.diagnosis, self.receptor, output, ambiguous_histidine="A:57",
        )
        decision = decision_from_intervention(output, "decision-his57")

        self.assertEqual(record["kind"], "histidine_template")
        self.assertEqual(record["eligible_histidines"], ["A:57", "A:90"])
        self.assertEqual(decision.kind, "select_histidine_template")
        self.assertIn("standard amino acid", decision.detected)
        self.assertIn("No state has been assigned yet", decision.detected)
        self.assertTrue(decision.changes_molecular_model)
        self.assertTrue(decision.requires_explicit_user)
        self.assertIn("HIE_CURRENT", {option.value for option in decision.options})
        self.assertIn("TEST_NEUTRAL_CURRENT", {option.value for option in decision.options})
        self.assertIn("HIP_ALL", {option.value for option in decision.options})
        self.assertIn("STOP", {option.value for option in decision.options})
        self.assertIn("Check metal coordination first", decision.presentation["guided"])
        self.assertIn("HIE has H on NE2", decision.presentation["guided"])
        self.assertIn("Stop when the evidence conflicts", decision.presentation["guided"])

    def test_selection_translates_to_exact_meeko_assignments(self):
        record = {
            "residue": "A:57",
            "eligible_histidines": ["A:57", "A:90"],
        }
        self.assertEqual(template_assignments(record, "HID_CURRENT"), "A:57=HID")
        self.assertEqual(template_assignments(record, "HIE_ALL"), "A:57=HIE,A:90=HIE")
        self.assertEqual(template_assignments(record, "STOP"), "")

    def test_neutral_sensitivity_creates_two_explicit_current_residue_assignments(self):
        record = {"residue": "A:57", "eligible_histidines": ["A:57", "A:90"]}

        self.assertEqual(
            neutral_sensitivity_assignments(record, "TEST_NEUTRAL_CURRENT"),
            {"HIE": "A:57=HIE", "HID": "A:57=HID"},
        )

    def test_selected_boxes_are_classified_from_histidine_coordinates_with_margin(self):
        receptor = self.root / "prepared.pdb"
        receptor.write_text(
            "ATOM      1  ND1 HIE A  57       9.000   0.000   0.000  1.00 12.00           N\n"
        )
        artifacts = [
            SimpleNamespace(kind="docking_box", metadata={
                "label": "P1", "geometry": {
                    "center_x": 0, "center_y": 0, "center_z": 0,
                    "size_x": 10, "size_y": 10, "size_z": 10,
                },
            }),
            SimpleNamespace(kind="docking_box", metadata={
                "label": "P2", "geometry": {
                    "center_x": 30, "center_y": 0, "center_z": 0,
                    "size_x": 10, "size_y": 10, "size_z": 10,
                },
            }),
        ]

        result = classify_histidine_affected_boxes(
            receptor, "A:57", ("P1", "P2"), artifacts,
        )

        self.assertEqual(result["affected_boxes"], ["P1"])
        self.assertEqual(result["unaffected_boxes"], ["P2"])
        self.assertEqual(result["margin_angstrom"], 4.0)

    def test_nonhistidine_failure_remains_failure_closed(self):
        self.diagnosis.write_text(
            "Receptor preparation failure category: Unsupported heme or cofactor template\n"
            "Why this matters: Cofactor chemistry requires specialized treatment.\n"
        )
        output = self.root / "intervention.json"
        record = write_intervention_record(self.diagnosis, self.receptor, output)

        self.assertEqual(record["kind"], "review_required")
        self.assertIsNone(decision_from_intervention(output, "decision-cofactor"))
        self.assertEqual(json.loads(output.read_text())["schema_version"], 1)

    @unittest.skipUnless(importlib.util.find_spec("gemmi"), "gemmi is required for mmCIF evidence")
    def test_mmcif_context_is_retained_as_evidence_not_an_automatic_assignment(self):
        source = self.root / "deposited.cif"
        source.write_text("""data_TEST
_exptl.method 'X-RAY DIFFRACTION'
_exptl_crystal_grow.pH 6.5
_refine.ls_d_res_high 1.80
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
ATOM 1 N ND1 . HIS A 1 57 ? 0 0 0 1 12 ? 57 HIS A ND1 1
ATOM 2 N NE2 . HIS A 1 57 ? 2 0 0 1 13 ? 57 HIS A NE2 1
ATOM 3 H HD1 . HIS A 1 57 ? 0 1 0 1 14 ? 57 HIS A HD1 1
HETATM 4 O O1 . GOL B 2 . ? 2 2 0 0.8 20 ? 301 GOL B O1 1
""")
        output = self.root / "intervention.json"
        record = write_intervention_record(
            self.diagnosis, self.receptor, output,
            ambiguous_histidine="A:57", source_mmcif=source,
        )
        evidence = record["deposited_mmcif_evidence"]

        self.assertEqual(evidence["status"], "available")
        self.assertEqual(evidence["crystallization_ph"], ["6.5"])
        self.assertEqual(
            evidence["explicit_ring_hydrogens_or_deuteriums"][0]["atom_name"], "HD1",
        )
        self.assertEqual(evidence["nearby_atoms_within_4A"][0]["residue_name"], "GOL")
        self.assertIn("do not", evidence["interpretation"])


if __name__ == "__main__":
    unittest.main()
