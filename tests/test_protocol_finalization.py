import tempfile
import unittest
from pathlib import Path

from docking_universal.protocol_finalization import (
    FinalizationSettings,
    ProtocolFinalizationRequest,
    selected_region_records,
)


class ProtocolFinalizationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.preparation = self.root / "target_receptor_prep"
        receptor = self.preparation / "receptor"
        receptor.mkdir(parents=True)
        self.source = self.root / "target.pdb"
        self.receptor_pdb = receptor / "target.pdb"
        self.receptor_pdbqt = receptor / "target.pdbqt"
        for path in (self.source, self.receptor_pdb, self.receptor_pdbqt):
            path.write_text("ATOM\n")

    def tearDown(self):
        self.temporary.cleanup()

    def box(self, number):
        path = self.preparation / "cavity" / f"target_pocket{number}.conf"
        path.parent.mkdir(exist_ok=True)
        path.write_text(
            f"center_x = {number}\ncenter_y = 2\ncenter_z = 3\n"
            "size_x = 20\nsize_y = 22\nsize_z = 24\n"
        )
        return path

    def test_region_records_preserve_cli_schema_order_and_labels(self):
        boxes = [self.box(2), self.box(1)]
        records = selected_region_records(boxes, [
            {"label": "P1", "path": boxes[1]}, {"label": "P2", "path": boxes[0]},
        ])
        self.assertEqual([item["box_label"] for item in records], ["P2", "P1"])
        self.assertEqual([item["site_number"] for item in records], [1, 2])
        self.assertEqual(records[0]["geometry"]["center_x"], "2")
        self.assertEqual(records[0]["definition_origin"], "user-selected labeled candidate")

    def test_settings_match_stable_protocol_parameter_shape(self):
        values = FinalizationSettings(
            engine="vina", ph=6.8, conformers=4, seed_count=3, base_seed=90,
            exhaustiveness=32, num_modes=12, energy_range=6,
        ).protocol_parameters()
        self.assertEqual(values["seeds"], [90, 91, 92])
        self.assertEqual(values["macrocycle_treatment"], "flexible_meeko")
        self.assertEqual(values["conformers_per_state"], 4)

    def test_request_rejects_changed_approved_box(self):
        box = self.box(1)
        regions = selected_region_records([box], [{"label": "P1", "path": box}])
        request = ProtocolFinalizationRequest(
            "study", "target", self.preparation, self.source,
            self.receptor_pdb, self.receptor_pdbqt, tuple(regions),
            FinalizationSettings(), "approval-1", 4, self.root / "final", True,
        )
        request.validate()
        box.write_text(box.read_text() + "# changed\n")
        with self.assertRaisesRegex(ValueError, "changed or is missing"):
            request.validate()

    def test_request_requires_separate_exploratory_use_approval(self):
        box = self.box(1)
        regions = selected_region_records([box], [{"label": "P1", "path": box}])
        request = ProtocolFinalizationRequest(
            "study", "target", self.preparation, self.source,
            self.receptor_pdb, self.receptor_pdbqt, tuple(regions),
            FinalizationSettings(), "approval-1", 4, self.root / "final", False,
        )
        with self.assertRaisesRegex(ValueError, "explicit approval"):
            request.validate()


if __name__ == "__main__":
    unittest.main()
